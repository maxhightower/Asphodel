"""Pedestrian and vehicle controllers (ASPHODEL_EMBODIED_MOBILITY_V1 §6, §10, §12).

Synthetic geometry only: a path small enough that every metre is checkable by
hand. The claims under test are the believability claims — walk to the end and
stop there, yield to a moving car, never be pushed forward by physics; drive up
to the limit, brake for the corner, stop at the destination, keep a following
gap, yield at a junction and break the deadlock, stop at a closed road.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.embodied.pathing import PhysicalPath
from asphodel.embodied.pedestrian import (PHYSICS_LEASH, WALK_SPEED, YIELD_DISTANCE,
                                          PedestrianController)
from asphodel.embodied.vehicle_control import (OtherVehicle, VehicleController,
                                               VehicleParams, junctions_on_path)
from asphodel.mobility import Mode, MobilityGraph, RoadSegment


# --------------------------------------------------------------------------- #
# pedestrian
# --------------------------------------------------------------------------- #
def _straight_walk(length: float = 100.0) -> PhysicalPath:
    return PhysicalPath([(0.0, 0.0), (length, 0.0)],
                        segments=[("s_walk", 0.0, length)], mode=Mode.FOOT)


def test_pedestrian_follows_the_path_and_stops_at_the_end():
    path = _straight_walk(100.0)
    c = PedestrianController(path)
    steps = 0
    while not c.arrived and steps < 1000:
        c.advance(1.0)
        steps += 1
        assert c.dist <= path.length + 1e-9
        assert math.isclose(c.position[1], 0.0, abs_tol=1e-9)
    assert c.arrived
    assert steps == math.ceil(100.0 / WALK_SPEED)
    # exactly at the destination anchor, standing still
    assert c.dist == pytest.approx(path.length)
    assert c.position == pytest.approx(path.points[-1])
    assert c.destination == pytest.approx(path.points[-1])
    assert c.distance_walked == pytest.approx(100.0)
    c.advance(1.0)
    assert c.speed == 0.0 and c.dist == pytest.approx(path.length)


def test_pedestrian_yields_to_a_moving_vehicle_ahead():
    path = _straight_walk(100.0)
    c = PedestrianController(path)
    for _ in range(10):
        c.advance(1.0)
    at = c.dist
    car_ahead = [((at + YIELD_DISTANCE - 1.0, 0.0), 6.0)]
    for _ in range(5):
        c.advance(1.0, car_ahead)
    assert c.yielding is True
    assert c.speed == 0.0
    assert c.dist == pytest.approx(at), "a yielding pedestrian must not advance"
    assert c.blocked_s == pytest.approx(5.0)

    # a *parked* car is not a reason to stop
    c.advance(1.0, [((at + 2.0, 0.0), 0.0)])
    assert c.yielding is False and c.speed == WALK_SPEED and c.dist > at
    assert c.blocked_s == 0.0

    # neither is a moving car well off the path
    before = c.dist
    c.advance(1.0, [((c.dist + 2.0, 40.0), 9.0)])
    assert c.yielding is False and c.dist > before


def test_pedestrian_reconcile_physical_never_advances_progress():
    path = _straight_walk(100.0)
    c = PedestrianController(path)
    for _ in range(10):
        c.advance(1.0)
    planned = c.dist
    # physics says the body is far AHEAD of the plan: ignored
    c.reconcile_physical((planned + 30.0, 0.0), False, 1.0)
    assert c.dist == pytest.approx(planned)
    # physics says the body is only slightly behind (inside the leash): ignored
    c.reconcile_physical((planned - PHYSICS_LEASH + 0.5, 0.0), False, 1.0)
    assert c.dist == pytest.approx(planned)
    # physics says the body is stuck 10 m back: progress is pulled back
    c.reconcile_physical((planned - 10.0, 0.0), False, 1.0)
    assert c.dist == pytest.approx(planned - 10.0 + PHYSICS_LEASH)
    assert c.dist < planned


def test_pedestrian_blocked_time_accumulates_and_clears():
    path = _straight_walk(100.0)
    c = PedestrianController(path)
    c.advance(1.0)
    at = c.dist
    for i in range(4):
        c.reconcile_physical((at, 0.0), True, 1.0)
        assert c.blocked is True
        assert c.blocked_s == pytest.approx(i + 1.0)
    c.advance(2.0)                       # blocked: still no progress, more time
    assert c.dist == pytest.approx(at) and c.blocked_s == pytest.approx(6.0)
    c.clear_block()
    assert c.blocked is False and c.blocked_s == 0.0
    c.advance(1.0)
    assert c.dist > at
    # a report that is no longer blocked also clears the counter
    c.reconcile_physical(c.position, True, 1.0)
    assert c.blocked_s == pytest.approx(1.0)
    c.reconcile_physical(c.position, False, 1.0)
    assert c.blocked is False and c.blocked_s == 0.0


def test_pedestrian_state_round_trips():
    path = _straight_walk(100.0)
    c = PedestrianController(path)
    for _ in range(7):
        c.advance(1.0)
    other = PedestrianController(path)
    other.restore(c.to_state())
    assert (other.dist, other.speed, other.heading, other.distance_walked) == \
        (c.dist, c.speed, c.heading, c.distance_walked)


# --------------------------------------------------------------------------- #
# vehicle
# --------------------------------------------------------------------------- #
def _drive_graph(road_class: str = "primary") -> MobilityGraph:
    """A --s1(300 m)-- B --s2(300 m)-- C, with a third leg at B (a junction)."""
    g = MobilityGraph()
    for nid, xy in (("A", (0.0, 0.0)), ("B", (300.0, 0.0)),
                    ("C", (300.0, 300.0)), ("D", (300.0, -100.0))):
        g.add_node(nid, xy)
    g.add_segment(RoadSegment("s1", [(0.0, 0.0), (300.0, 0.0)], road_class), "A", "B")
    g.add_segment(RoadSegment("s2", [(300.0, 0.0), (300.0, 300.0)], road_class), "B", "C")
    g.add_segment(RoadSegment("s3", [(300.0, 0.0), (300.0, -100.0)], road_class), "B", "D")
    return g


def _controller(g: MobilityGraph):
    route = g.route("A", "C", Mode.CAR)
    assert route is not None and route.segments == ["s1", "s2"]
    path = PhysicalPath.from_route(g, route)
    assert path.length == pytest.approx(600.0)
    c = VehicleController(path)
    c.junctions = junctions_on_path(g, path)
    return c, path


def _run(c, g, others=None, dt=0.1, limit=6000, until=None):
    t, hist = 0.0, []
    for _ in range(limit):
        c.advance(dt, g, Mode.CAR, list(others or []), "veh:me", t)
        t += dt
        hist.append((round(t, 3), c.dist, c.speed, c.last_reason))
        if until is not None and until(c, t):
            break
        if until is None and c.arrived:
            break
    return t, hist


def test_vehicle_accelerates_brakes_for_the_curve_and_stops_at_the_end():
    g = _drive_graph()
    c, path = _controller(g)
    assert c.junctions and c.junctions[0][0] == pytest.approx(300.0)
    t, hist = _run(c, g)
    speeds = [h[2] for h in hist]
    # accelerates to the ceiling (min of segment limit and vehicle max)
    limit = min(VehicleParams().max_speed, g.segments["s1"].travel_speed(Mode.CAR))
    assert max(speeds) == pytest.approx(limit)
    assert any(h[2] >= limit - 1e-9 and h[1] < 250.0 for h in hist)
    # brakes for the 90 degree turn at B
    corner = [h[2] for h in hist if 280.0 <= h[1] <= 320.0]
    assert corner and min(corner) < limit / 2.0, "the car took the corner flat out"
    assert min(corner) > 0.5, "the car should slow for the corner, not stop"
    # stops exactly at the destination
    assert c.arrived
    assert abs(path.length - c.dist) <= 0.1
    assert c.speed == 0.0
    assert c.distance_driven == pytest.approx(path.length)
    # no accelerations beyond the declared limits (the final touch-down step
    # snaps the last centimetres to a standstill and is exempt)
    for (t0, d0, v0, _), (t1, d1, v1, _) in zip(hist, hist[1:]):
        if d1 >= path.length - 1e-6:
            continue
        assert v1 - v0 <= VehicleParams().accel * 0.1 + 1e-9
        assert v0 - v1 <= VehicleParams().brake * 0.1 + 1e-9


def test_vehicle_keeps_a_following_gap():
    g = _drive_graph()
    c, path = _controller(g)
    lead_along = 120.0
    lead_xy = path.point_at(lead_along)
    params = c.params
    worst = math.inf
    t = 0.0
    for _ in range(2000):
        lead = OtherVehicle("veh:lead", lead_xy, 0.0, 0.0)
        c.advance(0.1, g, Mode.CAR, [lead], "veh:me", t)
        t += 0.1
        gap = lead_along - c.dist - params.length
        worst = min(worst, gap)
        if c.speed == 0.0 and c.dist > 10.0:
            break
    assert c.following == "veh:lead"
    assert worst >= params.follow_gap - 1e-6, \
        f"closed to {worst:.2f} m, inside the {params.follow_gap} m standstill gap"
    assert c.dist == pytest.approx(lead_along - params.length - params.follow_gap, abs=0.05)
    assert c.blocked is True and c.events().get("following", 0) == 1
    assert c.last_reason == "following"

    # the lead pulls away: we follow again, and 'blocked' is a transition count
    for _ in range(400):
        c.advance(0.1, g, Mode.CAR,
                  [OtherVehicle("veh:lead", path.point_at(400.0), 8.0, 0.0)],
                  "veh:me", t)
        t += 0.1
        if c.speed > 1.0:
            break
    assert c.blocked is False
    assert c.events().get("following", 0) == 1, "events count transitions, not ticks"


def test_vehicle_yields_at_a_junction_then_breaks_the_deadlock():
    # A calm street (5.5 m/s): approaching a junction at a speed the car can
    # actually stop from within the junction yield distance.
    g = _drive_graph("living_street")
    c, path = _controller(g)
    params = c.params
    # a car creeping into the junction from the side road, arriving before us
    other = OtherVehicle("veh:aaa", (300.0, -8.0), 2.0, 0.0,
                         next_junction=(300.0, 0.0), junction_dist=0.5)
    stopped_at, max_wait = None, 0.0
    t = 0.0
    for _ in range(4000):
        c.advance(0.1, g, Mode.CAR, [other], "veh:me", t)
        t += 0.1
        max_wait = max(max_wait, c.waiting_junction_s)
        if stopped_at is None and c.speed == 0.0 and c.dist > 250.0:
            stopped_at = c.dist
            assert c.yielding_to == "veh:aaa"
            assert c.last_reason == "junction"
        if c.dist > 305.0:
            break
    assert stopped_at is not None, "the car never yielded at the junction"
    # it stopped short of the junction, not in it
    assert stopped_at < 300.0
    assert 300.0 - stopped_at <= params.junction_yield_m
    # and it waited the bounded deadlock time before proceeding
    assert max_wait >= params.junction_wait_max_s
    assert max_wait <= params.junction_wait_max_s + 1.0
    assert c.dist > 300.0, "the deadlock breaker never let the car through"
    assert c.events().get("junction", 0) >= 1


def test_vehicle_gives_way_to_whoever_arrives_first():
    g = _drive_graph("living_street")
    c, path = _controller(g)
    c.dist, c.speed = 290.0, 2.0            # 10 m from the junction, ETA 5 s
    late = OtherVehicle("veh:zzz", (300.0, -30.0), 1.0, 0.0,
                        next_junction=(300.0, 0.0), junction_dist=25.0)
    c.advance(0.1, g, Mode.CAR, [late], "veh:me", 0.0)
    assert c.yielding_to is None, "we arrive first; we do not yield"
    early = OtherVehicle("veh:zzz", (300.0, -6.0), 3.0, 0.0,
                         next_junction=(300.0, 0.0), junction_dist=1.0)
    c.advance(0.1, g, Mode.CAR, [early], "veh:me", 0.1)
    assert c.yielding_to == "veh:zzz"


def test_vehicle_stops_before_a_road_closed_to_its_mode():
    g = _drive_graph()
    c, path = _controller(g)
    g.segments["s2"].dynamic_state.closed_modes = {Mode.CAR}
    t = 0.0
    for _ in range(4000):
        c.advance(0.1, g, Mode.CAR, [], "veh:me", t)
        t += 0.1
        if c.blocked_s > 5.0:
            break
    assert c.road_closed_ahead == "s2"
    assert c.speed == 0.0
    assert c.dist < 300.0, "the car entered a road closed to cars"
    assert 300.0 - c.dist <= 4.0, "the car stopped nowhere near the closure"
    assert c.blocked is True and c.blocked_s > 5.0
    assert c.events().get("road_closed", 0) == 1
    assert not c.arrived
    # reopening the road lets it continue (the graph is the authority)
    g.segments["s2"].dynamic_state.closed_modes = set()
    for _ in range(4000):
        c.advance(0.1, g, Mode.CAR, [], "veh:me", t)
        t += 0.1
        if c.arrived:
            break
    assert c.arrived and c.road_closed_ahead is None
    assert c.events().get("road_closed", 0) == 1


def test_vehicle_reconcile_physical_only_holds_back():
    g = _drive_graph()
    c, _ = _controller(g)
    _run(c, g, until=lambda ctl, t: ctl.dist > 100.0)
    planned = c.dist
    c.reconcile_physical(c.path.point_at(planned + 40.0), False, 0.1)
    assert c.dist == pytest.approx(planned), "physics must not push the car forward"
    c.reconcile_physical(c.path.point_at(planned - 20.0), False, 0.1)
    assert c.dist == pytest.approx(planned - 20.0 + 4.0)
    c.reconcile_physical(c.path.point_at(c.dist), True, 0.1)
    assert c.blocked is True and c.speed == 0.0 and c.blocked_s > 0.0


def test_vehicle_state_round_trips():
    g = _drive_graph()
    c, path = _controller(g)
    _run(c, g, until=lambda ctl, t: ctl.dist > 150.0)
    other = VehicleController(path)
    other.restore(c.to_state())
    assert (other.dist, other.speed, other.distance_driven) == \
        (c.dist, c.speed, c.distance_driven)
    assert other.events() == c.events()

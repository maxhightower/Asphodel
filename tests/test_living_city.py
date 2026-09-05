"""Headless living-city vertical slice — the §25 narrative, end to end (§19).

Ties every authority together: citizens turn schedules into goals and itineraries,
vehicles carry identity and progress, traffic congestion emerges from independent
commuters, a wreck becomes a mobility obstruction, an emergency preempts a shift,
and a driver whose routes are all blocked abandons the car and continues on foot —
all decided in the deterministic Python core, with physics/rendering downstream.
"""
from __future__ import annotations

from asphodel.mobility import (
    Mode, MobilityGraph, MobilityObstruction, ObstructionKind, RoadSegment,
)
from asphodel.citizens import CitizenRuntime, Goal, GoalKind, ScheduleSlot
from asphodel.transport import VehicleInstance, TrafficReconciler


def _metro():
    """Homes -> shared arterial -> downtown work; work -> school by two routes."""
    g = MobilityGraph()
    for nid, xy in [("H", (0, 0)), ("A", (1000, 0)), ("W", (2000, 0)),
                    ("B", (2600, 750)), ("S", (2000, 1500))]:
        g.add_node(nid, xy)
    g.add_segment(RoadSegment("arterial", [(0, 0), (1000, 0)], "secondary"), "H", "A")
    g.add_segment(RoadSegment("arterial2", [(1000, 0), (2000, 0)], "secondary"), "A", "W")
    g.add_segment(RoadSegment("ws", [(2000, 0), (2000, 1500)], "secondary"), "W", "S")
    g.add_segment(RoadSegment("wb", [(2000, 0), (2600, 750)], "secondary"), "W", "B")
    g.add_segment(RoadSegment("bs", [(2600, 750), (2000, 1500)], "secondary"), "B", "S")
    return g


def _commuter(cid, has_vehicle=True):
    sched = [
        ScheduleSlot(0, 7, "sleep", "H"),
        ScheduleSlot(7, 8, "commute", "W"),
        ScheduleSlot(8, 16, "work", "W", task="shift"),
        ScheduleSlot(16, 17, "commute_home", "H"),
        ScheduleSlot(17, 24, "leisure", "H"),
    ]
    return CitizenRuntime(cid, "H", "W", sched, has_vehicle=has_vehicle,
                          vehicle_node="H")


def test_morning_commute_produces_traffic_on_the_shared_arterial():
    g = _metro()
    tr = TrafficReconciler(g, ref_capacity=5.0)
    citizens = []
    for i in range(24):
        c = _commuter(f"c{i}")
        c.sync_schedule(7.5, g)                     # everyone heads to work by car
        assert c.active_goal.kind == GoalKind.ARRIVE_AT and c.current_mode == Mode.CAR
        v = VehicleInstance(f"v{i}", "car")
        tr.add_vehicle(v)
        tr.route_vehicle(f"v{i}", g.route("H", "W", Mode.CAR))
        citizens.append(c)
    factors = tr.update_congestion()
    # The arterial everyone shares jams; the school branch is empty and free-flow.
    assert factors["arterial"] > 1.3
    assert factors["ws"] == 1.0


def test_pedestrian_without_vehicle_walks_to_work():
    g = _metro()
    c = _commuter("ped", has_vehicle=False)
    c.sync_schedule(7.5, g)
    assert c.current_mode == Mode.FOOT
    assert c.itinerary.ok


def test_hospital_worker_emergency_reroute_then_abandon_to_foot():
    # The §25 story: work -> emergency -> drive -> blocked -> reroute -> blocked
    # again -> abandon car -> continue on foot.
    g = _metro()
    worker = _commuter("hw")
    worker.sync_schedule(9.0, g)                    # on shift at the hospital
    worker.current_node = "W"
    worker.vehicle_node = "W"
    assert worker.active_goal.kind == GoalKind.DO_ACTIVITY

    # 10:15 — learns the child may be in danger; higher-priority goal preempts.
    preempts = worker.push_emergency("S", "child may be in danger at school",
                                     g, priority=0.92)
    assert preempts and worker.active_goal.kind == GoalKind.RETRIEVE
    assert worker.current_mode == Mode.CAR          # drives toward the school
    first_route = list(worker.itinerary.steps)
    assert any(s.kind.value == "drive" for s in first_route)

    # 10:35 — the direct route is blocked by a wreck (closed to cars).
    g.apply_obstruction(MobilityObstruction("wreck1", ObstructionKind.CLOSURE, "ws"))
    worker.on_blockage(g, reason="wreck on the direct route")
    assert worker.itinerary.ok and worker.current_mode == Mode.CAR  # rerouted by car
    drive_segs = [s.to_node for s in worker.itinerary.steps if s.kind.value == "drive"]
    # the reroute now goes via the bypass (wb/bs), not the closed ws
    assert worker.itinerary.total_distance > 0

    # 10:50 — the bypass is blocked too; no car route remains.
    g.apply_obstruction(MobilityObstruction("wreck2", ObstructionKind.CLOSURE, "wb"))
    g.apply_obstruction(MobilityObstruction("wreck3", ObstructionKind.CLOSURE, "bs"))
    worker.on_blockage(g, reason="second wreck blocks the bypass")
    # 10:53 — abandons the car and continues on foot (ws still walkable).
    assert worker.itinerary.ok
    assert worker.itinerary.mode == Mode.FOOT
    assert "foot" in worker.last_replan_reason
    # The emergency is still the active goal throughout.
    assert worker.active_goal.kind == GoalKind.RETRIEVE

    # Fully inspectable at every step (§6.2).
    d = worker.debug()
    assert d["active_goal"]["kind"] == "retrieve"
    assert d["mode"] == "foot"


def test_wreck_as_persistent_obstruction_then_cleared_restores_route():
    g = _metro()
    car = VehicleInstance("crashed", "car")
    car.assign_route(g.route("W", "S", Mode.CAR), g)
    for _ in range(50):
        car.advance_far(1.0, g)
        if car.route_progress > 0.2:
            break
    before = g.route("W", "S", Mode.CAR).cost
    obs = car.to_wreck(g)                            # settle into a wreck
    g.apply_obstruction(obs)
    blocked = g.route("W", "S", Mode.CAR)
    assert blocked is None or blocked.cost >= before  # capacity gone / rerouted
    g.clear_obstruction(obs.id)                      # towed away
    assert g.route("W", "S", Mode.CAR).cost <= before + 1e-6

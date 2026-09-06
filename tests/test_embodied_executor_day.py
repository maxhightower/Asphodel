"""One embodied citizen, one whole day (ASPHODEL_EMBODIED_MOBILITY_V1 §5, §9, §16).

The standalone MobilityRuntime over the canonical Houston bundle, citizen 4,
from 05:00 for 24 h in the runtime's own 1 s substeps. The claims:

* the morning commute happens as an ordered sequence of real events —
  leave home 13106, walk, get into veh:4, drive, park, get out, walk, enter
  work 4517 — and the 'work' activity only starts once inside that building;
* the state machine visits the §9 states in the §9 order;
* nothing teleports: between consecutive substeps the citizen never moves
  further than their mode allows, and a transition never jumps more than 3 m;
* vehicle identity survives the whole day and its parked_location is the
  parking anchor the PARK step chose;
* a vehicle that disappears before ENTER_VEHICLE is a bounded failure: the
  citizen replans on foot and still gets to work — the trip is not stuck.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.citizens.planning import StepKind
from asphodel.embodied import MobilityRuntime, load_entrances
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodiment import CitySpatialContext

CITY = "houston"
CITIZEN = 4
HOME = 13106
WORK = 4517
VEHICLE = "veh:4"
START_HOUR = 5.0
DT = 1.0                       # the runtime's own substep: every tick is sampled

# ASPHODEL_EMBODIED_MOBILITY_V1 §9, in order.
STATE_ORDER = [
    EmbodimentState.INSIDE_BUILDING, EmbodimentState.ON_FOOT,
    EmbodimentState.APPROACHING_VEHICLE, EmbodimentState.ENTERING_VEHICLE,
    EmbodimentState.IN_VEHICLE, EmbodimentState.DRIVING, EmbodimentState.PARKED,
    EmbodimentState.EXITING_VEHICLE, EmbodimentState.ON_FOOT,
    EmbodimentState.INSIDE_BUILDING, EmbodimentState.DOING_ACTIVITY,
]

WALK_JUMP = 1.4 * DT + 1.0     # MODE_TOP_SPEED[FOOT] * dt + slack
DRIVE_JUMP = 17.0 * DT + 1.0   # above the 16 m/s city ceiling
TRANSITION_JUMP = 3.0          # doors, kerbs: a step, never a jump

_MOVING = {EmbodimentState.ON_FOOT, EmbodimentState.APPROACHING_VEHICLE,
           EmbodimentState.DRIVING}


@pytest.fixture(scope="module")
def bundle():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    ctx = CitySpatialContext.from_bundle_dir(d)
    entrances, anchors = load_entrances(d)
    pop = load_bundle_population(d)
    profile = next(c for c in pop if int(c.citizen_id) == CITIZEN)
    return d, ctx, entrances, anchors, profile


def _runtime(bundle):
    d, ctx, entrances, anchors, profile = bundle
    rt = MobilityRuntime(ctx.street_graph, entrances, anchors, ctx=ctx, bundle_dir=d)
    assert rt.register(profile, START_HOUR), "citizen 4 could not be registered"
    return rt, rt.execs[CITIZEN]


@pytest.fixture(scope="module")
def day(bundle):
    """24 h of citizen 4, sampled every substep."""
    rt, ex = _runtime(bundle)
    hour = START_HOUR
    prev_pos, prev_state = ex.pos, ex.state
    order = [ex.state]
    jumps = []                 # (from_state, to_state, metres, hour)
    walked, driven = [], []
    drive_route_m = None
    parked_anchor = None
    for _ in range(int(24 * 3600 / DT)):
        rt.advance(DT, hour)
        hour = (hour + DT / 3600.0) % 24.0
        step = ex.current_step
        if drive_route_m is None and ex.state is EmbodimentState.DRIVING \
                and step is not None and step.kind is StepKind.DRIVE:
            drive_route_m = step.route.distance
        if parked_anchor is None and ex.state is EmbodimentState.PARKED \
                and step is not None and step.anchor_xy is not None:
            parked_anchor = tuple(step.anchor_xy)
        jumps.append((prev_state, ex.state, math.dist(ex.pos, prev_pos), hour))
        walked.append(ex.distance_walked)
        driven.append(ex.distance_driven)
        if ex.state is not prev_state:
            order.append(ex.state)
        prev_pos, prev_state = ex.pos, ex.state
    return {"rt": rt, "ex": ex, "order": order, "jumps": jumps,
            "trace": list(ex.trace), "walked": walked, "driven": driven,
            "drive_route_m": drive_route_m, "parked_anchor": parked_anchor}


def _events(trace, kinds=None):
    out = []
    for row in trace:
        if kinds is None or row["event"] in kinds:
            out.append(row)
    return out


# --------------------------------------------------------------------------- #
# the morning commute
# --------------------------------------------------------------------------- #
MORNING_KINDS = {"plan", "left_building", "walk_start", "walk_done",
                 "entered_vehicle", "drive_start", "drive_done", "parked",
                 "exited_vehicle", "entered_building", "activity"}


def test_morning_commute_event_sequence(day):
    rows = [r for r in _events(day["trace"], MORNING_KINDS) if r["t"] <= 4.0 * 3600.0]
    # the commute begins with the plan that has real steps in it
    start = next(i for i, r in enumerate(rows)
                 if r["event"] == "plan" and r.get("steps"))
    seq = [r["event"] for r in rows[start:]]
    expected = ["plan", "left_building", "walk_start", "walk_done",
                "entered_vehicle", "drive_start", "drive_done", "parked",
                "exited_vehicle", "walk_start", "walk_done", "entered_building"]
    assert seq[:len(expected)] == expected, seq[:len(expected)]

    got = rows[start:start + len(expected)]
    by_kind = {r["event"]: r for r in got}
    assert by_kind["left_building"]["building_id"] == HOME
    assert by_kind["entered_vehicle"]["vehicle_id"] == VEHICLE
    assert by_kind["drive_start"]["vehicle_id"] == VEHICLE
    assert by_kind["drive_start"]["length_m"] > 1000.0
    assert by_kind["drive_start"]["segments"] > 10
    assert by_kind["parked"]["vehicle_id"] == VEHICLE
    assert by_kind["parked"]["node"].startswith("park:")
    assert by_kind["exited_vehicle"]["vehicle_id"] == VEHICLE
    assert by_kind["entered_building"]["building_id"] == WORK
    # the commute is walked and driven in real time, not skipped
    assert by_kind["drive_done"]["t"] - by_kind["drive_start"]["t"] > 120.0


def test_work_activity_only_after_entering_the_building(day):
    entered = next(r for r in day["trace"]
                   if r["event"] == "entered_building" and r.get("building_id") == WORK)
    work = next(r for r in day["trace"]
                if r["event"] == "activity" and r.get("activity") == "work")
    assert work["t"] >= entered["t"], "worked before arriving"
    assert work["building_id"] == WORK
    # the citizen is at work by 08:05 (schedule says 08:00; the walk from the
    # car park is the honest difference)
    hour = (START_HOUR + work["t"] / 3600.0) % 24.0
    assert hour <= 8.0 + 5.0 / 60.0, f"work started at {hour:.3f}"
    assert (START_HOUR + entered["t"] / 3600.0) % 24.0 <= 8.0


def test_state_machine_follows_the_section_9_order(day):
    order = day["order"]
    assert EmbodimentState.TRIP_FAILED not in order
    seen = set(order)
    required = {EmbodimentState.INSIDE_BUILDING, EmbodimentState.ON_FOOT,
                EmbodimentState.ENTERING_VEHICLE, EmbodimentState.IN_VEHICLE,
                EmbodimentState.DRIVING, EmbodimentState.PARKED,
                EmbodimentState.EXITING_VEHICLE, EmbodimentState.DOING_ACTIVITY}
    assert required <= seen

    # the commute's states appear in the §9 order (states the trip does not
    # need — an approach walk to a car parked at the kerb — may be skipped)
    first_drive = order.index(EmbodimentState.DRIVING)
    cycle = order[order.index(EmbodimentState.ON_FOOT):first_drive + 5]
    i = 0
    for state in cycle:
        while i < len(STATE_ORDER) and STATE_ORDER[i] is not state:
            i += 1
        assert i < len(STATE_ORDER), f"{state} is out of §9 order in {cycle}"
        i += 1


def test_no_teleport_between_substeps(day):
    worst = {}
    for a, b, dist, hour in day["jumps"]:
        if a is EmbodimentState.DRIVING or b is EmbodimentState.DRIVING:
            cap = DRIVE_JUMP
        elif a in _MOVING or b in _MOVING:
            cap = WALK_JUMP
        else:
            cap = TRANSITION_JUMP
        key = (a.value, b.value)
        worst[key] = max(worst.get(key, 0.0), dist)
        assert dist <= cap, (f"teleport {dist:.1f} m at hour {hour:.3f} "
                             f"({a.value} -> {b.value}, cap {cap} m)")
    # the transitions themselves are steps across a kerb, not jumps
    for (a, b), dist in worst.items():
        if a != b and "driving" not in (a, b):
            assert dist <= TRANSITION_JUMP, f"{a} -> {b} moved {dist:.1f} m"


def test_distances_are_monotonic_and_match_the_route(day):
    walked, driven = day["walked"], day["driven"]
    for series in (walked, driven):
        for a, b in zip(series, series[1:]):
            assert b >= a - 1e-9, "distance travelled went backwards"
    ex = day["ex"]
    assert ex.distance_walked > 300.0
    assert ex.trips_completed >= 4
    # the drive covered the planned route, to within 1 %
    route_m = day["drive_route_m"]
    assert route_m is not None
    drive_done = next(r for r in day["trace"] if r["event"] == "drive_done")
    assert abs(drive_done["driven_m"] - route_m) <= 0.01 * route_m, \
        f"drove {drive_done['driven_m']} m of a {route_m} m route"


def test_vehicle_identity_and_parking_survive_the_day(day):
    rt, ex = day["rt"], day["ex"]
    assert set(rt.vehicles) == {VEHICLE}
    veh = rt.vehicles[VEHICLE]
    assert veh.vehicle_id == VEHICLE and veh.owner == str(CITIZEN)
    assert veh.driver is None                      # nobody is in it at 05:00 next day
    assert veh.parked_location is not None
    assert veh.engine_state == "off" and veh.speed == 0.0
    # it is parked at an anchor the parking index still holds for it
    assert VEHICLE in rt.parking.occupied.values()
    idx = next(i for i, v in rt.parking.occupied.items() if v == VEHICLE)
    node_xy = rt.citizens[CITIZEN].node_meta[f"park:{idx}"]["xy"]
    assert math.dist(veh.parked_location, node_xy) < 1e-6
    # ... and the morning PARK step's anchor is where the car actually stood
    parked = next(r for r in day["trace"] if r["event"] == "parked")
    assert math.dist(day["parked_anchor"], parked["anchor"]) < 0.1
    assert ex.blocked_events == 0


# --------------------------------------------------------------------------- #
# §16: the car is gone
# --------------------------------------------------------------------------- #
def test_vehicle_vanishing_before_enter_falls_back_to_walking(bundle):
    rt, ex = _runtime(bundle)
    hour = START_HOUR
    dropped = False
    prev_pos, prev_state = ex.pos, ex.state
    arrived_hour = None
    for _ in range(int(6 * 3600 / DT)):
        step = ex.current_step
        if not dropped and step is not None and step.kind is StepKind.ENTER_VEHICLE:
            rt.vehicles.pop(VEHICLE)          # the car is not there any more
            dropped = True
        rt.advance(DT, hour)
        hour = (hour + DT / 3600.0) % 24.0
        dist = math.dist(ex.pos, prev_pos)
        cap = (DRIVE_JUMP if EmbodimentState.DRIVING in (prev_state, ex.state)
               else WALK_JUMP if (prev_state in _MOVING or ex.state in _MOVING)
               else TRANSITION_JUMP)
        assert dist <= cap, f"teleport {dist:.1f} m at hour {hour:.3f}"
        prev_pos, prev_state = ex.pos, ex.state
        if ex.building_id == WORK:
            arrived_hour = hour
            break
    assert dropped, "the ENTER_VEHICLE step never came up"
    fails = [r for r in ex.trace if r["event"] == "failure"]
    assert fails and fails[0]["reason"] == "vehicle unavailable"
    assert len(fails) <= 3, "the failure policy must not livelock on the same step"
    # it replanned on foot and walked the whole way
    plans = [r for r in ex.trace if r["event"] == "plan" and r.get("steps")]
    assert any(all("drive" not in s for s in p["steps"]) for p in plans[1:])
    assert not rt.citizens[CITIZEN].has_vehicle
    assert arrived_hour is not None, "the citizen never reached work on foot"
    assert arrived_hour <= 9.0
    assert ex.state in (EmbodimentState.INSIDE_BUILDING, EmbodimentState.DOING_ACTIVITY)
    assert not ex.trip_failed and ex.distance_walked > 3000.0
    assert ex.distance_driven == 0.0

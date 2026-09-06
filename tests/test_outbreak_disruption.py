"""Civil breakdown: disrupted workplaces and abandoned cars (§8).

Two independent breakdown paths, both through existing authorities:

* a workplace whose registered workers are dying is DISRUPTED, and the workers
  still there are pushed home through the planner (a "disruption" goal), never
  by relocating anybody;
* a citizen who collapses at the wheel leaves the car exactly where it stopped:
  the VehicleInstance becomes a PERSISTENT_WRECK and the wreck is applied to the
  street graph as a MobilityObstruction, so every later route pays for it.

A stalled car is a hard block for vehicles and a soft one for people: the
runtime overrides the generic WRECK effect (which only removes half a segment's
capacity) with ``modes_affected = {CAR, HEAVY}``, so the segment's
``traverse_cost(Mode.CAR)`` is infinite — every later CAR route reroutes — while
FOOT stays open (§11 "abandon the car and walk").
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodiment import CitySpatialContext
from asphodel.mobility import Mode
from asphodel.outbreak.health import ALIVE, HealthState
from asphodel.transport.instances import VehicleFidelity

CITY = "houston"
INDEX = 42
WORK = 2318
START_HOUR = 5.0
END_HOUR = 15.0
GRACE_S = 30 * 60.0            # the workers get half an hour to react
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _world(d, start_hour):
    w = world_from_bundle(CITY, micro_params=MICRO)
    w.start_hour = start_hour
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    return w


@pytest.fixture(scope="module")
def day():
    """05:00 -> 15:00 with the index case at citizen 42, sampling the workers
    of building 2318 every game minute."""
    d = _bundle_dir()
    w = _world(d, START_HOUR)
    ob = w.enable_outbreak("classic_zombie", index_case=INDEX)
    workers = list(ob.workers_by_building[WORK])
    samples = []
    for _ in range(int((END_HOUR - START_HOUR) * 60)):
        w.advance_seconds(60.0)
        row = {"t": round(ob.now_s, 1), "workers": {}}
        for cid in workers:
            ex, rt = w.mobility.execs[cid], w.mobility.citizens[cid]
            rec = ob.records.get(cid)
            row["workers"][cid] = {
                "building_id": int(ex.building_id),
                "state": ex.state.value, "override": ex.override,
                "goal_sources": sorted({g.source for g in rt.goals.goals}),
                "active_goal": None if rt.active_goal is None else rt.active_goal.source,
                "health": "susceptible" if rec is None else rec.state.value,
                "alive": rec is None or rec.state in ALIVE,
            }
        samples.append(row)
    return {"world": w, "ob": ob, "workers": workers, "samples": samples}


@pytest.fixture(scope="module")
def driving():
    """A world at ~07:50 with a citizen physically DRIVING, and no infection —
    the vehicle-abandonment path is exercised directly."""
    d = _bundle_dir()
    w = _world(d, 7.0)
    ob = w.enable_outbreak("classic_zombie", seed_index_case=False)
    driver = None
    for _ in range(50):
        w.advance_seconds(60.0)
        driver = next((c for c in sorted(w.mobility.execs)
                       if w.mobility.execs[c].state == EmbodimentState.DRIVING
                       and w.mobility.execs[c].vehicle_id
                       and w.mobility.vehicles[w.mobility.execs[c].vehicle_id].current_segment(
                           w.mobility.graph) is not None), None)
        if driver is not None:
            break
    if driver is None:
        pytest.skip("no citizen was driving on a street segment in the window")
    return {"world": w, "ob": ob, "driver": driver}


# --------------------------------------------------------------------------- #
# workplace disruption
# --------------------------------------------------------------------------- #
def test_the_index_case_workplace_is_disrupted(day):
    ob = day["ob"]
    hits = [e for e in ob.events if e["event"] == "WORKPLACE_DISRUPTED"
            and e["building_id"] == WORK]
    assert len(hits) == 1, hits
    e = hits[0]
    assert e["workers"] == day["workers"]
    assert e["reason"]
    assert e["down"] or e["hazard"]
    assert WORK in ob.disrupted_buildings
    assert ob.disrupted_buildings[WORK]["t"] == pytest.approx(e["t"], abs=1.0)
    assert ob.snapshot()["disrupted_buildings"][str(WORK)]["reason"] == e["reason"]


def test_disruption_is_justified_by_the_health_records(day):
    ob = day["ob"]
    e = next(x for x in ob.events if x["event"] == "WORKPLACE_DISRUPTED"
             and x["building_id"] == WORK)
    down = e["down"]
    for cid in down:
        assert ob.records[cid].state in (HealthState.INCAPACITATED, HealthState.DEAD,
                                         HealthState.CORPSE, HealthState.UNDEAD)
    if not e["hazard"]:
        assert len(down) / len(e["workers"]) >= ob.pathogen.workplace_disruption_fraction
    else:
        for cid in e["hazard"]:
            assert ob.records[cid].state in (HealthState.INCAPACITATED, HealthState.CORPSE,
                                             HealthState.UNDEAD)


def test_workers_still_at_the_disrupted_workplace_are_sent_home(day):
    ob, samples = day["ob"], day["samples"]
    e = next(x for x in ob.events if x["event"] == "WORKPLACE_DISRUPTED"
             and x["building_id"] == WORK)
    # the workers present in the last minute before the disruption: the world
    # clock interleaves movement and outbreak per second, so by the sample
    # after the disruption the reaction (leaving) may already have happened
    before = [s for s in samples if s["t"] < e["t"]]
    at_disruption = before[-1] if before else next(s for s in samples if s["t"] >= e["t"])
    still_at_work = [c for c, w in at_disruption["workers"].items()
                     if w["alive"] and w["building_id"] == WORK]
    assert still_at_work, "nobody was left at the workplace to react"
    window = [s for s in samples if e["t"] <= s["t"] <= e["t"] + GRACE_S]
    invalidated = {x["citizen_id"] for x in ob.events
                   if x["event"] == "PLAN_INVALIDATED" and str(WORK) in str(x.get("reason", ""))
                   and e["t"] <= x["t"] <= e["t"] + GRACE_S}
    for cid in still_at_work:
        reacted = any("disruption" in s["workers"][cid]["goal_sources"]
                      or s["workers"][cid]["building_id"] != WORK
                      or not s["workers"][cid]["alive"]
                      for s in window)
        assert reacted or cid in invalidated, (cid, [s["workers"][cid] for s in window[:5]])
        assert cid in invalidated or any(s["workers"][cid]["building_id"] != WORK for s in window), cid


def test_a_disrupted_workplace_is_disrupted_once_and_stays_disrupted(day):
    ob = day["ob"]
    kinds = [e["building_id"] for e in ob.events if e["event"] == "WORKPLACE_DISRUPTED"]
    assert len(kinds) == len(set(kinds))
    for bid in kinds:
        assert bid in ob.disrupted_buildings


# --------------------------------------------------------------------------- #
# the abandoned car
# --------------------------------------------------------------------------- #
def test_abandoned_vehicle_becomes_a_wreck_and_obstructs_its_street(driving):
    w, ob, cid = driving["world"], driving["ob"], driving["driver"]
    graph = w.mobility.graph
    ex = w.mobility.execs[cid]
    vid = ex.vehicle_id
    veh = w.mobility.vehicles[vid]
    sid = veh.current_segment(graph)
    seg = graph.segments[sid]
    endpoints = next((u, v) for u, adj in graph._adj.items()
                     for (v, s, _f) in adj if s == sid)
    cost_before = seg.traverse_cost(Mode.CAR)
    route_before = graph.route(endpoints[0], endpoints[1], Mode.CAR)
    pos_before = tuple(ex.pos)
    n_events = len(ob.events)

    ob._abandon_vehicle(cid, ex, "test")

    # the vehicle itself
    assert veh.fidelity is VehicleFidelity.PERSISTENT_WRECK
    assert veh.driver is None and veh.speed == 0.0 and veh.engine_state == "off"
    assert veh.parked_location is not None
    assert ex.speed == 0.0
    assert math.hypot(ex.pos[0] - pos_before[0], ex.pos[1] - pos_before[1]) == 0.0

    # the obstruction on the graph
    obs_id = f"wreck:{vid}"
    assert obs_id in graph._obstructions
    assert obs_id in ob.obstructions
    obs = graph._obstructions[obs_id]
    assert obs.affected_segment == sid and obs.source_entity == vid
    assert obs_id in seg.dynamic_state.obstruction_ids
    assert seg.dynamic_state.blocked_fraction > 0.0

    # cost: the street is closed to cars, still walkable (see module docstring)
    assert math.isfinite(cost_before)
    assert math.isinf(seg.traverse_cost(Mode.CAR))
    assert not seg.allows(Mode.CAR)
    assert seg.allows(Mode.FOOT) and math.isfinite(seg.traverse_cost(Mode.FOOT))

    # the events
    new = ob.events[n_events:]
    ab = next(e for e in new if e["event"] == "VEHICLE_ABANDONED")
    ro = next(e for e in new if e["event"] == "ROAD_OBSTRUCTED")
    assert ab["citizen_id"] == cid and ab["vehicle_id"] == vid and ab["segment"] == sid
    assert ab["reason"] == "test"
    assert ro["obstruction_id"] == obs_id and ro["segment"] == sid
    assert "car" in ro["closed_modes"]

    # every later route sees it
    route_after = graph.route(endpoints[0], endpoints[1], Mode.CAR)
    assert route_before is not None and sid in route_before.segments
    assert route_after is None or sid not in route_after.segments, route_after.segments
    if route_after is not None:
        assert route_after.cost > route_before.cost
    # people still get through on foot
    walk = graph.route(endpoints[0], endpoints[1], Mode.FOOT)
    assert walk is not None


def test_abandoning_twice_does_not_duplicate_the_obstruction(driving):
    w, ob, cid = driving["world"], driving["ob"], driving["driver"]
    ex = w.mobility.execs[cid]
    graph = w.mobility.graph
    before = len(graph._obstructions), len(ob.obstructions)
    ob._abandon_vehicle(cid, ex, "test again")
    assert (len(graph._obstructions), len(ob.obstructions)) == before


def test_the_day_run_abandons_the_index_case_car_on_the_street(day):
    ob = day["ob"]
    ab = [e for e in ob.events if e["event"] == "VEHICLE_ABANDONED"]
    if not ab:
        pytest.skip("no driver collapsed at the wheel in this run")
    graph = day["world"].mobility.graph
    for e in ab:
        assert e["reason"] == "driver incapacitated"
        veh = day["world"].mobility.vehicles[e["vehicle_id"]]
        assert veh.fidelity is VehicleFidelity.PERSISTENT_WRECK
        if e["segment"] is not None:
            assert f"wreck:{e['vehicle_id']}" in graph._obstructions
    obstructed = [e for e in ob.events if e["event"] == "ROAD_OBSTRUCTED"]
    assert len(obstructed) == len([e for e in ab if e["segment"] is not None])

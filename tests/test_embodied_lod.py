"""Distance-banded LOD and physical reports (ASPHODEL_EMBODIED_MOBILITY_V1 §17, §18).

The same citizen must be the same citizen in every band: promoted to PHYSICAL
near the focus, demoted to ROUTE_SIMULATED when the player walks away (the trip
keeps running), frozen to ABSTRACT only as an overflow of the active budget and
caught up when the focus comes back — with no jump in position and no change of
identity at any boundary. And when a Godot body reports where physics actually
put it, that report may hold the citizen back but never push it forward.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodied import MobilityRuntime, load_entrances
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodiment import CitySpatialContext
from asphodel.lod.entity import LODBand

CITY = "houston"
CITIZEN = 4
VEHICLE = "veh:4"
FAR = 20000.0                # metres away: well beyond the route radius


@pytest.fixture(scope="module")
def bundle():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    ctx = CitySpatialContext.from_bundle_dir(d)
    entrances, anchors = load_entrances(d)
    pop = load_bundle_population(d)
    return d, ctx, entrances, anchors, pop


def _runtime(bundle, only=None, hour=7.49):
    d, ctx, entrances, anchors, pop = bundle
    rt = MobilityRuntime(ctx.street_graph, entrances, anchors, ctx=ctx, bundle_dir=d)
    for prof in pop:
        if only is not None and int(prof.citizen_id) not in only:
            continue
        if getattr(prof, "home_building_id", None) is None:
            continue
        rt.register(prof, hour)
    return rt


def _advance_until(rt, hour, pred, max_s=4000, focus=None):
    ex = rt.execs[CITIZEN]
    for _ in range(int(max_s)):
        if focus == "follow":
            rt.set_focus_xy(ex.pos)
        rt.advance(1.0, hour)
        hour = (hour + 1.0 / 3600.0) % 24.0
        if pred(ex):
            return hour, True
    return hour, False


def _row(snap, cid=CITIZEN):
    return next(r for r in snap["citizens"] if r["citizen_id"] == cid)


# --------------------------------------------------------------------------- #
# promotion / demotion / re-promotion
# --------------------------------------------------------------------------- #
def test_focus_promotes_demotes_and_re_promotes_the_same_citizen(bundle):
    rt = _runtime(bundle, only={CITIZEN})
    ex = rt.execs[CITIZEN]
    hour = 7.49
    rt.set_focus_xy(ex.pos)

    # --- PHYSICAL: the player is standing next to the citizen -------------
    hour, ok = _advance_until(rt, hour, lambda e: e.state is EmbodimentState.DRIVING,
                              focus="follow")
    assert ok, "citizen 4 never started driving"
    rt.set_focus_xy(ex.pos)
    rt.advance(1.0, hour)
    snap = rt.snapshot()
    assert rt.bands[CITIZEN] is LODBand.PHYSICAL
    assert _row(snap)["band"] == "physical"
    assert f"cit:{CITIZEN}" in snap["near"]
    route = snap["routes"].get(f"cit:{CITIZEN}")
    assert route and len(route) >= 2, "a PHYSICAL body must be handed its route"
    assert ex.has_body is True
    vehicle_id = ex.vehicle_id
    assert vehicle_id == VEHICLE

    # --- ROUTE_SIMULATED: the player leaves; the trip carries on ----------
    rt.set_focus_xy((ex.pos[0] + FAR, ex.pos[1] + FAR))
    positions = []
    for _ in range(60):
        rt.advance(1.0, hour)
        hour = (hour + 1.0 / 3600.0) % 24.0
        positions.append(ex.pos)
    snap = rt.snapshot()
    assert rt.bands[CITIZEN] is LODBand.ROUTE_SIMULATED
    assert _row(snap)["band"] == "route_simulated"
    assert f"cit:{CITIZEN}" not in snap["near"]
    assert snap["routes"] == {}
    assert ex.has_body is False
    assert CITIZEN not in rt.frozen_at, "one citizen never overflows the budget"
    # the trip really progressed while nobody was looking
    moved = math.dist(positions[0], positions[-1])
    assert moved > 100.0, f"the demoted trip only moved {moved:.1f} m"
    assert len({p for p in positions}) == len(positions), "position stopped changing"
    # ... as the same citizen, in the same car
    assert _row(snap)["citizen_id"] == CITIZEN
    assert ex.vehicle_id == vehicle_id
    assert rt.vehicles[VEHICLE].vehicle_id == VEHICLE

    # --- back to PHYSICAL, on foot: no jump at the boundary ---------------
    hour, ok = _advance_until(rt, hour,
                              lambda e: e.state is EmbodimentState.ON_FOOT and e.ped is not None,
                              max_s=1200)
    assert ok, "citizen 4 never got out of the car"
    before = _row(rt.snapshot(include_routes=False))
    rt.set_focus_xy(ex.pos)
    seen = [(before["x"], before["y"])]
    bands = []
    for _ in range(10):
        rt.advance(1.0, hour)
        hour = (hour + 1.0 / 3600.0) % 24.0
        row = _row(rt.snapshot(include_routes=False))
        seen.append((row["x"], row["y"]))
        bands.append(row["band"])
    assert "physical" in bands, "the citizen was never re-promoted"
    for a, b in zip(seen, seen[1:]):
        assert math.dist(a, b) < 5.0, f"position jumped {math.dist(a, b):.1f} m"
    assert rt.execs[CITIZEN].citizen_id == CITIZEN

    # --- the transition log names who moved band and in which direction ---
    mine = [t for t in rt.transitions if t["citizen_id"] == CITIZEN]
    assert mine, "no LOD transitions recorded"
    pairs = {(t["from"], t["to"]) for t in mine}
    assert ("route_simulated", "physical") in pairs
    assert ("physical", "route_simulated") in pairs
    for t in mine:
        assert t["citizen_id"] == CITIZEN and "t" in t


# --------------------------------------------------------------------------- #
# ABSTRACT is an overflow band, and re-activation catches up
# --------------------------------------------------------------------------- #
def test_overflow_freezes_far_citizens_and_activation_catches_up(bundle):
    rt = _runtime(bundle, hour=7.0)
    assert len(rt.execs) > 50, "the whole canonical population should register"
    rt.max_active = 5
    hour = 7.0
    focus = rt.execs[CITIZEN].pos
    rt.set_focus_xy(focus)
    for _ in range(2400):
        rt.advance(1.0, hour)
        hour = (hour + 1.0 / 3600.0) % 24.0

    frozen = sorted(rt.frozen_at)
    assert frozen, "no citizen was frozen despite the tiny active budget"
    assert len(rt.execs) - len(frozen) >= rt.max_active - 1
    for cid in frozen:
        assert rt.bands[cid] is LODBand.ABSTRACT
        assert rt.frozen_at[cid] <= rt.now_s
        assert math.dist(rt.execs[cid].pos, focus) > rt.lod.route_radius
    near_ids = [c for c in rt.execs if c not in rt.frozen_at]
    assert all(rt.bands[c] is not LODBand.ABSTRACT for c in near_ids)

    # a citizen that was mid-trip when it froze
    moving = [c for c in frozen
              if rt.execs[c].state in (EmbodimentState.DRIVING, EmbodimentState.ON_FOOT)]
    assert moving, "no frozen citizen was mid-trip"
    cid = moving[0]
    ex = rt.execs[cid]
    froze_at, was = rt.frozen_at[cid], ex.pos
    assert rt.now_s - froze_at > 0.0

    clock = rt.now_s
    rt.set_focus_xy(ex.pos)
    rt.advance(1.0, hour)
    assert rt.now_s == pytest.approx(clock + 1.0), "catch-up disturbed the clock"
    assert cid not in rt.frozen_at, "the focus did not re-activate the citizen"
    assert rt.bands[cid] is not LODBand.ABSTRACT
    # the catch-up ran for exactly the frozen interval and left the clock intact
    catch = [t for t in rt.transitions
             if t["citizen_id"] == cid and t.get("catch_up_s") is not None]
    assert catch, "no catch-up recorded"
    assert catch[-1]["catch_up_s"] == pytest.approx(clock - froze_at, abs=1.1)
    assert math.dist(ex.pos, was) > 1.0, "the caught-up citizen did not advance"

    snap = rt.snapshot(include_routes=False)
    assert {r["citizen_id"] for r in snap["citizens"]} == set(rt.execs)
    assert _row(snap, cid)["band"] in ("physical", "route_simulated")


# --------------------------------------------------------------------------- #
# physical reports from Godot bodies
# --------------------------------------------------------------------------- #
def test_physical_report_holds_a_walker_back_but_never_pushes_it_forward(bundle):
    rt = _runtime(bundle, only={CITIZEN})
    ex = rt.execs[CITIZEN]
    hour = 7.49
    rt.set_focus_xy(ex.pos)
    hour, ok = _advance_until(rt, hour,
                              lambda e: e.state is EmbodimentState.ON_FOOT and e.ped is not None,
                              focus="follow")
    assert ok and ex.has_body, "citizen 4 is not an embodied walker"
    ped = ex.ped
    for _ in range(60):
        if ex.ped is not None and ex.ped.dist >= 20.0:
            break
        rt.set_focus_xy(ex.pos)
        rt.advance(1.0, hour)
    planned = ex.ped.dist
    assert ex.ped is ped and planned >= 20.0

    # physics reports the body 10 m BEHIND the plan: progress is pulled back
    behind = ex.ped.path.point_at(planned - 10.0)
    applied = rt.apply_physical_report([{"id": f"cit:{CITIZEN}", "x": behind[0],
                                         "z": behind[1], "blocked": False}], 1.0)
    assert applied == 1
    assert ex.ped.dist < planned
    assert ex.ped.dist == pytest.approx(planned - 10.0 + 3.0, abs=1e-6)
    assert ex.pos == pytest.approx(ex.ped.path.point_at(ex.ped.dist))

    # physics reports the body 30 m AHEAD of the plan: ignored
    held = ex.ped.dist
    ahead = ex.ped.path.point_at(held + 30.0)
    assert rt.apply_physical_report([{"id": f"cit:{CITIZEN}", "x": ahead[0],
                                      "z": ahead[1], "blocked": False}], 1.0) == 1
    assert ex.ped.dist == pytest.approx(held), "a report must never advance the plan"

    # a blocked body is counted
    blocked_before = ex.blocked_events
    here = ex.pos
    for i in range(3):
        rt.apply_physical_report([{"id": f"cit:{CITIZEN}", "x": here[0], "z": here[1],
                                   "blocked": True}], 1.0)
        assert ex.blocked_events == blocked_before + i + 1
    assert ex.ped.blocked is True and ex.ped.blocked_s > 0.0

    # unknown bodies and un-embodied citizens are ignored, not invented
    assert rt.apply_physical_report([{"id": "cit:999999", "x": 0.0, "z": 0.0}], 1.0) == 0
    assert rt.apply_physical_report([{"id": "veh:999999", "x": 0.0, "z": 0.0}], 1.0) == 0
    rt.set_focus_xy((ex.pos[0] + FAR, ex.pos[1] + FAR))
    rt.advance(1.0, hour)
    assert ex.has_body is False
    assert rt.apply_physical_report([{"id": f"cit:{CITIZEN}", "x": here[0],
                                      "z": here[1]}], 1.0) == 0

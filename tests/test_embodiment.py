"""Package 2 certification: physical citizen embodiment.

Covers the ten required embodiment tests from the milestone brief. The
load-bearing property throughout: embodiment is a *pure, derived, RNG-free*
authoritative interpretation of where an identified citizen is — so it is
deterministic, survives promote/demote and save/load, and is provably
epidemic-neutral (the macro curve is bit-identical whether embodiment is computed
or not).
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.citizen import CitizenProfile, ScheduleEntry
from asphodel import npc
from asphodel.embodiment import (
    CitySpatialContext, resolve_physical_location, LocationMode, Movement,
    LOCATION_SCHEMA_VERSION,
)
from asphodel.bundle_population import load_bundle_population
from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.save import save_world, load_world_file


BUNDLE = "madisonville_tx"


def _ctx():
    return CitySpatialContext.from_bundle_dir(resolve_bundle_dir(BUNDLE))


def _pop():
    return load_bundle_population(resolve_bundle_dir(BUNDLE))


def _work_hour(schedule):
    for e in schedule:
        if e.activity == "work":
            return (e.start_hour + min(e.end_hour, 24.0)) / 2.0 % 24.0
    return None


def _activity_hour(schedule, activity):
    for e in schedule:
        if e.activity == activity:
            return (e.start_hour + min(e.end_hour, 23.999)) / 2.0 % 24.0
    return None


# --------------------------------------------------------------------------- #
# 1. Determinism: same city + citizen + seed + time => same physical location
# --------------------------------------------------------------------------- #
def test_1_determinism_same_inputs_same_location():
    ctx = _ctx()
    pop = _pop()
    c = pop[0]
    kw = dict(citizen_id=c.citizen_id, schedule=c.schedule, hour=13.0,
              home_xy=c.home_xy, work_xy=c.work_xy,
              home_zone=c.home_zone, work_zone=c.work_zone, ctx=ctx)
    a = resolve_physical_location(**kw)
    b = resolve_physical_location(**kw)
    assert a.to_dict() == b.to_dict()
    assert a.version == LOCATION_SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# 2. An on-shift worker resolves to their real workplace building
# --------------------------------------------------------------------------- #
def test_2_on_shift_nurse_at_workplace_building():
    ctx = _ctx()
    pop = _pop()
    nurses = [c for c in pop if c.occupation == "nurse" and c.work_xy is not None]
    assert nurses, "bundle has no nurse with a workplace"
    c = nurses[0]
    h = _work_hour(c.schedule)
    assert h is not None
    loc = resolve_physical_location(
        citizen_id=c.citizen_id, schedule=c.schedule, hour=h,
        home_xy=c.home_xy, work_xy=c.work_xy,
        home_zone=c.home_zone, work_zone=c.work_zone, ctx=ctx)
    assert loc.activity == "work"
    assert loc.mode == LocationMode.BUILDING
    # At the real workplace coordinate, and at the building nearest to it.
    assert math.hypot(loc.x - c.work_xy[0], loc.y - c.work_xy[1]) < 1.0
    assert loc.building_id == ctx.nearest_building(c.work_xy)
    assert loc.building_id >= 0


# --------------------------------------------------------------------------- #
# 3. An off-shift citizen resolves home when the schedule says home
# --------------------------------------------------------------------------- #
def test_3_off_shift_citizen_at_home():
    ctx = _ctx()
    pop = _pop()
    c = next(c for c in pop if c.home_xy is not None)
    h = _activity_hour(c.schedule, "sleep")
    assert h is not None
    loc = resolve_physical_location(
        citizen_id=c.citizen_id, schedule=c.schedule, hour=h,
        home_xy=c.home_xy, work_xy=c.work_xy,
        home_zone=c.home_zone, work_zone=c.work_zone, ctx=ctx)
    assert loc.activity in ("sleep", "leisure", "idle")
    assert loc.mode == LocationMode.BUILDING
    assert math.hypot(loc.x - c.home_xy[0], loc.y - c.home_xy[1]) < 1.0


# --------------------------------------------------------------------------- #
# 4. A commuter occupies a real road route, not a synthetic coordinate
# --------------------------------------------------------------------------- #
def test_4_commuter_on_real_road():
    ctx = _ctx()
    pop = _pop()
    commuters = [c for c in pop
                 if c.work_xy is not None and _activity_hour(c.schedule, "commute")]
    assert commuters, "no commuters in bundle"
    # A commuting citizen must be snapped onto the real road network — measurably
    # closer to a road than the straight-line midpoint between home and work.
    got_on_road = False
    for c in commuters:
        h = _activity_hour(c.schedule, "commute")
        loc = resolve_physical_location(
            citizen_id=c.citizen_id, schedule=c.schedule, hour=h,
            home_xy=c.home_xy, work_xy=c.work_xy,
            home_zone=c.home_zone, work_zone=c.work_zone, ctx=ctx)
        assert loc.activity == "commute"
        assert loc.mode == LocationMode.STREET
        assert loc.movement == Movement.COMMUTING
        # It is on a real road vertex (snapped), so distance to the road is ~0.
        if ctx.distance_to_road((loc.x, loc.y)) < 1.0:
            got_on_road = True
    assert got_on_road, "no commuter resolved onto a real road segment"


# --------------------------------------------------------------------------- #
# Helpers for World-level tests
# --------------------------------------------------------------------------- #
def _bundle_world(seed=0, focus_zone=None, with_ctx=True):
    from asphodel.bridge.worldfactory import world_from_bundle
    w = world_from_bundle(BUNDLE, seed=seed,
                          micro_params=MicroParams(area_size=100.0,
                                                   infection_radius=2.0,
                                                   mixing_step_frac=0.12))
    pop = _pop()
    w.set_citizens(pop)
    if with_ctx:
        w.set_spatial_context(_ctx())
    if focus_zone is not None:
        w.set_focus([focus_zone])
    return w, pop


def _busy_zone(pop):
    from collections import Counter
    hz = Counter(c.home_zone for c in pop if c.home_zone is not None)
    return hz.most_common(1)[0][0]


# --------------------------------------------------------------------------- #
# 5. Identified citizen survives promote -> demote -> re-promote coherently
# --------------------------------------------------------------------------- #
def test_5_promote_demote_repromote_spatial_continuity():
    pop = _pop()
    zone = _busy_zone(pop)
    w, _ = _bundle_world(seed=1, focus_zone=zone)
    w.step()
    assert zone in w.promoted
    az = w.promoted[zone]
    ids = az.citizen_id[az.identified_slots()]
    assert ids.size > 0
    cid = int(ids[0])
    before = w.physical_location(cid)
    assert before is not None

    # Demote by dropping focus and advancing until it leaves the live set.
    w.set_focus([])
    for _ in range(60):
        w.step()
        if zone not in w.promoted:
            break
    assert zone not in w.promoted
    # Location is still coherent while demoted (pure function of schedule/hour).
    mid = w.physical_location(cid)
    assert mid is not None and mid.citizen_id == cid

    # Re-promote; the same citizen resolves to a coherent location for the hour.
    w.set_focus([zone])
    w.step()
    assert zone in w.promoted
    after = w.physical_location(cid)
    assert after is not None and after.citizen_id == cid
    # Same schedule => at the same hour the location matches deterministically.
    h = w.current_hour()
    direct = resolve_physical_location(
        citizen_id=cid, schedule=w._schedules[cid], hour=h,
        home_xy=w._spatial[cid][0], work_xy=w._spatial[cid][1],
        home_zone=w._spatial[cid][2], work_zone=w._spatial[cid][3],
        action=w._citizen_action(cid), zone=w._spatial[cid][2], ctx=w.spatial_ctx)
    assert after.to_dict() == direct.to_dict()


# --------------------------------------------------------------------------- #
# 6. Roster citizen leaves and returns as same identity + coherent place state
# --------------------------------------------------------------------------- #
def test_6_roster_citizen_returns_coherent():
    pop = _pop()
    zone = _busy_zone(pop)
    w, _ = _bundle_world(seed=2, focus_zone=zone)
    w.step()
    az = w.promoted[zone]
    cid = int(az.citizen_id[az.identified_slots()][0])
    w.interact_with(cid)
    assert w.roster.contains(cid)
    loc_before = w.physical_location(cid)

    w.set_focus([])
    for _ in range(60):
        w.step()
        if zone not in w.promoted:
            break
    # advance more, then return
    for _ in range(4):
        w.step()
    w.set_focus([zone])
    w.step()
    assert w.roster.contains(cid)                    # same identity persists
    az2 = w.promoted[zone]
    assert (az2.citizen_id == cid).any()             # re-embodied as same person
    loc_after = w.physical_location(cid)
    assert loc_after is not None
    # Coherent: a real, finite world position tied to the same citizen id.
    assert loc_after.citizen_id == cid
    assert math.isfinite(loc_after.x) and math.isfinite(loc_after.y)


# --------------------------------------------------------------------------- #
# 7. Embodiment on/off does not alter epidemic outputs
# --------------------------------------------------------------------------- #
def test_7_embodiment_is_epidemic_neutral():
    pop = _pop()
    zone = _busy_zone(pop)

    # World A: embodiment fully exercised (ctx attached, snapshot every tick).
    wa, _ = _bundle_world(seed=7, focus_zone=zone, with_ctx=True)
    # World B: no spatial context, embodiment never queried.
    wb, _ = _bundle_world(seed=7, focus_zone=zone, with_ctx=False)

    def totals(w):
        s = w.sim
        return [round(float(getattr(s, n).sum()), 9) for n in ("S", "E", "Ia", "Is", "R", "D")]

    for _ in range(40):
        wa.step()
        # Exercise the embodiment path every tick (snapshot computes it).
        snap = wa.snapshot()
        if snap["agents"]:
            _ = next(iter(snap["agents"].values()))["embodiment"]
        wb.step()
    assert totals(wa) == totals(wb), "embodiment perturbed the epidemic"


# --------------------------------------------------------------------------- #
# 8. Population conservation remains exact (with embodiment active)
# --------------------------------------------------------------------------- #
def test_8_population_conservation():
    pop = _pop()
    zone = _busy_zone(pop)
    w, _ = _bundle_world(seed=8, focus_zone=zone, with_ctx=True)
    total0 = float((w.sim.S + w.sim.E + w.sim.Ia + w.sim.Is + w.sim.R + w.sim.D).sum())
    for _ in range(50):
        w.step()
        _ = w.snapshot()
        total = float((w.sim.S + w.sim.E + w.sim.Ia + w.sim.Is + w.sim.R + w.sim.D).sum())
        assert abs(total - total0) < 1e-6, f"population drifted: {total} vs {total0}"


# --------------------------------------------------------------------------- #
# 9. Replay determinism remains intact
# --------------------------------------------------------------------------- #
def test_9_replay_determinism():
    pop = _pop()
    zone = _busy_zone(pop)

    def run():
        w, _ = _bundle_world(seed=9, focus_zone=zone, with_ctx=True)
        traj = []
        for _ in range(30):
            w.step()
            snap = w.snapshot()
            loc = None
            for z, ag in snap["agents"].items():
                emb = ag["embodiment"]
                for i, cid in enumerate(ag["citizen_id"]):
                    if cid >= 0:
                        loc = (cid, tuple(round(v, 6) for v in emb["world_xy"][i]))
                        break
                if loc:
                    break
            traj.append(loc)
        return traj

    assert run() == run(), "embodiment replay was non-deterministic"


# --------------------------------------------------------------------------- #
# 10. Save/load restores physical state deterministically
# --------------------------------------------------------------------------- #
def test_10_saveload_restores_physical_state(tmp_path):
    pop = _pop()
    zone = _busy_zone(pop)
    w, _ = _bundle_world(seed=10, focus_zone=zone, with_ctx=True)
    w.step()
    az = w.promoted[zone]
    cid = int(az.citizen_id[az.identified_slots()][0])
    w.interact_with(cid)
    for _ in range(5):
        w.step()

    loc_before = w.physical_location(cid).to_dict()

    path = str(tmp_path / "emb.json")
    save_world(w, path, bundle=BUNDLE, player_citizen=cid)
    reloaded = load_world_file(path)
    # Re-attach the same static geometry the session would on LOAD.
    reloaded.set_spatial_context(_ctx())

    loc_after = reloaded.physical_location(cid).to_dict()
    assert loc_after == loc_before, "physical state not restored deterministically"

    # And continuation stays deterministic in the embodied position.
    def step_and_loc(world):
        world.step()
        return world.physical_location(cid).to_dict()

    assert step_and_loc(w) == step_and_loc(reloaded)


if __name__ == "__main__":
    import pathlib
    import tempfile
    import types
    import inspect
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            if "tmp_path" in inspect.signature(fn).parameters:
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print("ok", name)
    print("embodiment certified")

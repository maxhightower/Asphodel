"""Save/load of the embodied world (ASPHODEL_EMBODIED_MOBILITY_V1 + save v3).

A trip is interrupted at four physically different moments — mid-walk,
mid-drive, in the car at the parking anchor, and inside the destination
building — saved to JSON, reloaded into a fresh World, and continued. The
reloaded world must be the same world: the same physical location, the same
mobility row, the same vehicle, and a continuation that stays bit-identical.

Also guarded: SAVE_VERSION is 3, a v2 save (no mobility block, no sub-tick
clock) still loads, and a world WITHOUT mobility keeps the legacy FAR
schedule-derived location authority exactly as before.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams, embodiment, npc
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodiment import CitySpatialContext
from asphodel.save import SAVE_VERSION, load_world, world_state

CITY = "houston"
CITIZEN = 4
WORK = 4517
VEHICLE = "veh:4"
START_HOUR = 7.0
DT = 1.0                  # both the live and the reloaded world step identically
CONTINUE_S = 30 * 60.0
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _new_world(d, population, mobility=True):
    w = world_from_bundle(CITY, micro_params=MICRO)
    w.start_hour = START_HOUR
    w.set_citizens(population)
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    if mobility:
        w.enable_mobility(bundle_dir=d)
    return w


def _reload(state, d, population):
    """The save -> JSON -> World -> geometry -> mobility path a session takes."""
    w = load_world(json.loads(json.dumps(state)))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    return w


def _rows(w):
    snap = w.mobility.snapshot(include_routes=False)
    row = next(r for r in snap["citizens"] if r["citizen_id"] == CITIZEN)
    vrow = next(r for r in snap["vehicles"] if r["vehicle_id"] == VEHICLE)
    return row, vrow


def _state(w):
    return world_state(w, bundle=CITY, player_citizen=None)


CHECKPOINTS = ("walking", "driving", "parked_exiting", "inside_work")


def _phase(ex):
    if ex.state in (EmbodimentState.PARKED, EmbodimentState.EXITING_VEHICLE):
        return "parked_exiting"
    if ex.state is EmbodimentState.DRIVING:
        return "driving"
    if ex.state in (EmbodimentState.ON_FOOT, EmbodimentState.APPROACHING_VEHICLE):
        return "walking"
    if ex.building_id == WORK and ex.inside:
        return "inside_work"
    return None


@pytest.fixture(scope="module")
def interruptions():
    """Interrupt, save, reload and continue at four points of one commute."""
    d = _bundle_dir()
    population = load_bundle_population(d)
    live = _new_world(d, population)
    ex = live.mobility.execs[CITIZEN]
    home = live.mobility.records[CITIZEN].home_xy

    saves, live_after = {}, {}
    pending = []           # (name, target game-second for the continuation)
    for _ in range(5000):
        live.advance_seconds(DT, focus_xy=home)
        t = round(live.game_seconds, 3)
        phase = _phase(ex)
        if phase in CHECKPOINTS and phase not in saves:
            row, vrow = _rows(live)
            saves[phase] = {"t": t, "state": _state(live),
                            "loc": live.physical_location(CITIZEN).to_dict(),
                            "row": row, "vrow": vrow}
            pending.append((phase, t + CONTINUE_S))
        for name, when in list(pending):
            if t >= when - 1e-6:
                live_after[name] = json.dumps(_state(live), sort_keys=True)
                pending.remove((name, when))
        if len(saves) == len(CHECKPOINTS) and not pending:
            break

    assert set(saves) == set(CHECKPOINTS), f"only reached {sorted(saves)}"
    assert set(live_after) == set(CHECKPOINTS)

    out = {}
    for name, rec in saves.items():
        w2 = _reload(rec["state"], d, population)
        row2, vrow2 = _rows(w2)
        loc2 = w2.physical_location(CITIZEN).to_dict()
        n = int(round(CONTINUE_S / DT))
        for _ in range(n):
            w2.advance_seconds(DT, focus_xy=home)
        after2 = json.dumps(_state(w2), sort_keys=True)
        out[name] = {"before": rec, "loc2": loc2,
                     "row2": row2, "vrow2": vrow2,
                     "after_live": live_after[name], "after_loaded": after2}
    out["_dir"] = d
    out["_pop"] = population
    return out


# A vehicle's FINISHED route is not persisted (dead state once the car has
# parked), so the two route-derived report fields of a parked car do not
# survive the reload. Everything that describes where and what the car IS does.
_DEAD_ROUTE_FIELDS = ("progress", "segment")


@pytest.mark.parametrize("phase", CHECKPOINTS)
def test_reloaded_world_is_the_same_world(interruptions, phase):
    rec = interruptions[phase]
    assert rec["before"]["loc"] == rec["loc2"], "physical location changed over save/load"
    assert rec["before"]["row"] == rec["row2"], "mobility row changed over save/load"
    before, after = dict(rec["before"]["vrow"]), dict(rec["vrow2"])
    if phase in ("parked_exiting", "inside_work"):
        for k in _DEAD_ROUTE_FIELDS:
            before.pop(k), after.pop(k)
    assert before == after, "vehicle row changed over save/load"
    assert rec["before"]["vrow"]["vehicle_id"] == VEHICLE
    for key in ("x", "y", "driver", "owner", "parked", "engine", "fidelity",
                "speed", "condition", "band"):
        assert rec["before"]["vrow"][key] == rec["vrow2"][key], key


@pytest.mark.parametrize("phase", CHECKPOINTS)
def test_continuation_is_bit_identical(interruptions, phase):
    rec = interruptions[phase]
    assert rec["after_live"] == rec["after_loaded"], \
        f"{phase}: the reloaded world diverged over the next 30 minutes"


def test_the_interruptions_really_were_different_moments(interruptions):
    states = {p: interruptions[p]["before"]["row"]["state"] for p in CHECKPOINTS}
    assert states["walking"] in ("on_foot", "approaching_vehicle")
    assert states["driving"] == "driving"
    assert states["parked_exiting"] in ("parked", "exiting_vehicle")
    assert states["inside_work"] in ("inside_building", "doing_activity")
    assert interruptions["inside_work"]["before"]["row"]["building_id"] == WORK
    # the drive interruption really was mid-route
    driving = interruptions["driving"]["before"]["row"]
    assert 0.0 < driving["progress"] < 1.0
    assert driving["vehicle_id"] == VEHICLE
    ts = [interruptions[p]["before"]["t"] for p in CHECKPOINTS]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


def test_save_version_and_block(interruptions):
    assert SAVE_VERSION == 3
    st = interruptions["driving"]["before"]["state"]
    assert st["save_version"] == 3
    assert st["mobility"] is not None
    assert st["mobility"]["version"] >= 1
    assert str(CITIZEN) in st["mobility"]["citizens"]
    assert VEHICLE in st["mobility"]["vehicles"]
    assert st["world"]["subtick_s"] >= 0.0


def test_v2_save_still_loads_without_mobility(interruptions):
    st = json.loads(json.dumps(interruptions["driving"]["before"]["state"]))
    st["save_version"] = 2
    st.pop("mobility")
    st["world"].pop("subtick_s")
    w = load_world(st)
    assert w.mobility is None
    assert w._pending_mobility_state is None
    assert w._subtick_s == 0.0
    # and it is still a usable world
    w.step()
    assert w.sim.tick >= 1


def test_world_without_mobility_uses_the_legacy_far_authority():
    d = _bundle_dir()
    population = load_bundle_population(d)
    w = _new_world(d, population, mobility=False)
    assert w.mobility is None
    cid = CITIZEN
    got = w.physical_location(cid)
    assert got is not None and got.citizen_id == cid
    home_xy, work_xy, hz, wz = w._spatial.get(cid, (None, None, None, None))
    home_bid, work_bid = w._buildings.get(cid, (None, None))
    expected = embodiment.resolve_physical_location(
        citizen_id=cid, schedule=w._schedules.get(cid, []), hour=w.current_hour(),
        home_xy=home_xy, work_xy=work_xy, home_zone=hz, work_zone=wz,
        action=w._citizen_action(cid), zone=hz, ctx=w.spatial_ctx,
        home_building_id=home_bid, work_building_id=work_bid)
    assert got.to_dict() == expected.to_dict()
    # the legacy path is unchanged by the milestone: still pure/derived
    assert w.physical_location(cid).to_dict() == got.to_dict()
    assert "mobility" not in w.snapshot()

"""M5 tests: deterministic save / load.

Covers the M5 exit gate:

* full process-destruction + reload works (save to disk, drop the object, reload),
* **deterministic continuation matches uninterrupted execution** — final AND
  intermediate authoritative state are bit-identical,
* promoted-zone state, roster, interventions, focus, and player identity survive,
* the schema is versioned; corrupted/incompatible saves fail safely.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.citizen import CitizenProfile, ScheduleEntry
from asphodel.save import (save_world, load_world, load_world_file, world_state,
                           SAVE_VERSION, SaveError)


DAY = [ScheduleEntry(0.0, 7.0, "sleep", "h"), ScheduleEntry(7.0, 9.0, "commute", "r"),
       ScheduleEntry(9.0, 17.0, "work", "o"), ScheduleEntry(17.0, 24.0, "leisure", "h")]


def _cfg(rows=4, cols=4, pop=1000.0, n_days=60.0):
    c = ScenarioConfig()
    c.model.graph.grid_rows = rows
    c.model.graph.grid_cols = cols
    c.model.graph.population_per_zone = pop
    c.n_days = n_days
    return c


def _micro():
    return MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _world():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    allc = []
    cid = 0
    for z in range(16):
        for _ in range(30):
            allc.append(CitizenProfile(
                citizen_id=cid, city="x", age=30, age_band="a", occupation="w",
                shift="d", home_district="d", work_district="d", home_zone=z,
                work_zone=z, schedule=DAY, inventory={}, spawn_hour=8.0,
                current_location="o", current_activity="work", current_task=""))
            cid += 1
    w.set_citizens(allc)
    return w


def _totals(w):
    s = w.sim
    return tuple(round(float(getattr(s, n).sum()), 9)
                 for n in ("S", "E", "Ia", "Is", "R", "D"))


def _trace(w):
    """A richer fingerprint to catch compensating errors: totals + belief sum +
    promoted set + roster ids + official signal."""
    s = w.sim
    return (_totals(w), round(float(s.belief.sum()), 9),
            tuple(w.promoted_zones()), tuple(w.roster.ids()),
            round(float(s.official_signal), 9), int(s.tick))


def _script(w, i):
    if i == 5:
        w.set_focus([5])
    if i == 6:
        w.interact_with(3)
    if i == 10:
        w.intervene("cordon", zones=[5])
    if i == 12:
        w.intervene("broadcast", level=1.0)


# --------------------------------------------------------------------------- #
# deterministic continuation (load-bearing)
# --------------------------------------------------------------------------- #
def test_deterministic_continuation_matches_uninterrupted(tmp_path):
    N, K = 160, 70

    # Run A: uninterrupted 0 -> N, recording the full trace.
    wa = _world()
    trace_a = []
    for i in range(N):
        _script(wa, i)
        wa.step()
        trace_a.append(_trace(wa))

    # Run B: 0 -> K, save, destroy, reload, K -> N.
    wb = _world()
    for i in range(K):
        _script(wb, i)
        wb.step()
    path = str(tmp_path / "save.json")
    save_world(wb, path, bundle="test", player_citizen=3)
    del wb
    wl = load_world_file(path)
    trace_b = []
    for i in range(K, N):
        _script(wl, i)          # i >= K, so no new scripted events fire
        wl.step()
        trace_b.append(_trace(wl))

    # The continued half is bit-identical to the uninterrupted run's tail.
    assert trace_b == trace_a[K:]
    assert trace_b[-1][0][5] > 0        # deaths accrued (a real run)


# --------------------------------------------------------------------------- #
# state survives the roundtrip
# --------------------------------------------------------------------------- #
def test_promoted_roster_intervention_identity_survive(tmp_path):
    w = _world()
    for i in range(70):
        _script(w, i)
        w.step()
    pre_promoted = w.promoted_zones()
    pre_roster = w.roster.ids()
    pre_cordon = bool(w.sim.cordoned[5])
    pre_broadcast = float(w.sim.broadcast_signal)

    path = str(tmp_path / "s.json")
    save_world(w, path, bundle="houston-ish", player_citizen=3)
    wl = load_world_file(path)

    assert wl.promoted_zones() == pre_promoted        # promoted zones survive
    assert wl.roster.ids() == pre_roster              # roster survives
    assert bool(wl.sim.cordoned[5]) == pre_cordon     # intervention survives
    assert float(wl.sim.broadcast_signal) == pre_broadcast
    assert 5 in wl.focus                              # focus survives
    # a promoted zone's identity arrays survive intact
    z = wl.promoted[pre_promoted[0]]
    assert z.citizen_id.shape[0] == z.pos.shape[0] == z.state.shape[0]


# --------------------------------------------------------------------------- #
# schema + safety
# --------------------------------------------------------------------------- #
def test_save_is_json_and_versioned(tmp_path):
    w = _world()
    w.set_focus([5])
    w.step()
    st = world_state(w, bundle="b", player_citizen=3)
    # fully JSON-serializable
    reloaded = json.loads(json.dumps(st))
    assert reloaded["save_version"] == SAVE_VERSION
    assert reloaded["game_identity"]["player_citizen"] == 3


def test_missing_file_fails_safely():
    try:
        load_world_file("/no/such/save.json")
        assert False, "expected SaveError"
    except SaveError as e:
        assert "cannot read" in str(e)


def test_incompatible_version_rejected():
    try:
        load_world({"save_version": SAVE_VERSION + 99})
        assert False, "expected SaveError"
    except SaveError as e:
        assert "incompatible" in str(e)


def test_missing_section_rejected():
    try:
        load_world({"save_version": SAVE_VERSION})
        assert False, "expected SaveError"
    except SaveError as e:
        assert "missing required section" in str(e)


# --------------------------------------------------------------------------- #
# via the bridge (Godot requests save/load; Python serializes)
# --------------------------------------------------------------------------- #
def test_bridge_save_load_roundtrip(tmp_path):
    from asphodel.bridge import WorldSession, PROTOCOL_VERSION
    from asphodel.bridge.protocol import Command

    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    s.handle({"cmd": Command.START_WORLD, "bundle": "madisonville_tx", "seed": 1})
    s.handle({"cmd": Command.SET_FOCUS, "zones": [33]})
    s.handle({"cmd": Command.ADVANCE, "ticks": 12})
    before = s.handle({"cmd": Command.ADVANCE, "ticks": 0})["totals"]

    path = str(tmp_path / "bridge.json")
    r = s.handle({"cmd": Command.SAVE, "path": path})
    assert r["ok"] and os.path.exists(path)

    # Fresh session loads it and continues from the identical state.
    s2 = WorldSession()
    s2.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    rl = s2.handle({"cmd": Command.LOAD, "path": path})
    assert rl["ok"] and rl["totals"] == before

    a = s.handle({"cmd": Command.ADVANCE, "ticks": 20})["totals"]
    b = s2.handle({"cmd": Command.ADVANCE, "ticks": 20})["totals"]
    assert a == b

    bad = s2.handle({"cmd": Command.LOAD, "path": "/no/such.json"})
    assert not bad["ok"] and bad["error"]["code"] == "bad_argument"


if __name__ == "__main__":
    import types
    import tempfile as _t
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            import inspect
            if "tmp_path" in inspect.signature(fn).parameters:
                import pathlib
                fn(pathlib.Path(_t.mkdtemp()))
            else:
                fn()
            print("ok", name)
    print("all M5 save/load tests passed")

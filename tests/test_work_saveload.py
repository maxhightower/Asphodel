"""Save/load of the work layer at six different moments
(ASPHODEL_SMART_OBJECTS_WORK_V1 §20-§22).

A Houston world is saved and restored the way a session restores one —

    load_world -> set_spatial_context -> enable_mobility -> enable_work

— while a citizen is:

* walking across rooms to a station (``phase == "to_object"``),
* using a station,
* waiting (a worker with nothing free, or a customer queued at a till),
* half way through a multi-step task (a cleaner carrying supplies from the
  store cupboard to the object it is going to clean),
* freshly interrupted by an emergency goal, and
* on its way home after leaving its shift.

For each moment the restored world must BE the world: identical sessions
(task, object, progress, phase, room), an identical reservation ledger,
identical object state deltas, identical events — and ten game minutes of both
must produce byte-identical save state.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.citizens.goals import Goal, GoalKind
from asphodel.embodiment import CitySpatialContext
from asphodel.save import load_world, world_state

CITY = "houston"
START_HOUR = 5.0
FAR = (9000.0, 9000.0)
CONTINUE_S = 10 * 60.0
END_HOUR = 17.0
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
MOMENTS = ("to_object", "using", "waiting", "carrying", "interrupted", "went_home")


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _state(w):
    return json.loads(json.dumps(world_state(w, bundle=CITY, player_citizen=None)))


def _reload(state, d):
    w = load_world(json.loads(json.dumps(state)))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    return w


def _fingerprint(w):
    wk = w.work
    return {
        "now_s": round(wk.now_s, 6),
        "activities": {c: a.to_dict() for c, a in sorted(wk.activities.items())},
        "ledger": wk.ledger.to_state(),
        "deltas": {int(b): r.state_deltas() for b, r in sorted(wk.registries.items())},
        "queues": {k: list(v) for k, v in sorted(wk.queues.items())},
        "employment": {c: e.to_dict() for c, e in sorted(wk.employment.items())},
        "events": list(wk.events),
        "event_seq": wk.event_seq,
        "shift_log": list(wk.shift_log),
        "reduced": dict(wk.reduced),
        "known_buildings": sorted(wk.registries),
    }


def _checkpoint(w, d, name, cid):
    state = _state(w)
    live_before = _fingerprint(w)
    w2 = _reload(state, d)
    rec = {"name": name, "cid": cid, "hour": w.current_hour(), "state": state,
           "live_before": live_before, "back_before": _fingerprint(w2)}
    w.advance_seconds(CONTINUE_S)
    w2.advance_seconds(CONTINUE_S)
    rec["live_after"] = json.dumps(_state(w), sort_keys=True)
    rec["back_after"] = json.dumps(_state(w2), sort_keys=True)
    rec["live_work_after"] = json.dumps(_fingerprint(w), sort_keys=True)
    rec["back_work_after"] = json.dumps(_fingerprint(w2), sort_keys=True)
    return rec


def _pick(w):
    """The first citizen (in id order) matching each moment we still need."""
    wk = w.work
    found = {}
    for cid, a in sorted(wk.activities.items()):
        if a.kind == "worker" and a.phase == "to_object" and a.waypoints and a.object_id:
            found.setdefault("to_object", cid)
        if a.kind == "worker" and a.phase == "using" and a.object_id:
            o = wk.registry(a.building_id).get(a.object_id)
            if o is not None and o.has("station"):
                found.setdefault("using", cid)
        if a.phase == "waiting" and (a.kind != "customer" or wk.queues.get(a.object_id or "")):
            found.setdefault("waiting", cid)
        if a.role == "cleaner" and a.carrying == "supplies" and a.phase in ("to_object", "using"):
            found.setdefault("carrying", cid)
    return found


@pytest.fixture(scope="module")
def checkpoints():
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO, seed=0)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    w.mobility.set_focus_xy(FAR)

    out = {}
    seen_seq = 0
    while len(out) < len(MOMENTS) and w.current_hour() < END_HOUR:
        w.advance_seconds(60.0)
        wk = w.work
        found = _pick(w)
        for name in ("to_object", "using", "waiting", "carrying"):
            if name not in out and name in found:
                out[name] = _checkpoint(w, d, name, found[name])
                break
        else:
            if "interrupted" not in out and w.current_hour() >= 10.0:
                working = [c for c, a in sorted(wk.activities.items())
                           if a.kind == "worker" and a.phase in ("using", "to_object")
                           and wk.ledger.held_by(c)]
                if working:
                    cid = working[0]
                    rt = w.mobility.citizens[cid]
                    seq0 = wk.event_seq
                    rt.push_goal(Goal(GoalKind.FLEE, target=rt.home_node, source="emergency",
                                      priority=0.92), w.mobility.graph)
                    hit = False
                    for _ in range(5):
                        w.advance_seconds(60.0)
                        hit = any(e["event"] == "WORK_INTERRUPTED" and e.get("citizen_id") == cid
                                  for e in wk.events if e["seq"] > seq0)
                        if hit:
                            break
                    if hit:
                        out["interrupted"] = _checkpoint(w, d, "interrupted", cid)
            elif "went_home" not in out:
                outs = [e for e in wk.events
                        if e["seq"] > seen_seq and e["event"] == "CLOCK_OUT"
                        and e.get("reason") in ("shift_end", "left")]
                if outs:
                    out["went_home"] = _checkpoint(w, d, "went_home", outs[0]["citizen_id"])
        seen_seq = wk.event_seq
    missing = [m for m in MOMENTS if m not in out]
    assert not missing, f"never reached: {missing} (stopped at {w.current_hour():.2f})"
    return out


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("moment", MOMENTS)
def test_the_sessions_survive_the_reload_exactly(checkpoints, moment):
    c = checkpoints[moment]
    assert c["back_before"]["activities"] == c["live_before"]["activities"]
    assert c["live_before"]["activities"], "no interior session was saved at all"
    assert c["back_before"]["now_s"] == c["live_before"]["now_s"]


@pytest.mark.parametrize("moment", ("to_object", "using", "waiting", "carrying"))
def test_the_citizen_of_interest_is_restored_field_for_field(checkpoints, moment):
    c = checkpoints[moment]
    cid = c["cid"]
    live = c["live_before"]["activities"][cid]
    back = c["back_before"]["activities"][cid]
    for key in ("task_id", "object_id", "progress_s", "duration_s", "phase", "room_id",
                "building_id", "kind", "role", "carrying", "task_instance", "waypoints",
                "worked_s", "session_start_s", "started_s", "next_s"):
        assert back[key] == live[key], (moment, cid, key, live[key], back[key])


def test_each_moment_really_was_the_moment_it_claims(checkpoints):
    to_obj = checkpoints["to_object"]
    a = to_obj["live_before"]["activities"][to_obj["cid"]]
    assert a["phase"] == "to_object" and a["waypoints"], a

    using = checkpoints["using"]
    b = using["live_before"]["activities"][using["cid"]]
    assert b["phase"] == "using" and b["object_id"] and b["progress_s"] >= 0.0

    waiting = checkpoints["waiting"]
    c = waiting["live_before"]["activities"][waiting["cid"]]
    assert c["phase"] == "waiting", c

    carry = checkpoints["carrying"]
    e = carry["live_before"]["activities"][carry["cid"]]
    assert e["carrying"] == "supplies" and e["role"] == "cleaner", e
    assert e["object_id"], "a carrying cleaner with no target object"

    interrupted = checkpoints["interrupted"]
    cid = interrupted["cid"]
    assert cid not in interrupted["live_before"]["activities"]
    rows = [s for s in interrupted["live_before"]["shift_log"] if s["citizen_id"] == cid]
    assert rows and rows[-1]["reason"].startswith("emergency"), rows[-1:]

    home = checkpoints["went_home"]
    outs = [x for x in home["live_before"]["events"]
            if x["event"] == "CLOCK_OUT" and x["citizen_id"] == home["cid"]]
    assert outs, "no CLOCK_OUT for the citizen that went home"
    assert home["cid"] not in home["live_before"]["activities"]


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_reservation_ledger_is_identical_after_the_reload(checkpoints, moment):
    c = checkpoints[moment]
    assert c["back_before"]["ledger"] == c["live_before"]["ledger"]
    assert c["live_before"]["ledger"]["holders"], "nothing was held at this moment"


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_object_state_deltas_are_identical_after_the_reload(checkpoints, moment):
    c = checkpoints[moment]
    assert c["back_before"]["deltas"] == c["live_before"]["deltas"]
    assert c["back_before"]["known_buildings"] == c["live_before"]["known_buildings"]
    assert any(c["live_before"]["deltas"].values()), "no object state changed all morning"


@pytest.mark.parametrize("moment", MOMENTS)
def test_events_employment_and_queues_survive_the_reload(checkpoints, moment):
    c = checkpoints[moment]
    for key in ("events", "event_seq", "employment", "queues", "shift_log", "reduced"):
        assert c["back_before"][key] == c["live_before"][key], (moment, key)


@pytest.mark.parametrize("moment", MOMENTS)
def test_a_ten_minute_continuation_is_byte_identical(checkpoints, moment):
    c = checkpoints[moment]
    assert c["back_work_after"] == c["live_work_after"], moment
    assert c["back_after"] == c["live_after"], moment


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_saved_state_carries_a_work_block(checkpoints, moment):
    st = checkpoints[moment]["state"]["work"]
    assert st is not None
    assert st["version"] == 1
    assert st["employment"], "no employment was persisted"
    assert isinstance(st["objects"], dict) and st["known_buildings"]
    assert st["event_seq"] >= len(st["events"])
    assert json.loads(json.dumps(st)) == st


def test_the_work_block_only_persists_changed_object_state(checkpoints):
    """The immutable half of an interior costs zero bytes: only the objects
    whose state moved away from the generated default are written."""
    st = checkpoints["using"]["state"]["work"]
    known = set(st["known_buildings"])
    assert len(known) > 100, len(known)
    changed = {int(b) for b, delta in st["objects"].items() if delta}
    assert changed, "no object state was persisted at all"
    assert changed <= known
    assert len(changed) < len(known), "every building wrote deltas: nothing is regenerated"


def test_a_restored_world_keeps_running_the_same_sessions(checkpoints):
    """Not just equal at t0: the two worlds stayed equal for ten minutes, and
    the work runtime actually did something in that time."""
    for moment in MOMENTS:
        c = checkpoints[moment]
        after = json.loads(c["live_work_after"])
        assert after["event_seq"] > c["live_before"]["event_seq"], moment
        assert after["now_s"] > c["live_before"]["now_s"], moment

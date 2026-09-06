"""Save/load of the cognition layer at three moments
(ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §22, §23).

A Houston world is saved and restored the way a session restores one —

    load_world -> set_spatial_context -> enable_mobility -> enable_outbreak
               -> enable_work -> enable_cognition

— while:

* a help task is running (a HELP_DECIDED has fired, its HELP_COMPLETED has
  not: the decision is in ``pending_help`` and the helper is mid-task),
* a warning has just been received (a told fact with its provenance, the
  told-set, the pair cooldown and the recipient's belief),
* a citizen has just decided to avoid a building on that hearsay (a
  belief-sourced goal in the CitizenRuntime and an entry in ``avoid_goals``).

Memories, relationships, social bookkeeping and the event stream must come
back identical (nothing derived is persisted: beliefs are recomputed), and
ten further game minutes of both worlds must be byte-identical.
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
from asphodel.cognition import memory as M
from asphodel.cognition.runtime import COGNITION_SCHEMA_VERSION
from asphodel.embodiment import CitySpatialContext
from asphodel.save import load_world, world_state

CITY = "houston"
START_HOUR = 5.0
FAR = (9000.0, 9000.0)
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
SHOP = 15873
SEED_AT_HOUR = 10.5
END_HOUR = 11.2
CONTINUE_S = 10 * 60.0
MOMENTS = ("helping", "warned", "avoiding")


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
    w.enable_outbreak()
    w.enable_work()
    w.enable_cognition()
    return w


def _fingerprint(w):
    c = w.cognition
    return {
        "now_s": round(c.now_s, 6),
        "state": c.to_state(),
        "rows": {cid: c.row(cid) for cid in sorted(c.memories)},
        "beliefs": {cid: sorted(b.to_dict()["key"] for b in c.beliefs(cid).values())
                    for cid in sorted(c.memories)},
        "belief_values": {cid: {k: round(b.value, 6) for k, b in sorted(c.beliefs(cid).items())}
                          for cid in sorted(c.memories)},
        "avoid_rooms": {f"{cid}:{c.avoid_goals[cid]['building_id']}":
                        sorted(c.avoid_rooms(cid, c.avoid_goals[cid]["building_id"]))
                        for cid in sorted(c.avoid_goals)},
        "goals": {cid: [g.to_dict() for g in w.mobility.citizens[cid].goals.goals]
                  for cid in sorted(c.avoid_goals) if cid in w.mobility.citizens},
    }


def _checkpoint(w, d, name, cid):
    state = _state(w)
    live_before = _fingerprint(w)
    w2 = _reload(state, d)
    rec = {"name": name, "cid": cid, "hour": w.current_hour(), "state": state,
           "live_before": live_before, "back_before": _fingerprint(w2)}
    for _ in range(int(CONTINUE_S // 60)):
        w.advance_seconds(60.0, focus_xy=FAR)
        w2.advance_seconds(60.0, focus_xy=FAR)
    rec["live_after"] = json.dumps(_state(w), sort_keys=True)
    rec["back_after"] = json.dumps(_state(w2), sort_keys=True)
    rec["live_cog_after"] = json.dumps(_fingerprint(w), sort_keys=True)
    rec["back_cog_after"] = json.dumps(_fingerprint(w2), sort_keys=True)
    return rec


@pytest.fixture(scope="module")
def checkpoints():
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO, seed=0)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    c = w.enable_cognition()
    ob = w.enable_outbreak("classic_zombie_fast", seed_index_case=False)
    w.mobility.set_focus_xy(FAR)

    out = {}
    seeded = None
    while len(out) < len(MOMENTS) and w.current_hour() < END_HOUR:
        w.advance_seconds(60.0, focus_xy=FAR)
        if seeded is None and w.current_hour() >= SEED_AT_HOUR:
            inside = sorted(cid for cid, a in w.work.activities.items()
                            if a.building_id == SHOP and a.kind == "customer"
                            and w.mobility.execs[cid].inside
                            and w.mobility.execs[cid].building_id == SHOP)
            if inside:
                seeded = inside[0]
                ob.seed_index_case(seeded)
        if "helping" not in out and c.pending_help:
            helper = sorted(c.pending_help)[0]
            out["helping"] = _checkpoint(w, d, "helping", helper)
            continue
        if "warned" not in out:
            rec = [e for e in c.events if e["event"] == "WARNING_RECEIVED"]
            if rec:
                out["warned"] = _checkpoint(w, d, "warned", rec[-1]["citizen_id"])
                continue
        if "avoiding" not in out and c.avoid_goals:
            out["avoiding"] = _checkpoint(w, d, "avoiding", sorted(c.avoid_goals)[0])
            continue
    missing = [m for m in MOMENTS if m not in out]
    assert not missing, f"never reached: {missing} (stopped at {w.current_hour():.2f})"
    out["_seeded"] = seeded
    return out


# --------------------------------------------------------------------------- #
def test_each_moment_really_was_the_moment_it_claims(checkpoints):
    helping = checkpoints["helping"]
    st = helping["live_before"]["state"]
    assert st["pending_help"], "no help decision was in flight"
    cid = str(helping["cid"])
    assert cid in st["pending_help"], (cid, sorted(st["pending_help"]))
    row = st["pending_help"][cid]
    assert row["event"] == "HELP_DECIDED" and row["beneficiary"] != helping["cid"]
    done = [e for e in st["events"] if e["event"] == "HELP_COMPLETED"
            and e.get("decision_seq") == row["seq"]]
    assert not done, "the help had already completed at this checkpoint"

    warned = checkpoints["warned"]
    rows = [e for e in warned["live_before"]["state"]["events"] if e["event"] == "WARNING_RECEIVED"]
    assert rows, "no warning had been received"
    last = rows[-1]
    assert last["citizen_id"] == warned["cid"]
    facts = warned["live_before"]["state"]["memories"][str(warned["cid"])]["facts"]
    told = [f for f in facts if f["source"] == M.TOLD]
    assert told, "the warned citizen holds no told fact"

    avoiding = checkpoints["avoiding"]
    st = avoiding["live_before"]["state"]
    assert st["avoid_goals"], "nobody was avoiding anything"
    held = st["avoid_goals"][str(avoiding["cid"])]
    assert held["building_id"] and "goal_id" in held
    goals = avoiding["live_before"]["goals"][avoiding["cid"]]
    assert any(g["source"] == "belief" for g in goals), goals


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_cognition_state_survives_the_reload_byte_for_byte(checkpoints, moment):
    c = checkpoints[moment]
    live, back = c["live_before"]["state"], c["back_before"]["state"]
    assert json.dumps(back, sort_keys=True) == json.dumps(live, sort_keys=True), moment
    assert back["version"] == COGNITION_SCHEMA_VERSION
    assert c["back_before"]["now_s"] == c["live_before"]["now_s"]


@pytest.mark.parametrize("moment", MOMENTS)
def test_memories_and_relationships_come_back_fact_for_fact(checkpoints, moment):
    c = checkpoints[moment]
    live, back = c["live_before"]["state"], c["back_before"]["state"]
    assert live["memories"], "nothing was remembered by anybody"
    assert set(back["memories"]) == set(live["memories"])
    for cid, st in live["memories"].items():
        assert back["memories"][cid] == st, (moment, cid)
    assert live["relationships"]["rels"], "no relationship was persisted"
    assert back["relationships"] == live["relationships"]
    for key in ("told", "pair_last_s", "calls", "help_cooldown", "help_pairs", "help_log",
                "avoid_goals", "safe_since", "pending_help", "room_avoid_reported",
                "events", "event_seq", "counts", "work_seq", "ob_seq"):
        assert back[key] == live[key], (moment, key)


@pytest.mark.parametrize("moment", MOMENTS)
def test_beliefs_are_recomputed_not_stored_and_come_out_the_same(checkpoints, moment):
    """Nothing derived is persisted: the restored world re-derives identical
    beliefs and identical room-avoidance sets from the same facts."""
    c = checkpoints[moment]
    assert "beliefs" not in c["live_before"]["state"]
    assert c["back_before"]["belief_values"] == c["live_before"]["belief_values"], moment
    assert c["back_before"]["avoid_rooms"] == c["live_before"]["avoid_rooms"], moment
    assert c["back_before"]["rows"] == c["live_before"]["rows"], moment


@pytest.mark.parametrize("moment", MOMENTS)
def test_a_ten_minute_continuation_is_byte_identical(checkpoints, moment):
    c = checkpoints[moment]
    assert c["back_cog_after"] == c["live_cog_after"], moment
    assert c["back_after"] == c["live_after"], moment


@pytest.mark.parametrize("moment", MOMENTS)
def test_both_worlds_really_kept_thinking_for_those_ten_minutes(checkpoints, moment):
    c = checkpoints[moment]
    after = json.loads(c["live_cog_after"])
    before = c["live_before"]
    assert after["now_s"] > before["now_s"]
    assert after["state"]["event_seq"] > before["state"]["event_seq"], moment
    facts_before = sum(len(v["facts"]) for v in before["state"]["memories"].values())
    facts_after = sum(len(v["facts"]) for v in after["state"]["memories"].values())
    assert facts_after >= facts_before


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_saved_state_carries_a_cognition_block(checkpoints, moment):
    st = checkpoints[moment]["state"]["cognition"]
    assert st is not None
    assert st["version"] == COGNITION_SCHEMA_VERSION
    assert st["seed"] == 0 and st["now_s"] > 0.0
    assert st["memories"] and st["relationships"]["rels"]
    assert st["event_seq"] >= len(st["events"])
    assert json.loads(json.dumps(st)) == st


def test_the_help_in_flight_finishes_identically_in_both_worlds(checkpoints):
    """The restored helper does not restart, duplicate or drop the help task."""
    c = checkpoints["helping"]
    live = json.loads(c["live_cog_after"])["state"]
    back = json.loads(c["back_cog_after"])["state"]
    decision = c["live_before"]["state"]["pending_help"][str(c["cid"])]
    done = [e for e in live["events"] if e["event"] == "HELP_COMPLETED"
            and e.get("decision_seq") == decision["seq"]]
    assert len(done) == 1, "the help task did not complete exactly once"
    assert done == [e for e in back["events"] if e["event"] == "HELP_COMPLETED"
                    and e.get("decision_seq") == decision["seq"]]
    ben = str(done[0]["beneficiary"])
    helped = [f for f in live["memories"][ben]["facts"] if f["kind"] == M.HELPED_BY]
    assert helped, "the beneficiary does not remember being helped"
    assert helped == [f for f in back["memories"][ben]["facts"] if f["kind"] == M.HELPED_BY]


def test_the_avoidance_goal_is_the_same_goal_after_the_reload(checkpoints):
    c = checkpoints["avoiding"]
    cid = c["cid"]
    live = c["live_before"]["goals"][cid]
    back = c["back_before"]["goals"][cid]
    assert live == back, (live, back)
    beliefs = [g for g in live if g["source"] == "belief"]
    assert beliefs and beliefs[0]["reason"], beliefs
    assert c["live_before"]["state"]["avoid_goals"][str(cid)]["goal_id"] == beliefs[0]["id"]

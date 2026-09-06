"""Save/load of the dialogue layer at four moments
(ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 §10, §22, §23).

A Houston world is saved and restored the way a session restores one —

    load_world -> set_spatial_context -> enable_mobility -> enable_outbreak
               -> enable_work -> enable_cognition -> enable_dialogue

— while:

* a player conversation is open (the player is a registered citizen standing
  in a room with an NPC it has just greeted),
* a fact has just been told and received in a conversation,
* a help request has been accepted and its help task has not finished,
* a help request has just been refused.

Conversations, requests, cooldowns, the event stream and the counters must
come back identical, restoring must not put a single new word in anybody's
mouth, and ten further game minutes of both worlds must be byte-identical.
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
from asphodel.dialogue import acts as A
from asphodel.dialogue.runtime import DIALOGUE_SCHEMA_VERSION
from asphodel.dialogue.session import ACTIVE, PLAYER
from asphodel.embodiment import CitySpatialContext
from asphodel.save import load_world, world_state

CITY = "houston"
START_HOUR = 5.0
SEED_AT_HOUR = 10.0
END_HOUR = 11.5
SHOP = 15873
FAR = (9000.0, 9000.0)
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
CONTINUE_S = 10 * 60.0
MOMENTS = ("player_talking", "fact_received", "request_accepted", "request_refused")


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
    w.enable_dialogue()
    return w


def _fingerprint(w):
    dl = w.dialogue
    return {"now_s": round(dl.now_s, 6), "state": dl.to_state(),
            "snapshot": dl.snapshot(0),
            "rows": {cid: dl.row(cid) for cid in sorted({p for c in dl.conversations.values()
                                                         for p in c.participants})}}


def _co_present_pair(w):
    """Two citizens standing in the same room, available to talk."""
    dl, c = w.dialogue, w.cognition
    inside = [cid for cid, ex in sorted(w.mobility.execs.items()) if ex.inside]
    by_room = {}
    for cid in inside:
        ex = w.mobility.execs[cid]
        by_room.setdefault((int(ex.building_id), c._ctx(cid).get("room_id")), []).append(cid)
    for _, ids in sorted(by_room.items()):
        for a in ids:
            for b in ids:
                if a != b and dl.available(a, PLAYER)[0] and dl.available(b, PLAYER)[0] \
                        and dl.co_present(a, b)[0]:
                    return a, b
    return None


def _checkpoint(w, d, name):
    state = _state(w)
    live_before = _fingerprint(w)
    w2 = _reload(state, d)
    rec = {"name": name, "hour": w.current_hour(), "state": state,
           "live_before": live_before, "back_before": _fingerprint(w2)}
    for _ in range(int(CONTINUE_S // 60)):
        w.advance_seconds(60.0, focus_xy=FAR)
        w2.advance_seconds(60.0, focus_xy=FAR)
    rec["live_after"] = json.dumps(_state(w), sort_keys=True)
    rec["back_after"] = json.dumps(_state(w2), sort_keys=True)
    rec["live_dlg_after"] = json.dumps(_fingerprint(w), sort_keys=True)
    rec["back_dlg_after"] = json.dumps(_fingerprint(w2), sort_keys=True)
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
    dl = w.enable_dialogue()
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
        if "request_accepted" not in out:
            live = [r for r in dl.requests.values() if r.state == A.REQ_ACCEPTED]
            if live:
                out["request_accepted"] = _checkpoint(w, d, "request_accepted")
                out["request_accepted"]["request_id"] = live[0].request_id
                continue
        if "request_refused" not in out and any(r.state == A.REQ_REFUSED for r in dl.requests.values()):
            out["request_refused"] = _checkpoint(w, d, "request_refused")
            continue
        if "fact_received" not in out and any(e["event"] == "FACT_RECEIVED" for e in dl.events):
            out["fact_received"] = _checkpoint(w, d, "fact_received")
            continue
        if "player_talking" not in out and w.current_hour() >= 9.0:
            pair = _co_present_pair(w)
            if pair is not None:
                player, npc = pair
                res = w.talk(player, npc, A.GREET)
                if res and res.get("ok"):
                    out["player_talking"] = _checkpoint(w, d, "player_talking")
                    out["player_talking"]["pair"] = (player, npc)
                    out["player_talking"]["talk"] = res
                    continue
    missing = [m for m in MOMENTS if m not in out]
    assert not missing, f"never reached: {missing} (stopped at {w.current_hour():.2f})"
    out["_seeded"] = seeded
    return out


# --------------------------------------------------------------------------- #
def test_each_moment_really_was_the_moment_it_claims(checkpoints):
    st = checkpoints["player_talking"]["live_before"]["state"]
    player, npc = checkpoints["player_talking"]["pair"]
    assert st["player_sessions"], "no player conversation was open"
    conv_id = st["player_sessions"][str(player)]
    conv = st["conversations"][conv_id]
    assert conv["state"] == ACTIVE and conv["channel"] == PLAYER
    assert sorted(conv["participants"]) == sorted([player, npc])
    assert [r["act"] for r in conv["acts"]] == [A.GREET, A.GREET]
    talk = checkpoints["player_talking"]["talk"]
    # the two greetings are spoken while the session is opened, so they arrive
    # in the transcript rather than in this turn's "lines"
    assert len(talk["transcript"]) >= 2 and talk["lines"] == [], talk
    assert talk["state"] == ACTIVE and talk["npc"] == npc

    st = checkpoints["fact_received"]["live_before"]["state"]
    got = [e for e in st["events"] if e["event"] == "FACT_RECEIVED"]
    assert got, "no fact had been received"
    assert [e for e in st["events"] if e["event"] == "FACT_SHARED"]

    st = checkpoints["request_accepted"]["live_before"]["state"]
    rid = checkpoints["request_accepted"]["request_id"]
    req = st["requests"][rid]
    assert req["state"] == A.REQ_ACCEPTED and req["completed_s"] < 0
    assert not [e for e in st["events"] if e["event"] == "REQUEST_COMPLETED"
                and e["request_id"] == rid], "the help had already finished"

    st = checkpoints["request_refused"]["live_before"]["state"]
    refused = [r for r in st["requests"].values() if r["state"] == A.REQ_REFUSED]
    assert refused and refused[0]["reason"], refused
    assert [e for e in st["events"] if e["event"] == "REQUEST_REFUSED"]


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_saved_world_carries_a_dialogue_block(checkpoints, moment):
    saved = checkpoints[moment]["state"]
    assert saved.get("dialogue") is not None, moment
    assert saved["dialogue"]["version"] == DIALOGUE_SCHEMA_VERSION
    for key in ("conversations", "requests", "events", "counts", "player_sessions", "rendered",
                "ask_last", "request_last", "seq", "event_seq", "now_s"):
        assert key in saved["dialogue"], key


@pytest.mark.parametrize("moment", MOMENTS)
def test_the_dialogue_state_survives_the_reload_byte_for_byte(checkpoints, moment):
    c = checkpoints[moment]
    live, back = c["live_before"]["state"], c["back_before"]["state"]
    assert json.dumps(back, sort_keys=True) == json.dumps(live, sort_keys=True), moment
    assert c["back_before"]["now_s"] == c["live_before"]["now_s"]
    assert json.dumps(c["back_before"]["rows"], sort_keys=True) == \
        json.dumps(c["live_before"]["rows"], sort_keys=True)
    assert json.dumps(c["back_before"]["snapshot"], sort_keys=True) == \
        json.dumps(c["live_before"]["snapshot"], sort_keys=True)


@pytest.mark.parametrize("moment", MOMENTS)
def test_restoring_puts_no_new_words_in_anybodys_mouth(checkpoints, moment):
    live, back = c_live_back(checkpoints, moment)
    assert back["event_seq"] == live["event_seq"]
    assert back["counts"] == live["counts"]
    assert len(back["events"]) == len(live["events"])
    assert [e for e in back["events"] if e["event"] == "SPEECH_ACT"] == \
        [e for e in live["events"] if e["event"] == "SPEECH_ACT"]
    assert back["rendered"] == live["rendered"]


def c_live_back(checkpoints, moment):
    c = checkpoints[moment]
    return c["live_before"]["state"], c["back_before"]["state"]


@pytest.mark.parametrize("moment", MOMENTS)
def test_conversations_and_requests_come_back_act_for_act(checkpoints, moment):
    live, back = c_live_back(checkpoints, moment)
    assert live["conversations"], "no conversation was persisted"
    assert set(back["conversations"]) == set(live["conversations"])
    for cid, conv in live["conversations"].items():
        assert back["conversations"][cid] == conv, (moment, cid)
    assert set(back["requests"]) == set(live["requests"])
    for rid, req in live["requests"].items():
        assert back["requests"][rid] == req, (moment, rid)
    for key in ("ask_last", "request_last", "player_sessions", "seq"):
        assert back[key] == live[key], key


@pytest.mark.parametrize("moment", MOMENTS)
def test_ten_more_minutes_are_byte_identical(checkpoints, moment):
    c = checkpoints[moment]
    assert c["back_after"] == c["live_after"], moment
    assert c["back_dlg_after"] == c["live_dlg_after"], moment


def test_the_restored_player_conversation_is_still_the_same_conversation(checkpoints):
    c = checkpoints["player_talking"]
    player, npc = c["pair"]
    live, back = c["live_before"]["state"], c["back_before"]["state"]
    conv_id = live["player_sessions"][str(player)]
    assert back["player_sessions"][str(player)] == conv_id
    assert back["conversations"][conv_id]["state"] == ACTIVE
    assert back["conversations"][conv_id]["turn"] == live["conversations"][conv_id]["turn"]
    assert back["conversations"][conv_id]["transcript"] == live["conversations"][conv_id]["transcript"]

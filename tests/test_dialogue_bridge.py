"""Bridge v8: conversations on the wire (protocol §8,
ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 §11, §26).

Godot never decides what an NPC knows or says; it sends a structured act and
renders the answer. This exercises the v8 surface against a real Houston
world through WorldSession (transport-free, the same handlers the socket
serves):

    HELLO v8 -> START_WORLD houston (player_citizen) -> ADVANCE_TIME
    -> TALK GREET / ASK_FACT / ASK_SAFETY / END_CONVERSATION
    -> GET_DIALOGUE -> SAVE -> LOAD

plus the refusals a client must be able to handle without a dead session: a
citizen who is not co-present, an act the grammar does not have, and the
dialogue commands against a world that has none.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge import PROTOCOL_VERSION, WorldSession
from asphodel.bridge.protocol import Command, ErrorCode
from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.dialogue.runtime import DIALOGUE_SCHEMA_VERSION
from asphodel.dialogue.session import ACTIVE, ENDED, PLAYER

CITY = "houston"
START_HOUR = 5.0
PLAYER_CITIZEN = 129
FAR = [9000.0, 9000.0]
TALK_HOUR = 9.0


def _houston_or_skip():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _hello(s=None):
    s = s or WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    assert r["ok"], r
    return s, r


def _neighbour(s, player):
    """A citizen standing in the same room as the player citizen."""
    w = s.world
    ex = w.mobility.execs.get(player)
    if ex is None or not ex.inside:
        return None
    dl = w.dialogue
    for cid in sorted(w.mobility.execs):
        if cid == player:
            continue
        if dl.co_present(player, cid)[0] and dl.available(cid, PLAYER)[0]:
            return cid
    return None


def _far_citizen(s, player):
    w = s.world
    dl = w.dialogue
    for cid in sorted(w.mobility.execs):
        if cid != player and not dl.co_present(player, cid)[0]:
            return cid
    return None


@pytest.fixture(scope="module")
def session():
    """One world with a player citizen, advanced until that citizen shares a
    room with somebody (its workplace, mid-morning)."""
    _houston_or_skip()
    s, hello = _hello()
    start = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                      "start_hour": START_HOUR, "player_citizen": PLAYER_CITIZEN})
    assert start["ok"], start
    s.world.mobility.set_focus_xy(tuple(FAR))
    npc = None
    while s.world.current_hour() < 12.0:
        r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 300.0, "focus_xy": FAR})
        assert r["ok"], r
        if s.world.current_hour() >= TALK_HOUR:
            npc = _neighbour(s, PLAYER_CITIZEN)
            if npc is not None:
                break
    assert npc is not None, "the player citizen never shared a room with anybody"
    return {"s": s, "hello": hello, "start": start, "npc": npc,
            "far": _far_citizen(s, PLAYER_CITIZEN), "hour": s.world.current_hour()}


# --------------------------------------------------------------------------- #
# HELLO / START_WORLD
# --------------------------------------------------------------------------- #
def test_hello_advertises_v8_and_the_dialogue_commands(session):
    r = session["hello"]
    assert PROTOCOL_VERSION >= 8 and r["protocol_version"] == PROTOCOL_VERSION
    for cmd in (Command.TALK, Command.GET_DIALOGUE):
        assert cmd in r["commands"], cmd


def test_start_world_enables_dialogue_with_cognition(session):
    r = session["start"]
    assert r["cognition_enabled"] is True
    assert r["dialogue_enabled"] is True
    assert session["s"].world.dialogue is not None
    assert r["player_citizen"] == PLAYER_CITIZEN


def test_start_world_with_dialogue_false_leaves_it_off():
    _houston_or_skip()
    s, _ = _hello()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                  "start_hour": START_HOUR, "dialogue": False, "player_citizen": PLAYER_CITIZEN})
    assert r["ok"], r
    assert r["cognition_enabled"] is True and r["dialogue_enabled"] is False
    assert s.world.dialogue is None
    assert s.handle({"cmd": Command.GET_DIALOGUE})["dialogue"] is None
    bad = s.handle({"cmd": Command.TALK, "citizen_id": 0, "act": "GREET"})
    assert bad["ok"] is False and bad["error"]["code"] == ErrorCode.BAD_ARGUMENT
    assert s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 60.0, "focus_xy": FAR})["ok"]


def test_cognition_false_leaves_dialogue_off_too():
    _houston_or_skip()
    s, _ = _hello()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                  "start_hour": START_HOUR, "cognition": False})
    assert r["ok"] and r["dialogue_enabled"] is False, r
    assert s.world.dialogue is None


def test_the_dialogue_commands_need_a_started_world():
    s, _ = _hello()
    for msg in ({"cmd": Command.GET_DIALOGUE}, {"cmd": Command.TALK, "citizen_id": 1, "act": "GREET"}):
        r = s.handle(msg)
        assert r["ok"] is False and r["error"]["code"] == ErrorCode.NOT_STARTED, msg


# --------------------------------------------------------------------------- #
# TALK
# --------------------------------------------------------------------------- #
def test_talk_greet_opens_a_conversation_with_a_co_present_citizen(session):
    s, npc = session["s"], session["npc"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "GREET"})
    assert r["ok"], r
    assert r["player_citizen"] == PLAYER_CITIZEN and r["npc"] == npc
    assert r["state"] == ACTIVE and r["conv_id"]
    assert r["transcript"] and len(r["transcript"]) >= 2
    assert set(r["options"]) >= {"ASK_FACT", "ASK_SAFETY", "END_CONVERSATION"}
    assert 0.0 <= r["warmth"] <= 1.0
    assert r["dialogue_enabled"] is True
    assert json.loads(json.dumps(r)) == r
    session["conv_id"] = r["conv_id"]


def test_talk_ask_fact_returns_acts_and_lines(session):
    s, npc = session["s"], session["npc"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "ASK_FACT",
                  "args": {"building_id": s.world.mobility.execs[PLAYER_CITIZEN].building_id}})
    assert r["ok"], r
    assert r["acts"] and r["lines"] and len(r["acts"]) == len(r["lines"])
    asked = r["acts"][0]
    assert asked["act"] == "ASK_FACT" and asked["speaker"] == PLAYER_CITIZEN
    answer = r["acts"][-1]
    assert answer["speaker"] == npc and answer["act"] == "ANSWER"
    assert isinstance(answer["line"], str) and answer["line"].strip()
    if answer["proposition"] and answer["proposition"]["kind"] != "UNKNOWN":
        assert answer["proposition"]["event_ref"], answer
        assert answer["proposition"]["epistemic"] != "UNKNOWN"
    else:
        assert answer["line"] in ("I don't know.", "I'm not sure.",
                                  "I don't remember it clearly any more."), answer


def test_talk_ask_safety_answers_about_where_the_player_stands(session):
    s, npc = session["s"], session["npc"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "ASK_SAFETY"})
    assert r["ok"], r
    assert r["lines"], r
    question = r["acts"][0]
    assert question["act"] == "ASK_SAFETY"
    assert question["proposition"]["building_id"] == \
        int(s.world.mobility.execs[PLAYER_CITIZEN].building_id)
    answer = r["acts"][-1]
    assert answer["speaker"] == npc and answer["line"].strip()


def test_talk_ask_person_is_answered_from_the_npcs_own_memory(session):
    s, npc = session["s"], session["npc"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "ASK_PERSON",
                  "args": {"citizen_id": PLAYER_CITIZEN}})
    assert r["ok"], r
    answer = r["acts"][-1]
    prop = answer["proposition"]
    assert prop is not None
    if prop["kind"] != "UNKNOWN":
        assert prop["subject"] == PLAYER_CITIZEN
        assert prop["event_ref"], prop
    else:
        assert answer["line"] == "I don't know."


def test_an_unknown_act_is_refused_with_the_options(session):
    s, npc = session["s"], session["npc"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "SING"})
    assert r["ok"] is False, r
    assert r["reason"] == "unknown_act"
    assert set(r["options"]) >= {"ASK_FACT", "END_CONVERSATION"}
    # the session and the conversation are both still alive
    assert s.handle({"cmd": Command.GET_DIALOGUE})["ok"]


def test_talking_to_somebody_far_away_is_refused_not_an_error(session):
    s, far = session["s"], session["far"]
    assert far is not None
    r = s.handle({"cmd": Command.TALK, "citizen_id": far, "act": "GREET"})
    assert r["ok"] is False, r
    assert r["reason"].startswith("not_co_present") or r["reason"] in ("asleep", "fleeing"), r
    assert r["npc"] == far
    assert s.handle({"cmd": Command.GET_DIALOGUE})["ok"]


def test_talking_to_an_unknown_citizen_is_a_bad_argument(session):
    s = session["s"]
    for cid in (10 ** 7, -1):
        r = s.handle({"cmd": Command.TALK, "citizen_id": cid, "act": "GREET"})
        assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT, cid
    r = s.handle({"cmd": Command.TALK, "act": "GREET"})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT
    r = s.handle({"cmd": Command.TALK, "citizen_id": session["npc"], "act": "GREET", "args": 7})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


def test_talk_end_conversation_closes_the_session(session):
    s, npc = session["s"], session["npc"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "END_CONVERSATION"})
    assert r["ok"], r
    assert r["state"] == ENDED
    assert [a["act"] for a in r["acts"]] == ["END_CONVERSATION", "END_CONVERSATION"]
    dl = s.world.dialogue
    assert PLAYER_CITIZEN not in dl.player_sessions
    assert dl.conversations[r["conv_id"]].state == ENDED
    d = s.handle({"cmd": Command.GET_DIALOGUE})["dialogue"]
    assert all(r["conv_id"] != c["conv_id"] for c in d["active"])


# --------------------------------------------------------------------------- #
# GET_DIALOGUE
# --------------------------------------------------------------------------- #
def test_get_dialogue_returns_events_counts_and_active_conversations(session):
    s = session["s"]
    r = s.handle({"cmd": Command.GET_DIALOGUE})
    assert r["ok"], r
    d = r["dialogue"]
    assert set(d) >= {"version", "now_s", "n_conversations", "active", "requests", "events",
                      "event_seq", "counts", "recent_lines"}
    assert d["version"] == DIALOGUE_SCHEMA_VERSION
    assert d["now_s"] > 0.0 and d["n_conversations"] > 0
    assert d["counts"] and list(d["counts"]) == sorted(d["counts"])
    assert d["counts"].get("SPEECH_ACT", 0) > 0
    assert d["events"] and d["event_seq"] >= len(d["events"])
    for e in d["events"]:
        assert isinstance(e["seq"], int) and isinstance(e["t"], (int, float)) and e["event"]
    assert all(c["state"] == ACTIVE for c in d["active"])
    assert isinstance(d["recent_lines"], list) and len(d["recent_lines"]) <= 20
    assert r["dialogue_enabled"] is True
    assert json.loads(json.dumps(d)) == d


def test_get_dialogue_since_seq_returns_only_newer_events(session):
    s, npc = session["s"], session["npc"]
    seq = s.handle({"cmd": Command.GET_DIALOGUE})["dialogue"]["event_seq"]
    r = s.handle({"cmd": Command.TALK, "citizen_id": npc, "act": "GREET"})
    assert r["ok"], r
    later = s.handle({"cmd": Command.GET_DIALOGUE, "since_seq": seq})["dialogue"]
    assert later["event_seq"] > seq
    assert later["events"] and all(e["seq"] > seq for e in later["events"])
    assert any(e["event"] == "SPEECH_ACT" for e in later["events"])
    empty = s.handle({"cmd": Command.GET_DIALOGUE, "since_seq": later["event_seq"]})["dialogue"]
    assert empty["events"] == []


def test_the_mobility_rows_carry_a_dialogue_summary(session):
    r = session["s"].handle({"cmd": Command.GET_MOBILITY, "routes": False})
    assert r["ok"], r
    rows = [x for x in r["mobility"]["citizens"] if "dialogue" in x]
    assert rows, "no mobility row carried a dialogue summary"
    for row in rows[:20]:
        dg = row["dialogue"]
        assert set(dg) == {"conversation", "with", "channel", "open_requests"}
        assert isinstance(dg["open_requests"], list)


# --------------------------------------------------------------------------- #
# SAVE / LOAD
# --------------------------------------------------------------------------- #
def test_save_and_load_keep_dialogue_enabled_and_the_same_state(session):
    s = session["s"]
    before = s.handle({"cmd": Command.GET_DIALOGUE})["dialogue"]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "dialogue.json")
        r = s.handle({"cmd": Command.SAVE, "path": path})
        assert r["ok"] and r["dialogue_enabled"] is True, r
        with open(path) as f:
            saved = json.load(f)
        assert saved["dialogue"] is not None
        assert saved["dialogue"]["version"] == DIALOGUE_SCHEMA_VERSION

        s2 = WorldSession()
        assert s2.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})["ok"]
        r = s2.handle({"cmd": Command.LOAD, "path": path})
        assert r["ok"], r
        assert r["dialogue_enabled"] is True and r["cognition_enabled"] is True
        after = s2.handle({"cmd": Command.GET_DIALOGUE})["dialogue"]
        assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)
        # and the restored world keeps talking
        assert s2.handle({"cmd": Command.ADVANCE_TIME, "seconds": 60.0, "focus_xy": FAR})["ok"]
        assert s2.world.dialogue is not None

"""Bridge v7: cognition on the wire (protocol §7,
ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §19).

Godot never simulates memory or relationships; it asks for them. This
exercises the v7 surface against a real Houston world through WorldSession
(transport-free, the same handlers the socket serves):

    HELLO v7 -> START_WORLD houston -> ADVANCE_TIME -> GET_COGNITION
    -> GET_CITIZEN_CONTEXT -> SAVE -> LOAD

plus the opt-out (``cognition: false``) and the error paths (an unknown
citizen, cognition disabled, no world) which must be clean error responses,
not a dead session.
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
from asphodel.cognition.runtime import COGNITION_SCHEMA_VERSION

CITY = "houston"
START_HOUR = 5.0
PLAYER = 129
FAR = [9000.0, 9000.0]
CONTEXT_KEYS = {"citizen_id", "location", "task", "goal", "needs", "health", "personality",
                "memories", "n_memories", "people_nearby", "relationships", "beliefs",
                "perceived_danger", "avoiding", "avoid_rooms_here", "recent_social"}


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


@pytest.fixture(scope="module")
def session():
    """One world, advanced to ~08:00 so people have met, served and helped."""
    _houston_or_skip()
    s, hello = _hello()
    start = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                      "start_hour": START_HOUR, "player_citizen": PLAYER})
    assert start["ok"], start
    s.world.mobility.set_focus_xy(tuple(FAR))
    while s.world.current_hour() < 8.0:
        r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 300.0, "focus_xy": FAR})
        assert r["ok"], r
    # a citizen with a rich context: the busiest memory in the city
    c = s.world.cognition
    known = max(sorted(c.memories), key=lambda cid: (len(c.memories[cid]), cid))
    return {"s": s, "hello": hello, "start": start, "known": known}


# --------------------------------------------------------------------------- #
# HELLO / START_WORLD
# --------------------------------------------------------------------------- #
def test_hello_advertises_v7_and_the_cognition_commands(session):
    r = session["hello"]
    assert PROTOCOL_VERSION >= 7 and r["protocol_version"] == PROTOCOL_VERSION
    for cmd in (Command.GET_COGNITION, Command.GET_CITIZEN_CONTEXT):
        assert cmd in r["commands"], cmd
    assert r["server"] == "asphodel-bridge"


def test_a_v6_client_is_refused_with_a_version_mismatch():
    s = WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION - 1})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.VERSION_MISMATCH


def test_start_world_enables_cognition_by_default(session):
    r = session["start"]
    assert r["mobility_enabled"] is True
    assert r["work_enabled"] is True
    assert r["cognition_enabled"] is True
    assert session["s"].world.cognition is not None


def test_start_world_with_cognition_false_leaves_it_off():
    _houston_or_skip()
    s, _ = _hello()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                  "start_hour": START_HOUR, "cognition": False})
    assert r["ok"], r
    assert r["mobility_enabled"] is True and r["work_enabled"] is True
    assert r["cognition_enabled"] is False
    assert s.world.cognition is None
    assert s.handle({"cmd": Command.GET_COGNITION})["cognition"] is None
    bad = s.handle({"cmd": Command.GET_CITIZEN_CONTEXT, "citizen_id": 0})
    assert bad["ok"] is False and bad["error"]["code"] == ErrorCode.BAD_ARGUMENT
    # and the world still runs
    assert s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 60.0, "focus_xy": FAR})["ok"]


def test_the_cognition_commands_need_a_started_world():
    s, _ = _hello()
    for msg in ({"cmd": Command.GET_COGNITION},
                {"cmd": Command.GET_CITIZEN_CONTEXT, "citizen_id": 1}):
        r = s.handle(msg)
        assert r["ok"] is False and r["error"]["code"] == ErrorCode.NOT_STARTED, msg


# --------------------------------------------------------------------------- #
# GET_COGNITION
# --------------------------------------------------------------------------- #
def test_get_cognition_returns_version_counts_and_events(session):
    r = session["s"].handle({"cmd": Command.GET_COGNITION})
    assert r["ok"], r
    c = r["cognition"]
    assert set(c) >= {"version", "now_s", "n_citizens_with_memory", "n_facts",
                      "n_relationships", "events", "event_seq", "counts", "avoiding"}
    assert c["version"] == COGNITION_SCHEMA_VERSION
    assert c["now_s"] > 0.0
    assert c["n_citizens_with_memory"] > 0 and c["n_facts"] > 0
    assert c["n_relationships"] > 0
    assert c["counts"] and all(isinstance(v, int) for v in c["counts"].values())
    assert c["events"] and c["event_seq"] >= len(c["events"])
    assert list(c["counts"]) == sorted(c["counts"])
    assert r["cognition_enabled"] is True
    assert json.loads(json.dumps(c)) == c


def test_get_cognition_since_seq_returns_only_newer_events(session):
    s = session["s"]
    first = s.handle({"cmd": Command.GET_COGNITION})["cognition"]
    seq = first["event_seq"]
    assert s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 120.0, "focus_xy": FAR})["ok"]
    later = s.handle({"cmd": Command.GET_COGNITION, "since_seq": seq})["cognition"]
    assert later["event_seq"] > seq
    assert later["events"], "nothing happened in two game minutes"
    assert all(e["seq"] > seq for e in later["events"])
    empty = s.handle({"cmd": Command.GET_COGNITION,
                      "since_seq": later["event_seq"]})["cognition"]
    assert empty["events"] == []


def test_the_event_rows_are_the_documented_social_vocabulary(session):
    c = session["s"].handle({"cmd": Command.GET_COGNITION})["cognition"]
    kinds = {e["event"] for e in c["events"]}
    assert kinds <= {"PRIORS", "MEMORY_CREATED", "MEMORY_REINFORCED", "MEMORY_DECAYED",
                     "RELATIONSHIP_CHANGED", "TRUST_CHANGED", "PERCEIVED", "ENCOUNTER",
                     "WARNING_SHARED", "WARNING_RECEIVED", "SOCIAL_ACTION", "HELP_DECIDED",
                     "HELP_STARTED", "HELP_COMPLETED", "RECIPROCATED", "AVOID_DECIDED",
                     "AVOID_ROOM_DECIDED", "AVOID_ENDED", "BELIEF_UPDATED"}, kinds
    assert {"MEMORY_CREATED", "RELATIONSHIP_CHANGED"} <= kinds, kinds
    for e in c["events"]:
        assert isinstance(e["seq"], int) and isinstance(e["t"], (int, float))


# --------------------------------------------------------------------------- #
# GET_CITIZEN_CONTEXT
# --------------------------------------------------------------------------- #
def test_get_citizen_context_returns_the_documented_keys(session):
    r = session["s"].handle({"cmd": Command.GET_CITIZEN_CONTEXT,
                             "citizen_id": session["known"]})
    assert r["ok"], r
    ctx = r["context"]
    assert set(ctx) == CONTEXT_KEYS, set(ctx) ^ CONTEXT_KEYS
    assert ctx["citizen_id"] == session["known"]
    assert set(ctx["location"]) >= {"building_id", "room_id", "zone", "x", "y", "inside", "band"}
    assert set(ctx["task"]) == {"task_id", "object_id", "phase", "role"}
    assert set(ctx["personality"]) == {"sociability", "helpfulness", "risk_tolerance",
                                       "loyalty", "suspicion"}
    assert all(0.0 <= v <= 1.0 for v in ctx["personality"].values())
    assert ctx["n_memories"] > 0 and ctx["memories"], ctx["n_memories"]
    for m in ctx["memories"]:
        assert {"fact_id", "kind", "source", "confidence", "effective", "salience"} <= set(m)
        assert m["owner"] == session["known"]
        assert 0.0 <= m["effective"] <= 1.0
    assert ctx["relationships"], "a citizen with memories and no relationships"
    for rel in ctx["relationships"]:
        assert rel["owner"] == session["known"] and rel["other"] != session["known"]
        for dim in ("familiarity", "trust", "affinity", "fear", "hostility", "obligation"):
            assert 0.0 <= rel[dim] <= 1.0
    assert isinstance(ctx["beliefs"], list)
    assert 0.0 <= ctx["perceived_danger"] <= 1.0
    assert isinstance(ctx["avoid_rooms_here"], list)
    assert isinstance(ctx["recent_social"], list) and len(ctx["recent_social"]) <= 6
    for e in ctx["recent_social"]:
        assert session["known"] in (e.get("citizen_id"), e.get("target"), e.get("recipient"),
                                    e.get("beneficiary"), e.get("other"))
    assert json.loads(json.dumps(ctx)) == ctx


def test_an_unknown_citizen_is_a_bad_argument_not_a_crash(session):
    s = session["s"]
    for cid in (10 ** 7, -1):
        r = s.handle({"cmd": Command.GET_CITIZEN_CONTEXT, "citizen_id": cid})
        assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT, cid
    r = s.handle({"cmd": Command.GET_CITIZEN_CONTEXT})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT
    r = s.handle({"cmd": Command.GET_CITIZEN_CONTEXT, "citizen_id": "seven"})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT
    # the session is still alive
    assert s.handle({"cmd": Command.GET_COGNITION})["ok"]


def test_the_mobility_rows_carry_a_cognition_summary(session):
    r = session["s"].handle({"cmd": Command.GET_MOBILITY, "routes": False})
    assert r["ok"], r
    rows = [x for x in r["mobility"]["citizens"] if "cognition" in x]
    assert rows, "no mobility row carried a cognition summary"
    for row in rows[:20]:
        cg = row["cognition"]
        assert set(cg) >= {"n_memories", "n_relationships", "top_belief", "avoiding", "helping"}
        assert isinstance(cg["n_memories"], int) and cg["n_memories"] >= 0


# --------------------------------------------------------------------------- #
# SAVE / LOAD
# --------------------------------------------------------------------------- #
def test_save_and_load_keep_cognition_enabled_and_the_same_context(session):
    s = session["s"]
    cid = session["known"]
    before_ctx = s.handle({"cmd": Command.GET_CITIZEN_CONTEXT, "citizen_id": cid})["context"]
    before_cog = s.handle({"cmd": Command.GET_COGNITION})["cognition"]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cognition.json")
        r = s.handle({"cmd": Command.SAVE, "path": path})
        assert r["ok"] and r["cognition_enabled"] is True, r
        with open(path) as f:
            saved = json.load(f)
        assert saved["cognition"] is not None
        assert saved["cognition"]["version"] == COGNITION_SCHEMA_VERSION

        s2 = WorldSession()
        assert s2.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})["ok"]
        r = s2.handle({"cmd": Command.LOAD, "path": path})
        assert r["ok"], r
        assert r["cognition_enabled"] is True
        assert r["work_enabled"] is True and r["mobility_enabled"] is True
        after_ctx = s2.handle({"cmd": Command.GET_CITIZEN_CONTEXT, "citizen_id": cid})["context"]
        after_cog = s2.handle({"cmd": Command.GET_COGNITION})["cognition"]
    assert json.dumps(after_ctx, sort_keys=True) == json.dumps(before_ctx, sort_keys=True)
    assert json.dumps(after_cog, sort_keys=True) == json.dumps(before_cog, sort_keys=True)
    assert before_ctx["n_memories"] > 0


def test_a_loaded_world_keeps_thinking(session):
    s = session["s"]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cognition.json")
        assert s.handle({"cmd": Command.SAVE, "path": path})["ok"]
        s2 = WorldSession()
        s2.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
        assert s2.handle({"cmd": Command.LOAD, "path": path})["ok"]
        seq = s2.handle({"cmd": Command.GET_COGNITION})["cognition"]["event_seq"]
        assert s2.handle({"cmd": Command.ADVANCE_TIME, "seconds": 300.0, "focus_xy": FAR})["ok"]
        after = s2.handle({"cmd": Command.GET_COGNITION})["cognition"]
    assert after["event_seq"] > seq
    assert after["n_facts"] > 0

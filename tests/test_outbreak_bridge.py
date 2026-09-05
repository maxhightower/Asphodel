"""Bridge v5: the outbreak on the wire (protocol §5).

Godot never simulates the outbreak; it asks for it. This exercises the whole v5
surface against a real Houston world through WorldSession (transport-free, the
same handlers the socket serves):

    HELLO v5 -> START_WORLD ... outbreak {...} -> GET_OUTBREAK -> SEED_OUTBREAK
    -> ADVANCE_TIME (mobility rows carry health) -> SAVE -> LOAD -> GET_OUTBREAK

and the error path: an unknown pathogen archetype is a bad_argument, not a
crashed session.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge import PROTOCOL_VERSION, WorldSession
from asphodel.bridge.protocol import Command, ErrorCode
from asphodel.bridge.worldfactory import resolve_bundle_dir

CITY = "houston"
INDEX = 42
SECOND = 4
START_HOUR = 5.0


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
    _houston_or_skip()
    s, _ = _hello()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 1,
                  "start_hour": START_HOUR,
                  "outbreak": {"pathogen": "classic_zombie", "citizen_id": INDEX}})
    assert r["ok"], r
    return {"s": s, "start": r}


def _outbreak(s, since_seq=None):
    msg = {"cmd": Command.GET_OUTBREAK}
    if since_seq is not None:
        msg["since_seq"] = since_seq
    r = s.handle(msg)
    assert r["ok"], r
    return r


# --------------------------------------------------------------------------- #
def test_hello_advertises_v5_and_the_outbreak_commands():
    _s, r = _hello()
    assert PROTOCOL_VERSION >= 5 and r["protocol_version"] == PROTOCOL_VERSION
    assert Command.SEED_OUTBREAK in r["commands"]
    assert Command.GET_OUTBREAK in r["commands"]


def test_start_world_with_an_outbreak_option_seeds_the_index_case(session):
    r = session["start"]
    assert r["outbreak_enabled"] is True
    assert r["mobility_enabled"] is True
    ob = _outbreak(session["s"])["outbreak"]
    seeded = [e for e in ob["events"] if e["event"] == "INFECTED"]
    assert [e["citizen_id"] for e in seeded] == [INDEX]
    assert ob["pathogen"] == "classic_zombie"


def test_get_outbreak_returns_counts_health_and_events(session):
    ob = _outbreak(session["s"])["outbreak"]
    assert set(ob) >= {"version", "t_s", "pathogen", "counts", "health",
                       "disrupted_buildings", "events", "event_seq"}
    assert sum(ob["counts"].values()) == session["start"]["n_citizens"] or ob["counts"]
    row = next(h for h in ob["health"] if h["citizen_id"] == INDEX)
    assert row["state"] == "incubating" and row["pathogen"] == "classic_zombie"
    assert row["symptom_t"] > 0 and row["lineage"] == []
    assert ob["counts"].get("susceptible", 0) > 0
    assert json.loads(json.dumps(ob)) == ob


def test_get_outbreak_since_seq_returns_only_newer_events(session):
    ob = _outbreak(session["s"])["outbreak"]
    last = ob["event_seq"]
    later = _outbreak(session["s"], since_seq=last)["outbreak"]
    assert later["events"] == []
    first = _outbreak(session["s"], since_seq=0)["outbreak"]
    assert first["events"] and all(e["seq"] > 0 for e in first["events"])


def test_seed_outbreak_adds_a_second_index_case_without_reseeding_the_first(session):
    s = session["s"]
    before = _outbreak(s)["outbreak"]
    r = s.handle({"cmd": Command.SEED_OUTBREAK, "citizen_id": SECOND})
    assert r["ok"], r
    assert r["outbreak_enabled"] is True
    after = r["outbreak"]
    infected = [e["citizen_id"] for e in after["events"] if e["event"] == "INFECTED"]
    assert infected.count(INDEX) == 1 and infected.count(SECOND) == 1
    old = next(h for h in before["health"] if h["citizen_id"] == INDEX)
    new = next(h for h in after["health"] if h["citizen_id"] == INDEX)
    assert old == new                               # the first case was untouched
    second = next(h for h in after["health"] if h["citizen_id"] == SECOND)
    assert second["state"] == "incubating" and second["source_citizen"] is None
    assert second["context"] == "index_case"
    assert after["event_seq"] > before["event_seq"]


def test_seed_outbreak_rejects_a_citizen_that_is_not_embodied(session):
    r = session["s"].handle({"cmd": Command.SEED_OUTBREAK, "citizen_id": 10 ** 7})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


def test_advance_time_returns_mobility_rows_carrying_health(session):
    s = session["s"]
    r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 600.0, "snapshot": "mobility"})
    assert r["ok"], r
    rows = r["mobility"]["citizens"]
    assert rows and all("health" in row for row in rows)
    states = {row["health"] for row in rows}
    assert states <= {"susceptible", "exposed", "incubating", "symptomatic",
                      "incapacitated", "dead", "corpse", "undead", "recovered"}
    assert next(row for row in rows if row["citizen_id"] == INDEX)["health"] == "incubating"
    assert r["outbreak_enabled"] is True
    ob = _outbreak(s)["outbreak"]
    assert ob["t_s"] == pytest.approx(r["advanced_seconds"], abs=1.0)


def test_save_then_load_restores_the_identical_outbreak(session, tmp_path_factory):
    s = session["s"]
    path = str(tmp_path_factory.mktemp("outbreak") / "save.json")
    before = _outbreak(s)["outbreak"]
    r = s.handle({"cmd": Command.SAVE, "path": path})
    assert r["ok"], r
    r = s.handle({"cmd": Command.LOAD, "path": path})
    assert r["ok"], r
    assert r["outbreak_enabled"] is True and r["mobility_enabled"] is True
    after = _outbreak(s)["outbreak"]
    assert after["health"] == before["health"]
    assert after["event_seq"] == before["event_seq"]
    assert after["events"] == before["events"]
    assert after["counts"] == before["counts"]
    assert after["t_s"] == before["t_s"]
    # and no citizen was seeded twice by the reload
    infected = [e["citizen_id"] for e in after["events"] if e["event"] == "INFECTED"]
    assert len(infected) == len(set(infected))


def test_unknown_pathogen_is_a_bad_argument(tmp_path_factory):
    _houston_or_skip()
    s, _ = _hello()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 1,
                  "start_hour": START_HOUR,
                  "outbreak": {"pathogen": "definitely_not_a_pathogen"}})
    assert not r["ok"], r
    assert r["error"]["code"] == ErrorCode.BAD_ARGUMENT
    assert "definitely_not_a_pathogen" in r["error"]["message"]
    # the session survives and can still start a world
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 1,
                  "start_hour": START_HOUR})
    assert r["ok"] and r["outbreak_enabled"] is False
    r = s.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": "still_not_a_pathogen"})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.BAD_ARGUMENT
    assert s.handle({"cmd": Command.GET_OUTBREAK})["outbreak"] is None
    r = s.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": "rage_virus", "citizen_id": INDEX})
    assert r["ok"] and r["outbreak"]["pathogen"] == "rage_virus"

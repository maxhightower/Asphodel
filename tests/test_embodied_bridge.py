"""Bridge protocol v4: the movement clock over the wire (ASPHODEL_EMBODIED_MOBILITY_V1).

A Godot client drives one clock (ADVANCE_TIME), moves one focus (SET_FOCUS xy),
reports its NEAR bodies back (MOBILITY_REPORT) and asks for the movement
snapshot (GET_MOBILITY). These tests run the session transport-free on the
canonical Houston bundle, and check that a save/load through the session keeps
citizen 4's mobility row identical.
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
CITIZEN = 4
VEHICLE = "veh:4"


def _skip_without_bundle():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _session(**start):
    s = WorldSession()
    hello = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    assert hello["ok"], hello
    r = s.handle(dict({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 1}, **start))
    assert r["ok"], r
    return s, r


@pytest.fixture(scope="module")
def session():
    _skip_without_bundle()
    s, started = _session()
    return s, started


def _mobility_flag(resp):
    """The session summary's "is mobility on" flag."""
    assert "mobility_enabled" in resp or "mobility" in resp, sorted(resp)
    return resp.get("mobility_enabled", resp.get("mobility"))


def _row(mob, cid=CITIZEN):
    return next(r for r in mob["citizens"] if r["citizen_id"] == cid)


# --------------------------------------------------------------------------- #
def test_hello_advertises_v4_and_the_new_commands():
    _skip_without_bundle()
    s = WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION, "id": 7})
    assert r["ok"] and r["id"] == 7
    assert PROTOCOL_VERSION == 4
    assert r["protocol_version"] == 4
    for cmd in (Command.ADVANCE_TIME, Command.MOBILITY_REPORT, Command.GET_MOBILITY):
        assert cmd in r["commands"]
    # an older client is rejected, never silently misread
    old = WorldSession().handle({"cmd": Command.HELLO, "protocol_version": 3})
    assert not old["ok"] and old["error"]["code"] == ErrorCode.VERSION_MISMATCH


def test_start_world_enables_mobility(session):
    s, started = session
    assert _mobility_flag(started) is True
    assert started["n_citizens"] > 50
    assert "hour" in started and 0.0 <= started["hour"] < 24.0
    assert started["game_seconds"] >= 0.0


def test_advance_time_returns_the_mobility_block(session):
    s, _ = session
    r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 120, "snapshot": "mobility",
                  "id": 11})
    assert r["ok"] and r["id"] == 11
    assert r["advanced_seconds"] == 120.0
    assert r["ticks_crossed"] == 0
    assert r["game_seconds"] >= 120.0
    mob = r["mobility"]
    assert mob["n_citizens"] == len(mob["citizens"]) > 50
    assert mob["t_s"] == pytest.approx(120.0)
    row = _row(mob)
    assert set(row) >= {"citizen_id", "x", "y", "state", "activity", "band",
                        "building_id", "vehicle_id", "progress"}
    assert mob["n_vehicles"] == len(mob["vehicles"]) >= 1
    assert any(v["vehicle_id"] == VEHICLE for v in mob["vehicles"])
    # the whole block is renderer-facing JSON
    assert json.loads(json.dumps(mob)) == mob


def test_set_focus_accepts_xy_and_moves_the_lod_focus(session):
    s, _ = session
    row = _row(s.handle({"cmd": Command.GET_MOBILITY, "routes": False})["mobility"])
    xy = [row["x"], row["y"]]
    r = s.handle({"cmd": Command.SET_FOCUS, "zones": [], "xy": xy, "id": 3})
    assert r["ok"] and r["id"] == 3
    assert s.world.mobility.focus_xy == (xy[0], xy[1])
    got = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 5, "snapshot": "mobility"})
    assert got["mobility"]["focus_xy"] == xy
    assert _row(got["mobility"])["band"] == "physical"
    assert f"cit:{CITIZEN}" in got["mobility"]["near"]
    # a malformed focus point is refused
    bad = s.handle({"cmd": Command.SET_FOCUS, "zones": [], "xy": ["a", 2]})
    assert not bad["ok"] and bad["error"]["code"] == ErrorCode.BAD_ARGUMENT


def test_mobility_report_applies_only_to_embodied_bodies(session):
    s, _ = session
    mob = s.handle({"cmd": Command.GET_MOBILITY, "routes": False})["mobility"]
    row = _row(mob)
    body = {"id": f"cit:{CITIZEN}", "x": row["x"], "y": 0.0, "z": row["y"],
            "blocked": False}
    r = s.handle({"cmd": Command.MOBILITY_REPORT, "bodies": [body], "dt": 0.1, "id": 4})
    assert r["ok"] and r["id"] == 4
    # 1 when the citizen is an embodied walker/driver right now, 0 otherwise —
    # a report is never invented for a body the world does not embody.
    assert r["applied"] in (0, 1)
    if row["band"] == "physical" and row["state"] in ("on_foot", "driving",
                                                      "approaching_vehicle"):
        assert r["applied"] == 1
    else:
        assert r["applied"] == 0
    assert s.handle({"cmd": Command.MOBILITY_REPORT,
                     "bodies": [{"id": "cit:987654", "x": 0.0, "z": 0.0}],
                     "dt": 0.1})["applied"] == 0


def test_get_mobility_does_not_advance(session):
    s, _ = session
    a = s.handle({"cmd": Command.GET_MOBILITY, "id": 9})
    assert a["ok"] and a["id"] == 9
    b = s.handle({"cmd": Command.GET_MOBILITY})
    assert a["mobility"]["t_s"] == b["mobility"]["t_s"]
    assert a["tick"] == b["tick"]
    assert "routes" in a["mobility"]
    assert "routes" not in s.handle({"cmd": Command.GET_MOBILITY,
                                     "routes": False})["mobility"]


def test_advance_time_crossing_a_tick(session):
    s, _ = session
    before = s.handle({"cmd": Command.GET_MOBILITY, "routes": False})
    tick_s = s.world.tick_seconds
    assert tick_s == pytest.approx(6 * 3600.0), "houston ticks are 6 game hours"
    r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 6 * 3600,
                  "snapshot": "mobility"})
    assert r["ok"]
    assert r["ticks_crossed"] == 1
    assert r["tick"] == before["tick"] + 1
    mob = r["mobility"]
    assert mob["t_s"] == pytest.approx(before["mobility"]["t_s"] + 6 * 3600.0)
    # the citizens went about their day across the tick boundary
    assert _row(mob)["citizen_id"] == CITIZEN
    assert any(v["vehicle_id"] == VEHICLE for v in mob["vehicles"])


def test_bad_arguments_are_rejected(session):
    s, _ = session
    for msg in ({"cmd": Command.ADVANCE_TIME, "seconds": -1},
                {"cmd": Command.ADVANCE_TIME, "seconds": "soon"},
                {"cmd": Command.ADVANCE_TIME, "seconds": 8 * 86400},
                {"cmd": Command.MOBILITY_REPORT, "bodies": "cit:4", "dt": 1},
                {"cmd": Command.MOBILITY_REPORT, "bodies": [], "dt": -1}):
        r = s.handle(msg)
        assert not r["ok"], msg
        assert r["error"]["code"] == ErrorCode.BAD_ARGUMENT
    # ... and a paused world does not advance its movement clock
    assert s.handle({"cmd": Command.PAUSE})["ok"]
    paused = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 10})
    assert not paused["ok"] and paused["error"]["code"] == ErrorCode.PAUSED
    assert s.handle({"cmd": Command.RESUME})["ok"]


def test_commands_need_a_world():
    _skip_without_bundle()
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    for cmd in (Command.ADVANCE_TIME, Command.GET_MOBILITY, Command.MOBILITY_REPORT):
        r = s.handle({"cmd": cmd, "seconds": 1, "bodies": [], "dt": 0.0})
        assert not r["ok"] and r["error"]["code"] == ErrorCode.NOT_STARTED


def test_world_started_without_mobility():
    _skip_without_bundle()
    s, started = _session(mobility=False)
    assert _mobility_flag(started) is False
    assert s.world.mobility is None
    snap = s.handle({"cmd": Command.SNAPSHOT})["world"]
    assert "mobility" not in snap
    r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 60, "snapshot": "mobility"})
    assert r["ok"] and r["mobility"] is None
    assert s.handle({"cmd": Command.GET_MOBILITY})["mobility"] is None
    assert s.handle({"cmd": Command.MOBILITY_REPORT,
                     "bodies": [{"id": "cit:4", "x": 0.0, "z": 0.0}],
                     "dt": 0.1})["applied"] == 0


def test_save_and_load_through_the_session_keeps_the_mobility_row(tmp_path):
    _skip_without_bundle()
    s, _ = _session()
    assert s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 1800})["ok"]
    before = _row(s.handle({"cmd": Command.GET_MOBILITY, "routes": False})["mobility"])
    path = str(tmp_path / "embodied.json")
    assert s.handle({"cmd": Command.SAVE, "path": path})["ok"]
    with open(path) as f:
        raw = json.load(f)
    assert raw["save_version"] == 3 and raw["mobility"] is not None

    fresh = WorldSession()
    fresh.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = fresh.handle({"cmd": Command.LOAD, "path": path})
    assert r["ok"], r
    assert _mobility_flag(r) is True
    after = _row(fresh.handle({"cmd": Command.GET_MOBILITY,
                               "routes": False})["mobility"])
    assert after == before, "citizen 4's mobility row changed over SAVE/LOAD"
    # and the reloaded session keeps running the same trip
    a = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 300, "snapshot": "mobility"})
    b = fresh.handle({"cmd": Command.ADVANCE_TIME, "seconds": 300,
                      "snapshot": "mobility"})
    assert _row(a["mobility"]) == _row(b["mobility"])

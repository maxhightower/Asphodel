"""Bridge v6: rooms, smart objects and work on the wire (protocol §6).

Godot never simulates work; it asks for it. This exercises the whole v6 surface
against a real Houston world through WorldSession (transport-free, the same
handlers the socket serves):

    HELLO v6 -> START_WORLD -> GET_WORK -> GET_ROOMS -> ADVANCE_TIME
    (mobility rows carry `work`) -> SET_OBJECT_STATE (a register breaks)

plus the opt-out (``work: false``) and the error paths (an unknown object, a
missing building_id) which must be bad_argument responses, not a dead session.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge import PROTOCOL_VERSION, WorldSession
from asphodel.bridge.protocol import Command, ErrorCode
from asphodel.bridge.worldfactory import resolve_bundle_dir

CITY = "houston"
START_HOUR = 5.0
PLAYER = 129
SHOP = 6059
FAR = [9000.0, 9000.0]


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
    """One world, advanced to ~09:00 so the shop is staffed and holdable."""
    _houston_or_skip()
    s, _ = _hello()
    start = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                      "start_hour": START_HOUR, "player_citizen": PLAYER})
    assert start["ok"], start
    s.world.mobility.set_focus_xy(tuple(FAR))
    while s.world.current_hour() < 9.0:
        r = s.handle({"cmd": Command.ADVANCE_TIME, "seconds": 300.0, "focus_xy": FAR})
        assert r["ok"], r
    return {"s": s, "start": start}


# --------------------------------------------------------------------------- #
# HELLO / START_WORLD
# --------------------------------------------------------------------------- #
def test_hello_advertises_v6_and_the_work_commands():
    _s, r = _hello()
    assert PROTOCOL_VERSION >= 6 and r["protocol_version"] == PROTOCOL_VERSION
    for cmd in (Command.GET_WORK, Command.GET_ROOMS, Command.SET_OBJECT_STATE):
        assert cmd in r["commands"], cmd
    assert r["server"] == "asphodel-bridge"


def test_a_v5_client_is_refused_with_a_version_mismatch():
    s = WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION - 1})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.VERSION_MISMATCH


def test_start_world_enables_work_by_default(session):
    r = session["start"]
    assert r["mobility_enabled"] is True
    assert r["work_enabled"] is True


def test_start_world_with_work_false_leaves_work_disabled():
    _houston_or_skip()
    s, _ = _hello()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                  "start_hour": START_HOUR, "work": False})
    assert r["ok"], r
    assert r["mobility_enabled"] is True
    assert r["work_enabled"] is False
    assert s.world.work is None
    assert s.handle({"cmd": Command.GET_WORK})["work"] is None
    bad = s.handle({"cmd": Command.GET_ROOMS, "building_id": SHOP})
    assert bad["ok"] is False and bad["error"]["code"] == ErrorCode.BAD_ARGUMENT
    bad = s.handle({"cmd": Command.SET_OBJECT_STATE, "object_id": f"so:{SHOP}:5",
                    "key": "working", "value": False})
    assert bad["ok"] is False and bad["error"]["code"] == ErrorCode.BAD_ARGUMENT


def test_the_work_commands_need_a_started_world():
    s, _ = _hello()
    for msg in ({"cmd": Command.GET_WORK},
                {"cmd": Command.GET_ROOMS, "building_id": SHOP},
                {"cmd": Command.SET_OBJECT_STATE, "object_id": "so:1:1", "key": "working",
                 "value": False}):
        r = s.handle(msg)
        assert r["ok"] is False and r["error"]["code"] == ErrorCode.NOT_STARTED, msg


# --------------------------------------------------------------------------- #
# GET_WORK
# --------------------------------------------------------------------------- #
def test_get_work_returns_sessions_reservations_queues_and_events(session):
    r = session["s"].handle({"cmd": Command.GET_WORK})
    assert r["ok"], r
    w = r["work"]
    assert set(w) >= {"now_s", "n_employed", "n_sessions", "sessions", "reservations",
                      "queues", "events", "event_seq"}
    assert w["n_employed"] > 0 and w["n_sessions"] == len(w["sessions"])
    assert w["events"] and w["event_seq"] >= len(w["events"])
    assert r["work_enabled"] is True and "hour" in r
    for cid, s in w["sessions"].items():
        assert int(cid) == s["citizen_id"]
        assert s["kind"] in ("worker", "customer", "resident")
        assert s["phase"] in ("idle", "to_object", "using", "waiting", "done")
    assert set(w["reservations"]) == {"holders", "since", "exclusive_of"}


def test_get_work_since_seq_returns_only_newer_events(session):
    s = session["s"]
    first = s.handle({"cmd": Command.GET_WORK})["work"]
    cut = first["event_seq"]
    again = s.handle({"cmd": Command.GET_WORK, "since_seq": cut})["work"]
    assert all(e["seq"] > cut for e in again["events"])
    assert again["event_seq"] >= cut
    assert s.handle({"cmd": Command.GET_WORK, "since_seq": 0})["work"]["events"]


def test_a_bad_since_seq_is_a_bad_argument(session):
    r = session["s"].handle({"cmd": Command.GET_WORK, "since_seq": "soon"})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


# --------------------------------------------------------------------------- #
# GET_ROOMS
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def rooms(session):
    r = session["s"].handle({"cmd": Command.GET_ROOMS, "building_id": SHOP})
    assert r["ok"], r
    return r


def test_get_rooms_describes_rooms_objects_occupants_and_status(rooms):
    assert rooms["building_id"] == SHOP
    assert rooms["rooms"], "a Houston retail building with no rooms"
    for row in rooms["rooms"]:
        assert set(row) == {"room_id", "kind", "zone", "x0", "y0", "x1", "y1", "doors"}
        assert row["x0"] <= row["x1"] and row["y0"] <= row["y1"]
        assert row["doors"] == sorted(row["doors"])
    assert len(rooms["entrance"]) == 2
    known = {r["room_id"] for r in rooms["rooms"]}
    for rid, cids in rooms["occupants"].items():
        assert int(rid) in known, rid
        assert cids == sorted(cids)
    st = rooms["status"]
    assert st["building_id"] == SHOP
    assert st["status"] in ("open", "reduced_function", "closed")
    assert set(st["staffed"]) <= set(st["stations"])


def test_get_rooms_objects_carry_state_holders_and_queues(rooms):
    objs = rooms["objects"]
    assert objs
    assert [o["object_id"] for o in objs] == sorted(o["object_id"] for o in objs)
    known = {r["room_id"] for r in rooms["rooms"]}
    for o in objs:
        assert set(o) >= {"object_id", "kind", "building_id", "room_id", "caps", "affordances",
                          "exclusive", "capacity", "state", "source", "holders", "queue"}
        assert o["building_id"] == SHOP and o["room_id"] in known
        assert o["object_id"].startswith(f"so:{SHOP}:")
        assert o["caps"] == sorted(o["caps"])
        assert len(o["holders"]) <= o["capacity"]
        assert o["source"] in ("decor", "fixture")
    stations = [o for o in objs if {"station", "transact"} <= set(o["caps"])]
    assert stations, "the shop has no station to work at"
    assert any(o["holders"] for o in stations), "no station was staffed at 09:00"


def test_get_rooms_ids_are_stable_across_calls(session, rooms):
    again = session["s"].handle({"cmd": Command.GET_ROOMS, "building_id": SHOP})
    assert again["ok"]
    assert [o["object_id"] for o in again["objects"]] == [o["object_id"] for o in rooms["objects"]]
    assert [(o["kind"], o["room_id"], o["x"], o["y"]) for o in again["objects"]] == \
           [(o["kind"], o["room_id"], o["x"], o["y"]) for o in rooms["objects"]]
    assert again["rooms"] == rooms["rooms"]
    assert again["entrance"] == rooms["entrance"]


def test_get_rooms_without_a_building_id_is_a_bad_argument(session):
    r = session["s"].handle({"cmd": Command.GET_ROOMS})
    assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


# --------------------------------------------------------------------------- #
# mobility rows carry `work`
# --------------------------------------------------------------------------- #
def test_mobility_rows_carry_the_work_context(session):
    r = session["s"].handle({"cmd": Command.ADVANCE_TIME, "seconds": 1.0, "focus_xy": FAR,
                             "snapshot": "mobility"})
    assert r["ok"], r
    rows = r["mobility"]["citizens"]
    assert rows
    for row in rows:
        assert "work" in row, row["citizen_id"]
        w = row["work"]
        assert set(w) == {"role", "workplace_id", "task", "phase", "object_id", "room_id",
                          "zone", "carrying", "help_for"}
    working = [row for row in rows if row["work"]["object_id"]]
    assert working, "no citizen was using an object"
    for row in working:
        assert row["work"]["room_id"] is not None and row["work"]["zone"]
    player = [row for row in rows if row["citizen_id"] == PLAYER][0]
    assert player["work"]["workplace_id"] == SHOP
    assert player["work"]["role"] == "cashier"


# --------------------------------------------------------------------------- #
# SET_OBJECT_STATE
# --------------------------------------------------------------------------- #
def test_setting_an_unknown_object_or_key_is_a_bad_argument(session):
    s = session["s"]
    for msg in ({"cmd": Command.SET_OBJECT_STATE, "object_id": "so:6059:999999",
                 "key": "working", "value": False},
                {"cmd": Command.SET_OBJECT_STATE, "object_id": "not-an-object",
                 "key": "working", "value": False},
                {"cmd": Command.SET_OBJECT_STATE, "object_id": "so:6059:5", "key": ""}):
        r = s.handle(msg)
        assert r["ok"] is False and r["error"]["code"] == ErrorCode.BAD_ARGUMENT, msg


def test_breaking_a_staffed_station_evicts_its_holders(session):
    s = session["s"]
    w = s.world.work
    rooms = s.handle({"cmd": Command.GET_ROOMS, "building_id": SHOP})
    held = [o for o in rooms["objects"] if o["holders"] and {"station", "transact"} <= set(o["caps"])]
    assert held, "no held station to break"
    target = held[0]
    holders_before = list(target["holders"])

    r = s.handle({"cmd": Command.SET_OBJECT_STATE, "object_id": target["object_id"],
                  "key": "working", "value": False})
    assert r["ok"], r
    assert r["object"]["object_id"] == target["object_id"]
    assert r["object"]["state"]["working"] is False
    assert r["holders"] == [], r["holders"]
    assert w.ledger.holders_of(target["object_id"]) == []
    evicted = [e for e in w.events if e["event"] == "OBJECT_UNAVAILABLE"
               and e["object_id"] == target["object_id"]]
    assert sorted(e["citizen_id"] for e in evicted) == sorted(holders_before)

    # the change is authoritative: it shows up on the next GET_ROOMS...
    after = s.handle({"cmd": Command.GET_ROOMS, "building_id": SHOP})
    row = [o for o in after["objects"] if o["object_id"] == target["object_id"]][0]
    assert row["state"]["working"] is False and row["holders"] == []
    # ...and in the persisted deltas
    assert target["object_id"] in w.registry(SHOP).state_deltas()

    # and it can be repaired
    back = s.handle({"cmd": Command.SET_OBJECT_STATE, "object_id": target["object_id"],
                     "key": "working", "value": True})
    assert back["ok"] and back["object"]["state"]["working"] is True
    assert w.registry(SHOP).get(target["object_id"]).available() is True


def test_the_external_state_change_is_evented_as_external(session):
    s = session["s"]
    oid = f"so:{SHOP}:5"
    before = s.world.work.event_seq
    r = s.handle({"cmd": Command.SET_OBJECT_STATE, "object_id": oid, "key": "dirty",
                  "value": True})
    assert r["ok"], r
    new = [e for e in s.world.work.events if e["seq"] > before]
    changes = [e for e in new if e["event"] == "STATE_CHANGE" and e["object_id"] == oid]
    assert changes, new
    assert changes[0]["source"] == "external" and changes[0]["citizen_id"] is None
    assert changes[0]["key"] == "dirty" and changes[0]["value"] is True
    assert s.world.work.registry(SHOP).get(oid).state["dirty"] is True

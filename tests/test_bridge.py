"""M1 tests: the live runtime authority bridge.

Covers the M1 exit gate:

* handshake + protocol version mismatch,
* deterministic START_WORLD from (bundle, seed),
* snapshot JSON roundtrip (the renderer contract stays json.dumps-able),
* SET_FOCUS routing to World.set_focus,
* INTERVENE routing to World.intervene (+ bad-argument rejection),
* PAUSE freezes advancement, RESUME continues from the identical state,
* SHUTDOWN ends the session/process,
* malformed command rejection (never crashes the session),
* the world advances *only, and exactly* on ADVANCE (no duplicate advancement,
  SNAPSHOT does not advance),
* deterministic replay of an identical command stream,
* a causal intervention (A/B cordon) changes the *future* authoritative state.

The core is exercised transport-free via WorldSession; a subset is re-run over
the real TCP socket to prove the framing/lifecycle.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge import WorldSession, PROTOCOL_VERSION
from asphodel.bridge.protocol import Command, ErrorCode
from asphodel.bridge.server import BridgeServer
from asphodel.bridge.client import BridgeClient


CITY = "madisonville_tx"   # smallest bundle -> fastest deterministic tests
BIG_CITY = "houston"


def _started(bundle=CITY, seed=1, **kw):
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = s.handle(dict({"cmd": Command.START_WORLD, "bundle": bundle, "seed": seed}, **kw))
    assert r["ok"], r
    return s


def _infected(totals):
    return sum(totals[k] for k in ("E", "Ia", "Is", "R", "D"))


# --------------------------------------------------------------------------- #
# handshake / versioning
# --------------------------------------------------------------------------- #
def test_hello_ok_and_version_envelope():
    s = WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION, "id": 5})
    assert r["ok"] and r["protocol_version"] == PROTOCOL_VERSION
    assert r["id"] == 5
    assert Command.ADVANCE in r["commands"]


def test_hello_version_mismatch_rejected():
    s = WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION + 1})
    assert not r["ok"]
    assert r["error"]["code"] == ErrorCode.VERSION_MISMATCH


def test_hello_requires_integer_version():
    s = WorldSession()
    r = s.handle({"cmd": Command.HELLO, "protocol_version": "one"})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.MALFORMED


# --------------------------------------------------------------------------- #
# start / not-started guards
# --------------------------------------------------------------------------- #
def test_command_before_start_is_rejected():
    s = WorldSession()
    for cmd in (Command.ADVANCE, Command.SNAPSHOT, Command.SET_FOCUS,
                Command.INTERVENE, Command.PAUSE, Command.RESUME):
        r = s.handle({"cmd": cmd})
        assert not r["ok"] and r["error"]["code"] == ErrorCode.NOT_STARTED, cmd


def test_start_world_deterministic():
    a = _started(bundle=BIG_CITY, seed=42)
    b = _started(bundle=BIG_CITY, seed=42)
    for _ in range(15):
        ra = a.handle({"cmd": Command.ADVANCE, "ticks": 4})
        rb = b.handle({"cmd": Command.ADVANCE, "ticks": 4})
    assert ra["totals"] == rb["totals"]
    assert ra["tick"] == rb["tick"]


def test_double_start_rejected():
    s = _started()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.ALREADY_STARTED


def test_start_unknown_bundle_is_internal_not_crash():
    s = WorldSession()
    r = s.handle({"cmd": Command.START_WORLD, "bundle": "atlantis"})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.INTERNAL


def test_start_requires_bundle():
    s = WorldSession()
    r = s.handle({"cmd": Command.START_WORLD})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


# --------------------------------------------------------------------------- #
# snapshot roundtrip / JSON safety
# --------------------------------------------------------------------------- #
def test_snapshot_json_roundtrip():
    s = _started(seed=2)
    s.handle({"cmd": Command.SET_FOCUS, "zones": [33]})
    s.handle({"cmd": Command.ADVANCE, "ticks": 12})
    r = s.handle({"cmd": Command.SNAPSHOT})
    assert r["ok"]
    world = r["world"]
    # Must survive a full JSON encode/decode unchanged.
    again = json.loads(json.dumps(world))
    assert again["tick"] == world["tick"]
    assert len(again["zones"]) == world["rows"] * world["cols"]


def test_snapshot_does_not_advance():
    s = _started()
    t0 = s.handle({"cmd": Command.SNAPSHOT})["world"]["tick"]
    for _ in range(5):
        s.handle({"cmd": Command.SNAPSHOT})
    t1 = s.handle({"cmd": Command.SNAPSHOT})["world"]["tick"]
    assert t0 == t1 == 0


# --------------------------------------------------------------------------- #
# focus routing
# --------------------------------------------------------------------------- #
def test_set_focus_routes_to_world():
    s = _started()
    r = s.handle({"cmd": Command.SET_FOCUS, "zones": [10, 11, 12]})
    assert r["ok"] and r["focus"] == [10, 11, 12]
    assert s.world.focus == {10, 11, 12}


def test_focus_forces_promotion():
    s = _started(seed=1)
    s.handle({"cmd": Command.SET_FOCUS, "zones": [33]})
    r = s.handle({"cmd": Command.ADVANCE, "ticks": 1})
    assert 33 in r["promoted"]  # the focused zone is force-promoted


# --------------------------------------------------------------------------- #
# advancement: only, and exactly, on ADVANCE
# --------------------------------------------------------------------------- #
def test_advance_is_exact_no_duplication():
    a = _started(seed=3)
    b = _started(seed=3)
    # 20 single ticks vs one advance of 20 -> identical state.
    for _ in range(20):
        a.handle({"cmd": Command.ADVANCE, "ticks": 1})
    rb = b.handle({"cmd": Command.ADVANCE, "ticks": 20})
    ra = a.handle({"cmd": Command.SNAPSHOT})["world"]
    assert ra["tick"] == rb["tick"] == 20
    # aggregate totals must match too
    sa = a._summary()["totals"]
    assert sa == rb["totals"]


def test_advance_zero_is_noop():
    s = _started()
    r = s.handle({"cmd": Command.ADVANCE, "ticks": 0})
    assert r["ok"] and r["tick"] == 0 and r["advanced"] == 0


def test_advance_negative_rejected():
    s = _started()
    r = s.handle({"cmd": Command.ADVANCE, "ticks": -1})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


# --------------------------------------------------------------------------- #
# pause / resume
# --------------------------------------------------------------------------- #
def test_pause_freezes_advance_resume_continues_identically():
    # Reference: advance 10 then 10 with no pause.
    ref = _started(seed=9)
    ref.handle({"cmd": Command.ADVANCE, "ticks": 10})
    ref.handle({"cmd": Command.ADVANCE, "ticks": 10})
    ref_totals = ref._summary()["totals"]

    # Same, but PAUSE in the middle and attempt to advance (must be refused),
    # then RESUME and finish. The paused attempts must not change state.
    s = _started(seed=9)
    s.handle({"cmd": Command.ADVANCE, "ticks": 10})
    p = s.handle({"cmd": Command.PAUSE})
    assert p["paused"] is True
    mid = s._summary()["totals"]
    for _ in range(3):
        r = s.handle({"cmd": Command.ADVANCE, "ticks": 5})
        assert not r["ok"] and r["error"]["code"] == ErrorCode.PAUSED
    assert s._summary()["totals"] == mid          # nothing advanced while paused
    res = s.handle({"cmd": Command.RESUME})
    assert res["paused"] is False
    s.handle({"cmd": Command.ADVANCE, "ticks": 10})
    assert s._summary()["totals"] == ref_totals   # identical to the un-paused run


# --------------------------------------------------------------------------- #
# intervention routing + causality
# --------------------------------------------------------------------------- #
def test_intervene_routes_and_validates():
    s = _started()
    assert s.handle({"cmd": Command.INTERVENE, "action": "broadcast", "level": 1.0})["ok"]
    assert s.handle({"cmd": Command.INTERVENE, "action": "cordon", "zones": [33]})["ok"]
    bad = s.handle({"cmd": Command.INTERVENE, "action": "teleport"})
    assert not bad["ok"] and bad["error"]["code"] == ErrorCode.BAD_ARGUMENT
    nomiss = s.handle({"cmd": Command.INTERVENE})
    assert not nomiss["ok"] and nomiss["error"]["code"] == ErrorCode.BAD_ARGUMENT


def test_cordon_changes_future_authoritative_state():
    """The load-bearing M1 causal proof: same city/seed/inputs, but a cordon of
    the seed zone measurably changes the later authoritative world."""
    def run(cordon):
        s = _started(bundle=BIG_CITY, seed=7)
        if cordon:
            s.handle({"cmd": Command.INTERVENE, "action": "cordon",
                      "zones": [s.world.cfg.seed_zone]})
        last = None
        for _ in range(20):
            last = s.handle({"cmd": Command.ADVANCE, "ticks": 5})
        return last["totals"]

    base = run(False)
    cordoned = run(True)
    assert base != cordoned                                   # trajectory diverged
    assert _infected(cordoned) < _infected(base)              # cordon contained it
    # And it is a real simulation change, not a label: measurable magnitude.
    assert _infected(base) - _infected(cordoned) > 1.0


# --------------------------------------------------------------------------- #
# malformed input never crashes the session
# --------------------------------------------------------------------------- #
def test_malformed_inputs_rejected_cleanly():
    s = _started()
    assert s.handle(42)["error"]["code"] == ErrorCode.MALFORMED
    assert s.handle({"id": 1})["error"]["code"] == ErrorCode.MALFORMED
    assert s.handle({"cmd": "NOPE"})["error"]["code"] == ErrorCode.UNKNOWN_COMMAND
    # session still healthy afterwards
    assert s.handle({"cmd": Command.ADVANCE, "ticks": 1})["ok"]


# --------------------------------------------------------------------------- #
# socket transport: lifecycle, roundtrip, shutdown, deterministic replay
# --------------------------------------------------------------------------- #
def test_socket_roundtrip_and_shutdown():
    with BridgeServer() as srv:
        with BridgeClient(port=srv.port) as c:
            assert c.hello()["ok"]
            assert c.start_world(CITY, seed=1)["ok"]
            assert c.set_focus([33])["focus"] == [33]
            r = c.advance(ticks=6)
            assert r["tick"] == 6
            snap = c.snapshot()["world"]
            assert len(snap["zones"]) == 100
            assert c.intervene("shelter_order", zones=[33], strength=0.9)["ok"]
            assert c.pause()["paused"] is True
            assert c.advance(1)["error"]["code"] == ErrorCode.PAUSED
            assert c.resume()["paused"] is False
            assert c.send_raw("{not valid json")["error"]["code"] == ErrorCode.MALFORMED
            assert c.shutdown()["ok"]


def test_socket_deterministic_replay():
    stream = [
        (Command.HELLO, {"protocol_version": PROTOCOL_VERSION}),
        (Command.START_WORLD, {"bundle": CITY, "seed": 11}),
        (Command.SET_FOCUS, {"zones": [33]}),
        (Command.ADVANCE, {"ticks": 7}),
        (Command.INTERVENE, {"action": "cordon", "zones": [33]}),
        (Command.ADVANCE, {"ticks": 7}),
    ]

    def play():
        with BridgeServer() as srv:
            with BridgeClient(port=srv.port) as c:
                last = None
                for cmd, kw in stream:
                    last = c.send(cmd, **kw)
                return last

    a = play()
    b = play()
    assert a["totals"] == b["totals"]
    assert a["tick"] == b["tick"] == 14


if __name__ == "__main__":
    # dependency-light smoke run
    import types
    g = dict(globals())
    for name, fn in g.items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            fn()
            print("ok", name)
    print("all bridge smoke tests passed")

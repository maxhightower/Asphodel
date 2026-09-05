"""The work runtime does not depend on level of detail (§18, §19).

Work is authoritative simulation, not a presentation effect. With the player
20 km away nobody in the shop is PHYSICAL, yet sessions start, tasks progress
and objects change state. Walking the player onto the shop's doorstep promotes
those citizens to PHYSICAL and must change *nothing* but the band: the same
session, the same object, the same task instance, progress that carries on from
where it was. Walking away again must not reset a session or duplicate a hold.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge import PROTOCOL_VERSION, WorldSession
from asphodel.bridge.protocol import Command
from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.lod.entity import LODBand

CITY = "houston"
START_HOUR = 5.0
PLAYER = 129
SHOP = 6059
FAR = (200000.0, 200000.0)          # 200 km: nothing is near the player


def _houston_or_skip():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _sample(w, cids):
    wk = w.work
    return {
        "now_s": wk.now_s,
        "event_seq": wk.event_seq,
        "bands": {c: w.mobility.bands.get(c) for c in cids},
        "activities": {c: wk.activities[c].to_dict() for c in cids if c in wk.activities},
        "held": {c: wk.ledger.held_by(c) for c in cids},
        "holders": {oid: list(hs) for oid, hs in wk.ledger.holders.items() if hs},
        "deltas": dict(wk.registry(SHOP).state_deltas()),
    }


@pytest.fixture(scope="module")
def lod():
    _houston_or_skip()
    s = WorldSession()
    assert s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})["ok"]
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                  "start_hour": START_HOUR, "player_citizen": PLAYER})
    assert r["ok"], r
    w = s.world
    w.mobility.max_active = len(w.mobility.execs) + 1     # no ABSTRACT overflow tier here
    w.mobility.set_focus_xy(FAR)
    while w.current_hour() < 9.0:
        w.advance_seconds(60.0, focus_xy=FAR)

    inside = sorted(c for c, a in w.work.activities.items() if a.building_id == SHOP)
    assert inside, "nobody was inside the shop at 09:00"

    far_a = _sample(w, inside)
    w.advance_seconds(60.0, focus_xy=FAR)
    far_b = _sample(w, inside)

    entrance = w.mobility.entrances.get(SHOP)
    assert entrance is not None, "the shop has no entrance anchor"
    # Stand where the shop's own staff are standing: this Houston retail box is
    # bigger across than the 120 m physical radius, so its street entrance
    # anchor is not close enough to the tills to promote the people at them.
    near_xy = w.mobility.execs[PLAYER].pos
    w.advance_seconds(1.0, focus_xy=near_xy)
    near_a = _sample(w, inside)
    w.advance_seconds(60.0, focus_xy=near_xy)
    near_b = _sample(w, inside)

    w.advance_seconds(1.0, focus_xy=FAR)
    back_a = _sample(w, inside)
    w.advance_seconds(60.0, focus_xy=FAR)
    back_b = _sample(w, inside)

    return {"world": w, "inside": inside, "entrance": entrance, "near_xy": near_xy,
            "far_a": far_a, "far_b": far_b, "near_a": near_a, "near_b": near_b,
            "back_a": back_a, "back_b": back_b}


def _continuity(before, after, cids):
    """Sessions that exist on both sides must be the same session."""
    common = [c for c in cids if c in before["activities"] and c in after["activities"]]
    for c in common:
        a, b = before["activities"][c], after["activities"][c]
        assert b["session_start_s"] == a["session_start_s"], (c, "session restarted")
        assert b["building_id"] == a["building_id"], c
        assert b["kind"] == a["kind"] and b["role"] == a["role"], c
        assert b["task_instance"] >= a["task_instance"], (c, "task counter went backwards")
        if b["task_id"] == a["task_id"] and b["object_id"] == a["object_id"] \
                and b["task_instance"] == a["task_instance"]:
            assert b["progress_s"] >= a["progress_s"] - 1e-6, (c, a["progress_s"], b["progress_s"])
    return common


# --------------------------------------------------------------------------- #
def test_nobody_in_the_shop_is_physical_while_the_player_is_far(lod):
    for phase in ("far_a", "far_b"):
        bands = lod[phase]["bands"]
        assert bands, phase
        assert all(b is not LODBand.PHYSICAL for b in bands.values()), (phase, bands)


def test_sessions_run_and_progress_without_a_physical_band(lod):
    """S18: no body, and the work still happens."""
    a, b = lod["far_a"], lod["far_b"]
    assert b["event_seq"] > a["event_seq"], "no work event in a whole minute"
    assert b["now_s"] > a["now_s"]
    assert a["activities"], "no interior session at all"
    moved = [c for c in a["activities"] if c in b["activities"]
             and (b["activities"][c]["progress_s"] != a["activities"][c]["progress_s"]
                  or b["activities"][c]["task_instance"] != a["activities"][c]["task_instance"])]
    assert moved, "not one session advanced while unobserved"
    assert any(h for h in a["held"].values()), "nothing was reserved while unobserved"


def test_walking_up_to_the_shop_promotes_its_occupants_to_physical(lod):
    bands = lod["near_a"]["bands"]
    physical = [c for c, b in bands.items() if b is LODBand.PHYSICAL]
    assert physical, ("nobody was promoted next to the tills", bands)
    assert PLAYER in physical


def test_the_shops_street_entrance_is_further_than_the_physical_radius(lod):
    """Documents why the focus is placed at the tills and not at the door: this
    retail box is wider than the 120 m physical radius."""
    import math
    w = lod["world"]
    ex, ey = lod["entrance"]
    far_from_door = [c for c in lod["inside"]
                     if math.dist(w.mobility.execs[c].pos, (ex, ey)) > w.mobility.lod.physical_radius]
    assert len(far_from_door) >= 1, "the whole shop fits inside the physical radius"


def test_promotion_does_not_restart_or_move_a_session(lod):
    """S19: the band changes, the session does not."""
    common = _continuity(lod["far_b"], lod["near_a"], lod["inside"])
    assert common, "no session spanned the promotion"
    same = [c for c in common
            if lod["near_a"]["activities"][c]["object_id"] == lod["far_b"]["activities"][c]["object_id"]
            and lod["near_a"]["activities"][c]["task_id"] == lod["far_b"]["activities"][c]["task_id"]]
    assert same, "every session changed object/task across a one-second promotion"


def test_progress_is_continuous_across_the_promotion(lod):
    before, after = lod["far_b"], lod["near_a"]
    grew = []
    for c in lod["inside"]:
        a = before["activities"].get(c)
        b = after["activities"].get(c)
        if not a or not b or a["task_instance"] != b["task_instance"] or a["phase"] != "using":
            continue
        if b["phase"] != "using":
            continue
        assert b["progress_s"] >= a["progress_s"] - 1e-6, (c, a["progress_s"], b["progress_s"])
        if b["progress_s"] > a["progress_s"]:
            grew.append(c)
    assert grew, "no in-progress task ticked across the promotion"


def test_reservations_survive_the_promotion_unchanged(lod):
    before, after = lod["far_b"], lod["near_a"]
    for c in lod["inside"]:
        keep = [o for o in before["held"][c] if o in after["holders"]]
        for oid in keep:
            assert c in after["holders"][oid], (c, oid, "hold vanished on promotion")


def test_demoting_again_neither_resets_the_session_nor_duplicates_a_hold(lod):
    _continuity(lod["near_b"], lod["back_a"], lod["inside"])
    _continuity(lod["back_a"], lod["back_b"], lod["inside"])
    for phase in ("near_a", "near_b", "back_a", "back_b"):
        holders = lod[phase]["holders"]
        wk = lod["world"].work
        for oid, hs in holders.items():
            assert len(hs) == len(set(hs)), (phase, oid, hs)
            o = wk.registry(int(oid.split(":")[1])).get(oid)
            assert o is not None and len(hs) <= o.capacity, (phase, oid, hs)


def test_the_band_returns_to_route_simulated_when_the_player_leaves(lod):
    bands = lod["back_b"]["bands"]
    assert all(b is not LODBand.PHYSICAL for b in bands.values()), bands


def test_object_state_keeps_accumulating_across_every_band_change(lod):
    seq = [lod[p]["deltas"] for p in ("far_a", "far_b", "near_a", "near_b", "back_a", "back_b")]
    assert seq[0], "the shop's objects never changed state"
    for earlier, later in zip(seq, seq[1:]):
        assert set(earlier) <= set(later), "an object's persisted state was dropped"


def test_the_work_event_stream_never_stalls_or_rewinds(lod):
    seqs = [lod[p]["event_seq"] for p in ("far_a", "far_b", "near_a", "near_b", "back_a", "back_b")]
    assert seqs == sorted(seqs), seqs
    assert seqs[-1] > seqs[0]

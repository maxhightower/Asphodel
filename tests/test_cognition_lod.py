"""Cognition does not depend on level of detail
(ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §23, §24; N23/N24).

Memory, relationships and social decisions are authoritative simulation, not a
presentation effect. With the player 200 km away nobody in the shop where a
cashier helps a cleaner is PHYSICAL, yet co-presence accumulates, memories are
written and the help task is decided and run. Walking the player onto that
workplace's doorstep promotes its occupants and must change *nothing* but the
band.

The strongest form of that claim is checked by branching: the same saved world
is restored twice and given the same second of game time, once with the focus
far away and once on the building's entrance. The two cognition states must be
identical while the LOD bands differ.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.lod.entity import LODBand
from asphodel.save import load_world, world_state

CITY = "houston"
START_HOUR = 5.0
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
MORNING_HOUR = 8.5          # by then the city is busy enough for the claims to bite
FAR = (200000.0, 200000.0)
STOP_HOUR = 9.0


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _build(d):
    w = world_from_bundle(CITY, micro_params=MICRO, seed=0)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    w.enable_cognition()
    w.mobility.max_active = len(w.mobility.execs) + 1     # no ABSTRACT overflow tier here
    w.mobility.set_focus_xy(FAR)
    return w


def _reload(state, d):
    w = load_world(json.loads(json.dumps(state)))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    w.enable_cognition()
    w.mobility.max_active = len(w.mobility.execs) + 1
    return w


def _sample(w, cids):
    c = w.cognition
    return {
        "now_s": c.now_s,
        "event_seq": c.event_seq,
        "bands": {cid: w.mobility.bands.get(cid) for cid in cids},
        "stores": {cid: (c.memories[cid].seq, len(c.memories[cid]))
                   for cid in cids if cid in c.memories},
        "facts": {cid: sorted(c.memories[cid].facts) for cid in cids if cid in c.memories},
        "rels": {cid: [(r.other, r.interactions, round(r.familiarity, 6), round(r.affinity, 6))
                       for r in c.rels.of(cid)] for cid in cids},
        "help_pairs": {f"{a}:{b}": n for (a, b), n in sorted(c.help_pairs.items())},
        "help_cooldown": {cid: t for cid, t in sorted(c.help_cooldown.items())},
        "pending_help": {cid: dict(v) for cid, v in sorted(c.pending_help.items())},
        "help_log": [dict(r) for r in c.help_log],
        "help_for": {cid: w.work.activities[cid].help_for
                     for cid in cids if cid in w.work.activities},
        "counts": dict(sorted(c.counts.items())),
        # city-wide totals: cognition runs everywhere, not only where the player is
        "city": {"citizens_with_memory": len(c.memories),
                 "facts": sum(len(st) for st in c.memories.values()),
                 "rel_pairs": len(c.rels.rels),
                 "interactions": sum(r.interactions for r in c.rels.rels.values())},
    }


def _help_rows(w):
    return [dict(e) for e in w.cognition.events if e["event"] == "HELP_DECIDED"]


@pytest.fixture(scope="module")
def lod():
    d = _bundle_dir()
    w = _build(d)
    # run until some workplace has run a help task through to completion
    # (8470 on the seed-0 day, at about 07:37)
    def _done():
        return [e for e in w.cognition.events if e["event"] == "HELP_COMPLETED"]
    while w.current_hour() < STOP_HOUR and not _done():
        w.advance_seconds(60.0, focus_xy=FAR)
    assert _done(), f"nobody helped anybody anywhere before {STOP_HOUR:.0f}:00"
    workplace = _done()[0]["building_id"]
    decided = [e for e in _help_rows(w) if e["building_id"] == workplace]
    assert decided, f"a help completed in {workplace} that was never decided"

    # let the morning fill up: a busy city makes the LOD claims non-vacuous
    while w.current_hour() < MORNING_HOUR:
        w.advance_seconds(60.0, focus_xy=FAR)
    inside = sorted(c for c, a in w.work.activities.items() if a.building_id == workplace)
    assert inside, "nobody was inside the workplace"

    far_a = _sample(w, inside)
    w.advance_seconds(60.0, focus_xy=FAR)
    far_b = _sample(w, inside)

    entrance = w.mobility.entrances.get(workplace)
    assert entrance is not None, "the workplace has no entrance anchor"

    # ---- the branch: one saved second, lived twice under different bands
    state = json.loads(json.dumps(world_state(w, bundle=CITY, player_citizen=None)))
    wf = _reload(state, d)
    wf.advance_seconds(1.0, focus_xy=FAR)
    wn = _reload(state, d)
    wn.advance_seconds(1.0, focus_xy=tuple(entrance))
    branch = {
        "far_state": json.dumps(wf.cognition.to_state(), sort_keys=True),
        "near_state": json.dumps(wn.cognition.to_state(), sort_keys=True),
        "far_work": json.dumps(wf.work.snapshot(), sort_keys=True),
        "near_work": json.dumps(wn.work.snapshot(), sort_keys=True),
        "far_bands": {cid: wf.mobility.bands.get(cid) for cid in inside},
        "near_bands": {cid: wn.mobility.bands.get(cid) for cid in inside},
    }

    # ---- and the same promotion on the live world
    near_xy = tuple(entrance)
    w.advance_seconds(1.0, focus_xy=near_xy)
    near_a = _sample(w, inside)
    if not any(b is LODBand.PHYSICAL for b in near_a["bands"].values()):
        # this workplace is wider than the physical radius: stand at a worker
        near_xy = tuple(w.mobility.execs[inside[0]].pos)
        w.advance_seconds(1.0, focus_xy=near_xy)
        near_a = _sample(w, inside)
    w.advance_seconds(60.0, focus_xy=near_xy)
    near_b = _sample(w, inside)

    w.advance_seconds(1.0, focus_xy=FAR)
    back_a = _sample(w, inside)
    w.advance_seconds(60.0, focus_xy=FAR)
    back_b = _sample(w, inside)

    return {"world": w, "inside": inside, "entrance": entrance, "near_xy": near_xy,
            "workplace": workplace,
            "decided": decided, "branch": branch, "help_rows": _help_rows(w),
            "far_a": far_a, "far_b": far_b, "near_a": near_a, "near_b": near_b,
            "back_a": back_a, "back_b": back_b}


PHASES = ("far_a", "far_b", "near_a", "near_b", "back_a", "back_b")


# --------------------------------------------------------------------------- #
def test_nobody_in_the_workplace_is_physical_while_the_player_is_far(lod):
    for phase in ("far_a", "far_b", "back_b"):
        bands = lod[phase]["bands"]
        assert bands, phase
        assert all(b is not LODBand.PHYSICAL for b in bands.values()), (phase, bands)


def test_memories_and_relationships_accumulate_with_nobody_watching(lod):
    """N23: cognition is simulation, not presentation."""
    a, b = lod["far_a"], lod["far_b"]
    assert a["stores"], "the workplace's own people remembered nothing"
    assert a["city"]["citizens_with_memory"] > 20, a["city"]
    assert a["city"]["facts"] > 50 and a["city"]["rel_pairs"] > 100, a["city"]
    assert b["city"]["facts"] >= a["city"]["facts"]
    assert b["city"]["interactions"] > a["city"]["interactions"], \
        "no relationship moved in an unobserved minute"
    assert b["event_seq"] > a["event_seq"]
    assert sum(len(v) for v in a["rels"].values()) > 0


def test_the_help_task_was_decided_and_run_with_nobody_watching(lod):
    decided = lod["decided"]
    assert decided
    e = decided[0]
    assert e["citizen_id"] != e["beneficiary"]
    assert e["score"] >= e["threshold"]
    bands = lod["far_a"]["bands"]
    assert bands.get(e["citizen_id"]) is not LODBand.PHYSICAL
    assert lod["far_a"]["help_pairs"] or lod["far_b"]["help_pairs"]


def test_walking_up_to_the_workplace_promotes_its_occupants(lod):
    physical = [c for c, b in lod["near_a"]["bands"].items() if b is LODBand.PHYSICAL]
    assert physical, ("nobody was promoted at the doorstep", lod["near_a"]["bands"])


def test_the_same_second_lived_at_two_detail_levels_is_the_same_cognition(lod):
    """N23/N24 in its strongest form: identical state, identical second,
    different bands, byte-identical memories, relationships and social state."""
    b = lod["branch"]
    assert b["far_bands"] != b["near_bands"], "the promotion did not change any band"
    assert any(x is LODBand.PHYSICAL for x in b["near_bands"].values())
    assert all(x is not LODBand.PHYSICAL for x in b["far_bands"].values())
    assert b["near_state"] == b["far_state"], "cognition differed between LOD bands"
    assert b["near_work"] == b["far_work"], "the work layer differed between LOD bands"


def test_promotion_neither_resets_nor_accelerates_a_citizens_memory(lod):
    """N24: crossing the band boundary is not an event in anyone's life. The
    exact-identity form of this claim is the branch test above; here the live
    world must merely carry every fact, relationship and help across the
    boundary, and gain no more in the promoted second than in an ordinary one."""
    before, after = lod["far_b"], lod["near_a"]
    assert before["bands"] != after["bands"], "the promotion did not change any band"
    _carries_over(before, after)


def test_demoting_again_neither_resets_nor_drops_anything(lod):
    _carries_over(lod["near_b"], lod["back_a"])
    _carries_over(lod["back_a"], lod["back_b"])
    assert all(b is not LODBand.PHYSICAL for b in lod["back_a"]["bands"].values())


def _carries_over(before, after):
    for cid, facts in before["facts"].items():
        assert cid in after["facts"], (cid, "a memory store vanished")
        assert set(facts) <= set(after["facts"][cid]), (cid, "a fact was dropped")
        assert after["stores"][cid][0] >= before["stores"][cid][0], (cid, "seq rewound")
    for cid, rels in before["rels"].items():
        later = {row[0]: row for row in after["rels"][cid]}
        for other, interactions, fam, aff in rels:
            assert other in later, (cid, other, "a relationship vanished")
            assert later[other][1] >= interactions and later[other][2] >= fam, (cid, other)
    assert after["help_log"][:len(before["help_log"])] == before["help_log"]
    for k, n in before["help_pairs"].items():
        assert after["help_pairs"].get(k, 0) >= n, k
    for cid, t in before["help_cooldown"].items():
        assert after["help_cooldown"].get(cid) == t, cid


def test_a_promoted_second_costs_no_more_memory_than_an_unobserved_one(lod):
    """No burst of catch-up perception when the player walks up."""
    minute = lod["far_b"]["city"]["facts"] - lod["far_a"]["city"]["facts"]
    promo = lod["near_a"]["city"]["facts"] - lod["far_b"]["city"]["facts"]
    demo = lod["back_a"]["city"]["facts"] - lod["near_b"]["city"]["facts"]
    assert promo >= 0 and demo >= 0
    assert promo <= max(minute, 4), (promo, minute)
    assert demo <= max(minute, 4), (demo, minute)


def test_no_memory_is_ever_lost_or_rewound_by_a_band_change(lod):
    seq = [lod[p] for p in PHASES]
    for earlier, later in zip(seq, seq[1:]):
        assert later["event_seq"] >= earlier["event_seq"]
        assert later["now_s"] >= earlier["now_s"]
        for cid, (s, n) in earlier["stores"].items():
            assert cid in later["stores"], (cid, "a citizen's memory store vanished")
            s2, n2 = later["stores"][cid]
            assert s2 >= s, (cid, "the fact counter went backwards")
            assert n2 >= n or s2 > s, (cid, "facts disappeared without new ones arriving")
        for cid, facts in earlier["facts"].items():
            assert set(facts) <= set(later["facts"][cid]), (cid, "a fact was forgotten")
        for cid, rels in earlier["rels"].items():
            later_by_other = {o: row for row in later["rels"][cid] for o in (row[0],)}
            for other, interactions, fam, aff in rels:
                assert other in later_by_other, (cid, other, "a relationship vanished")
                assert later_by_other[other][1] >= interactions, (cid, other)
    assert seq[-1]["event_seq"] > seq[0]["event_seq"]


def test_no_help_task_is_decided_twice(lod):
    rows = lod["help_rows"]
    assert rows
    keys = [(e["citizen_id"], e["beneficiary"], e["task_id"], e["object_id"], e["t"]) for e in rows]
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    assert not dupes, f"the same help was decided twice: {dupes[:4]}"
    assert len({e["seq"] for e in rows}) == len(rows)
    # one helper runs one help task at a time: every decision closes before the next
    c = lod["world"].cognition
    completed = {e["decision_seq"]: e for e in c.events if e["event"] == "HELP_COMPLETED"}
    by_helper = {}
    for e in rows:
        prev = by_helper.get(e["citizen_id"])
        if prev is not None:
            assert prev["seq"] in completed, \
                f"helper {e['citizen_id']} was given a second task before finishing {prev['seq']}"
            assert completed[prev["seq"]]["seq"] < e["seq"]
        by_helper[e["citizen_id"]] = e
    assert len(lod["world"].work.activities) > 0


def test_the_help_state_only_ever_grows_across_band_changes(lod):
    seq = [lod[p] for p in PHASES]
    for earlier, later in zip(seq, seq[1:]):
        assert len(later["help_log"]) >= len(earlier["help_log"])
        assert later["help_log"][:len(earlier["help_log"])] == earlier["help_log"]
        for k, n in earlier["help_pairs"].items():
            assert later["help_pairs"].get(k, 0) >= n, k
        for k, v in earlier["counts"].items():
            assert later["counts"].get(k, 0) >= v, k

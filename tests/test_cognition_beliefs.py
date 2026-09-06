"""Beliefs derived from memory (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §8, §16).

Pure-Python. A belief is never stored: it is derived from the evidence in the
memory store, so it moves when the evidence moves and it can be wrong.

* one direct sighting produces danger:person, danger:room and danger:building;
* the same fact told by someone else (C3) is believed LESS than one seen;
* hearsay loses a further share per hop;
* two independent rumours accumulate (noisy-OR) without exceeding 1;
* a later PLACE_SAFE observation of the place halves the danger evidence (N19);
* a room danger makes the building somewhat dangerous;
* personality_for is deterministic and bounded (§18).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.cognition import memory as M
from asphodel.cognition.beliefs import (DANGER_ACT, HOP_DISCOUNT, danger_of_building,
                                        danger_of_person, danger_of_room, derive)
from asphodel.cognition.memory import MemoryStore
from asphodel.cognition.personality import TRAITS, Personality, personality_for

BID, RID, THREAT = 500, 3, 99
NOW = 1000.0


def _direct(owner=1, t=0.0, **kw):
    st = MemoryStore(owner)
    st.remember(M.THREAT_PERSON, t, actor=THREAT, building_id=BID, room_id=RID, **kw)
    return st


def _told(owner=1, t=0.0, *, teller=4, witness=7, hops=1, confidence=0.6, origin="7:1"):
    st = MemoryStore(owner)
    st.remember(M.THREAT_PERSON, t, actor=THREAT, building_id=BID, room_id=RID, source=M.TOLD,
                source_citizen=teller, origin_witness=witness, origin_id=origin, hops=hops,
                confidence=confidence)
    return st


# --------------------------------------------------------------------------- #
# one fact -> three beliefs
# --------------------------------------------------------------------------- #
def test_one_direct_sighting_yields_person_room_and_building_danger():
    b = derive(_direct(), NOW)
    assert set(b) == {f"danger:person:{THREAT}", f"danger:room:{BID}:{RID}",
                      f"danger:building:{BID}"}
    person = b[f"danger:person:{THREAT}"]
    room = b[f"danger:room:{BID}:{RID}"]
    building = b[f"danger:building:{BID}"]
    for x in (person, room, building):
        assert 0.0 < x.value <= 1.0
    assert person.first_hand is True and room.first_hand is True
    assert person.subject == THREAT and person.building_id is None
    assert room.building_id == BID and room.room_id == RID
    assert building.building_id == BID and building.room_id is None
    assert room.value >= DANGER_ACT, "a fresh sighting is not even actionable"
    assert danger_of_person(b, THREAT) == person.value
    assert danger_of_room(b, BID, RID) == room.value
    assert danger_of_building(b, BID) == building.value
    assert danger_of_room(b, BID, 999) == 0.0
    assert danger_of_building(b, 999) == 0.0
    assert danger_of_person(b, 12345) == 0.0
    assert room.evidence == ["1:1"] and person.evidence == ["1:1"]
    assert person.source_citizens == [] and room.source_citizens == []


def test_no_threat_facts_means_no_beliefs():
    st = MemoryStore(1)
    st.remember(M.WORKED_BESIDE, 0.0, actor=2, building_id=BID, room_id=RID)
    st.remember(M.HELPED_BY, 0.0, actor=3, building_id=BID, room_id=RID)
    assert derive(st, NOW) == {}


def test_an_outdoor_threat_has_no_place_belief_only_a_person_one():
    st = MemoryStore(1)
    st.remember(M.THREAT_PERSON, 0.0, actor=THREAT)
    b = derive(st, NOW)
    assert list(b) == [f"danger:person:{THREAT}"]


# --------------------------------------------------------------------------- #
# C3: told is believed less than seen
# --------------------------------------------------------------------------- #
def test_a_told_fact_with_lower_confidence_gives_lower_danger_than_a_seen_one():
    seen = derive(_direct(), NOW)
    heard = derive(_told(), NOW)
    for key in (f"danger:person:{THREAT}", f"danger:room:{BID}:{RID}", f"danger:building:{BID}"):
        assert heard[key].value < seen[key].value, key
    assert heard[f"danger:room:{BID}:{RID}"].first_hand is False
    assert heard[f"danger:room:{BID}:{RID}"].source_citizens == [4]
    assert heard[f"danger:person:{THREAT}"].source_citizens == [4]


def test_hearsay_is_discounted_a_further_share_per_hop():
    one = derive(_told(hops=1, confidence=0.6), NOW)
    two = derive(_told(hops=2, confidence=0.6), NOW)
    three = derive(_told(hops=3, confidence=0.6), NOW)
    v1 = one[f"danger:room:{BID}:{RID}"].value
    v2 = two[f"danger:room:{BID}:{RID}"].value
    v3 = three[f"danger:room:{BID}:{RID}"].value
    assert v1 > v2 > v3 > 0.0
    assert v2 == pytest.approx(v1 * HOP_DISCOUNT)
    assert v3 == pytest.approx(v1 * HOP_DISCOUNT ** 2)


def test_a_stale_rumour_is_weaker_than_a_fresh_one():
    fresh = derive(_told(t=NOW), NOW)
    stale = derive(_told(t=0.0), NOW + 5.0 * 86400.0)
    assert stale[f"danger:room:{BID}:{RID}"].value < fresh[f"danger:room:{BID}:{RID}"].value


# --------------------------------------------------------------------------- #
# accumulation
# --------------------------------------------------------------------------- #
def test_two_rumours_about_different_threats_accumulate_by_noisy_or():
    st = MemoryStore(1)
    st.remember(M.THREAT_PERSON, 0.0, actor=THREAT, building_id=BID, room_id=RID, source=M.TOLD,
                source_citizen=4, origin_witness=7, origin_id="7:1", hops=1, confidence=0.5)
    st.remember(M.THREAT_PERSON, 0.0, actor=THREAT + 1, building_id=BID, room_id=RID,
                source=M.TOLD, source_citizen=5, origin_witness=8, origin_id="8:1", hops=1,
                confidence=0.5)
    b = derive(st, 0.0)
    one = 0.5
    room = b[f"danger:room:{BID}:{RID}"]
    assert room.value == pytest.approx(1.0 - (1 - one) * (1 - one))
    assert room.value > one, "a second rumour did not add anything"
    assert room.value < 1.0
    assert sorted(room.source_citizens) == [4, 5]
    assert len(room.evidence) == 2


def test_evidence_never_pushes_a_belief_above_one():
    st = MemoryStore(1)
    for i in range(20):
        st.remember(M.THREAT_PERSON, 0.0, actor=THREAT + i, building_id=BID, room_id=RID)
    b = derive(st, 0.0)
    for x in b.values():
        assert 0.0 <= x.value <= 1.0
    assert b[f"danger:room:{BID}:{RID}"].value == pytest.approx(1.0)
    assert b[f"danger:building:{BID}"].value <= 1.0


# --------------------------------------------------------------------------- #
# N19: contradicting evidence
# --------------------------------------------------------------------------- #
def test_a_later_place_safe_halves_the_evidence_of_the_threat():
    st = _direct(t=100.0)
    before = derive(st, NOW)[f"danger:room:{BID}:{RID}"].value
    st.remember(M.PLACE_SAFE, NOW, building_id=BID, room_id=RID, t=NOW)
    after = derive(st, NOW)[f"danger:room:{BID}:{RID}"].value
    assert after == pytest.approx(before * 0.5)
    assert after < before


def test_a_place_safe_from_before_the_threat_changes_nothing():
    st = _direct(t=500.0)
    before = derive(st, NOW)[f"danger:room:{BID}:{RID}"].value
    st.remember(M.PLACE_SAFE, NOW, building_id=BID, room_id=RID, t=100.0)
    assert derive(st, NOW)[f"danger:room:{BID}:{RID}"].value == pytest.approx(before)


def test_a_place_safe_in_another_room_does_not_discount_this_one():
    st = _direct(t=100.0)
    before = derive(st, NOW)[f"danger:room:{BID}:{RID}"].value
    st.remember(M.PLACE_SAFE, NOW, building_id=BID, room_id=RID + 1, t=NOW)
    assert derive(st, NOW)[f"danger:room:{BID}:{RID}"].value == pytest.approx(before)
    st.remember(M.PLACE_SAFE, NOW, building_id=BID + 1, room_id=RID, t=NOW)
    assert derive(st, NOW)[f"danger:room:{BID}:{RID}"].value == pytest.approx(before)


def test_observing_safety_does_not_erase_the_person_belief():
    """The room may be safe now; the undead citizen is still dangerous."""
    st = _direct(t=100.0)
    person_before = derive(st, NOW)[f"danger:person:{THREAT}"].value
    st.remember(M.PLACE_SAFE, NOW, building_id=BID, room_id=RID, t=NOW)
    assert derive(st, NOW)[f"danger:person:{THREAT}"].value == pytest.approx(person_before)


# --------------------------------------------------------------------------- #
# building aggregate
# --------------------------------------------------------------------------- #
def test_a_room_danger_makes_the_building_somewhat_dangerous():
    b = derive(_direct(), NOW)
    room = b[f"danger:room:{BID}:{RID}"].value
    building = b[f"danger:building:{BID}"].value
    assert building == pytest.approx(room * 0.9)
    assert 0.0 < building < room, "the building is as dangerous as its worst room"


def test_two_dangerous_rooms_make_the_building_more_dangerous_than_either():
    st = MemoryStore(1)
    st.remember(M.THREAT_PERSON, 0.0, actor=THREAT, building_id=BID, room_id=1)
    st.remember(M.THREAT_PERSON, 0.0, actor=THREAT + 1, building_id=BID, room_id=2)
    b = derive(st, 0.0)
    r1 = b[f"danger:room:{BID}:1"].value
    r2 = b[f"danger:room:{BID}:2"].value
    assert b[f"danger:building:{BID}"].value > max(r1, r2) * 0.9
    assert b[f"danger:building:{BID}"].value <= 1.0


def test_a_building_wide_threat_fact_and_its_rooms_combine():
    """A fact with no room (a shout heard through the building) is itself a
    building belief, and room evidence adds to it."""
    st = MemoryStore(1)
    st.remember(M.WORKPLACE_DISRUPTED, 0.0, building_id=BID)       # not a threat kind
    st.remember(M.CORPSE_SEEN, 0.0, target=THREAT, building_id=BID, source=M.TOLD,
                source_citizen=4, origin_witness=7, origin_id="7:1", hops=1, confidence=0.5)
    b = derive(st, 0.0)
    only_building = b[f"danger:building:{BID}"].value
    assert only_building > 0.0
    assert f"danger:room:{BID}:None" not in b
    st.remember(M.THREAT_PERSON, 0.0, actor=THREAT, building_id=BID, room_id=RID,
                source=M.TOLD, source_citizen=5, origin_witness=8, origin_id="8:1", hops=1,
                confidence=0.5)
    b2 = derive(st, 0.0)
    assert b2[f"danger:building:{BID}"].value > only_building
    assert b2[f"danger:building:{BID}"].evidence, "the building belief lost its own evidence"


def test_belief_rows_are_json_shaped_and_rounded():
    b = derive(_told(), NOW)
    for x in b.values():
        d = x.to_dict()
        assert set(d) == {"key", "value", "evidence", "first_hand", "source_citizens", "subject",
                          "building_id", "room_id", "last_t"}
        assert d["value"] == round(x.value, 3)
        assert isinstance(d["evidence"], list) and isinstance(d["source_citizens"], list)


def test_derive_is_deterministic_for_the_same_store():
    st = _direct()
    a = {k: v.to_dict() for k, v in derive(st, NOW).items()}
    b = {k: v.to_dict() for k, v in derive(st, NOW).items()}
    assert a == b


# --------------------------------------------------------------------------- #
# personality (§18)
# --------------------------------------------------------------------------- #
def test_personality_is_deterministic_and_bounded():
    for cid in (0, 1, 7, 129, 297, 8470):
        p = personality_for(0, cid)
        assert personality_for(0, cid) == p, "personality drifted between calls"
        assert isinstance(p, Personality)
        for t in TRAITS:
            v = getattr(p, t)
            assert 0.0 <= v <= 1.0, (cid, t, v)
        assert set(p.to_dict()) == set(TRAITS)


def test_personality_depends_on_both_seed_and_citizen():
    a = personality_for(0, 1)
    b = personality_for(0, 2)
    c = personality_for(1, 1)
    assert a != b and a != c


def test_personalities_are_diverse_but_mostly_moderate():
    people = [personality_for(0, cid) for cid in range(400)]
    for t in TRAITS:
        vals = [getattr(p, t) for p in people]
        assert len(set(vals)) > 100, (t, "the whole city has one personality")
        assert 0.4 < sum(vals) / len(vals) < 0.6, (t, "the trait is not centred")
        assert max(vals) > 0.85 and min(vals) < 0.15, (t, "no extremes at all")
        # triangular-ish: the middle third holds more than a uniform's third
        mid = sum(1 for v in vals if 1 / 3 <= v <= 2 / 3)
        assert mid / len(vals) > 0.40, (t, mid / len(vals))

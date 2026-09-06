"""Structured episodic memory (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §6, §7).

Pure-Python: a MemoryStore is a bounded, deterministic, provenance-carrying
container. Nothing here needs a world.

What is asserted:

* the same event seen again REINFORCES one fact (count, last_t) and never
  creates a second row for the same merge key;
* a first-hand account supersedes hearsay when it reinforces a told fact
  (the provenance collapses to the owner, hops back to 0);
* confidence decays: ``effective()`` is exactly half at one half-life;
* consolidation drops decayed non-durable facts, respects CAPACITY, and
  keeps durable (salience >= 0.80) facts last;
* a TOLD fact keeps origin_witness / origin_id / hops / source_citizen;
* to_state/from_state is byte-identical under json.dumps(sort_keys=True);
* two stores fed the same sequence are identical (determinism).
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.cognition import memory as M
from asphodel.cognition.memory import MemoryFact, MemoryStore


def _dump(store) -> str:
    return json.dumps(store.to_state(), sort_keys=True)


def _feed(store, t0=0.0):
    """A deterministic sequence of writes used by several tests."""
    store.remember(M.WORKED_BESIDE, t0 + 10.0, actor=2, building_id=100, room_id=1)
    store.remember(M.WORKED_BESIDE, t0 + 20.0, actor=2, building_id=100, room_id=1)
    store.remember(M.SERVED, t0 + 30.0, target=3, building_id=100, room_id=0,
                   object_id="so:100:1", source=M.PARTICIPANT)
    store.remember(M.THREAT_PERSON, t0 + 40.0, actor=9, building_id=100, room_id=0,
                   source=M.TOLD, source_citizen=5, origin_witness=7, origin_id="7:3",
                   hops=1, confidence=0.6)
    store.remember(M.HELPED_BY, t0 + 50.0, actor=4, target=1, building_id=100, room_id=2,
                   source=M.PARTICIPANT)
    return store


# --------------------------------------------------------------------------- #
# merge / reinforcement
# --------------------------------------------------------------------------- #
def test_the_same_event_reinforces_one_fact_and_never_makes_a_second():
    st = MemoryStore(1)
    f1, created1 = st.remember(M.WORKED_BESIDE, 100.0, actor=2, building_id=10, room_id=3)
    assert created1 is True and f1.count == 1
    for i, t in enumerate((200.0, 300.0, 400.0), start=2):
        f, created = st.remember(M.WORKED_BESIDE, t, actor=2, building_id=10, room_id=3)
        assert created is False, "a merge key was stored twice"
        assert f.fact_id == f1.fact_id
        assert f.count == i
        assert f.last_t == t
    assert len(st) == 1
    assert len(st.find(M.WORKED_BESIDE, actor=2)) == 1


def test_the_merge_key_is_kind_actor_target_building_room():
    """Anything that differs in one of the five key fields is a separate fact."""
    st = MemoryStore(1)
    base = dict(actor=2, target=3, building_id=10, room_id=4)
    st.remember(M.MET, 10.0, **base)
    variants = [dict(base, kind=M.WORKED_BESIDE), dict(base, actor=99), dict(base, target=99),
                dict(base, building_id=99), dict(base, room_id=99)]
    for v in variants:
        kind = v.pop("kind", M.MET)
        st.remember(kind, 10.0, **v)
    assert len(st) == 1 + len(variants)
    # the object_id is NOT part of the key: it updates the existing fact
    n = len(st)
    f, created = st.remember(M.MET, 20.0, object_id="so:10:7", **base)
    assert created is False and len(st) == n and f.object_id == "so:10:7"


def test_reinforcement_never_lowers_confidence():
    st = MemoryStore(1)
    st.remember(M.THREAT_PERSON, 0.0, actor=9, building_id=1, room_id=0, confidence=0.9)
    f, _ = st.remember(M.THREAT_PERSON, 10.0, actor=9, building_id=1, room_id=0, confidence=0.2)
    assert f.confidence == 0.9


def test_a_first_hand_account_supersedes_hearsay_on_reinforcement():
    st = MemoryStore(1)
    told, _ = st.remember(M.THREAT_PERSON, 0.0, actor=9, building_id=5, room_id=0, source=M.TOLD,
                          source_citizen=4, origin_witness=7, origin_id="7:2", hops=1,
                          confidence=0.5)
    assert told.source == M.TOLD and told.first_hand() is False
    seen, created = st.remember(M.THREAT_PERSON, 60.0, actor=9, building_id=5, room_id=0,
                                source=M.DIRECT, confidence=1.0)
    assert created is False and seen.fact_id == told.fact_id, "seeing it made a second fact"
    assert seen.source == M.DIRECT and seen.first_hand() is True
    assert seen.source_citizen is None and seen.hops == 0
    assert seen.origin_witness == 1 and seen.origin_id == seen.fact_id
    assert seen.confidence == 1.0


def test_hearsay_does_not_downgrade_a_first_hand_fact():
    st = MemoryStore(1)
    seen, _ = st.remember(M.ATTACK_SEEN, 0.0, actor=9, target=3, building_id=5, room_id=0)
    f, created = st.remember(M.ATTACK_SEEN, 30.0, actor=9, target=3, building_id=5, room_id=0,
                             source=M.TOLD, source_citizen=4, origin_witness=8, origin_id="8:1",
                             hops=1, confidence=0.4)
    assert created is False
    assert f.source == M.DIRECT and f.hops == 0 and f.source_citizen is None
    assert f.origin_witness == 1


# --------------------------------------------------------------------------- #
# decay
# --------------------------------------------------------------------------- #
def test_effective_confidence_halves_at_exactly_one_half_life():
    st = MemoryStore(1)
    f, _ = st.remember(M.MET, 0.0, actor=2, building_id=1, room_id=0)
    hl = M.half_life_s(f.salience)
    assert f.effective(0.0) == pytest.approx(1.0)
    assert f.effective(hl) == pytest.approx(0.5)
    assert f.effective(2 * hl) == pytest.approx(0.25)
    assert f.effective(-100.0) == pytest.approx(1.0), "a fact from the future is not amplified"


def test_a_salient_fact_outlives_a_trivial_one():
    assert M.half_life_s(0.0) == pytest.approx(7200.0)
    assert M.half_life_s(1.0) == pytest.approx(3.0 * 86400.0)
    assert M.half_life_s(M.SALIENCE[M.ATTACK_SEEN]) > M.half_life_s(M.SALIENCE[M.MET]) * 10
    st = MemoryStore(1)
    trivial, _ = st.remember(M.MET, 0.0, actor=2)
    major, _ = st.remember(M.ATTACKED_BY, 0.0, actor=3)
    day = 86400.0
    assert trivial.effective(day) < 0.01
    assert major.effective(day) > 0.5


def test_decay_restarts_from_the_last_reinforcement_not_the_first_sighting():
    st = MemoryStore(1)
    f, _ = st.remember(M.MET, 0.0, actor=2)
    hl = M.half_life_s(f.salience)
    st.remember(M.MET, hl, actor=2)
    assert f.last_t == hl
    assert f.effective(hl) == pytest.approx(1.0)
    assert f.effective(2 * hl) == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# consolidation
# --------------------------------------------------------------------------- #
def test_consolidate_drops_decayed_non_durable_facts_and_keeps_durable_ones():
    st = MemoryStore(1)
    trivial, _ = st.remember(M.MET, 0.0, actor=2)
    beside, _ = st.remember(M.WORKED_BESIDE, 0.0, actor=3)
    durable, _ = st.remember(M.ATTACKED_BY, 0.0, actor=4)
    assert durable.durable() and not trivial.durable()
    now = 30.0 * 86400.0
    assert durable.effective(now) < M.FORGET_BELOW, "the durable fact was not decayed at all"
    dropped = st.consolidate(now)
    assert sorted(dropped) == sorted([trivial.fact_id, beside.fact_id])
    assert set(st.facts) == {durable.fact_id}
    assert st.forgotten == 2
    # a dropped fact's merge key is released: the same event can be learned afresh
    f, created = st.remember(M.MET, now, actor=2)
    assert created is True and f.fact_id != trivial.fact_id


def test_consolidate_enforces_capacity_and_forgets_durable_facts_last():
    st = MemoryStore(1, capacity=8)
    now = 100.0
    durable = []
    for i in range(4):
        f, _ = st.remember(M.ATTACKED_BY, now, actor=1000 + i)
        durable.append(f.fact_id)
    trivial = []
    for i in range(20):
        f, _ = st.remember(M.MET, now, actor=i)
        trivial.append(f.fact_id)
    assert len(st) == 24
    dropped = st.consolidate(now)
    assert len(st) == 8, len(st)
    assert set(durable) <= set(st.facts), "a durable fact was dropped while trivia survived"
    assert set(durable) & set(dropped) == set()
    assert len(dropped) == 16


def test_consolidate_is_a_no_op_on_a_fresh_small_store():
    st = _feed(MemoryStore(1))
    assert st.consolidate(60.0) == []
    assert len(st) == 4


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #
def test_a_told_fact_carries_the_original_witness_teller_and_hop_depth():
    st = MemoryStore(1)
    f, _ = st.remember(M.THREAT_PERSON, 500.0, actor=9, building_id=5, room_id=1, source=M.TOLD,
                       source_citizen=4, origin_witness=7, origin_id="7:12", hops=2,
                       confidence=0.42, t=300.0)
    assert f.source == M.TOLD and f.first_hand() is False
    assert f.source_citizen == 4
    assert f.origin_witness == 7
    assert f.origin_id == "7:12"
    assert f.hops == 2
    assert f.confidence == pytest.approx(0.42)
    assert f.t == 300.0 and f.last_t == 500.0, "the fact keeps the event time, not the telling"
    assert f.owner == 1 and f.fact_id.startswith("1:")


def test_a_first_hand_fact_is_its_own_origin():
    st = MemoryStore(6)
    for source in (M.DIRECT, M.PARTICIPANT):
        f, _ = st.remember(M.ATTACK_SEEN, 0.0, actor=9, target=source, source=source)
        assert f.origin_witness == 6
        assert f.origin_id == f.fact_id
        assert f.hops == 0 and f.source_citizen is None
        assert f.first_hand() is True


def test_known_people_covers_actors_targets_and_tellers():
    st = _feed(MemoryStore(1))
    assert st.known_people() == [2, 3, 4, 5, 9]


# --------------------------------------------------------------------------- #
# persistence / determinism
# --------------------------------------------------------------------------- #
def test_state_round_trips_byte_identically():
    st = _feed(MemoryStore(1))
    st.consolidate(100.0)
    before = _dump(st)
    back = MemoryStore.from_state(json.loads(json.dumps(st.to_state())))
    assert _dump(back) == before
    assert back.owner == st.owner and back.seq == st.seq and back.capacity == st.capacity
    assert back.forgotten == st.forgotten
    for fid, f in st.facts.items():
        assert back.facts[fid].to_dict() == f.to_dict()


def test_a_restored_store_still_merges_onto_the_restored_facts():
    """The merge index is rebuilt on load, not lost: the same event reinforces."""
    st = _feed(MemoryStore(1))
    back = MemoryStore.from_state(st.to_state())
    n = len(back)
    f, created = back.remember(M.WORKED_BESIDE, 900.0, actor=2, building_id=100, room_id=1)
    assert created is False and len(back) == n
    assert f.count == 3
    # and new facts do not collide with restored ids
    g, created = back.remember(M.MET, 900.0, actor=42)
    assert created is True and g.fact_id not in st.facts


def test_two_stores_fed_the_same_sequence_are_identical():
    a = _feed(MemoryStore(1))
    b = _feed(MemoryStore(1))
    assert _dump(a) == _dump(b)
    a.consolidate(3.0 * 86400.0)
    b.consolidate(3.0 * 86400.0)
    assert _dump(a) == _dump(b)


def test_the_state_is_json_clean_and_sorted_by_fact_id():
    st = _feed(MemoryStore(1))
    state = st.to_state()
    assert json.loads(json.dumps(state)) == state
    ids = [f["fact_id"] for f in state["facts"]]
    assert ids == sorted(ids)
    for f in state["facts"]:
        assert set(f) == set(MemoryFact.__dataclass_fields__)


def test_every_kind_has_a_salience_and_a_valence():
    for kind in M.KINDS:
        assert kind in M.SALIENCE, kind
        assert kind in M.VALENCE, kind
        assert 0.0 <= M.SALIENCE[kind] <= 1.0
        assert -1.0 <= M.VALENCE[kind] <= 1.0
    for kind in M.THREAT_KINDS:
        assert kind in M.KINDS and M.VALENCE[kind] < 0.0
        assert M.SALIENCE[kind] >= M.DURABLE_SALIENCE, (kind, "a threat that is not durable")


def test_salient_orders_by_effective_confidence_times_salience():
    st = MemoryStore(1)
    st.remember(M.MET, 0.0, actor=2)
    st.remember(M.ATTACKED_BY, 0.0, actor=3)
    st.remember(M.HELPED_BY, 0.0, actor=4)
    top = st.salient(3600.0, 2)
    assert [f.kind for f in top] == [M.ATTACKED_BY, M.HELPED_BY]

"""Grounding: what a speaker may assert and with which epistemic status
(ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 §2, §6, §7, §20, §21).

No world here: :mod:`asphodel.dialogue.grounding` takes ONE citizen's memory
store and nothing else, so the whole authority split can be exercised on
hand-built stores.

* :func:`proposition_from_fact` maps the fact's source onto the epistemic
  status the speaker is allowed to claim (participant -> EXPERIENCED, seen ->
  DIRECT, told once and believed -> SECOND_HAND, told twice or weakly ->
  HEARSAY);
* :func:`ground` rejects an assertion no fact supports, rejects one whose
  subject or room disagrees with the fact, and downgrades a first-hand claim
  made on a told fact (never the reverse), capping confidence at the fact's
  effective confidence;
* :func:`retrieve` is bounded (TOP_K), never returns a fact that has decayed
  below the retrieval floor, and ranks subject/place matches first;
* the four question answerers (:func:`event_answer`, :func:`person_answer`,
  :func:`safety_answer`, :func:`location_answer`) each fall back to a
  grounded "I don't know" rather than inventing anything.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.cognition import memory as M
from asphodel.cognition.beliefs import derive
from asphodel.dialogue import acts as A
from asphodel.dialogue import grounding as G

NOW = 100_000.0


def _store(owner: int = 1) -> M.MemoryStore:
    return M.MemoryStore(owner)


def _told(store, kind, *, hops=1, conf=0.8, teller=2, origin=3, t=None, **kw):
    f, _ = store.remember(kind, NOW if t is None else t, source=M.TOLD, source_citizen=teller,
                          origin_witness=origin, origin_id=f"{origin}:1", hops=hops, confidence=conf,
                          t=NOW if t is None else t, **kw)
    return f


# --------------------------------------------------------------------------- #
# epistemic mapping
# --------------------------------------------------------------------------- #
def test_the_fact_source_decides_the_epistemic_status_not_the_speaker():
    st = _store()
    seen, _ = st.remember(M.ATTACK_SEEN, NOW, actor=7, target=8, building_id=100, room_id=0)
    mine, _ = st.remember(M.ATTACKED_BY, NOW, actor=7, target=1, building_id=100, room_id=0,
                          source=M.PARTICIPANT)
    heard = _told(st, M.THREAT_PERSON, actor=9, building_id=101, hops=1, conf=0.8)
    far = _told(st, M.THREAT_PERSON, actor=10, building_id=102, hops=2, conf=0.8)
    weak = _told(st, M.THREAT_PERSON, actor=11, building_id=103, hops=1,
                 conf=G.WEAK_CONFIDENCE - 0.1)

    assert G.epistemic_of(mine, NOW) == A.EXPERIENCED
    assert G.epistemic_of(seen, NOW) == A.DIRECT
    assert G.epistemic_of(heard, NOW) == A.SECOND_HAND
    assert G.epistemic_of(far, NOW) == A.HEARSAY, "two hops is hearsay, not second hand"
    assert G.epistemic_of(weak, NOW) == A.HEARSAY, "a weakly believed telling is hearsay"

    p = G.proposition_from_fact(heard, NOW)
    assert p.kind == A.PERSON_IS_DANGEROUS and p.subject == 9
    assert p.epistemic == A.SECOND_HAND
    assert p.source_citizen == 2 and p.origin_witness == 3 and p.hops == 1
    assert p.event_ref == heard.fact_id
    assert 0.0 < p.confidence <= 1.0

    # a first-hand fact never names a teller
    assert G.proposition_from_fact(seen, NOW).source_citizen is None


def test_a_told_fact_becomes_hearsay_once_it_has_decayed_below_the_weak_line():
    st = _store()
    f = _told(st, M.THREAT_PERSON, actor=9, building_id=101, hops=1, conf=0.9)
    assert G.epistemic_of(f, NOW) == A.SECOND_HAND
    later = NOW + 4 * M.half_life_s(f.salience)
    assert f.effective(later) < G.WEAK_CONFIDENCE
    assert G.epistemic_of(f, later) == A.HEARSAY


# --------------------------------------------------------------------------- #
# ground(): the validator
# --------------------------------------------------------------------------- #
def test_an_unsupported_proposition_is_rejected():
    st = _store()
    st.remember(M.MET, NOW, actor=5, building_id=100)
    p = A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=101, epistemic=A.DIRECT,
                      confidence=1.0)
    g, verdict = G.ground(st, p, NOW)
    assert g is None and verdict == "rejected:unsupported"
    # nothing in an empty store supports anything either
    assert G.ground(_store(2), p, NOW) == (None, "rejected:unsupported")
    assert G.ground(None, p, NOW) == (None, "rejected:no_memory")


def test_a_proposition_with_the_wrong_subject_or_room_is_rejected():
    st = _store()
    st.remember(M.THREAT_PERSON, NOW, actor=9, building_id=100, room_id=0)
    ok, verdict = G.ground(st, A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=100,
                                             room_id=0), NOW)
    assert ok is not None and verdict == "accepted"
    for bad in (A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=8, building_id=100, room_id=0),
                A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=100, room_id=3),
                A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=999)):
        g, v = G.ground(st, bad, NOW)
        assert g is None and v == "rejected:unsupported", bad


def test_a_first_hand_claim_on_a_told_fact_is_downgraded_and_capped():
    st = _store()
    f = _told(st, M.THREAT_PERSON, actor=9, building_id=101, hops=1, conf=0.6)
    claim = A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=101,
                          epistemic=A.DIRECT, confidence=1.0, source_citizen=None)
    g, verdict = G.ground(st, claim, NOW)
    assert verdict == "downgraded:source", verdict
    assert g.epistemic == A.SECOND_HAND, "a told fact may never be spoken as 'I saw'"
    assert g.source_citizen == 2 and g.hops == 1
    assert g.confidence <= f.effective(NOW) + 1e-9 < 1.0, "confidence is capped by the fact"


def test_an_overconfident_claim_on_a_real_observation_is_downgraded_in_confidence():
    st = _store()
    f, _ = st.remember(M.THREAT_PERSON, NOW - 4 * 3600.0, actor=9, building_id=101, confidence=0.7)
    f.last_t = NOW - 4 * 3600.0
    eff = f.effective(NOW)
    assert eff < 0.7
    g, verdict = G.ground(st, A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=101,
                                            epistemic=A.DIRECT, confidence=1.0), NOW)
    assert verdict == "downgraded:confidence", verdict
    assert g.epistemic == A.DIRECT
    assert abs(g.confidence - min(1.0, eff)) < 1e-6


def test_an_unknown_proposition_needs_no_support():
    st = _store()
    p = A.Proposition(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE)
    assert G.ground(st, p, NOW) == (p, "accepted")
    assert G.ground(None, p, NOW) == (p, "accepted")


def test_a_fact_that_has_decayed_past_recall_supports_nothing():
    st = _store()
    f = _told(st, M.THREAT_PERSON, actor=9, building_id=101, hops=1, conf=0.05)
    assert f.effective(NOW) < G.RETRIEVAL_FLOOR
    g, v = G.ground(st, A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=101), NOW)
    assert g is None and v == "rejected:unsupported"


# --------------------------------------------------------------------------- #
# retrieve(): bounded, floored, ranked
# --------------------------------------------------------------------------- #
def test_retrieval_is_bounded_to_top_k():
    st = _store()
    for i in range(20):
        st.remember(M.MET, NOW, actor=100 + i, building_id=200 + i)
    out = G.retrieve(st, NOW, kinds=(M.MET,))
    assert len(out) == G.TOP_K
    assert len(G.retrieve(st, NOW, kinds=(M.MET,), top_k=3)) == 3
    assert G.retrieve(None, NOW, kinds=(M.MET,)) == []


def test_retrieval_never_returns_a_fact_below_the_floor():
    st = _store()
    strong, _ = st.remember(M.THREAT_PERSON, NOW, actor=9, building_id=100)
    faint = _told(st, M.THREAT_PERSON, actor=10, building_id=100, hops=1, conf=0.05)
    old, _ = st.remember(M.MET, NOW - 20 * 3600.0, actor=11, building_id=100, confidence=0.5)
    old.last_t = NOW - 20 * 3600.0
    assert faint.effective(NOW) < G.RETRIEVAL_FLOOR and old.effective(NOW) < G.RETRIEVAL_FLOOR
    got = {f.fact_id for f in G.retrieve(st, NOW, building_id=100, top_k=10)}
    assert strong.fact_id in got
    assert faint.fact_id not in got and old.fact_id not in got
    assert all(f.effective(NOW) >= G.RETRIEVAL_FLOOR for f in G.retrieve(st, NOW, building_id=100))


def test_retrieval_ranks_the_asked_subject_and_place_first():
    st = _store()
    for i in range(6):
        st.remember(M.MET, NOW, actor=50 + i, building_id=300 + i)
    wanted, _ = st.remember(M.MET, NOW, actor=77, building_id=999)
    top = G.retrieve(st, NOW, subject=77)
    assert top and top[0].fact_id == wanted.fact_id
    assert all(f.actor == 77 or f.target == 77 or f.source_citizen == 77 for f in top)
    place = G.retrieve(st, NOW, building_id=999)
    assert place and place[0].fact_id == wanted.fact_id
    assert all(f.building_id == 999 for f in place)


# --------------------------------------------------------------------------- #
# the four answerers
# --------------------------------------------------------------------------- #
def test_event_answer_is_unknown_on_an_empty_store_and_uncertain_when_only_decayed():
    empty = _store()
    p = G.event_answer(empty, NOW, building_id=100)
    assert p.kind == A.UNKNOWN and p.epistemic == A.NO_KNOWLEDGE and p.detail == ""
    assert G.event_answer(None, NOW).kind == A.UNKNOWN

    faded = _store(2)
    f = _told(faded, M.ATTACK_SEEN, actor=9, target=8, building_id=100, hops=1, conf=0.05)
    assert f.effective(NOW) < G.RETRIEVAL_FLOOR
    p = G.event_answer(faded, NOW, building_id=100)
    assert p.kind == A.UNKNOWN and p.epistemic == A.UNCERTAIN and p.detail == "decayed"


def test_event_answer_returns_the_most_salient_retrievable_event():
    st = _store()
    st.remember(M.MET, NOW, actor=5, building_id=100)
    attack, _ = st.remember(M.ATTACK_SEEN, NOW, actor=9, target=8, building_id=100, room_id=0)
    p = G.event_answer(st, NOW, building_id=100)
    assert p.kind == A.ATTACK_HAPPENED and p.event_ref == attack.fact_id
    assert p.subject == 9 and p.target == 8 and p.building_id == 100
    assert p.epistemic == A.DIRECT
    # asked about another building it holds nothing about
    assert G.event_answer(st, NOW, building_id=555).kind == A.UNKNOWN


def test_person_answer_separates_seen_from_heard_of_from_unknown():
    st = _store()
    st.remember(M.MET, NOW, actor=42, building_id=100)
    p = G.person_answer(st, NOW, 42)
    assert p.kind == A.PERSON_SEEN and p.subject == 42 and p.detail == "recent"
    assert p.epistemic in (A.DIRECT, A.EXPERIENCED)

    _told(st, M.THREAT_PERSON, actor=43, building_id=101, hops=1, conf=0.8)
    q = G.person_answer(st, NOW, 43)
    assert q.kind == A.PERSON_HEARD_OF and q.subject == 43
    assert q.source_citizen == 2 and q.epistemic == A.SECOND_HAND

    assert G.person_answer(st, NOW, 44).kind == A.UNKNOWN
    assert G.person_answer(st, NOW, 44).epistemic == A.NO_KNOWLEDGE


def test_person_answer_marks_an_old_sighting_as_earlier():
    st = _store()
    f, _ = st.remember(M.MET, NOW - 3 * 3600.0, actor=42, building_id=100)
    f.last_t = NOW - 3 * 3600.0
    p = G.person_answer(st, NOW, 42)
    assert p.kind == A.PERSON_SEEN and p.detail == "earlier"


def test_safety_answer_is_dangerous_on_a_told_threat_safe_on_first_hand_and_unknown_otherwise():
    # told threat about the place -> dangerous, and never claimed as seen
    told = _store(1)
    _told(told, M.THREAT_PERSON, actor=9, building_id=100, room_id=0, hops=1, conf=0.9)
    p = G.safety_answer(told, derive(told, NOW), NOW, 100, 0)
    assert p.kind == A.PLACE_IS_DANGEROUS and p.building_id == 100
    assert p.epistemic in (A.SECOND_HAND, A.HEARSAY, A.UNCERTAIN)
    assert p.epistemic not in (A.DIRECT, A.EXPERIENCED)
    assert p.confidence > 0.0

    # a first-hand co-presence in the place and no threat -> safe
    safe = _store(2)
    safe.remember(M.WORKED_BESIDE, NOW, actor=5, building_id=100, room_id=0)
    q = G.safety_answer(safe, derive(safe, NOW), NOW, 100, 0)
    assert q.kind == A.PLACE_IS_SAFE and q.epistemic == A.DIRECT and q.building_id == 100

    # nothing at all about the place -> I don't know
    r = G.safety_answer(_store(3), {}, NOW, 100, 0)
    assert r.kind == A.UNKNOWN and r.epistemic == A.NO_KNOWLEDGE
    assert G.safety_answer(safe, derive(safe, NOW), NOW, 777, None).kind == A.UNKNOWN


def test_location_answer_only_places_a_fact_the_speaker_holds():
    st = _store()
    f, _ = st.remember(M.ATTACK_SEEN, NOW, actor=9, target=8, building_id=100, room_id=2)
    p = G.location_answer(st, NOW, f.fact_id)
    assert p.kind == A.EVENT_LOCATION and p.building_id == 100 and p.room_id == 2
    assert p.epistemic == A.DIRECT

    assert G.location_answer(st, NOW, "nope:1").kind == A.UNKNOWN
    assert G.location_answer(st, NOW, None).epistemic == A.NO_KNOWLEDGE
    assert G.location_answer(None, NOW, f.fact_id).kind == A.UNKNOWN

    out, _ = st.remember(M.MET, NOW, actor=6)
    q = G.location_answer(st, NOW, out.fact_id)
    assert q.kind == A.UNKNOWN and q.detail == "outdoors" and q.epistemic == A.UNCERTAIN

    faint = _told(st, M.ATTACK_SEEN, actor=11, target=12, building_id=500, hops=1, conf=0.04)
    assert G.location_answer(st, NOW, faint.fact_id).kind == A.UNKNOWN


def test_a_proposition_round_trips_through_its_dict():
    st = _store()
    f = _told(st, M.THREAT_PERSON, actor=9, building_id=101, hops=1, conf=0.8)
    p = G.proposition_from_fact(f, NOW)
    back = A.Proposition.from_dict(p.to_dict())
    assert back.to_dict() == p.to_dict()

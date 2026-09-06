"""Grounding: what a speaker may assert, and with which epistemic status
(§2, §6, §7, §20, §21).

Everything here takes ONE citizen's memory store (and its derived beliefs)
and nothing else. There is no world handle in this module: a proposition
that the store does not support cannot be produced, whatever the world
knows.

* :func:`retrieve` — bounded ranked retrieval of the facts relevant to a
  query (subject, place, kinds, recency, salience, confidence); at most
  ``TOP_K`` facts, none below the retrieval floor (a decayed fact is not
  remembered in detail).
* :func:`proposition_from_fact` — the structured assertion a fact supports,
  with its epistemic status derived from the fact's source and hops.
* :func:`ground` — the validator: a candidate proposition is accepted only
  if a fact in the speaker's store supports every one of its fields; its
  confidence is capped by that fact's effective confidence and its epistemic
  status is set from the fact (a told fact can never be rendered as "I saw").
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..cognition import memory as M
from ..cognition.beliefs import Belief, danger_of_building, danger_of_room
from . import acts as A

TOP_K = 5
RETRIEVAL_FLOOR = 0.12          # effective confidence below which a fact is not retrievable in detail
WEAK_CONFIDENCE = 0.45          # below this a told fact is rendered as hearsay ("I heard")
RECENT_S = 3600.0

# fact kind -> proposition kind
KIND_OF: Dict[str, str] = {
    M.THREAT_PERSON: A.PERSON_IS_DANGEROUS, M.ATTACK_SEEN: A.ATTACK_HAPPENED, M.ATTACKED_BY: A.ATTACK_HAPPENED,
    M.CORPSE_SEEN: A.PERSON_DEAD, M.DEATH_SEEN: A.PERSON_DEAD, M.PLACE_SAFE: A.PLACE_IS_SAFE,
    M.HELPED_BY: A.HELP_RECEIVED, M.STATION_FAILED: A.STATION_BROKEN,
    M.WORKPLACE_DISRUPTED: A.WORKPLACE_DISRUPTED, M.MET: A.PERSON_SEEN, M.WORKED_BESIDE: A.PERSON_SEEN,
    M.SERVED: A.PERSON_SEEN, M.SERVED_BY: A.PERSON_SEEN, M.FLED_WITH: A.PERSON_SEEN, M.SAW_HELP: A.PERSON_SEEN,
    M.COWORKER_INTERRUPTED: A.PERSON_SEEN, M.HELPED: A.PERSON_SEEN,
}
EVENT_KINDS = (M.ATTACK_SEEN, M.ATTACKED_BY, M.THREAT_PERSON, M.CORPSE_SEEN, M.DEATH_SEEN, M.STATION_FAILED,
               M.WORKPLACE_DISRUPTED, M.HELPED_BY, M.COWORKER_INTERRUPTED)


def epistemic_of(f: M.MemoryFact, now_s: float) -> str:
    eff = f.effective(now_s)
    if f.source == M.PARTICIPANT:
        return A.EXPERIENCED
    if f.source == M.DIRECT:
        return A.DIRECT
    if f.source == M.TOLD:
        if f.hops >= 2 or eff < WEAK_CONFIDENCE:
            return A.HEARSAY
        return A.SECOND_HAND
    return A.UNCERTAIN


def proposition_from_fact(f: M.MemoryFact, now_s: float, kind: Optional[str] = None) -> Proposition:
    """The assertion this fact supports; nothing in it comes from anywhere else."""
    k = kind or KIND_OF.get(f.kind, A.UNKNOWN)
    subject, target = f.actor, f.target
    if f.kind in (M.CORPSE_SEEN, M.DEATH_SEEN):
        subject, target = f.target, None
    if f.kind == M.HELPED_BY:
        subject, target = f.actor, f.target
    return Proposition(kind=k, subject=subject, target=target, building_id=f.building_id, room_id=f.room_id,
                       object_id=f.object_id, event_ref=f.fact_id, epistemic=epistemic_of(f, now_s),
                       source_citizen=f.source_citizen if f.source == M.TOLD else None,
                       origin_witness=f.origin_witness, origin_id=f.origin_id, hops=f.hops,
                       confidence=min(1.0, f.effective(now_s)), t=f.t, detail=f.detail)


Proposition = A.Proposition


def retrieve(store: Optional[M.MemoryStore], now_s: float, *, kinds: Tuple[str, ...] = (),
             subject: Optional[int] = None, building_id: Optional[int] = None, room_id: Optional[int] = None,
             top_k: int = TOP_K, floor: float = RETRIEVAL_FLOOR) -> List[M.MemoryFact]:
    """Bounded ranked retrieval from ONE store. Score = topic match + subject
    match + place match + recency + salience + effective confidence; facts
    under the retrieval floor are not returned (they have decayed past
    recall in detail)."""
    if store is None:
        return []
    scored = []
    for f in store.facts.values():
        eff = f.effective(now_s)
        if eff < floor:
            continue
        s = 0.0
        if kinds:
            if f.kind not in kinds:
                continue
            s += 1.0
        if subject is not None:
            if f.actor == subject or f.target == subject or f.source_citizen == subject:
                s += 1.5
            elif kinds == ():
                continue
        if building_id is not None:
            if f.building_id == building_id:
                s += 1.0
                if room_id is not None and f.room_id == room_id:
                    s += 0.5
            elif kinds == () and subject is None:
                continue
        age = max(0.0, now_s - f.t)
        s += 0.6 * (1.0 if age <= RECENT_S else max(0.0, 1.0 - (age - RECENT_S) / (8.0 * 3600.0)))
        s += 0.8 * f.salience + 0.5 * eff + (0.2 if f.first_hand() else 0.0)
        scored.append((s, f))
    scored.sort(key=lambda sf: (-sf[0], sf[1].fact_id))
    return [f for _, f in scored[:top_k]]


def ground(store: Optional[M.MemoryStore], prop: Proposition, now_s: float) -> Tuple[Optional[Proposition], str]:
    """The validator. Returns (grounded proposition, verdict) where the
    verdict is ``accepted`` / ``downgraded`` / ``rejected:<why>``. A
    proposition is supported only by a fact in the speaker's own store whose
    fields agree with it; the returned proposition's epistemic status and
    confidence come from that fact, never from the candidate."""
    if prop.kind in (A.UNKNOWN, A.NOTHING_HAPPENED):
        return prop, "accepted"
    if store is None:
        return None, "rejected:no_memory"
    wanted = [k for k, v in KIND_OF.items() if v == prop.kind]
    if prop.kind == A.EVENT_LOCATION:
        wanted = list(EVENT_KINDS)
    if prop.kind == A.PERSON_HEARD_OF:
        wanted = list(KIND_OF)
    if not wanted:
        return None, "rejected:unknown_kind"
    best = None
    for f in store.facts.values():
        if f.kind not in wanted:
            continue
        if prop.event_ref and f.fact_id != prop.event_ref:
            continue
        fs, ft = f.actor, f.target
        if f.kind in (M.CORPSE_SEEN, M.DEATH_SEEN):
            fs, ft = f.target, None
        if prop.subject is not None and fs != prop.subject:
            continue
        if prop.target is not None and ft != prop.target:
            continue
        if prop.building_id is not None and f.building_id != prop.building_id:
            continue
        if prop.room_id is not None and f.room_id != prop.room_id:
            continue
        if prop.object_id is not None and f.object_id != prop.object_id:
            continue
        eff = f.effective(now_s)
        if eff < RETRIEVAL_FLOOR:
            continue
        if best is None or (f.first_hand(), eff) > (best.first_hand(), best.effective(now_s)):
            best = f
    if best is None:
        return None, "rejected:unsupported"
    g = proposition_from_fact(best, now_s, kind=prop.kind)
    # the candidate may not claim more than the fact: fill missing place fields from the fact,
    # never the reverse; confidence and epistemic status are the fact's
    verdict = "accepted"
    if prop.epistemic in (A.DIRECT, A.EXPERIENCED) and g.epistemic not in (A.DIRECT, A.EXPERIENCED):
        verdict = "downgraded:source"
    elif prop.confidence > g.confidence + 1e-6:
        verdict = "downgraded:confidence"
    return g, verdict


def safety_answer(store: Optional[M.MemoryStore], beliefs: Dict[str, Belief], now_s: float,
                  building_id: int, room_id: Optional[int]) -> Proposition:
    """"Is this place safe?" from the speaker's beliefs and facts only."""
    bid = int(building_id)
    d_room = danger_of_room(beliefs, bid, room_id) if room_id is not None else 0.0
    d_b = danger_of_building(beliefs, bid)
    danger = max(d_room, d_b)
    facts_here = retrieve(store, now_s, building_id=bid, top_k=8, floor=0.0)
    threat_here = [f for f in facts_here if f.kind in M.THREAT_KINDS]
    if danger >= 0.25 and threat_here:
        best = max(threat_here, key=lambda f: (f.first_hand(), f.effective(now_s)))
        p = proposition_from_fact(best, now_s, kind=A.PLACE_IS_DANGEROUS)
        p.building_id, p.room_id = bid, (best.room_id if best.room_id is not None else room_id)
        p.confidence = round(danger, 3)
        if p.epistemic in (A.SECOND_HAND, A.HEARSAY) and danger < 0.5:
            p.epistemic = A.UNCERTAIN if p.epistemic == A.HEARSAY else p.epistemic
        return p
    safe = [f for f in facts_here if f.kind == M.PLACE_SAFE or f.first_hand()]
    if safe:
        best = max(safe, key=lambda f: f.last_t)
        p = proposition_from_fact(best, now_s, kind=A.PLACE_IS_SAFE)
        p.building_id, p.room_id = bid, room_id
        p.epistemic = A.DIRECT if best.first_hand() else A.BELIEF
        p.confidence = round(max(0.3, 1.0 - danger) * best.effective(now_s), 3)
        if threat_here:
            p.epistemic = A.UNCERTAIN
        return p
    return Proposition(kind=A.UNKNOWN, building_id=bid, room_id=room_id, epistemic=A.NO_KNOWLEDGE)


def person_answer(store: Optional[M.MemoryStore], now_s: float, subject: int) -> Proposition:
    """"Have you seen X?" — the most useful fact about X the speaker holds."""
    facts = retrieve(store, now_s, subject=int(subject), top_k=6)
    seen = [f for f in facts if f.first_hand() and (f.actor == subject or f.target == subject)]
    if seen:
        best = max(seen, key=lambda f: f.last_t)
        p = proposition_from_fact(best, now_s, kind=A.PERSON_SEEN)
        p.subject = int(subject)
        p.t = best.last_t
        p.detail = "recent" if now_s - best.last_t <= RECENT_S else "earlier"
        return p
    heard = [f for f in facts if f.source == M.TOLD and (f.actor == subject or f.target == subject)]
    if heard:
        best = max(heard, key=lambda f: f.effective(now_s))
        p = proposition_from_fact(best, now_s, kind=A.PERSON_HEARD_OF)
        p.subject = int(subject)
        return p
    return Proposition(kind=A.UNKNOWN, subject=int(subject), epistemic=A.NO_KNOWLEDGE)


def event_answer(store: Optional[M.MemoryStore], now_s: float, building_id: Optional[int] = None,
                 subject: Optional[int] = None) -> Proposition:
    """"What happened?" — the most salient retrievable event the speaker holds
    (about a place or a person when asked), else a grounded "nothing"."""
    facts = retrieve(store, now_s, kinds=EVENT_KINDS, building_id=building_id, subject=subject, top_k=TOP_K)
    facts = [f for f in facts if building_id is None or f.building_id == building_id]
    if subject is not None:
        facts = [f for f in facts if f.actor == subject or f.target == subject]
    if not facts:
        if store is not None and any(f.effective(now_s) < RETRIEVAL_FLOOR and f.kind in EVENT_KINDS
                                     for f in store.facts.values()):
            return Proposition(kind=A.UNKNOWN, building_id=building_id, subject=subject, epistemic=A.UNCERTAIN,
                               detail="decayed")
        return Proposition(kind=A.UNKNOWN, building_id=building_id, subject=subject, epistemic=A.NO_KNOWLEDGE)
    best = max(facts, key=lambda f: (f.salience * f.effective(now_s), f.first_hand(), f.fact_id))
    return proposition_from_fact(best, now_s)


def location_answer(store: Optional[M.MemoryStore], now_s: float, event_ref: Optional[str]) -> Proposition:
    """"Where was that?" — the place of a fact the speaker itself asserted."""
    f = store.facts.get(event_ref) if (store is not None and event_ref) else None
    if f is None or f.effective(now_s) < RETRIEVAL_FLOOR:
        return Proposition(kind=A.UNKNOWN, event_ref=event_ref, epistemic=A.NO_KNOWLEDGE)
    if f.building_id is None:
        return Proposition(kind=A.UNKNOWN, event_ref=event_ref, epistemic=A.UNCERTAIN, detail="outdoors")
    p = proposition_from_fact(f, now_s, kind=A.EVENT_LOCATION)
    return p

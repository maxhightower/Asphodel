"""Beliefs derived from memory (§8, §16).

A belief is the owner's CURRENT estimate, derived from the evidence in the
memory store: one direct memory, two rumours and one contradicting
observation combine into a single confidence. Beliefs are therefore never
stored as truth; they are recomputed from facts (cached per citizen and
invalidated when the store changes), and they can be wrong.

Evidence weighting:

* source: first-hand evidence counts fully; hearsay counts by the trust the
  owner places in the teller (captured at reception in the fact's
  confidence) and loses a further share per hop;
* time: every fact's confidence decays with its salience half-life;
* contradiction: a later PLACE_SAFE observation of the same place halves the
  danger evidence recorded before it (direct evidence beats older hearsay).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .memory import (ATTACK_SEEN, ATTACKED_BY, CORPSE_SEEN, DEATH_SEEN, FALSE_WARNING, HELPED_BY,
                     MemoryFact, MemoryStore, PLACE_SAFE, THREAT_KINDS, THREAT_PERSON, TOLD)

HOP_DISCOUNT = 0.75          # hearsay loses this share of confidence per hop beyond the first
DANGER_ACT = 0.45            # a danger belief at/above this drives behaviour


@dataclass
class Belief:
    key: str                  # "danger:person:<cid>" | "danger:room:<bid>:<rid>" | "danger:building:<bid>"
    value: float              # confidence 0..1
    evidence: List[str] = field(default_factory=list)     # fact ids
    first_hand: bool = False
    source_citizens: List[int] = field(default_factory=list)
    subject: Optional[int] = None
    building_id: Optional[int] = None
    room_id: Optional[int] = None
    last_t: float = 0.0

    def to_dict(self) -> dict:
        return {"key": self.key, "value": round(self.value, 3), "evidence": list(self.evidence),
                "first_hand": self.first_hand, "source_citizens": list(self.source_citizens),
                "subject": self.subject, "building_id": self.building_id, "room_id": self.room_id,
                "last_t": self.last_t}


def _weight(f: MemoryFact, now_s: float) -> float:
    w = f.effective(now_s)
    if f.source == TOLD:
        w *= HOP_DISCOUNT ** max(0, f.hops - 1)
    return w


def _combine(ws: List[float]) -> float:
    """Noisy-OR: independent pieces of evidence accumulate, never exceed 1."""
    p = 1.0
    for w in ws:
        p *= (1.0 - max(0.0, min(1.0, w)))
    return 1.0 - p


def derive(store: MemoryStore, now_s: float) -> Dict[str, Belief]:
    """All current beliefs of one citizen."""
    out: Dict[str, Belief] = {}
    threats = [f for f in store.facts.values() if f.kind in THREAT_KINDS]
    safes = [f for f in store.facts.values() if f.kind == PLACE_SAFE]

    def safe_after(f: MemoryFact) -> bool:
        return any(s.building_id == f.building_id
                   and (s.room_id is None or f.room_id is None or s.room_id == f.room_id)
                   and s.t > f.t for s in safes)

    # people
    by_person: Dict[int, List[MemoryFact]] = {}
    for f in threats:
        if f.actor is not None and f.kind in (THREAT_PERSON, ATTACK_SEEN, ATTACKED_BY):
            by_person.setdefault(int(f.actor), []).append(f)
    for cid, fs in sorted(by_person.items()):
        ws = [_weight(f, now_s) for f in fs]
        b = Belief(f"danger:person:{cid}", _combine(ws), [f.fact_id for f in sorted(fs, key=lambda x: x.fact_id)],
                   any(f.first_hand() for f in fs),
                   sorted({int(f.source_citizen) for f in fs if f.source_citizen is not None}),
                   subject=cid, last_t=max(f.last_t for f in fs))
        out[b.key] = b
    # places (room-level where known, plus the building as a whole)
    by_room: Dict[Tuple[int, Optional[int]], List[MemoryFact]] = {}
    for f in threats:
        if f.building_id is None or f.building_id < 0:
            continue
        by_room.setdefault((int(f.building_id), f.room_id), []).append(f)
    for (bid, rid), fs in sorted(by_room.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None else kv[0][1])):
        ws = [_weight(f, now_s) * (0.5 if safe_after(f) else 1.0) for f in fs]
        key = f"danger:room:{bid}:{rid}" if rid is not None else f"danger:building:{bid}"
        b = Belief(key, _combine(ws), [f.fact_id for f in sorted(fs, key=lambda x: x.fact_id)],
                   any(f.first_hand() for f in fs),
                   sorted({int(f.source_citizen) for f in fs if f.source_citizen is not None}),
                   subject=None, building_id=bid, room_id=rid, last_t=max(f.last_t for f in fs))
        out[b.key] = b
    # building-level aggregate over its rooms (a room danger makes the building somewhat dangerous)
    agg: Dict[int, List[float]] = {}
    for b in list(out.values()):
        if b.room_id is not None:
            agg.setdefault(b.building_id, []).append(b.value * 0.9)
    for bid, vs in sorted(agg.items()):
        key = f"danger:building:{bid}"
        if key in out:
            out[key].value = _combine([out[key].value] + vs)
        else:
            out[key] = Belief(key, _combine(vs), [], False, [], building_id=bid,
                              last_t=max(x.last_t for x in out.values() if x.building_id == bid))
    return out


def danger_of_room(beliefs: Dict[str, Belief], bid: int, rid: int) -> float:
    b = beliefs.get(f"danger:room:{bid}:{rid}")
    return b.value if b else 0.0


def danger_of_building(beliefs: Dict[str, Belief], bid: int) -> float:
    b = beliefs.get(f"danger:building:{bid}")
    return b.value if b else 0.0


def danger_of_person(beliefs: Dict[str, Belief], cid: int) -> float:
    b = beliefs.get(f"danger:person:{cid}")
    return b.value if b else 0.0

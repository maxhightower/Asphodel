"""Structured episodic memory (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §6, §7).

A :class:`MemoryFact` is a structured fact one citizen holds about the world:
who did what to whom, where, when, and *how the owner knows it* (direct
observation, participation, or told by someone — with the original witness
and the hop depth preserved). Dialogue may later verbalize a fact; the fact
itself is never prose.

A :class:`MemoryStore` is bounded and deterministic:

* repeated equivalent facts (same kind / actor / target / place) MERGE into
  one fact whose ``count`` and ``last_t`` are reinforced, so seeing the same
  coworker every morning is one growing memory, not four hundred;
* confidence DECAYS with a salience-dependent half-life (a major event —
  attack, death, rescue — is remembered for days, a trivial one for hours);
* when the store is over its cap, the least *effective* facts are forgotten
  first; durable facts (salience >= DURABLE_SALIENCE) are dropped last.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Tuple

# --- fact kinds (the structured vocabulary) ---------------------------------
# social / work
WORKED_BESIDE = "WORKED_BESIDE"          # actor = other citizen (aggregated co-presence)
MET = "MET"                              # actor = other citizen (co-presence outside work)
SERVED_BY = "SERVED_BY"                  # owner was served by actor
SERVED = "SERVED"                        # owner served target
HELPED_BY = "HELPED_BY"                  # actor helped owner (target = owner)
HELPED = "HELPED"                        # owner helped target
SAW_HELP = "SAW_HELP"                    # owner saw actor help target
STATION_FAILED = "STATION_FAILED"        # object broke (actor = displaced worker)
COWORKER_INTERRUPTED = "COWORKER_INTERRUPTED"   # actor left work abruptly
WORKPLACE_DISRUPTED = "WORKPLACE_DISRUPTED"
WARNED_BY = "WARNED_BY"                  # actor warned owner (a social act, distinct from the fact)
FALSE_WARNING = "FALSE_WARNING"          # actor's warning contradicted by direct observation
# threat
THREAT_PERSON = "THREAT_PERSON"          # actor is dangerous (undead) — seen at place
ATTACK_SEEN = "ATTACK_SEEN"              # actor attacked target at place
ATTACKED_BY = "ATTACKED_BY"              # owner was attacked by actor
CORPSE_SEEN = "CORPSE_SEEN"              # target's corpse at place
DEATH_SEEN = "DEATH_SEEN"                # target died at place
PLACE_SAFE = "PLACE_SAFE"                # owner was at place and saw no threat (contradicting evidence)
FLED_WITH = "FLED_WITH"                  # actor fled the same threat
ABANDONED_BY = "ABANDONED_BY"            # actor left owner in danger
REFUSED_BY = "REFUSED_BY"                # actor refused owner's request for help

KINDS = (WORKED_BESIDE, MET, SERVED_BY, SERVED, HELPED_BY, HELPED, SAW_HELP, STATION_FAILED,
         COWORKER_INTERRUPTED, WORKPLACE_DISRUPTED, WARNED_BY, FALSE_WARNING, THREAT_PERSON,
         ATTACK_SEEN, ATTACKED_BY, CORPSE_SEEN, DEATH_SEEN, PLACE_SAFE, FLED_WITH, ABANDONED_BY, REFUSED_BY)

# --- sources ----------------------------------------------------------------
DIRECT = "direct"            # saw it happen
PARTICIPANT = "participant"  # was part of it
TOLD = "told"                # heard it from another citizen

# baseline salience per kind (0..1); durable facts outlive the cap and decay slowly
SALIENCE: Dict[str, float] = {
    WORKED_BESIDE: 0.15, MET: 0.10, SERVED_BY: 0.25, SERVED: 0.20, HELPED_BY: 0.85, HELPED: 0.70,
    SAW_HELP: 0.45, STATION_FAILED: 0.40, COWORKER_INTERRUPTED: 0.45, WORKPLACE_DISRUPTED: 0.60,
    WARNED_BY: 0.50, FALSE_WARNING: 0.70, THREAT_PERSON: 0.95, ATTACK_SEEN: 1.0, ATTACKED_BY: 1.0,
    CORPSE_SEEN: 0.90, DEATH_SEEN: 1.0, PLACE_SAFE: 0.35, FLED_WITH: 0.75, ABANDONED_BY: 0.85,
    REFUSED_BY: 0.55,
}
VALENCE: Dict[str, float] = {
    HELPED_BY: 0.8, HELPED: 0.4, SAW_HELP: 0.3, SERVED_BY: 0.1, SERVED: 0.05, WORKED_BESIDE: 0.05,
    MET: 0.02, WARNED_BY: 0.3, FALSE_WARNING: -0.5, THREAT_PERSON: -0.9, ATTACK_SEEN: -0.9,
    ATTACKED_BY: -1.0, CORPSE_SEEN: -0.7, DEATH_SEEN: -0.9, FLED_WITH: 0.3, ABANDONED_BY: -0.8,
    STATION_FAILED: -0.2, COWORKER_INTERRUPTED: -0.2, WORKPLACE_DISRUPTED: -0.5, PLACE_SAFE: 0.1,
    REFUSED_BY: -0.5,
}
DURABLE_SALIENCE = 0.80
CAPACITY = 64                  # episodic facts per citizen
FORGET_BELOW = 0.05            # effective confidence under which a non-durable fact is dropped
THREAT_KINDS = (THREAT_PERSON, ATTACK_SEEN, ATTACKED_BY, CORPSE_SEEN, DEATH_SEEN)


def half_life_s(salience: float) -> float:
    """Decay half-life: 2 h for trivial facts, ~3 days for the most salient."""
    s = max(0.0, min(1.0, salience))
    return 7200.0 + (3.0 * 86400.0 - 7200.0) * (s ** 2)


@dataclass
class MemoryFact:
    fact_id: str                         # "<owner>:<n>" — stable within the owner
    owner: int
    kind: str
    actor: Optional[int] = None          # citizen the fact is about (the subject)
    target: Optional[int] = None         # second citizen, if any
    building_id: Optional[int] = None
    room_id: Optional[int] = None
    object_id: Optional[str] = None
    t: float = 0.0                       # when it happened (world seconds)
    source: str = DIRECT
    source_citizen: Optional[int] = None  # who told the owner (TOLD)
    origin_witness: Optional[int] = None  # who originally observed it
    origin_id: str = ""                  # the witness's fact id (information lineage)
    hops: int = 0                        # 0 = first-hand
    confidence: float = 1.0
    salience: float = 0.5
    valence: float = 0.0
    count: int = 1                       # reinforcements (merged equivalents)
    last_t: float = 0.0                  # last reinforcement
    detail: str = ""

    # -- keys ----------------------------------------------------------------
    def merge_key(self) -> tuple:
        return (self.kind, self.actor, self.target, self.building_id, self.room_id)

    def effective(self, now_s: float) -> float:
        """Confidence after decay since the last reinforcement."""
        age = max(0.0, now_s - self.last_t)
        return self.confidence * (0.5 ** (age / half_life_s(self.salience)))

    def durable(self) -> bool:
        return self.salience >= DURABLE_SALIENCE

    def first_hand(self) -> bool:
        return self.source in (DIRECT, PARTICIPANT)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryFact":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


class MemoryStore:
    """One citizen's bounded episodic memory."""

    def __init__(self, owner: int, capacity: int = CAPACITY):
        self.owner = int(owner)
        self.capacity = int(capacity)
        self.facts: Dict[str, MemoryFact] = {}
        self._by_key: Dict[tuple, str] = {}
        self.seq = 0
        self.forgotten = 0

    def __len__(self) -> int:
        return len(self.facts)

    # -- write -----------------------------------------------------------------
    def remember(self, kind: str, now_s: float, *, actor=None, target=None, building_id=None,
                 room_id=None, object_id=None, source: str = DIRECT, source_citizen=None,
                 origin_witness=None, origin_id: str = "", hops: int = 0,
                 confidence: float = 1.0, salience: Optional[float] = None,
                 detail: str = "", t: Optional[float] = None) -> Tuple[MemoryFact, bool]:
        """Store or reinforce. Returns (fact, created)."""
        sal = SALIENCE.get(kind, 0.5) if salience is None else float(salience)
        key = (kind, actor, target, building_id, room_id)
        fid = self._by_key.get(key)
        if fid is not None and fid in self.facts:
            f = self.facts[fid]
            f.count += 1
            f.last_t = float(now_s)
            f.t = float(now_s if t is None else t)
            # a first-hand account supersedes hearsay; confidence never drops on reinforcement
            if source != TOLD and f.source == TOLD:
                f.source, f.source_citizen, f.hops = source, None, 0
                f.origin_witness, f.origin_id = self.owner, f.fact_id
            f.confidence = max(f.confidence, float(confidence))
            if object_id is not None:
                f.object_id = object_id
            if detail:
                f.detail = detail
            return f, False
        self.seq += 1
        fid = f"{self.owner}:{self.seq}"
        f = MemoryFact(fid, self.owner, kind, actor=actor, target=target, building_id=building_id,
                       room_id=room_id, object_id=object_id, t=float(now_s if t is None else t),
                       source=source, source_citizen=source_citizen,
                       origin_witness=(self.owner if source != TOLD else origin_witness),
                       origin_id=(fid if source != TOLD else origin_id), hops=int(hops),
                       confidence=float(confidence), salience=sal, valence=VALENCE.get(kind, 0.0),
                       count=1, last_t=float(now_s), detail=detail)
        self.facts[fid] = f
        self._by_key[key] = fid
        return f, True

    def forget(self, fact_id: str) -> None:
        f = self.facts.pop(fact_id, None)
        if f is not None:
            self._by_key.pop(f.merge_key(), None)
            self.forgotten += 1

    def consolidate(self, now_s: float) -> List[str]:
        """Apply forgetting: drop decayed non-durable facts and, over capacity,
        the least effective ones (durable facts last). Returns dropped ids."""
        dropped: List[str] = []
        for fid, f in sorted(self.facts.items()):
            if not f.durable() and f.effective(now_s) < FORGET_BELOW:
                dropped.append(fid)
        for fid in dropped:
            self.forget(fid)
        if len(self.facts) > self.capacity:
            order = sorted(self.facts.values(),
                           key=lambda f: (f.durable(), f.effective(now_s) * (0.5 + f.salience), f.fact_id))
            for f in order[: len(self.facts) - self.capacity]:
                dropped.append(f.fact_id)
                self.forget(f.fact_id)
        return dropped

    # -- read ------------------------------------------------------------------
    def find(self, kind: Optional[str] = None, actor=None, target=None, building_id=None,
             room_id=None) -> List[MemoryFact]:
        out = []
        for f in self.facts.values():
            if kind is not None and f.kind != kind:
                continue
            if actor is not None and f.actor != actor:
                continue
            if target is not None and f.target != target:
                continue
            if building_id is not None and f.building_id != building_id:
                continue
            if room_id is not None and f.room_id != room_id:
                continue
            out.append(f)
        return sorted(out, key=lambda f: f.fact_id)

    def about(self, cid: int) -> List[MemoryFact]:
        return sorted((f for f in self.facts.values() if f.actor == cid or f.target == cid),
                      key=lambda f: f.fact_id)

    def salient(self, now_s: float, n: int = 8) -> List[MemoryFact]:
        return sorted(self.facts.values(),
                      key=lambda f: (-(f.effective(now_s) * f.salience), f.fact_id))[:n]

    def known_people(self) -> List[int]:
        s = set()
        for f in self.facts.values():
            if f.actor is not None and f.actor != self.owner:
                s.add(int(f.actor))
            if f.target is not None and f.target != self.owner:
                s.add(int(f.target))
            if f.source_citizen is not None:
                s.add(int(f.source_citizen))
        return sorted(s)

    # -- persistence -------------------------------------------------------------
    def to_state(self) -> dict:
        return {"owner": self.owner, "capacity": self.capacity, "seq": self.seq, "forgotten": self.forgotten,
                "facts": [self.facts[k].to_dict() for k in sorted(self.facts)]}

    @classmethod
    def from_state(cls, st: dict) -> "MemoryStore":
        m = cls(int(st["owner"]), int(st.get("capacity", CAPACITY)))
        m.seq = int(st.get("seq", 0))
        m.forgotten = int(st.get("forgotten", 0))
        for d in st.get("facts") or []:
            f = MemoryFact.from_dict(d)
            m.facts[f.fact_id] = f
            m._by_key[f.merge_key()] = f.fact_id
        return m

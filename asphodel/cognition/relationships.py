"""Bounded persistent relationships (§9, §10).

One :class:`Relationship` is the OWNER's view of another citizen along six
dimensions in [0, 1]: familiarity, trust, affinity, fear, hostility and
obligation. Views are directional (A's view of B is not B's of A).

State changes only through :func:`apply` with the deterministic update
table ``RULES``: an event kind maps to bounded deltas. Lightweight priors are
allowed for household and workplace (§10) and are the only non-experience
source; certification shows relationships moving because of events that
actually happened.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Tuple

DIMS = ("familiarity", "trust", "affinity", "fear", "hostility", "obligation")


@dataclass
class Relationship:
    owner: int
    other: int
    familiarity: float = 0.0
    trust: float = 0.3        # a stranger is neither trusted nor distrusted
    affinity: float = 0.0
    fear: float = 0.0
    hostility: float = 0.0
    obligation: float = 0.0
    interactions: int = 0
    last_t: float = 0.0
    origin: str = ""          # "household" | "workplace" | "" (experience only)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in DIMS:
            d[k] = round(d[k], 4)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Relationship":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})

    def summary(self) -> str:
        best = max(DIMS, key=lambda k: getattr(self, k))
        return f"{best}={getattr(self, best):.2f}"


# event -> (dimension, delta). Deltas saturate: x += delta * (1 - x) for
# positive, x += delta * x for negative — bounded and order-stable.
RULES: Dict[str, Tuple[Tuple[str, float], ...]] = {
    "worked_beside":     (("familiarity", 0.06),),
    "met":               (("familiarity", 0.03),),
    "served_by":         (("familiarity", 0.05), ("affinity", 0.03)),
    "served":            (("familiarity", 0.04),),
    "helped_by":         (("familiarity", 0.10), ("trust", 0.25), ("affinity", 0.30), ("obligation", 0.50)),
    "helped":            (("familiarity", 0.08), ("affinity", 0.12)),
    "saw_help":          (("trust", 0.08), ("affinity", 0.06)),
    "reciprocated":      (("obligation", -0.60),),      # owner discharged an obligation to other
    "warned_by":         (("familiarity", 0.08), ("trust", 0.12), ("affinity", 0.08)),
    "warning_confirmed": (("trust", 0.20),),
    "false_warning":     (("trust", -0.35), ("affinity", -0.10)),
    "attacked_by":       (("fear", 0.90), ("hostility", 0.80), ("trust", -0.90), ("affinity", -0.80)),
    "threat_seen":       (("fear", 0.80), ("hostility", 0.50), ("trust", -0.80)),
    "attack_seen":       (("fear", 0.85), ("hostility", 0.70), ("trust", -0.85)),
    "fled_with":         (("familiarity", 0.12), ("affinity", 0.15), ("trust", 0.10)),
    "abandoned_by":      (("trust", -0.40), ("affinity", -0.30)),
    "told_threat":       (("fear", 0.35),),          # about the threat person, via hearsay
}

PRIORS: Dict[str, Dict[str, float]] = {
    "household": {"familiarity": 0.80, "trust": 0.70, "affinity": 0.60},
    "workplace": {"familiarity": 0.30, "trust": 0.40, "affinity": 0.15},
}


def _sat(x: float, delta: float) -> float:
    if delta >= 0:
        x = x + delta * (1.0 - x)
    else:
        x = x + delta * x
    return max(0.0, min(1.0, x))


class RelationshipGraph:
    def __init__(self):
        self.rels: Dict[Tuple[int, int], Relationship] = {}

    def get(self, owner: int, other: int, create: bool = False) -> Optional[Relationship]:
        k = (int(owner), int(other))
        r = self.rels.get(k)
        if r is None and create:
            r = Relationship(k[0], k[1])
            self.rels[k] = r
        return r

    def of(self, owner: int) -> List[Relationship]:
        return sorted((r for (o, _), r in self.rels.items() if o == int(owner)), key=lambda r: r.other)

    def prior(self, owner: int, other: int, origin: str, now_s: float) -> Relationship:
        r = self.get(owner, other, create=True)
        if not r.origin:
            r.origin = origin
            for k, v in PRIORS[origin].items():
                setattr(r, k, max(getattr(r, k), v))
            r.last_t = now_s
        return r

    def apply(self, owner: int, other: int, rule: str, now_s: float,
              scale: float = 1.0) -> List[Tuple[str, float, float]]:
        """Apply one rule; returns [(dim, old, new)] for the trace."""
        if int(owner) == int(other):
            return []
        r = self.get(owner, other, create=True)
        changes = []
        for dim, delta in RULES[rule]:
            old = getattr(r, dim)
            new = _sat(old, delta * float(scale))
            if abs(new - old) > 1e-9:
                setattr(r, dim, new)
                changes.append((dim, round(old, 4), round(new, 4)))
        r.interactions += 1
        r.last_t = float(now_s)
        return changes

    def to_state(self) -> dict:
        return {"rels": [self.rels[k].to_dict() for k in sorted(self.rels)]}

    @classmethod
    def from_state(cls, st: dict) -> "RelationshipGraph":
        g = cls()
        for d in st.get("rels") or []:
            r = Relationship.from_dict(d)
            g.rels[(r.owner, r.other)] = r
        return g

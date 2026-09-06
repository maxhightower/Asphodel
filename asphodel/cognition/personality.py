"""Bounded deterministic personality (§18): five traits in [0, 1] that bias
decisions and produce diversity. Nothing else — no taxonomy, no biography.
A trait vector is a pure function of (world seed, citizen id) and is never
stored: it cannot drift, be regenerated differently, or diverge on load.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from ..world_source.detrand import hash64

TRAITS = ("sociability", "helpfulness", "risk_tolerance", "loyalty", "suspicion")


@dataclass(frozen=True)
class Personality:
    sociability: float
    helpfulness: float
    risk_tolerance: float
    loyalty: float
    suspicion: float

    def to_dict(self) -> dict:
        return {k: round(v, 3) for k, v in asdict(self).items()}


def _u(seed: int, cid: int, trait: str) -> float:
    # a triangular-ish draw (mean of two uniforms) keeps most citizens moderate
    a = (hash64(int(seed), int(cid), "trait", trait, 0) % 10_000) / 10_000.0
    b = (hash64(int(seed), int(cid), "trait", trait, 1) % 10_000) / 10_000.0
    return round(0.5 * (a + b), 3)


def personality_for(seed: int, cid: int) -> Personality:
    return Personality(*[_u(seed, cid, t) for t in TRAITS])

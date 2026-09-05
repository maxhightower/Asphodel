"""Mobility obstructions: the clean seam from physical events to semantic mobility.

AS-NAV-0 §5.4 + §10. A physical event (a wreck settling, a barricade, a flood,
a fire) does NOT reach into road scripts. It produces a :class:`MobilityObstruction`
— a declarative description of *what* is blocked and *how much* — which the graph
applies to segment ``dynamic_state``. Removing/towing the obstruction restores the
capacity. This keeps collision consequences out of any one car script (§10 DON'T).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence, Set, Tuple

from .segments import Mode

Vec2 = Tuple[float, float]


class ObstructionKind(Enum):
    WRECK = "wreck"
    BARRICADE = "barricade"
    CONSTRUCTION = "construction"
    CLOSURE = "closure"
    FLOOD = "flood"
    FIRE = "fire"
    CROWD = "crowd"
    DISABLED_SIGNAL = "disabled_signal"
    BLOCKED_BRIDGE = "blocked_bridge"
    TUNNEL_OBSTRUCTION = "tunnel_obstruction"


# How much of a segment's capacity each kind removes at severity 1.0, and which
# modes it forbids outright. Data-driven so new catastrophes are new rows.
_KIND_EFFECT = {
    ObstructionKind.WRECK: (0.5, set()),
    ObstructionKind.BARRICADE: (1.0, {Mode.CAR, Mode.HEAVY}),
    ObstructionKind.CONSTRUCTION: (0.6, set()),
    ObstructionKind.CLOSURE: (1.0, {Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    ObstructionKind.FLOOD: (0.9, {Mode.CAR, Mode.HEAVY, Mode.FOOT, Mode.BICYCLE}),
    ObstructionKind.FIRE: (1.0, {Mode.CAR, Mode.HEAVY, Mode.EMERGENCY, Mode.FOOT, Mode.BICYCLE}),
    ObstructionKind.CROWD: (0.4, {Mode.CAR, Mode.HEAVY}),
    ObstructionKind.DISABLED_SIGNAL: (0.3, set()),
    ObstructionKind.BLOCKED_BRIDGE: (1.0, {Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    ObstructionKind.TUNNEL_OBSTRUCTION: (1.0, {Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
}


@dataclass
class MobilityObstruction:
    """A physical event's effect on mobility, independent of any renderer (§10)."""

    id: str
    kind: ObstructionKind
    affected_segment: str
    location: Optional[Vec2] = None
    severity: float = 1.0                      # 0..1 scales blocked_fraction
    modes_affected: Optional[Set[Mode]] = None  # override the kind default
    source_entity: Optional[str] = None         # e.g. a VehicleInstance id

    def blocked_fraction(self) -> float:
        base, _ = _KIND_EFFECT[self.kind]
        return max(0.0, min(1.0, base * self.severity))

    def closed_modes(self) -> Set[Mode]:
        if self.modes_affected is not None:
            return set(self.modes_affected)
        _, modes = _KIND_EFFECT[self.kind]
        # Only fully-blocking severities forbid the modes; a light wreck slows.
        return set(modes) if self.blocked_fraction() >= 0.95 else set()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "affected_segment": self.affected_segment,
            "location": list(self.location) if self.location else None,
            "severity": self.severity,
            "blocked_fraction": self.blocked_fraction(),
            "closed_modes": sorted(m.value for m in self.closed_modes()),
            "source_entity": self.source_entity,
        }

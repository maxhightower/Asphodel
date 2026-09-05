"""LOD / streaming state machine with identity preservation (§12).

The same semantic person or vehicle exists across every fidelity boundary; only
its *representation* changes, never its identity or its semantic payload (goal,
route, progress). This module decides the LOD band from distance-to-focus with
hysteresis (so entities near a boundary do not flicker) and provides an
EntityLODState whose transitions are guaranteed to preserve id + payload — the
§17.4 invariants (far->near preserves id, near->far preserves goal and route).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional


class LODBand(IntEnum):
    """Generic fidelity bands, nearest (0) to most abstract (3)."""

    PHYSICAL = 0          # full physics body
    NEAR_SIMPLIFIED = 1   # nearby but cheap
    ROUTE_SIMULATED = 2   # progressing along a route, no physics
    ABSTRACT = 3          # a statistic


class CitizenLOD(Enum):
    ABSTRACT = "abstract"
    ROUTE_SIMULATED = "route_simulated"
    NEAR_SIMPLIFIED = "near_simplified"
    PHYSICAL = "physical"
    INTERIOR_PHYSICAL = "interior_physical"


_BAND_TO_CITIZEN = {
    LODBand.PHYSICAL: CitizenLOD.PHYSICAL,
    LODBand.NEAR_SIMPLIFIED: CitizenLOD.NEAR_SIMPLIFIED,
    LODBand.ROUTE_SIMULATED: CitizenLOD.ROUTE_SIMULATED,
    LODBand.ABSTRACT: CitizenLOD.ABSTRACT,
}


def band_to_citizen_lod(band: LODBand, interior: bool = False) -> CitizenLOD:
    if band == LODBand.PHYSICAL and interior:
        return CitizenLOD.INTERIOR_PHYSICAL
    return _BAND_TO_CITIZEN[band]


@dataclass
class LODController:
    """Distance-banded LOD with promote/demote hysteresis.

    ``*_radius`` are the promote thresholds (entering a nearer band). Demotion to a
    farther band requires crossing the threshold plus ``hysteresis`` metres, so an
    entity loitering on a boundary does not oscillate. Deterministic in distance.
    """

    physical_radius: float = 120.0
    near_radius: float = 400.0
    route_radius: float = 3000.0
    hysteresis: float = 40.0

    def band_for(self, distance: float,
                 current: Optional[LODBand] = None) -> LODBand:
        # Target band purely by distance.
        if distance <= self.physical_radius:
            target = LODBand.PHYSICAL
        elif distance <= self.near_radius:
            target = LODBand.NEAR_SIMPLIFIED
        elif distance <= self.route_radius:
            target = LODBand.ROUTE_SIMULATED
        else:
            target = LODBand.ABSTRACT
        if current is None:
            return target
        # Hysteresis: only demote (go to a higher band) if clearly past the edge.
        if target > current:
            edges = {
                LODBand.PHYSICAL: self.physical_radius,
                LODBand.NEAR_SIMPLIFIED: self.near_radius,
                LODBand.ROUTE_SIMULATED: self.route_radius,
            }
            edge = edges.get(current)
            if edge is not None and distance <= edge + self.hysteresis:
                return current
        return target


@dataclass
class EntityLODState:
    """Identity + payload that survive every LOD transition (§12)."""

    entity_id: str
    band: LODBand = LODBand.ABSTRACT
    payload: dict = field(default_factory=dict)  # goal, route, progress, ...
    transitions: int = 0

    def transition(self, new_band: LODBand) -> "EntityLODState":
        """Change fidelity band. Identity and payload are preserved by contract."""
        if new_band != self.band:
            self.band = new_band
            self.transitions += 1
        return self

    def update_from_focus(self, distance: float,
                          controller: LODController) -> LODBand:
        self.transition(controller.band_for(distance, self.band))
        return self.band

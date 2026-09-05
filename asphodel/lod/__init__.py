"""LOD / streaming, identity preservation, and safe materialization (§12)."""
from __future__ import annotations

from .entity import (
    CitizenLOD,
    EntityLODState,
    LODBand,
    LODController,
    band_to_citizen_lod,
)
from .materialize import (
    MaterializationRequest,
    MaterializationResult,
    resolve_materialization,
)

__all__ = [
    "LODBand",
    "CitizenLOD",
    "band_to_citizen_lod",
    "LODController",
    "EntityLODState",
    "MaterializationRequest",
    "MaterializationResult",
    "resolve_materialization",
]

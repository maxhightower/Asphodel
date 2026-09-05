"""Regional geospatial terrain authority (AS-REGION-0).

Two extents (detailed city inside a wide region), an offline elevation-provider
abstraction with archetype-driven geographic identity, chunked quadtree LOD
terrain with crack-hiding skirts and distance-driven physical fidelity, coarse
land cover, and bake artifacts for offline runtime.
"""
from __future__ import annotations

from .elevation import (
    ARCHETYPES,
    CachedDEMProvider,
    ElevationProvider,
    FallbackDEMProvider,
    SyntheticElevationProvider,
    TerrainArchetype,
    USGS3DEPProvider,
    archetype_for,
)
from .terrain import (
    ChunkPhysicalState,
    RegionalExtent,
    TerrainChunk,
    bake_heightmap,
    build_quadtree,
    chunk_mesh,
    terrain_stats,
)
from . import landcover

__all__ = [
    "ARCHETYPES",
    "TerrainArchetype",
    "archetype_for",
    "ElevationProvider",
    "SyntheticElevationProvider",
    "CachedDEMProvider",
    "USGS3DEPProvider",
    "FallbackDEMProvider",
    "RegionalExtent",
    "TerrainChunk",
    "ChunkPhysicalState",
    "build_quadtree",
    "chunk_mesh",
    "bake_heightmap",
    "terrain_stats",
    "landcover",
]

"""Coarse regional land-cover classification (AS-REGION-0, §3.3).

Not per-tree detail — the goal is geographic identity at horizon distance: water,
coastline, forest masses, plains/desert, and bare rock/snow on high mountains.
Classification is derived from elevation, local slope, and the archetype's
forest/aridity hints, with seed-stable noise breaking up the boundaries so forest
masses read as patches rather than a hard contour.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from . import noise
from .elevation import SyntheticElevationProvider, ElevationProvider, TerrainArchetype

WATER = 0
BEACH = 1
PLAINS = 2
DESERT = 3
FOREST = 4
ROCK = 5
SNOW = 6

LEGEND = {
    WATER: "water",
    BEACH: "beach",
    PLAINS: "plains",
    DESERT: "desert",
    FOREST: "forest",
    ROCK: "rock",
    SNOW: "snow",
}


def classify_grid(provider: ElevationProvider, arch: TerrainArchetype,
                  x: np.ndarray, z: np.ndarray, seed: int = 0) -> np.ndarray:
    """Return integer land-cover codes for a grid of projected coords."""
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    elev = np.asarray(provider.sample(x, z), dtype=np.float64)

    # Local slope via small finite differences (metres per metre).
    d = 40.0
    ex = (np.asarray(provider.sample(x + d, z)) - np.asarray(provider.sample(x - d, z))) / (2 * d)
    ez = (np.asarray(provider.sample(x, z + d)) - np.asarray(provider.sample(x, z - d))) / (2 * d)
    slope = np.hypot(ex, ez)

    out = np.full(elev.shape, PLAINS if not arch.arid else DESERT, dtype=np.int64)

    sea = arch.sea_level
    if sea is not None:
        out = np.where(elev <= sea, WATER, out)
        out = np.where((elev > sea) & (elev <= sea + 3.0), BEACH, out)

    # Forest masses: patchy, favouring moderate elevations and gentler slopes.
    fscale = 1.0 / 4000.0
    forest_n = noise.fbm(x * fscale, z * fscale, seed=seed + 313, octaves=4)
    is_landish = out != WATER
    forest_ok = (forest_n > (1.0 - arch.forest_fraction)) & (slope < 0.35) & is_landish
    out = np.where(forest_ok, FOREST, out)

    # High mountains: bare rock then snow above treeline-ish bands.
    if arch.mountain_relief > 0:
        base = arch.base_elevation
        rock_line = base + 0.55 * arch.mountain_relief
        snow_line = base + 0.80 * arch.mountain_relief
        out = np.where((elev >= rock_line) & (elev < snow_line), ROCK, out)
        out = np.where(elev >= snow_line, SNOW, out)
        # Steep faces are rock regardless of band.
        out = np.where((slope > 0.6) & (elev > base + 100), ROCK, out)

    return out


def coverage_fractions(codes: np.ndarray) -> dict:
    """Fraction of each land-cover class in a classified grid (for gating/QA)."""
    total = codes.size
    return {LEGEND[k]: float((codes == k).sum()) / total for k in LEGEND}

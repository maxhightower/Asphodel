"""Pure geometry helpers: projection, polygon area, block & polyline layout.

No network, no dependencies beyond the stdlib + a passed-in RNG, so every
function here is trivially unit-testable.
"""
from __future__ import annotations

import math
from typing import Iterable

# Meters per degree near the equator; lon is additionally scaled by cos(lat).
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0


def project(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Equirectangular projection of (lat, lon) to local meters about (lat0, lon0).

    Returns (x, z) where x is east, z is north. Distortion is under ~0.5% for
    typical city extents (radius < 50 km) — fine for relative city geometry.
    """
    x = (lon - lon0) * M_PER_DEG_LON * math.cos(math.radians(lat0))
    z = (lat - lat0) * M_PER_DEG_LAT
    return (x, z)


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Absolute area of a polygon via the shoelace formula.

    Units are the square of the input units (project first for square meters).
    Returns 0.0 for degenerate (<3 point) rings.
    """
    n = len(points)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def place_blocks(
    density: float,
    center_xy: tuple[float, float],
    cell_extent: tuple[float, float],
    rng,
    max_blocks: int = 8,
    min_height: float = 4.0,
    max_height: float = 40.0,
) -> list[dict]:
    """Representative low-poly blocks for one cell, count & height proportional to density.

    `density` in [0, 1]; positions are jittered within 80% of the cell to leave
    visible streets. `rng` is a `random.Random` for deterministic placement.
    Returns dicts: {"xy": [x, z], "height": float, "footprint": float}.
    """
    n = int(round(max(0.0, min(1.0, density)) * max_blocks))
    cx, cz = center_xy
    w, h = cell_extent
    blocks = []
    for _ in range(n):
        bx = cx + (rng.random() - 0.5) * w * 0.8
        bz = cz + (rng.random() - 0.5) * h * 0.8
        # Multiplier in [0.3, 1.0] keeps height varied but never above max_height.
        height = min_height + density * (max_height - min_height) * (0.3 + 0.7 * rng.random())
        footprint = 4.0 + 6.0 * rng.random()
        blocks.append({"xy": [bx, bz], "height": round(height, 3), "footprint": round(footprint, 3)})
    return blocks


def project_polyline(
    latlon_points: Iterable[tuple[float, float]], lat0: float, lon0: float
) -> list[list[float]]:
    """Project a sequence of (lat, lon) into a list of [x, z] pairs."""
    return [list(project(lat, lon, lat0, lon0)) for lat, lon in latlon_points]

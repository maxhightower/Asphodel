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

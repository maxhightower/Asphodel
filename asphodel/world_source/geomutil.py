"""Shared geometry helpers for the exterior compiler (shapely-backed).

shapely/numpy are compile-time dependencies of the world_source pipeline
only; the runtime game and simulation stay free of them.
"""
from __future__ import annotations

import math

from shapely.geometry import (  # noqa: F401  (re-exported for stages)
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import unary_union  # noqa: F401


def ring_edges(poly: Polygon):
    """Yield ((x0,z0),(x1,z1)) for each exterior-ring edge (closed)."""
    coords = list(poly.exterior.coords)
    for i in range(len(coords) - 1):
        yield coords[i], coords[i + 1]


def edge_point(p0, p1, t: float):
    return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)


def edge_outward_normal(poly: Polygon, p0, p1):
    """Unit normal of edge p0->p1 pointing away from the polygon interior."""
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dz) or 1.0
    nx, nz = -dz / ln, dx / ln
    mx, mz = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    probe = Point(mx + nx * 0.5, mz + nz * 0.5)
    if poly.contains(probe):
        nx, nz = -nx, -nz
    return nx, nz


def polyline_length(pts) -> float:
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )


def point_along_polyline(pts, dist: float):
    """(x, z, heading_deg) at arc distance along a polyline (clamped)."""
    if dist <= 0:
        d0 = math.degrees(math.atan2(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
        return (pts[0][0], pts[0][1], d0)
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if acc + seg >= dist and seg > 0:
            t = (dist - acc) / seg
            x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
            z = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
            hd = math.degrees(
                math.atan2(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            )
            return (x, z, hd)
        acc += seg
    p0, p1 = pts[-2], pts[-1]
    hd = math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1]))
    return (p1[0], p1[1], hd)


def sanitize_polygon(rings) -> Polygon | None:
    """Rings [[(x,z),...], ...] -> valid shapely Polygon (or None)."""
    if not rings or len(rings[0]) < 3:
        return None
    try:
        poly = Polygon(rings[0], rings[1:] if len(rings) > 1 else None)
    except Exception:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    if isinstance(poly, MultiPolygon):
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly if poly.area > 0 else None


def largest_rectangle_side(poly: Polygon):
    """Approximate dominant orientation (degrees) via min rotated rect."""
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    best, ang = 0.0, 0.0
    for i in range(len(coords) - 1):
        dx = coords[i + 1][0] - coords[i][0]
        dz = coords[i + 1][1] - coords[i][1]
        ln = math.hypot(dx, dz)
        if ln > best:
            best = ln
            ang = math.degrees(math.atan2(dx, dz))
    return ang

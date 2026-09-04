"""Chunked quadtree terrain with LOD, skirts, and physical-fidelity promotion.

AS-REGION-0, §3.2–§3.4. The regional world is a quadtree over a large square
extent. Leaf chunks subdivide by distance to the focus (player/camera): near the
focus chunks are small and dense (LOD0), far away they are large and cheap
(distant horizon). Every leaf meshes at a FIXED vertex resolution, so triangle
count per chunk is bounded regardless of area, and total runtime memory is
bounded by the number of leaves the split rule admits.

Crack avoidance: neighbouring chunks of different depth create T-junctions. We
hang a **skirt** (a vertical wall dropping ``skirt_depth`` below each border
vertex) around every chunk, hiding any seam gap without needing to stitch
resolutions. Chunk corner vertices are sampled at exact world positions, so
shared corners between any two chunks match to the bit.

Physical fidelity is distance-driven (§3.4): near terrain has collision and
navigation; distant terrain is render-only. Fidelity is promoted/demoted as the
focus moves — the mesh (semantic geometry) never changes when this happens.

Deterministic: identical (provider, extent, focus) → identical chunk set and
identical mesh bytes (§17.1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np

from .elevation import ElevationProvider

Vec2 = Tuple[float, float]


@dataclass(frozen=True)
class RegionalExtent:
    """The two-tier extent from §3: a bounded detailed city inside a wide region.

    Radii are in metres. ``horizon`` is where render-only terrain fades into the
    atmosphere. ``center`` is the projected-metre origin (usually (0, 0)).
    """

    detailed_city_radius: float = 3000.0
    regional_radius: float = 60000.0
    horizon_radius: float = 150000.0
    center: Vec2 = (0.0, 0.0)

    @classmethod
    def from_km(cls, detailed_km=3.0, regional_km=60.0, horizon_km=150.0,
                center: Vec2 = (0.0, 0.0)) -> "RegionalExtent":
        return cls(detailed_km * 1000.0, regional_km * 1000.0,
                   horizon_km * 1000.0, center)

    def root_square(self) -> Tuple[float, float, float]:
        """SW corner (x0, z0) and side length covering the horizon extent."""
        side = 2.0 * self.horizon_radius
        return (self.center[0] - self.horizon_radius,
                self.center[1] - self.horizon_radius, side)


@dataclass(frozen=True)
class TerrainChunk:
    """One quadtree leaf: a square patch of terrain at a given depth."""

    x0: float
    z0: float
    size: float
    depth: int
    max_depth: int

    @property
    def center(self) -> Vec2:
        return (self.x0 + self.size / 2.0, self.z0 + self.size / 2.0)

    @property
    def lod(self) -> int:
        """0 = finest (nearest). Higher = coarser/more distant."""
        return self.max_depth - self.depth

    def key(self) -> str:
        """Stable id for independent loading/caching (§3.2)."""
        return f"c{self.depth}_{int(round(self.x0))}_{int(round(self.z0))}"

    def distance_to(self, focus: Vec2) -> float:
        """Distance from focus to the nearest point of the chunk (0 if inside)."""
        dx = max(self.x0 - focus[0], 0.0, focus[0] - (self.x0 + self.size))
        dz = max(self.z0 - focus[1], 0.0, focus[1] - (self.z0 + self.size))
        return math.hypot(dx, dz)

    def physical_state(self, focus: Vec2, collision_radius: float,
                       nav_radius: float) -> "ChunkPhysicalState":
        """Distance-driven fidelity (§3.4). Rendered always; collision/nav near."""
        d = self.distance_to(focus)
        return ChunkPhysicalState(
            rendered=True,
            collision=d <= collision_radius,
            navigation=d <= nav_radius,
            distance=d,
        )


@dataclass(frozen=True)
class ChunkPhysicalState:
    rendered: bool
    collision: bool
    navigation: bool
    distance: float


def build_quadtree(extent: RegionalExtent, focus: Vec2, max_depth: int = 6,
                   lod_ratio: float = 1.6) -> List[TerrainChunk]:
    """Split the region into leaves, fine near the focus, coarse far away.

    A chunk subdivides while ``size > lod_ratio * distance_to_focus`` and depth is
    below ``max_depth``. This is the classic quadtree screen-space-error rule; it
    is deterministic in the focus, so the leaf set is reproducible.
    """
    x0, z0, side = extent.root_square()
    leaves: List[TerrainChunk] = []

    def rec(cx0: float, cz0: float, size: float, depth: int) -> None:
        chunk = TerrainChunk(cx0, cz0, size, depth, max_depth)
        d = chunk.distance_to(focus)
        if depth < max_depth and size > lod_ratio * max(d, 1.0):
            h = size / 2.0
            rec(cx0, cz0, h, depth + 1)
            rec(cx0 + h, cz0, h, depth + 1)
            rec(cx0, cz0 + h, h, depth + 1)
            rec(cx0 + h, cz0 + h, h, depth + 1)
        else:
            leaves.append(chunk)

    rec(x0, z0, side, 0)
    # Sort for a stable, reproducible ordering independent of recursion order.
    leaves.sort(key=lambda c: (c.depth, c.x0, c.z0))
    return leaves


def chunk_mesh(chunk: TerrainChunk, provider: ElevationProvider, res: int = 16,
               skirt_depth: float = 30.0, origin_elevation: float = 0.0) -> dict:
    """Mesh one chunk at fixed resolution with a crack-hiding skirt.

    Returns a JSON-friendly dict: ``vertices`` (list of [x, y, z], y up, elevation
    relative to ``origin_elevation``), ``indices`` (flat triangle list), plus
    counts and the height range. Triangle count is bounded: ``2*res*res`` for the
    surface plus ``4*res*2`` for the skirt walls — independent of chunk area.
    """
    n = res + 1
    xs = chunk.x0 + (np.arange(n) / res) * chunk.size
    zs = chunk.z0 + (np.arange(n) / res) * chunk.size
    gx, gz = np.meshgrid(xs, zs)  # shape (n, n)
    gy = np.asarray(provider.sample(gx, gz), dtype=np.float64) - origin_elevation

    verts: List[List[float]] = []
    for iz in range(n):
        for ix in range(n):
            verts.append([float(gx[iz, ix]), float(gy[iz, ix]), float(gz[iz, ix])])

    indices: List[int] = []
    for iz in range(res):
        for ix in range(res):
            a = iz * n + ix
            b = a + 1
            c = a + n
            d = c + 1
            # Two triangles, CCW when viewed from above (+y).
            indices += [a, c, b, b, c, d]

    # Skirt: drop a copy of every border vertex by skirt_depth and wall it in.
    surface_verts = len(verts)
    y_min = float(gy.min())
    border: List[int] = []
    for ix in range(n):
        border.append(ix)                       # north edge (iz=0)
    for iz in range(1, n):
        border.append(iz * n + (n - 1))         # east edge
    for ix in range(n - 2, -1, -1):
        border.append((n - 1) * n + ix)         # south edge
    for iz in range(n - 2, 0, -1):
        border.append(iz * n)                   # west edge
    skirt_base = surface_verts
    for vi in border:
        vx, vy, vz = verts[vi]
        verts.append([vx, vy - skirt_depth, vz])
    m = len(border)
    for i in range(m):
        top_a = border[i]
        top_b = border[(i + 1) % m]
        bot_a = skirt_base + i
        bot_b = skirt_base + (i + 1) % m
        indices += [top_a, bot_a, top_b, top_b, bot_a, bot_b]

    return {
        "key": chunk.key(),
        "lod": chunk.lod,
        "depth": chunk.depth,
        "origin": [chunk.x0, chunk.z0],
        "size": chunk.size,
        "res": res,
        "vertices": verts,
        "indices": indices,
        "triangle_count": len(indices) // 3,
        "surface_vertex_count": surface_verts,
        "skirt_depth": skirt_depth,
        "y_min": y_min,
        "y_max": float(gy.max()),
    }


def bake_heightmap(provider: ElevationProvider, extent: RegionalExtent,
                   step_m: float = 500.0) -> dict:
    """Sample a regular heightmap over the regional extent (a bake artifact).

    This is what a compiled bundle ships so the game runs offline via
    :class:`CachedDEMProvider`. Returns bounds, step, shape, and the row-major
    height grid (list of lists), plus provenance.
    """
    x0, z0, side = extent.root_square()
    n = int(math.ceil(side / step_m)) + 1
    xs = x0 + np.arange(n) * step_m
    zs = z0 + np.arange(n) * step_m
    gx, gz = np.meshgrid(xs, zs)
    h = np.asarray(provider.sample(gx, gz), dtype=np.float64)
    return {
        "x0": x0,
        "z0": z0,
        "step_m": step_m,
        "shape": [int(h.shape[0]), int(h.shape[1])],
        "heights": [[round(float(v), 2) for v in row] for row in h],
        "provenance": provider.provenance(),
    }


def terrain_stats(provider: ElevationProvider, extent: RegionalExtent,
                  samples: int = 96) -> dict:
    """Relief statistics over the regional extent — the flat/mountain gate (§3.5).

    Returns min/max/mean elevation, relief span, and the max local gradient
    (metres of rise per metre horizontally), which is what distinguishes a
    genuinely mountainous region from a flat one.
    """
    x0, z0, side = extent.root_square()
    xs = x0 + np.linspace(0, side, samples)
    zs = z0 + np.linspace(0, side, samples)
    gx, gz = np.meshgrid(xs, zs)
    h = np.asarray(provider.sample(gx, gz), dtype=np.float64)
    step = side / (samples - 1)
    dzdx = np.gradient(h, step, axis=1)
    dzdz = np.gradient(h, step, axis=0)
    slope = np.hypot(dzdx, dzdz)
    return {
        "min_elevation": float(h.min()),
        "max_elevation": float(h.max()),
        "mean_elevation": float(h.mean()),
        "relief_span": float(h.max() - h.min()),
        "max_gradient": float(slope.max()),
        "mean_gradient": float(slope.mean()),
    }

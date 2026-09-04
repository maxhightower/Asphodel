"""Synthesize street-aligned building footprints for bundles baked before
buildings.json existed (or baked offline, where Overpass is unreachable).

Real OSM footprints are always preferred — `python -m asphodel.osm_city` bakes
them when it has network access. This module is the fallback: it reads a
bundle's REAL road polylines + zone densities and lays plausible lots along
both sides of every street, so the world still visibly follows the city's
actual OSM street geometry. Output is deterministic for a given bundle.

CLI:  python -m asphodel.osm_city.synth godot/bundles/<city>
"""
from __future__ import annotations

import json
import math
import os
import random
import sys

# Half-width (m) of the carriageway per highway class; buildings set back from it.
ROAD_HALF_WIDTH = {
    "motorway": 12.0, "trunk": 10.0, "primary": 7.5, "secondary": 6.0,
    "tertiary": 4.5, "unclassified": 3.5, "residential": 3.0,
    "living_street": 3.0, "service": 2.5, "pedestrian": 2.5,
}
_DEFAULT_HALF_WIDTH = 4.0

# (kind, levels_range, width_range_m, depth_range_m) menus by local density.
_DENSE_MENU = [
    ("shop", (1, 2), (10.0, 18.0), (12.0, 20.0)),
    ("commercial", (1, 3), (12.0, 24.0), (14.0, 24.0)),
    ("office", (2, 5), (14.0, 24.0), (14.0, 26.0)),
    ("apartments", (2, 4), (14.0, 26.0), (12.0, 20.0)),
    ("restaurant", (1, 1), (9.0, 14.0), (10.0, 16.0)),
]
_SPARSE_MENU = [
    ("house", (1, 2), (9.0, 14.0), (8.0, 12.0)),
    ("house", (1, 1), (8.0, 12.0), (7.0, 11.0)),
    ("garage", (1, 1), (5.0, 7.0), (5.0, 7.0)),
    ("shop", (1, 1), (9.0, 14.0), (10.0, 14.0)),
]
_LEVEL_HEIGHT_M = 3.2


class _Grid:
    """Coarse spatial hash for overlap + road-clearance checks."""

    def __init__(self, cell: float = 30.0):
        self.cell = cell
        self.cells: dict[tuple[int, int], list] = {}

    def _key(self, x: float, z: float) -> tuple[int, int]:
        return (int(math.floor(x / self.cell)), int(math.floor(z / self.cell)))

    def add(self, x: float, z: float, payload) -> None:
        self.cells.setdefault(self._key(x, z), []).append((x, z, payload))

    def near(self, x: float, z: float):
        kx, kz = self._key(x, z)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                yield from self.cells.get((kx + dx, kz + dz), ())


def _seg_dist(px, pz, ax, az, bx, bz) -> float:
    vx, vz = bx - ax, bz - az
    L2 = vx * vx + vz * vz
    if L2 <= 1e-9:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, ((px - ax) * vx + (pz - az) * vz) / L2))
    return math.hypot(px - (ax + t * vx), pz - (az + t * vz))


def _zone_lookup(zones: list[dict]):
    """density at (x, z) via the zone grid (0.0 outside)."""
    def density(x: float, z: float) -> float:
        for zn in zones:
            cx, cz = zn["center_xy"]
            ex, ez = zn["extent"]
            if abs(x - cx) <= ex * 0.5 and abs(z - cz) <= ez * 0.5:
                return float(zn.get("density", 0.0))
        return 0.0
    return density


def synthesize(roads: dict, zones: list[dict], seed: int = 0,
               max_buildings: int = 5000) -> list[dict]:
    """Street-aligned synthetic footprints from real road polylines."""
    rng = random.Random(seed ^ 0x5F00D)
    density_at = _zone_lookup(zones)

    road_grid = _Grid(cell=60.0)
    for pl in roads.get("polylines", []):
        pts = pl.get("points", [])
        hw = ROAD_HALF_WIDTH.get(pl.get("class", ""), _DEFAULT_HALF_WIDTH)
        for i in range(len(pts) - 1):
            (ax, az), (bx, bz) = pts[i], pts[i + 1]
            # register the segment at both ends and midpoint so near() finds it
            for qx, qz in ((ax, az), ((ax + bx) / 2, (az + bz) / 2), (bx, bz)):
                road_grid.add(qx, qz, (ax, az, bx, bz, hw))

    placed = _Grid(cell=30.0)
    out: list[dict] = []

    for pl in roads.get("polylines", []):
        pts = pl.get("points", [])
        hw = ROAD_HALF_WIDTH.get(pl.get("class", ""), _DEFAULT_HALF_WIDTH)
        for i in range(len(pts) - 1):
            (ax, az), (bx, bz) = pts[i], pts[i + 1]
            seg_len = math.hypot(bx - ax, bz - az)
            if seg_len < 8.0:
                continue
            ux, uz = (bx - ax) / seg_len, (bz - az) / seg_len   # along road
            nx, nz = -uz, ux                                    # road normal
            step = 24.0
            d = step * rng.random() * 0.5 + 8.0
            while d < seg_len - 8.0:
                for side in (1.0, -1.0):
                    px, pz = ax + ux * d, az + uz * d
                    dens = density_at(px, pz)
                    # empty countryside stays empty; town cores fill in
                    if rng.random() > 0.10 + 0.90 * (dens ** 0.6):
                        continue
                    menu = _DENSE_MENU if dens > 0.45 else _SPARSE_MENU
                    kind, lv_rng, w_rng, d_rng = menu[rng.randrange(len(menu))]
                    w = rng.uniform(*w_rng)
                    depth = rng.uniform(*d_rng)
                    setback = hw + rng.uniform(4.0, 9.0)
                    cx = px + nx * side * (setback + depth * 0.5)
                    cz = pz + nz * side * (setback + depth * 0.5)
                    # keep clear of every nearby road, not just this one
                    clear = min((_seg_dist(cx, cz, *seg[:4]) - seg[4]
                                 for seg in (p for _, _, p in road_grid.near(cx, cz))),
                                default=1e9)
                    if clear < depth * 0.5 + 2.0:
                        continue
                    # no overlap with an already-placed neighbour
                    r = math.hypot(w, depth) * 0.5
                    if any(math.hypot(cx - ox, cz - oz) < r + orad + 1.5
                           for ox, oz, orad in
                           ((x, z, p) for x, z, p in placed.near(cx, cz))):
                        continue
                    levels = rng.randint(*lv_rng)
                    hx, hz = ux * w * 0.5, uz * w * 0.5       # half along road
                    dxn, dzn = nx * side * depth * 0.5, nz * side * depth * 0.5
                    ring = [
                        (cx - hx - dxn, cz - hz - dzn),
                        (cx + hx - dxn, cz + hz - dzn),
                        (cx + hx + dxn, cz + hz + dzn),
                        (cx - hx + dxn, cz - hz + dzn),
                    ]
                    out.append({
                        "footprint": [[round(x, 2), round(z, 2)] for x, z in ring],
                        "center_xy": [round(cx, 2), round(cz, 2)],
                        "levels": levels,
                        "height": round(levels * _LEVEL_HEIGHT_M
                                        * rng.uniform(0.9, 1.15), 2),
                        "kind": kind,
                        "area_m2": round(w * depth, 1),
                        "synthetic": True,
                    })
                    placed.add(cx, cz, r)
                d += step
    if len(out) > max_buildings:
        out = out[:max_buildings]
    return out


def synth_bundle_dir(bundle_dir: str, max_buildings: int = 5000) -> int:
    """Write buildings.json for `bundle_dir`; returns the building count."""
    with open(os.path.join(bundle_dir, "meta.json")) as f:
        meta = json.load(f)
    with open(os.path.join(bundle_dir, "roads.json")) as f:
        roads = json.load(f)
    with open(os.path.join(bundle_dir, "zones.json")) as f:
        zones = json.load(f)
    buildings = synthesize(roads, zones, seed=int(meta.get("seed", 0)),
                           max_buildings=max_buildings)
    from .bundle import _write_json
    _write_json(os.path.join(bundle_dir, "buildings.json"), buildings)
    return len(buildings)


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m asphodel.osm_city.synth <bundle_dir> [...]",
              file=sys.stderr)
        return 2
    for d in args:
        n = synth_bundle_dir(d)
        print(f"{d}: wrote {n} synthetic street-aligned buildings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

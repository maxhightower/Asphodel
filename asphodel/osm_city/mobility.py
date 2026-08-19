"""Derive a generic weighted zone-mobility graph from a city's real roads.

The epidemic engine consumes a generic sparse edge list ``[[a, b, weight], ...]``
over zone indices (see ``GraphParams.mobility_edges``); it knows nothing about
OSM. This module is the OSM-side derivation that produces that list from the
city's road network, so two zones are linked (and how strongly) by the roads
that actually cross between them rather than by mere grid adjacency.

Everything here works in the bundle's local **metre** frame using the zone grid
geometry, so it runs identically at build time (freshly projected roads) and as
an offline re-bake from a committed bundle (roads already in metres).

Weighting model (generic, documented, not overfit):

* each road class has a capacity weight, motorway > trunk > primary > secondary
  > tertiary > residential (a motorway link moves far more people than a lane);
* walking a road, every time it crosses from zone A into zone B contributes that
  class's capacity to the A-B edge;
* parallel/again-crossing roads between the same pair *sum*, so more and bigger
  roads make a stronger edge;
* an optional small ``local_floor`` links grid-adjacent populated cells so the
  epidemic doesn't fragment where only minor (un-fetched) streets connect two
  neighbourhoods -- explicit and separately tested.
"""
from __future__ import annotations

import math

# Generic per-class capacity weights. Only the four major classes are fetched by
# the Overpass query today; the rest are here for completeness/future use.
ROAD_CAPACITY = {
    "motorway": 8.0, "trunk": 6.0, "primary": 4.0, "secondary": 2.5,
    "tertiary": 1.5, "residential": 1.0,
}
DEFAULT_CAPACITY = 1.0


def road_capacity(road_class: str) -> float:
    return ROAD_CAPACITY.get(road_class, DEFAULT_CAPACITY)


class GridIndex:
    """Maps a metre point to a zone id using the tessellation's grid geometry."""

    def __init__(self, rows: int, cols: int, x_min: float, z_min: float,
                 cell_w: float, cell_h: float):
        self.rows = rows
        self.cols = cols
        self.x_min = x_min
        self.z_min = z_min
        self.cell_w = cell_w
        self.cell_h = cell_h

    @classmethod
    def from_zones(cls, zones: list[dict], rows: int, cols: int) -> "GridIndex":
        # Uniform cells (tessellate guarantees this): read the cell size off any
        # zone and the origin off the min corner.
        e = zones[0]["extent"]
        cw, ch = float(e[0]), float(e[1])
        x_min = min(float(z["center_xy"][0]) - float(z["extent"][0]) * 0.5 for z in zones)
        z_min = min(float(z["center_xy"][1]) - float(z["extent"][1]) * 0.5 for z in zones)
        return cls(rows, cols, x_min, z_min, cw, ch)

    def zone_of(self, x: float, z: float) -> int:
        col = min(self.cols - 1, max(0, int((x - self.x_min) / self.cell_w)))
        row = min(self.rows - 1, max(0, int((z - self.z_min) / self.cell_h)))
        return row * self.cols + col

    def grid_adjacent_pairs(self):
        """Orthogonally-adjacent (4-neighbour) zone-id pairs, unordered."""
        for r in range(self.rows):
            for c in range(self.cols):
                i = r * self.cols + c
                if c + 1 < self.cols:
                    yield (i, i + 1)
                if r + 1 < self.rows:
                    yield (i, i + self.cols)


def _step_len(grid: GridIndex) -> float:
    return max(1.0, min(grid.cell_w, grid.cell_h) * 0.5)


def derive_road_edges(grid: GridIndex, road_polylines: list[dict]) -> dict:
    """Pure road-crossing derivation: {(a, b): weight} for a<b, roads only.

    Each polyline's segments are finely subsampled so a road that spans several
    cells produces an edge for *each* real transition, not just its endpoints.
    """
    step = _step_len(grid)
    acc: dict[tuple[int, int], float] = {}
    for pl in road_polylines:
        cap = road_capacity(pl.get("class", ""))
        pts = pl.get("points", [])
        prev_zone = None
        for k in range(len(pts) - 1):
            x0, z0 = float(pts[k][0]), float(pts[k][1])
            x1, z1 = float(pts[k + 1][0]), float(pts[k + 1][1])
            seg = math.hypot(x1 - x0, z1 - z0)
            n = max(1, int(math.ceil(seg / step)))
            for s in range(n + 1):
                t = s / n
                zone = grid.zone_of(x0 + (x1 - x0) * t, z0 + (z1 - z0) * t)
                if prev_zone is not None and zone != prev_zone:
                    pair = (prev_zone, zone) if prev_zone < zone else (zone, prev_zone)
                    acc[pair] = acc.get(pair, 0.0) + cap
                prev_zone = zone
    return acc


def build_mobility_edges(grid: GridIndex, road_edges: dict,
                         local_floor: float = 0.0,
                         populated: list[bool] | None = None,
                         ndigits: int = 5) -> list[list]:
    """Combine road edges with an optional local-diffusion floor into an edge list.

    ``local_floor`` (metres-agnostic weight) is added to every grid-adjacent pair
    of *populated* cells so the graph stays connected where only minor streets
    (not fetched) link two neighbourhoods; road-connected pairs keep their much
    larger road weight on top. ``populated`` (per-zone bool) gates the floor so
    empty cells are never turned into fake conduits. Deterministic + sorted.
    """
    edges: dict[tuple[int, int], float] = dict(road_edges)
    if local_floor > 0.0:
        for (a, b) in grid.grid_adjacent_pairs():
            if populated is not None and not (populated[a] and populated[b]):
                continue
            edges[(a, b)] = edges.get((a, b), 0.0) + local_floor
    return [[a, b, round(w, ndigits)] for (a, b), w in sorted(edges.items())]


def derive_zone_mobility(zones: list[dict], road_polylines: list[dict],
                         rows: int, cols: int, local_floor: float = 0.0,
                         populated: list[bool] | None = None) -> list[list]:
    """Convenience: grid geometry from zones -> road edges -> final edge list."""
    grid = GridIndex.from_zones(zones, rows, cols)
    road_edges = derive_road_edges(grid, road_polylines)
    if populated is None:
        populated = [float(z.get("population", 0.0)) > 0.0 for z in zones]
    return build_mobility_edges(grid, road_edges, local_floor=local_floor,
                                populated=populated)


def mobility_stats(edges: list[list], n_zones: int) -> dict:
    """Summary statistics for reporting (degree, components, strongest edge)."""
    adj: dict[int, set] = {i: set() for i in range(n_zones)}
    strongest = (None, None, 0.0)
    for a, b, w in edges:
        a, b, w = int(a), int(b), float(w)
        adj[a].add(b)
        adj[b].add(a)
        if w > strongest[2]:
            strongest = (a, b, w)
    seen = set()
    components = 0
    for start in range(n_zones):
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
    degrees = [len(adj[i]) for i in range(n_zones)]
    connected = [i for i in range(n_zones) if degrees[i] > 0]
    return {
        "n_zones": n_zones,
        "n_edges": len(edges),
        "avg_degree": (sum(degrees) / n_zones) if n_zones else 0.0,
        "avg_degree_connected": (sum(degrees[i] for i in connected) / len(connected))
                                 if connected else 0.0,
        "connected_components": components,
        "isolated_zones": n_zones - len(connected),
        "strongest_edge": {"a": strongest[0], "b": strongest[1], "weight": strongest[2]},
        "max_weight": strongest[2],
    }

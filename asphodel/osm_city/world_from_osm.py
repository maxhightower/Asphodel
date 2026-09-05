"""Build a canonical :class:`~asphodel.world.StreetMap` from *parsed OSM data*.

This is the seam that makes citizen generation share ONE authoritative world
with the playable geometry. The OSM pipeline (``pipeline.build_bundle``) already
parses a real city into building footprints + major-road polylines and projects
them into a local metre frame about the bbox centre. This module turns those
exact same inputs into the ``StreetMap`` / ``Building`` types the citizen spawner
consumes -- so a citizen's home/work are *real buildings of the selected city*,
in the *same coordinate frame* as the rendered blocks and roads, rather than an
abstract profile shared across every city.

``asphodel.world.load_osm`` is the live-network GIS seam (osmnx/shapely); this is
the offline, dependency-light equivalent fed by the already-fetched Overpass
geometry the bundle is built from. Both terminate in the identical canonical
``StreetMap``, so the citizen model and ``resolve_collapse_situation`` are
unchanged.
"""

# CONVERGENCE NOTE: street_map_from_bundle (zones-blocks scatter) is the LEGACY
# citizen-bake path for a bundle that has no buildings.json. Every committed
# bundle now has one, so the canonical path is world_from_compiled
# (footprint identity == building_id). Do not extend the blocks path.
from __future__ import annotations

import math

import numpy as np

from ..world import (
    Building, StreetMap, category_from_osm_tags, structure_from_osm_tags,
    RESIDENTIAL, COMMERCIAL, MEDICAL, EDUCATION, CIVIC, INDUSTRIAL, TRANSIT,
)
from . import geometry as geo


# Compass sectors give buildings a readable, position-derived "neighborhood"
# without OSM admin boundaries -- and because they come from real footprint
# positions they differ from city to city.
_SECTORS = [
    ["South-West", "South", "South-East"],
    ["West", "Old Town", "East"],
    ["North-West", "North", "North-East"],
]


def _sector(cx: float, cz: float, bbox_m: tuple[float, float, float, float]) -> str:
    xmin, zmin, xmax, zmax = bbox_m
    fx = 0.0 if xmax == xmin else (cx - xmin) / (xmax - xmin)
    fz = 0.0 if zmax == zmin else (cz - zmin) / (zmax - zmin)
    col = min(2, max(0, int(fx * 3)))
    row = min(2, max(0, int(fz * 3)))
    return _SECTORS[row][col]


def _road_class_to_tags(cls: str) -> dict:
    """A major-road ``highway=`` class -> the tag dict structure_from_osm_tags reads."""
    return {"highway": cls}


def _build_street_graph(bbox, roads):
    """Project road polylines into a metre street graph (nodes, edges, attrs).

    Nodes are deduplicated by a ~1 m grid snap so shared intersections connect.
    Each consecutive pair of vertices in a polyline becomes an edge carrying its
    Euclidean length and a road-structure attribute derived from the OSM class.
    """
    south, west, north, east = bbox
    lat0, lon0 = (south + north) / 2.0, (west + east) / 2.0

    nodes: dict[int, tuple[float, float]] = {}
    node_of: dict[tuple[int, int], int] = {}
    edges: list[tuple[int, int, float]] = []
    edge_attrs: dict[tuple[int, int], dict] = {}

    def node_id(x: float, z: float) -> int:
        key = (int(round(x)), int(round(z)))
        nid = node_of.get(key)
        if nid is None:
            nid = len(nodes)
            node_of[key] = nid
            nodes[nid] = (float(x), float(z))
        return nid

    for r in roads:
        pts = [geo.project(lat, lon, lat0, lon0) for (lat, lon) in r["points"]]
        structure = structure_from_osm_tags(_road_class_to_tags(r.get("class", "")))
        prev = None
        for (x, z) in pts:
            nid = node_id(x, z)
            if prev is not None and prev != nid:
                a, b = prev, nid
                length = math.hypot(nodes[a][0] - nodes[b][0],
                                    nodes[a][1] - nodes[b][1])
                if length > 0:
                    edges.append((a, b, length))
                    edge_attrs[(a, b) if a <= b else (b, a)] = {"structure": structure}
            prev = nid
    return nodes, edges, edge_attrs


def street_map_from_osm(bbox, buildings, roads, source: str = "osm") -> StreetMap:
    """Assemble a canonical ``StreetMap`` from parsed OSM buildings + roads.

    ``bbox`` is (south, west, north, east); ``buildings`` and ``roads`` are the
    dicts produced by ``overpass.parse_osm`` (buildings carry ``ring``/``levels``
    and, when present, ``tags`` or a precomputed ``category``; roads carry
    ``class``/``points``). Coordinates are projected into the *same* metre frame
    the bundle uses (equirectangular about the bbox centre).
    """
    south, west, north, east = bbox
    lat0, lon0 = (south + north) / 2.0, (west + east) / 2.0

    nodes, edges, edge_attrs = _build_street_graph(bbox, roads)

    # Building footprints -> categorised Buildings in the metre frame.
    built: list[Building] = []
    xs_all: list[float] = []
    zs_all: list[float] = []
    tmp: list[tuple[list[tuple[float, float]], float, tuple[float, float], int, str]] = []
    for b in buildings:
        ring_m = [geo.project(lat, lon, lat0, lon0) for (lat, lon) in b["ring"]]
        if len(ring_m) < 3:
            continue
        area = geo.polygon_area(ring_m)
        if area <= 0:
            continue
        cx = sum(p[0] for p in ring_m) / len(ring_m)
        cz = sum(p[1] for p in ring_m) / len(ring_m)
        levels = max(1, int(b.get("levels", 1)))
        cat = b.get("category") or category_from_osm_tags(b.get("tags", {})) or RESIDENTIAL
        tmp.append((ring_m, area, (cx, cz), levels, cat))
        xs_all += [p[0] for p in ring_m]
        zs_all += [p[1] for p in ring_m]

    if xs_all:
        bbox_m = (min(xs_all), min(zs_all), max(xs_all), max(zs_all))
    else:
        bbox_m = (0.0, 0.0, 1.0, 1.0)

    # A street graph is required so buildings can pin to a nearest node; if the
    # city had no major roads in the extract, fall back to a single centre node
    # (routing then returns inf and the spawner uses straight-line distance).
    if not nodes:
        nodes = {0: ((bbox_m[0] + bbox_m[2]) / 2.0, (bbox_m[1] + bbox_m[3]) / 2.0)}

    sm = StreetMap(nodes=nodes, edges=edges, buildings=[], bbox=bbox_m,
                   source=source, edge_attrs=edge_attrs)

    for i, (ring_m, area, (cx, cz), levels, cat) in enumerate(tmp):
        built.append(Building(
            id=i, category=cat, footprint=ring_m, centroid=(cx, cz),
            area=area, levels=levels,
            neighborhood=_sector(cx, cz, bbox_m),
            street_node=sm.nearest_node((cx, cz)),
            name=f"{_sector(cx, cz, bbox_m)} {cat} {i}",
        ))
    sm.buildings = built
    return sm


# ---------------------------------------------------------------------------
# Offline path: reconstruct the canonical StreetMap from a *committed bundle*.
# ---------------------------------------------------------------------------
# The bundle's per-zone `blocks` ARE the city's rendered building stock (same
# metre frame as the geometry the game draws) and `roads` are its street lines.
# Rebuilding a StreetMap from them lets citizens be (re)generated from the exact
# city the player walks, with no OSM re-fetch -- the same canonical Building /
# CityWorld model the OSM path produces. Only building *category* is not stored
# in a bundle, so it is drawn deterministically per block, biased by the zone's
# real OSM-derived density (dense cells host more workplaces; sparse cells are
# mostly homes) so different cities yield materially different populations.
_ZONING = (RESIDENTIAL, COMMERCIAL, EDUCATION, MEDICAL, CIVIC, TRANSIT, INDUSTRIAL)


def _category_weights(density: float) -> np.ndarray:
    d = max(0.0, min(1.0, density))
    # Sharpened so the density gradient actually shows up in the building mix:
    # a dense downtown block is thick with commercial/civic/medical stock while a
    # sparse small-town block is overwhelmingly homes with a little light
    # industry -- so a metropolis and a small town spawn different populations.
    return np.array([
        6.0 - 2.5 * d,          # residential: dominant, fades a bit downtown
        0.3 + 6.0 * d,          # commercial: scales hard with density
        0.15 + 2.0 * d,         # education
        0.1 + 1.8 * d,          # medical
        0.1 + 1.6 * d,          # civic
        0.05 + 1.2 * d,         # transit
        1.8 - 1.5 * d,          # industrial: more at the sparse edges
    ], dtype=float)


def _roads_to_graph(road_polylines):
    """Street graph from bundle road polylines (already [x,z] metres)."""
    nodes: dict[int, tuple[float, float]] = {}
    node_of: dict[tuple[int, int], int] = {}
    edges: list[tuple[int, int, float]] = []
    edge_attrs: dict[tuple[int, int], dict] = {}

    def node_id(x: float, z: float) -> int:
        key = (int(round(x)), int(round(z)))
        nid = node_of.get(key)
        if nid is None:
            nid = len(nodes)
            node_of[key] = nid
            nodes[nid] = (float(x), float(z))
        return nid

    for pl in road_polylines:
        cls = pl.get("class", "")
        structure = structure_from_osm_tags(_road_class_to_tags(cls))
        prev = None
        for p in pl.get("points", []):
            nid = node_id(float(p[0]), float(p[1]))
            if prev is not None and prev != nid:
                a, b = prev, nid
                length = math.hypot(nodes[a][0] - nodes[b][0],
                                    nodes[a][1] - nodes[b][1])
                if length > 0:
                    edges.append((a, b, length))
                    edge_attrs[(a, b) if a <= b else (b, a)] = {"structure": structure}
            prev = nid
    return nodes, edges, edge_attrs


def street_map_from_bundle(zones, roads, seed: int = 0,
                           source: str = "bundle") -> StreetMap:
    """Reconstruct a canonical ``StreetMap`` from a committed bundle offline.

    ``zones`` is the bundle's zones list (each with ``blocks``/``density``);
    ``roads`` its roads dict (``polylines``). Deterministic in ``seed``.
    """
    polylines = roads.get("polylines", []) if isinstance(roads, dict) else []
    nodes, edges, edge_attrs = _roads_to_graph(polylines)

    # Bounds from block positions (the buildings themselves).
    xs, zs = [], []
    for z in zones:
        for blk in z.get("blocks", []):
            xy = blk["xy"]
            xs.append(float(xy[0]))
            zs.append(float(xy[1]))
    if xs:
        bbox_m = (min(xs), min(zs), max(xs), max(zs))
    else:
        bbox_m = (0.0, 0.0, 1.0, 1.0)
    if not nodes:
        nodes = {0: ((bbox_m[0] + bbox_m[2]) / 2.0, (bbox_m[1] + bbox_m[3]) / 2.0)}

    sm = StreetMap(nodes=nodes, edges=edges, buildings=[], bbox=bbox_m,
                   source=source, edge_attrs=edge_attrs)

    rng = np.random.default_rng(seed)
    built: list[Building] = []
    bid = 0
    for z in zones:
        density = float(z.get("density", 0.0))
        w = _category_weights(density)
        p = w / w.sum()
        for blk in z.get("blocks", []):
            cx, cz = float(blk["xy"][0]), float(blk["xy"][1])
            side = float(blk.get("footprint", 6.0))
            height = float(blk.get("height", 6.0))
            cat = _ZONING[int(rng.choice(len(_ZONING), p=p))]
            levels = max(1, int(round(height / 3.5)))
            half = side / 2.0
            footprint = [(cx - half, cz - half), (cx + half, cz - half),
                         (cx + half, cz + half), (cx - half, cz + half)]
            hood = _sector(cx, cz, bbox_m)
            built.append(Building(
                id=bid, category=cat, footprint=footprint, centroid=(cx, cz),
                area=side * side, levels=levels, neighborhood=hood,
                street_node=sm.nearest_node((cx, cz)),
                name=f"{hood} {cat} {bid}",
            ))
            bid += 1
    sm.buildings = built
    return sm

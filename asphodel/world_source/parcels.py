"""OW-MVP-3: block / parcel / frontage compiler.

Houston's official parcel layer is unreachable from this build environment
(recorded in provenance), so parcels here are DERIVED per the documented
fallback: city blocks are polygonized from the road network, classified by
land-use overlay + building/POI hints, and subdivided around building
footprints.  Nothing here pretends to be surveyed truth — every parcel
carries observation_class DERIVED.

Determinism: blocks are sorted by (round(centroid.z), round(centroid.x));
building subdivision uses Voronoi cells of building centroids sorted by
bid; parcel ids derive from block id + building stable key.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import polygonize, unary_union, voronoi_diagram
from shapely.strtree import STRtree

from .grammar_tables import (
    parcel_archetype_for_landuse,
    parcel_archetype_for_place,
)
from .records import Parcel

# Blocks are cut only by roads that structure the street grid.
_BLOCK_CUTTING = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "unclassified", "living_street",
}

# A building's parcel never extends farther than this from its footprint.
_MAX_YARD_M = 90.0
_MIN_BLOCK_AREA = 150.0
_FRONTAGE_REACH = 8.0  # beyond road half-width + sidewalk + verge


def _building_parcel_hint(props: dict) -> str | None:
    sub = (props.get("subtype") or "").lower()
    if not sub:
        return None
    return {
        "residential": "RESIDENTIAL",
        "commercial": "RETAIL",
        "retail": "RETAIL",
        "industrial": "INDUSTRIAL",
        "education": "SCHOOL",
        "medical": "MEDICAL",
        "civic": "CIVIC",
        "religious": "CIVIC",
        "outbuilding": None,
        "service": None,
        "agricultural": "VACANT_OPEN",
        "entertainment": "RETAIL",
        "transportation": "CIVIC",
    }.get(sub)


def compile_blocks(roads, bounds) -> list[Polygon]:
    """Polygonize road centerlines + world boundary into city blocks."""
    min_x, min_z, max_x, max_z = bounds
    frame = box(min_x, min_z, max_x, max_z)
    lines = [frame.exterior]
    for r in roads:
        if r.cls in _BLOCK_CUTTING and len(r.pts) >= 2:
            lines.append(LineString(r.pts))
    merged = unary_union(lines)
    blocks = []
    for poly in polygonize(merged):
        poly = poly.intersection(frame)
        if poly.is_empty or poly.area < _MIN_BLOCK_AREA:
            continue
        if poly.geom_type == "MultiPolygon":
            blocks.extend(g for g in poly.geoms if g.area >= _MIN_BLOCK_AREA)
        elif poly.geom_type == "Polygon":
            blocks.append(poly)
    blocks.sort(key=lambda p: (round(p.centroid.y, 1), round(p.centroid.x, 1)))
    return blocks


def _landuse_arch(poly: Polygon, lu_tree, lu_feats) -> tuple[str, float]:
    """Majority land-use archetype over a polygon -> (arch, covered_frac)."""
    best: dict[str, float] = {}
    total = 0.0
    if lu_tree is not None:
        for idx in lu_tree.query(poly):
            feat_poly, cls = lu_feats[int(idx)]
            try:
                a = poly.intersection(feat_poly).area
            except Exception:
                continue
            if a <= 0:
                continue
            arch = parcel_archetype_for_landuse(cls)
            best[arch] = best.get(arch, 0.0) + a
            total += a
    if not best:
        return ("UNKNOWN", 0.0)
    arch = max(sorted(best), key=lambda k: best[k])
    return (arch, min(1.0, total / max(poly.area, 1.0)))


def compile_parcels(roads, buildings, land_use_feats, place_feats, bounds):
    """Derive parcels for the full extent.

    roads: [RoadSegment]; buildings: [{bid, key, poly, props}] sorted by bid;
    land_use_feats: [(shapely_poly, class_str)]; place_feats:
    [(Point, category_str)]; bounds: (min_x, min_z, max_x, max_z).
    Returns (blocks, parcels) with parcels covering every block.
    """
    blocks = compile_blocks(roads, bounds)
    lu_tree = STRtree([p for p, _ in land_use_feats]) if land_use_feats else None
    place_tree = STRtree([pt for pt, _ in place_feats]) if place_feats else None

    # Bucket buildings into blocks by centroid.
    blk_tree = STRtree(blocks)
    blk_buildings: dict[int, list] = {i: [] for i in range(len(blocks))}
    homeless = []
    for b in buildings:
        c = b["poly"].centroid
        hit = None
        for idx in blk_tree.query(c):
            if blocks[int(idx)].covers(c):
                hit = int(idx)
                break
        if hit is None:
            homeless.append(b)
        else:
            blk_buildings[hit].append(b)

    parcels: list[Parcel] = []
    for bi, block in enumerate(blocks):
        blk_arch, blk_cov = _landuse_arch(block, lu_tree, lu_feats=land_use_feats)
        members = sorted(blk_buildings[bi], key=lambda b: b["bid"])
        if not members:
            arch = blk_arch if blk_arch != "UNKNOWN" else "VACANT_OPEN"
            parcels.append(Parcel(
                pid=f"p:{bi}:open", poly=block, arch=arch, obs="DERIVED",
                block_id=bi,
            ))
            continue

        cells = _subdivide(block, members)
        leftover = block
        for b, cell in cells:
            if cell.is_empty or cell.area <= 1.0:
                cell = b["poly"].buffer(2.0).intersection(block)
                if cell.is_empty:
                    continue
            arch = _parcel_arch_for(b, cell, blk_arch, place_tree, place_feats,
                                    lu_tree, land_use_feats)
            parcels.append(Parcel(
                pid=f"p:{bi}:{b['key']}", poly=cell, arch=arch, obs="DERIVED",
                block_id=bi, building_bids=[b["bid"]],
            ))
            leftover = leftover.difference(cell)
        # Open remainder (big-block interiors, park strips) stays intentional.
        if not leftover.is_empty and leftover.area > 400.0:
            geoms = (leftover.geoms if leftover.geom_type == "MultiPolygon"
                     else [leftover])
            for gi, g in enumerate(sorted(
                    geoms, key=lambda p: (round(p.centroid.y, 1),
                                          round(p.centroid.x, 1)))):
                if g.area < 400.0:
                    continue
                arch, cov = _landuse_arch(g, lu_tree, land_use_feats)
                if arch in ("UNKNOWN", "RESIDENTIAL") or cov < 0.2:
                    arch = "VACANT_OPEN" if arch != "PARK" else "PARK"
                parcels.append(Parcel(
                    pid=f"p:{bi}:rest{gi}", poly=g, arch=arch, obs="DERIVED",
                    block_id=bi,
                ))

    _derive_frontage(parcels, roads)
    return blocks, parcels


def _subdivide(block: Polygon, members: list):
    """Voronoi subdivision of a block around its buildings (capped yards)."""
    if len(members) == 1:
        b = members[0]
        cell = block.intersection(b["poly"].buffer(_MAX_YARD_M))
        cell = _principal_part(cell, b["poly"])
        return [(b, cell)]
    seeds = MultiPoint([b["poly"].centroid for b in members])
    try:
        vor = voronoi_diagram(seeds, envelope=block.buffer(50.0))
    except Exception:
        return [(b, b["poly"].buffer(3.0).intersection(block)) for b in members]
    cells_by_member = []
    vor_cells = list(vor.geoms)
    for b in members:
        c = b["poly"].centroid
        cell = None
        for vc in vor_cells:
            if vc.covers(c):
                cell = vc
                break
        if cell is None:
            cell = b["poly"].buffer(3.0)
        clipped = block.intersection(cell)
        clipped = clipped.intersection(
            b["poly"].buffer(_MAX_YARD_M))
        clipped = clipped.union(b["poly"].intersection(block)).buffer(0)
        cells_by_member.append((b, _principal_part(clipped, b["poly"])))
    return cells_by_member


def _principal_part(geom, footprint):
    """Keep the connected component containing the building footprint."""
    if geom.geom_type == "MultiPolygon":
        c = footprint.centroid
        parts = sorted(geom.geoms, key=lambda g: g.area, reverse=True)
        for g in parts:
            if g.intersects(footprint):
                return g
        return parts[0]
    return geom


def _parcel_arch_for(b, cell, blk_arch, place_tree, place_feats,
                     lu_tree, land_use_feats):
    lu_arch, lu_cov = _landuse_arch(cell, lu_tree, land_use_feats)
    hint = _building_parcel_hint(b["props"])
    poi = None
    if place_tree is not None:
        cats = []
        for idx in place_tree.query(cell):
            pt, cat = place_feats[int(idx)]
            if cell.covers(pt):
                cats.append(cat)
        for cat in sorted(cats):
            got = parcel_archetype_for_place(cat)
            if got:
                poi = got
                break
    # Precedence: specific POI > building subtype > land use > block context.
    for cand in (poi, hint):
        if cand:
            return cand
    if lu_arch != "UNKNOWN" and lu_cov >= 0.25:
        return lu_arch
    if blk_arch != "UNKNOWN":
        return blk_arch
    # Heuristic of last resort: small footprint reads residential.
    return "RESIDENTIAL" if b["poly"].area < 400.0 else "UNKNOWN"


def _derive_frontage(parcels: list[Parcel], roads) -> None:
    """Mark parcel boundary edges that face a road (street-facing side)."""
    lines = []
    meta = []
    for r in roads:
        if r.path_only or len(r.pts) < 2:
            continue
        lines.append(LineString(r.pts))
        meta.append(r)
    if not lines:
        return
    tree = STRtree(lines)
    for p in parcels:
        coords = list(p.poly.exterior.coords)
        best_key, best_d = None, 1e9
        for i in range(len(coords) - 1):
            mx = (coords[i][0] + coords[i + 1][0]) / 2.0
            mz = (coords[i][1] + coords[i + 1][1]) / 2.0
            pt = Point(mx, mz)
            idx = tree.nearest(pt)
            if idx is None:
                continue
            r = meta[int(idx)]
            d = lines[int(idx)].distance(pt)
            reach = r.carriage_w / 2.0 + r.sidewalk_w + r.verge_w + _FRONTAGE_REACH
            if d <= reach:
                p.frontage.append((coords[i], coords[i + 1]))
                if d < best_d:
                    best_d, best_key = d, r.key
        p.road_key = best_key

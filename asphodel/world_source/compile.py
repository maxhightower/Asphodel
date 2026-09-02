"""Exterior world compiler orchestrator.

Pipeline (mission §30): normalized WorldSourceV1 -> stable identity ->
streets -> parcels -> building grammar -> parcel detail -> surface raster
-> chunk emission.  Everything below is presentation compilation; the
authoritative simulation bundle files (zones/timeline/mobility/meta) are
not touched here.  buildings.json IS regenerated (identity re-founding,
§9 of the design doc) — callers must rebake citizens afterwards.
"""
from __future__ import annotations

import json
import os
import time

from ..city_visual import business_identity
from . import appearance_infer, buildings_grammar, detail, identity, normalize, streets
from . import parcels as parcels_mod
from .chunkgrid import ChunkGrid
from .chunks import build_chunks, expected_cells, write_chunks
from .geomutil import sanitize_polygon
from .records import SurfacePatch
from .schema import COMPILER_VERSION, validate_chunk
from .surfaces import census, paint_surfaces

# Overture base land_cover/land classes -> semantic surface (priority 20/30).
LANDCOVER_TO_SURFACE = {
    "forest": "TREE_CANOPY", "wood": "TREE_CANOPY", "tree": "TREE_CANOPY",
    "grass": "ROUGH_VEGETATION", "grassland": "ROUGH_VEGETATION",
    "meadow": "ROUGH_VEGETATION", "shrub": "ROUGH_VEGETATION",
    "scrub": "ROUGH_VEGETATION", "crop": "ROUGH_VEGETATION",
    "farmland": "ROUGH_VEGETATION",
    "barren": "BARE_GROUND", "sand": "BARE_GROUND", "rock": "BARE_GROUND",
    "urban": "OTHER_IMPERVIOUS", "developed": "OTHER_IMPERVIOUS",
    "impervious": "OTHER_IMPERVIOUS",
    "water": "WATER", "wetland": "ROUGH_VEGETATION", "mangrove": "ROUGH_VEGETATION",
    "snow": "BARE_GROUND", "ice": "BARE_GROUND",
}

_GREEN_LANDUSE = {"park", "recreation", "grass", "garden", "cemetery",
                  "pitch", "golf_course", "playground"}

ATTRIBUTION = [
    "Map data © OpenStreetMap contributors, Overture Maps Foundation "
    "(ODbL)",
    "Place data © Overture Maps Foundation (CDLA-Permissive-2.0)",
]


def _base_patches(ws) -> list[SurfacePatch]:
    """Observed base fill: land / land_cover / land_use greens / water."""
    patches = []
    for f in ws.land + ws.land_cover:
        poly = sanitize_polygon(f.geometry) if f.geom_type == "polygon" else None
        if poly is None:
            continue
        surf = LANDCOVER_TO_SURFACE.get(
            (f.properties.get("class") or f.properties.get("subtype") or "")
            .lower())
        if surf and surf != "WATER":
            patches.append(SurfacePatch(poly, surf, 20))
    for f in ws.land_use:
        poly = sanitize_polygon(f.geometry) if f.geom_type == "polygon" else None
        if poly is None:
            continue
        cls = (f.properties.get("class") or "").lower()
        if cls in _GREEN_LANDUSE:
            patches.append(SurfacePatch(poly, "MAINTAINED_GRASS", 22))
    for f in ws.water:
        poly = sanitize_polygon(f.geometry) if f.geom_type == "polygon" else None
        if poly is not None:
            patches.append(SurfacePatch(poly, "WATER", 30))
    return patches


def compile_city(city: str, release: str, seed: int,
                 out_dir: str | None = None,
                 data_root: str = "data/raw") -> dict:
    """Compile the full exterior world for one city; returns a report."""
    t0 = time.time()
    ws = normalize.load_world_source(city, release, data_root=data_root)
    bounds = ws.meta["bounds_m"]  # (min_x, min_z, max_x, max_z)
    grid = ChunkGrid(*bounds)

    ordered = identity.order_buildings(ws.buildings)
    ident = identity.identity_table(city, release, seed, ordered)

    segments = streets.compile_streets(ws.roads, seed)

    bdicts = []
    feats_by_bid = []
    for bid, f in enumerate(ordered):
        poly = sanitize_polygon(f.geometry)
        if poly is None:
            raise ValueError(f"normalize let through invalid footprint {f.stable_key}")
        bdicts.append({"bid": bid, "key": f.stable_key, "poly": poly,
                       "props": f.properties})
        feats_by_bid.append(f)

    lu_feats = []
    for f in ws.land_use:
        poly = sanitize_polygon(f.geometry) if f.geom_type == "polygon" else None
        if poly is not None:
            lu_feats.append((poly, (f.properties.get("class") or "")))
    place_feats = []
    from shapely.geometry import Point
    for f in ws.places:
        if f.geom_type == "point" and f.geometry:
            x, z = f.geometry[0]
            place_feats.append((Point(x, z), (f.properties.get("category") or "")))

    blocks, parcel_list = parcels_mod.compile_parcels(
        segments, bdicts, lu_feats, place_feats, bounds)

    brecords = buildings_grammar.compile_buildings(
        ordered, parcel_list, segments, seed)
    # Package C: fill appearance (facade/roof colour+material) for buildings that
    # carry no observed values, deterministically + spatially coherently. Never
    # overwrites observed truth; provenance stays honest (mostly PROCEDURAL).
    appearance_infer.infer_records(brecords, seed)
    # Package H: attach a deterministic fictional business identity to every
    # non-residential building (name/category/palette/sign_family, always
    # PROCEDURAL). Serialized into the chunk building dict for the renderer.
    business_identity.assign_records(brecords, seed)

    det = detail.compile_detail(parcel_list, brecords, segments, seed)
    curb = detail.curb_vehicles(segments, parcel_list, seed)
    sprops, sanchors = streets.street_props(segments, ws.connectors, seed)
    ent_anchors = detail.entrance_anchors(brecords)

    placements = det.placements + curb + sprops
    # Package E: remove vehicles whose footprints intersect (curb/driveway/parking
    # passes are independent and can collide).
    placements = detail.dedupe_vehicles(placements)
    anchors = _sanitize_anchors(det.anchors + sanchors + ent_anchors,
                                brecords, bounds)

    patches = (
        _base_patches(ws)
        + det.patches
        + streets.street_surface_patches(segments)
        + buildings_grammar.building_surface_patches(brecords)
    )
    rasters = paint_surfaces(grid, patches)
    surf_census = census(rasters)

    chunks = build_chunks(grid, rasters, segments, parcel_list, brecords,
                          placements, anchors)
    bad = []
    for key, chunk in chunks.items():
        errs = validate_chunk(chunk, expected_cells())
        if errs:
            bad.append((key, errs[:3]))
    if bad:
        raise ValueError(f"invalid chunks: {bad[:5]} (+{len(bad) - 5 if len(bad) > 5 else 0})")

    report = {
        "city": city,
        "release": release,
        "seed": seed,
        "compiler_version": COMPILER_VERSION,
        "counts": {
            "buildings": len(brecords),
            "parcels": len(parcel_list),
            "blocks": len(blocks),
            "road_segments": len(segments),
            "road_km": round(sum(
                _seg_len(s.pts) for s in segments) / 1000.0, 2),
            "placements": len(placements),
            "vehicles": sum(1 for p in placements if p.cat == "vehicle"),
            "trees": sum(1 for p in placements if p.cat == "tree"),
            "props": sum(1 for p in placements if p.cat == "prop"),
            "anchors": len(anchors),
            "chunks": len(chunks),
        },
        "surface_census_cells": surf_census,
        "detail_stats": det.stats,
        "elapsed_s": round(time.time() - t0, 1),
    }

    if out_dir is not None:
        _write_world(out_dir, city, release, seed, grid, ident, chunks,
                     anchors, report, feats_by_bid, brecords, ws,
                     parcel_list)
    return report


def _sanitize_anchors(anchors, brecords, bounds):
    """Spawn anchors are authoritative spatial promises: none may sit
    inside a building footprint or off-map.  Non-entrance anchors that
    cannot be salvaged are dropped; BUILDING_ENTRANCE anchors are nudged
    until clear (dense row-building edges can push a naive entrance point
    into the neighbour's footprint)."""
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    min_x, min_z, max_x, max_z = bounds
    polys = [b.poly for b in brecords]
    tree = STRtree(polys) if polys else None

    def inside(x, z):
        if tree is None:
            return False
        pt = Point(x, z)
        for idx in tree.query(pt):
            if polys[int(idx)].covers(pt):
                return True
        return False

    def in_bounds(x, z):
        return (min_x + 0.5 <= x <= max_x - 0.5
                and min_z + 0.5 <= z <= max_z - 0.5)

    out = []
    dropped = 0
    for a in anchors:
        x, z = a.x, a.z
        ok = in_bounds(x, z) and not inside(x, z)
        if not ok:
            found = None
            for r in (2.5, 4.0, 6.0, 9.0, 12.0):
                for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (0.707, 0.707), (-0.707, 0.707),
                               (0.707, -0.707), (-0.707, -0.707)):
                    nx, nz = x + dx * r, z + dz * r
                    if in_bounds(nx, nz) and not inside(nx, nz):
                        found = (nx, nz)
                        break
                if found:
                    break
            if found is None:
                dropped += 1
                continue  # even entrances: better absent than inside a wall
            a.x, a.z = found
        out.append(a)
    if dropped:
        print(f"[anchors] dropped {dropped} unsalvageable anchors")
    return out


def _seg_len(pts) -> float:
    import math
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def _write_world(out_dir, city, release, seed, grid, ident, chunks, anchors,
                 report, feats_by_bid, brecords, ws, ws_parcels):
    wdir = os.path.join(out_dir, "world")
    os.makedirs(wdir, exist_ok=True)
    sizes = write_chunks(wdir, chunks)
    meta = {
        "version": 1,
        "city": city,
        "source_release": release,
        "compiler_version": COMPILER_VERSION,
        "seed": seed,
        "bounds_m": list(grid_bounds(grid)),
        "chunk_size_m": 256.0,
        "chunk_grid": {"cols": grid.cols, "rows": grid.rows},
        "counts": report["counts"],
        "surface_census_cells": report["surface_census_cells"],
        "attribution": ATTRIBUTION,
        "license_note": (
            "world/ contains only geographic database content derived from "
            "ODbL/CDLA-Permissive sources plus procedural derivations; no "
            "proprietary gameplay data lives here."),
    }
    with open(os.path.join(wdir, "world_meta.json"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    import gzip

    def _write_gz(path, obj):
        payload = json.dumps(obj, separators=(",", ":"),
                             sort_keys=True).encode("utf-8")
        with open(path, "wb") as f:
            f.write(gzip.compress(payload, mtime=0))

    _write_gz(os.path.join(wdir, "identity.json.gz"), ident)
    _write_gz(os.path.join(wdir, "spawn_anchors.json.gz"), {
        "version": 1,
        "anchors": [[a.kind, round(a.x, 2), round(a.z, 2), a.bid]
                    for a in sorted(anchors, key=lambda a: (
                        a.kind, round(a.x, 2), round(a.z, 2), a.bid))],
    })

    # Regenerated authoritative buildings.json (identity re-founding).
    # "cat" is the occupation-workplace category (asphodel.world keys):
    # parcel context refines the building archetype so hospitals/schools
    # keep hosting their occupations after the source switch.
    parcel_arch = {}
    for p in ws_parcels:
        for bid in p.building_bids:
            parcel_arch[bid] = p.arch
    arch_cat = {
        "DETACHED_RESIDENTIAL": "residential", "MULTIFAMILY": "residential",
        "SMALL_COMMERCIAL": "commercial", "BIG_BOX_COMMERCIAL": "commercial",
        "OFFICE_HIGHRISE": "commercial", "INDUSTRIAL": "industrial",
        "CIVIC_SPECIAL": "civic", "GENERIC_UNKNOWN": "residential",
    }
    parcel_cat = {"SCHOOL": "education", "MEDICAL": "medical",
                  "CIVIC": "civic", "INDUSTRIAL": "industrial",
                  "RETAIL": "commercial", "OFFICE": "commercial"}
    blist = []
    for bid, rec in enumerate(brecords):
        ring = [[round(x, 2), round(z, 2)]
                for x, z in rec.poly.exterior.coords[:-1]]
        cat = parcel_cat.get(parcel_arch.get(bid, ""),
                             arch_cat.get(rec.arch, "residential"))
        blist.append({"poly": ring, "height": round(rec.h, 2),
                      "key": rec.key, "arch": rec.arch, "cat": cat})
    with open(os.path.join(out_dir, "buildings.json"), "w") as f:
        json.dump({"version": 1, "source": f"overture@{release}",
                   "storey_m": 3.3, "buildings": blist},
                  f, separators=(",", ":"), sort_keys=True)
    report["world_bytes"] = sum(sizes.values())


def grid_bounds(grid: ChunkGrid):
    return (grid.min_x, grid.min_z, grid.max_x, grid.max_z)

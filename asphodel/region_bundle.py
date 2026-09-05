"""Bake regional / mobility / physics artifacts into a city bundle (§17, §23).

These writers are ADDITIVE: they emit new files (``region.json``, ``streetmap.json``,
``physics.json``) alongside an existing bundle without touching the legacy
meta/zones/roads/timeline files, so the existing byte-determinism guarantees and
tests are untouched. The game's Godot loaders consume these new files to build
regional terrain, a routable mobility graph, and the collision matrix.

Everything here is offline and deterministic (§0, §3.1): identical inputs produce
byte-identical artifacts.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .geo import GeoReference
from .region import (
    SyntheticElevationProvider,
    RegionalExtent,
    archetype_for,
    bake_heightmap,
    build_quadtree,
    terrain_stats,
    landcover,
)
from .region.elevation import CachedDEMProvider
from .mobility import MobilityGraph, Mode
from .physics import (
    godot_layer_names,
    BODY_PROFILES,
    OBJECT_SOLIDITY,
    collision_matrix,
)

from .region.erosion import erode_and_hydrology

import numpy as np


def _stats_from_grid(h: np.ndarray, step_m: float) -> dict:
    """Relief statistics computed from a heightmap grid (the eroded surface)."""
    gy, gx = np.gradient(h, step_m)
    slope = np.hypot(gx, gy)
    return {
        "min_elevation": float(h.min()),
        "max_elevation": float(h.max()),
        "mean_elevation": float(h.mean()),
        "relief_span": float(h.max() - h.min()),
        "max_gradient": float(slope.max()),
        "mean_gradient": float(slope.mean()),
    }


def build_region_artifact(georef: GeoReference, archetype_name: str,
                          extent: Optional[RegionalExtent] = None,
                          seed: int = 0, focus=(0.0, 0.0),
                          heightmap_step_m: float = 800.0,
                          max_depth: int = 6) -> dict:
    """Build the regional terrain artifact for a city (§3).

    Ships a coarse baked heightmap (offline runtime source), the archetype macro
    form, relief statistics (the flat/mountain gate), a land-cover summary, and a
    chunk manifest describing the quadtree LOD for a default focus. Fine chunk
    meshes are rebuilt at runtime from the cached heightmap — the artifact stays
    small.
    """
    extent = extent or RegionalExtent.from_km(3, 40, 60, center=focus)
    arch = archetype_for(archetype_name)
    provider = SyntheticElevationProvider(georef, arch, seed=seed)

    # Bake the raw heightmap, then run the offline erosion + hydrology pass so the
    # terrain gains dendritic valleys and rivers (realism for every city).
    heightmap = bake_heightmap(provider, extent, step_m=heightmap_step_m)
    raw = np.asarray(heightmap["heights"], dtype=np.float64)
    mountainous = float(raw.max() - raw.min()) > 400.0
    hydro = erode_and_hydrology(raw, heightmap["step_m"], seed=seed,
                                mountainous=mountainous)
    eroded = hydro["heights"]
    heightmap["heights"] = [[round(float(v), 2) for v in row] for row in eroded]
    heightmap["eroded"] = True
    water_cells = [[int(r), int(c)] for r, c in zip(*np.where(hydro["water_mask"]))]

    stats = _stats_from_grid(eroded, heightmap["step_m"])

    # Land cover summary over a coarse grid.
    x0, z0, side = extent.root_square()
    xs = x0 + np.linspace(0, side, 64)
    zs = z0 + np.linspace(0, side, 64)
    gx, gz = np.meshgrid(xs, zs)
    codes = landcover.classify_grid(provider, arch, gx, gz, seed=seed)
    cover = landcover.coverage_fractions(codes)

    # Chunk manifest for a default center focus (Godot restreams as the player moves).
    leaves = build_quadtree(extent, focus, max_depth=max_depth)
    chunks = []
    for c in leaves:
        ps = c.physical_state(focus, collision_radius=extent.detailed_city_radius,
                              nav_radius=extent.detailed_city_radius * 0.7)
        chunks.append({
            "key": c.key(), "origin": [c.x0, c.z0], "size": c.size,
            "lod": c.lod, "depth": c.depth,
            "rendered": ps.rendered, "collision": ps.collision,
            "navigation": ps.navigation,
        })

    return {
        "version": "1",
        "georef": georef.to_dict(),
        "archetype": arch.name,
        "extent": {
            "detailed_city_radius": extent.detailed_city_radius,
            "regional_radius": extent.regional_radius,
            "horizon_radius": extent.horizon_radius,
            "center": list(extent.center),
        },
        "seed": seed,
        "terrain_stats": stats,
        "land_cover": cover,
        "sea_level": arch.sea_level,
        "heightmap": heightmap,
        "water_cells": water_cells,       # [row, col] into the heightmap grid
        "river_cells": hydro["river_cells"],
        "chunk_manifest": chunks,
        "atmosphere": {
            # First-pass aerial perspective params (§14): fog begins past the
            # detailed city and saturates near the horizon.
            "fog_start": extent.detailed_city_radius,
            "fog_end": extent.horizon_radius,
            "haze_tint": [0.62, 0.70, 0.80],
        },
    }


def build_mobility_artifact(roads: dict, snap: float = 3.0) -> dict:
    """Export a routable directed mobility graph from legacy roads polylines."""
    g = MobilityGraph.from_polylines(roads.get("polylines", []), snap=snap)
    segs = []
    # Recover endpoints for each segment from adjacency.
    endpoints = {}
    for u, adj in g._adj.items():
        for (v, sid, fwd) in adj:
            if fwd:
                endpoints[sid] = (u, v)
    for sid, seg in g.segments.items():
        u, v = endpoints.get(sid, (None, None))
        segs.append({
            "id": sid, "u": u, "v": v, "class": seg.road_class,
            "length": round(seg.length, 2),
            "directionality": seg.directionality.value,
            "modes": sorted(m.value for m in seg.allowed_modes),
            "speed_limit": seg.speed_limit, "lanes": seg.lanes,
        })
    return {
        "version": "1",
        "nodes": {nid: [round(p[0], 2), round(p[1], 2)] for nid, p in g.nodes.items()},
        "segments": segs,
        "stats": g.stats(),
    }


def build_physics_artifact() -> dict:
    """Export the authoritative collision matrix + solidity taxonomy."""
    return {
        "version": "1",
        "layers": {str(k): v for k, v in godot_layer_names().items()},
        "body_profiles": {k: {"layer": p.layer, "mask": p.mask, "role": p.role.value}
                          for k, p in BODY_PROFILES.items()},
        "object_solidity": {k: {"solidity": o.solidity.value, "body": o.body,
                                "collision": o.collision, "navigation": o.navigation}
                            for k, o in OBJECT_SOLIDITY.items()},
        "collision_matrix": [{"a": a, "b": b, "blocks": blocks}
                             for (a, b, blocks) in collision_matrix()],
    }


def _write_json(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def augment_bundle(bundle_dir: str, archetype_name: str, seed: int = 0) -> dict:
    """Read a compiled bundle and write region/mobility/physics artifacts into it."""
    with open(os.path.join(bundle_dir, "meta.json")) as f:
        meta = json.load(f)
    with open(os.path.join(bundle_dir, "roads.json")) as f:
        roads = json.load(f)

    georef = GeoReference.from_bundle_meta(meta)
    region = build_region_artifact(georef, archetype_name, seed=seed)
    mobility = build_mobility_artifact(roads)
    physics = build_physics_artifact()

    _write_json(os.path.join(bundle_dir, "region.json"), region)
    _write_json(os.path.join(bundle_dir, "streetmap.json"), mobility)
    _write_json(os.path.join(bundle_dir, "physics.json"), physics)
    return {"region": region, "mobility": mobility, "physics": physics}


def write_region_only_bundle(out_dir: str, name: str, lat: float, lon: float,
                             elevation: float, archetype_name: str,
                             seed: int = 0) -> dict:
    """Emit a region-only bundle (no OSM city) for a location — the regional
    visual proving ground (§20) for a city we cannot fetch offline (e.g. Denver)."""
    os.makedirs(out_dir, exist_ok=True)
    georef = GeoReference(lat, lon, origin_elevation=elevation)
    region = build_region_artifact(georef, archetype_name, seed=seed)
    region["name"] = name
    _write_json(os.path.join(out_dir, "region.json"), region)
    _write_json(os.path.join(out_dir, "physics.json"), build_physics_artifact())
    return region

"""End-to-end (network-free) core: parsed OSM -> bundle on disk.

`build_bundle` takes an already-resolved bbox plus parsed buildings/roads (so it
is fully testable offline), tessellates, runs the existing belief-cascade sim on
the resulting per-zone populations, lays out blocks/roads, and writes the bundle.
"""
from __future__ import annotations

import random

from dataclasses import asdict

from ..config import ScenarioConfig, ModelParams, GraphParams, PathogenGenome
from ..runner import run_scenario
from . import geometry as geo
from . import tessellate as tess
from . import bundle as bnd


def _densest_populated_zone(zones: list[dict]) -> int:
    best = max(zones, key=lambda z: z["population"])
    if best["population"] > 0.0:
        return best["id"]
    return len(zones) // 2  # fallback: grid center-ish


# Storey height used when OSM gives levels but no explicit height tag.
_LEVEL_HEIGHT_M = 3.2
_MIN_FOOTPRINT_M2 = 6.0


def bake_footprints(buildings, lat0, lon0, max_buildings=30000) -> list[dict]:
    """Project building rings to local meters for the buildings.json payload.

    Drops degenerate/tiny rings; when over `max_buildings`, keeps the ones
    closest to the city center so dense downtowns stay coherent.
    """
    out = []
    for b in buildings:
        ring = [geo.project(lat, lon, lat0, lon0) for (lat, lon) in b["ring"]]
        # Overpass closed ways repeat the first node; store the open ring.
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) < 3:
            continue
        area = geo.polygon_area(ring)
        if area < _MIN_FOOTPRINT_M2:
            continue
        levels = max(1, int(b.get("levels", 1)))
        height = b.get("height_m") or levels * _LEVEL_HEIGHT_M
        cx = sum(p[0] for p in ring) / len(ring)
        cz = sum(p[1] for p in ring) / len(ring)
        entry = {
            "footprint": [[round(x, 2), round(z, 2)] for x, z in ring],
            "center_xy": [round(cx, 2), round(cz, 2)],
            "levels": levels,
            "height": round(float(height), 2),
            "kind": b.get("kind", "generic"),
            "area_m2": round(area, 1),
        }
        if b.get("name"):
            entry["name"] = b["name"]
        out.append(entry)
    if len(out) > max_buildings:
        out.sort(key=lambda e: e["center_xy"][0] ** 2 + e["center_xy"][1] ** 2)
        out = out[:max_buildings]
    return out


def build_bundle(query, bbox, buildings, roads, out_dir, grid=16,
                 total_pop=500000.0, seed=0, n_days=120.0, dt=0.25,
                 genome=None, max_buildings=30000) -> None:
    genome = genome or PathogenGenome()
    south, west, north, east = bbox
    lat0, lon0 = (south + north) / 2.0, (west + east) / 2.0

    # 1. Tessellate into a grid with density-weighted population.
    t = tess.tessellate(bbox, buildings, grid=grid, total_pop=total_pop)
    populations = [z["population"] for z in t.zones]
    seed_zone = _densest_populated_zone(t.zones)

    # 2. Run the existing belief-cascade sim on the real populations.
    cfg = ScenarioConfig(
        name=query,
        genome=genome,
        model=ModelParams(graph=GraphParams(
            grid_rows=t.rows, grid_cols=t.cols, population=populations,
        )),
        dt=dt, n_days=n_days, seed=seed, seed_zone=seed_zone,
    )
    result = run_scenario(cfg)

    # 3. Lay out representative blocks per zone (deterministic RNG).
    rng = random.Random(seed)
    for z in t.zones:
        z["blocks"] = geo.place_blocks(
            z["density"], tuple(z["center_xy"]), tuple(z["extent"]), rng,
        )

    # 4. Project roads + building footprints to local meters.
    road_out = {"polylines": [
        {"class": r["class"], "points": geo.project_polyline(r["points"], lat0, lon0)}
        for r in roads
    ]}
    building_out = bake_footprints(buildings, lat0, lon0, max_buildings=max_buildings)

    # 5. Assemble bundle.
    meta = {
        "name": query, "query": query,
        "bbox": [south, west, north, east], "center": [lat0, lon0],
        "projection": "equirectangular",
        # cell_m is the mean cell side (cells are near-square but not exactly);
        # Godot uses each zone's own `extent` for precise sizing.
        "grid": {"rows": t.rows, "cols": t.cols,
                 "cell_m": round((t.cell_w + t.cell_h) / 2.0, 3)},
        "dt": dt, "n_days": n_days, "n_ticks": cfg.n_ticks,
        "genome": asdict(genome), "seed": seed, "seed_zone": seed_zone,
        "n_buildings": len(building_out),
        "version": "1",
    }
    timeline = bnd.build_timeline(result.belief_history)
    bnd.write_bundle(out_dir, meta, t.zones, road_out, timeline,
                     buildings=building_out)

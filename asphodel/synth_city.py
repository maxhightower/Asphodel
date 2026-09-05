"""Offline synthetic city bundle generator (procedural, deterministic).

When a real public-data city cannot be fetched (offline / restricted egress),
this produces a plausible detailed-city bundle — a downtown grid of streets and
buildings with a density gradient — in the SAME bundle schema the canonical
loaders accept (meta/zones/roads/timeline/mobility/buildings/citizens), then
augments it with regional terrain, the street graph, and the physics matrix.
It is clearly a *synthesized* city (``meta.source == "synthetic"``); nothing in
it pretends to be surveyed truth. It has no compiled ``world/`` stream, so Godot
renders it through the footprint fallback path.

CLI:  python -m asphodel.synth_city boulder  (regenerates the committed bundle)
"""
from __future__ import annotations

import json
import math
import os
import random

import numpy as np
from typing import Optional

from .region_bundle import augment_bundle


def _smooth_falloff(x: float, z: float, cx: float, cz: float, radius: float) -> float:
    d = math.hypot(x - cx, z - cz)
    t = max(0.0, 1.0 - d / radius)
    return t * t * (3.0 - 2.0 * t)   # smoothstep density 1 at core -> 0 at edge


def build_synth_city_bundle(
    out_dir: str,
    name: str,
    lat: float,
    lon: float,
    elevation: float,
    archetype_name: str,
    seed: int = 0,
    bounds=(-1900.0, 3100.0, -2300.0, 2300.0),  # x0, x1, z0, z1 (metres)
    downtown=(600.0, 0.0),
    zone_m: float = 400.0,
    block_street_m: float = 135.0,
    augment: bool = True,
) -> dict:
    """Write a synthetic city bundle to ``out_dir`` and return the meta dict."""
    rng = random.Random(seed)
    x0, x1, z0, z1 = bounds
    cx, cz = downtown
    core_radius = 1900.0   # a tight, recognizable downtown core

    cols = int(math.ceil((x1 - x0) / zone_m))
    rows = int(math.ceil((z1 - z0) / zone_m))

    zones = []
    for r in range(rows):
        for c in range(cols):
            zx = x0 + (c + 0.5) * zone_m
            zz = z0 + (r + 0.5) * zone_m
            density = _smooth_falloff(zx, zz, cx, cz, core_radius)
            n_blocks = int(round(density * 8)) + (1 if density > 0.1 else 0)
            blocks = []
            for _ in range(n_blocks):
                bx = zx + (rng.random() - 0.5) * zone_m * 0.85
                bz = zz + (rng.random() - 0.5) * zone_m * 0.85
                # A taller, denser core tapering to low-rise suburbs.
                h = 7.0 + pow(density, 1.3) * 62.0 * (0.55 + 0.45 * rng.random())
                fp = 14.0 + 20.0 * rng.random()
                blocks.append({"xy": [round(bx, 2), round(bz, 2)],
                               "height": round(h, 2), "footprint": round(fp, 2)})
            zones.append({
                "id": r * cols + c, "row": r, "col": c,
                "center_xy": [round(zx, 2), round(zz, 2)],
                "extent": [zone_m, zone_m],
                "density": round(density, 4),
                "population": round(density * 1800.0, 1),
                "blocks": blocks,
            })

    # Street grid emitted as per-block segments so intersections become shared
    # nodes (a routable grid, not disconnected full-span lines). Each segment
    # spans one block between adjacent intersections.
    xs = []
    x = x0
    while x <= x1 + 1e-6:
        xs.append(round(x, 2))
        x += block_street_m
    zs = []
    z = z0
    while z <= z1 + 1e-6:
        zs.append(round(z, 2))
        z += block_street_m
    arterial = zone_m * 1.5

    def _cls(x, z):
        on_art = (abs((x - x0) % arterial) < 1e-6) or (abs((z - z0) % arterial) < 1e-6)
        return "secondary" if on_art else "residential"

    polylines = []
    for zi, z in enumerate(zs):
        for xi, x in enumerate(xs):
            if xi + 1 < len(xs):     # east edge (an east-west street)
                polylines.append({"class": _cls(x, z),
                                   "points": [[x, z], [xs[xi + 1], z]]})
            if zi + 1 < len(zs):     # south edge (a north-south street)
                polylines.append({"class": _cls(x, z),
                                   "points": [[x, z], [x, zs[zi + 1]]]})

    # --- the epidemic tier: the same products asphodel.osm_city.pipeline bakes
    # for a real city, so worldfactory / the bridge / BundleLoader accept this
    # bundle without a special case.
    from dataclasses import asdict
    from .config import ScenarioConfig, ModelParams, GraphParams, PathogenGenome
    from .runner import run_scenario
    from .osm_city import mobility as mob
    from .osm_city import bundle as bnd
    from .osm_city import buildings as bld
    from .osm_city.citizens import write_citizens_from_bundle

    local_floor = 0.1
    dt, n_days = 0.25, 90.0
    genome = PathogenGenome()
    populations = [z["population"] for z in zones]
    seed_zone = max(zones, key=lambda z: z["population"])["id"]
    mobility_edges = mob.derive_zone_mobility(
        zones, polylines, rows, cols, local_floor=local_floor)
    cfg = ScenarioConfig(
        name=name, genome=genome,
        model=ModelParams(graph=GraphParams(
            grid_rows=rows, grid_cols=cols, population=populations,
            mobility_edges=mobility_edges if mobility_edges else None)),
        dt=dt, n_days=n_days, seed=seed, seed_zone=seed_zone)
    result = run_scenario(cfg)
    stats = mob.mobility_stats(mobility_edges, rows * cols)

    # A synthetic bbox implied by the metre bounds (equirectangular inverse).
    dlat = (z1 - z0) / 111320.0 / 2.0
    dlon = (x1 - x0) / (111320.0 * math.cos(math.radians(lat))) / 2.0
    meta = {
        "name": name, "query": name,
        "bbox": [lat - dlat, lon - dlon, lat + dlat, lon + dlon],
        "center": [lat, lon],
        "origin_elevation": elevation,
        "projection": "equirectangular",
        "grid": {"rows": rows, "cols": cols, "cell_m": zone_m},
        "dt": dt, "n_days": n_days, "n_ticks": cfg.n_ticks,
        "genome": asdict(genome), "seed": seed, "seed_zone": seed_zone,
        "mobility": {"source": "roads", "local_floor": local_floor,
                     "n_edges": stats["n_edges"],
                     "connected_components": stats["connected_components"]},
        "source": "synthetic",
        "version": "1",
    }
    roads = {"polylines": polylines}
    timeline = bnd.build_timeline(result.belief_history)
    bnd.write_bundle(out_dir, meta, zones, roads, timeline,
                     mobility={"version": 1, "local_floor": local_floor,
                               "edges": mobility_edges})
    # Canonical {version, buildings:[{poly,height}]} footprints, road-aware.
    footprints = bld.generate_procedural(zones, seed=seed, roads=polylines)
    footprints["source"] = "procedural-synthetic"
    # Workplace categories by zone density (the same zoning mix the legacy
    # bake used), so the synthetic city has shops, offices, clinics and
    # schools for citizens to work in — not 639 houses. Deterministic.
    from .osm_city.world_from_osm import _ZONING, _category_weights
    zrng = np.random.default_rng(seed + 101)
    zone_of = {}
    for z in zones:
        zone_of[(z["row"], z["col"])] = z
    for b in footprints["buildings"]:
        cx = sum(p[0] for p in b["poly"]) / len(b["poly"])
        cz = sum(p[1] for p in b["poly"]) / len(b["poly"])
        c = int((cx - x0) // zone_m); r = int((cz - z0) // zone_m)
        z = zone_of.get((min(rows - 1, max(0, r)), min(cols - 1, max(0, c))))
        density = float(z["density"]) if z else 0.0
        w = _category_weights(density)
        b["cat"] = _ZONING[int(zrng.choice(len(_ZONING), p=w / w.sum()))]
    bnd._write_json(os.path.join(out_dir, "buildings.json"), footprints)
    write_citizens_from_bundle(out_dir, name, n=60, seed=seed)

    if augment:
        augment_bundle(out_dir, archetype_name, seed=seed)
    return meta


# Committed synthetic cities: name -> generator arguments.
SYNTH_CITIES = {
    "boulder": dict(name="Boulder, Colorado", lat=40.015, lon=-105.2705,
                    elevation=1655.0, archetype_name="front_range_adjacent",
                    seed=7),
}


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m asphodel.synth_city")
    p.add_argument("city", choices=sorted(SYNTH_CITIES))
    p.add_argument("--out", default=None,
                   help="bundle directory (default godot/bundles/<city>)")
    args = p.parse_args(argv)
    out = args.out or os.path.join("godot", "bundles", args.city)
    meta = build_synth_city_bundle(out, **SYNTH_CITIES[args.city])
    print(f"wrote synthetic bundle {args.city} -> {out} ({meta['grid']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _write(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")

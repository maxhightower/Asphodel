"""End-to-end (network-free) core: parsed OSM -> bundle on disk.

`build_bundle` takes an already-resolved bbox plus parsed buildings/roads (so it
is fully testable offline), tessellates, runs the existing belief-cascade sim on
the resulting per-zone populations, lays out blocks/roads, and writes the bundle.
"""
from __future__ import annotations

import os
import random

from dataclasses import asdict

from ..config import ScenarioConfig, ModelParams, GraphParams, PathogenGenome
from ..runner import run_scenario
from . import geometry as geo
from . import tessellate as tess
from . import bundle as bnd
from . import mobility as mob

# Small local-diffusion floor linking grid-adjacent *populated* cells so the
# epidemic doesn't fragment where only minor (un-fetched) streets connect two
# neighbourhoods. It is tiny next to a real road's capacity (residential 1.0 up
# to motorway 8.0), so roads still dominate relative mobility.
DEFAULT_LOCAL_FLOOR = 0.1


def _densest_populated_zone(zones: list[dict]) -> int:
    best = max(zones, key=lambda z: z["population"])
    if best["population"] > 0.0:
        return best["id"]
    return len(zones) // 2  # fallback: grid center-ish


def rebake_mobility(bundle_dir: str, local_floor=DEFAULT_LOCAL_FLOOR) -> dict:
    """Offline: re-derive a committed bundle's road-mobility graph and re-run its
    sim so the baked timeline reflects real-road connectivity. No OSM re-fetch --
    it uses the bundle's own zones/roads/meta. Returns the mobility stats.

    Rewrites ``timeline.json`` + ``mobility.json`` and updates ``meta.json``'s
    mobility summary; leaves zones/roads/citizens untouched.
    """
    import json
    import os

    with open(os.path.join(bundle_dir, "meta.json")) as f:
        meta = json.load(f)
    with open(os.path.join(bundle_dir, "zones.json")) as f:
        zones = json.load(f)
    with open(os.path.join(bundle_dir, "roads.json")) as f:
        roads = json.load(f)

    zones = sorted(zones, key=lambda z: z["id"])
    rows = int(meta["grid"]["rows"])
    cols = int(meta["grid"]["cols"])
    populations = [z["population"] for z in zones]

    mobility_edges = mob.derive_zone_mobility(
        zones, roads.get("polylines", []), rows, cols, local_floor=local_floor)

    genome = PathogenGenome(**meta["genome"])
    cfg = ScenarioConfig(
        name=meta.get("name", bundle_dir),
        genome=genome,
        model=ModelParams(graph=GraphParams(
            grid_rows=rows, grid_cols=cols, population=populations,
            mobility_edges=mobility_edges if mobility_edges else None,
        )),
        dt=float(meta["dt"]), n_days=float(meta["n_days"]),
        seed=int(meta["seed"]), seed_zone=int(meta["seed_zone"]),
    )
    result = run_scenario(cfg)

    stats = mob.mobility_stats(mobility_edges, rows * cols)
    meta["mobility"] = {"source": "roads", "local_floor": local_floor,
                        "n_edges": stats["n_edges"],
                        "connected_components": stats["connected_components"]}
    timeline = bnd.build_timeline(result.belief_history)
    bnd._write_json(os.path.join(bundle_dir, "meta.json"), meta)
    bnd._write_json(os.path.join(bundle_dir, "timeline.json"), timeline)
    bnd._write_json(os.path.join(bundle_dir, "mobility.json"),
                    {"version": 1, "local_floor": local_floor, "edges": mobility_edges})
    return stats


def build_bundle(query, bbox, buildings, roads, out_dir, grid=16,
                 total_pop=500000.0, seed=0, n_days=120.0, dt=0.25,
                 genome=None, bake_citizens=True, n_citizens=60,
                 local_floor=DEFAULT_LOCAL_FLOOR) -> None:
    genome = genome or PathogenGenome()
    south, west, north, east = bbox
    lat0, lon0 = (south + north) / 2.0, (west + east) / 2.0

    # 1. Tessellate into a grid with density-weighted population.
    t = tess.tessellate(bbox, buildings, grid=grid, total_pop=total_pop)
    populations = [z["population"] for z in t.zones]
    seed_zone = _densest_populated_zone(t.zones)

    # 2. Project roads to local meters (needed before the sim so real-road
    #    connectivity can shape inter-zone mobility).
    road_out = {"polylines": [
        {"class": r["class"], "points": geo.project_polyline(r["points"], lat0, lon0)}
        for r in roads
    ]}

    # 3. Derive the real-road zone-mobility graph the epidemic will ride.
    mobility_edges = mob.derive_zone_mobility(
        t.zones, road_out["polylines"], t.rows, t.cols, local_floor=local_floor)

    # 4. Run the belief-cascade sim on the real populations AND real-road mobility.
    cfg = ScenarioConfig(
        name=query,
        genome=genome,
        model=ModelParams(graph=GraphParams(
            grid_rows=t.rows, grid_cols=t.cols, population=populations,
            mobility_edges=mobility_edges if mobility_edges else None,
        )),
        dt=dt, n_days=n_days, seed=seed, seed_zone=seed_zone,
    )
    result = run_scenario(cfg)

    # 5. Lay out representative blocks per zone (deterministic RNG).
    rng = random.Random(seed)
    for z in t.zones:
        z["blocks"] = geo.place_blocks(
            z["density"], tuple(z["center_xy"]), tuple(z["extent"]), rng,
        )

    # 6. Assemble bundle.
    stats = mob.mobility_stats(mobility_edges, t.rows * t.cols)
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
        "mobility": {"source": "roads", "local_floor": local_floor,
                     "n_edges": stats["n_edges"],
                     "connected_components": stats["connected_components"]},
        "version": "1",
    }
    timeline = bnd.build_timeline(result.belief_history)
    mobility_payload = {"version": 1, "local_floor": local_floor,
                        "edges": mobility_edges}
    bnd.write_bundle(out_dir, meta, t.zones, road_out, timeline,
                     mobility=mobility_payload)

    # 5b. Real building footprints: project the OSM building rings into the
    #     bundle metre frame so the renderer can extrude the ACTUAL city, not
    #     just density-derived sticks. Falls back to a procedural fill if no OSM
    #     rings are available (e.g. re-deriving an old bundle).
    from . import buildings as bld
    if buildings:
        footprints = bld.project_osm_buildings(buildings, lat0, lon0)
    else:
        footprints = bld.generate_procedural(t.zones, seed=seed)
    bnd._write_json(os.path.join(out_dir, "buildings.json"), footprints)

    # 6. Bake a spawnable citizen population from the SAME resolved city -- real
    #    buildings, real streets, real population geography -- so the playable
    #    citizens are materially derived from this city, not a generic profile.
    if bake_citizens:
        from .citizens import build_population_from_osm, _write
        pop = build_population_from_osm(bbox, buildings, roads, city_name=query,
                                        n=n_citizens, seed=seed)
        _write(out_dir, pop)

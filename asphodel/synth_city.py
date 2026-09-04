"""Offline synthetic city bundle generator (procedural, deterministic).

When a real OSM city cannot be fetched (offline / restricted egress), this
produces a plausible detailed-city bundle — a downtown grid of streets and
buildings with a density gradient — in the same bundle schema Godot loads
(meta/zones/roads), then augments it with regional terrain, a mobility graph, and
the physics matrix. It is clearly a *synthesized* city, matching Asphodel's
"procedurally synthesized worlds converging into common types" direction.
"""
from __future__ import annotations

import json
import math
import os
import random
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

    # Street grid: local streets + wider arterials.
    polylines = []
    x = x0
    while x <= x1 + 1e-6:
        cls = "secondary" if abs((x - x0) % (zone_m * 1.5)) < 1e-6 else "residential"
        polylines.append({"class": cls, "points": [[round(x, 2), z0], [round(x, 2), z1]]})
        x += block_street_m
    z = z0
    while z <= z1 + 1e-6:
        cls = "secondary" if abs((z - z0) % (zone_m * 1.5)) < 1e-6 else "residential"
        polylines.append({"class": cls, "points": [[x0, round(z, 2)], [x1, round(z, 2)]]})
        z += block_street_m

    meta = {
        "name": name,
        "center": [lat, lon],
        "origin_elevation": elevation,
        "projection": "equirectangular",
        "grid": {"rows": rows, "cols": cols, "cell_m": zone_m},
        "seed": seed,
        "source": "synthetic",
        "version": "1",
    }

    os.makedirs(out_dir, exist_ok=True)
    _write(os.path.join(out_dir, "meta.json"), meta)
    _write(os.path.join(out_dir, "zones.json"), zones)
    _write(os.path.join(out_dir, "roads.json"), {"polylines": polylines})

    if augment:
        augment_bundle(out_dir, archetype_name, seed=seed)
    return meta


def _write(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")

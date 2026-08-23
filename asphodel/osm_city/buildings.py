"""Building footprints for a bundle — real OSM polygons *or* a procedural fill.

The tessellation step (``tessellate.py``) collapses each real OSM building
footprint into a per-zone *density* scalar and discards the polygon. That is fine
for the epidemic (density -> population) but leaves the renderer with nothing to
draw but a few procedural sticks. This module produces an explicit **building
footprint layer** the renderer can extrude into real masses:

* :func:`project_osm_buildings` — the REAL path: project each OSM building ring
  (lat/lon, as fetched by ``overpass.parse_elements``) into the bundle's metre
  frame and carry its height. Wire this into a bake and the city mirrors OSM.
* :func:`generate_procedural` — the FALLBACK: when the real rings are gone (the
  committed bundles), fill each zone with a deterministic grid of rectangular
  buildings whose coverage and height scale with the zone's density, leaving
  street gaps. A plausible built-up city, explicitly *not* the real footprints.

Both return the same schema, written to ``buildings.json``::

    {"version": 1, "source": "osm"|"procedural", "storey_m": 3.3,
     "buildings": [{"poly": [[x, z], ...], "height": float}, ...]}
"""

from __future__ import annotations

import random

from . import geometry as geo


SCHEMA_VERSION = 1
STOREY_M = 3.3


# --------------------------------------------------------------------------- #
# real OSM path
# --------------------------------------------------------------------------- #
def project_osm_buildings(buildings, lat0: float, lon0: float,
                          storey_m: float = STOREY_M) -> dict:
    """Project OSM building rings into the bundle metre frame.

    ``buildings`` is ``overpass.parse_elements``'s building list:
    ``[{"ring": [(lat, lon), ...], "levels": int, ...}]``. Height is
    ``levels * storey_m``. Rings with fewer than 3 vertices are skipped.
    """
    out = []
    for b in buildings:
        ring = b.get("ring", [])
        if len(ring) < 3:
            continue
        poly = [list(geo.project(lat, lon, lat0, lon0)) for (lat, lon) in ring]
        levels = max(1, int(b.get("levels", 1)))
        out.append({"poly": poly, "height": round(levels * storey_m, 2)})
    return {"version": SCHEMA_VERSION, "source": "osm",
            "storey_m": storey_m, "buildings": out}


# --------------------------------------------------------------------------- #
# procedural fallback
# --------------------------------------------------------------------------- #
def generate_procedural(zones, seed: int = 0, storey_m: float = STOREY_M,
                        parcel_target_m: float = 80.0,
                        street_frac: float = 0.28) -> dict:
    """Fill every zone with a deterministic grid of rectangular buildings.

    For each zone the cell is divided into an NxN grid of parcels (~
    ``parcel_target_m`` across); a fraction of each parcel is left as street
    (``street_frac``), and a building is placed in the remainder with probability
    scaled by the zone density. Building height scales with density (downtown
    rises, suburbs stay low). Deterministic from ``seed`` + zone id.
    """
    out = []
    for z in sorted(zones, key=lambda zz: int(zz["id"])):
        density = float(z.get("density", 0.0))
        if density <= 0.0:
            continue
        cx, cz = z["center_xy"]
        w, h = z["extent"]
        rng = random.Random(seed * 1_000_003 + int(z["id"]))
        ncols = max(1, round(w / parcel_target_m))
        nrows = max(1, round(h / parcel_target_m))
        pw = w / ncols
        ph = h / nrows
        x0 = cx - w * 0.5
        z0 = cz - h * 0.5
        # Coverage: even sparse zones get some buildings; dense ones nearly fill.
        p_build = min(0.95, 0.12 + density * 1.4)
        for r in range(nrows):
            for c in range(ncols):
                if rng.random() > p_build:
                    continue
                # Parcel box, minus a street margin; building fills 55-85% of it.
                fill = 0.55 + 0.30 * rng.random()
                bw = pw * (1.0 - street_frac) * fill
                bh = ph * (1.0 - street_frac) * fill
                # Jittered centre within the parcel's buildable area.
                margin_x = (pw - bw) * 0.5
                margin_z = (ph - bh) * 0.5
                pcx = x0 + (c + 0.5) * pw + (rng.random() - 0.5) * margin_x
                pcz = z0 + (r + 0.5) * ph + (rng.random() - 0.5) * margin_z
                # Height: 1 storey (suburb) up to ~10 (downtown), density-driven.
                levels = 1 + int(round(density * 9.0 * (0.5 + rng.random())))
                height = round(levels * storey_m, 2)
                hx, hz = bw * 0.5, bh * 0.5
                poly = [[pcx - hx, pcz - hz], [pcx + hx, pcz - hz],
                        [pcx + hx, pcz + hz], [pcx - hx, pcz + hz]]
                out.append({"poly": poly, "height": height})
    return {"version": SCHEMA_VERSION, "source": "procedural",
            "storey_m": storey_m, "buildings": out}

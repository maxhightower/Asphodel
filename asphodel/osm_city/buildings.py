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

# CONVERGENCE NOTE: the canonical building producer is asphodel/world_source
# (Overture footprints -> buildings.json v1 + world/ chunks). generate_procedural
# here is the offline fallback for a SYNTHETIC city (asphodel.synth_city) and
# project_osm_buildings the June OSM path; both write the same v1 schema.

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

# Corridor half-widths (metres) reserved around each road class so a procedural
# footprint never lands on a street. These mirror the Godot renderer's roadway +
# sidewalk extents (street_world._build_surface_road / _build_elevated) plus a
# small clearance margin, since the true footprint map isn't known here.
_CORRIDOR_HALF = {
    "motorway": 10.0, "trunk": 10.0,   # wide elevated deck
    "primary": 10.0,                   # 12 m roadway + 3 m walk + margin
    "secondary": 7.5, "tertiary": 7.5,  # 8 m roadway + 2.2 m walk + margin
}
_CORRIDOR_DEFAULT = 6.5


def _corridor_half(cls: str) -> float:
    return _CORRIDOR_HALF.get(cls, _CORRIDOR_DEFAULT)


def _seg_aabb_hit(ax: float, az: float, bx: float, bz: float,
                  minx: float, minz: float, maxx: float, maxz: float) -> bool:
    """Liang–Barsky: does segment (a->b) touch the axis-aligned box? Used to test
    a candidate footprint (its box expanded by the corridor half-width) against a
    road segment — a hit means the building would sit on the street, so reject it."""
    dx = bx - ax
    dz = bz - az
    p = (-dx, dx, -dz, dz)
    q = (ax - minx, maxx - ax, az - minz, maxz - az)
    t0, t1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0.0:
            if qi < 0.0:
                return False            # parallel and outside this slab
        else:
            t = qi / pi
            if pi < 0.0:
                if t > t1:
                    return False
                if t > t0:
                    t0 = t
            else:
                if t < t0:
                    return False
                if t < t1:
                    t1 = t
    return True


def _zone_corridors(zone, roads, pad: float):
    """Segments (ax, az, bx, bz, half) of every road that comes near this zone's
    cell (within ``pad`` of its bounds), so a footprint is only tested against the
    handful of roads that could actually cross it."""
    cx, cz = zone["center_xy"]
    w, h = zone["extent"]
    minx, maxx = cx - w * 0.5 - pad, cx + w * 0.5 + pad
    minz, maxz = cz - h * 0.5 - pad, cz + h * 0.5 + pad
    segs = []
    for pl in roads:
        half = _corridor_half(str(pl.get("class", "")))
        pts = pl.get("points", [])
        for k in range(len(pts) - 1):
            ax, az = float(pts[k][0]), float(pts[k][1])
            bx, bz = float(pts[k + 1][0]), float(pts[k + 1][1])
            # Cheap reject: segment bbox (grown by half) misses the zone bbox.
            if max(ax, bx) + half < minx or min(ax, bx) - half > maxx:
                continue
            if max(az, bz) + half < minz or min(az, bz) - half > maxz:
                continue
            segs.append((ax, az, bx, bz, half))
    return segs


def _on_street(pcx: float, pcz: float, hx: float, hz: float, corridors) -> bool:
    """True if the footprint box (centre pcx,pcz half hx,hz) overlaps any road
    corridor — i.e. it would clip a street."""
    for ax, az, bx, bz, half in corridors:
        if _seg_aabb_hit(ax, az, bx, bz,
                         pcx - hx - half, pcz - hz - half,
                         pcx + hx + half, pcz + hz + half):
            return True
    return False


def generate_procedural(zones, seed: int = 0, storey_m: float = STOREY_M,
                        parcel_target_m: float = 80.0,
                        street_frac: float = 0.28,
                        roads=None) -> dict:
    """Fill every zone with a deterministic grid of rectangular buildings.

    For each zone the cell is divided into an NxN grid of parcels (~
    ``parcel_target_m`` across); a fraction of each parcel is left as street
    (``street_frac``), and a building is placed in the remainder with probability
    scaled by the zone density. Building height scales with density (downtown
    rises, suburbs stay low). Deterministic from ``seed`` + zone id.

    When ``roads`` (the projected road polylines, ``[{"class", "points"}, ...]``)
    is supplied, any footprint that would overlap a road corridor is first shrunk
    toward its parcel centre and, if it still clips, dropped — so procedurally
    generated buildings never sit on a street even though the real footprint map
    isn't known.
    """
    roads = roads or []
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
        # Roads that could cross this zone (pad by the widest corridor).
        corridors = _zone_corridors(z, roads, pad=12.0) if roads else []
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
                hx, hz = bw * 0.5, bh * 0.5
                # Keep footprints off the streets: if this box clips a road
                # corridor, shrink it toward the parcel centre a couple of times
                # before giving up on the parcel entirely.
                if corridors:
                    tries = 0
                    while _on_street(pcx, pcz, hx, hz, corridors) and tries < 3:
                        hx *= 0.6
                        hz *= 0.6
                        tries += 1
                    if _on_street(pcx, pcz, hx, hz, corridors):
                        continue
                    if hx < 2.0 or hz < 2.0:
                        continue          # shrank to a nub — skip
                # Height: 1 storey (suburb) up to ~10 (downtown), density-driven.
                levels = 1 + int(round(density * 9.0 * (0.5 + rng.random())))
                height = round(levels * storey_m, 2)
                poly = [[pcx - hx, pcz - hz], [pcx + hx, pcz - hz],
                        [pcx + hx, pcz + hz], [pcx - hx, pcz + hz]]
                out.append({"poly": poly, "height": height})
    return {"version": SCHEMA_VERSION, "source": "procedural",
            "storey_m": storey_m, "buildings": out}

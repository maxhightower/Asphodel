"""OW-MVP-2: street cross-section and street-furniture compiler.

Turns normalized road/connector `schema.Feature`s into `records.RoadSegment`
rows (geometry + deterministic cross-section), the `SurfacePatch` polygons
that paint them into the semantic raster (see `surfaces.py`), and the
PROCEDURAL props/anchors scattered along them.

Authority boundary: carriageway width/lane count/sidewalk presence are
DERIVED from `grammar_tables.ROAD_CLASS_PARAMS` unless the source feature
carries an observed measurement (`width_m`, `lanes_total`) within a sane
range, in which case the observed value wins and `observed_width` records
that provenance. Everything placed by `street_props` (streetlights, poles,
hydrants, signals/signs, anchors) is PROCEDURAL: positions are derived only
from segment geometry plus `DetRand` streams keyed on the segment's stable
key, never from iteration order or a global RNG, so re-running the compiler
over the same input reproduces the same world.
"""
from __future__ import annotations

import math

from shapely.strtree import STRtree

from . import geomutil, grammar_tables
from .detrand import DetRand
from .records import Anchor, Placement, RoadSegment

_PATH_CLASSES = {"footway", "cycleway", "path", "steps", "track",
                 "pedestrian", "bridleway"}

_LIGHT_CLASSES = {
    "primary", "secondary", "tertiary", "residential", "unclassified",
    "living_street", "trunk", "motorway",
}
_POLE_CLASSES = {"residential", "unclassified", "tertiary"}
_HYDRANT_CLASSES = {"residential", "tertiary", "secondary"}
_MAJOR_CLASSES = {"primary", "secondary", "trunk"}

_MAX_SIGNALS = 500
_MAX_SIGNS = 2000


def compile_streets(road_features: list, seed: int) -> list:
    """Build RoadSegment rows from normalized road Features.

    `seed` is accepted for interface symmetry with the other compile_*
    stages (and so a future revision can key geometry-adjacent decisions on
    it); this stage's cross-section derivation is otherwise a pure table
    lookup and carries no randomness of its own.
    """
    segments: list[RoadSegment] = []
    for f in road_features:
        if f.geom_type != "line":
            continue
        pts = f.geometry
        if not pts or len(pts) < 2:
            continue
        props = f.properties or {}
        raw_cls = props.get("class")
        cls = raw_cls.strip().lower() if isinstance(raw_cls, str) and raw_cls else "unknown"
        subtype = props.get("subtype")
        if subtype and subtype != "road" and cls not in _PATH_CLASSES:
            # Non-carriageway subtype (e.g. a parking aisle or driveway
            # tagged on the roads layer) that isn't itself a pedestrian/
            # cycle way -- not a street for this compiler's purposes.
            continue

        table = grammar_tables.road_params_for(
            cls if cls not in _PATH_CLASSES else "footway")

        if cls in _PATH_CLASSES or not table["carriageway"]:
            segments.append(RoadSegment(
                key=f.stable_key, pts=list(pts), cls=cls,
                carriage_w=2.0, lanes=0, sidewalk_w=0.0,
                verge_w=table["verge_width_m"], curb=table["curb"],
                markings="none", elevated=False, path_only=True,
                observed_width=False,
            ))
            continue

        lanes = table["lanes"]
        lanes_total = props.get("lanes_total")
        if isinstance(lanes_total, (int, float)) and 1 <= lanes_total <= 10:
            lanes = int(lanes_total)

        width_m = props.get("width_m")
        observed_width = False
        if isinstance(width_m, (int, float)) and 2.0 <= width_m <= 60.0:
            carriage_w = float(width_m)
            observed_width = True
        else:
            carriage_w = lanes * table["lane_width_m"]

        segments.append(RoadSegment(
            key=f.stable_key, pts=list(pts), cls=cls,
            carriage_w=carriage_w, lanes=lanes,
            sidewalk_w=table["sidewalk_width_m"], verge_w=table["verge_width_m"],
            curb=table["curb"], markings=table["markings"],
            elevated=cls in ("motorway", "trunk"), path_only=False,
            observed_width=observed_width,
        ))
    return segments


def street_surface_patches(segments: list) -> list:
    """Carriageway/sidewalk/verge SurfacePatch bands for each segment."""
    from .records import SurfacePatch

    patches: list[SurfacePatch] = []
    for seg in segments:
        line = geomutil.LineString(seg.pts)
        if seg.path_only:
            path_band = line.buffer(1.0, cap_style="flat", join_style="round")
            if not path_band.is_empty and path_band.area > 0:
                patches.append(SurfacePatch(poly=path_band, surface="SIDEWALK", priority=64))
            continue

        carriageway = line.buffer(seg.carriage_w / 2.0, cap_style="flat", join_style="round")
        if not carriageway.is_empty and carriageway.area > 0:
            # Elevated (motorway/trunk) decks still paint a ROAD corridor at
            # ground level for MVP -- the deck mesh renders above it, but the
            # ground underneath reading as "road corridor" rather than bare
            # terrain is the accepted placeholder per the design doc.
            patches.append(SurfacePatch(poly=carriageway, surface="ROAD", priority=70))

        if seg.sidewalk_w > 0:
            inner = line.buffer(seg.carriage_w / 2.0 + seg.verge_w,
                                 cap_style="flat", join_style="round")
            outer = line.buffer(seg.carriage_w / 2.0 + seg.verge_w + seg.sidewalk_w,
                                 cap_style="flat", join_style="round")
            band = outer.difference(inner)
            if not band.is_empty and band.area > 0:
                patches.append(SurfacePatch(poly=band, surface="SIDEWALK", priority=65))

        if seg.verge_w > 0:
            verge_outer = line.buffer(seg.carriage_w / 2.0 + seg.verge_w,
                                       cap_style="flat", join_style="round")
            band = verge_outer.difference(carriageway)
            if not band.is_empty and band.area > 0:
                patches.append(SurfacePatch(poly=band, surface="MAINTAINED_GRASS", priority=60))

    return patches


def _perp(heading_deg: float, side: int) -> tuple:
    """Unit vector perpendicular to a polyline heading, offset by `side`.

    `heading_deg` follows geomutil.point_along_polyline's convention
    (atan2(dx, dz) in degrees, i.e. 0 = north/+z). `side` is +1 or -1.
    """
    hd = math.radians(heading_deg)
    return (math.cos(hd) * side, -math.sin(hd) * side)


def _walk(pts: list, spacing: float, length: float | None = None):
    """Yield (x, z, heading_deg) at `spacing` intervals, offset by half-step."""
    if length is None:
        length = geomutil.polyline_length(pts)
    if length <= 0 or spacing <= 0:
        return
    d = spacing / 2.0
    while d < length:
        x, z, hd = geomutil.point_along_polyline(pts, d)
        yield (x, z, hd)
        d += spacing


def street_props(segments: list, connector_features: list, seed: int) -> tuple:
    """Scatter street furniture and anchors along carriageway segments.

    Every scatter decision is keyed `DetRand(seed, segment.key, purpose)` --
    never on list index -- so the result is identical regardless of feature
    ordering. Traffic signals/signs are additionally capped and processed in
    stable_key order over `connector_features` so a re-run with the same
    inputs always keeps the same first-N when a cap is hit.
    """
    placements: list[Placement] = []
    anchors: list[Anchor] = []

    road_lines = []
    road_meta = []
    for seg in segments:
        if seg.path_only or len(seg.pts) < 2:
            continue
        road_lines.append(geomutil.LineString(seg.pts))
        road_meta.append(seg)

        length = geomutil.polyline_length(seg.pts)
        if length <= 0:
            continue

        if seg.cls in _LIGHT_CLASSES:
            jitter = DetRand(seed, seg.key, "lights").uniform(0.8, 1.2)
            spacing = 40.0 * jitter
            for i, (x, z, hd) in enumerate(_walk(seg.pts, spacing, length)):
                side = 1 if i % 2 == 0 else -1
                nx, nz = _perp(hd, side)
                off = seg.carriage_w / 2.0 + 0.8
                rot = (hd + 90.0 * side) % 360.0
                placements.append(Placement(
                    kind="streetlight", x=x + nx * off, z=z + nz * off,
                    rot=rot, cat="prop",
                ))

        if seg.cls in _POLE_CLASSES:
            side = 1 if DetRand(seed, seg.key, "poles_side").chance(0.5) else -1
            for x, z, hd in _walk(seg.pts, 55.0, length):
                nx, nz = _perp(hd, side)
                off = seg.carriage_w / 2.0 + seg.sidewalk_w + 0.5
                placements.append(Placement(
                    kind="utility_pole", x=x + nx * off, z=z + nz * off,
                    rot=hd, cat="prop",
                ))

        if seg.cls in _HYDRANT_CLASSES:
            side = 1 if DetRand(seed, seg.key, "hydrants_side").chance(0.5) else -1
            for x, z, hd in _walk(seg.pts, 150.0, length):
                nx, nz = _perp(hd, side)
                off = seg.carriage_w / 2.0 + seg.sidewalk_w
                placements.append(Placement(
                    kind="fire_hydrant", x=x + nx * off, z=z + nz * off,
                    rot=hd, cat="prop",
                ))

        if not seg.elevated:
            for x, z, hd in _walk(seg.pts, 60.0, length):
                anchors.append(Anchor(kind="ROAD_ANCHOR", x=x, z=z, bid=-1))
            if seg.sidewalk_w > 0:
                for i, (x, z, hd) in enumerate(_walk(seg.pts, 50.0, length)):
                    side = 1 if i % 2 == 0 else -1
                    nx, nz = _perp(hd, side)
                    off = seg.carriage_w / 2.0 + seg.verge_w + seg.sidewalk_w / 2.0
                    anchors.append(Anchor(
                        kind="SIDEWALK_ANCHOR", x=x + nx * off, z=z + nz * off, bid=-1,
                    ))

    tree = STRtree(road_lines) if road_lines else None
    signal_count = 0
    sign_count = 0
    for cf in sorted(connector_features, key=lambda f: f.stable_key):
        if signal_count >= _MAX_SIGNALS and sign_count >= _MAX_SIGNS:
            break
        if tree is None:
            break
        x, z = cf.geometry[0]
        pt = geomutil.Point(x, z)

        majors, near15 = set(), set()
        has_sec_tert = False
        max_cw_major = 0.0
        max_cw_15 = 0.0
        for ci in tree.query(pt.buffer(20.0)):
            ci = int(ci)
            seg = road_meta[ci]
            d = road_lines[ci].distance(pt)
            if d <= 20.0 and seg.cls in _MAJOR_CLASSES:
                majors.add(seg.key)
                max_cw_major = max(max_cw_major, seg.carriage_w)
            if d <= 15.0:
                near15.add(seg.key)
                max_cw_15 = max(max_cw_15, seg.carriage_w)
                if seg.cls in ("secondary", "tertiary"):
                    has_sec_tert = True

        if len(majors) >= 2 and signal_count < _MAX_SIGNALS:
            off = max_cw_major / 2.0 + 1.0
            placements.append(Placement(kind="traffic_signal", x=x + off, z=z + off,
                                         rot=0.0, cat="prop"))
            placements.append(Placement(kind="traffic_signal", x=x - off, z=z - off,
                                         rot=180.0, cat="prop"))
            signal_count += 2
        elif len(near15) >= 2 and has_sec_tert and sign_count < _MAX_SIGNS:
            off = max_cw_15 / 2.0 + 1.0
            placements.append(Placement(kind="traffic_sign", x=x + off, z=z + off,
                                         rot=0.0, cat="prop"))
            sign_count += 1

    return placements, anchors

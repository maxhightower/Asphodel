"""OW-MVP-4: building footprint -> BuildingRecord compiler.

Consumes identity-ordered building `schema.Feature`s (index == bid, per
`identity.order_buildings`) plus the parcels/road segments already compiled
by `parcels.py` / `streets.py`, and assigns each footprint a physical
archetype, height, roof, entrance, and feature-tag list.

Authority boundary: height/floors/roof are OBSERVED when the source feature
carries them (`height_m`, `levels`, `roof_shape`); otherwise they are
PROCEDURAL, drawn from a `DetRand` stream keyed on the building's stable key
so the same input always yields the same building. The building *archetype*
itself is DERIVED primarily from the parcel's land-use archetype (already
informed by Overture subtype via `parcels._building_parcel_hint`) plus
observed footprint area/height -- this module deliberately does not
re-interpret `subtype` on its own, to keep a single source of archetype
truth in `grammar_tables.building_archetype_for`.
"""
from __future__ import annotations

import math

from shapely.strtree import STRtree

from . import geomutil, grammar_tables
from .detrand import DetRand
from .records import BuildingRecord, SurfacePatch
from . import appearance as appearance_mod

# Deterministic-infer height ranges (metres) per BUILDING_ARCHETYPES, used
# only when a footprint has neither an observed height_m nor a levels count.
_HEIGHT_RANGES = {
    "DETACHED_RESIDENTIAL": (3.5, 6.5),
    "MULTIFAMILY": (6.0, 12.0),
    "SMALL_COMMERCIAL": (4.0, 7.0),
    "BIG_BOX_COMMERCIAL": (6.0, 9.0),
    "INDUSTRIAL": (5.0, 10.0),
    "OFFICE_HIGHRISE": (30.0, 80.0),
    "CIVIC_SPECIAL": (5.0, 12.0),
    "GENERIC_UNKNOWN": (3.5, 8.0),
}

_PITCHED_ROOF_TAGS = {"gabled", "hipped", "pitched"}

_ENTRANCE_W = {
    "DETACHED_RESIDENTIAL": 1.2,
    "SMALL_COMMERCIAL": 2.4,
    "BIG_BOX_COMMERCIAL": 4.0,
}
_DEFAULT_ENTRANCE_W = 1.8


def _entrance_edge(poly, frontage: list, road_tree, road_lines: list) -> int:
    """Index of the exterior-ring edge that best represents the street face.

    Precedence: the parcel's own frontage segments (most specific) -> the
    nearest carriageway road line -> the longest edge, as a degenerate
    fallback when no road context exists at all.
    """
    edges = list(geomutil.ring_edges(poly))

    if frontage:
        flines = [geomutil.LineString(list(seg)) for seg in frontage]
        best_i, best_d = 0, float("inf")
        for i, (p0, p1) in enumerate(edges):
            mx, mz = geomutil.edge_point(p0, p1, 0.5)
            pt = geomutil.Point(mx, mz)
            d = min(fl.distance(pt) for fl in flines)
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    if road_tree is not None:
        best_i, best_d = 0, float("inf")
        for i, (p0, p1) in enumerate(edges):
            mx, mz = geomutil.edge_point(p0, p1, 0.5)
            pt = geomutil.Point(mx, mz)
            idx = road_tree.nearest(pt)
            if idx is None:
                continue
            d = road_lines[int(idx)].distance(pt)
            if d < best_d:
                best_d, best_i = d, i
        return best_i

    best_i, best_len = 0, -1.0
    for i, (p0, p1) in enumerate(edges):
        ln = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if ln > best_len:
            best_len, best_i = ln, i
    return best_i


def compile_buildings(ordered_features: list, parcels: list, segments: list,
                       seed: int) -> list:
    bid_to_parcel = {}
    for p in parcels:
        for bid in p.building_bids:
            bid_to_parcel[bid] = p

    road_lines = [geomutil.LineString(s.pts) for s in segments
                  if not s.path_only and len(s.pts) >= 2]
    road_tree = STRtree(road_lines) if road_lines else None

    records: list[BuildingRecord] = []
    for bid, f in enumerate(ordered_features):
        poly = geomutil.sanitize_polygon(f.geometry)
        assert poly is not None, f"building {f.stable_key} has no valid geometry"

        props = f.properties or {}
        parcel = bid_to_parcel.get(bid)
        parcel_arch = parcel.arch if parcel is not None else "UNKNOWN"
        area = float(props.get("_area", poly.area))

        height_m = props.get("height_m")
        levels = props.get("levels")
        rng_h = DetRand(seed, f.stable_key, "height")

        if isinstance(height_m, (int, float)) and height_m > 0:
            h = float(height_m)
            height_observed = True
            arch = grammar_tables.building_archetype_for(parcel_arch, area, h)
        elif isinstance(levels, (int, float)) and levels > 0:
            h = float(levels) * 3.3
            height_observed = False
            arch = grammar_tables.building_archetype_for(parcel_arch, area, h)
        else:
            provisional_h = rng_h.uniform(4.0, 8.0)
            arch = grammar_tables.building_archetype_for(parcel_arch, area, provisional_h)
            lo, hi = _HEIGHT_RANGES[arch]
            h = rng_h.uniform(lo, hi)
            height_observed = False

        if isinstance(levels, (int, float)) and levels > 0:
            floors = max(1, round(levels))
        elif arch in ("BIG_BOX_COMMERCIAL", "INDUSTRIAL"):
            floors = 1
        else:
            floors = max(1, round(h / 3.3))

        roof_shape = (props.get("roof_shape") or "").strip().lower()
        if roof_shape in _PITCHED_ROOF_TAGS:
            roof = "pitched"
        elif roof_shape == "flat":
            roof = "flat"
        else:
            rng_roof = DetRand(seed, f.stable_key, "roof")
            if arch == "DETACHED_RESIDENTIAL":
                roof = "pitched" if rng_roof.chance(0.9) else "flat"
            elif arch == "MULTIFAMILY":
                roof = "pitched" if rng_roof.chance(0.4) else "flat"
            else:
                roof = "flat"

        frontage = parcel.frontage if parcel is not None else []
        entrance_edge = _entrance_edge(poly, frontage, road_tree, road_lines)
        p0, p1 = list(geomutil.ring_edges(poly))[entrance_edge]
        mx, mz = geomutil.edge_point(p0, p1, 0.5)
        nx, nz = geomutil.edge_outward_normal(poly, p0, p1)
        ex, ez = mx + nx * 1.5, mz + nz * 1.5
        if poly.contains(geomutil.Point(ex, ez)):
            nx, nz = -nx, -nz
            ex, ez = mx + nx * 1.5, mz + nz * 1.5
        entrance_w = _ENTRANCE_W.get(arch, _DEFAULT_ENTRANCE_W)

        rng_feat = DetRand(seed, f.stable_key, "feat")
        feat: list = []
        if arch == "DETACHED_RESIDENTIAL":
            if rng_feat.chance(0.45):
                feat.append("garage")
            if rng_feat.chance(0.35):
                feat.append("porch")
        elif arch == "MULTIFAMILY":
            if rng_feat.chance(0.5):
                feat.append("balconies")
            feat.append("lobby")
        elif arch == "SMALL_COMMERCIAL":
            feat += ["storefront", "sign_band"]
        elif arch == "BIG_BOX_COMMERCIAL":
            feat += ["storefront", "loading_dock", "rooftop_hvac", "parapet"]
        elif arch == "INDUSTRIAL":
            feat += ["loading_dock", "rooftop_hvac"]
        elif arch == "OFFICE_HIGHRISE":
            feat += ["lobby", "parapet", "rooftop_hvac"]
        elif arch == "CIVIC_SPECIAL":
            feat += ["lobby"]

        # Package B: assemble appearance truth (observed where the source
        # supplies it; roof shape observed or DERIVED; height provenance).
        appearance = appearance_mod.build_appearance(
            bid, props, roof, h, height_observed).to_dict()

        records.append(BuildingRecord(
            bid=bid, key=f.stable_key, poly=poly, h=h, floors=floors,
            arch=arch, roof=roof, entrance_edge=entrance_edge,
            entrance_t=0.5, entrance_w=entrance_w, entrance_xy=(ex, ez),
            feat=feat, parcel_id=(parcel.pid if parcel is not None else None),
            height_observed=height_observed, appearance=appearance,
        ))

    return records


def building_surface_patches(records: list) -> list:
    return [SurfacePatch(poly=r.poly, surface="BUILDING", priority=90) for r in records]

"""Overture GeoParquet -> WorldSourceV1 normalization.

Reads the cached raw parquet packet (data/raw/overture/<release>/<city>/)
and produces the versioned normalized representation the compiler consumes
(schema.WorldSourceV1).  Only the fields Asphodel needs are lifted; the
projection is the exact frame the committed bundles already use
(osm_city.geometry.project: equirectangular about the bbox centre,
x=east, z=north metres).

Multipolygons are exploded into one Feature per part (suffix "#<i>") so
every polygon Feature is a simple ring list.  Every Feature carries its
source id (Overture GERS) as the stable key — the foundation of stable
building identity (identity.py).
"""
from __future__ import annotations

import os

import pyarrow.parquet as pq
import shapely
from shapely.geometry import Polygon

from ..osm_city.geometry import project
from .bbox import city_bbox
from .schema import Feature, WorldSourceV1

# Overture segment classes that are carriageway roads.
ROAD_CLASSES = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "residential",
    "unclassified", "living_street", "service", "unknown",
}
PATH_CLASSES = {"footway", "cycleway", "path", "steps", "track", "pedestrian",
                "bridleway"}

_LAYER_FILES = {
    "roads": "segment",
    "connectors": "connector",
    "buildings": "building",
    "building_parts": "building_part",
    "water": "water",
    "land": "land",
    "land_use": "land_use",
    "land_cover": "land_cover",
    "infrastructure": "infrastructure",
    "places": "place",
}


def _table(data_root, release, city, name):
    path = os.path.join(data_root, "overture", release, city, f"{name}.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"missing raw packet {path}; run `python -m asphodel.world_source "
            f"acquire --city {city}` first")
    return pq.read_table(path)


def _col(tbl, name):
    return tbl.column(name).to_pylist() if name in tbl.column_names else [None] * len(tbl)


def _project_ring(ring, lat0, lon0):
    # WKB is (lon, lat); project() takes (lat, lon).
    return [project(lat, lon, lat0, lon0) for lon, lat in ring]


def _polygon_features(geoms, ids, props_list, source, lat0, lon0, lic):
    feats = []
    for gid, geom, props in zip(ids, geoms, props_list):
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for pi, part in enumerate(parts):
            if part.geom_type != "Polygon" or part.exterior is None:
                continue
            rings = [_project_ring(part.exterior.coords, lat0, lon0)]
            for hole in part.interiors:
                rings.append(_project_ring(hole.coords, lat0, lon0))
            if len(rings[0]) < 4:
                continue
            key = gid if len(parts) == 1 else f"{gid}#{pi}"
            feats.append(Feature(
                stable_key=key, geometry=rings, geom_type="polygon",
                properties=dict(props), source=source, source_id=gid,
                license_family=lic,
            ))
    return feats


def _first_rule_value(rules):
    """Overture *_rules: list of {value, between}; take the whole-span rule."""
    if not rules:
        return None
    for r in rules:
        if r and r.get("between") is None:
            return r.get("value")
    return rules[0].get("value") if rules[0] else None


def _oneway_from_access(rules):
    """Read a one-way rule out of Overture ``access_restrictions``.

    Overture encodes a one-way street as a whole-span ``access_type='denied'``
    restriction scoped to a heading: denying the *backward* heading means the
    carriageway is legal only *forward* along its linestring, and vice versa.
    Returns ``None`` (two-way) unless such a rule is present.

    Authority note: this is a pure read of the source packet — the routing
    consequence lives in the mobility bake, not here.
    """
    if not rules:
        return None
    for r in rules:
        if not r or r.get("access_type") != "denied":
            continue
        if r.get("between") is not None:
            continue                      # partial-span rule: not a one-way
        heading = (r.get("when") or {}).get("heading")
        if heading == "backward":
            return "forward"
        if heading == "forward":
            return "backward"
    return None


def _road_features(tbl, lat0, lon0, src):
    """Normalize the transportation/segment table into road line Features."""
    geoms = shapely.from_wkb(tbl.column("geometry").to_pylist())
    subtypes = _col(tbl, "subtype")
    classes = _col(tbl, "class")
    widths = _col(tbl, "width_rules")
    conns = _col(tbl, "connectors")
    access = _col(tbl, "access_restrictions")
    ids = _col(tbl, "id")
    feats = []
    for gid, geom, sub, cls, wr, cl, ar in zip(
            ids, geoms, subtypes, classes, widths, conns, access):
        if geom is None or geom.geom_type != "LineString":
            continue
        cls = (cls or "unknown").lower()
        if sub == "rail" or sub == "water":
            continue
        if cls not in ROAD_CLASSES and cls not in PATH_CLASSES:
            continue
        pts = _project_ring(geom.coords, lat0, lon0)
        if len(pts) < 2:
            continue
        # Graph topology carried alongside the geometry: the connector GERS
        # ids this segment touches and the fraction along it where each sits.
        # The exterior compiler ignores both; the mobility bake splits on them.
        connectors = sorted(
            ([c["connector_id"], float(c["at"])] for c in (cl or [])
             if c and c.get("connector_id") is not None and c.get("at") is not None),
            key=lambda ca: (ca[1], ca[0]))
        feats.append(Feature(
            stable_key=gid, geometry=pts, geom_type="line",
            properties={
                "class": cls,
                "subtype": sub,
                "width_m": _first_rule_value(wr),
                "lanes_total": None,
                "connectors": connectors,
                "oneway": _oneway_from_access(ar),
            },
            source=f"{src}/transportation/segment", source_id=gid,
        ))
    return feats


def _connector_features(tbl, lat0, lon0, src):
    """Normalize the transportation/connector table into point Features."""
    geoms = shapely.from_wkb(tbl.column("geometry").to_pylist())
    feats = []
    for gid, geom in zip(_col(tbl, "id"), geoms):
        if geom is None or geom.geom_type != "Point":
            continue
        x, z = project(geom.y, geom.x, lat0, lon0)
        feats.append(Feature(
            stable_key=gid, geometry=[(x, z)], geom_type="point",
            properties={}, source=f"{src}/transportation/connector",
            source_id=gid,
        ))
    return feats


def _frame(city: str, release: str):
    """The bundle metre frame + meta block shared by every loader here."""
    w, s, e, n = city_bbox(city)
    lat0 = (s + n) / 2.0
    lon0 = (w + e) / 2.0
    min_x, min_z = project(s, w, lat0, lon0)
    max_x, max_z = project(n, e, lat0, lon0)
    meta = {
        "city": city,
        "release": release,
        "bbox": [w, s, e, n],
        "origin": [lat0, lon0],
        "bounds_m": (min_x, min_z, max_x, max_z),
    }
    return lat0, lon0, meta, (min_x, min_z, max_x, max_z)


def load_world_source_roads(city: str, release: str,
                            data_root: str = "data/raw") -> WorldSourceV1:
    """Load ONLY the transportation layers (segment + connector).

    The mobility bake needs the street network and nothing else; loading the
    full world source would pull in buildings/land/places (hundreds of MB of
    parquet) for no benefit. The returned WorldSourceV1 carries the same
    ``meta``/``roads``/``connectors`` this module's full loader produces, in
    the same bundle metre frame, so the bake cannot drift from the compiler.
    """
    lat0, lon0, meta, _ = _frame(city, release)
    ws = WorldSourceV1()
    ws.meta = meta
    src = f"overture@{release}"
    ws.roads = _road_features(
        _table(data_root, release, city, "segment"), lat0, lon0, src)
    ws.connectors = _connector_features(
        _table(data_root, release, city, "connector"), lat0, lon0, src)
    return ws


def load_world_source(city: str, release: str,
                      data_root: str = "data/raw") -> WorldSourceV1:
    lat0, lon0, meta, bounds = _frame(city, release)
    min_x, min_z, max_x, max_z = bounds

    ws = WorldSourceV1()
    ws.meta = meta

    src = f"overture@{release}"

    # ---- roads / paths -------------------------------------------------
    ws.roads = _road_features(
        _table(data_root, release, city, "segment"), lat0, lon0, src)
    ws.connectors = _connector_features(
        _table(data_root, release, city, "connector"), lat0, lon0, src)

    # ---- buildings -----------------------------------------------------
    tbl = _table(data_root, release, city, "building")
    geoms = shapely.from_wkb(tbl.column("geometry").to_pylist())
    heights = _col(tbl, "height")
    floors = _col(tbl, "num_floors")
    subtypes = _col(tbl, "subtype")
    classes = _col(tbl, "class")
    roofs = _col(tbl, "roof_shape")
    # Package B: appearance-bearing columns (facade/roof colour + material).
    # Coverage is ~0% for the cert cities (VIS-0) but preserved end-to-end with
    # provenance so the rare observed values survive and future data generalizes.
    facade_colors = _col(tbl, "facade_color")
    facade_materials = _col(tbl, "facade_material")
    roof_colors = _col(tbl, "roof_color")
    roof_materials = _col(tbl, "roof_material")
    ids = _col(tbl, "id")
    for idx, (gid, geom, h, fl, sub, cls, roof) in enumerate(zip(
            ids, geoms, heights, floors, subtypes, classes, roofs)):
        if geom is None or geom.is_empty:
            continue
        parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for pi, part in enumerate(parts):
            if part.geom_type != "Polygon":
                continue
            rings = [_project_ring(part.exterior.coords, lat0, lon0)]
            for hole in part.interiors:
                rings.append(_project_ring(hole.coords, lat0, lon0))
            if len(rings[0]) < 4:
                continue
            poly = Polygon(rings[0])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty or poly.area < 4.0:
                continue  # sub-4m2 slivers carry no gameplay meaning
            c = poly.centroid
            key = gid if len(parts) == 1 else f"{gid}#{pi}"
            ws.buildings.append(Feature(
                stable_key=key, geometry=rings, geom_type="polygon",
                properties={
                    "height_m": float(h) if h is not None else None,
                    "levels": int(fl) if fl is not None else None,
                    "subtype": sub, "class": cls, "roof_shape": roof,
                    "facade_color": facade_colors[idx],
                    "facade_material": facade_materials[idx],
                    "roof_color": roof_colors[idx],
                    "roof_material": roof_materials[idx],
                    "_centroid": (c.x, c.y),
                    "_area": poly.area,
                },
                source=f"{src}/buildings/building", source_id=gid,
            ))

    # ---- base polygons -------------------------------------------------
    for layer, fname in (("water", "water"), ("land", "land"),
                         ("land_use", "land_use"),
                         ("land_cover", "land_cover"),
                         ("infrastructure", "infrastructure")):
        tbl = _table(data_root, release, city, fname)
        geoms = shapely.from_wkb(tbl.column("geometry").to_pylist())
        subtypes = _col(tbl, "subtype")
        classes = _col(tbl, "class")
        ids = _col(tbl, "id")
        polys, pids, plist = [], [], []
        for gid, geom, sub, cls in zip(ids, geoms, subtypes, classes):
            if geom is None or geom.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            polys.append(geom)
            pids.append(gid)
            plist.append({"class": (cls or sub or ""), "subtype": sub})
        getattr(ws, layer).extend(_polygon_features(
            polys, pids, plist, f"{src}/base/{fname}", lat0, lon0, "ODBL"))

    # ---- places --------------------------------------------------------
    tbl = _table(data_root, release, city, "place")
    geoms = shapely.from_wkb(tbl.column("geometry").to_pylist())
    cats = _col(tbl, "categories")
    confs = _col(tbl, "confidence")
    for gid, geom, cat, conf in zip(_col(tbl, "id"), geoms, cats, confs):
        if geom is None or geom.geom_type != "Point":
            continue
        x, z = project(geom.y, geom.x, lat0, lon0)
        if not (min_x - 100 <= x <= max_x + 100 and min_z - 100 <= z <= max_z + 100):
            continue
        primary = (cat or {}).get("primary") if isinstance(cat, dict) else None
        ws.places.append(Feature(
            stable_key=gid, geometry=[(x, z)], geom_type="point",
            properties={"category": primary or "",
                        "confidence": float(conf) if conf is not None else 0.5},
            source=f"{src}/places/place", source_id=gid,
            confidence=float(conf) if conf is not None else 0.5,
            license_family="PERMISSIVE",
        ))

    return ws

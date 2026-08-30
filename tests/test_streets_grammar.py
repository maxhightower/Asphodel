"""Tests for OW-MVP-2 (streets.py) and OW-MVP-4 (buildings_grammar.py).

Synthetic fixtures only -- no real city data touches this test.
"""
from __future__ import annotations

import math

from shapely.geometry import Point

from asphodel.world_source import buildings_grammar, identity, parcels, streets, surfaces
from asphodel.world_source.chunkgrid import ChunkGrid
from asphodel.world_source.schema import Feature

SEED = 1234


def _square(cx: float, cz: float, area: float) -> list:
    half = math.sqrt(area) / 2.0
    return [
        (cx - half, cz - half), (cx + half, cz - half),
        (cx + half, cz + half), (cx - half, cz + half),
        (cx - half, cz - half),
    ]


def _road_features():
    primary = Feature(
        stable_key="r:primary", geometry=[(-200.0, 0.0), (200.0, 0.0)],
        geom_type="line", properties={"class": "primary"},
        source="test", source_id=None,
    )
    residential = Feature(
        stable_key="r:residential", geometry=[(0.0, -200.0), (0.0, 200.0)],
        geom_type="line", properties={"class": "residential"},
        source="test", source_id=None,
    )
    return [primary, residential]


def _connector_features():
    return [Feature(
        stable_key="c:0", geometry=[(0.0, 0.0)], geom_type="point",
        properties={}, source="test", source_id=None,
    )]


def _building_features():
    house = Feature(
        stable_key="b:house", geometry=[_square(50.0, 60.0, 100.0)],
        geom_type="polygon",
        properties={"_centroid": (50.0, 60.0), "_area": 100.0, "subtype": "residential"},
        source="test", source_id=None,
    )
    bigbox = Feature(
        stable_key="b:bigbox", geometry=[_square(-80.0, -80.0, 3000.0)],
        geom_type="polygon",
        properties={"_centroid": (-80.0, -80.0), "_area": 3000.0},
        source="test", source_id=None,
    )
    office = Feature(
        stable_key="b:office", geometry=[_square(120.0, -100.0, 900.0)],
        geom_type="polygon",
        properties={"_centroid": (120.0, -100.0), "_area": 900.0, "height_m": 60.0},
        source="test", source_id=None,
    )
    noattr = Feature(
        stable_key="b:noattr", geometry=[_square(-50.0, 70.0, 200.0)],
        geom_type="polygon",
        properties={"_centroid": (-50.0, 70.0), "_area": 200.0},
        source="test", source_id=None,
    )
    return [house, bigbox, office, noattr]


def _compiled_world():
    road_features = _road_features()
    segments = streets.compile_streets(road_features, SEED)

    ordered = identity.order_buildings(_building_features())
    building_dicts = []
    from asphodel.world_source import geomutil
    for bid, f in enumerate(ordered):
        poly = geomutil.sanitize_polygon(f.geometry)
        building_dicts.append({"bid": bid, "key": f.stable_key, "poly": poly,
                                "props": f.properties})

    bounds = (-256.0, -256.0, 256.0, 256.0)
    blocks, parcel_list = parcels.compile_parcels(
        segments, building_dicts, [], [], bounds,
    )
    return segments, ordered, parcel_list


# ---------------------------------------------------------------------------
# compile_streets
# ---------------------------------------------------------------------------

def test_compile_streets_widths():
    segments = streets.compile_streets(_road_features(), SEED)
    by_cls = {s.cls: s for s in segments}
    assert by_cls["primary"].carriage_w == 14.0  # 4 lanes * 3.5 m
    assert by_cls["primary"].lanes == 4
    assert by_cls["residential"].carriage_w == 6.0  # 2 lanes * 3.0 m
    assert by_cls["residential"].lanes == 2
    for s in segments:
        assert not s.path_only
        assert not s.observed_width


def test_compile_streets_skips_short_and_non_road_subtype():
    too_short = Feature(
        stable_key="r:short", geometry=[(0.0, 0.0)], geom_type="line",
        properties={"class": "residential"}, source="test", source_id=None,
    )
    parking_aisle = Feature(
        stable_key="r:aisle", geometry=[(1.0, 1.0), (2.0, 2.0)], geom_type="line",
        properties={"class": "residential", "subtype": "parking_aisle"},
        source="test", source_id=None,
    )
    footway = Feature(
        stable_key="r:fw", geometry=[(1.0, 1.0), (5.0, 1.0)], geom_type="line",
        properties={"class": "footway", "subtype": "sidewalk"},
        source="test", source_id=None,
    )
    segments = streets.compile_streets([too_short, parking_aisle, footway], SEED)
    keys = {s.key for s in segments}
    assert "r:short" not in keys
    assert "r:aisle" not in keys
    assert "r:fw" in keys
    fw = next(s for s in segments if s.key == "r:fw")
    assert fw.path_only


# ---------------------------------------------------------------------------
# street_surface_patches
# ---------------------------------------------------------------------------

def test_street_surface_patches():
    segments = streets.compile_streets(_road_features(), SEED)
    patches = streets.street_surface_patches(segments)

    road_patches = [p for p in patches if p.surface == "ROAD"]
    assert road_patches
    assert any(p.poly.contains(Point(10.0, 0.5)) for p in road_patches)

    sidewalk_patches = [p for p in patches if p.surface == "SIDEWALK"]
    assert sidewalk_patches

    for p in patches:
        assert not p.poly.is_empty


# ---------------------------------------------------------------------------
# street_props: determinism + placement sanity
# ---------------------------------------------------------------------------

def test_street_props_deterministic_and_sane():
    segments = streets.compile_streets(_road_features(), SEED)
    connectors = _connector_features()

    placements1, anchors1 = streets.street_props(segments, connectors, SEED)
    placements2, anchors2 = streets.street_props(segments, connectors, SEED)
    assert placements1 == placements2
    assert anchors1 == anchors2

    lights = [p for p in placements1 if p.kind == "streetlight"]
    assert lights
    primary_lights = [p for p in lights if -200.0 <= p.x <= 200.0 and abs(p.z) < 20.0]
    assert primary_lights

    primary = next(s for s in segments if s.cls == "primary")
    residential = next(s for s in segments if s.cls == "residential")

    road_anchors = [a for a in anchors1 if a.kind == "ROAD_ANCHOR"]
    assert road_anchors

    primary_anchors = sorted(
        (a.x for a in road_anchors if abs(a.z) < 1e-6 and -200.0 <= a.x <= 200.0)
    )
    assert len(primary_anchors) >= 2
    for a, b in zip(primary_anchors, primary_anchors[1:]):
        assert b - a <= 80.0

    for a in road_anchors:
        if abs(a.z) < 1e-6:  # on the primary centerline
            assert abs(a.z) < primary.carriage_w / 2.0
        elif abs(a.x) < 1e-6:  # on the residential centerline
            assert abs(a.x) < residential.carriage_w / 2.0


# ---------------------------------------------------------------------------
# compile_buildings
# ---------------------------------------------------------------------------

def test_compile_buildings_archetypes_and_geometry():
    segments, ordered, parcel_list = _compiled_world()
    records = buildings_grammar.compile_buildings(ordered, parcel_list, segments, SEED)

    assert len(records) == 4
    for i, rec in enumerate(records):
        assert rec.bid == i

    by_key = {r.key: r for r in records}

    house = by_key["b:house"]
    assert house.arch == "DETACHED_RESIDENTIAL"
    assert house.roof == "pitched"

    office = by_key["b:office"]
    assert office.arch == "OFFICE_HIGHRISE"
    assert office.roof == "flat"
    assert office.height_observed
    assert office.h == 60.0

    bigbox = by_key["b:bigbox"]
    assert bigbox.arch in ("BIG_BOX_COMMERCIAL", "GENERIC_UNKNOWN")

    for rec in records:
        assert not rec.poly.contains(Point(*rec.entrance_xy))
        assert 0.0 <= rec.entrance_t <= 1.0
        assert rec.floors >= 1


def test_compile_buildings_deterministic():
    segments, ordered, parcel_list = _compiled_world()
    r1 = buildings_grammar.compile_buildings(ordered, parcel_list, segments, SEED)
    r2 = buildings_grammar.compile_buildings(ordered, parcel_list, segments, SEED)

    def _key(r):
        return (r.bid, r.key, r.h, r.floors, r.arch, r.roof, r.entrance_edge,
                r.entrance_t, r.entrance_w, r.entrance_xy, tuple(r.feat),
                r.parcel_id, r.height_observed)

    assert [_key(r) for r in r1] == [_key(r) for r in r2]


def test_building_surface_patches_paint_footprint():
    segments, ordered, parcel_list = _compiled_world()
    records = buildings_grammar.compile_buildings(ordered, parcel_list, segments, SEED)
    patches = buildings_grammar.building_surface_patches(records)
    assert all(p.surface == "BUILDING" and p.priority == 90 for p in patches)

    grid = ChunkGrid(-256.0, -256.0, 256.0, 256.0)
    rasters = surfaces.paint_surfaces(grid, patches)

    house = next(r for r in records if r.key == "b:house")
    hx, hz = house.poly.centroid.x, house.poly.centroid.y
    cx, cz = grid.chunk_of(hx, hz)
    ox, oz = grid.chunk_origin(cx, cz)
    col = int((hx - ox) / 2.0)
    row = int((hz - oz) / 2.0)
    idx = row * 128 + col
    assert rasters[(cx, cz)][idx] == surfaces.surface_index("BUILDING")

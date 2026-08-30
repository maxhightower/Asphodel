"""Tests for OW-MVP-5,6,7,8,9: the parcel-detail exterior compiler stage.

Builds a small synthetic fixture directly from records.py + parcels.py
(compile_parcels), independent of any streets-grammar or building-generator
module that may be under concurrent development elsewhere in this repo.
"""
from __future__ import annotations

from shapely.geometry import Point, box

from asphodel.world_source.detail import (
    DetailResult,
    compile_detail,
    curb_vehicles,
    entrance_anchors,
)
from asphodel.world_source.parcels import compile_parcels
from asphodel.world_source.records import BuildingRecord, RoadSegment

BOUNDS = (-256.0, -256.0, 256.0, 256.0)

_HOUSE_POLY = box(4, 55, 16, 65)          # 12x10, east side of NS road
_RETAIL_POLY = box(-110, -40, -70, -10)   # 40x30, south of EW road
_INDUSTRIAL_POLY = box(-20, 55, -4, 75)   # 16x20, north side of NS road


def _roads():
    return [
        RoadSegment(
            key="ew", pts=[(-256.0, 0.0), (256.0, 0.0)], cls="primary",
            carriage_w=14.0, lanes=4, sidewalk_w=1.8, verge_w=1.5,
            curb=True, markings="solid_lanes",
        ),
        RoadSegment(
            key="ns", pts=[(0.0, -256.0), (0.0, 256.0)], cls="residential",
            carriage_w=6.0, lanes=2, sidewalk_w=1.5, verge_w=2.0,
            curb=True, markings="dashed_center",
        ),
    ]


def _building_dicts():
    return [
        {"bid": 0, "key": "house", "poly": _HOUSE_POLY,
         "props": {"subtype": "residential"}},
        {"bid": 1, "key": "retail", "poly": _RETAIL_POLY,
         "props": {"subtype": "commercial"}},
        {"bid": 2, "key": "industrial", "poly": _INDUSTRIAL_POLY,
         "props": {"subtype": "industrial"}},
    ]


def _building_records():
    return [
        BuildingRecord(
            bid=0, key="house", poly=_HOUSE_POLY, h=6.0, floors=1,
            arch="DETACHED_RESIDENTIAL", roof="pitched",
            entrance_edge=2, entrance_t=0.5, entrance_w=1.0,
            entrance_xy=(3.0, 60.0), feat=[],
        ),
        BuildingRecord(
            bid=1, key="retail", poly=_RETAIL_POLY, h=9.0, floors=1,
            arch="BIG_BOX_COMMERCIAL", roof="flat",
            entrance_edge=1, entrance_t=0.5, entrance_w=3.0,
            entrance_xy=(-90.0, -9.0), feat=["loading_dock"],
        ),
        BuildingRecord(
            bid=2, key="industrial", poly=_INDUSTRIAL_POLY, h=9.0, floors=1,
            arch="INDUSTRIAL", roof="flat",
            entrance_edge=3, entrance_t=0.5, entrance_w=3.0,
            entrance_xy=(-12.0, 54.0), feat=[],
        ),
    ]


def _fixture():
    roads = _roads()
    blocks, parcels = compile_parcels(
        roads, _building_dicts(), [], [], BOUNDS)
    buildings = _building_records()
    return roads, parcels, buildings


def _find_parcel(parcels, arch, bid):
    for p in parcels:
        if p.arch == arch and bid in p.building_bids:
            return p
    raise AssertionError(f"no {arch} parcel with building {bid} found")


def test_fixture_archetypes_resolved():
    _, parcels, _ = _fixture()
    house = _find_parcel(parcels, "RESIDENTIAL", 0)
    retail = _find_parcel(parcels, "RETAIL", 1)
    industrial = _find_parcel(parcels, "INDUSTRIAL", 2)
    assert house.building_bids == [0]
    assert retail.building_bids == [1]
    assert industrial.building_bids == [2]


def _placement_tuple(pl):
    return (pl.kind, round(pl.x, 6), round(pl.z, 6), round(pl.rot, 6),
            pl.variant, pl.cat)


def _anchor_tuple(a):
    return (a.kind, round(a.x, 6), round(a.z, 6), a.bid)


def _patch_tuple(p):
    return (p.surface, p.priority, p.poly.wkb)


def test_deterministic_across_runs():
    roads, parcels, buildings = _fixture()
    r1 = compile_detail(parcels, buildings, roads, seed=42)
    r2 = compile_detail(parcels, buildings, roads, seed=42)
    assert [_placement_tuple(p) for p in r1.placements] == \
        [_placement_tuple(p) for p in r2.placements]
    assert [_anchor_tuple(a) for a in r1.anchors] == \
        [_anchor_tuple(a) for a in r2.anchors]
    assert [_patch_tuple(p) for p in r1.patches] == \
        [_patch_tuple(p) for p in r2.patches]
    assert r1.stats == r2.stats


def test_placements_within_bounds():
    roads, parcels, buildings = _fixture()
    res = compile_detail(parcels, buildings, roads, seed=7)
    min_x, min_z, max_x, max_z = BOUNDS
    assert res.placements, "expected some placements in the fixture"
    for pl in res.placements:
        assert min_x - 1e-6 <= pl.x <= max_x + 1e-6
        assert min_z - 1e-6 <= pl.z <= max_z + 1e-6


def test_house_gets_yard_furniture_across_seeds():
    roads, parcels, buildings = _fixture()
    furniture_kinds = {"mailbox", "garbage_bin", "recycling_bin", "ac_condenser"}
    house_area = _HOUSE_POLY.buffer(25.0)
    for seed in range(5):
        res = compile_detail(parcels, buildings, roads, seed)
        near_house = [
            pl for pl in res.placements
            if pl.kind in furniture_kinds and house_area.contains(Point(pl.x, pl.z))
        ]
        assert near_house, f"seed {seed}: expected yard furniture near the house"


def test_house_gets_driveway_or_walkway_anchor_across_seeds():
    roads, parcels, buildings = _fixture()
    house_area = _HOUSE_POLY.buffer(45.0)
    for seed in range(5):
        res = compile_detail(parcels, buildings, roads, seed)
        near_house = [
            a for a in res.anchors
            if a.kind in ("DRIVEWAY_ANCHOR", "PEDESTRIAN_APPROACH")
            and house_area.contains(Point(a.x, a.z))
        ]
        assert near_house, f"seed {seed}: expected a driveway/walkway anchor"


def test_retail_parking_lot_and_stalls():
    roads, parcels, buildings = _fixture()
    res = compile_detail(parcels, buildings, roads, seed=3)
    assert any(p.surface == "PARKING" for p in res.patches)
    assert res.stats.get("stalls", 0) > 0
    vehicle_or_stop = [
        pl for pl in res.placements if pl.cat == "vehicle" or pl.kind == "parking_stop"
    ]
    assert vehicle_or_stop


def test_trees_never_inside_building_footprints():
    roads, parcels, buildings = _fixture()
    footprints = [b.poly for b in buildings]
    res = compile_detail(parcels, buildings, roads, seed=11)
    from asphodel.world_source.grammar_tables import TREE_KINDS
    # Bushes deliberately hug building perimeters (foundation planting), so
    # the clearance invariant applies to actual trees only.
    trees = [pl for pl in res.placements
             if pl.cat == "tree" and pl.kind in TREE_KINDS]
    assert trees, "expected some tree placements"
    for pl in trees:
        pt = Point(pl.x, pl.z)
        for fp in footprints:
            assert fp.distance(pt) > 2.0


def test_entrance_anchors_one_per_building():
    buildings = _building_records()
    anchors = entrance_anchors(buildings)
    assert len(anchors) == len(buildings)
    by_bid = {a.bid: a for a in anchors}
    assert set(by_bid) == {0, 1, 2}
    for a in anchors:
        assert a.kind == "BUILDING_ENTRANCE"
        assert a.bid >= 0


def test_compile_detail_never_emits_building_entrance():
    roads, parcels, buildings = _fixture()
    res = compile_detail(parcels, buildings, roads, seed=5)
    assert all(a.kind != "BUILDING_ENTRANCE" for a in res.anchors)


def test_industrial_fences_present_for_some_seed():
    roads, parcels, buildings = _fixture()
    industrial_poly = _INDUSTRIAL_POLY
    found_any = False
    for seed in range(12):
        res = compile_detail(parcels, buildings, roads, seed)
        fences = [pl for pl in res.placements if pl.kind == "chainlink_fence"]
        if fences:
            found_any = True
            for pl in fences:
                pt = Point(pl.x, pl.z)
                assert not industrial_poly.contains(pt)
                assert industrial_poly.distance(pt) > 0.0
    assert found_any, "expected chainlink fences for at least one of 12 seeds"


def test_stats_populated():
    roads, parcels, buildings = _fixture()
    res = compile_detail(parcels, buildings, roads, seed=1)
    assert isinstance(res.stats, dict) and res.stats
    assert res.stats.get("trees", 0) > 0
    assert res.stats.get("stalls", 0) > 0
    assert res.stats.get("driveways", 0) > 0


def test_curb_vehicles_bounded_deterministic_and_in_bounds():
    roads = _roads()
    _, parcels = compile_parcels(roads, _building_dicts(), [], [], BOUNDS)
    v1 = curb_vehicles(roads, parcels, seed=9)
    v2 = curb_vehicles(roads, parcels, seed=9)
    assert [_placement_tuple(p) for p in v1] == [_placement_tuple(p) for p in v2]
    assert len(v1) <= 3000
    min_x, min_z, max_x, max_z = BOUNDS
    for pl in v1:
        assert min_x - 5 <= pl.x <= max_x + 5
        assert min_z - 5 <= pl.z <= max_z + 5
        assert pl.cat == "vehicle"


def test_curb_vehicles_only_from_residential_segments():
    roads = _roads()
    _, parcels = compile_parcels(roads, _building_dicts(), [], [], BOUNDS)
    v = curb_vehicles(roads, parcels, seed=2)
    # Our fixture's only residential segment runs along x=0; every curb
    # vehicle should sit near that line (well away from the primary road).
    for pl in v:
        assert abs(pl.x) < 5.0

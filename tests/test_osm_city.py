"""Phase-1 OSM city pipeline tests (offline; inline fixtures, no network)."""
from __future__ import annotations

import math
import random

from asphodel.osm_city import geometry as geo


def test_project_origin_is_zero():
    assert geo.project(40.0, -73.0, 40.0, -73.0) == (0.0, 0.0)


def test_project_one_degree_lat_is_about_110540m():
    x, z = geo.project(41.0, -73.0, 40.0, -73.0)
    assert abs(x) < 1e-6
    assert abs(z - 110540.0) < 1.0


def test_project_one_degree_lon_scales_by_cos_lat():
    x, z = geo.project(40.0, -72.0, 40.0, -73.0)
    expected = 111320.0 * math.cos(math.radians(40.0))
    assert abs(x - expected) < 1.0
    assert abs(z) < 1e-6


def test_polygon_area_unit_square():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert abs(geo.polygon_area(square) - 100.0) < 1e-9


def test_polygon_area_is_orientation_independent():
    cw = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
    assert abs(geo.polygon_area(cw) - 100.0) < 1e-9


def test_polygon_area_degenerate_is_zero():
    assert geo.polygon_area([]) == 0.0
    assert geo.polygon_area([(0.0, 0.0)]) == 0.0
    assert geo.polygon_area([(0.0, 0.0), (1.0, 1.0)]) == 0.0


def test_place_blocks_count_scales_with_density():
    rng = random.Random(0)
    low = geo.place_blocks(0.0, (0.0, 0.0), (100.0, 100.0), rng, max_blocks=8)
    rng = random.Random(0)
    high = geo.place_blocks(1.0, (0.0, 0.0), (100.0, 100.0), rng, max_blocks=8)
    assert len(low) == 0
    assert len(high) == 8


def test_place_blocks_positions_within_cell():
    rng = random.Random(1)
    blocks = geo.place_blocks(1.0, (50.0, -20.0), (100.0, 100.0), rng, max_blocks=8)
    for b in blocks:
        x, z = b["xy"]
        assert 10.0 <= x <= 90.0   # center 50 +/- 0.4*100
        assert -60.0 <= z <= 20.0  # center -20 +/- 0.4*100
        assert 0.0 < b["height"] <= 40.0   # max_height is a true ceiling
        assert b["footprint"] > 0.0


def test_place_blocks_deterministic_for_same_seed():
    a = geo.place_blocks(0.7, (0.0, 0.0), (80.0, 80.0), random.Random(42), max_blocks=8)
    b = geo.place_blocks(0.7, (0.0, 0.0), (80.0, 80.0), random.Random(42), max_blocks=8)
    assert a == b


def test_project_polyline_maps_each_point():
    line = geo.project_polyline([(40.0, -73.0), (41.0, -73.0)], 40.0, -73.0)
    assert line[0] == [0.0, 0.0]
    assert abs(line[1][1] - 110540.0) < 1.0


from asphodel.osm_city import tessellate as tess


def _square_building(lat, lon, d=0.0005, levels=1):
    """A small square building footprint centered at (lat, lon)."""
    return {
        "ring": [(lat - d, lon - d), (lat - d, lon + d),
                 (lat + d, lon + d), (lat + d, lon - d)],
        "levels": levels,
    }


def test_grid_dims_from_aspect_ratio():
    # Wide bbox (more lon span than lat span) -> more cols than rows.
    bbox = (40.0, -74.0, 40.5, -73.0)  # (s, w, n, e): 1.0 lon span, 0.5 lat span
    t = tess.tessellate(bbox, buildings=[], grid=8, total_pop=1000.0)
    assert t.cols == 8
    assert t.rows == 4
    assert len(t.zones) == 32


def test_population_sums_to_total():
    bbox = (40.0, -73.01, 40.01, -73.0)
    buildings = [_square_building(40.002, -73.008), _square_building(40.008, -73.002)]
    t = tess.tessellate(bbox, buildings, grid=4, total_pop=10000.0)
    assert abs(sum(z["population"] for z in t.zones) - 10000.0) < 1e-6


def test_empty_buildings_give_zero_population():
    bbox = (40.0, -73.01, 40.01, -73.0)
    t = tess.tessellate(bbox, buildings=[], grid=4, total_pop=10000.0)
    assert all(z["population"] == 0.0 for z in t.zones)


def test_zone_ids_match_row_col_order():
    bbox = (40.0, -73.01, 40.01, -73.0)
    t = tess.tessellate(bbox, buildings=[], grid=4, total_pop=1.0)
    for z in t.zones:
        assert z["id"] == z["row"] * t.cols + z["col"]


def test_levels_weight_population():
    # Two identical footprints; the 3-storey one gets ~3x the population.
    bbox = (40.0, -73.02, 40.01, -73.0)
    tall = _square_building(40.005, -73.015, levels=3)
    short = _square_building(40.005, -73.005, levels=1)
    t = tess.tessellate(bbox, [tall, short], grid=2, total_pop=4000.0)
    pops = sorted(z["population"] for z in t.zones if z["population"] > 0)
    assert len(pops) == 2
    assert abs(pops[1] / pops[0] - 3.0) < 0.2

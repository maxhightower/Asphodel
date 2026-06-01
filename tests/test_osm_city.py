"""Phase-1 OSM city pipeline tests (offline; inline fixtures, no network)."""
from __future__ import annotations

import math

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


import random


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
        assert 0.0 <= x <= 100.0   # center 50 +/- 0.4*100
        assert -70.0 <= z <= 30.0  # center -20 +/- 0.4*100
        assert b["height"] > 0.0
        assert b["footprint"] > 0.0


def test_place_blocks_deterministic_for_same_seed():
    a = geo.place_blocks(0.7, (0.0, 0.0), (80.0, 80.0), random.Random(42), max_blocks=8)
    b = geo.place_blocks(0.7, (0.0, 0.0), (80.0, 80.0), random.Random(42), max_blocks=8)
    assert a == b


def test_project_polyline_maps_each_point():
    line = geo.project_polyline([(40.0, -73.0), (41.0, -73.0)], 40.0, -73.0)
    assert line[0] == [0.0, 0.0]
    assert abs(line[1][1] - 110540.0) < 1.0

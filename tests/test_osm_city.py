"""Phase-1 OSM city pipeline tests (offline; inline fixtures, no network)."""
from __future__ import annotations

import json as _json
import math
import os
import random

import numpy as np
import pytest

from asphodel.config import ScenarioConfig, GraphParams, ModelParams
from asphodel.runner import run_scenario
from asphodel.osm_city import geocode as gc
from asphodel.osm_city import CityNotFound
from asphodel.osm_city import geometry as geo
from asphodel.osm_city import overpass as ov
from asphodel.osm_city import bundle as bnd
from asphodel.osm_city import pipeline as pipe


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
    # Wider in meters than tall -> more cols than rows. The bbox spans 1.0 deg lon
    # x 0.5 deg lat, but at lat ~40 a deg of lon is ~0.77x a deg of lat, so the
    # projected meter aspect (~84966 x 55270 m) gives 8 cols and round(8*0.65)=5
    # rows -> near-square ~10620 x 11054 m cells.
    bbox = (40.0, -74.0, 40.5, -73.0)  # (s, w, n, e)
    t = tess.tessellate(bbox, buildings=[], grid=8, total_pop=1000.0)
    assert t.cols == 8
    assert t.rows == 5
    assert len(t.zones) == 40
    # Cells are near-square (within 15%) thanks to the meter-based aspect.
    assert abs(t.cell_w / t.cell_h - 1.0) < 0.15


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


def test_per_zone_population_sets_N0():
    pops = [100.0, 200.0, 300.0, 400.0]
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2, population=pops)),
        n_days=1.0,
    )
    from asphodel.model import Simulation
    sim = Simulation(cfg)
    assert np.allclose(sim.N0, np.array(pops))


def test_default_population_unchanged_when_vector_absent():
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2,
                                            population_per_zone=777.0)),
        n_days=1.0,
    )
    from asphodel.model import Simulation
    sim = Simulation(cfg)
    assert np.allclose(sim.N0, np.full(4, 777.0))


def test_run_scenario_with_heterogeneous_population():
    pops = [5000.0, 1000.0, 1000.0, 1000.0]
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2, population=pops)),
        n_days=5.0, seed_zone=0,
    )
    result = run_scenario(cfg)
    assert result.belief_history.shape == (cfg.n_ticks + 1, 4)


def test_zero_population_zone_keeps_belief_finite():
    # Real OSM grids contain empty cells (population 0: water, parks, rural
    # edges). The sim must stay NaN-free -- an empty zone is inert, not a 0/0
    # that propagates through belief contagion and poisons the whole grid.
    pops = [5000.0, 0.0, 0.0, 0.0]
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2, population=pops)),
        n_days=10.0, seed_zone=0,
    )
    result = run_scenario(cfg)
    assert np.isfinite(result.belief_history).all()


# Nominatim returns boundingbox as [south, north, west, east] strings.
_NOMINATIM_FIXTURE = _json.dumps([
    {"boundingbox": ["41.6", "42.0", "-87.9", "-87.5"], "display_name": "Chicago"}
])


def test_geocode_returns_bbox_in_swne_order():
    bbox = gc.geocode("Chicago", fetch=lambda url: _NOMINATIM_FIXTURE)
    s, w, n, e = bbox
    assert (s, w, n, e) == (41.6, -87.9, 42.0, -87.5)


def test_geocode_raises_when_empty():
    with pytest.raises(CityNotFound):
        gc.geocode("Nowhereville", fetch=lambda url: "[]")


def test_geocode_caps_oversized_bbox():
    huge = _json.dumps([{"boundingbox": ["30.0", "36.0", "-106.0", "-93.0"]}])  # Texas-ish
    bbox = gc.geocode("Texas", fetch=lambda url: huge, max_span_deg=0.5)
    s, w, n, e = bbox
    assert abs((n - s) - 0.5) < 1e-9
    assert abs((e - w) - 0.5) < 1e-9
    # Stays centered on the original center.
    assert abs(((s + n) / 2) - 33.0) < 1e-9
    assert abs(((w + e) / 2) - (-99.5)) < 1e-9


def test_geocode_builds_query_url():
    captured = {}
    def fake_fetch(url):
        captured["url"] = url
        return _NOMINATIM_FIXTURE
    gc.geocode("San Francisco", fetch=fake_fetch)
    assert "q=San+Francisco" in captured["url"]
    assert "format=json" in captured["url"]


# Overpass `out geom;` returns ways with inline node geometry.
_OVERPASS_FIXTURE = {
    "elements": [
        {"type": "way", "tags": {"building": "yes", "building:levels": "3"},
         "geometry": [{"lat": 40.000, "lon": -73.000}, {"lat": 40.000, "lon": -73.001},
                      {"lat": 40.001, "lon": -73.001}, {"lat": 40.001, "lon": -73.000}]},
        {"type": "way", "tags": {"building": "house"},
         "geometry": [{"lat": 40.002, "lon": -73.002}, {"lat": 40.002, "lon": -73.003},
                      {"lat": 40.003, "lon": -73.003}]},
        {"type": "way", "tags": {"highway": "primary", "name": "Main St"},
         "geometry": [{"lat": 40.000, "lon": -73.000}, {"lat": 40.010, "lon": -73.010}]},
        {"type": "node", "lat": 40.0, "lon": -73.0},  # ignored
    ]
}


def test_build_query_contains_bbox_and_filters():
    q = ov.build_query((40.0, -73.1, 40.1, -73.0))
    assert "40.0,-73.1,40.1,-73.0" in q
    assert 'way["building"]' in q
    assert "highway" in q
    assert "out geom;" in q


def test_parse_osm_splits_buildings_and_roads():
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    assert len(buildings) == 2
    assert len(roads) == 1
    assert buildings[0]["levels"] == 3
    assert buildings[1]["levels"] == 1          # untagged -> default 1
    assert roads[0]["class"] == "primary"
    assert roads[0]["points"][0] == (40.000, -73.000)


def test_fetch_osm_uses_cache(tmp_path):
    calls = {"n": 0}
    def fake_fetch(query):
        calls["n"] += 1
        return _json.dumps(_OVERPASS_FIXTURE)
    bbox = (40.0, -73.1, 40.1, -73.0)
    a = ov.fetch_osm(bbox, cache_dir=str(tmp_path), fetch=fake_fetch)
    b = ov.fetch_osm(bbox, cache_dir=str(tmp_path), fetch=fake_fetch)
    assert calls["n"] == 1                        # second call served from cache
    assert a == b


def _toy_inputs():
    meta = {"name": "Toy", "query": "Toy", "bbox": [0, 0, 1, 1],
            "center": [0.5, 0.5], "projection": "equirectangular",
            "grid": {"rows": 2, "cols": 2, "cell_m": 100.0},
            "dt": 0.25, "n_days": 1.0, "n_ticks": 4,
            "genome": {"R0": 3.0}, "seed": 0, "seed_zone": 0, "version": "1"}
    zones = [{"id": 0, "row": 0, "col": 0, "center_xy": [0.0, 0.0], "extent": [100.0, 100.0],
              "population": 1000.0, "density": 1.0, "blocks": []}]
    roads = {"polylines": [{"class": "primary", "points": [[0.0, 0.0], [10.0, 10.0]]}]}
    timeline = {"field": "belief", "shape": [5, 1], "data": [[0.0], [0.1], [0.2], [0.3], [0.4]]}
    return meta, zones, roads, timeline


def test_write_bundle_creates_all_files(tmp_path):
    meta, zones, roads, timeline = _toy_inputs()
    bnd.write_bundle(str(tmp_path), meta, zones, roads, timeline)
    for name in ("meta.json", "zones.json", "roads.json", "timeline.json"):
        assert os.path.exists(tmp_path / name)


def test_write_bundle_is_deterministic(tmp_path):
    meta, zones, roads, timeline = _toy_inputs()
    a, b = tmp_path / "a", tmp_path / "b"
    bnd.write_bundle(str(a), meta, zones, roads, timeline)
    bnd.write_bundle(str(b), meta, zones, roads, timeline)
    for name in ("meta.json", "zones.json", "roads.json", "timeline.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_build_timeline_rounds_and_shapes():
    hist = np.array([[0.123456789, 0.5], [0.987654321, 0.25]])
    tl = bnd.build_timeline(hist)
    assert tl["field"] == "belief"
    assert tl["shape"] == [2, 2]
    assert tl["data"][0][0] == 0.12346     # rounded to 5 dp


def test_build_bundle_end_to_end_offline(tmp_path):
    # Use the Overpass fixture parsed into buildings/roads, no network.
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    bbox = (40.0, -73.01, 40.01, -73.0)
    out = tmp_path / "city"
    pipe.build_bundle(
        query="Toytown", bbox=bbox, buildings=buildings, roads=roads,
        out_dir=str(out), grid=4, total_pop=20000.0, seed=0, n_days=10.0,
    )
    meta = _json.loads((out / "meta.json").read_text())
    zones = _json.loads((out / "zones.json").read_text())
    timeline = _json.loads((out / "timeline.json").read_text())

    assert meta["grid"]["rows"] * meta["grid"]["cols"] == len(zones)
    assert timeline["shape"] == [meta["n_ticks"] + 1, len(zones)]
    assert abs(sum(z["population"] for z in zones) - 20000.0) < 1.0
    assert all("blocks" in z for z in zones)
    # seed_zone is a populated cell
    assert zones[meta["seed_zone"]]["population"] > 0.0


def test_build_bundle_is_byte_deterministic(tmp_path):
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    bbox = (40.0, -73.01, 40.01, -73.0)
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        pipe.build_bundle(query="Toytown", bbox=bbox, buildings=buildings, roads=roads,
                          out_dir=str(out), grid=4, total_pop=20000.0, seed=0, n_days=10.0)
    for name in ("meta.json", "zones.json", "roads.json", "timeline.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_build_bundle_timeline_is_finite(tmp_path):
    # End-to-end guard: the fixture's bbox has mostly empty cells, so this would
    # be all-NaN if zero-population zones weren't handled. Every value must be
    # a finite belief in [0, 1].
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    out = tmp_path / "city"
    pipe.build_bundle(query="Toytown", bbox=(40.0, -73.01, 40.01, -73.0),
                      buildings=buildings, roads=roads, out_dir=str(out),
                      grid=4, total_pop=20000.0, seed=0, n_days=10.0)
    timeline = _json.loads((out / "timeline.json").read_text())
    data = np.array(timeline["data"], dtype=float)
    assert np.isfinite(data).all()
    assert (data >= 0.0).all() and (data <= 1.0).all()


# ---------------------------------------------------------------- buildings.json

def test_parse_osm_classifies_and_extracts_height():
    data = {"elements": [
        {"type": "way", "tags": {"building": "retail", "height": "12 m", "name": "Corner Shop"},
         "geometry": [{"lat": 40.000, "lon": -73.000}, {"lat": 40.000, "lon": -73.001},
                      {"lat": 40.001, "lon": -73.001}]},
        {"type": "way", "tags": {"building": "yes", "amenity": "pharmacy"},
         "geometry": [{"lat": 40.002, "lon": -73.002}, {"lat": 40.002, "lon": -73.003},
                      {"lat": 40.003, "lon": -73.003}]},
    ]}
    buildings, _ = ov.parse_osm(data)
    assert buildings[0]["kind"] == "shop"
    assert buildings[0]["height_m"] == 12.0
    assert buildings[0]["name"] == "Corner Shop"
    assert buildings[1]["kind"] == "pharmacy"
    assert buildings[1]["height_m"] is None


def test_build_query_includes_minor_streets():
    q = ov.build_query((40.0, -73.1, 40.1, -73.0))
    assert "residential" in q
    assert "service" in q
    assert "tertiary" in q


def test_bake_footprints_projects_and_defaults_height():
    buildings, _ = ov.parse_osm(_OVERPASS_FIXTURE)
    baked = pipe.bake_footprints(buildings, lat0=40.0005, lon0=-73.0005)
    assert len(baked) == 2
    b0 = baked[0]
    assert b0["levels"] == 3
    assert abs(b0["height"] - 3 * 3.2) < 1e-6      # levels * storey height
    assert len(b0["footprint"]) == 4
    assert all(len(p) == 2 for p in b0["footprint"])
    assert b0["area_m2"] > 1000.0                  # ~111m x ~85m block


def test_bake_footprints_drops_closing_duplicate_and_tiny_rings():
    ring = [(40.0, -73.0), (40.0, -73.001), (40.001, -73.001), (40.0, -73.0)]
    tiny = [(40.0, -73.0), (40.0, -73.0000001), (40.0000001, -73.0000001)]
    baked = pipe.bake_footprints(
        [{"ring": ring, "levels": 1}, {"ring": tiny, "levels": 1}], 40.0, -73.0)
    assert len(baked) == 1
    assert len(baked[0]["footprint"]) == 3          # closing point removed


def test_bake_footprints_caps_to_nearest_center():
    def sq(off_lat):
        return {"ring": [(off_lat, 0.0), (off_lat, 0.001),
                         (off_lat + 0.001, 0.001), (off_lat + 0.001, 0.0)],
                "levels": 1}
    buildings = [sq(i * 0.01) for i in range(10)]
    baked = pipe.bake_footprints(buildings, 0.0, 0.0, max_buildings=3)
    assert len(baked) == 3
    # nearest-to-center survive: those with the smallest |offset|
    assert all(abs(b["center_xy"][1]) < 2500.0 for b in baked)


def test_build_bundle_writes_buildings_json(tmp_path):
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    out = tmp_path / "city"
    pipe.build_bundle(query="Toytown", bbox=(40.0, -73.01, 40.01, -73.0),
                      buildings=buildings, roads=roads, out_dir=str(out),
                      grid=4, total_pop=20000.0, seed=0, n_days=10.0)
    baked = _json.loads((out / "buildings.json").read_text())
    meta = _json.loads((out / "meta.json").read_text())
    assert len(baked) == 2
    assert meta["n_buildings"] == 2
    assert baked[0]["kind"] in ("generic", "house")
    for b in baked:
        assert len(b["footprint"]) >= 3


# ------------------------------------------------------------- synth fallback

def test_synth_buildings_are_deterministic_and_clear_of_roads():
    from asphodel.osm_city import synth
    roads = {"polylines": [
        {"class": "primary", "points": [[0.0, 0.0], [400.0, 0.0]]},
        {"class": "residential", "points": [[0.0, 0.0], [0.0, 400.0]]},
    ]}
    zones = [{"center_xy": [200.0, 200.0], "extent": [600.0, 600.0],
              "density": 1.0, "population": 1000.0}]
    a = synth.synthesize(roads, zones, seed=7)
    b = synth.synthesize(roads, zones, seed=7)
    assert a == b
    assert len(a) > 5
    for bld in a:
        assert bld["synthetic"] is True
        assert len(bld["footprint"]) == 4
        # every corner stays off the primary carriageway (halfwidth 7.5m)
        for x, z in bld["footprint"]:
            if 0.0 <= x <= 400.0:
                assert abs(z) > 7.5

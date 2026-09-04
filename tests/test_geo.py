"""Tests for the authoritative geographic frame + floating origin (AS-REGION-0, §13)."""
from __future__ import annotations

import math

from asphodel.geo import GeoReference, FloatingOrigin, haversine_m
from asphodel.osm_city import geometry as geom


def test_project_origin_is_zero():
    g = GeoReference(40.0, -73.0)
    assert g.project(40.0, -73.0) == (0.0, 0.0)


def test_project_matches_legacy_city_projection():
    # The regional frame MUST agree with the city pipeline's projection so
    # regional terrain and the detailed city align exactly (§17.1).
    g = GeoReference(29.82, -95.46)
    for lat, lon in [(29.85, -95.43), (29.79, -95.49), (29.82, -95.50)]:
        gx, gz = g.project(lat, lon)
        lx, lz = geom.project(lat, lon, 29.82, -95.46)
        assert abs(gx - lx) < 1e-9
        assert abs(gz - lz) < 1e-9


def test_unproject_round_trips():
    g = GeoReference(39.74, -104.99, origin_elevation=1600.0)
    for lat, lon in [(39.80, -105.20), (39.60, -104.80)]:
        x, z = g.project(lat, lon)
        rlat, rlon = g.unproject(x, z)
        assert abs(rlat - lat) < 1e-9
        assert abs(rlon - lon) < 1e-9


def test_project_one_degree_lat_is_about_110540m():
    g = GeoReference(40.0, -73.0)
    x, z = g.project(41.0, -73.0)
    assert abs(x) < 1e-6
    assert abs(z - 110540.0) < 1.0


def test_projection_error_vs_haversine_small_for_city_extent():
    g = GeoReference(29.82, -95.46)
    x, z = g.project(29.87, -95.40)  # ~ a few km away
    flat = math.hypot(x, z)
    great = haversine_m(29.82, -95.46, 29.87, -95.40)
    assert abs(flat - great) / great < 0.01  # under 1% for city scale


def test_project3_uses_origin_elevation():
    g = GeoReference(39.74, -104.99, origin_elevation=1600.0)
    x, y, z = g.project3(39.74, -104.99, 1650.0)
    assert (round(x, 6), round(z, 6)) == (0.0, 0.0)
    assert abs(y - 50.0) < 1e-9  # 50 m above origin elevation


def test_floating_origin_round_trip_is_identity():
    fo = FloatingOrigin(shift=(1234.0, 0.0, -987.0))
    p = (5000.0, 12.0, -3000.0)
    r = fo.to_render(p)
    back = fo.to_global(r)
    assert back == p


def test_floating_origin_no_rebase_within_threshold():
    fo = FloatingOrigin(threshold=4000.0, quantum=1000.0)
    delta = fo.maybe_rebase((100.0, 0.0, 100.0))
    assert delta == (0.0, 0.0, 0.0)
    assert fo.rebase_count == 0


def test_floating_origin_rebase_preserves_semantic_position():
    # The core §13/§17.4 invariant: rebasing shrinks render coords but an
    # entity's semantic (global) position is unchanged.
    fo = FloatingOrigin(threshold=4000.0, quantum=1000.0)
    entity_global = (50123.0, 8.0, -49876.0)
    render_before = fo.to_render(entity_global)
    assert fo.to_global(render_before) == entity_global

    delta = fo.maybe_rebase(entity_global)
    assert delta != (0.0, 0.0, 0.0)
    assert fo.rebase_count == 1
    # Render coords are now small...
    render_after = fo.to_render(entity_global)
    assert max(abs(render_after[0]), abs(render_after[2])) <= fo.threshold
    # ...but the semantic position recovered from them is identical.
    assert fo.to_global(render_after) == entity_global


def test_floating_origin_rebase_is_deterministic_and_quantized():
    fo1 = FloatingOrigin(threshold=4000.0, quantum=1000.0)
    fo2 = FloatingOrigin(threshold=4000.0, quantum=1000.0)
    focus = (50123.0, 0.0, -49876.0)
    fo1.maybe_rebase(focus)
    fo2.maybe_rebase(focus)
    assert fo1.shift == fo2.shift
    # Snapped to the quantum grid.
    assert fo1.shift[0] % 1000.0 == 0.0
    assert fo1.shift[2] % 1000.0 == 0.0

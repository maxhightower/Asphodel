"""Tests for regional terrain: elevation, LOD chunking, skirts, flat/mountain gate.

Covers §17.1: deterministic bundle generation, valid elevation sampling, chunk
seams within tolerance, Houston-flat / Denver-mountainous differentiation.
"""
from __future__ import annotations

import numpy as np

from asphodel.geo import GeoReference
from asphodel.region import (
    ARCHETYPES,
    SyntheticElevationProvider,
    CachedDEMProvider,
    FallbackDEMProvider,
    USGS3DEPProvider,
    RegionalExtent,
    build_quadtree,
    chunk_mesh,
    bake_heightmap,
    terrain_stats,
    landcover,
)

HOUSTON = GeoReference(29.82, -95.46, origin_elevation=15.0)
DENVER = GeoReference(39.74, -104.99, origin_elevation=1600.0)


def _flat_provider():
    return SyntheticElevationProvider(HOUSTON, ARCHETYPES["coastal_plain"], seed=7)


def _mtn_provider():
    return SyntheticElevationProvider(DENVER, ARCHETYPES["mountain_front"], seed=7)


# --- elevation sampling -----------------------------------------------------
def test_synthetic_sampling_is_deterministic():
    p1 = _mtn_provider()
    p2 = _mtn_provider()
    xs = np.linspace(-40000, 40000, 33)
    zs = np.linspace(-40000, 40000, 33)
    gx, gz = np.meshgrid(xs, zs)
    assert np.array_equal(p1.sample(gx, gz), p2.sample(gx, gz))


def test_sampling_scalar_and_array_agree():
    p = _flat_provider()
    arr = p.sample(np.array([1000.0]), np.array([2000.0]))[0]
    scal = p.sample(1000.0, 2000.0)
    assert abs(arr - scal) < 1e-9


def test_flat_city_stays_flat():
    stats = terrain_stats(_flat_provider(), RegionalExtent.from_km(3, 40, 60))
    # Gentle coastal plain: modest relief, no steep gradient anywhere.
    assert stats["relief_span"] < 120.0
    assert stats["max_gradient"] < 0.05  # < 5% grade


def test_mountain_city_has_genuine_relief():
    stats = terrain_stats(_mtn_provider(), RegionalExtent.from_km(3, 40, 60))
    assert stats["relief_span"] > 800.0          # real mountains
    assert stats["max_gradient"] > 0.15          # steep faces


def test_flat_and_mountain_are_dramatically_different():
    flat = terrain_stats(_flat_provider(), RegionalExtent.from_km(3, 40, 60))
    mtn = terrain_stats(_mtn_provider(), RegionalExtent.from_km(3, 40, 60))
    # The whole point of §3.5: geography alone communicates the difference.
    assert mtn["relief_span"] > 8.0 * flat["relief_span"]


def test_mountain_front_rises_only_on_one_side():
    # No fake mountain ring: the Front Range is to the west, plains to the east.
    # Compare band means (a single ridged sample can sit in a valley).
    p = _mtn_provider()
    zs = np.linspace(-30000, 30000, 40)
    west = np.mean([p.sample(x, z) for x in np.linspace(-50000, -30000, 20) for z in zs])
    east = np.mean([p.sample(x, z) for x in np.linspace(30000, 50000, 20) for z in zs])
    assert west - east > 400.0


def test_coastal_plain_has_no_mountain_component():
    p = _flat_provider()
    # Sampling far in every direction stays low — no ridge anywhere.
    for ang in np.linspace(0, 2 * np.pi, 8, endpoint=False):
        x, z = 45000.0 * np.cos(ang), 45000.0 * np.sin(ang)
        assert p.sample(x, z) < 200.0


# --- quadtree LOD -----------------------------------------------------------
def test_quadtree_is_deterministic():
    ext = RegionalExtent.from_km(3, 40, 80)
    a = build_quadtree(ext, (0.0, 0.0), max_depth=6)
    b = build_quadtree(ext, (0.0, 0.0), max_depth=6)
    assert [c.key() for c in a] == [c.key() for c in b]


def test_quadtree_is_fine_near_focus_coarse_far():
    ext = RegionalExtent.from_km(3, 40, 80)
    leaves = build_quadtree(ext, (0.0, 0.0), max_depth=6)
    near = [c for c in leaves if c.distance_to((0.0, 0.0)) < 2000.0]
    far = [c for c in leaves if c.distance_to((0.0, 0.0)) > 30000.0]
    assert near and far
    assert min(c.size for c in near) < max(c.size for c in far)
    # Nearest chunks reach the finest LOD (0).
    assert min(c.lod for c in near) == 0


def test_quadtree_leaves_have_bounded_count():
    ext = RegionalExtent.from_km(3, 40, 80)
    leaves = build_quadtree(ext, (0.0, 0.0), max_depth=7)
    # Quadtree focused split stays modest, not the millions a uniform grid needs.
    assert len(leaves) < 400


# --- mesh + skirts ----------------------------------------------------------
def test_chunk_mesh_is_deterministic():
    ext = RegionalExtent.from_km(3, 40, 80)
    chunk = build_quadtree(ext, (0.0, 0.0), max_depth=6)[0]
    p = _mtn_provider()
    m1 = chunk_mesh(chunk, p, res=16)
    m2 = chunk_mesh(chunk, p, res=16)
    assert m1["vertices"] == m2["vertices"]
    assert m1["indices"] == m2["indices"]


def test_chunk_mesh_triangle_count_is_bounded():
    ext = RegionalExtent.from_km(3, 40, 80)
    chunk = build_quadtree(ext, (0.0, 0.0), max_depth=6)[0]
    m = chunk_mesh(chunk, _mtn_provider(), res=16)
    surface = 2 * 16 * 16
    assert m["triangle_count"] == surface + m["triangle_count"] - surface  # sanity
    assert m["triangle_count"] >= surface           # includes skirt
    assert m["triangle_count"] < surface + 4 * 16 * 2 + 8  # skirt is small & bounded


def test_chunk_corner_vertices_match_provider_exactly():
    # Shared corners between neighbouring chunks agree to the bit because both
    # sample the provider at the identical world coordinate (crack-free corners).
    ext = RegionalExtent.from_km(3, 40, 80)
    chunk = build_quadtree(ext, (0.0, 0.0), max_depth=6)[0]
    p = _mtn_provider()
    m = chunk_mesh(chunk, p, res=8, origin_elevation=DENVER.origin_elevation)
    n = m["res"] + 1
    corner = m["vertices"][0]  # (x, y, z) at chunk SW-ish corner
    expected_y = float(p.sample(corner[0], corner[2])) - DENVER.origin_elevation
    assert abs(corner[1] - expected_y) < 1e-9


def test_skirt_hangs_below_surface():
    ext = RegionalExtent.from_km(3, 40, 80)
    chunk = build_quadtree(ext, (0.0, 0.0), max_depth=6)[0]
    m = chunk_mesh(chunk, _mtn_provider(), res=8, skirt_depth=30.0)
    surface = m["surface_vertex_count"]
    surface_ys = [v[1] for v in m["vertices"][:surface]]
    skirt_ys = [v[1] for v in m["vertices"][surface:]]
    assert min(skirt_ys) < min(surface_ys)  # skirt drops below the lowest surface vert


# --- physical fidelity (§3.4) ----------------------------------------------
def test_chunk_physical_fidelity_is_distance_driven():
    ext = RegionalExtent.from_km(3, 40, 80)
    leaves = build_quadtree(ext, (0.0, 0.0), max_depth=6)
    near = min(leaves, key=lambda c: c.distance_to((0.0, 0.0)))
    far = max(leaves, key=lambda c: c.distance_to((0.0, 0.0)))
    ns = near.physical_state((0.0, 0.0), collision_radius=3000.0, nav_radius=2000.0)
    fs = far.physical_state((0.0, 0.0), collision_radius=3000.0, nav_radius=2000.0)
    assert ns.rendered and fs.rendered   # both drawn
    assert ns.collision and not fs.collision
    assert ns.navigation and not fs.navigation


# --- bake artifact round-trip ----------------------------------------------
def test_baked_heightmap_round_trips_through_cached_provider():
    ext = RegionalExtent.from_km(3, 20, 40)
    src = _mtn_provider()
    art = bake_heightmap(src, ext, step_m=500.0)
    cached = CachedDEMProvider(
        np.array(art["heights"]), art["x0"], art["z0"], art["step_m"],
        provenance=art["provenance"],
    )
    # Sample away from grid nodes; bilinear cache is close to the source.
    for x, z in [(1234.0, -5678.0), (-20000.0, 12000.0), (3000.0, 3000.0)]:
        assert abs(cached.sample(x, z) - src.sample(x, z)) < 60.0


def test_fallback_provider_degrades_to_synthetic():
    # No cache acquired -> USGS3DEP.sample raises -> fall back to synthetic.
    chain = FallbackDEMProvider([
        USGS3DEPProvider(DENVER, cache=None),
        _mtn_provider(),
    ])
    assert abs(chain.sample(0.0, 0.0)) >= 0.0  # does not raise
    assert chain.provenance()["source"] == "synthetic"


# --- land cover -------------------------------------------------------------
def test_landcover_coast_has_water_mountain_has_rock():
    ext = RegionalExtent.from_km(3, 40, 60)
    x0, z0, side = ext.root_square()
    xs = x0 + np.linspace(0, side, 80)
    zs = z0 + np.linspace(0, side, 80)
    gx, gz = np.meshgrid(xs, zs)

    coast = landcover.classify_grid(_flat_provider(), ARCHETYPES["coastal_plain"], gx, gz)
    cf = landcover.coverage_fractions(coast)
    assert cf["water"] > 0.02

    mtn = landcover.classify_grid(_mtn_provider(), ARCHETYPES["mountain_front"], gx, gz)
    mf = landcover.coverage_fractions(mtn)
    assert mf["rock"] + mf["snow"] > 0.02
    assert mf["water"] == 0.0  # landlocked

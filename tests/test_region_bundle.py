"""Tests for bundle augmentation + the flat/mountain visual proving grounds (§20)."""
from __future__ import annotations

import json
import os

import pytest

from asphodel.geo import GeoReference
from asphodel.region_bundle import (
    build_region_artifact,
    build_mobility_artifact,
    build_physics_artifact,
)
from asphodel.mobility import Mode, MobilityGraph, RoadSegment

BUNDLES = os.path.join(os.path.dirname(__file__), os.pardir, "godot", "bundles")


def test_region_artifact_is_deterministic():
    g = GeoReference(29.82, -95.46, origin_elevation=15.0)
    a = build_region_artifact(g, "coastal_plain", seed=0)
    b = build_region_artifact(g, "coastal_plain", seed=0)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_flat_city_gate():
    g = GeoReference(29.82, -95.46, origin_elevation=15.0)
    a = build_region_artifact(g, "coastal_plain", seed=0)
    assert a["terrain_stats"]["relief_span"] < 150.0
    assert a["terrain_stats"]["max_gradient"] < 0.05
    assert a["land_cover"]["plains"] > 0.4          # dominated by flat land
    assert a["land_cover"].get("water", 0.0) > 0.0  # a coast exists


def test_mountain_city_gate():
    g = GeoReference(39.74, -104.99, origin_elevation=1609.0)
    a = build_region_artifact(g, "mountain_front", seed=0)
    assert a["terrain_stats"]["relief_span"] > 800.0
    assert a["terrain_stats"]["max_gradient"] > 0.15
    assert a["land_cover"]["rock"] + a["land_cover"]["snow"] > 0.0
    assert a["land_cover"].get("water", 0.0) == 0.0  # landlocked


def test_flat_and_mountain_are_obviously_different():
    flat = build_region_artifact(GeoReference(29.82, -95.46), "coastal_plain")
    mtn = build_region_artifact(GeoReference(39.74, -104.99), "mountain_front")
    assert (mtn["terrain_stats"]["relief_span"]
            > 8.0 * flat["terrain_stats"]["relief_span"])


def test_chunk_manifest_has_near_collision_far_render_only():
    g = GeoReference(29.82, -95.46)
    a = build_region_artifact(g, "coastal_plain")
    chunks = a["chunk_manifest"]
    assert any(c["collision"] for c in chunks)          # near chunks collide
    assert any(not c["collision"] and c["rendered"] for c in chunks)  # far render-only


def test_atmosphere_params_present_for_distance_cue():
    a = build_region_artifact(GeoReference(29.82, -95.46), "coastal_plain")
    atmo = a["atmosphere"]
    assert atmo["fog_end"] > atmo["fog_start"] > 0


def test_mobility_artifact_from_real_roads_is_routable():
    with open(os.path.join(BUNDLES, "houston", "roads.json")) as f:
        roads = json.load(f)
    art = build_mobility_artifact(roads)
    assert art["stats"]["directed_edges"] > 0
    assert len(art["segments"]) == art["stats"]["segments"]
    # Schema version 2: geometry survives the bake, so Python and the client
    # measure the same street.
    assert art["version"] == 2
    assert art["frame"] == "bundle_metres"
    assert all(len(s["pts"]) >= 2 for s in art["segments"])
    assert any(len(s["pts"]) > 2 for s in art["segments"])  # bends kept


def test_mobility_artifact_is_byte_deterministic():
    with open(os.path.join(BUNDLES, "houston", "roads.json")) as f:
        roads = json.load(f)
    a = build_mobility_artifact(roads, source_label="t")
    b = build_mobility_artifact(roads, source_label="t")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    ids = [s["id"] for s in a["segments"]]
    assert ids == sorted(ids)
    assert list(a["nodes"]) == sorted(a["nodes"])


def test_mobility_graph_load_reads_the_baked_streetmap():
    g = MobilityGraph.load(os.path.join(BUNDLES, "boulder"))
    # The synthetic grid has no Overture packet: it is baked by the polyline
    # fallback, which still emits schema v2 and says where it came from.
    assert g.version == 2
    assert "polylines" in (g.source or "")
    assert g.stats()["segments"] > 0


def test_mobility_graph_load_falls_back_to_roads_json(tmp_path):
    with open(os.path.join(BUNDLES, "houston", "roads.json")) as f:
        roads = json.load(f)
    roads["polylines"] = roads["polylines"][:50]
    with open(tmp_path / "roads.json", "w") as f:
        json.dump(roads, f)
    g = MobilityGraph.load(str(tmp_path))       # no streetmap.json here
    assert "roads.json" in g.source
    assert g.stats()["segments"] > 0


def test_physics_artifact_matches_authority():
    art = build_physics_artifact()
    assert "world_static" in art["body_profiles"]
    assert art["body_profiles"]["player"]["mask"] != 0
    # every colliding object references a real body profile
    for kind, o in art["object_solidity"].items():
        if o["collision"]:
            assert o["body"] in art["body_profiles"]


def test_committed_houston_region_artifact_is_flat_if_present():
    path = os.path.join(BUNDLES, "houston", "region.json")
    if not os.path.exists(path):
        pytest.skip("houston region artifact not baked in this tree")
    with open(path) as f:
        region = json.load(f)
    assert region["archetype"] == "coastal_plain"
    assert region["terrain_stats"]["relief_span"] < 150.0


def test_committed_denver_region_artifact_is_mountainous_if_present():
    path = os.path.join(BUNDLES, "denver_region", "region.json")
    if not os.path.exists(path):
        pytest.skip("denver region artifact not baked in this tree")
    with open(path) as f:
        region = json.load(f)
    assert region["archetype"] == "mountain_front"
    assert region["terrain_stats"]["relief_span"] > 800.0


# --------------------------------------------------------------------------- #
# Schema v2: the city plateau — the compiled city at y = 0 sits ON the ground
# --------------------------------------------------------------------------- #
def _inside_city(a):
    import numpy as np
    hm = a["heightmap"]
    h = np.array(hm["heights"])
    xs = hm["x0"] + np.arange(h.shape[1]) * hm["step_m"]
    zs = hm["z0"] + np.arange(h.shape[0]) * hm["step_m"]
    gx, gz = np.meshgrid(xs, zs)
    r = np.hypot(gx - a["extent"]["center"][0], gz - a["extent"]["center"][1])
    return h, r


def test_region_schema_v2_city_plateau_is_flat_at_datum():
    g = GeoReference(39.74, -104.99, origin_elevation=1609.0)
    a = build_region_artifact(g, "mountain_front", seed=0, datum=1609.0)
    assert a["version"] == 2
    assert a["city_plateau"]["datum_elevation"] == 1609.0
    assert a["georef"]["origin_elevation"] == 1609.0
    h, r = _inside_city(a)
    inside = r <= a["extent"]["detailed_city_radius"]
    assert inside.any()
    assert abs(h[inside] - 1609.0).max() < 0.011          # flat to rounding
    outside = r > a["extent"]["detailed_city_radius"] + a["city_plateau"]["blend_m"]
    assert (h[outside].max() - h[outside].min()) > 800.0  # mountains survive
    # No baked water inside the built city disc.
    step = a["heightmap"]["step_m"]
    for row, col in a["water_cells"]:
        x = a["heightmap"]["x0"] + col * step
        z = a["heightmap"]["z0"] + row * step
        assert (x * x + z * z) ** 0.5 > a["extent"]["detailed_city_radius"]


def test_region_plateau_datum_defaults_to_mean_city_height():
    g = GeoReference(29.82, -95.46)
    a = build_region_artifact(g, "coastal_plain", seed=0)
    d = a["city_plateau"]["datum_elevation"]
    assert a["georef"]["origin_elevation"] == pytest.approx(d, abs=0.01)
    h, r = _inside_city(a)
    assert abs(h[r <= 3000.0] - d).max() < 0.011


def test_committed_bundles_carry_v2_region_with_provenance():
    for city in ("houston", "madisonville_tx", "austin", "san_antonio",
                 "boulder", "denver_region"):
        path = os.path.join(BUNDLES, city, "region.json")
        if not os.path.exists(path):
            pytest.skip(f"{city} bundle absent")
        with open(path) as f:
            a = json.load(f)
        assert a["version"] == 2, city
        assert a["provenance"]["terrain"] == "synthetic", city
        assert a["city_plateau"]["datum_elevation"] == pytest.approx(
            a["georef"]["origin_elevation"], abs=0.01), city

"""Compiled-world citizen baking + spawn anchor contracts (mission §19-20)."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.osm_city.citizens import build_population_from_compiled
from asphodel.osm_city.world_from_compiled import (
    SpawnAnchors,
    has_compiled_world,
    street_map_from_compiled,
)

_BUNDLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "godot", "bundles")
_HOUSTON = os.path.join(_BUNDLES, "houston")


def test_compiled_world_present():
    assert has_compiled_world(_HOUSTON)
    assert has_compiled_world(os.path.join(_BUNDLES, "madisonville_tx"))


def test_street_map_ids_align_with_buildings_json():
    sm = street_map_from_compiled(_HOUSTON)
    with open(os.path.join(_HOUSTON, "buildings.json")) as f:
        bjson = json.load(f)["buildings"]
    by_id = sm.by_id()
    assert len(sm.buildings) > 20000
    # Building.id is the buildings.json array index (the authoritative
    # building_id every interior/container hash keys on).
    for bid in (0, 100, 5000, len(bjson) - 1):
        if bid in by_id:
            b = by_id[bid]
            ring = bjson[bid]["poly"]
            assert abs(b.centroid[0]
                       - sum(p[0] for p in ring) / len(ring)) < 1e-6


def test_entrance_anchors_cover_street_map_buildings():
    sm = street_map_from_compiled(_HOUSTON)
    anchors = SpawnAnchors(_HOUSTON, sm)
    missing = [b.id for b in sm.buildings
               if anchors.entrance(b.id) is None]
    # Anchor sanitization may drop a handful of unsalvageable entrances
    # (buildings wholly enclosed by other footprints); citizens fall back
    # to walk anchors there.  It must stay a rounding error.
    assert len(missing) / len(sm.buildings) < 0.005, len(missing)


def test_bake_deterministic_and_anchored():
    a = build_population_from_compiled(_HOUSTON, "Houston", n=25, seed=3)
    b = build_population_from_compiled(_HOUSTON, "Houston", n=25, seed=3)
    assert a == b
    for r in a:
        assert r["spawn_xy"] is not None
        assert r["spawn_anchor"] in ("entrance", "route", "walk")
        assert r["spawn_anchor"] != "fallback"


def test_commute_spawns_are_routed_not_straightline():
    sm = street_map_from_compiled(_HOUSTON)
    anchors = SpawnAnchors(_HOUSTON, sm)
    home = (-2000.0, -2000.0)
    work = (2000.0, 2500.0)
    (x, z), approx = anchors.commute_point(home, work, 0.5)
    assert not approx
    # The routed midpoint must sit on the road graph (near some edge), and
    # for a diagonal trip across a grid city it should differ measurably
    # from the straight-line midpoint.
    mid = ((home[0] + work[0]) / 2.0, (home[1] + work[1]) / 2.0)
    assert (x - mid[0]) ** 2 + (z - mid[1]) ** 2 > 25.0
    best = min(
        (xn - x) ** 2 + (zn - z) ** 2
        for xn, zn in sm.nodes.values())
    assert best < 200.0 ** 2  # on/near the graph, not floating in a yard


def test_compile_writes_only_presentation_files(tmp_path):
    """The exterior compiler must never touch simulation truth files."""
    from asphodel.world_source.compile import compile_city
    out = tmp_path / "bundle"
    out.mkdir()
    compile_city("madisonville_tx", "2026-08-19.0", seed=0,
                 out_dir=str(out))
    written = set()
    for root, _, files in os.walk(out):
        for f in files:
            written.add(os.path.relpath(os.path.join(root, f), out))
    assert "buildings.json" in written
    for sim_file in ("zones.json", "timeline.json", "mobility.json",
                     "meta.json", "roads.json"):
        assert sim_file not in written
    assert any(w.startswith("world/chunks/") for w in written)

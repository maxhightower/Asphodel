"""
World layer tests: street map + categorised buildings + procedural interiors,
and the world-resolved citizen spawn (citizens in real buildings).

Run with:  python -m pytest tests/test_world.py -q
       or:  python tests/test_world.py        (dependency-free smoke run)

Covers:

* OSM tag -> category mapping precedence,
* deterministic procedural synthesis (same spec+seed => identical map),
* street graph connectivity and finite street-routed distances,
* building invariants (residential hosts no workplace; capacity > 0),
* deterministic procedural interiors with rooms on every floor,
* resolve_world (the choose-a-city -> populated-world step),
* world-resolved spawn: homes are residential buildings, work hosts the
  occupation's category, zones derive from building position, commute is
  street-routed, and the spawn is deterministic / city-biased,
* the OSM seam fails loudly (not silently) when its toolchain is absent.
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.world import (
    SynthCitySpec, OSMSource, RESIDENTIAL, INDUSTRIAL, MEDICAL,
    synthesize_city, generate_interior, category_from_osm_tags, load_osm,
)
from asphodel.citizen import (
    default_catalog, default_cities, resolve_world,
    spawn_population_in_world, HOME,
)


CATALOG = default_catalog()


# --------------------------------------------------------------------------- #
# OSM tag mapping
# --------------------------------------------------------------------------- #
def test_osm_tag_category_precedence():
    assert category_from_osm_tags({"amenity": "hospital", "building": "yes"}) == MEDICAL
    assert category_from_osm_tags({"landuse": "industrial"}) == INDUSTRIAL
    assert category_from_osm_tags({"building": "apartments"}) == RESIDENTIAL
    assert category_from_osm_tags({"shop": "bakery"}) == "commercial"
    assert category_from_osm_tags({"amenity": "university"}) == "education"
    assert category_from_osm_tags({"railway": "station"}) == "transit"
    # Untagged footprint defaults to residential; a truly unknown feature is None.
    assert category_from_osm_tags({"building": "yes"}) == RESIDENTIAL
    assert category_from_osm_tags({"natural": "water"}) is None


# --------------------------------------------------------------------------- #
# procedural synthesis
# --------------------------------------------------------------------------- #
def test_synthesis_is_deterministic():
    spec = SynthCitySpec(blocks_x=5, blocks_y=4)
    a = synthesize_city(spec, seed=3)
    b = synthesize_city(spec, seed=3)
    assert len(a.buildings) == len(b.buildings)
    for x, y in zip(a.buildings, b.buildings):
        assert (x.category, x.centroid, x.levels) == (y.category, y.centroid, y.levels)


def test_synthesis_graph_connected_and_routable():
    sm = synthesize_city(SynthCitySpec(blocks_x=4, blocks_y=4), seed=0)
    nodes = list(sm.nodes)
    # Every node reachable from node 0 (a grid is connected).
    d = sm.route_length(nodes[0], nodes[-1])
    assert math.isfinite(d) and d > 0
    # Nearest-node lookup returns an actual node.
    assert sm.nearest_node((10.0, 10.0)) in sm.nodes


def test_building_invariants():
    sm = synthesize_city(SynthCitySpec(), seed=1)
    assert sm.buildings, "no buildings generated"
    for b in sm.buildings:
        assert b.capacity > 0
        assert b.area > 0 and b.levels >= 1
        if b.category == RESIDENTIAL:
            assert b.workplaces == []
        else:
            assert b.workplaces == [b.category]
    # A default-zoned city contains housing and at least one workplace category.
    cats = sm.categories_present()
    assert RESIDENTIAL in cats
    assert cats - {RESIDENTIAL}


# --------------------------------------------------------------------------- #
# procedural interiors
# --------------------------------------------------------------------------- #
def test_interior_is_deterministic_and_populated():
    sm = synthesize_city(SynthCitySpec(), seed=2)
    b = sm.buildings[0]
    i1 = generate_interior(b, seed=5)
    i2 = generate_interior(b, seed=5)
    assert len(i1.levels) == b.levels
    assert i1.room_count == i2.room_count and i1.room_count >= b.levels
    for floor in i1.levels:
        assert floor, "a floor has no rooms"


# --------------------------------------------------------------------------- #
# resolve_world + world-resolved spawn
# --------------------------------------------------------------------------- #
def test_resolve_world_uses_synth_fallback():
    cw = resolve_world(default_cities()["generic"], seed=0)
    assert cw.street_map.source.startswith("synthetic")
    assert cw.street_map.buildings


def test_world_spawn_places_citizens_in_real_buildings():
    cw = resolve_world(default_cities()["harbor"], seed=0)
    sm = cw.street_map
    by_id = sm.by_id()
    for c in spawn_population_in_world(cw, CATALOG, n=60, seed=1):
        # Home is a real residential building.
        assert c.home_building_id in by_id
        assert by_id[c.home_building_id].is_residential
        assert c.home_xy == by_id[c.home_building_id].centroid
        assert c.home_zone == cw.zone_of_xy(c.home_xy)
        # Work, when present, hosts the occupation's category.
        occ = next((o for o in CATALOG.occupations if o.name == c.occupation), None)
        if occ is not None and occ.workplace not in (HOME, ""):
            assert c.work_building_id in by_id
            assert occ.workplace in by_id[c.work_building_id].workplaces
            assert c.commute_metres is None or c.commute_metres >= 0
        else:
            assert c.work_building_id is None


def test_world_spawn_is_deterministic():
    cw = resolve_world(default_cities()["generic"], seed=0)
    a = spawn_population_in_world(cw, CATALOG, n=30, seed=7)
    b = spawn_population_in_world(cw, CATALOG, n=30, seed=7)
    assert [c.to_dict() for c in a] == [c.to_dict() for c in b]


def test_world_spawn_respects_city_bias():
    """The harbor's industrial-heavy map + multipliers spawn more dock workers
    than the balanced generic city -- the bias survives the move to buildings."""
    gen = resolve_world(default_cities()["generic"], seed=0)
    har = resolve_world(default_cities()["harbor"], seed=0)
    g = Counter(c.occupation for c in spawn_population_in_world(gen, CATALOG, 300, seed=0))
    h = Counter(c.occupation for c in spawn_population_in_world(har, CATALOG, 300, seed=0))
    assert h["dock_worker"] > g["dock_worker"]


def test_city_yaml_round_trip_carries_world_source():
    import tempfile
    from asphodel.citizen import CityProfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harbor.yaml")
        default_cities()["harbor"].to_yaml(path)
        back = CityProfile.from_yaml(path)
    assert back.synth is not None
    # The reloaded source reproduces the same world + spawn.
    a = spawn_population_in_world(resolve_world(default_cities()["harbor"], 0), CATALOG, 20, 1)
    b = spawn_population_in_world(resolve_world(back, 0), CATALOG, 20, 1)
    assert [c.to_dict() for c in a] == [c.to_dict() for c in b]


def test_osm_seam_fails_loudly_without_toolchain():
    """load_osm must raise a clear error (never silently return junk) when the
    GIS toolchain / network isn't available -- so callers know to synthesize."""
    try:
        import osmnx  # noqa: F401
        return  # toolchain present: the seam would attempt real work; skip.
    except Exception:
        pass
    raised = False
    try:
        load_osm(OSMSource(place="Nowhere"))
    except (RuntimeError, NotImplementedError):
        raised = True
    assert raised


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

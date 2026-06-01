"""
Travel-event & location-aware resolution tests: road structures, the in-transit
event catalogue, and the commute-caught branch of resolve_collapse_situation.

Run with:  python -m pytest tests/test_travel_events.py -q
       or:  python tests/test_travel_events.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.world import (
    synthesize_city, SynthCitySpec, structure_from_osm_tags,
    SURFACE, HIGHWAY, BRIDGE, TUNNEL, RAMP,
)
from asphodel.vehicles import RoadNetwork, STRUCT_CAPACITY, vehicle_class
from asphodel.travel_events import default_travel_events, select_travel_event
from asphodel.citizen import (
    default_catalog, default_cities, resolve_world,
    spawn_population_in_world, resolve_collapse_situation,
)


CATALOG = default_catalog()


def _commute_midpoint(schedule):
    for e in schedule:
        if e.activity == "commute":
            mid = (e.start_hour + e.end_hour) / 2.0
            return mid % 24.0
    return None


# --------------------------------------------------------------------------- #
# road structures
# --------------------------------------------------------------------------- #
def test_osm_structure_mapping():
    assert structure_from_osm_tags({"tunnel": "yes"}) == TUNNEL
    assert structure_from_osm_tags({"bridge": "yes"}) == BRIDGE
    assert structure_from_osm_tags({"highway": "motorway"}) == HIGHWAY
    assert structure_from_osm_tags({"highway": "motorway_link"}) == RAMP
    assert structure_from_osm_tags({"highway": "residential"}) == SURFACE


def test_synth_map_has_varied_structures():
    sm = synthesize_city(SynthCitySpec(blocks_x=6, blocks_y=6), seed=0)
    found = {sm.edge_structure(u, v) for (u, v, _) in sm.edges}
    # The generator lays a ring road, a river of bridges, a tunnel and ramps.
    assert {HIGHWAY, BRIDGE, TUNNEL} <= found
    # Untagged segments default to surface.
    assert SURFACE in found


def test_structure_changes_road_capacity():
    sm = synthesize_city(SynthCitySpec(), seed=0)
    road = RoadNetwork.from_street_map(sm)
    caps_by_struct = {}
    for (u, v, _) in sm.edges:
        s = sm.edge_structure(u, v)
        key = (u, v) if u <= v else (v, u)
        caps_by_struct.setdefault(s, road.capacity[key])
    # Bridges/tunnels are chokepoints; highways carry more than surface streets.
    assert caps_by_struct[BRIDGE] < caps_by_struct[SURFACE]
    assert caps_by_struct[HIGHWAY] > caps_by_struct[SURFACE]


# --------------------------------------------------------------------------- #
# event selection
# --------------------------------------------------------------------------- #
def test_select_matches_structure_and_vehicle():
    rng = np.random.default_rng(0)
    # On a bridge in a car -> a bridge-or-any event.
    ev = select_travel_event(rng, BRIDGE, "car")
    assert BRIDGE in ev.structures
    # On a ramp in a car -> the flyover event is the only ramp-specific one.
    assert select_travel_event(np.random.default_rng(1), RAMP, "car").name \
        == "Stranded on the flyover"
    # Non-motorized always gets the on-foot event regardless of structure.
    ev = select_travel_event(np.random.default_rng(2), HIGHWAY, "bicycle")
    assert ev.vehicles == "nonmotorized"


def test_select_is_deterministic():
    a = select_travel_event(np.random.default_rng(5), SURFACE, "car")
    b = select_travel_event(np.random.default_rng(5), SURFACE, "car")
    assert a.name == b.name


def test_vehicle_class():
    assert vehicle_class("foot") == "nonmotorized"
    assert vehicle_class("bus") == "transit"
    assert vehicle_class("truck") == "motorized"


def test_every_event_has_dilemma_and_tags():
    for e in default_travel_events():
        assert e.situation and e.dilemma and e.tags
        assert e.severity >= 1


# --------------------------------------------------------------------------- #
# location-aware resolution
# --------------------------------------------------------------------------- #
def test_commute_resolves_to_a_travel_event():
    cw = resolve_world(default_cities()["capital"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=400, seed=0)
    checked = 0
    for c in pop:
        mid = _commute_midpoint(c.schedule)
        if mid is None:
            continue
        sit = resolve_collapse_situation(c, collapse_hour=mid, world=cw)
        assert sit.kind == "travel" and sit.context == "commute"
        assert sit.fired and sit.tags
        assert sit.structure in (SURFACE, HIGHWAY, BRIDGE, TUNNEL, RAMP)
        # On-hand inventory carried into the event.
        if c.inventory:
            assert any(a.startswith("on you:") for a in sit.assets)
        checked += 1
    assert checked > 20


def test_commute_event_is_road_aware_and_deterministic():
    cw = resolve_world(default_cities()["capital"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=400, seed=0)
    c = next(c for c in pop if _commute_midpoint(c.schedule) is not None)
    mid = _commute_midpoint(c.schedule)
    a = resolve_collapse_situation(c, mid, world=cw)
    b = resolve_collapse_situation(c, mid, world=cw)
    assert a == b
    # The chosen event must be valid for the structure it reported.
    assert a.structure in a_structures(a)


def a_structures(sit):
    for e in default_travel_events():
        if e.name == sit.title:
            return e.structures
    return ()


def test_commute_without_world_still_gives_travel_event():
    cw = resolve_world(default_cities()["generic"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=200, seed=1)
    c = next(c for c in pop if _commute_midpoint(c.schedule) is not None)
    mid = _commute_midpoint(c.schedule)
    sit = resolve_collapse_situation(c, mid, world=None)   # no road awareness
    assert sit.kind == "travel" and sit.fired


def test_workplace_still_signature_and_errand_generic():
    cw = resolve_world(default_cities()["capital"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=300, seed=2)
    saw_work = saw_errand = False
    for c in pop:
        for e in c.schedule:
            mid = (e.start_hour + e.end_hour) / 2.0 % 24.0
            sit = resolve_collapse_situation(c, mid, world=cw)
            if e.activity == "work" and sit.kind == "signature":
                assert sit.context == "workplace"
                saw_work = True
            if e.activity == "errand" and not sit.fired:
                assert sit.context == "errand" and sit.kind == "generic"
                saw_errand = True
    assert saw_work and saw_errand


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

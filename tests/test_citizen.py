"""
Citizen spawn tests: the possibility space a player can be dropped into.

Run with:  python -m pytest tests/test_citizen.py -q
       or:  python tests/test_citizen.py     (dependency-free smoke run)

Covers the invariants the feature promises:

* determinism from (city + catalog + seed),
* age-eligibility of the sampled occupation,
* every spawned occupation's workplace is actually hosted by the city,
* the schedule is well-formed (time-ordered, non-empty, valid locations) and the
  spawn clock lands the citizen inside a real block,
* home / work resolve to macro grid zones when districts are pinned,
* inventories are non-negative integers,
* the *agnostic-but-city-biased* contract: a city's multipliers shift the
  occupation mix in the expected direction without removing possibilities,
* a city only offers occupations whose workplace it hosts,
* YAML round-trip of both the catalog and a city.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.citizen import (
    CityProfile, District, HOME,
    spawn_citizen, spawn_population,
    default_catalog, default_cities,
)


CATALOG = default_catalog()
CITIES = default_cities()


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def test_spawn_is_deterministic():
    a = spawn_citizen(CITIES["generic"], CATALOG, seed=42)
    b = spawn_citizen(CITIES["generic"], CATALOG, seed=42)
    assert a.to_dict() == b.to_dict()


def test_population_is_deterministic_and_order_stable():
    p1 = spawn_population(CITIES["harbor"], CATALOG, n=50, seed=7)
    p2 = spawn_population(CITIES["harbor"], CATALOG, n=50, seed=7)
    assert [c.to_dict() for c in p1] == [c.to_dict() for c in p2]
    # Order-stable regardless of crowd size: citizen i is the same in n=10 / n=50.
    p_small = spawn_population(CITIES["harbor"], CATALOG, n=10, seed=7)
    for i in range(10):
        assert p_small[i].to_dict() == p1[i].to_dict()


def test_different_seeds_differ():
    a = spawn_population(CITIES["generic"], CATALOG, n=30, seed=0)
    b = spawn_population(CITIES["generic"], CATALOG, n=30, seed=1)
    assert [c.occupation for c in a] != [c.occupation for c in b]


# --------------------------------------------------------------------------- #
# per-citizen validity
# --------------------------------------------------------------------------- #
def _occ_by_name(name):
    for o in CATALOG.occupations:
        if o.name == name:
            return o
    return None


def test_occupation_age_eligible():
    for city in CITIES.values():
        for c in spawn_population(city, CATALOG, n=80, seed=3):
            occ = _occ_by_name(c.occupation)
            if occ is None:
                continue  # the synthetic idle fallback
            assert occ.min_age <= c.age <= occ.max_age, (c.occupation, c.age)


def test_work_location_hosts_the_occupation():
    for city in CITIES.values():
        hosting = {d.name: set(d.workplaces) for d in city.districts}
        for c in spawn_population(city, CATALOG, n=80, seed=5):
            occ = _occ_by_name(c.occupation)
            if occ is None or occ.workplace in (HOME, ""):
                assert c.work_district is None
                continue
            assert c.work_district is not None
            assert occ.workplace in hosting[c.work_district], (
                c.occupation, occ.workplace, c.work_district)


def test_schedule_is_well_formed():
    city = CITIES["generic"]
    valid_locs = {d.name for d in city.districts}
    for c in spawn_population(city, CATALOG, n=60, seed=11):
        assert c.schedule, "empty schedule"
        prev = -1.0
        for e in c.schedule:
            assert e.end_hour > e.start_hour
            assert e.start_hour >= prev - 1e-9, "schedule not time-ordered"
            prev = e.start_hour
            assert e.location in valid_locs, e.location
        # The spawn clock must land inside a real block.
        assert c.current_location in valid_locs
        assert c.current_activity


def test_home_and_work_resolve_to_zones():
    city = CITIES["capital"]  # all districts pinned to grid zones
    zone_of = {d.name: d.zone for d in city.districts}
    for c in spawn_population(city, CATALOG, n=40, seed=2):
        assert c.home_zone == zone_of[c.home_district]
        if c.work_district is not None:
            assert c.work_zone == zone_of[c.work_district]
        else:
            assert c.work_zone is None


def test_inventory_non_negative_ints():
    for c in spawn_population(CITIES["generic"], CATALOG, n=60, seed=9):
        for item, qty in c.inventory.items():
            assert isinstance(qty, int) and qty > 0, (item, qty)


def test_fixed_spawn_hour_param():
    cat = default_catalog()
    cat.params.spawn_hour = 9.0
    for c in spawn_population(CITIES["generic"], cat, n=20, seed=4):
        assert c.spawn_hour == 9.0


# --------------------------------------------------------------------------- #
# the central contract: agnostic, but slightly determined by the city
# --------------------------------------------------------------------------- #
def test_city_biases_occupation_mix():
    """A harbor spawns more dock workers than the balanced generic city, and a
    university town spawns more students -- but neither removes the other's
    possibilities outright (only the city's *map* can gate reachability)."""
    n = 400
    gen = Counter(c.occupation for c in spawn_population(CITIES["generic"], CATALOG, n, seed=0))
    harb = Counter(c.occupation for c in spawn_population(CITIES["harbor"], CATALOG, n, seed=0))
    uni = Counter(c.occupation for c in spawn_population(CITIES["university"], CATALOG, n, seed=0))

    assert harb["dock_worker"] > gen["dock_worker"]
    assert uni["student"] > gen["student"]
    # Office work is reachable everywhere (commercial/civic exist), so the
    # de-emphasised harbor still spawns *some* -- nothing is hard-removed.
    assert harb["office_worker"] > 0


def test_city_without_workplace_offers_no_such_job():
    """An occupation whose workplace category no district hosts is simply never
    spawned -- the agnostic catalog is gated by the city's map, not edited."""
    landlocked = CityProfile(
        name="hamlet",
        districts=[
            District("Cottages", "residential", 1.0, [], zone=0),
            District("Square", "commercial", 0.3, ["commercial"], zone=1),
            # no industrial / medical / education / civic / transit districts
        ],
    )
    occs = {c.occupation for c in spawn_population(landlocked, CATALOG, n=200, seed=0)}
    # Industrial / medical / etc. jobs cannot appear here...
    assert "dock_worker" not in occs
    assert "nurse" not in occs
    assert "teacher" not in occs
    # ...while home-anchored and commercial roles still can.
    assert occs & {"grocery_clerk", "chef", "office_worker", "retiree",
                   "unemployed", "child"}


# --------------------------------------------------------------------------- #
# YAML round-trip (config-as-data)
# --------------------------------------------------------------------------- #
def test_catalog_yaml_round_trip():
    from asphodel.citizen import CitizenSpawnCatalog
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "catalog.yaml")
        CATALOG.to_yaml(path)
        back = CitizenSpawnCatalog.from_yaml(path)
    assert [o.name for o in back.occupations] == [o.name for o in CATALOG.occupations]
    assert back.common_items == CATALOG.common_items
    assert back.params.day_start == CATALOG.params.day_start


def test_city_yaml_round_trip_reproduces_spawn():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "city.yaml")
        CITIES["harbor"].to_yaml(path)
        back = CityProfile.from_yaml(path)
    a = spawn_population(CITIES["harbor"], CATALOG, n=25, seed=1)
    b = spawn_population(back, CATALOG, n=25, seed=1)
    assert [c.to_dict() for c in a] == [c.to_dict() for c in b]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

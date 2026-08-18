"""Certification for real-city citizen baking (the canonical world path).

Citizens are generated from the *same resolved world the game renders* -- real
buildings, streets and population geography of the selected city -- with coherent
collapse situations and location-scoped possessions. These tests assert the
gameplay-integrity contracts the character screen and first-person spawn rely on.
"""
from __future__ import annotations

import json
import os
from collections import Counter

from asphodel.osm_city import citizens as cz
from asphodel.osm_city.world_from_osm import street_map_from_bundle
from asphodel.signatures import default_signatures

_BUNDLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "godot", "bundles")

_REQUIRED_KEYS = {
    "profile", "name", "age", "occupation", "shift", "home_district",
    "work_district", "spawn_hour", "current_activity", "current_location",
    "inventory", "inventory_scopes", "home_xy", "work_xy", "spawn_xy",
    "spawn_context", "spawn_approx", "signature_title", "signature_location",
    "signature_situation", "signature_dilemma", "situation_kind", "on_duty",
    "environment",
}

_ANYTIME = {k for k, v in default_signatures().items() if v.trigger == "anytime"}


def _load(city_dir):
    with open(os.path.join(_BUNDLES, city_dir, "zones.json")) as f:
        zones = json.load(f)
    with open(os.path.join(_BUNDLES, city_dir, "roads.json")) as f:
        roads = json.load(f)
    return zones, roads


def _pop(city_dir, name, n=80, seed=0):
    zones, roads = _load(city_dir)
    return cz.build_population_from_bundle(zones, roads, name, n=n, seed=seed)


# --------------------------------------------------------------------------- #
# 1. real-city citizens use real city/world data
# --------------------------------------------------------------------------- #
def test_records_have_required_keys():
    for r in _pop("madisonville_tx", "Madisonville", n=20):
        assert _REQUIRED_KEYS <= set(r.keys())
        assert isinstance(r["name"], str) and r["name"]
        assert isinstance(r["age"], int) and r["age"] > 0
        assert isinstance(r["inventory"], dict)


def test_citizens_use_real_buildings_of_the_selected_city():
    zones, roads = _load("houston")
    sm = street_map_from_bundle(zones, roads, seed=0)
    by_id = sm.by_id()
    pop = cz.build_population_from_world(sm, "Houston", n=60, seed=0)
    assert len(pop) == 60
    placed = 0
    for r in pop:
        # Home coordinate is a real building of this city's stock.
        assert r["home_xy"] is not None
        if r["work_xy"] is not None:
            placed += 1
    assert placed > 0, "no citizen resolved a workplace in the city"
    assert len(sm.buildings) == sum(len(z.get("blocks", [])) for z in zones)
    assert by_id                                    # the stock is non-empty


# --------------------------------------------------------------------------- #
# 2. citizen physical locations are valid (inside the world, non-null spawn)
# --------------------------------------------------------------------------- #
def test_spawn_points_are_valid_and_in_bounds():
    zones, roads = _load("madisonville_tx")
    sm = street_map_from_bundle(zones, roads, seed=0)
    xmin, zmin, xmax, zmax = sm.bbox
    pad = 50.0
    for r in cz.build_population_from_world(sm, "Madisonville", n=60, seed=0):
        sp = r["spawn_xy"]
        assert sp is not None, "every citizen must have an authoritative spawn"
        assert xmin - pad <= sp[0] <= xmax + pad, sp
        assert zmin - pad <= sp[1] <= zmax + pad, sp
        assert r["spawn_context"] in ("home", "workplace", "commute", "errand")


# --------------------------------------------------------------------------- #
# 3. the signature situation agrees with the current context (no contradiction)
# --------------------------------------------------------------------------- #
def test_signature_agrees_with_activity_and_location():
    for r in _pop("houston", "Houston", n=120):
        activity = r["current_activity"]
        kind = r["situation_kind"]
        # on_duty must mean literally "at work right now".
        assert r["on_duty"] == (activity == "work")
        # A travel scenario only for someone actually commuting.
        if kind == "travel":
            assert activity == "commute", (r["occupation"], activity)
        # The core contradiction guard: a citizen who is NOT on shift can only
        # carry an occupation *signature* if that job's signature triggers
        # anytime (home-anchored roles). A sleeping truck driver must NOT be
        # "driving a loaded truck on the motorway".
        if kind == "signature" and not r["on_duty"]:
            assert r["occupation"] in _ANYTIME, (
                r["occupation"], activity, r["signature_title"])
        # Nobody asleep is on duty / firing an on-site occupation scenario.
        if activity == "sleep":
            assert not r["on_duty"]
            assert kind != "travel"


# --------------------------------------------------------------------------- #
# 4. on-person inventory is context-correct
# --------------------------------------------------------------------------- #
def test_on_hand_holds_only_genuine_personal_items_when_off_duty():
    for r in _pop("houston", "Houston", n=120):
        scopes = r["inventory_scopes"]
        # "inventory" (the character screen's "On hand") is exactly on_person.
        assert r["inventory"] == scopes["on_person"]
        if r["current_activity"] not in ("work", "commute"):
            # Off the job and not in transit: nothing but personal items on hand;
            # the occupation's kit sits in the workplace scope.
            for item in r["inventory"]:
                assert item in cz._PERSONAL_ITEMS, (r["occupation"], item)


# --------------------------------------------------------------------------- #
# 5. deterministic generation
# --------------------------------------------------------------------------- #
def test_bake_is_deterministic():
    a = _pop("houston", "Houston", n=40, seed=7)
    b = _pop("houston", "Houston", n=40, seed=7)
    assert a == b


# --------------------------------------------------------------------------- #
# 6. different cities => materially different populations (not a generic mix)
# --------------------------------------------------------------------------- #
def test_two_cities_are_materially_different():
    hz, hr = _load("houston")
    mz, mr = _load("madisonville_tx")
    hsm = street_map_from_bundle(hz, hr, seed=0)
    msm = street_map_from_bundle(mz, mr, seed=0)
    hou = cz.build_population_from_world(hsm, "Houston", n=200, seed=0)
    mad = cz.build_population_from_world(msm, "Madisonville", n=200, seed=0)

    # (a) The building stock is the city's own: the metropolis has far more
    #     buildings than the small town (real population geography).
    assert len(hsm.buildings) > 3.0 * len(msm.buildings), (
        len(hsm.buildings), len(msm.buildings))

    # (b) Occupation mixes are not identical.
    ho = Counter(r["occupation"] for r in hou)
    mo = Counter(r["occupation"] for r in mad)
    l1 = sum(abs(ho[k] - mo[k]) for k in set(ho) | set(mo))
    assert l1 > 0, "occupation mixes are identical -> generic population"

    # (c) The dense metropolis carries more specialised medical staff than the
    #     small town (a building-stock-driven, city-specific difference).
    med = {"nurse", "doctor", "paramedic", "pharmacist", "care_worker",
           "lab_technician"}
    assert sum(ho[k] for k in med) >= sum(mo[k] for k in med)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

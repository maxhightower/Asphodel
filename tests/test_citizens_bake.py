"""Tests for baking a spawnable citizen population into a bundle."""
from __future__ import annotations

from asphodel.osm_city import citizens as cz

_REQUIRED_KEYS = {
    "profile", "name", "age", "occupation", "shift", "home_district",
    "work_district", "spawn_hour", "current_activity", "current_location",
    "inventory", "signature_title", "signature_location",
    "signature_situation", "signature_dilemma",
}


def test_population_count_and_profiles():
    pop = cz.build_citizen_population("cities", n_per_profile=5, seed=0)
    assert len(pop) == 5 * len(cz.DEFAULT_PROFILES)
    assert {r["profile"] for r in pop} == set(cz.DEFAULT_PROFILES)


def test_records_have_required_keys_and_types():
    pop = cz.build_citizen_population("cities", n_per_profile=3, seed=1)
    for r in pop:
        assert _REQUIRED_KEYS <= set(r.keys())
        assert isinstance(r["name"], str) and r["name"]
        assert isinstance(r["age"], int) and r["age"] > 0
        assert isinstance(r["inventory"], dict)


def test_signatures_attached_for_common_jobs():
    # At least some citizens carry a non-empty signature title.
    pop = cz.build_citizen_population("cities", n_per_profile=20, seed=2)
    assert any(r["signature_title"] for r in pop)


def test_bake_is_deterministic():
    a = cz.build_citizen_population("cities", n_per_profile=8, seed=7)
    b = cz.build_citizen_population("cities", n_per_profile=8, seed=7)
    assert a == b

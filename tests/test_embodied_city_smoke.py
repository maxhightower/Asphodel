"""Per-city smoke test of the embodied mobility runtime (ASPHODEL_EMBODIED_MOBILITY_V1).

The reduced form of ``tools/mobility_city_smoke.py``: 1 game hour from 05:00 and
3 sampled commuters per city. A bundle without a compiled world (no
``world/spawn_anchors.json.gz``) carries nothing to embody and is skipped.
"""
from __future__ import annotations

import pytest

from tools.mobility_city_smoke import has_compiled_world, smoke_city

try:
    from asphodel.bridge.worldfactory import resolve_bundle_dir
except Exception as exc:                                   # pragma: no cover
    pytest.skip(f"asphodel unavailable: {exc}", allow_module_level=True)

CITIES = ["houston", "madisonville_tx", "san_antonio"]
# One hour of the morning commute: the window in which the schedule actually
# moves people (nothing is scheduled to travel before ~07:00).
START_HOUR = 7.0
RUN_HOURS = 1.0
SAMPLE_N = 3


@pytest.fixture(scope="module")
def smoke():
    """One runtime smoke per city, shared by the assertions below."""
    cache = {}

    def get(city):
        if city not in cache:
            try:
                bundle_dir = resolve_bundle_dir(city)
            except FileNotFoundError:
                pytest.skip(f"no bundle for {city}")
            if not has_compiled_world(bundle_dir):
                pytest.skip(f"{city} has no compiled world (world/spawn_anchors.json.gz)")
            cache[city] = smoke_city(city, run_hours=RUN_HOURS, sample_n=SAMPLE_N,
                                     start_hour=START_HOUR, verbose=False)
        return cache[city]

    return get


@pytest.mark.parametrize("city", CITIES)
def test_citizens_and_vehicles_register(smoke, city):
    r = smoke(city)
    assert r["n_citizens"] > 0, f"{city}: no citizen registered"
    assert r["n_vehicles"] > 0, f"{city}: no vehicle spawned"
    # every car owner that kept its car is accounted for
    assert r["n_lost_car_no_parking"] <= r["n_citizens"]


@pytest.mark.parametrize("city", CITIES)
def test_sample_routes_and_parking_resolve(smoke, city):
    r = smoke(city)
    sample = r["sample"]
    assert r["sample_citizens"], f"{city}: no commuter to sample"
    assert not sample["errors"], f"{city}: sample checks failed: {sample['errors']}"
    for row in sample["citizens"]:
        assert row["home_entrance"], f"{city}: citizen {row['citizen_id']} home has no entrance"
        assert row["work_entrance"], f"{city}: citizen {row['citizen_id']} work has no entrance"
        assert row["foot_route"], f"{city}: citizen {row['citizen_id']} has no FOOT route"
        if row["parking_resolved"] is not None:
            assert row["parking_resolved"], f"{city}: citizen {row['citizen_id']} found no parking"
            assert row["car_route"], f"{city}: citizen {row['citizen_id']} has no CAR route"


@pytest.mark.parametrize("city", CITIES)
def test_citizens_complete_trips(smoke, city):
    r = smoke(city)
    assert r["status"] == "PASS", f"{city}: {r['reason']}"
    assert r["n_completed_trip"] >= 1, \
        f"{city}: no citizen completed a trip in {RUN_HOURS} h"
    assert r["n_trip_failed_events"] == 0, \
        f"{city}: trips failed outright: {r['failure_reasons']}"

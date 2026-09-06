"""Per-city smoke test of the smart-object / work runtime
(ASPHODEL_SMART_OBJECTS_WORK_V1).

The reduced form of ``tools/work_city_smoke.py``: one game morning
(05:00 -> 11:00) per city — long enough for the day shift to arrive, clock in,
walk to a station and change an object's state — plus a 2 game-hour
determinism check: the same city built and run twice must produce the same
event list and the same executor/ledger digest.

A bundle without a compiled world (no ``world/spawn_anchors.json.gz``) carries
nothing to embody and is skipped, as is a bundle in which nobody is employable
(no workplace whose smart objects support a job role).
"""
from __future__ import annotations

import pytest

from tools.work_city_smoke import REQUIRED_EVENTS, has_compiled_world, smoke_city

try:
    from asphodel.bridge.worldfactory import resolve_bundle_dir
except Exception as exc:                                   # pragma: no cover
    pytest.skip(f"asphodel unavailable: {exc}", allow_module_level=True)

CITIES = ["houston", "madisonville_tx", "san_antonio"]
START_HOUR = 5.0
END_HOUR = 11.0
DETERMINISM_HOURS = 2.0


@pytest.fixture(scope="module")
def smoke():
    """One work smoke per city, shared by the assertions below."""
    cache = {}

    def get(city):
        if city not in cache:
            try:
                bundle_dir = resolve_bundle_dir(city)
            except FileNotFoundError:
                pytest.skip(f"no bundle for {city}")
            if not has_compiled_world(bundle_dir):
                pytest.skip(f"{city} has no compiled world (world/spawn_anchors.json.gz)")
            cache[city] = smoke_city(city, start_hour=START_HOUR, end_hour=END_HOUR,
                                     det_hours=DETERMINISM_HOURS, verbose=False)
        r = cache[city]
        if r["status"] == "INFO":
            pytest.skip(f"{city}: {r['reason']}")
        return r

    return get


@pytest.mark.parametrize("city", CITIES)
def test_city_passes_the_work_smoke(smoke, city):
    r = smoke(city)
    assert r["status"] == "PASS", f"{city}: {r['reason']}"


@pytest.mark.parametrize("city", CITIES)
def test_citizens_are_employed_with_real_stations(smoke, city):
    """Employment is only meaningful where the workplace has smart objects."""
    r = smoke(city)
    emp, obj = r["employment"], r["objects"]
    assert r["n_citizens"] > 0
    assert emp["n_employed"] >= 1, f"{city}: nobody is employed"
    assert sum(emp["roles"].values()) == emp["n_employed"]
    assert obj["n_workplaces_with_objects"] >= 1
    assert obj["n_objects"] >= obj["registers"] + obj["desks"], \
        f"{city}: object census does not add up: {obj}"
    # a job role needs a station or a cleanable/stockable object to work through
    assert obj["registers"] + obj["desks"] + obj["shelves"] >= 1, \
        f"{city}: {emp['n_employed']} employed but no register, desk or shelf anywhere"


@pytest.mark.parametrize("city", CITIES)
def test_the_shift_actually_happens(smoke, city):
    """Somebody clocks in, uses an object and changes its state."""
    r = smoke(city)
    counts = r["story_counts"]
    for kind in REQUIRED_EVENTS:
        assert counts[kind] >= 1, \
            f"{city}: no {kind} event between {START_HOUR:.0f}:00 and {END_HOUR:.0f}:00 " \
            f"({r['employment']['n_employed']} employed); counts {counts}"
    assert r["n_workers_used_an_object"] >= 1, \
        f"{city}: {r['n_workers_clocked_in']} workers clocked in but none used an object"
    assert r["n_workers_used_an_object"] <= r["n_workers_clocked_in"]
    assert r["n_events_dropped_between_drains"] == 0, \
        f"{city}: the work event ring dropped events between drains"


@pytest.mark.parametrize("city", CITIES)
def test_reservation_invariants_hold_every_game_minute(smoke, city):
    """No exclusive object with two holders; no citizen on two exclusive objects."""
    r = smoke(city)
    inv = r["invariants"]
    assert inv["checks"] >= int((END_HOUR - START_HOUR) * 60), \
        f"{city}: the ledger was only checked {inv['checks']} times"
    assert inv["n_violations"] == 0, \
        f"{city}: reservation invariant broken {inv['n_violations']} times: " \
        f"{inv['violations'][:3]}"


@pytest.mark.parametrize("city", CITIES)
def test_run_is_deterministic(smoke, city):
    r = smoke(city)
    det = r["determinism"]
    assert det["events_identical"], \
        f"{city}: two runs of the first {det['hours']} game hours produced different " \
        f"event lists: {det['first_difference']}"
    assert det["digests_identical"], \
        f"{city}: executor/ledger digests diverged: {det['digest_run1']} vs " \
        f"{det['digest_run2']}"
    assert det["n_events_run1"] == det["n_events_run2"] > 0

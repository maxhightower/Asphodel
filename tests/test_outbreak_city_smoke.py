"""Per-city smoke test of the outbreak runtime (ASPHODEL_OUTBREAK_V1).

The reduced form of ``tools/outbreak_city_smoke.py``: one game morning
(05:00 -> 11:00) per city, long enough for the data-driven index case to walk
symptom onset -> incapacitation -> death (and reanimation, when it is
scheduled inside the window), plus a 2 game-hour determinism check — the same
city built and run twice must produce the same event list.

A bundle without a compiled world (no ``world/spawn_anchors.json.gz``) carries
nothing to embody and is skipped, as is a bundle with no workplace shared by
two day-shift workers (no data-driven index case exists there).
"""
from __future__ import annotations

import pytest

from tools.outbreak_city_smoke import has_compiled_world, smoke_city

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
    """One outbreak smoke per city, shared by the assertions below."""
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
def test_index_case_is_a_worker_with_coworkers(smoke, city):
    r = smoke(city)
    idx = r["index_case"]
    assert idx["citizen_id"] is not None, f"{city}: no index case was seeded"
    assert idx["work_building_id"] is not None, f"{city}: index case has no workplace"
    assert idx["n_registered_coworkers"] >= 1, \
        f"{city}: the data-driven index case should share its workplace"
    assert r["n_citizens"] > 0


@pytest.mark.parametrize("city", CITIES)
def test_index_case_progresses(smoke, city):
    """symptom onset -> incapacitation -> death, in order, inside the window."""
    r = smoke(city)
    prog, idx = r["progression"], r["index_case"]
    fired = prog["fired_at_hour"]
    for kind in ("SYMPTOM_ONSET", "INCAPACITATED", "DEATH"):
        assert fired[kind] is not None, \
            f"{city}: index case never reached {kind} by {END_HOUR:.0f}:00 " \
            f"(scheduled {idx['schedule_hours']})"
    assert fired["SYMPTOM_ONSET"] <= fired["INCAPACITATED"] <= fired["DEATH"], \
        f"{city}: transitions fired out of order: {fired}"
    # reanimation is only due when the record says so AND it lands in the window
    rean = idx["schedule_hours"]["reanimation"]
    if idx["will_reanimate"] and rean is not None and rean <= END_HOUR:
        assert fired["REANIMATION"] is not None, \
            f"{city}: corpse scheduled to rise at {rean}h never did"
        assert r["health"]["n_undead"] >= 1
    assert prog["final_state"] in ("incapacitated", "dead", "corpse", "undead"), \
        f"{city}: index case ended {prog['final_state']}"


@pytest.mark.parametrize("city", CITIES)
def test_run_is_deterministic(smoke, city):
    r = smoke(city)
    det = r["determinism"]
    assert det["events_identical"], \
        f"{city}: two runs of the first {det['hours']} game hours diverged: " \
        f"{det['first_difference']}"
    assert det["n_events_run1"] == det["n_events_run2"] > 0


@pytest.mark.parametrize("city", CITIES)
def test_events_and_health_are_consistent(smoke, city):
    """Every event kind seen is accounted for and health counts add up."""
    r = smoke(city)
    h, kinds = r["health"], r["events_by_kind"]
    assert kinds.get("EXPOSURE", 0) >= 1 and kinds.get("INFECTED", 0) >= 1
    assert h["n_ever_infected"] >= 1
    assert sum(h["by_state"].values()) == h["n_registered"], \
        f"{city}: health snapshot counts {h['by_state']} do not cover " \
        f"{h['n_registered']} registered citizens"
    # onward transmission is reported, never required (sparse bundles have no
    # shared workplaces for the pathogen to use)
    assert r["onward"]["n_onward_exposures"] >= 0
    assert r["n_events_dropped_between_drains"] == 0, \
        f"{city}: the runtime event ring dropped events between drains"

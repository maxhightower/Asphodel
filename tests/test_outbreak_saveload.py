"""Save/load of the outbreak at four biologically different moments (§10).

The world is saved while the index case is incubating, while it is symptomatic,
while it is a corpse waiting to rise, and after it has risen. Each save goes
through JSON and comes back as a fresh World the way a session restores one:

    load_world -> set_spatial_context -> enable_mobility -> enable_outbreak

The restored world must BE the world: identical health records, identical event
trace, identical disrupted buildings, identical executor overrides — and a ten
game-minute continuation of both must produce byte-identical save state. And
because restoring re-enters ``enable_outbreak``, the index case must not be
seeded a second time: no citizen ever gets two INFECTED events.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.outbreak.health import HealthState
from asphodel.save import load_world, world_state

CITY = "houston"
INDEX = 42
START_HOUR = 5.0
CONTINUE_S = 10 * 60.0
MAX_MINUTES = 7 * 60          # 05:00 -> 12:00 is plenty for the whole chain
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
PHASES = ("incubation", "symptomatic", "corpse", "undead")


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _state(w):
    return json.loads(json.dumps(world_state(w, bundle=CITY, player_citizen=None)))


def _reload(state, d):
    w = load_world(json.loads(json.dumps(state)))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_outbreak()
    return w


def _fingerprint(ob):
    return {
        "now_s": round(ob.now_s, 3),
        "records": {c: r.to_state() for c, r in sorted(ob.records.items())},
        "events": list(ob.events),
        "event_seq": ob.event_seq,
        "disrupted": {int(k): v for k, v in ob.disrupted_buildings.items()},
        "obstructions": list(ob.obstructions),
        "counts": ob.snapshot(max_events=0)["counts"],
    }


def _overrides(w, ob):
    return {c: w.mobility.execs[c].override for c in sorted(ob.records)}


def _phase_of(ob):
    st = ob.records[INDEX].state
    if st is HealthState.INCUBATING:
        return "incubation"
    if st is HealthState.SYMPTOMATIC:
        return "symptomatic"
    if st is HealthState.CORPSE:
        return "corpse"
    if st is HealthState.UNDEAD:
        return "undead"
    return None


@pytest.fixture(scope="module")
def checkpoints():
    """Advance one world through the whole chain, saving + restoring + comparing
    at each of the four phases."""
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    ob = w.enable_outbreak("classic_zombie", index_case=INDEX)
    out = {}
    minutes = 0
    while len(out) < len(PHASES) and minutes < MAX_MINUTES:
        # the incubation checkpoint is taken at ~07:00, the others as they arrive
        phase = _phase_of(ob)
        want = (phase == "incubation" and ob.now_s >= 2 * 3600.0) or \
               (phase in PHASES and phase != "incubation")
        if want and phase not in out:
            state = _state(w)
            live_before = _fingerprint(ob)
            live_overrides = _overrides(w, ob)
            w2 = _reload(state, d)
            ob2 = w2.outbreak
            rec = {"phase": phase, "t": ob.now_s, "state": state,
                   "live_before": live_before, "restored_before": _fingerprint(ob2),
                   "live_overrides": live_overrides, "restored_overrides": _overrides(w2, ob2),
                   "restored_row": w2.mobility_snapshot(include_routes=False),
                   "live_row": w.mobility_snapshot(include_routes=False)}
            w.advance_seconds(CONTINUE_S)
            w2.advance_seconds(CONTINUE_S)
            rec["live_after"] = json.dumps(_state(w), sort_keys=True)
            rec["restored_after"] = json.dumps(_state(w2), sort_keys=True)
            rec["live_ob_after"] = _fingerprint(ob)
            rec["restored_ob_after"] = _fingerprint(ob2)
            out[phase] = rec
            minutes += int(CONTINUE_S // 60)
            continue
        w.advance_seconds(60.0)
        minutes += 1
    assert set(out) == set(PHASES), f"phases reached: {sorted(out)}"
    return out


@pytest.mark.parametrize("phase", PHASES)
def test_health_records_are_identical_after_reload(checkpoints, phase):
    c = checkpoints[phase]
    assert c["restored_before"]["records"] == c["live_before"]["records"]
    assert c["restored_before"]["records"], "no health records were saved"
    assert c["restored_before"]["now_s"] == c["live_before"]["now_s"]
    assert c["restored_before"]["counts"] == c["live_before"]["counts"]


@pytest.mark.parametrize("phase", PHASES)
def test_events_and_disruption_are_identical_after_reload(checkpoints, phase):
    c = checkpoints[phase]
    assert c["restored_before"]["events"] == c["live_before"]["events"]
    assert c["restored_before"]["event_seq"] == c["live_before"]["event_seq"]
    assert c["restored_before"]["disrupted"] == c["live_before"]["disrupted"]
    assert c["restored_before"]["obstructions"] == c["live_before"]["obstructions"]


@pytest.mark.parametrize("phase", PHASES)
def test_executor_overrides_are_identical_after_reload(checkpoints, phase):
    c = checkpoints[phase]
    assert c["restored_overrides"] == c["live_overrides"]
    expected = {"incubation": "", "symptomatic": "", "corpse": "corpse", "undead": "undead"}[phase]
    assert c["live_overrides"][INDEX] == expected, (phase, c["live_overrides"][INDEX])


@pytest.mark.parametrize("phase", PHASES)
def test_mobility_rows_carry_the_same_health_after_reload(checkpoints, phase):
    c = checkpoints[phase]
    live = {r["citizen_id"]: (r["health"], r["state"], r["x"], r["y"])
            for r in c["live_row"]["citizens"]}
    back = {r["citizen_id"]: (r["health"], r["state"], r["x"], r["y"])
            for r in c["restored_row"]["citizens"]}
    assert live == back
    assert live[INDEX][0] == {"incubation": "incubating", "symptomatic": "symptomatic",
                              "corpse": "corpse", "undead": "undead"}[phase]


@pytest.mark.parametrize("phase", PHASES)
def test_a_ten_minute_continuation_is_byte_identical(checkpoints, phase):
    c = checkpoints[phase]
    assert c["restored_after"] == c["live_after"]
    assert c["restored_ob_after"] == c["live_ob_after"]


@pytest.mark.parametrize("phase", PHASES)
def test_reloading_never_reseeds_the_outbreak(checkpoints, phase):
    c = checkpoints[phase]
    for fp in (c["restored_before"], c["restored_ob_after"]):
        infected = Counter(e["citizen_id"] for e in fp["events"] if e["event"] == "INFECTED")
        assert infected, "no INFECTED event survived the reload"
        assert max(infected.values()) == 1, [k for k, v in infected.items() if v > 1]
        seeded = [e for e in fp["events"] if e["event"] == "EXPOSURE"
                  and e.get("context") == "index_case"]
        assert len(seeded) == 1 and seeded[0]["citizen_id"] == INDEX
    # the restored runtime kept the index case's record, it did not roll a new one
    assert c["restored_before"]["records"][INDEX]["infection_t"] == 0.0


def test_the_saved_world_state_carries_the_outbreak_block(checkpoints):
    st = checkpoints["undead"]["state"]
    ob = st["outbreak"]
    assert ob["pathogen"]["name"] == "classic_zombie"
    assert str(INDEX) in ob["records"]
    assert ob["records"][str(INDEX)]["state"] == "undead"
    assert ob["event_seq"] >= len(ob["events"]) > 0
    assert json.loads(json.dumps(ob)) == ob


def test_every_phase_was_biologically_distinct(checkpoints):
    seen = {p: checkpoints[p]["live_before"]["records"][INDEX]["state"] for p in PHASES}
    assert seen == {"incubation": "incubating", "symptomatic": "symptomatic",
                    "corpse": "corpse", "undead": "undead"}
    ts = [checkpoints[p]["t"] for p in PHASES]
    assert ts == sorted(ts)

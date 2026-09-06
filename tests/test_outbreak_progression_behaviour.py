"""Progression and behaviour of the index case, minute by minute (§6, §7).

Citizen 42 is seeded at 05:00 in the Houston world and the world is advanced to
11:00 with the executor sampled every game minute. The chain the trace must
show is the one the health record scheduled at infection time:

    symptom onset -> "go home" goal -> incapacitation (wherever the body is)
    -> death in place -> reanimation in place -> undead, no car

and at no sample may the body teleport: a minute of walking is at most
1.4 m/s * 60 s, a minute of driving at most 17 m/s * 60 s, and an
incapacitated body or a corpse does not move at all.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodiment import CitySpatialContext
from asphodel.outbreak.health import HealthState

CITY = "houston"
INDEX = 42
START_HOUR = 5.0
END_HOUR = 11.0
STEP_S = 60.0
DRIVE_MAX_M = 17.0 * STEP_S + 5.0
WALK_MAX_M = 1.4 * STEP_S + 5.0
MOVING_STATES = {EmbodimentState.DRIVING.value, EmbodimentState.APPROACHING_VEHICLE.value,
                 EmbodimentState.ENTERING_VEHICLE.value, EmbodimentState.EXITING_VEHICLE.value,
                 EmbodimentState.PARKED.value}
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


@pytest.fixture(scope="module")
def run():
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    ob = w.enable_outbreak("classic_zombie", index_case=INDEX)
    rt, ex = w.mobility.citizens[INDEX], w.mobility.execs[INDEX]
    home_bid = (rt.node_meta.get(rt.home_node) or {}).get("building_id")
    work_bid = int(w.mobility.records[INDEX].work_building_id)
    samples = []

    def sample():
        samples.append({
            "t": round(ob.now_s, 1), "pos": tuple(ex.pos), "state": ex.state.value,
            "override": ex.override, "building_id": int(ex.building_id),
            "vehicle_id": ex.vehicle_id, "health": ob.records[INDEX].state.value,
            "has_vehicle": bool(rt.has_vehicle), "in_vehicle": bool(ex.in_vehicle),
            "goal_sources": sorted({g.source for g in rt.goals.goals}),
            "activity": rt.current_activity,
        })

    sample()
    for _ in range(int((END_HOUR - START_HOUR) * 3600 // STEP_S)):
        w.advance_seconds(STEP_S)
        sample()
    return {"world": w, "ob": ob, "rec": ob.records[INDEX], "samples": samples,
            "home_bid": home_bid, "work_bid": work_bid,
            "events": [e for e in ob.events if e.get("citizen_id") == INDEX]}


def _event(run, kind):
    hits = [e for e in run["events"] if e["event"] == kind]
    assert len(hits) == 1, f"expected exactly one {kind} for citizen {INDEX}, got {len(hits)}"
    return hits[0]


def _after(run, t):
    return [s for s in run["samples"] if s["t"] >= t]


# --------------------------------------------------------------------------- #
# the scheduled chain
# --------------------------------------------------------------------------- #
def test_the_whole_fatal_chain_fires_at_its_scheduled_times(run):
    rec = run["rec"]
    assert rec.fatal is True and rec.will_reanimate is True
    for kind, when in (("SYMPTOM_ONSET", rec.symptom_t), ("INCAPACITATED", rec.incapacitation_t),
                       ("DEATH", rec.death_t), ("REANIMATION", rec.reanimate_t)):
        e = _event(run, kind)
        assert abs(e["t"] - when) <= 1.0, (kind, e["t"], when)
    seqs = [_event(run, k)["seq"] for k in ("SYMPTOM_ONSET", "INCAPACITATED", "DEATH", "REANIMATION")]
    assert seqs == sorted(seqs)
    assert rec.state is HealthState.UNDEAD and rec.undead_since_t == pytest.approx(rec.reanimate_t, abs=1.0)


def test_symptom_onset_pushes_a_health_goal_and_a_trip_home(run):
    onset = _event(run, "SYMPTOM_ONSET")
    inv = [e for e in run["events"] if e["event"] == "PLAN_INVALIDATED"
           and e.get("goal") == "go_home"]
    assert inv and inv[0]["seq"] == onset["seq"] + 1
    assert "symptomatic" in inv[0]["reason"]
    # while symptomatic the citizen carries a health-sourced goal
    symptomatic = [s for s in run["samples"] if s["health"] == "symptomatic"]
    assert symptomatic, "no sample caught the symptomatic window"
    assert all("health" in s["goal_sources"] for s in symptomatic), symptomatic


def test_the_symptomatic_citizen_leaves_work_for_home(run):
    onset = _event(run, "SYMPTOM_ONSET")
    inc = _event(run, "INCAPACITATED")
    assert onset["building_id"] == run["work_bid"], onset
    between = [s for s in run["samples"] if onset["t"] <= s["t"] <= inc["t"] + STEP_S]
    left_work = [s for s in between if s["building_id"] != run["work_bid"]]
    reached_home = [s for s in between if s["building_id"] == run["home_bid"]]
    # either the trip home completed before collapse, or the collapse happened
    # en route -- both are valid, but the citizen must have left the workplace
    assert left_work, between
    assert reached_home or inc["building_id"] != run["work_bid"], (inc, between[-3:])


def test_incapacitation_freezes_the_body_where_it_stood(run):
    inc = _event(run, "INCAPACITATED")
    after = _after(run, inc["t"])
    assert after, "no sample after incapacitation"
    first = after[0]
    assert first["override"] == "incapacitated"
    assert first["state"] == inc["embodiment"] == EmbodimentState.INCAPACITATED.value
    assert (round(first["pos"][0], 1), round(first["pos"][1], 1)) == (inc["x"], inc["y"])
    assert first["building_id"] == inc["building_id"] and first["vehicle_id"] == inc["vehicle_id"]
    # five minutes of holding still
    held = [s for s in after if s["t"] <= inc["t"] + 300.0]
    assert len(held) >= 5
    for s in held:
        assert s["pos"] == first["pos"], (s, first)


def test_death_keeps_the_body_and_records_the_corpse_in_place(run):
    rec, death = run["rec"], _event(run, "DEATH")
    corpse = [e for e in run["events"] if e["event"] == "CORPSE_CREATED"]
    assert len(corpse) == 1 and corpse[0]["seq"] == death["seq"] + 1
    assert rec.corpse_xy == corpse[0]["corpse_xy"]
    assert rec.corpse_building_id == death["building_id"] == corpse[0]["corpse_building_id"]
    after = _after(run, death["t"])[0]
    assert after["override"] == "corpse" and after["health"] == "corpse"
    assert [round(after["pos"][0], 2), round(after["pos"][1], 2)] == rec.corpse_xy
    assert (death["x"], death["y"]) == (round(after["pos"][0], 1), round(after["pos"][1], 1))
    # the corpse never moves before it rises
    frozen = [s for s in run["samples"] if death["t"] <= s["t"] <= rec.reanimate_t]
    assert len(frozen) >= 2 and all(s["pos"] == after["pos"] for s in frozen)


def test_reanimation_is_the_same_citizen_in_the_same_place(run):
    rec, death, rise = run["rec"], _event(run, "DEATH"), _event(run, "REANIMATION")
    assert rise["citizen_id"] == rise["original_citizen_id"] == INDEX
    assert (rise["x"], rise["y"]) == (death["x"], death["y"])       # jump 0
    assert math.hypot(rise["x"] - rec.corpse_xy[0], rise["y"] - rec.corpse_xy[1]) < 0.1
    assert rise["embodiment"] == EmbodimentState.UNDEAD.value
    after = _after(run, rise["t"])[0]
    assert math.hypot(after["pos"][0] - rec.corpse_xy[0],
                      after["pos"][1] - rec.corpse_xy[1]) <= 1.0 * STEP_S


def test_the_undead_walks_without_a_car(run):
    rise = _event(run, "REANIMATION")
    after = _after(run, rise["t"] + STEP_S)
    assert after, "no sample after reanimation"
    for s in after:
        assert s["override"] == "undead", s
        assert s["has_vehicle"] is False and s["in_vehicle"] is False, s
        assert s["vehicle_id"] is None, s
    rt = run["world"].mobility.citizens[INDEX]
    assert rt.has_vehicle is False
    assert run["world"].mobility.execs[INDEX].override == "undead"
    assert rise["vehicle_id"] is None


def test_the_abandoned_car_of_the_index_case_became_a_wreck(run):
    """The index case collapsed at the wheel: the car stayed where it stopped."""
    ab = [e for e in run["ob"].events if e["event"] == "VEHICLE_ABANDONED"
          and e.get("citizen_id") == INDEX]
    if not ab:
        pytest.skip("the index case did not collapse while driving in this run")
    veh = run["world"].mobility.vehicles[ab[0]["vehicle_id"]]
    assert veh.driver is None and veh.speed == 0.0
    assert veh.fidelity.value == "persistent_wreck"


# --------------------------------------------------------------------------- #
# no teleport, ever
# --------------------------------------------------------------------------- #
def test_no_teleport_across_the_whole_run(run):
    samples = run["samples"]
    assert len(samples) >= 300
    worst = 0.0
    for a, b in zip(samples, samples[1:]):
        jump = math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1])
        held = {a["override"], b["override"]} <= {"incapacitated", "corpse"}
        if held and a["override"] and b["override"]:
            assert jump == 0.0, (a, b, jump)
            continue
        driving = (a["state"] in MOVING_STATES or b["state"] in MOVING_STATES
                   or a["in_vehicle"] or b["in_vehicle"])
        limit = DRIVE_MAX_M if driving else WALK_MAX_M
        assert jump <= limit, (a, b, jump, limit)
        worst = max(worst, jump)
    assert worst > 0.0


def test_the_frozen_states_never_move_at_all(run):
    frozen = [s for s in run["samples"] if s["override"] in ("incapacitated", "corpse")]
    assert len(frozen) >= 5
    assert len({s["pos"] for s in frozen}) == 1


def test_undead_speed_is_the_pathogen_speed(run):
    ob = run["ob"]
    rise = _event(run, "REANIMATION")
    walking = _after(run, rise["t"] + STEP_S)
    for a, b in zip(walking, walking[1:]):
        jump = math.hypot(b["pos"][0] - a["pos"][0], b["pos"][1] - a["pos"][1])
        assert jump <= ob.pathogen.undead_speed * STEP_S + 5.0, (a, b, jump)

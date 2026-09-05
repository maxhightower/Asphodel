"""HealthRecord + pathogen grammar (ASPHODEL_OUTBREAK_V1 §3, §4).

The health record is the biological authority: every outcome is decided ONCE,
from a pure function of (world_seed, citizen_id, purpose), and stored. These
tests pin that contract without a world: determinism, the forced-symptomatic
index case, the asymptomatic branch, fatal vs non-fatal, a single reanimation
roll, the ordering of scheduled transitions, and the state round trip.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.outbreak.health import HealthRecord, HealthState, jittered, roll
from asphodel.outbreak.pathogen import (ARCHETYPES, OutbreakPathogen, classic_zombie,
                                        pathogen_by_name)

SEED = 12345
CID = 42
TIMES = ("exposure_t", "infection_t", "infectious_from_t", "symptom_t",
         "incapacitation_t", "death_t", "recovery_t", "reanimate_t")


def _infect(seed=SEED, cid=CID, p=None, now=1000.0, **kw):
    rec = HealthRecord(cid)
    rec.infect(p or classic_zombie(), seed, now, kw.pop("source", None),
               kw.pop("context", "index_case"), kw.pop("location", (10.0, 20.0)),
               kw.pop("lineage", []), **kw)
    return rec


def _stamps(rec):
    return {k: getattr(rec, k) for k in TIMES}


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def test_infect_is_deterministic_for_same_seed_and_citizen():
    a = _infect(force_symptomatic=True)
    b = _infect(force_symptomatic=True)
    assert _stamps(a) == _stamps(b)
    assert (a.fatal, a.asymptomatic, a.will_reanimate) == (b.fatal, b.asymptomatic, b.will_reanimate)
    assert a.to_state() == b.to_state()


def test_infect_differs_for_a_different_seed_or_citizen():
    base = _infect(force_symptomatic=True)
    other_seed = _infect(seed=SEED + 1, force_symptomatic=True)
    assert _stamps(other_seed) != _stamps(base)
    # at least one citizen in a small sweep must land on different timestamps
    others = [_infect(cid=c, force_symptomatic=True) for c in range(43, 60)]
    assert any(_stamps(o) != _stamps(base) for o in others)


def test_timestamps_are_offsets_of_the_infection_time():
    early = _infect(now=0.0, force_symptomatic=True)
    late = _infect(now=3600.0, force_symptomatic=True)
    for k in TIMES:
        a, b = getattr(early, k), getattr(late, k)
        if a is None:
            assert b is None
        else:
            assert b == pytest.approx(a + 3600.0)


def test_roll_is_a_pure_function_in_unit_interval():
    for cid in (0, 1, 42, 299):
        for purpose in ("mortality", "reanimation", "incubation"):
            u = roll(SEED, cid, purpose)
            assert 0.0 <= u < 1.0
            assert u == roll(SEED, cid, purpose)
    assert roll(SEED, CID, "mortality") != roll(SEED, CID, "reanimation")
    assert roll(SEED, CID, "contact:1", 3) != roll(SEED, CID, "contact:1", 4)


# --------------------------------------------------------------------------- #
# branches
# --------------------------------------------------------------------------- #
def test_force_symptomatic_makes_an_index_case_symptomatic():
    p = OutbreakPathogen(asymptomatic_fraction=1.0)   # everyone would be asymptomatic
    forced = _infect(p=p, force_symptomatic=True)
    assert forced.asymptomatic is False
    assert forced.symptom_t is not None and forced.symptom_t > forced.infection_t
    natural = _infect(p=p)
    assert natural.asymptomatic is True


def test_asymptomatic_path_recovers_and_never_dies():
    p = OutbreakPathogen(asymptomatic_fraction=1.0)
    rec = _infect(p=p)
    assert rec.state is HealthState.INCUBATING
    assert rec.symptom_t is None and rec.incapacitation_t is None and rec.death_t is None
    assert rec.will_reanimate is None and rec.fatal is False
    assert rec.recovery_t > rec.infection_t
    assert rec.infectious_from_t is not None
    assert rec.next_transition(rec.infection_t) == ("recovery", rec.recovery_t)


def test_fatal_path_schedules_incapacitation_death_and_reanimation():
    p = OutbreakPathogen(asymptomatic_fraction=0.0, mortality_fraction=1.0,
                         reanimation_fraction=1.0)
    rec = _infect(p=p)
    assert rec.fatal is True and rec.will_reanimate is True
    assert rec.recovery_t is None
    assert rec.infection_t < rec.symptom_t < rec.incapacitation_t < rec.death_t < rec.reanimate_t


def test_non_fatal_path_recovers_and_never_reanimates():
    p = OutbreakPathogen(asymptomatic_fraction=0.0, mortality_fraction=0.0)
    rec = _infect(p=p)
    assert rec.fatal is False
    assert rec.incapacitation_t is None and rec.death_t is None
    assert rec.will_reanimate is None and rec.reanimate_t is None
    assert rec.recovery_t > rec.symptom_t


def test_fatal_but_not_reanimating_leaves_no_reanimation_time():
    p = OutbreakPathogen(asymptomatic_fraction=0.0, mortality_fraction=1.0,
                         reanimation_fraction=0.0)
    rec = _infect(p=p)
    assert rec.fatal is True and rec.will_reanimate is False and rec.reanimate_t is None


def test_will_reanimate_is_rolled_once_from_the_reanimation_purpose():
    p = OutbreakPathogen(asymptomatic_fraction=0.0, mortality_fraction=1.0,
                         reanimation_fraction=0.5)
    for cid in range(0, 40):
        rec = _infect(cid=cid, p=p)
        assert rec.will_reanimate == (roll(SEED, cid, "reanimation") < 0.5)
        # re-deciding the same infection can never change the outcome
        again = _infect(cid=cid, p=p, now=1000.0)
        assert again.will_reanimate == rec.will_reanimate
        assert again.reanimate_t == rec.reanimate_t
    # the population is genuinely split (the roll is used, not a constant)
    outs = {_infect(cid=c, p=p).will_reanimate for c in range(0, 40)}
    assert outs == {True, False}


def test_jitter_stays_inside_the_declared_band():
    p = classic_zombie()
    for cid in range(0, 60):
        rec = _infect(cid=cid, p=p, now=0.0, force_symptomatic=True)
        inc = rec.symptom_t
        assert p.incubation_s * (1 - p.jitter) <= inc <= p.incubation_s * (1 + p.jitter)
    assert jittered(100.0, 0.4, 0.0) == pytest.approx(60.0)
    assert jittered(100.0, 0.4, 1.0) == pytest.approx(140.0)


def test_infectious_weight_follows_the_state():
    p = classic_zombie()
    rec = _infect(p=p, now=0.0, force_symptomatic=True)
    assert rec.infectious_weight(p, 0.0) == 0.0                       # early incubation
    assert rec.infectious_weight(p, rec.infectious_from_t) == p.presymptomatic_factor
    rec.state = HealthState.SYMPTOMATIC
    assert rec.infectious_weight(p, rec.symptom_t) == 1.0
    rec.state = HealthState.UNDEAD
    assert rec.infectious_weight(p, rec.symptom_t) == p.undead_infectious
    rec.state = HealthState.RECOVERED
    assert rec.infectious_weight(p, rec.symptom_t) == 0.0


# --------------------------------------------------------------------------- #
# scheduled transitions
# --------------------------------------------------------------------------- #
def test_next_transition_orders_the_whole_fatal_chain():
    p = OutbreakPathogen(asymptomatic_fraction=0.0, mortality_fraction=1.0,
                         reanimation_fraction=1.0)
    rec = _infect(p=p, now=0.0)
    seen = []
    states = {"symptom_onset": HealthState.SYMPTOMATIC,
              "incapacitation": HealthState.INCAPACITATED,
              "death": HealthState.CORPSE,
              "reanimation": HealthState.UNDEAD}
    while True:
        nxt = rec.next_transition(rec.reanimate_t + 1.0)
        if nxt is None:
            break
        seen.append(nxt)
        rec.state = states[nxt[0]]
    assert [n for n, _ in seen] == ["symptom_onset", "incapacitation", "death", "reanimation"]
    ts = [t for _, t in seen]
    assert ts == sorted(ts)
    assert ts == [rec.symptom_t, rec.incapacitation_t, rec.death_t, rec.reanimate_t]


def test_next_transition_is_none_in_terminal_states():
    rec = _infect(force_symptomatic=True)
    for state in (HealthState.SUSCEPTIBLE, HealthState.RECOVERED, HealthState.DEAD,
                  HealthState.UNDEAD):
        rec.state = state
        assert rec.next_transition(1e9) is None


def test_dead_without_reanimation_has_no_further_transition():
    p = OutbreakPathogen(asymptomatic_fraction=0.0, mortality_fraction=1.0,
                         reanimation_fraction=0.0)
    rec = _infect(p=p)
    rec.state = HealthState.CORPSE          # would-be corpse, but no reanimate_t
    assert rec.next_transition(1e9) is None


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def test_to_state_from_state_round_trip():
    rec = _infect(source=7, context="building:2318", lineage=[1, 3])
    rec.state = HealthState.CORPSE
    rec.corpse_xy = [1.5, 2.5]
    rec.corpse_building_id = 2318
    rec.attacks = 3
    rec.bitten_by = 9
    rec.exposures_resisted = 11
    st = rec.to_state()
    assert st["state"] == "corpse" and isinstance(st["state"], str)
    back = HealthRecord.from_state(st)
    assert back.state is HealthState.CORPSE
    assert back.to_state() == st
    assert back.lineage == [1, 3, 7] and back.lineage is not rec.lineage


def test_from_state_survives_a_json_round_trip_and_ignores_extra_keys():
    import json
    rec = _infect(force_symptomatic=True)
    st = json.loads(json.dumps(rec.to_state()))
    st["some_future_field"] = 1
    back = HealthRecord.from_state(st)
    assert back.to_state() == rec.to_state()


def test_alive_and_infected_partitions():
    rec = HealthRecord(1)
    assert rec.alive and not rec.infected
    for s in (HealthState.INCUBATING, HealthState.SYMPTOMATIC, HealthState.INCAPACITATED):
        rec.state = s
        assert rec.alive and rec.infected
    for s in (HealthState.DEAD, HealthState.CORPSE, HealthState.UNDEAD):
        rec.state = s
        assert not rec.alive
    rec.state = HealthState.RECOVERED
    assert rec.alive and not rec.infected


# --------------------------------------------------------------------------- #
# pathogen grammar
# --------------------------------------------------------------------------- #
def test_every_archetype_builds_and_progresses():
    assert set(ARCHETYPES) == {"classic_zombie", "classic_shambler", "rage_virus",
                               "cordyceps", "necro_latent"}
    for name in sorted(ARCHETYPES):
        p = pathogen_by_name(name)
        assert isinstance(p, OutbreakPathogen) and p.name == name
        assert p.incubation_s > 0 and p.symptomatic_s > 0 and 0.0 <= p.jitter < 1.0
        assert 0.0 <= p.asymptomatic_fraction <= 1.0
        assert 0.0 <= p.mortality_fraction <= 1.0
        assert 0.0 <= p.reanimation_fraction <= 1.0
        rec = _infect(p=p, now=0.0, force_symptomatic=True)
        assert rec.state is HealthState.INCUBATING and rec.symptom_t > 0.0
        assert p.to_dict() == OutbreakPathogen.from_dict(p.to_dict()).to_dict()


def test_pathogen_by_name_rejects_unknown_names():
    for bad in ("", "zombie", "classic", "CLASSIC_ZOMBIE", "necro-latent"):
        with pytest.raises(KeyError):
            pathogen_by_name(bad)


def test_pathogen_is_frozen_and_defaults_to_classic_zombie():
    p = classic_zombie()
    assert p.name == "classic_zombie" and OutbreakPathogen().name == "classic_zombie"
    with pytest.raises(Exception):
        p.incubation_s = 1.0

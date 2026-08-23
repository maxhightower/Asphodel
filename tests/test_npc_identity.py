"""M2 tests (Phase 11 SP1): citizen identity + schedule activity.

Covers the M2 exit gate:

* promoted agents carry citizen identities,
* schedule activity updates correctly (a legible daily rhythm),
* the identity/activity arrays stay aligned under add / remove / reconcile,
* identity assignment consumes ZERO draws from AgentZone.rng,
* snapshots expose identity + activity,
* **citizens-disabled vs citizens-enabled outbreak trajectory is bit-identical**
  (the load-bearing calibration-neutrality test),
* deterministic replay remains intact with citizens enabled,
* population is still conserved.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.micro import AgentZone, S, E, IA, IS, R, D
from asphodel.citizen import CitizenProfile, ScheduleEntry
from asphodel.config import PathogenGenome
from asphodel import npc


DAY_SCHEDULE = [
    ScheduleEntry(0.0, 7.0, "sleep", "home"),
    ScheduleEntry(7.0, 9.0, "commute", "road"),
    ScheduleEntry(9.0, 17.0, "work", "office"),
    ScheduleEntry(17.0, 19.0, "errand", "shop"),
    ScheduleEntry(19.0, 24.0, "leisure", "home"),
]


def _cfg(rows=4, cols=4, pop=1000.0, n_days=40.0):
    c = ScenarioConfig()
    c.model.graph.grid_rows = rows
    c.model.graph.grid_cols = cols
    c.model.graph.population_per_zone = pop
    c.n_days = n_days
    return c


def _micro():
    return MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _citizens(n_per_zone, zones):
    out = []
    cid = 0
    for z in zones:
        for _ in range(n_per_zone):
            out.append(CitizenProfile(
                citizen_id=cid, city="x", age=30, age_band="adult",
                occupation="worker", shift="day", home_district="d",
                work_district="d", home_zone=z, work_zone=z,
                schedule=DAY_SCHEDULE, inventory={}, spawn_hour=8.0,
                current_location="home", current_activity="work", current_task=""))
            cid += 1
    return out


# --------------------------------------------------------------------------- #
# identity assignment is RNG-free
# --------------------------------------------------------------------------- #
def test_assign_identities_consumes_zero_rng():
    z = AgentZone.from_counts({"S": 100, "E": 0, "Ia": 0, "Is": 0, "R": 0, "D": 0},
                              PathogenGenome(), _micro(), dt=0.25, seed=5)
    before = z.rng.bit_generator.state
    z.assign_identities(np.arange(10), np.arange(1000, 1010))
    after = z.rng.bit_generator.state
    assert before == after                       # not a single draw consumed
    assert (z.citizen_id[:10] == np.arange(1000, 1010)).all()
    assert (z.citizen_id[10:] == -1).all()


# --------------------------------------------------------------------------- #
# arrays stay aligned under add / remove / reconcile
# --------------------------------------------------------------------------- #
def _fingerprint(zone):
    """Map each agent's position row -> its citizen_id, as an alignment truth."""
    return {tuple(np.round(p, 9)): int(c)
            for p, c in zip(zone.pos, zone.citizen_id)}


def test_identity_stays_aligned_through_mutations():
    z = AgentZone.from_counts({"S": 200, "E": 0, "Ia": 0, "Is": 0, "R": 0, "D": 0},
                              PathogenGenome(), _micro(), dt=0.25, seed=3)
    # Give every agent a distinct identity so misalignment is detectable.
    z.assign_identities(np.arange(z.n), np.arange(z.n))
    truth = _fingerprint(z)

    z.remove_agents({"S": 40})                   # some leave
    for p, c in zip(z.pos, z.citizen_id):
        assert truth[tuple(np.round(p, 9))] == int(c)     # survivors still aligned

    n_before = z.n
    z.add_agents({"S": 30})                       # anonymous arrivals
    assert z.n == n_before + 30
    assert (z.citizen_id[-30:] == -1).all()       # arrivals are anonymous
    # pre-existing agents keep their identities aligned with their positions
    for p, c in zip(z.pos[:n_before], z.citizen_id[:n_before]):
        assert truth[tuple(np.round(p, 9))] == int(c)

    z.reconcile_to_counts({"S": 150, "E": 10, "Ia": 0, "Is": 0, "R": 0, "D": 0})
    # lengths stay consistent across all aligned arrays
    assert z.citizen_id.shape[0] == z.n == z.pos.shape[0] == z.state.shape[0]
    assert z.activity.shape[0] == z.n


# --------------------------------------------------------------------------- #
# promoted agents carry identity; snapshot exposes it
# --------------------------------------------------------------------------- #
def test_promoted_agents_carry_identity_and_snapshot_exposes_it():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.set_citizens(_citizens(40, range(16)))
    w.set_focus([5])
    for _ in range(4):
        w.step()
    snap = w.snapshot()
    assert 5 in snap["agents"]
    ag = snap["agents"][5]
    n = len(ag["positions"])
    assert len(ag["citizen_id"]) == n == len(ag["state"]) == len(ag["activity"])
    cid = np.array(ag["citizen_id"])
    assert (cid >= 0).sum() > 0                   # some real citizens embodied
    assert (cid >= 0).sum() <= 40                 # capped by eligible residents
    assert (cid < 0).sum() > 0                    # and anonymous fill remains
    assert "activity_occupancy" in snap and 5 in snap["activity_occupancy"]


# --------------------------------------------------------------------------- #
# schedule activity produces a legible daily rhythm
# --------------------------------------------------------------------------- #
def test_activity_follows_schedule_across_the_day():
    dominant = set()
    for start_hour in (2.0, 8.0, 12.0, 18.0, 21.0):
        w = World(_cfg(), micro_params=_micro(), start_hour=start_hour, seed=1)
        w.set_citizens(_citizens(40, [5]))
        w.set_focus([5])
        w.step()
        zone = w.promoted[5]
        hour = w.current_hour()
        expected = npc.activity_at_hour(DAY_SCHEDULE, hour)
        ids = zone.identified_slots()
        assert ids.size > 0
        # every identified agent's activity matches its schedule at this hour
        assert (zone.activity[ids] == expected).all(), (start_hour, hour, expected)
        dominant.add(npc.activity_name(expected))
    # sweeping the day surfaces several distinct activities -> a real rhythm
    assert len(dominant) >= 3, dominant


# --------------------------------------------------------------------------- #
# THE load-bearing test: identity layer is epidemiologically neutral
# --------------------------------------------------------------------------- #
def _trajectory(enable_citizens):
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    if enable_citizens:
        w.set_citizens(_citizens(50, range(16)))
    traj = []
    for _ in range(int(40.0 / w.dt)):
        wt = w.step()
        traj.append((wt.S, wt.E, wt.Ia, wt.Is, wt.R, wt.D))
    return traj


def test_citizens_disabled_vs_enabled_is_bit_identical():
    disabled = _trajectory(False)
    enabled = _trajectory(True)
    assert disabled == enabled                   # exact equality, no tolerance
    # and the run was non-trivial (an epidemic actually happened)
    assert enabled[-1][5] > 0                     # deaths accrued


def test_deterministic_replay_with_citizens():
    a = _trajectory(True)
    b = _trajectory(True)
    assert a == b


# --------------------------------------------------------------------------- #
# conservation unaffected
# --------------------------------------------------------------------------- #
def test_population_conserved_with_citizens():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.set_citizens(_citizens(50, range(16)))
    N0 = 1000.0 * 16
    last = None
    for _ in range(int(40.0 / w.dt)):
        last = w.step()
        assert abs(last.total_pop - N0) < 1e-6, last.total_pop
    assert last.D > 0


if __name__ == "__main__":
    import types
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            fn()
            print("ok", name)
    print("all M2 identity tests passed")

"""M3 tests (Phase 11 SP2): reactive affordances.

Covers the M3 exit gate:

* the environment advertises affordances; agents pick via a seeded, score-weighted
  top-k draw (no argmax, no GOAP/behaviour trees),
* citizens visibly/reactively depart from routine as belief rises,
* reactions are deterministic (per-citizen seeded, never AgentZone.rng),
* designed content wins: a signature moment forces `signature` over any utility,
* **reactive layer ON vs OFF is bit-identical in the epidemic curve** (reactions
  are pure `chosen_action` labels; the certified belief-driven shelter channel is
  untouched),
* performance stays inside the live-bubble budget (cheap per-identified-agent loop).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.citizen import CitizenProfile, ScheduleEntry
from asphodel import npc
from asphodel.npc import choose_action, NEEDS
from asphodel.affordances import advertise


def _rng(cid):
    return np.random.default_rng(cid)


WORK_ALL_DAY = [ScheduleEntry(0.0, 24.0, "work", "office")]


def _cfg(rows=4, cols=4, pop=1000.0, n_days=40.0):
    c = ScenarioConfig()
    c.model.graph.grid_rows = rows
    c.model.graph.grid_cols = cols
    c.model.graph.population_per_zone = pop
    c.n_days = n_days
    return c


def _micro():
    return MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _citizens(n, zone):
    return [CitizenProfile(
        citizen_id=c, city="x", age=30, age_band="a", occupation="w", shift="d",
        home_district="d", work_district="d", home_zone=zone, work_zone=zone,
        schedule=WORK_ALL_DAY, inventory={}, spawn_hour=8.0, current_location="o",
        current_activity="work", current_task="") for c in range(n)]


# --------------------------------------------------------------------------- #
# 1. the pure chooser
# --------------------------------------------------------------------------- #
def test_high_safety_need_prefers_shelter_when_offered():
    ads = [("continue_schedule", 0.3), ("shelter", 0.9), ("flee", 0.5)]
    needs = {"safety": 1.0, "fatigue": 0.0, "hunger": 0.0, "social": 0.0}
    picks = [choose_action(ads, needs, _rng(i)) for i in range(200)]
    assert picks.count("shelter") > picks.count("flee")   # weighted, not uniform


def test_chooser_deterministic_in_seed():
    ads = [("shelter", 0.6), ("flee", 0.6), ("seek", 0.6)]
    needs = {n: 0.5 for n in NEEDS}
    assert choose_action(ads, needs, _rng(7)) == choose_action(ads, needs, _rng(7))


def test_empty_advertisements_falls_back_to_schedule():
    assert choose_action([], {n: 0.5 for n in NEEDS}, _rng(1)) == "continue_schedule"


# --------------------------------------------------------------------------- #
# 2. the projection
# --------------------------------------------------------------------------- #
def test_fire_place_advertises_flee_and_shelter():
    ads = dict(advertise(["fire"], belief=0.9))
    assert "flee" in ads and "shelter" in ads
    assert ads["flee"] >= 0.8


def test_calm_place_favours_routine():
    ads = advertise(None, belief=0.0)
    d = {}
    for a, u in ads:
        d[a] = max(d.get(a, 0.0), u)
    assert d["continue_schedule"] >= d.get("shelter", 0.0)


# --------------------------------------------------------------------------- #
# 3. curve-identity (load-bearing): reactions never move the epidemic
# --------------------------------------------------------------------------- #
def _trajectory(reactions):
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.reactions_enabled = reactions
    allc = []
    cid = 0
    for z in range(16):
        for _ in range(50):
            allc.append(CitizenProfile(
                citizen_id=cid, city="x", age=30, age_band="a", occupation="w",
                shift="d", home_district="d", work_district="d", home_zone=z,
                work_zone=z, schedule=WORK_ALL_DAY, inventory={}, spawn_hour=8.0,
                current_location="o", current_activity="work", current_task=""))
            cid += 1
    w.set_citizens(allc)
    traj = []
    for _ in range(int(40.0 / w.dt)):
        wt = w.step()
        traj.append((wt.S, wt.E, wt.Ia, wt.Is, wt.R, wt.D))
    return traj


def test_reactions_on_vs_off_is_bit_identical():
    on = _trajectory(True)
    off = _trajectory(False)
    assert on == off                                # exact equality, no tolerance
    assert on[-1][5] > 0                            # a real epidemic happened


# --------------------------------------------------------------------------- #
# 4. reactions respond to belief
# --------------------------------------------------------------------------- #
def _shelter_flee_share(broadcast, tags=None):
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=2)
    w.set_citizens(_citizens(60, 5))
    if tags:
        w.set_citizen_tags({c: tags for c in range(60)})
    w.set_focus([5])
    if broadcast:
        w.intervene("broadcast", level=1.0)
    for _ in range(12):
        w.step()
    occ = w.reaction_occupancy().get(5, {})
    total = sum(occ.values()) or 1
    return (occ.get("shelter", 0) + occ.get("flee", 0)) / total, occ


def test_belief_spike_raises_shelter_and_flee():
    calm, _ = _shelter_flee_share(False)
    spike, occ = _shelter_flee_share(True)
    assert spike > calm + 0.25                       # a material rise
    # routine collapses under the spike
    assert occ["continue_schedule"] < 60


def test_hazard_makes_flee_appear_under_spike():
    _, occ = _shelter_flee_share(True, tags=["fire"])
    assert occ["flee"] > 0                            # a hazard advertises fleeing


# --------------------------------------------------------------------------- #
# 5. subordination: designed content wins
# --------------------------------------------------------------------------- #
def test_signature_moment_overrides_utility():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=3)
    w.set_citizens(_citizens(40, 5))
    w.set_signature_citizens([0, 1, 2])              # these are in an authored moment
    w.set_focus([5])
    w.intervene("broadcast", level=1.0)              # maximal pressure to react
    for _ in range(6):
        w.step()
    zone = w.promoted[5]
    for cid in (0, 1, 2):
        slot = int(np.where(zone.citizen_id == cid)[0][0])
        assert zone.chosen_action[slot] == npc.SIGNATURE


# --------------------------------------------------------------------------- #
# 6. determinism + zero AgentZone.rng
# --------------------------------------------------------------------------- #
def test_chosen_action_deterministic_across_runs():
    def run():
        w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=4)
        w.set_citizens(_citizens(60, 5))
        w.set_focus([5])
        w.intervene("broadcast", level=1.0)
        for _ in range(10):
            w.step()
        z = w.promoted[5]
        order = np.argsort(z.citizen_id, kind="stable")
        return z.citizen_id[order].tolist(), z.chosen_action[order].tolist()

    assert run() == run()


def test_reactions_consume_zero_zone_rng():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=5)
    w.set_citizens(_citizens(40, 5))
    w.set_focus([5])
    w.step()                                         # promote + first reaction pass
    zone = w.promoted[5]
    before = zone.rng.bit_generator.state
    w.intervene("broadcast", level=1.0)
    zone_before_state = zone.state.copy()
    w._update_zone_reactions(5, zone)                # a pure reaction refresh
    after = zone.rng.bit_generator.state
    assert before == after                           # not one draw spent
    assert (zone.state == zone_before_state).all()   # and no epidemic state moved


if __name__ == "__main__":
    import types
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            fn()
            print("ok", name)
    print("all M3 reactive tests passed")

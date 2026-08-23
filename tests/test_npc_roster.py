"""M4 tests (Phase 11 SP3): bounded named roster + uprezzing.

Covers the M4 exit gate:

* the roster store is bounded, event-driven, LRU-by-interaction, deterministic,
* player-relevant citizens persist across demote→re-promote (identity + record),
* the hard cap always holds, independent of city size,
* eviction is deterministic (least-recently-interacted, lowest-id tie-break),
* macro population stays authoritative — conservation is exact across the churn,
* deterministic replay is intact (same scripted interactions -> same roster).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.roster import Roster, RosterRecord
from asphodel.citizen import CitizenProfile, ScheduleEntry


WORK_ALL_DAY = [ScheduleEntry(0.0, 24.0, "work", "office")]


def _cfg(rows=4, cols=4, pop=1000.0, n_days=80.0):
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
# 1. the pure bounded store
# --------------------------------------------------------------------------- #
def test_bound_never_exceeded():
    r = Roster(max_roster=4)
    for cid in range(20):
        r.promote(cid, None, tick=cid)
    assert len(r) <= 4


def test_lru_by_interaction_eviction():
    r = Roster(max_roster=2)
    r.promote(1, None, tick=0)
    r.promote(2, None, tick=1)
    r.interact(1, tick=5)                      # 1 more recent than 2
    r.promote(3, None, tick=6)                 # full -> evict LRU (2)
    assert r.contains(1) and r.contains(3) and not r.contains(2)


def test_eviction_tie_break_lowest_id():
    r = Roster(max_roster=2)
    r.promote(5, None, tick=0)
    r.promote(9, None, tick=0)                 # same tick as 5
    r.promote(7, None, tick=1)                 # tie at tick 0 -> evict lowest id (5)
    assert not r.contains(5) and r.contains(9) and r.contains(7)


def test_checkpoint_restore_roundtrip():
    r = Roster(max_roster=4)
    r.promote(7, None, tick=0)
    r.set_state(7, needs={"safety": 0.8}, chosen_action=2)
    rec = r.checkpoint(7)
    assert rec.citizen_id == 7 and rec.needs["safety"] == 0.8 and rec.chosen_action == 2
    assert r.restore_record(7) == rec          # survives unchanged


def test_promotion_is_idempotent():
    r = Roster(max_roster=4)
    r.promote(7, None, tick=0)
    r.promote(7, None, tick=1)
    assert len(r) == 1


# --------------------------------------------------------------------------- #
# 2. event-driven promotion via the World
# --------------------------------------------------------------------------- #
def test_interact_with_promotes():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.set_citizens(_citizens(40, 5))
    w.set_focus([5])
    w.step()
    assert not w.roster.contains(3)
    assert w.interact_with(3) is True          # a new member added
    assert w.roster.contains(3)
    assert w.interact_with(3) is False         # idempotent refresh


def test_focus_proximity_promotes_after_sustained_presence():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0,
              proximity_ticks=3, seed=1)
    w.set_citizens(_citizens(10, 5))
    w.set_focus([5])
    for _ in range(3):
        w.step()
    # sustained focus proximity eventually names residents of the focused zone
    assert len(w.roster) > 0
    assert all(w.citizens[c].home_zone == 5 for c in w.roster.ids())


def test_signature_in_view_promotes():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.set_citizens(_citizens(40, 5))
    w.set_signature_citizens([2])
    w.set_focus([5])
    w.step()
    assert w.roster.contains(2)                 # memorable moment in view -> named


# --------------------------------------------------------------------------- #
# 3. uprezzing: persistence across demote -> re-promote
# --------------------------------------------------------------------------- #
def _leave_until_demote(w, zone=5, limit=80):
    w.set_focus([])
    for _ in range(limit):
        w.step()
        if zone not in w.promoted:
            return True
    return False


def test_identity_persists_across_demote_and_repromote():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.set_citizens(_citizens(40, 5))
    w.set_focus([5])
    w.step()
    w.interact_with(3)
    w.roster.set_state(3, needs={"safety": 0.7})
    record_before = w.roster.checkpoint(3)

    assert _leave_until_demote(w), "zone 5 never demoted after leaving"
    for _ in range(10):                         # time passes while demoted
        w.step()
    # the roster record survived the demote interval unchanged in identity/needs
    assert w.roster.contains(3)
    assert w.roster.get(3).needs == record_before.needs

    w.set_focus([5])
    w.step()                                     # re-promote
    zone = w.promoted[5]
    assert (zone.citizen_id == 3).any()          # X is the same person again


def test_checkpointed_action_restored_when_reactions_off():
    w = World(_cfg(), micro_params=_micro(), start_hour=8.0, seed=1)
    w.reactions_enabled = False
    w.set_citizens(_citizens(40, 5))
    w.set_focus([5])
    w.step()
    w.interact_with(3)
    zone = w.promoted[5]
    slot = int(np.where(zone.citizen_id == 3)[0][0])
    zone.chosen_action[slot] = 2                 # the agent genuinely chose action 2

    assert _leave_until_demote(w)
    assert w.roster.get(3).chosen_action == 2    # checkpointed at demote
    for _ in range(10):
        w.step()
    w.set_focus([5])
    w.step()
    zone = w.promoted[5]
    slot = int(np.where(zone.citizen_id == 3)[0][0])
    assert int(zone.chosen_action[slot]) == 2    # restored on re-promote


# --------------------------------------------------------------------------- #
# 4. bound + conservation + determinism across a full churned run
# --------------------------------------------------------------------------- #
def _scripted_run(seed=1, max_roster=64, city_zones=16):
    rows = cols = int(city_zones ** 0.5)
    w = World(_cfg(rows=rows, cols=cols), micro_params=_micro(),
              start_hour=8.0, max_roster=max_roster, seed=seed)
    w.set_citizens(_citizens(40, 5) + _citizens_offset(40, 6, 40))
    N0 = 1000.0 * (rows * cols)
    roster_snap = []
    for i in range(int(80.0 / w.dt)):
        if i == 2:
            w.set_focus([5])
        if i == 4:
            w.interact_with(3)
        if i == 6:
            w.interact_with(7)
        if i == 30:
            w.set_focus([6])
        if i == 60:
            w.set_focus([5])
        wt = w.step()
        assert abs(wt.total_pop - N0) < 1e-6, wt.total_pop     # conservation
        assert len(w.roster) <= max_roster                     # hard bound
        roster_snap.append(tuple(w.roster.ids()))
    return roster_snap


def _citizens_offset(n, zone, id_offset):
    out = _citizens(n, zone)
    for c in out:
        c.citizen_id += id_offset
    return out


def test_conservation_and_bound_across_churn():
    _scripted_run()                              # asserts inside the loop


def test_deterministic_roster_replay():
    a = _scripted_run(seed=2)
    b = _scripted_run(seed=2)
    assert a == b


def test_bound_independent_of_city_size():
    # A much larger city with the same interactions must not grow the roster.
    small = _scripted_run(seed=3, city_zones=16)
    big = _scripted_run(seed=3, city_zones=64)
    assert max(len(ids) for ids in small) == max(len(ids) for ids in big)


if __name__ == "__main__":
    import types
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            fn()
            print("ok", name)
    print("all M4 roster tests passed")

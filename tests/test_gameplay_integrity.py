"""
Gameplay-integrity certification (Python side).

These are the "one authoritative world" regression tests introduced by the
gameplay-integrity milestone. They assert contracts the first-person game and
the live renderer depend on:

* the renderer-facing snapshot is always JSON-serializable,
* the live-agent budget is a *hard* cap for non-focused promotion,
* empty (zero-population) cells do not generate/relay social belief,

Run with:  python -m pytest tests/test_gameplay_integrity.py -q
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.config import GraphParams, ModelParams
from asphodel.runner import run_scenario


def _grid_config(rows=4, cols=4, pop=1000.0, n_days=60.0):
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = rows
    cfg.model.graph.grid_cols = cols
    cfg.model.graph.population_per_zone = pop
    cfg.n_days = n_days
    return cfg


def _micro():
    return MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


# --------------------------------------------------------------------------- #
# 1. snapshot() is JSON-serializable with 0, 1, and many promoted zones
# --------------------------------------------------------------------------- #
def _assert_json_round_trips(world: World):
    snap = world.snapshot()
    text = json.dumps(snap)                 # must not raise
    back = json.loads(text)
    assert back["tick"] == snap["tick"]
    # Promoted-zone agent arrays survive as plain nested lists.
    for _z, payload in back["agents"].items():
        assert isinstance(payload["positions"], list)
        assert isinstance(payload["state"], list)


def test_snapshot_json_safe_no_zones_promoted():
    cfg = _grid_config(rows=4, cols=4, n_days=5.0)
    w = World(cfg, micro_params=_micro(), seed=0)
    w.step()                                # a few ticks, nothing promoted yet
    assert len(w.promoted) == 0
    _assert_json_round_trips(w)


def test_snapshot_json_safe_one_zone_promoted():
    cfg = _grid_config(rows=4, cols=4, n_days=5.0)
    w = World(cfg, micro_params=_micro(), seed=0)
    w.set_focus([5])                        # force exactly one promotion
    w.step()
    assert 5 in w.promoted and len(w.promoted) == 1
    _assert_json_round_trips(w)


def test_snapshot_json_safe_multiple_zones_promoted():
    cfg = _grid_config(rows=4, cols=4, n_days=5.0)
    w = World(cfg, micro_params=_micro(), seed=0)
    w.set_focus([1, 5, 9])                  # force several promotions
    w.step()
    assert len(w.promoted) >= 3
    _assert_json_round_trips(w)


# --------------------------------------------------------------------------- #
# 2. max_live_agents is a HARD non-focus cap
# --------------------------------------------------------------------------- #
def _world_with_living(cap, living_by_zone, focus=()):
    """A World whose macro living population per zone is set explicitly, so the
    budget logic can be exercised deterministically."""
    rows, cols = 1, len(living_by_zone)
    cfg = _grid_config(rows=rows, cols=cols, pop=1.0, n_days=1.0)
    w = World(cfg, micro_params=_micro(), max_live_agents=cap, seed=0)
    # Overwrite the macro ledger so living() == the requested per-zone counts.
    w.sim.S = np.asarray(living_by_zone, dtype=float)
    for name in ("E", "Ia", "Is", "R", "D"):
        setattr(w.sim, name, np.zeros(len(living_by_zone)))
    w.set_focus(focus)
    return w


def test_hard_cap_first_candidate_larger_than_cap_is_rejected():
    # A single non-focused zone of 5000 vs a 2500 cap: it must NOT be promoted.
    w = _world_with_living(2500, [5000.0, 100.0])
    frac = np.array([0.9, 0.1])             # the big zone is also the hottest
    kept = w._apply_budget({0, 1}, frac)
    assert 0 not in kept                    # over-cap zone rejected
    assert kept == {1}                      # the affordable zone still fits


def test_hard_cap_multiple_candidates_fitting_exactly():
    # Three 1000-agent zones, cap 3000: all three fit exactly.
    w = _world_with_living(3000, [1000.0, 1000.0, 1000.0])
    frac = np.array([0.3, 0.2, 0.1])
    kept = w._apply_budget({0, 1, 2}, frac)
    assert kept == {0, 1, 2}


def test_hard_cap_focus_zone_may_exceed_cap():
    # A focused 4000-agent zone with a 2500 cap: focus is non-negotiable.
    w = _world_with_living(2500, [4000.0, 500.0], focus=[0])
    frac = np.array([0.1, 0.9])
    kept = w._apply_budget({0, 1}, frac)
    assert 0 in kept                        # focus exceeds the cap, still kept
    # ...and its overage consumes the whole budget, so the auto zone is dropped.
    assert 1 not in kept


def test_hard_cap_auto_zones_after_forced_focus_consumes_budget():
    # Focus consumes 2000 of a 2500 cap; a 1000-agent auto zone does not fit.
    w = _world_with_living(2500, [2000.0, 1000.0, 400.0], focus=[0])
    frac = np.array([0.1, 0.9, 0.8])
    kept = w._apply_budget({0, 1, 2}, frac)
    assert 0 in kept                        # focus
    assert 1 not in kept                    # 2000 + 1000 > 2500 -> rejected
    assert 2 in kept                        # 2000 + 400  <= 2500 -> fits


# --------------------------------------------------------------------------- #
# 3. Empty cells do not generate / relay social belief
# --------------------------------------------------------------------------- #
def _belief_relay(middle_pop):
    """Isolate the *social belief contagion* channel on a 1x3 chain A-M-B.

    A's belief is pinned high every tick; there is no outbreak, no authority
    signal and no fleeing, so the ONLY way belief can reach B is by social
    contagion relayed through the middle cell M. Returns (M_final, B_final).
    A and B are never adjacent, so B can only light up if M relays.
    """
    from asphodel.model import Simulation
    pops = [5000.0, middle_pop, 5000.0]
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(
            grid_rows=1, grid_cols=3, population=pops)),
        n_days=1.0, seed_zone=0, seed_exposed=0.0,   # no disease at all
    )
    sim = Simulation(cfg)
    zero_alarm = np.zeros(sim.Z)
    for _ in range(400):
        sim.belief[0] = 1.0                          # pin A at full panic
        sim._update_belief(zero_alarm)               # belief-only step
    return float(sim.belief[1]), float(sim.belief[2])


def test_empty_middle_cell_does_not_relay_belief():
    # Empty middle: B must stay at the floor -- an empty cell holds no crowd to
    # carry panic from A across to B.
    m_empty, b_empty = _belief_relay(middle_pop=0.0)
    assert m_empty < 0.05, f"empty cell accumulated belief ({m_empty})"
    assert b_empty < 0.05, f"B lit up through the empty cell ({b_empty})"


def test_populated_middle_cell_does_relay_belief():
    # Contrast: a *populated* middle relays panic from A to B as it should, so
    # the empty-cell result above is the population weighting at work, not an
    # accident of a severed graph.
    m_full, b_full = _belief_relay(middle_pop=5000.0)
    assert m_full > 0.3, f"populated middle failed to catch belief ({m_full})"
    assert b_full > 0.1, f"populated middle failed to relay to B ({b_full})"


def test_uniform_population_belief_matches_plain_mix():
    # With uniform population the population-weighted belief mixing must reduce
    # exactly to the plain mobility mix, so classic scenarios are unchanged.
    from asphodel.graph import ZoneGraph
    g = ZoneGraph(GraphParams(grid_rows=4, grid_cols=4, population_per_zone=1000.0))
    assert np.allclose(g.mix, g.belief_mix)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

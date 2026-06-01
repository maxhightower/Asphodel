"""
Phase 5 tests: the ``World`` orchestrator -- running the macro grid together
with dynamically promoted agent zones, with inter-zone flux.

Run with:  python -m pytest tests/test_orchestrator.py -q
       or:  python tests/test_orchestrator.py   (dependency-free smoke run)

Covers the Phase-5 invariants (see ARCHITECTURE.md):

* population is conserved *exactly* across a mixed macro+micro run,
* ``Simulation.step(frozen_internal=...)`` freezes only the named zones'
  internal SEIR and is a no-op when None (macro back-compat),
* zones promote/demote at runtime via the player-focus trigger + hysteresis,
* inter-zone flux actually moves people in/out of a promoted zone,
* the orchestrator is deterministic from (config + seed),
* a single promoted zone still reproduces the macro epidemic in expectation
  (the calibration survives going through the World facade).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import (
    World, ScenarioConfig, MicroParams, HandoffParams, PathogenGenome,
    Simulation, run_macro_reference, STATE_NAMES,
)
from asphodel.macro_ref import passive_macro_config


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
# exact population conservation across the mixed run
# --------------------------------------------------------------------------- #
def test_population_conserved_mixed_run():
    cfg = _grid_config(rows=4, cols=4, pop=1000.0, n_days=60.0)
    w = World(cfg, micro_params=_micro(), seed=1)
    N0 = 1000.0 * 16
    for _ in range(int(60.0 / cfg.dt)):
        wt = w.step()
        assert abs(wt.total_pop - N0) < 1e-6, wt.total_pop
    # The epidemic must actually have promoted zones (otherwise we tested nothing).
    assert wt.D > 0
    assert len(w.promoted) > 0


# --------------------------------------------------------------------------- #
# frozen_internal: freezes the named zones, no-op when None
# --------------------------------------------------------------------------- #
def test_frozen_internal_none_is_macro_backcompat():
    cfg = _grid_config(rows=3, cols=3, n_days=10.0)
    a = Simulation(cfg)
    b = Simulation(cfg)
    for _ in range(40):
        a.step()
        b.step(frozen_internal=None)
    for name in ("S", "E", "Ia", "Is", "R", "D"):
        assert np.allclose(getattr(a, name), getattr(b, name))


def test_frozen_internal_freezes_named_zone():
    # 1x1 grid => no inter-zone flux, so a frozen zone must be perfectly static.
    cfg = passive_macro_config(PathogenGenome(), n_agents=1000, dt=0.25, n_days=10.0,
                               seed_exposed=20)
    sim = Simulation(cfg)
    before = {name: float(getattr(sim, name)[0]) for name in ("S", "E", "Ia", "Is", "R", "D")}
    for _ in range(20):
        sim.step(frozen_internal={0})
    for name in ("S", "E", "Ia", "Is", "R", "D"):
        assert abs(float(getattr(sim, name)[0]) - before[name]) < 1e-9, name


# --------------------------------------------------------------------------- #
# runtime promote / demote via player focus + hysteresis
# --------------------------------------------------------------------------- #
def test_focus_promotes_and_clearing_demotes():
    cfg = _grid_config(rows=4, cols=4, n_days=20.0)
    w = World(cfg, micro_params=_micro(), seed=0)
    # Zone 0 is a corner; the seed is in the centre, so zone 0 has no infection.
    w.set_focus([0])
    w.step()
    assert 0 in w.promoted, "focus must force-promote even with no infection"
    # Clear focus: with zero infectious fraction it is below the demote
    # threshold, so it must demote back to macro.
    w.set_focus([])
    w.step()
    assert 0 not in w.promoted, "clearing focus on an uninfected zone must demote"


# --------------------------------------------------------------------------- #
# inter-zone flux actually moves people across the boundary
# --------------------------------------------------------------------------- #
def test_flux_moves_people_between_promoted_zones():
    # Two zones, both force-promoted.  Put all the infection (and thus the
    # belief/panic that drives fleeing) in zone 1 so people flee 1 -> 0.
    cfg = _grid_config(rows=1, cols=2, pop=1000.0, n_days=40.0)
    cfg.seed_zone = 1
    cfg.seed_exposed = 100.0
    w = World(cfg, micro_params=_micro(), seed=2)
    w.set_focus([0, 1])
    z0_start = sum(w.promoted.get(0).counts().values()) if 0 in w.promoted else 1000
    N0 = 2000.0
    moved = False
    for _ in range(int(40.0 / cfg.dt)):
        wt = w.step()
        assert abs(wt.total_pop - N0) < 1e-6
        if 0 in w.promoted:
            z0_now = sum(w.promoted[0].counts().values())
            if z0_now > z0_start + 5:   # zone 0 gained fleers from zone 1
                moved = True
    assert moved, "no inter-zone flux observed into the safe zone"


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def test_world_determinism():
    cfg = _grid_config(rows=4, cols=4, n_days=40.0)
    wa = World(cfg, micro_params=_micro(), seed=5)
    wb = World(cfg, micro_params=_micro(), seed=5)
    for _ in range(int(40.0 / cfg.dt)):
        ta = wa.step()
        tb = wb.step()
        assert ta.promoted == tb.promoted
        for name in STATE_NAMES:
            assert abs(getattr(ta, name) - getattr(tb, name)) < 1e-9, name


# --------------------------------------------------------------------------- #
# a single promoted zone still reproduces the macro epidemic in expectation
# --------------------------------------------------------------------------- #
def test_single_promoted_zone_matches_macro_in_expectation():
    genome = PathogenGenome()
    N = 1000
    dt, n_days = 0.25, 100.0
    seeds = list(range(30))

    macro = run_macro_reference(genome, N, dt, n_days, seed_exposed=10)
    macro_attack = (N - macro["S"][-1]) / N

    # World as a single passive zone, force-promoted from t=0 (pure agents).
    attacks = []
    for s in seeds:
        cfg = passive_macro_config(genome, N, dt, n_days, seed_exposed=10)
        w = World(cfg, micro_params=_micro(), seed=s)
        w.set_focus([0])
        for _ in range(int(n_days / dt)):
            wt = w.step()
        attacks.append((N - wt.S) / N)
    micro_attack = float(np.mean(attacks))

    rel = abs(micro_attack - macro_attack) / macro_attack
    assert rel < 0.15, (macro_attack, micro_attack, rel)


# --------------------------------------------------------------------------- #
# Phase 6: spatial-hash neighbour search is exact; live-bubble budget caps
# --------------------------------------------------------------------------- #
def test_spatial_hash_matches_pairwise():
    from asphodel.micro import AgentZone
    g = PathogenGenome()
    rng = np.random.default_rng(0)
    for trial in range(15):
        N = int(rng.integers(50, 1200))
        area = float(np.sqrt(N / 0.1))
        z = AgentZone(g, _micro_n(N, area), dt=0.25, seed=trial)
        z.state = rng.integers(0, 6, size=N).astype(np.int8)
        z.pos = rng.uniform(0, z.L, size=(N, 2))
        w = z._infectious_weight()
        ncell = int(z.L // z.r)
        a = z._neighbour_infectious_load_pairwise(w)
        b = z._neighbour_infectious_load_hashed(w, ncell)
        assert np.allclose(a, b, atol=1e-9), (trial, np.abs(a - b).max())


def test_max_live_zones_cap():
    cfg = _grid_config(rows=6, cols=6, n_days=80.0)
    w = World(cfg, micro_params=_micro(), max_live_zones=4, seed=0)
    peak = 0
    for _ in range(int(80.0 / cfg.dt)):
        wt = w.step()
        peak = max(peak, wt.n_promoted)
        assert wt.n_promoted <= 4, wt.n_promoted
    assert peak == 4, f"cap never bound (peak {peak}); test is vacuous"


def test_focus_kept_even_when_cap_is_full():
    # Cap of 2: a focused corner zone (uninfected) must still be promoted, even
    # though higher-infectious zones are competing for the budget.
    cfg = _grid_config(rows=6, cols=6, n_days=60.0)
    w = World(cfg, micro_params=_micro(), max_live_zones=2, seed=0)
    w.set_focus([0])
    promoted_with_focus = False
    for _ in range(int(60.0 / cfg.dt)):
        wt = w.step()
        assert wt.n_promoted <= 2
        if 0 in w.promoted:
            promoted_with_focus = True
    assert promoted_with_focus, "focused zone was dropped by the budget cap"


def test_max_live_agents_cap():
    cfg = _grid_config(rows=6, cols=6, pop=1000.0, n_days=80.0)
    # Budget for ~2.5 zones of ~1000 -> at most 2 full zones promoted.
    w = World(cfg, micro_params=_micro(), max_live_agents=2500, seed=0)
    for _ in range(int(80.0 / cfg.dt)):
        wt = w.step()
        live_agents = sum(z.n for z in w.promoted.values())
        # Never exceed the budget by more than one zone's worth.
        assert live_agents <= 2500 + 1100, live_agents


def _micro_n(n, area):
    return MicroParams(n_agents=n, area_size=area, infection_radius=2.0,
                       mixing_step_frac=0.12)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

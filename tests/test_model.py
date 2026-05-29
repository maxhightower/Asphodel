"""
Sanity tests for the belief-cascade prototype.  Run with:  python -m pytest -q
(or  python tests/test_model.py  for a dependency-free smoke run).

These assert the invariants the design brief calls out: mass conservation,
tick-rate independence, determinism/reproducibility, and that the qualitative
arc (a silent phase followed by a cascade) actually appears in the baseline.
"""

from __future__ import annotations

import copy
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import ScenarioConfig, run_scenario


def _total_people(sim):
    return float(sim.S.sum() + sim.E.sum() + sim.Ia.sum()
                 + sim.Is.sum() + sim.R.sum() + sim.D.sum())


def test_mass_conservation():
    cfg = ScenarioConfig()
    res = run_scenario(cfg, record_belief=False)
    expected = cfg.model.graph.population_per_zone * res.graph.n_zones
    assert abs(_total_people(res.sim) - expected) < 1e-6 * expected


def test_no_negative_compartments():
    res = run_scenario(ScenarioConfig(), record_belief=False)
    for name in ("S", "E", "Ia", "Is", "R", "D"):
        arr = getattr(res.sim, name)
        assert (arr >= -1e-9).all(), f"{name} went negative"


def test_belief_bounds():
    res = run_scenario(ScenarioConfig())
    assert (res.belief_history >= 0.0).all()
    assert (res.belief_history <= 1.0 + 1e-9).all()


def test_determinism():
    a = run_scenario(ScenarioConfig(), record_belief=False)
    b = run_scenario(ScenarioConfig(), record_belief=False)
    assert np.allclose(a.frame.values, b.frame.values)


def test_tick_rate_independence():
    """Halving dt should not change the qualitative arc (tipping day within a
    fraction of a day)."""
    coarse = copy.deepcopy(ScenarioConfig()); coarse.dt = 0.5
    fine = copy.deepcopy(ScenarioConfig()); fine.dt = 0.125
    rc = run_scenario(coarse, record_belief=False)
    rf = run_scenario(fine, record_belief=False)
    assert abs(rc.panic_day(0.5) - rf.panic_day(0.5)) < 2.0


def test_arc_emerges():
    """Baseline should show a silent phase then a cascade: panic should start
    well after t=0 and eventually engulf most of the grid."""
    res = run_scenario(ScenarioConfig(), record_belief=False)
    silent = res.panic_day(0.1)
    full = res.panic_day(0.9)
    assert silent is not None and full is not None
    assert silent > 10.0           # genuine silent phase, not instant panic
    assert full > silent           # it spreads over time (a cascade)
    assert res.frame["n_panic"].max() >= 0.9 * res.graph.n_zones


def test_long_incubation_lengthens_silent_phase():
    short = copy.deepcopy(ScenarioConfig()); short.genome.incubation_period = 3.0
    long = copy.deepcopy(ScenarioConfig()); long.genome.incubation_period = 12.0
    rs = run_scenario(short, record_belief=False)
    rl = run_scenario(long, record_belief=False)
    assert rl.panic_day(0.1) > rs.panic_day(0.1)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

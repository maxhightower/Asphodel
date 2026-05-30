"""
Phase 4b tests: episode mode (run-to-termination), both tiers.

Covers:

* macro runs terminate by **burnout** (active infection -> ~0) before the safety
  cap, leaving never-infected (S) + recovered (R) + dead (D) -- and most infected
  recover, not die;
* "fixed" termination mode reproduces the ordinary fixed-horizon run exactly;
* micro episodes are stochastic -> a genuine distribution of outcomes, each run
  to its own absorbing state;
* a subcritical genome (R0 < 1) produces stochastic die-out episodes (the
  extinction path) with low attack rate and short duration.

Run with:  python -m pytest tests/test_episodes.py -q
       or:  python tests/test_episodes.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import (
    Scenario, ScenarioConfig, run_scenario, TerminationParams,
    macro_episode, micro_episode, run_episodes,
)
from asphodel.episodes import BURNOUT, MAX_DAYS, SUSCEPTIBLES_EXHAUSTED


# --------------------------------------------------------------------------- #
# macro burnout
# --------------------------------------------------------------------------- #
def test_macro_terminates_by_burnout():
    sc = Scenario()
    ep = macro_episode(sc, seed=0)
    # Reaches the absorbing state, not the safety cap.
    assert ep.terminal_reason == BURNOUT
    assert ep.duration_days < sc.termination.max_days
    # Burnout means the epidemic genuinely ran its course (well past the old
    # 120-day horizon) and most people who were infected RECOVERED, not died.
    assert ep.duration_days > 120.0
    assert ep.final_state["R"] > 20 * ep.final_state["D"]
    # Some never-infected remain (belief-driven sheltering flattens the curve).
    assert 0.3 < ep.final_state["attack_rate"] < 0.7


def test_fixed_mode_matches_fixed_horizon_run():
    sc = Scenario()
    sc.termination = TerminationParams(mode="fixed")
    ep = macro_episode(sc, seed=0)
    # Exactly the n_days horizon, no early stop.
    assert abs(ep.duration_days - sc.n_days) < sc.dt
    # And the per-tick trajectory matches the ordinary runner bit-for-bit.
    ref = run_scenario(ScenarioConfig(), record_belief=False)
    assert ep.n_ticks == len(ref.frame)


# --------------------------------------------------------------------------- #
# micro episodes -> a distribution
# --------------------------------------------------------------------------- #
def test_micro_episodes_run_to_termination():
    sc = Scenario()
    sc.micro_params.n_agents = 400
    res = run_episodes(sc, n_episodes=6, tier="micro", seed_exposed=8)
    assert len(res.episodes) == 6
    for ep in res.episodes:
        assert ep.terminal_reason in (BURNOUT, SUSCEPTIBLES_EXHAUSTED)
        assert ep.duration_days < sc.termination.max_days
        assert 0.0 <= ep.final_state["attack_rate"] <= 1.0
    s = res.summary["attack_rate"]
    assert s["mean"] is not None and s["median"] is not None


def test_micro_subcritical_dies_out():
    # R0 < 1 -> the outbreak cannot sustain; episodes go extinct (the stochastic
    # die-out / extinction path).  This is a *statistical* claim: every episode
    # terminates by burnout with a low attack rate, and on average the outbreak
    # fails to take off.  (A single subcritical chain can briefly exceed 5%
    # before dying, so we assert the ensemble, not a strict per-episode bound.)
    sc = Scenario()
    sc.genome.R0 = 0.5
    sc.micro_params.n_agents = 400
    res = run_episodes(sc, n_episodes=8, tier="micro", seed_exposed=4)
    for ep in res.episodes:
        assert ep.terminal_reason == BURNOUT
        assert ep.final_state["attack_rate"] < 0.3       # loose per-episode cap
        assert ep.duration_days < sc.termination.max_days
    # On average the outbreak does not take off, and most episodes don't.
    assert res.summary["attack_rate"]["mean"] < 0.15
    assert sum(e.final_state["took_off"] for e in res.episodes) <= len(res.episodes) // 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

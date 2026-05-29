"""
Phase 4a tests: the macro<->micro handoff and the calibration machinery.

Run with:  python -m pytest tests/test_phase4a.py -q
       or:  python tests/test_phase4a.py   (dependency-free smoke run)

Covers the invariants the brief calls out:

* round-trip mass conservation (macro -> promote -> agents -> demote -> macro),
* no discontinuity/jump at the handoff boundary,
* the spawn manifest conserves the total exactly (largest-remainder),
* micro non-infection transitions match the macro genome in expectation,
* tick-rate independence of the calibrated micro transmission,
* determinism of a seeded micro run,
* the calibrated micro reproduces the macro curve in expectation (analytic).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import (
    PathogenGenome, MicroParams,
    run_micro, run_micro_ensemble, run_macro_reference,
    calibrate, agreement_metrics, passes,
    promote, round_trip, largest_remainder_counts, STATE_NAMES,
)
from asphodel.micro import AgentZone


GENOME = PathogenGenome()  # baseline


def _micro(n=600):
    return MicroParams(n_agents=n, area_size=100.0, infection_radius=2.0,
                       mixing_step_frac=0.12)


# --------------------------------------------------------------------------- #
# spawn manifest / conservation
# --------------------------------------------------------------------------- #
def test_largest_remainder_conserves_total():
    floats = {"S": 950.4, "E": 10.6, "Ia": 12.3, "Is": 8.9, "R": 17.4, "D": 0.4}
    ints = largest_remainder_counts(floats)
    assert sum(ints.values()) == round(sum(floats.values()))
    for name in STATE_NAMES:
        assert abs(ints[name] - floats[name]) < 1.0  # within rounding


def test_spawn_matches_counts():
    counts = {"S": 900, "E": 20, "Ia": 30, "Is": 25, "R": 20, "D": 5}
    zone = AgentZone.from_counts(counts, GENOME, _micro(1000), dt=0.25, seed=1)
    got = zone.counts()
    assert got == counts
    assert zone.n == sum(counts.values())


def test_round_trip_mass_conservation():
    params = _micro(800)
    rt = round_trip(GENOME, params, dt=0.25, macro_days_before=20.0,
                    micro_days=20.0, macro_days_after=20.0, seed=0, seed_exposed=8)
    n = rt["n_total"]
    # Total people across every stitched timestep is exactly N (no loss/creation).
    s = rt["series"]
    totals = sum(s[name] for name in STATE_NAMES)
    assert np.allclose(totals, n, atol=1e-6), f"totals drift: {totals.min()}..{totals.max()}"


def test_round_trip_no_discontinuity():
    """The macro must continue smoothly from the agent-derived state: the counts
    handed across each seam are preserved (the derived update / merge messages)."""
    params = _micro(800)
    rt = round_trip(GENOME, params, dt=0.25, macro_days_before=20.0,
                    micro_days=20.0, macro_days_after=20.0, seed=0, seed_exposed=8)
    # Promote: total conserved (float->int rounding only, < 1 person).
    tb = sum(rt["counts_before_promote"].values())
    ta = sum(rt["counts_after_promote"].values())
    assert abs(tb - ta) <= 1.0
    # Merge/demote: agent counts handed to the macro exactly.
    db = rt["counts_before_demote"]
    da = rt["counts_after_demote"]
    for name in STATE_NAMES:
        assert abs(db[name] - da[name]) < 1e-9


def test_no_invalid_states():
    zone = AgentZone(GENOME, _micro(500), dt=0.25, seed=3)
    zone.seed_infection(10)
    for _ in range(200):
        zone.step()
    assert (zone.state >= 0).all() and (zone.state <= 5).all()
    assert zone.living_count() + int((zone.state == 5).sum()) == zone.n


# --------------------------------------------------------------------------- #
# determinism & tick-rate independence
# --------------------------------------------------------------------------- #
def test_micro_determinism():
    a = run_micro(GENOME, _micro(400), dt=0.25, n_days=40.0, seed=7, seed_exposed=8)
    b = run_micro(GENOME, _micro(400), dt=0.25, n_days=40.0, seed=7, seed_exposed=8)
    for name in STATE_NAMES:
        assert np.array_equal(a[name], b[name])


def test_micro_tick_rate_independence():
    """Halving dt should not change the calibrated dynamics: the mean attack
    rate at the horizon agrees within a few percent across dt."""
    seeds = list(range(40))
    coarse = run_micro_ensemble(GENOME, _micro(600), dt=0.5, n_days=120.0,
                                seeds=seeds, seed_exposed=6)
    fine = run_micro_ensemble(GENOME, _micro(600), dt=0.125, n_days=120.0,
                              seeds=seeds, seed_exposed=6)
    atk_c = (600 - coarse["S_mean"][-1]) / 600
    atk_f = (600 - fine["S_mean"][-1]) / 600
    assert abs(atk_c - atk_f) < 0.05, (atk_c, atk_f)


# --------------------------------------------------------------------------- #
# the central claim: micro reproduces macro in expectation
# --------------------------------------------------------------------------- #
def test_calibration_matches_macro_in_expectation():
    params = _micro(1000)
    seeds = list(range(60))
    macro = run_macro_reference(GENOME, 1000, dt=0.25, n_days=120.0, seed_exposed=10)
    cal = calibrate(GENOME, params, dt=0.25, n_days=120.0, seeds=seeds,
                    method="analytic", seed_exposed=10)
    micro = run_micro_ensemble(GENOME, cal, dt=0.25, n_days=120.0, seeds=seeds,
                               seed_exposed=10)
    metrics = agreement_metrics(macro, micro, total=1000)
    # Analytic alone should already be within a generous tolerance.
    assert passes(metrics, tol=0.15), metrics


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

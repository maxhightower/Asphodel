"""
The calibration procedure (the heart of Phase 4a).

Goal: derive the micro proximity parameters from the genome so that the agent
tier reproduces the macro beta *in expectation*.  Two approaches are provided:

1. **Analytic** (``analytic_contact_prob`` in micro.py): solve the well-mixed
   relation ``p = beta * A / (living * pi r^2)`` directly.  Fast and elegant;
   exact for the perfectly-mixed torus, approximate once movement is finite.

2. **Empirical** (``calibrate_empirical`` here): run the micro at the analytic
   p, measure the realised early-exponential growth rate, compare to the macro's
   growth rate over the same window, and solve for a multiplicative correction
   to p.  Because force of infection (hence the growth rate's transmission term)
   is linear in p, one Newton-like step on log-growth converges fast.

The calibration is a *function of the genome*: ``calibrate(genome, ...)`` returns
the MicroParams to use, and is validated across several genomes in phase4a.py.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .config import PathogenGenome, MicroParams
from .micro import run_micro_ensemble, STATE_NAMES
from .macro_ref import run_macro_reference


# --------------------------------------------------------------------------- #
# growth-rate measurement
# --------------------------------------------------------------------------- #
def _cumulative_infected(series: dict, prefix: str = "") -> np.ndarray:
    """Ever-infected = everyone not still susceptible = N - S (works for both
    macro series and the *_mean micro series via ``prefix``)."""
    s_key = "S" + prefix
    total = sum(series[name + prefix][0] for name in STATE_NAMES)
    return total - series[s_key]


def early_growth_rate(day: np.ndarray, cuminf: np.ndarray,
                      lo_frac: float = 0.01, hi_frac: float = 0.10,
                      total: float | None = None) -> float:
    """Exponential growth rate (per day) of the cumulative-infected curve over
    the early window between ``lo_frac`` and ``hi_frac`` of the population.

    Fit log(cuminf) vs day by least squares on the window; the slope is the
    growth rate rho.  Robust to the exact endpoints as long as the window is in
    the genuinely exponential phase.
    """
    if total is None:
        total = cuminf.max()
    lo, hi = lo_frac * total, hi_frac * total
    mask = (cuminf >= lo) & (cuminf <= hi) & (cuminf > 0)
    if mask.sum() < 3:
        # Window too thin (tiny epidemic); fall back to all positive points.
        mask = cuminf > 0
        if mask.sum() < 3:
            return float("nan")
    x = day[mask]
    y = np.log(cuminf[mask])
    A = np.vstack([x, np.ones_like(x)]).T
    slope, _ = np.linalg.lstsq(A, y, rcond=None)[0]
    return float(slope)


# --------------------------------------------------------------------------- #
# the calibration entry points
# --------------------------------------------------------------------------- #
def calibrate_analytic(genome: PathogenGenome, base: MicroParams) -> MicroParams:
    """Analytic calibration: use the closed-form p (correction = 1.0).

    Returns MicroParams with ``contact_prob=None`` so the per-tick analytic p is
    recomputed from the current ``living`` count each step (tracking N=living)."""
    return replace(base, contact_prob=None, contact_prob_correction=1.0)


def calibrate_empirical(genome: PathogenGenome, base: MicroParams, dt: float,
                        n_days: float, seeds: list[int], seed_exposed: int = 10,
                        n_iter: int = 2, verbose: bool = False) -> MicroParams:
    """Empirical calibration: correct the analytic p so the micro early-growth
    rate matches the macro reference.

    The growth rate's transmission term is linear in the effective beta, which is
    linear in p.  We therefore iterate ``correction <- correction *
    (rho_macro_excess / rho_micro_excess)`` where the "excess" subtracts the
    seed-decay floor.  In practice we match on cumulative-infected growth, which
    is monotone and well-behaved.
    """
    macro = run_macro_reference(genome, base.n_agents, dt, n_days, seed_exposed)
    total = base.n_agents
    macro_cum = _cumulative_infected(macro)
    rho_macro = early_growth_rate(macro["day"], macro_cum, total=total)

    params = replace(base, contact_prob=None, contact_prob_correction=1.0)
    for it in range(n_iter):
        micro = run_micro_ensemble(genome, params, dt, n_days, seeds, seed_exposed)
        micro_cum = _cumulative_infected(micro, prefix="_mean")
        rho_micro = early_growth_rate(micro["day"], micro_cum, total=total)
        if not np.isfinite(rho_micro) or rho_micro <= 0:
            break
        # Match growth rates by scaling the correction.  rho is increasing in
        # the correction; the ratio gives a fast multiplicative update.
        factor = rho_macro / rho_micro
        new_corr = params.contact_prob_correction * factor
        if verbose:
            print(f"  [empirical it={it}] rho_macro={rho_macro:.4f} "
                  f"rho_micro={rho_micro:.4f} factor={factor:.3f} "
                  f"-> correction={new_corr:.3f}")
        params = replace(params, contact_prob_correction=new_corr)
        if abs(factor - 1.0) < 0.02:
            break
    return params


def calibrate(genome: PathogenGenome, base: MicroParams, dt: float,
              n_days: float, seeds: list[int], method: str = "analytic",
              seed_exposed: int = 10, verbose: bool = False) -> MicroParams:
    """Genome -> calibrated MicroParams.  ``method`` is 'analytic' or 'empirical'."""
    if method == "analytic":
        return calibrate_analytic(genome, base)
    if method == "empirical":
        return calibrate_empirical(genome, base, dt, n_days, seeds,
                                   seed_exposed=seed_exposed, verbose=verbose)
    raise ValueError(f"unknown calibration method {method!r}")


# --------------------------------------------------------------------------- #
# agreement metrics
# --------------------------------------------------------------------------- #
def _infectious(series: dict, prefix: str = "") -> np.ndarray:
    return series["Ia" + prefix] + series["Is" + prefix]


def agreement_metrics(macro: dict, micro: dict, total: float) -> dict:
    """Quantitative macro vs mean-micro discrepancy.

    Reports relative error in: peak infectious height, peak timing, final attack
    rate (ever-infected fraction), and early-exponential growth rate.
    """
    m_inf = _infectious(macro)
    u_inf = _infectious(micro, prefix="_mean")
    day = macro["day"]

    m_peak = m_inf.max()
    u_peak = u_inf.max()
    m_peak_day = day[int(np.argmax(m_inf))]
    u_peak_day = day[int(np.argmax(u_inf))]

    m_attack = _cumulative_infected(macro)[-1] / total
    u_attack = _cumulative_infected(micro, prefix="_mean")[-1] / total

    m_rho = early_growth_rate(day, _cumulative_infected(macro), total=total)
    u_rho = early_growth_rate(day, _cumulative_infected(micro, prefix="_mean"),
                              total=total)

    def relerr(a, b):
        denom = abs(a) if abs(a) > 1e-9 else 1.0
        return abs(b - a) / denom

    horizon = day[-1]
    return {
        "peak_height_macro": float(m_peak),
        "peak_height_micro": float(u_peak),
        "peak_height_relerr": float(relerr(m_peak, u_peak)),
        "peak_day_macro": float(m_peak_day),
        "peak_day_micro": float(u_peak_day),
        "peak_day_relerr": float(abs(u_peak_day - m_peak_day) / max(horizon, 1.0)),
        "attack_rate_macro": float(m_attack),
        "attack_rate_micro": float(u_attack),
        "attack_rate_relerr": float(relerr(m_attack, u_attack)),
        "growth_rate_macro": float(m_rho),
        "growth_rate_micro": float(u_rho),
        "growth_rate_relerr": float(relerr(m_rho, u_rho)),
    }


# Default pass tolerance for each relative-error metric (stated in FINDINGS).
DEFAULT_TOLERANCE = 0.10


def passes(metrics: dict, tol: float = DEFAULT_TOLERANCE) -> bool:
    keys = ("peak_height_relerr", "peak_day_relerr",
            "attack_rate_relerr", "growth_rate_relerr")
    return all(metrics[k] <= tol for k in keys)

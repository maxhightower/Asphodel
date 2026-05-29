"""
Phase 4a experiments: prove (or honestly disprove) that a calibrated agent tier
reproduces the macro epidemic curve in expectation, across genomes.

Produces, into ``output/``:

* ``phase4a_overlay_<genome>.png`` -- macro single-zone infectious curve vs the
  mean micro curve over many seeds, with a confidence band.  The headline plot.
* a printed agreement-metrics table (peak height, peak timing, attack rate,
  early growth rate) with pass/fail against the stated tolerance.
* ``phase4a_n_sweep.png`` -- how agreement and variance scale with agent count.
* ``phase4a_demotion_continuity.png`` -- a curve through a promote->demote cycle
  showing no kink at the seams.

Run with:  python -m asphodel.phase4a
"""

from __future__ import annotations

import os
import json

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .config import PathogenGenome, MicroParams
from .micro import run_micro_ensemble, STATE_NAMES
from .macro_ref import run_macro_reference
from .calibration import calibrate, agreement_metrics, passes, DEFAULT_TOLERANCE
from .handoff import round_trip, total_people

OUTDIR = "output"


# --------------------------------------------------------------------------- #
# the validation genomes (vary R0 / incubation / asymptomatic fraction)
# --------------------------------------------------------------------------- #
GENOMES = {
    "baseline": PathogenGenome(R0=3.0, incubation_period=5.0, infectious_period=7.0,
                               asymptomatic_fraction=0.4, symptom_onset_delay=2.0,
                               mortality_fraction=0.02),
    "fast_hot": PathogenGenome(R0=5.0, incubation_period=3.0, infectious_period=5.0,
                               asymptomatic_fraction=0.2, symptom_onset_delay=1.5,
                               mortality_fraction=0.04),
    "slow_silent": PathogenGenome(R0=2.0, incubation_period=10.0, infectious_period=10.0,
                                  asymptomatic_fraction=0.6, symptom_onset_delay=3.0,
                                  mortality_fraction=0.01),
    "low_r0": PathogenGenome(R0=1.6, incubation_period=5.0, infectious_period=7.0,
                             asymptomatic_fraction=0.3, symptom_onset_delay=2.0,
                             mortality_fraction=0.02),
}


def default_micro(n_agents: int = 1000) -> MicroParams:
    return MicroParams(n_agents=n_agents, area_size=100.0, infection_radius=2.0,
                       mixing_step_frac=0.12)


def default_seeds(n: int = 80) -> list[int]:
    return list(range(n))


# --------------------------------------------------------------------------- #
# 1. headline overlay + metrics across genomes
# --------------------------------------------------------------------------- #
def overlay_and_metrics(method: str = "analytic", n_agents: int = 1000,
                        n_seeds: int = 60, dt: float = 0.25, n_days: float = 120.0,
                        seed_exposed: int = 10, genomes: dict | None = None,
                        tol: float = DEFAULT_TOLERANCE) -> dict:
    genomes = genomes or GENOMES
    seeds = default_seeds(n_seeds)
    base = default_micro(n_agents)
    os.makedirs(OUTDIR, exist_ok=True)

    results = {}
    for name, genome in genomes.items():
        macro = run_macro_reference(genome, n_agents, dt, n_days, seed_exposed)
        params = calibrate(genome, base, dt, n_days, seeds, method=method,
                           seed_exposed=seed_exposed, verbose=True)
        micro = run_micro_ensemble(genome, params, dt, n_days, seeds, seed_exposed)
        metrics = agreement_metrics(macro, micro, total=n_agents)
        ok = passes(metrics, tol)
        results[name] = {"metrics": metrics, "passes": ok,
                         "correction": params.contact_prob_correction,
                         "beta": genome.beta()}
        _plot_overlay(name, macro, micro, metrics, ok, method, n_seeds, n_agents)

    _print_metrics_table(results, method, tol)
    return results


def _plot_overlay(name, macro, micro, metrics, ok, method, n_seeds, n_agents):
    day = macro["day"]
    m_inf = macro["Ia"] + macro["Is"]
    u_inf = micro["Ia_mean"] + micro["Is_mean"]
    u_std = np.sqrt(micro["Ia_std"] ** 2 + micro["Is_std"] ** 2)

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5.5))

    axL.plot(day, m_inf, color="black", lw=2.2, label="macro (reference)")
    axL.plot(day, u_inf, color="tab:red", lw=1.6, ls="--",
             label=f"micro mean ({n_seeds} seeds)")
    axL.fill_between(day, u_inf - 2 * u_std, u_inf + 2 * u_std, color="tab:red",
                     alpha=0.20, label="micro ±2σ band")
    axL.set_title(f"Infectious (I_a+I_s):  {name}")
    axL.set_xlabel("day"); axL.set_ylabel("infectious people")
    axL.legend(fontsize=9); axL.grid(alpha=0.3)

    # Cumulative-infected (attack curve) -- the whole-arc check.
    m_cum = n_agents - macro["S"]
    u_cum = n_agents - micro["S_mean"]
    u_cum_std = micro["S_std"]
    axR.plot(day, m_cum, color="black", lw=2.2, label="macro")
    axR.plot(day, u_cum, color="tab:blue", lw=1.6, ls="--", label="micro mean")
    axR.fill_between(day, u_cum - 2 * u_cum_std, u_cum + 2 * u_cum_std,
                     color="tab:blue", alpha=0.20, label="micro ±2σ")
    axR.set_title("Cumulative infected (attack curve)")
    axR.set_xlabel("day"); axR.set_ylabel("ever-infected people")
    axR.legend(fontsize=9); axR.grid(alpha=0.3)

    verdict = "PASS" if ok else "FAIL"
    fig.suptitle(
        f"Phase 4a macro vs mean-micro  [{name}, {method}]   "
        f"peakH err {metrics['peak_height_relerr']*100:.1f}%  "
        f"peakT err {metrics['peak_day_relerr']*100:.1f}%  "
        f"attack err {metrics['attack_rate_relerr']*100:.1f}%  "
        f"growth err {metrics['growth_rate_relerr']*100:.1f}%   -> {verdict}",
        fontsize=11, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(OUTDIR, f"phase4a_overlay_{name}.png")
    fig.savefig(path, dpi=110); plt.close(fig)
    print(f"  -> {path}")


def _print_metrics_table(results, method, tol):
    print(f"\n=== Phase 4a agreement metrics  (method={method}, tol={tol:.0%}) ===")
    hdr = (f"{'genome':<14}{'beta':>7}{'corr':>7}{'peakH%':>9}{'peakT%':>9}"
           f"{'attack%':>9}{'growth%':>9}{'verdict':>9}")
    print(hdr)
    for name, r in results.items():
        m = r["metrics"]
        print(f"{name:<14}{r['beta']:>7.3f}{r['correction']:>7.3f}"
              f"{m['peak_height_relerr']*100:>9.1f}{m['peak_day_relerr']*100:>9.1f}"
              f"{m['attack_rate_relerr']*100:>9.1f}{m['growth_rate_relerr']*100:>9.1f}"
              f"{('PASS' if r['passes'] else 'FAIL'):>9}")


# --------------------------------------------------------------------------- #
# 2. N sweep -- agreement & variance vs agent count
# --------------------------------------------------------------------------- #
def n_sweep(genome_name: str = "baseline", method: str = "analytic",
            n_values=(200, 500, 1000, 2000), n_seeds: int = 60,
            dt: float = 0.25, n_days: float = 120.0, seed_exposed: int = 10) -> dict:
    genome = GENOMES[genome_name]
    seeds = default_seeds(n_seeds)
    os.makedirs(OUTDIR, exist_ok=True)

    peak_err, attack_err, peak_cv = [], [], []
    rows = []
    for N in n_values:
        base = default_micro(N)
        se = max(1, int(round(seed_exposed * N / 1000)))  # keep seed fraction fixed
        macro = run_macro_reference(genome, N, dt, n_days, se)
        params = calibrate(genome, base, dt, n_days, seeds, method=method, seed_exposed=se)
        micro = run_micro_ensemble(genome, params, dt, n_days, seeds, se)
        metrics = agreement_metrics(macro, micro, total=N)
        # Coefficient of variation of the peak infectious height across seeds.
        inf_all = micro["Ia_all"] + micro["Is_all"]
        peaks = inf_all.max(axis=1)
        cv = float(peaks.std(ddof=1) / max(peaks.mean(), 1e-9))
        peak_err.append(metrics["peak_height_relerr"])
        attack_err.append(metrics["attack_rate_relerr"])
        peak_cv.append(cv)
        rows.append((N, metrics["peak_height_relerr"], metrics["attack_rate_relerr"], cv))

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5))
    axL.plot(n_values, np.array(peak_err) * 100, "o-", label="peak-height rel. error")
    axL.plot(n_values, np.array(attack_err) * 100, "s-", label="attack-rate rel. error")
    axL.set_xscale("log"); axL.set_xlabel("agent count N"); axL.set_ylabel("relative error (%)")
    axL.set_title("Macro vs mean-micro agreement vs N"); axL.legend(); axL.grid(alpha=0.3)

    axR.plot(n_values, peak_cv, "o-", color="tab:purple", label="peak-height CV (1/√N ref)")
    ref = peak_cv[0] * np.sqrt(n_values[0]) / np.sqrt(np.array(n_values, float))
    axR.plot(n_values, ref, "k--", alpha=0.6, label="1/√N")
    axR.set_xscale("log"); axR.set_yscale("log")
    axR.set_xlabel("agent count N"); axR.set_ylabel("coefficient of variation")
    axR.set_title("Stochastic spread of the peak vs N"); axR.legend(); axR.grid(alpha=0.3)

    fig.suptitle(f"Phase 4a N sweep  [{genome_name}, {method}]", fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(OUTDIR, "phase4a_n_sweep.png")
    fig.savefig(path, dpi=110); plt.close(fig)

    print(f"\n=== Phase 4a N sweep  [{genome_name}, {method}] ===")
    print(f"{'N':>6}{'peakH%':>10}{'attack%':>10}{'peak_CV':>10}")
    for N, pe, ae, cv in rows:
        print(f"{N:>6}{pe*100:>10.1f}{ae*100:>10.1f}{cv:>10.3f}")
    print(f"  -> {path}")
    return {"rows": rows}


# --------------------------------------------------------------------------- #
# 3. demotion continuity -- one curve through promote -> demote, no kink
# --------------------------------------------------------------------------- #
def demotion_continuity(genome_name: str = "baseline", method: str = "analytic",
                        n_agents: int = 1000, dt: float = 0.25,
                        macro_before: float = 25.0, micro_days: float = 40.0,
                        macro_after: float = 55.0, seed: int = 0,
                        seed_exposed: int = 10) -> dict:
    genome = GENOMES[genome_name]
    base = default_micro(n_agents)
    seeds = default_seeds(40)
    params = calibrate(genome, base, dt, macro_before + micro_days + macro_after,
                       seeds, method=method, seed_exposed=seed_exposed)
    os.makedirs(OUTDIR, exist_ok=True)

    rt = round_trip(genome, params, dt, macro_before, micro_days, macro_after,
                    seed=seed, seed_exposed=seed_exposed)
    s = rt["series"]
    day = s["day"]
    inf = s["Ia"] + s["Is"]
    cum = rt["n_total"] - s["S"]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(day, inf, color="tab:red", lw=1.8, label="infectious (I_a+I_s)")
    ax.plot(day, cum, color="tab:blue", lw=1.4, alpha=0.8, label="cumulative infected")
    ax.axvspan(rt["seam_promote_day"], rt["seam_demote_day"], color="gray",
               alpha=0.15, label="promoted (agents are truth)")
    ax.axvline(rt["seam_promote_day"], color="green", ls=":", lw=1.5, label="promote")
    ax.axvline(rt["seam_demote_day"], color="purple", ls=":", lw=1.5, label="demote")
    ax.set_title(f"Promote -> agents -> demote, no kink at the seams  [{genome_name}]")
    ax.set_xlabel("day"); ax.set_ylabel("people"); ax.legend(fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout()
    path = os.path.join(OUTDIR, "phase4a_demotion_continuity.png")
    fig.savefig(path, dpi=110); plt.close(fig)

    # Conservation report at each seam.
    tb = total_people(rt["counts_before_promote"])
    ta = total_people(rt["counts_after_promote"])
    db = total_people(rt["counts_before_demote"])
    da = total_people(rt["counts_after_demote"])
    print(f"\n=== Phase 4a demotion continuity  [{genome_name}, {method}] ===")
    print(f"  total people  before promote = {tb:.2f}  after promote = {ta:.0f}")
    print(f"  total people  before demote  = {db:.0f}  after demote  = {da:.0f}")
    print(f"  conserved through handoff: {abs(tb-ta) < 1.5 and abs(db-da) < 1e-6}")
    print(f"  -> {path}")
    return rt


def run_all() -> None:
    print("\n########## Phase 4a: macro<->micro calibration ##########")
    print("\n--- Analytic calibration (closed-form p from genome) ---")
    res_an = overlay_and_metrics(method="analytic")
    print("\n--- Empirical calibration (growth-rate correction) ---")
    res_em = overlay_and_metrics(method="empirical")
    sweep = n_sweep()
    demotion_continuity()

    # Clean machine-readable summary (short lines, easy to inspect).
    os.makedirs(OUTDIR, exist_ok=True)
    summary = {"tolerance": DEFAULT_TOLERANCE, "analytic": {}, "empirical": {},
               "n_sweep": sweep["rows"]}
    for key, res in (("analytic", res_an), ("empirical", res_em)):
        for name, r in res.items():
            m = r["metrics"]
            summary[key][name] = {
                "passes": r["passes"], "correction": round(r["correction"], 4),
                "beta": round(r["beta"], 4),
                "peakH_relerr": round(m["peak_height_relerr"], 4),
                "peakT_relerr": round(m["peak_day_relerr"], 4),
                "attack_relerr": round(m["attack_rate_relerr"], 4),
                "growth_relerr": round(m["growth_rate_relerr"], 4),
                "attack_macro": round(m["attack_rate_macro"], 4),
                "attack_micro": round(m["attack_rate_micro"], 4),
            }
    path = os.path.join(OUTDIR, "phase4a_summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote summary -> {path}")


if __name__ == "__main__":
    run_all()

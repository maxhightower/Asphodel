"""
Experiment / sweep runners for the belief-cascade prototype.

Each function answers one of the key questions from the design brief and emits
a comparison plot plus a small printed table.  Configs are always deep-copied
before mutation -- ``dataclasses.replace`` is shallow and would otherwise share
(and corrupt) the nested ModelParams across runs.

Run everything with:  python -m asphodel.experiments
"""

from __future__ import annotations

import copy
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .config import ScenarioConfig
from .runner import run_scenario, RunResult
from . import metrics

OUTDIR = "output"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clone(cfg: ScenarioConfig) -> ScenarioConfig:
    return copy.deepcopy(cfg)


def _tip_days(res: RunResult) -> tuple[float | None, float | None]:
    """(day 10% of zones panic, day 90% of zones panic).

    Delegates to the consolidated ``metrics`` module (Phase 4b) -- same
    definition as before, now defined in exactly one place."""
    n = res.graph.n_zones
    return (metrics.panic_day(res.frame, n, 0.1),
            metrics.panic_day(res.frame, n, 0.9))


def _summary(res: RunResult) -> dict:
    """The Phase 3a experiment summary, re-expressed via ``metrics`` (the
    reported numbers are unchanged -- the formulas live in ``metrics`` now)."""
    n = res.graph.n_zones
    return {
        "silent_until": metrics.panic_day(res.frame, n, 0.1),
        "fully_panicked": metrics.panic_day(res.frame, n, 0.9),
        "tip_sharpness_days": metrics.macro_metrics(res.frame, n)["tip_sharpness_days"],
        "authority_alarm_day": metrics.authority_alarm_day(res.frame),
        "final_dead": metrics.total_dead(res.frame),
        "peak_water_fail": metrics.peak_water_fail(res.frame),
    }


def _print_table(title: str, rows: list[tuple[str, dict]]) -> None:
    print(f"\n=== {title} ===")
    keys = list(rows[0][1].keys())
    header = f"{'variant':<22}" + "".join(f"{k:>22}" for k in keys)
    print(header)
    for label, m in rows:
        line = f"{label:<22}"
        for k in keys:
            v = m[k]
            line += f"{('—' if v is None else f'{v:.2f}'):>22}"
        print(line)


# --------------------------------------------------------------------------- #
# 1. Incubation sweep -- long incubation => long silent "Day -1"
# --------------------------------------------------------------------------- #
def incubation_sweep(base: ScenarioConfig | None = None,
                     values=(2.0, 5.0, 8.0, 12.0)) -> None:
    base = base or ScenarioConfig()
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5))
    rows = []
    for inc in values:
        cfg = _clone(base)
        cfg.genome.incubation_period = inc
        cfg.name = f"incubation={inc}"
        res = run_scenario(cfg, record_belief=False)
        rows.append((f"inc={inc}d", _summary(res)))
        d = res.frame
        infectious = d["I_asymp"] + d["I_symp"]
        axL.plot(d["day"], infectious, label=f"inc={inc}d")
        axR.plot(d["day"], d["belief_mean"], label=f"inc={inc}d")
    axL.set_title("Total infectious vs time"); axL.set_xlabel("day")
    axL.set_ylabel("infectious people"); axL.legend(); axL.grid(alpha=0.3)
    axR.set_title("Mean belief vs time (longer incubation => later alarm)")
    axR.set_xlabel("day"); axR.set_ylabel("mean belief"); axR.legend(); axR.grid(alpha=0.3)
    fig.suptitle("Incubation sweep: silent spread vs visible alarm", fontweight="bold")
    fig.tight_layout()
    path = os.path.join(OUTDIR, "exp_incubation_sweep.png")
    os.makedirs(OUTDIR, exist_ok=True)
    fig.savefig(path, dpi=110); plt.close(fig)
    _print_table("Incubation sweep", rows)
    print(f"  -> {path}")


# --------------------------------------------------------------------------- #
# 2. Belief-coupling sweep -- no cascade -> runaway cascade
# --------------------------------------------------------------------------- #
def belief_coupling_sweep(base: ScenarioConfig | None = None,
                          values=(0.2, 0.4, 0.6, 0.8, 1.0, 1.2)) -> None:
    base = base or ScenarioConfig()
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5))
    rows = []
    sharp_x, sharp_y = [], []
    n = None
    for ws in values:
        cfg = _clone(base)
        cfg.model.belief.w_social = ws
        cfg.name = f"w_social={ws}"
        res = run_scenario(cfg, record_belief=False)
        n = res.graph.n_zones
        m = _summary(res)
        rows.append((f"w_social={ws}", m))
        axL.plot(res.frame["day"], res.frame["n_panic"], label=f"w_social={ws}")
        if m["tip_sharpness_days"] is not None:
            sharp_x.append(ws); sharp_y.append(m["tip_sharpness_days"])
    axL.axhline(n, color="gray", ls=":", lw=1)
    axL.set_title("Zones in panic (the cascade)"); axL.set_xlabel("day")
    axL.set_ylabel("# zones in panic"); axL.legend(fontsize=8); axL.grid(alpha=0.3)
    axR.plot(sharp_x, sharp_y, "o-", color="tab:red")
    axR.set_title("Tip sharpness (days from 10% to 90% panicked)")
    axR.set_xlabel("social-contagion weight"); axR.set_ylabel("days"); axR.grid(alpha=0.3)
    fig.suptitle("Belief-coupling sweep: finding the cascade envelope", fontweight="bold")
    fig.tight_layout()
    path = os.path.join(OUTDIR, "exp_belief_coupling_sweep.png")
    os.makedirs(OUTDIR, exist_ok=True)
    fig.savefig(path, dpi=110); plt.close(fig)
    _print_table("Belief-coupling sweep", rows)
    print(f"  -> {path}")


# --------------------------------------------------------------------------- #
# 3. Authority-lag sweep -- more lag => alarm fires later relative to spread
# --------------------------------------------------------------------------- #
def authority_lag_sweep(base: ScenarioConfig | None = None,
                        values=(2.0, 6.0, 12.0, 20.0)) -> None:
    base = base or ScenarioConfig()
    fig, ax = plt.subplots(figsize=(9, 5.5))
    rows = []
    for lag in values:
        cfg = _clone(base)
        cfg.model.authority.observation_lag_days = lag
        cfg.name = f"lag={lag}"
        res = run_scenario(cfg, record_belief=False)
        rows.append((f"lag={lag}d", _summary(res)))
        ax.plot(res.frame["day"], res.frame["official_signal"], label=f"lag={lag}d")
    # Reference: true visible burden ramp from the last run.
    d = run_scenario(_clone(base), record_belief=False).frame
    visible_frac = (d["I_symp"] + d["D"]) / (base.model.graph.population_per_zone *
                                             base.model.graph.grid_rows * base.model.graph.grid_cols)
    ax2 = ax.twinx()
    ax2.plot(d["day"], visible_frac, color="black", ls="--", lw=1.5, label="true visible fraction")
    ax2.set_ylabel("true visible fraction")
    ax.set_title("Authority lag: official signal fires later as lag grows")
    ax.set_xlabel("day"); ax.set_ylabel("official signal [0-1]"); ax.grid(alpha=0.3)
    l1, lab1 = ax.get_legend_handles_labels(); l2, lab2 = ax2.get_legend_handles_labels()
    ax.legend(l1 + l2, lab1 + lab2, fontsize=8, loc="center right")
    fig.suptitle("Authority-lag sweep", fontweight="bold"); fig.tight_layout()
    path = os.path.join(OUTDIR, "exp_authority_lag_sweep.png")
    os.makedirs(OUTDIR, exist_ok=True)
    fig.savefig(path, dpi=110); plt.close(fig)
    _print_table("Authority-lag sweep", rows)
    print(f"  -> {path}")


# --------------------------------------------------------------------------- #
# 4. Infrastructure coupling on/off
# --------------------------------------------------------------------------- #
def coupling_onoff(base: ScenarioConfig | None = None) -> None:
    base = base or ScenarioConfig()
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(14, 5))
    rows = []
    for enabled in (False, True):
        cfg = _clone(base)
        cfg.model.infrastructure.enabled = enabled
        cfg.name = f"infra={'on' if enabled else 'off'}"
        res = run_scenario(cfg, record_belief=False)
        rows.append((cfg.name, _summary(res)))
        axL.plot(res.frame["day"], res.frame["belief_mean"],
                 label=f"infra {'on' if enabled else 'off'}")
        axR.plot(res.frame["day"], res.frame["n_panic"],
                 label=f"infra {'on' if enabled else 'off'}")
    axL.set_title("Mean belief: infra cascade on vs off"); axL.set_xlabel("day")
    axL.set_ylabel("mean belief"); axL.legend(); axL.grid(alpha=0.3)
    axR.set_title("Zones in panic: infra cascade on vs off"); axR.set_xlabel("day")
    axR.set_ylabel("# zones in panic"); axR.legend(); axR.grid(alpha=0.3)
    fig.suptitle("Infrastructure coupling on/off", fontweight="bold"); fig.tight_layout()
    path = os.path.join(OUTDIR, "exp_coupling_onoff.png")
    os.makedirs(OUTDIR, exist_ok=True)
    fig.savefig(path, dpi=110); plt.close(fig)
    _print_table("Infrastructure coupling on/off", rows)
    print(f"  -> {path}")


def run_all() -> None:
    base = ScenarioConfig()
    incubation_sweep(base)
    belief_coupling_sweep(base)
    authority_lag_sweep(base)
    coupling_onoff(base)


if __name__ == "__main__":
    run_all()

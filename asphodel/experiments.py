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

OUTDIR = "output"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _clone(cfg: ScenarioConfig) -> ScenarioConfig:
    return copy.deepcopy(cfg)


def _tip_days(res: RunResult) -> tuple[float | None, float | None]:
    """(day 10% of zones panic, day 90% of zones panic)."""
    n = res.graph.n_zones
    d = res.frame

    def day_at(frac):
        c = d["n_panic"] >= frac * n
        return float(d.loc[c, "day"].iloc[0]) if c.any() else None

    return day_at(0.1), day_at(0.9)


def _summary(res: RunResult) -> dict:
    t10, t90 = _tip_days(res)
    sharpness = (t90 - t10) if (t10 is not None and t90 is not None) else None
    return {
        "silent_until": t10,        # day the cascade becomes visible (10% zones)
        "fully_panicked": t90,      # day 90% of zones panic
        "tip_sharpness_days": sharpness,
        "authority_alarm_day": res.authority_alarm_day(),
        "final_dead": float(res.frame["D"].iloc[-1]),
        "peak_water_fail": int(res.frame["n_water_fail"].max()),
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


# --------------------------------------------------------------------------- #
# 5. Topology comparison -- diffusion wave (grid) vs synchronized tip
# --------------------------------------------------------------------------- #
def topology_comparison(base: ScenarioConfig | None = None) -> None:
    """Does the cascade synchronize when the graph stops being a pure grid?

    Grid contagion can only diffuse to adjacent zones (a wave); small-world
    shortcuts and commute hubs let belief jump across the map, which should
    compress the tip (10%->90%) toward a near-simultaneous flip.  Open question
    from FINDINGS.md s8.
    """
    base = base or ScenarioConfig()
    variants = [
        ("grid", {"topology": "grid"}),
        ("small_world p=0.1", {"topology": "small_world", "rewire_prob": 0.1}),
        ("small_world p=0.3", {"topology": "small_world", "rewire_prob": 0.3}),
        ("commute (4 hubs)", {"topology": "commute", "n_hubs": 4}),
    ]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    rows = []
    for label, overrides in variants:
        cfg = _clone(base)
        for k, v in overrides.items():
            setattr(cfg.model.graph, k, v)
        cfg.name = label
        res = run_scenario(cfg, record_belief=False)
        rows.append((label, _summary(res)))
        ax.plot(res.frame["day"], res.frame["n_panic"], label=label)
    ax.set_title("Belief cascade by topology: grid wave vs synchronized tip")
    ax.set_xlabel("day"); ax.set_ylabel("# zones in panic")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.suptitle("Topology comparison", fontweight="bold"); fig.tight_layout()
    path = os.path.join(OUTDIR, "exp_topology_comparison.png")
    os.makedirs(OUTDIR, exist_ok=True)
    fig.savefig(path, dpi=110); plt.close(fig)
    _print_table("Topology comparison", rows)
    print(f"  -> {path}")


# --------------------------------------------------------------------------- #
# 6. Intervention demo -- the player levers vs a no-intervention baseline
# --------------------------------------------------------------------------- #
def intervention_demo(base: ScenarioConfig | None = None) -> None:
    """Quantify each Phase-8 player intervention (applied at day 0) vs doing
    nothing, driven through the World.intervene API.

    Promotion is disabled (threshold above 1.0) so this is a deterministic
    macro comparison -- the interventions act on the same fields the agent tier
    would inherit.
    """
    from .config import HandoffParams
    from .orchestrator import World

    base = base or ScenarioConfig()
    seed = base.model.graph.grid_rows // 2 * base.model.graph.grid_cols \
        + base.model.graph.grid_cols // 2
    no_promote = HandoffParams(promote_threshold=2.0, demote_threshold=1.9)

    def run(setup) -> dict:
        cfg = _clone(base)
        w = World(cfg, handoff=no_promote, seed=0)
        if setup:
            setup(w)
        n = int(round(cfg.n_days / cfg.dt))
        panic, days, dead, water = [], [], None, 0
        nz = w.Z
        for _ in range(n):
            wt = w.step()
            panic.append(int((w.sim.belief > cfg.model.belief.panic_threshold).sum()))
            days.append(wt.day)
            dead = wt.D
            water = max(water, int((~w.sim.water_ok).sum()))
        d = np.array(days)
        pa = np.array(panic)

        def day_at(frac):
            c = pa >= frac * nz
            return float(d[c][0]) if c.any() else None
        t10, t90 = day_at(0.1), day_at(0.9)
        return {"final_dead": dead, "silent_until": t10, "fully_panicked": t90,
                "tip_sharpness_days": (t90 - t10) if t10 and t90 else None,
                "peak_water_fail": water}

    variants = [
        ("no intervention", None),
        ("cordon seed @0", lambda w: w.intervene("cordon", zones=[seed])),
        ("broadcast @0", lambda w: w.intervene("broadcast", level=1.0)),
        ("shelter order @0", lambda w: w.intervene("shelter_order", zones=None, strength=0.85)),
        ("staffing @0", lambda w: w.intervene("allocate_staffing", zones=None, amount=1.0)),
        ("cordon + shelter", lambda w: (w.intervene("cordon", zones=[seed]),
                                        w.intervene("shelter_order", zones=None, strength=0.85))),
    ]
    rows = [(label, run(setup)) for label, setup in variants]
    _print_table("Intervention demo (applied at day 0)", rows)


def run_all() -> None:
    base = ScenarioConfig()
    incubation_sweep(base)
    belief_coupling_sweep(base)
    authority_lag_sweep(base)
    coupling_onoff(base)
    topology_comparison(base)
    intervention_demo(base)


if __name__ == "__main__":
    run_all()

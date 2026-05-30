"""
Phase 4b: the scenario engine in action.

This module is the demonstration that the engine is *general enough* -- the old
Phase 3a sweeps and the Phase 4a calibration check are re-expressed here as
``Scenario`` definitions + engine sweeps, replacing the bespoke scripts.  It
also:

* writes the example scenario YAMLs (``scenarios/scn_*.yaml``),
* runs the **regression check** (engine numbers vs the legacy ``experiments.py``
  path, asserted identical -- the data behind ``REGRESSION_PHASE4B.md``),
* runs the **demonstration sweep** (genome x w_social x seed) producing the tidy
  results table + a summary plot.

Run everything:  python -m asphodel.phase4b
Pieces:          python -m asphodel.phase4b --regression | --demo | --scenarios
"""

from __future__ import annotations

import argparse
import copy
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .config import ScenarioConfig, PathogenGenome
from .scenario import Scenario, ScenarioMetadata, get_location_profile
from .engine import (
    run_single, run_ensemble, build_sweep, run_sweep, set_path,
    export_table, dump_sweep_spec,
)
from . import metrics
from . import experiments as legacy

OUTDIR = "output"
SCEN_DIR = "scenarios"


# --------------------------------------------------------------------------- #
# the migrated Phase 3a sweeps, expressed as engine axes
# --------------------------------------------------------------------------- #
# Each entry: (axis dotted-path, values) -- exactly the values the legacy
# experiments swept, now as scenario axes.
PHASE3A_SWEEPS = {
    "incubation": ("genome.incubation_period", (2.0, 5.0, 8.0, 12.0)),
    "w_social": ("model_params.belief.w_social", (0.2, 0.4, 0.6, 0.8, 1.0, 1.2)),
    "authority_lag": ("model_params.authority.observation_lag_days", (2.0, 6.0, 12.0, 20.0)),
    "infra_onoff": ("model_params.infrastructure.enabled", (False, True)),
}


def _base_scenario() -> Scenario:
    """The baseline scenario == the Phase 3a default config, as a Scenario."""
    return Scenario.from_scenario_config(ScenarioConfig(),
                                         metadata=ScenarioMetadata(name="baseline"))


# --------------------------------------------------------------------------- #
# regression: engine numbers must equal the legacy experiments path
# --------------------------------------------------------------------------- #
def _legacy_summary(dotted: str, value) -> dict:
    """Run the legacy code path (ScenarioConfig + experiments._summary) for one
    swept value, returning the legacy summary dict."""
    cfg = ScenarioConfig()
    # mirror set_path on the macro config for the legacy run
    _set_cfg(cfg, dotted, value)
    res = legacy.run_scenario(cfg, record_belief=False)
    return legacy._summary(res)


def _set_cfg(cfg: ScenarioConfig, dotted: str, value) -> None:
    """Apply a scenario-style dotted path to a macro ScenarioConfig (the legacy
    object), translating the ``model_params`` prefix to ``model``."""
    path = dotted.replace("model_params", "model").split(".")
    target = cfg
    for p in path[:-1]:
        target = getattr(target, p)
    setattr(target, path[-1], value)


def regression(tol: float = 1e-9) -> dict:
    """Compare engine outcome metrics to the legacy experiments path for every
    Phase 3a sweep value.  Returns a {sweep: rows} dict for the writeup and
    asserts every comparable number matches within ``tol``."""
    base = _base_scenario()
    report = {}
    print("\n=== Phase 4b regression: engine vs legacy experiments path ===")
    for sweep_name, (dotted, values) in PHASE3A_SWEEPS.items():
        rows = []
        for v in values:
            sc = set_path(base, dotted, v)
            res = run_single(sc, record_belief=False)
            n = res.graph.n_zones
            # engine numbers (mapped to the legacy summary keys for comparison)
            eng = {
                "silent_until": metrics.panic_day(res.frame, n, 0.1),
                "fully_panicked": metrics.panic_day(res.frame, n, 0.9),
                "tip_sharpness_days": metrics.macro_metrics(res.frame, n)["tip_sharpness_days"],
                "authority_alarm_day": metrics.authority_alarm_day(res.frame),
                "final_dead": metrics.total_dead(res.frame),
                "peak_water_fail": metrics.peak_water_fail(res.frame),
            }
            leg = _legacy_summary(dotted, v)
            for k in eng:
                a, b = eng[k], leg[k]
                if a is None or b is None:
                    assert a is b or a == b, (sweep_name, v, k, a, b)
                else:
                    assert abs(a - b) <= tol, (sweep_name, v, k, a, b)
            rows.append((v, eng, leg))
        report[sweep_name] = rows
        print(f"  {sweep_name:<14} {len(values)} values: engine == legacy  ✓")
    print("  ALL Phase 3a sweep numbers reproduce exactly.")
    return report


# --------------------------------------------------------------------------- #
# Phase 4a calibration check, re-expressed as scenario-driven
# --------------------------------------------------------------------------- #
def phase4a_via_scenario(n_seeds: int = 40) -> dict:
    """Re-express the Phase 4a calibration-in-expectation check as scenario
    driven: the genome + micro_params come from a ``Scenario``, then the frozen
    4a calibration/micro path is run.  Proves the engine carries the micro tier
    config, not just the macro coefficients."""
    from .macro_ref import run_macro_reference
    from .calibration import calibrate, agreement_metrics, passes
    from .micro import run_micro_ensemble

    sc = Scenario()
    sc.micro_params.n_agents = 1000
    seeds = list(range(n_seeds))
    g, mp, dt, n_days = sc.genome, sc.micro_params, sc.dt, sc.n_days

    macro = run_macro_reference(g, mp.n_agents, dt, n_days, seed_exposed=10)
    cal = calibrate(g, mp, dt, n_days, seeds, method="analytic", seed_exposed=10)
    micro = run_micro_ensemble(g, cal, dt, n_days, seeds, seed_exposed=10)
    m = agreement_metrics(macro, micro, total=mp.n_agents)
    ok = passes(m, tol=0.15)
    print("\n=== Phase 4a calibration check (scenario-driven, baseline genome) ===")
    print(f"  growth err {m['growth_rate_relerr']*100:.1f}%  "
          f"attack err {m['attack_rate_relerr']*100:.1f}%  "
          f"peakT err {m['peak_day_relerr']*100:.1f}%  "
          f"peakH err {m['peak_height_relerr']*100:.1f}%  -> "
          f"{'PASS' if ok else 'FAIL'} (tol 15%)")
    return {"metrics": m, "passes": ok}


# --------------------------------------------------------------------------- #
# the demonstration sweep: genome x w_social x seed in one command
# --------------------------------------------------------------------------- #
DEMO_GENOMES = {
    "baseline": PathogenGenome(R0=3.0, incubation_period=5.0),
    "fast_hot": PathogenGenome(R0=5.0, incubation_period=3.0),
    "slow_silent": PathogenGenome(R0=2.0, incubation_period=10.0),
}


def demo_sweep(seeds=(0,), w_social_values=(0.2, 0.4, 0.6, 0.8, 1.0, 1.2),
               outdir: str = OUTDIR) -> "pd.DataFrame":
    """genome x w_social x seed -> tidy table (CSV) + a summary plot.

    Shows the engine doing in one call what used to take bespoke scripting:
    sweep two axes across several genomes, get a tidy results table, and plot an
    outcome metric across the sweep."""
    import pandas as pd
    os.makedirs(outdir, exist_ok=True)
    base = _base_scenario()
    base.metadata.name = "demo"

    axes = {
        "genome": list(DEMO_GENOMES.keys()),   # handled specially below
        "model_params.belief.w_social": list(w_social_values),
    }
    # genome is a structured axis, so build scenarios manually for clarity.
    scenarios = []
    for gname, genome in DEMO_GENOMES.items():
        sc_g = copy.deepcopy(base)
        sc_g.genome = copy.deepcopy(genome)
        sc_g.metadata.name = gname
        for axis_values, sc in build_sweep(sc_g, {"model_params.belief.w_social": list(w_social_values)}):
            axis_values = {"genome": gname, **axis_values}
            scenarios.append((axis_values, sc))

    df = run_sweep(scenarios, seeds=list(seeds), progress=True)
    table_path = export_table(df, os.path.join(outdir, "phase4b_demo_sweep.csv"))
    dump_sweep_spec(base, {"genome": list(DEMO_GENOMES), **axes}, list(seeds),
                    os.path.join(outdir, "phase4b_demo_sweep_spec.json"))
    print(f"\n=== Phase 4b demonstration sweep (genome x w_social x seed) ===")
    print(f"  {len(df)} runs -> {table_path}")

    # Summary plot: tip sharpness vs w_social, one line per genome (seed-averaged).
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5))
    for gname in DEMO_GENOMES:
        sub = df[df["genome"] == gname]
        agg = sub.groupby("w_social", as_index=False).agg(
            tip=("tip_sharpness_days", "mean"),
            silent=("silent_phase_days", "mean"))
        axL.plot(agg["w_social"], agg["tip"], "o-", label=gname)
        axR.plot(agg["w_social"], agg["silent"], "o-", label=gname)
    axL.set_title("Tip sharpness (10→90% panic) vs social-contagion weight")
    axL.set_xlabel("w_social"); axL.set_ylabel("days (10%→90%)")
    axL.legend(); axL.grid(alpha=0.3)
    axR.set_title("Silent-phase length vs social-contagion weight")
    axR.set_xlabel("w_social"); axR.set_ylabel("day 10% of zones panic")
    axR.legend(); axR.grid(alpha=0.3)
    fig.suptitle("Phase 4b demo sweep: one command, two axes, three genomes",
                 fontweight="bold")
    fig.tight_layout()
    plot_path = os.path.join(outdir, "phase4b_demo_sweep.png")
    fig.savefig(plot_path, dpi=110); plt.close(fig)
    print(f"  summary plot -> {plot_path}")
    return df


# --------------------------------------------------------------------------- #
# example scenario YAMLs
# --------------------------------------------------------------------------- #
def write_example_scenarios(scen_dir: str = SCEN_DIR) -> list[str]:
    """Write >=3 example Scenario YAMLs, including a start_date axis on the same
    genome (proving the axis is wired even though start_date doesn't yet change
    dynamics)."""
    os.makedirs(scen_dir, exist_ok=True)
    written = []

    # 1. Generic baseline scenario.
    base = _base_scenario()
    base.metadata = ScenarioMetadata(
        name="generic_baseline",
        description="Phase 3a baseline arc, expressed as a Scenario.",
        notes="8x8 grid, generic location, default genome and params.")
    base.start_date = "2020-01-15"
    p = os.path.join(scen_dir, "scn_generic_baseline.yaml")
    base.to_yaml(p); written.append(p)

    # 2 & 3. Same genome + params, two different start_dates on the Houston
    # location -- the start_date axis (dynamics identical this phase; the axis
    # is recorded and threaded for the events phase).
    for label, sdate in (("spring", "2020-03-20"), ("autumn", "2020-09-22")):
        sc = copy.deepcopy(base)
        sc.metadata = ScenarioMetadata(
            name=f"houston_{label}",
            description=f"Houston outbreak starting in {label} ({sdate}).",
            notes="Same genome/params as generic_baseline; only start_date and "
                  "location differ. start_date is carried/recorded this phase "
                  "(events phase will let it drive weather/disasters).")
        sc.location_profile = get_location_profile("houston")
        sc.start_date = sdate
        p = os.path.join(scen_dir, f"scn_houston_{label}.yaml")
        sc.to_yaml(p); written.append(p)

    # 4. A runaway-cascade scenario (w_social past the knee), for completeness.
    runaway = copy.deepcopy(base)
    runaway.metadata = ScenarioMetadata(
        name="runaway_cascade",
        description="Social contagion past the knee (w_social=1.2): a near-"
                    "instant, disease-decoupled tip.",
        notes="Demonstrates the runaway regime from FINDINGS §3.")
    runaway.model_params.belief.w_social = 1.2
    p = os.path.join(scen_dir, "scn_runaway_cascade.yaml")
    runaway.to_yaml(p); written.append(p)

    print("\n=== Example scenarios written ===")
    for p in written:
        # verify each round-trips
        Scenario.from_yaml(p)
        print(f"  {p}")
    return written


# --------------------------------------------------------------------------- #
# inter-zone flux demonstration (conservation + mobility-in-expectation)
# --------------------------------------------------------------------------- #
def flux_demo(n_seeds: int = 8, n_ticks: int = 200, outdir: str = OUTDIR) -> dict:
    """Promote a 2x2 block within a 4x4 macro grid, run flux, and report exact
    conservation + realized-vs-expected inter-zone flux (the 4a-style check)."""
    from .config import GraphParams, ModelParams, MicroParams
    from .model import Simulation
    from .flux import promote_block

    os.makedirs(outdir, exist_ok=True)
    cfg = ScenarioConfig()
    cfg.model = ModelParams(graph=GraphParams(grid_rows=4, grid_cols=4,
                                              population_per_zone=1000.0,
                                              mobility=0.15))
    sim = Simulation(cfg)
    for _ in range(40):
        sim.step()
    g = sim.graph
    block = [g.index(1, 1), g.index(1, 2), g.index(2, 1), g.index(2, 2)]
    mp = MicroParams(n_agents=1000, area_size=100.0, infection_radius=2.0,
                     mixing_step_frac=0.12)

    realized_edges, expected_edges = {}, {}
    max_drift = 0.0
    for s in range(n_seeds):
        fb = promote_block(sim, block, cfg.genome, mp, dt=cfg.dt,
                           flux_rate=cfg.model.graph.mobility, seed=s)
        t0 = fb.total_population()
        for _ in range(n_ticks):
            fb.step(step_dynamics=True)
            max_drift = max(max_drift, abs(fb.total_population() - t0))
        for edge, exp in fb.ledger.expected.items():
            expected_edges[edge] = expected_edges.get(edge, 0.0) + exp
            realized_edges[edge] = realized_edges.get(edge, 0) + fb.ledger.realized.get(edge, 0)

    edges = sorted(e for e in expected_edges if expected_edges[e] >= 1.0)
    exp_v = np.array([expected_edges[e] for e in edges])
    real_v = np.array([realized_edges.get(e, 0) for e in edges])
    ratio = real_v.sum() / exp_v.sum()

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(exp_v, real_v, alpha=0.7)
    lim = max(exp_v.max(), real_v.max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", alpha=0.6, label="realized = expected")
    ax.set_xlabel("expected inter-zone flux  (flux_rate · mix[i,j] · Nᵢ, summed)")
    ax.set_ylabel("realized inter-zone flux  (agents that crossed i→j)")
    ax.set_title(f"Micro inter-zone flux matches macro mobility\n"
                 f"{n_seeds} seeds × {n_ticks} ticks, aggregate ratio = {ratio:.3f}")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    path = os.path.join(outdir, "phase4b_flux.png")
    fig.savefig(path, dpi=110); plt.close(fig)

    print("\n=== Phase 4b inter-zone flux demonstration ===")
    print(f"  population conservation: max drift over {n_seeds}×{n_ticks} steps "
          f"= {max_drift:.2e} people (exact)")
    print(f"  realized/expected inter-zone flux (aggregate) = {ratio:.4f}")
    print(f"  -> {path}")
    return {"max_drift": max_drift, "ratio": float(ratio),
            "n_edges": len(edges)}


# --------------------------------------------------------------------------- #
# episode mode (run-to-termination) demonstration
# --------------------------------------------------------------------------- #
def episodes_demo(n_episodes: int = 24, outdir: str = OUTDIR) -> dict:
    """Run-to-termination on both tiers: one macro burnout + a micro episode
    distribution (incl. a subcritical die-out case), with a summary plot."""
    from .episodes import macro_episode, run_episodes

    os.makedirs(outdir, exist_ok=True)
    print("\n=== Phase 4b episode mode (run to termination) ===")

    # Macro: deterministic, runs to burnout (well past the old 120-day horizon).
    macro = macro_episode(_base_scenario(), seed=0)
    fs = macro.final_state
    print(f"  MACRO baseline: {macro.terminal_reason} at day {macro.duration_days:.0f} "
          f"-> attack {fs['attack_rate']:.1%}, recovered {fs['R']:.0f}, dead {fs['D']:.0f} "
          f"(infected mostly recover, not die)")

    # Micro: stochastic -> a real distribution of outcomes, each to termination.
    sc = Scenario(); sc.micro_params.n_agents = 1000
    res = run_episodes(sc, n_episodes=n_episodes, tier="micro", seed_exposed=10)
    atk = res.summary["attack_rate"]; dur = res.summary["duration_days"]
    print(f"  MICRO baseline ({n_episodes} episodes): reasons={res.reasons}")
    print(f"    attack rate: mean {atk['mean']:.1%}  p5 {atk['p5']:.1%}  p95 {atk['p95']:.1%}")
    print(f"    duration:    mean {dur['mean']:.0f}d  p5 {dur['p5']:.0f}d  p95 {dur['p95']:.0f}d")

    # Subcritical genome -> stochastic die-out (extinction) episodes.
    sub = Scenario(); sub.genome.R0 = 0.7; sub.micro_params.n_agents = 1000
    res_sub = run_episodes(sub, n_episodes=n_episodes, tier="micro", seed_exposed=5)
    atk_sub = res_sub.summary["attack_rate"]
    print(f"  MICRO subcritical (R0=0.7): reasons={res_sub.reasons}  "
          f"attack mean {atk_sub['mean']:.1%} (outbreak fails to take off)")

    # Plot: per-episode attack vs duration (supercritical vs subcritical).
    fig, ax = plt.subplots(figsize=(8, 5.5))
    a1 = [e.final_state["attack_rate"] for e in res.episodes]
    d1 = [e.duration_days for e in res.episodes]
    a0 = [e.final_state["attack_rate"] for e in res_sub.episodes]
    d0 = [e.duration_days for e in res_sub.episodes]
    ax.scatter(d1, a1, alpha=0.7, label="baseline (R0=3): takes off, burns out")
    ax.scatter(d0, a0, alpha=0.7, color="tab:red", label="subcritical (R0=0.7): dies out")
    ax.set_xlabel("episode duration (days to termination)")
    ax.set_ylabel("attack rate (ever-infected fraction)")
    ax.set_title(f"Episode mode: {n_episodes} micro runs each to its absorbing state")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    path = os.path.join(outdir, "phase4b_episodes.png")
    fig.savefig(path, dpi=110); plt.close(fig)
    print(f"  -> {path}")
    return {"macro": macro, "micro_reasons": res.reasons,
            "subcritical_reasons": res_sub.reasons}


# --------------------------------------------------------------------------- #
def run_all() -> None:
    write_example_scenarios()
    regression()
    phase4a_via_scenario()
    flux_demo()
    episodes_demo()
    demo_sweep()


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4b scenario-engine demos")
    ap.add_argument("--regression", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--scenarios", action="store_true")
    ap.add_argument("--phase4a", action="store_true")
    ap.add_argument("--flux", action="store_true")
    ap.add_argument("--episodes", action="store_true")
    args = ap.parse_args()
    if not any([args.regression, args.demo, args.scenarios, args.phase4a,
                args.flux, args.episodes]):
        run_all()
        return
    if args.scenarios:
        write_example_scenarios()
    if args.regression:
        regression()
    if args.phase4a:
        phase4a_via_scenario()
    if args.flux:
        flux_demo()
    if args.episodes:
        episodes_demo()
    if args.demo:
        demo_sweep()


if __name__ == "__main__":
    main()

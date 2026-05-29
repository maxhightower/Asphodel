#!/usr/bin/env python3
"""
Command-line scenario runner for the Asphodel belief-cascade prototype.

Examples
--------
  # Run the built-in default scenario, write CSV + plots into output/
  python run.py

  # Run a scenario described by a YAML file
  python run.py --config scenarios/baseline.yaml

  # Override a few knobs from the command line
  python run.py --w-social 1.0 --incubation 8 --seed 3 --name hot_cascade

  # Run several seeds and compare the tipping point
  python run.py --seeds 0 1 2 3 4

  # Run the full experiment suite (all four sweeps)
  python run.py --experiments

  # Also render a belief-cascade GIF (needs pillow)
  python run.py --animate
"""

from __future__ import annotations

import argparse
import copy
import os

from asphodel.config import ScenarioConfig
from asphodel.runner import run_scenario, run_multi_seed
from asphodel.viz import time_series_plot, belief_snapshots, belief_animation


def build_config(args) -> ScenarioConfig:
    if args.config:
        cfg = ScenarioConfig.from_yaml(args.config)
    else:
        cfg = ScenarioConfig()
    # Command-line overrides (only applied when given).
    if args.name:
        cfg.name = args.name
    if args.seed is not None:
        cfg.seed = args.seed
    if args.days is not None:
        cfg.n_days = args.days
    if args.dt is not None:
        cfg.dt = args.dt
    if args.incubation is not None:
        cfg.genome.incubation_period = args.incubation
    if args.r0 is not None:
        cfg.genome.R0 = args.r0
    if args.w_social is not None:
        cfg.model.belief.w_social = args.w_social
    if args.mobility is not None:
        cfg.model.graph.mobility = args.mobility
    if args.no_infra:
        cfg.model.infrastructure.enabled = False
    if args.no_authority:
        cfg.model.authority.enabled = False
    if args.events:
        cfg.model.events.enabled = True
    return cfg


def report(res) -> None:
    print(f"\nScenario '{res.config.name}'  seed={res.seed}  "
          f"dt={res.config.dt}  days={res.config.n_days}")
    print(f"  silent until (10% zones panic) : {res.panic_day(0.1)}")
    print(f"  tipping point (50% zones panic) : {res.panic_day(0.5)}")
    print(f"  fully panicked (90% zones)      : {res.panic_day(0.9)}")
    print(f"  authority alarm day             : {res.authority_alarm_day()}")
    print(f"  peak-infection day              : {res.peak_infection_day():.1f}")
    print(f"  final dead                      : {res.frame['D'].iloc[-1]:.0f}")
    print(f"  peak water failures             : {int(res.frame['n_water_fail'].max())} zones")


def main() -> None:
    p = argparse.ArgumentParser(description="Asphodel belief-cascade prototype runner")
    p.add_argument("--config", help="YAML scenario file")
    p.add_argument("--name", help="scenario name (for output filenames)")
    p.add_argument("--seed", type=int, help="RNG seed")
    p.add_argument("--seeds", type=int, nargs="+", help="run several seeds and compare")
    p.add_argument("--days", type=float, help="simulated horizon in days")
    p.add_argument("--dt", type=float, help="tick length in days")
    p.add_argument("--incubation", type=float, help="genome incubation period (days)")
    p.add_argument("--r0", type=float, help="genome R0")
    p.add_argument("--w-social", type=float, dest="w_social", help="social-contagion weight")
    p.add_argument("--mobility", type=float, help="inter-zone mobility fraction")
    p.add_argument("--no-infra", action="store_true", help="disable infrastructure cascade")
    p.add_argument("--no-authority", action="store_true", help="disable authority signal")
    p.add_argument("--events", action="store_true", help="enable stochastic events")
    p.add_argument("--animate", action="store_true", help="also render belief GIF")
    p.add_argument("--experiments", action="store_true", help="run the full sweep suite")
    p.add_argument("--phase4b", action="store_true",
                   help="run the Phase 4b scenario-engine suite "
                        "(regression + inter-zone flux + demo sweep)")
    p.add_argument("--outdir", default="output", help="output directory")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    if args.experiments:
        from asphodel.experiments import run_all
        run_all()
        return

    if args.phase4b:
        from asphodel.phase4b import run_all
        run_all()
        return

    base = build_config(args)

    if args.seeds:
        results = run_multi_seed(base, args.seeds)
        print(f"\nMulti-seed comparison ({len(results)} seeds):")
        print(f"{'seed':>6}{'silent10%':>12}{'tip50%':>10}{'panic90%':>10}{'final_dead':>12}")
        for r in results:
            print(f"{r.seed:>6}{str(r.panic_day(0.1)):>12}{str(r.panic_day(0.5)):>10}"
                  f"{str(r.panic_day(0.9)):>10}{r.frame['D'].iloc[-1]:>12.0f}")
        # Plot the first seed in detail.
        base0 = results[0]
        time_series_plot(base0, os.path.join(args.outdir, f"{base.name}_timeseries.png"))
        belief_snapshots(base0, os.path.join(args.outdir, f"{base.name}_belief.png"))
        return

    res = run_scenario(base)
    res.to_csv(os.path.join(args.outdir, f"{base.name}_aggregate.csv"))
    time_series_plot(res, os.path.join(args.outdir, f"{base.name}_timeseries.png"))
    belief_snapshots(res, os.path.join(args.outdir, f"{base.name}_belief.png"))
    if args.animate:
        gif = belief_animation(res, os.path.join(args.outdir, f"{base.name}_belief.gif"))
        if gif is None:
            print("  (animation skipped: pillow not available)")
    report(res)
    print(f"\nOutputs written to {args.outdir}/")


if __name__ == "__main__":
    main()

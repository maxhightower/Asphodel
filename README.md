# Asphodel — Phase 3a: Belief-Cascade Prototype

A headless, 2D/no-graphics Python simulation of an outbreak spreading through a
small grid of abstract **zones**, where what drives behaviour is not the
infection itself but what people *believe* about it.

The single research question this prototype exists to answer:

> **Does a believable `Day −1 → Day 0 → collapse` arc *emerge* from the belief
> dynamics — a period of normalcy while infection silently climbs, then a rapid
> social tipping point into panic — and can we control it?**

The short answer (see [`FINDINGS.md`](FINDINGS.md)): **yes, and yes.** The arc
emerges robustly and the tipping point is tunable from "gradual diffusion wave"
to "near-instant runaway" via a single social-contagion weight.

This is a throwaway research prototype — plain Python, matplotlib, CSV. No game
engine, no 3D, no real map data. It builds only the **macro/abstract tier** of
the larger Asphodel design (the whole-city math), and only the epidemic +
belief + minimal coupling pieces of it.

---

## The model

Everything is a **coupled field over a zone graph**. Each zone holds a small
bundle of state; the interesting behaviour comes from the coupling rules
between fields, not from any single field's complexity.

| Field | What it is |
|---|---|
| **Infection** | SEIR metapopulation: `S, E, I_asymptomatic, I_symptomatic, R, D` per zone. Structure & rates derived from a pathogen *genome* (R0, incubation, infectious period, asymptomatic fraction, symptom-onset delay, mortality). |
| **Belief** ∈ [0,1] | Perceived danger per zone. Updated from three channels — **(1) direct observation** of *visible* burden (`I_symptomatic + D`), **(2) social contagion** from neighbours (the cascade), **(3) the authority's official signal** — plus an infrastructure-alarm channel. Has inertia, a per-tick step cap, an asymmetric rise/decay, and a floor. |
| **Behaviour** | Belief drives aggregate multipliers: **sheltering** (cuts within-zone contact → lowers β) and **fleeing** (moves population along edges toward safer zones). This closes the core feedback loop. |
| **Infrastructure** | One coupled cascade: `staffing → power → water`. Staffing falls as people die / flee / shelter; failures raise belief and force movement. Toggleable. |
| **Authority** | A single global actor that observes a **lagged, partial** (visible-only) view of the epidemic and raises the official signal when it crosses an alarm threshold — so in long-incubation scenarios it necessarily reacts *late*. |
| **Events** *(stretch)* | Poisson exogenous shocks + an emergent transport-hazard expectation (panic-congestion ~ outflow², operator incapacitation ~ infected fraction of fleers). Toggleable, logged as numbers. |

The single most important coupling loop:

```
belief → behaviour (shelter / flee) → infection + movement
       → visible burden → observation → belief …          (+ social contagion between zones)
```

The engine is explicit discrete-time difference equations at a fixed `dt`; all
rates scale by `dt` so the dynamics are **tick-rate independent**, and runs are
**deterministic** from `(config + seed)`.

---

## Layout

```
asphodel/
  config.py        # PathogenGenome, ModelParams, ScenarioConfig (dataclasses, YAML round-trip)
  graph.py         # ZoneGraph: grid topology + mobility mixing matrices
  model.py         # Simulation: the coupled-field update loop
  runner.py        # run_scenario / run_multi_seed + RunResult + CSV export
  viz.py           # time-series plots, belief heatmap snapshots, optional GIF
  experiments.py   # the four parameter sweeps
scenarios/         # YAML scenario presets (baseline, runaway, long Day-1, events)
tests/             # invariant + arc tests
run.py             # CLI entry point
FINDINGS.md        # the written readout (the actual deliverable)
```

The **model** is cleanly separated from the **scenario/config** and from the
**visualization/output**. Every important coefficient is an exposed parameter —
the whole point is sweeping them.

---

## Quick start

```bash
pip install numpy matplotlib pandas pyyaml

# Run the default scenario: writes CSV + time-series + belief-cascade snapshots
python run.py

# Run from a YAML scenario, and also render the cascade GIF
python run.py --config scenarios/baseline.yaml --animate

# Override knobs from the command line
python run.py --w-social 1.0 --incubation 8 --name hot_cascade
python run.py --no-infra              # infrastructure cascade off
python run.py --events                # stochastic events on

# Compare several seeds (only diverge when events are enabled)
python run.py --seeds 0 1 2 3 4

# Run the full experiment suite (four sweeps → output/*.png + tables)
python run.py --experiments      # or:  python -m asphodel.experiments

# Tests (invariants + arc)
python tests/test_model.py       # or:  python -m pytest -q
```

Outputs land in `output/`: per-tick aggregate CSV, the four-panel time-series
plot, the belief-cascade heatmap grid (and optional GIF), and the sweep plots.

---

## Key experiments

| Experiment | Question | Plot |
|---|---|---|
| **Incubation sweep** | Does long incubation produce a long "normal" Day −1? | `output/exp_incubation_sweep.png` |
| **Belief-coupling sweep** | Where is the envelope between "no cascade" and "runaway"? | `output/exp_belief_coupling_sweep.png` |
| **Authority-lag sweep** | Does more lag fire the alarm later relative to true spread? | `output/exp_authority_lag_sweep.png` |
| **Infra coupling on/off** | Does the infrastructure cascade meaningfully change collapse? | `output/exp_coupling_onoff.png` |

See **[`FINDINGS.md`](FINDINGS.md)** for the numbers, the controllable envelope,
the failure modes, and the answer to the research question.

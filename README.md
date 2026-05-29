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

---

## Phase 4a — Macro↔Micro handoff & calibration

Phase 4a "promotes" a single macro zone into **discrete agents** moving in
continuous 2D space, transmitting by physical **proximity** instead of the
macro's mass-action term, then "demotes" it back to math. It answers one
statistical question:

> **Can the agent-resolved (micro) simulation reproduce the macro model's
> epidemic curve *in expectation*, so that promoting a zone to agents does not
> change how fast the disease spreads — for any pathogen genome?**

The short answer (see [`FINDINGS_PHASE4A.md`](FINDINGS_PHASE4A.md)): **yes.** A
closed-form genome→micro-parameter relation (plus a small, genome-stable ≈1.04×
correction) makes the mean micro epidemic track the macro single-zone curve
across four genomes (β = 0.20–1.00) — growth rate, peak timing and final attack
rate agree to a few percent. The agent model and macro reference reuse the
**same `PathogenGenome`**; only the transmission step is calibrated.

```
asphodel/
  micro.py        # AgentZone: agents on a torus, proximity transmission, spatial-hash neighbours
  macro_ref.py    # the trusted macro Simulation as a single passive closed zone (the ground truth)
  calibration.py  # genome -> micro params (analytic + empirical), growth-rate + agreement metrics
  handoff.py      # promote / derived-update / demote messages, hysteresis, round-trip
  phase4a.py      # overlay+metrics across genomes, N sweep, demotion continuity
```

```bash
# Run the full Phase 4a suite (overlay plots + metrics + N sweep + continuity)
python -m asphodel.phase4a
#   -> output/phase4a_overlay_<genome>.png   macro vs mean-micro (+ ±2σ band)
#   -> output/phase4a_n_sweep.png            agreement & variance vs agent count
#   -> output/phase4a_demotion_continuity.png  promote->demote, no kink at seams
#   -> output/phase4a_summary.json           machine-readable metrics

# Phase 4a tests (round-trip conservation, continuity, calibration-in-expectation)
python tests/test_phase4a.py     # or:  python -m pytest tests/test_phase4a.py -q
```

The micro/handoff parameters are documented as data in
[`scenarios/phase4a_micro.yaml`](scenarios/phase4a_micro.yaml).

---

## Phase 4b — the scenario engine

Phase 4b turns the prototypes into a reusable **scenario engine**: a run is data
*(genome × start_date × location × params × seed)*, runnable single / ensemble /
swept, returning structured results and distribution summaries — plus
**inter-zone agent flux** at the micro tier (several adjacent zones promoted at
once, agents migrate between them, population conserved exactly).

```
asphodel/
  scenario.py   # the Scenario object: composes the existing configs + start_date,
                #   location_profile, flux_params, metadata; YAML round-trip
  metrics.py    # the outcome metrics, consolidated into one place
  engine.py     # run_single / run_ensemble / run_sweep (+ dotted-path axis setter)
  flux.py       # MicroFluxBlock: inter-zone agent flux, layered on the frozen AgentZone
  phase4b.py    # migrated experiments + regression + flux demo + demonstration sweep
```

```bash
# Define a run as data and round-trip it (examples in scenarios/scn_*.yaml)
python -c "from asphodel import Scenario; print(Scenario.from_yaml('scenarios/scn_generic_baseline.yaml').metadata.name)"

# The full Phase 4b suite: example scenarios + regression + flux + demo sweep
python -m asphodel.phase4b          # or:  python run.py --phase4b

# Pieces
python -m asphodel.phase4b --regression   # engine numbers == legacy path, asserted
python -m asphodel.phase4b --flux         # inter-zone flux conservation + mobility check
python -m asphodel.phase4b --demo         # genome × w_social × seed -> output/phase4b_demo_sweep.*
```

A two-axis, multi-seed sweep in one call:

```python
from asphodel import Scenario, build_sweep, run_sweep
base = Scenario()                                          # = the Phase 3a baseline
axes = {"genome.incubation_period": [2, 5, 8, 12],
        "model_params.belief.w_social": [0.6, 0.8, 1.0]}
df = run_sweep(build_sweep(base, axes), seeds=range(20))   # tidy table, one row per run
```

All existing findings are provably intact — see
**[`REGRESSION_PHASE4B.md`](REGRESSION_PHASE4B.md)** (15 old + 11 new tests pass;
every migrated experiment reproduces its headline number exactly) — and the
engine result + inter-zone-flux findings are in
**[`FINDINGS_PHASE4B.md`](FINDINGS_PHASE4B.md)**.

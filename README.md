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

## Phase 5 — The `World` orchestrator (the engine façade)

Phase 5 ties the two tiers into a single **headless engine** a front-end (e.g.
Godot) would render against, without touching any game engine. `World`
(`asphodel/orchestrator.py`) runs the whole-map macro simulation and promotes
zones into agents **at runtime**, exchanging people across the macro↔micro
boundary (the inter-zone flux that Phase 4a left stubbed). Population is
conserved exactly; the disease genome, calibration and handoff messages are all
reused unchanged.

```python
from asphodel import World, ScenarioConfig, MicroParams

world = World(ScenarioConfig(), micro_params=MicroParams())
world.set_focus([world.sim.graph.center_zone()])  # player camera → force-promote
for _ in range(480):
    tick = world.step()                            # advance one dt
snap = world.snapshot()                            # everything the renderer needs
```

The full engine contract, the per-tick orchestration algorithm, the
conservation guarantee, and the roadmap for the remaining simulation work (then
Godot last) are documented in **[`ARCHITECTURE.md`](ARCHITECTURE.md)**.

A real-time **budget cap** sizes the live bubble: `World(max_live_zones=…,
max_live_agents=…)` keeps player-focused zones plus the most-infectious zones
within budget and leaves the rest as math.

```bash
python tests/test_orchestrator.py   # or:  python -m pytest tests/test_orchestrator.py -q
python -m asphodel.bench            # Phase 6: tick-cost benchmark + budget table
```

**Phase 6** made the agent neighbour search genuinely O(n) (a spatial hash, ~600×
faster at 10k agents, bit-identical to the old pairwise scan) and measured the
engine budget: a 1000-agent live zone costs <1 ms/tick, so dozens run in real
time. See **[`FINDINGS_PHASE6.md`](FINDINGS_PHASE6.md)**.

**Phase 7** made the zone graph's topology a swappable dial (`grid` /
`small_world` / `commute`, with per-zone populations and multi-seed outbreaks).
Finding: a commute **hub** graph collapses the cascade's tip ~6× and nearly
doubles deaths, while mild small-world rewiring barely moves it — concentration,
not randomness, synchronizes the panic (`FINDINGS.md` §9).

**Phase 8** lets the player act on the world via `world.intervene(...)` —
`broadcast`, `cordon`, `shelter_order`, `allocate_staffing` — flowing through both
the macro fields and any live agent zone. Finding: propping up infrastructure can
*increase* deaths by muting an alarm the population relied on
(`FINDINGS_PHASE8.md`).

```python
world.intervene("cordon", zones=[seed_zone])         # quarantine a zone
world.intervene("shelter_order", zones=None, strength=0.85)  # all zones
world.intervene("broadcast", level=1.0)              # emergency address
```

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

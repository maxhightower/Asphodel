# FINDINGS — Asphodel Phase 4b: Scenario Engine & Inter-Zone Flux

**What this phase was:** consolidation and integration, not frontier work. Turn
the pile of validated-but-single-purpose prototypes (macro tier, micro tier,
calibration, handoff) into a **reusable scenario engine** — define a run as data
*(genome × start_date × location × params × seed)*, run it single / ensemble /
swept, get back structured results and distribution summaries — plus the one
genuinely new piece of simulation that multi-zone scenarios need: **inter-zone
agent flux** at the micro tier (stubbed in 4a).

**Result:** experiments that used to need hand-built configs and bespoke scripts
now run from a scenario definition; many-seed / many-scenario sweeps are a single
command; inter-zone flux conserves population exactly and reproduces macro
mobility in expectation; and **every Phase 3a and 4a finding reproduces exactly**
(see `REGRESSION_PHASE4B.md`). Models stayed frozen.

Regenerate: `python -m asphodel.phase4b` (writes `output/phase4b_*` and the
example `scenarios/scn_*.yaml`); tests `python -m pytest -q`.

---

## 0. What was built (and what stayed frozen)

| Module | Role | New? |
|---|---|---|
| `asphodel/scenario.py` | The `Scenario` object: composes the existing `PathogenGenome` / `ModelParams` / `MicroParams` / `HandoffParams` + the run-level axes (`start_date`, `location_profile`, `flux_params`, `metadata`, seed/run settings). YAML round-trip; `to_scenario_config()` bridge to the frozen macro engine. | new |
| `asphodel/metrics.py` | The outcome metrics, consolidated from the ad-hoc code in `runner.py` / `experiments.py`, + ensemble distribution summaries. | new |
| `asphodel/engine.py` | `run_single` / `run_ensemble` / `run_sweep`, dotted-path axis setter, optional parallel-by-seed, CSV/parquet export, reproducible sweep-spec dump. | new |
| `asphodel/flux.py` | `MicroFluxBlock`: inter-zone agent flux for a promoted block, layered on top of the **unchanged** `AgentZone`. | new |
| `asphodel/phase4b.py` | Migrated Phase 3a/4a experiments, regression check, example scenarios, demo sweep, flux demo. | new |
| `model.py`, `micro.py`, `calibration.py`, `macro_ref.py`, `handoff.py` | The validated cores. | **frozen, untouched** |
| `runner.py`, `experiments.py` | Lightly refactored to *delegate* to `metrics.py` (no number changed). | refactor only |

---

## 1. What the engine now makes easy

The abstraction is validated by the fact that **every old experiment is now a
few lines of scenario + axis spec**, and reproduces its numbers exactly:

```python
from asphodel import Scenario, build_sweep, run_sweep

base = Scenario()                                   # = the Phase 3a baseline
axes = {"genome.incubation_period": [2, 5, 8, 12],  # any nested field, by name
        "model_params.belief.w_social": [0.6, 0.8, 1.0]}
df = run_sweep(build_sweep(base, axes), seeds=range(20))   # tidy table, one row/run
```

* **Single run** → a full per-tick `RunResult` (same CSV/history/plots as before).
* **Ensemble** (`run_ensemble`, one scenario × many seeds) → per-run outcome
  metrics + mean/median/percentile bands. The metric set is the one the design
  named: silent-phase length, day-of-50%-zones-panic, peak timing/height, attack
  rate, total dead, day-of-infra-collapse, day-of-authority-alarm.
* **Sweep** (`run_sweep`, grid/list of scenarios × seeds) → a tidy DataFrame
  (one row per run, columns = scenario axes + outcome metrics) exported to
  CSV/parquet for offline analysis. `dump_sweep_spec` logs the base scenario +
  axes + seeds so any table regenerates.
* **Determinism**: a run is fixed by scenario + seed; a sweep by base + axes +
  seed list. `run_sweep(...).equals(run_sweep(...))` holds (tested).

**Demonstration sweep** (`phase4b.demo_sweep`, one command): *genome × w_social ×
seed* across three genomes, → `output/phase4b_demo_sweep.csv` (the tidy table) +
`output/phase4b_demo_sweep.png` (tip-sharpness and silent-phase length vs
`w_social`, one line per genome). For the baseline genome the table reproduces
FINDINGS §3 to the decimal (e.g. `w_social=0.8` → silent 24.0, full 48.25, tip
24.25). This is exactly what used to require a bespoke script per axis.

### The scenario identity is real

`Scenario` makes *(genome × start_date × location × params × seed)* a single
round-trippable object (see `scenarios/scn_*.yaml`). `start_date` and
`location_profile` are **carried, recorded, and sweepable now**, even though they
don't yet drive dynamics:

* `scn_houston_spring.yaml` and `scn_houston_autumn.yaml` are the *same genome
  and params* with different `start_date`s — running both gives **identical
  dynamics** (verified), proving the axis is wired and inert, ready for the
  events phase to make it bite.
* `location_profile.population_scale` is the one location parameter that already
  bites (folded into per-zone population in `to_scenario_config`); the houston
  stub additionally records climate-zone / lat-long placeholders.

---

## 2. Inter-zone micro flux (the one new sim piece)

Phase 4a promoted a single zone and stubbed inter-zone flux to zero. Phase 4b
implements it for a block of simultaneously-promoted adjacent zones.

**Design that keeps the frozen dynamics frozen.** Each promoted zone stays an
independent `AgentZone` (its own torus); its internal step — proximity
transmission + genome transitions — is the verbatim 4a code. Migration is a
**separate process layered on top**. With `flux_rate = 0` (or a single zone) a
block is *bit-identical* to independent 4a zones
(`test_flux_zero_reduces_to_independent_zones`). This is why no 4a number moved.

**The conservation ledger.** Each tick, every agent in a promoted zone emigrates
with the dt-correct probability `1 − exp(−flux_rate·dt)`, choosing its
destination neighbour by the **macro mobility weights** `ZoneGraph.mix[i,·]`.
Then:

* **promoted → promoted** (the *live handoff*): the agent is moved into the
  neighbour's agent set with its **full epidemic state preserved**.
* **promoted → non-promoted** (the *demote-side*): the departure is added to that
  neighbour's **macro compartment counts** (the cross-zone flux ledger).

So every agent that leaves a promoted zone arrives somewhere, and the block total
(promoted agents + non-promoted macro counts) is invariant.

### Result 1 — exact conservation

Promoting the central 2×2 block of a 4×4 macro grid (1000 agents/zone) and
running 200 ticks with the epidemic live, across 8 seeds:

```
population conservation: max drift over 8×200 steps = 1.8e-12 people  (exact)
```

The only non-zero "drift" is float round-off at the 1e-12 level. The drain into
the non-promoted macro sinks is real and non-trivial (the demote-side path is
exercised), yet the grand total never changes. Tested in
`test_flux_conserves_total_population`; the all-promoted (fully-internal) case is
tested per-compartment in `test_flux_live_handoff_preserves_compartments`
(every compartment total conserved to 1e-9 with the epidemic frozen — confirming
the live handoff carries state, not just headcount).

### Result 2 — micro flux matches macro mobility in expectation

Same discipline as 4a's transmission calibration: the *expected* per-day flux
from zone i to neighbour j is `flux_rate · mix[i,j] · Nᵢ`. Aggregated over 8
seeds × 200 ticks:

```
realized / expected inter-zone flux (aggregate) = 1.007
```

i.e. realized agent movement reproduces the configured macro-mobility
expectation to **<1%** (`output/phase4b_flux.png` plots realized vs expected per
edge; the points lie on the identity line). The test
`test_flux_matches_mobility_in_expectation` asserts the aggregate ratio within
3% and every meaningful per-edge ratio within 6%.

### Boundary effects / honest caveats

* **"Macro mobility" is a mixing weight, not a movement rate, in the macro
  model.** The macro tier uses `mobility` to mix *infection pressure* (and belief
  contagion); it does not physically relocate population except via belief-driven
  fleeing. So "micro flux reproduces macro mobility" means the micro migration is
  *parameterised to be consistent with the macro mobility structure* (same `mix`
  weights, rate defaulting to `mobility`) and we verify the realised movement
  matches that configured expectation — exactly the thing that is well-defined.
  Reconciling agent flux with the macro's belief-driven fleeing term is left as a
  later modelling decision, not forced here.
* **Flux is currently one-way at the block boundary** (promoted → non-promoted
  macro sink). Modelling the reverse inflow (macro → promoted) would require a
  spawn rule at the boundary; it is a clean extension point (below), out of scope
  for a correctness phase.
* **Migration uses fresh uniform torus positions** on arrival, consistent with
  the well-mixed-per-zone assumption calibration relies on; it does not introduce
  spatial structure across zones (there is none in the macro tier to match).

---

## 3. Episode mode — running to termination, not a fixed horizon

A run can now advance until the epidemic reaches its **absorbing state** instead
of stopping at a fixed `n_days`. The natural end state in this SEIR model is
**burnout** — no *active* infection left (`E + Ia + Is` below a threshold) or
susceptibles exhausted, whichever first — with a `max_days` safety cap. (See
`TerminationParams`; `episodes.py` drives the frozen `Simulation` / `AgentZone`
loops to termination — neither core was edited.)

This also fixed a real mis-scoping: the default `n_days = 120` **cut the baseline
off mid-epidemic** — peak infection isn't until ~day 156. Run to termination, the
baseline macro epidemic resolves at **day 576**, leaving **48.4% attack rate,
152 366 recovered, and 2 603 dead.** Two facts the model insists on:

* **Infected mostly recover, they don't all die** — 152 366 recovered vs 2 603
  dead. "All infected dead" is not a state this model reaches; burnout is.
* **~52% are never infected** at baseline — belief-driven sheltering flattens the
  curve into a herd-immunity-like plateau. "All healthy infected" (S→0) only
  happens without mitigation (~97% attack, resolves by ~day 197).

**Both tiers** run as episodes. The macro tier is deterministic (events off), so
its episodes are identical across seeds. The **micro tier is stochastic**, so N
episodes give a genuine distribution — and naturally include **stochastic
die-out** episodes where the outbreak never takes off:

| micro episodes (baseline genome, N = 1000, 24 runs) | result |
|---|---|
| terminal reason | burnout, 24/24 |
| attack rate | mean 96.4% (p5 95.1%, p95 97.5%) |
| duration to termination | mean 113 d (p5 98, p95 129) |
| subcritical R0 = 0.7 (24 runs) | all burn out, attack ≈ 2.9% (fails to take off) |

(`output/phase4b_episodes.png` plots attack vs duration for take-off vs die-out.)
Run via `python -m asphodel.phase4b --episodes`, or:

```python
from asphodel import Scenario, run_episodes, macro_episode
macro = macro_episode(Scenario(), seed=0)            # one macro run to burnout
res   = run_episodes(Scenario(), 50, tier="micro")   # 50 stochastic episodes + distribution
```

Note the micro single-zone episode is the *passive* SEIR reference (no belief /
behaviour feedback), so it burns hotter (~96% attack) than the macro grid (~48%,
which has the sheltering feedback) — an honest, expected tier difference, not an
error.

---

## 4. Integration bugs / decisions found during consolidation

* **Repo state vs handoff brief.** The session began with Phase 4a not present
  on the working branch; it was merged in before any work, and the 15-test
  baseline re-established, before building. (No code bug — a branch-state issue.)
* **`replace` is shallow** — the existing `experiments._clone` already used
  `copy.deepcopy` for exactly this reason; the engine's `set_path` / `build_sweep`
  follow suit (deep-copy before mutating a nested dataclass) so swept scenarios
  never share-and-corrupt nested `ModelParams`.
* **Metrics had three near-duplicate definitions** (`RunResult`,
  `experiments._tip_days`, `experiments._summary`). Consolidating them into
  `metrics.py` and having the old call sites delegate removed the duplication
  with zero number changes (proven in `REGRESSION_PHASE4B.md`).
* **`None`-valued metrics** (event never occurred, e.g. authority never alarms in
  the runaway regime) are handled explicitly in the ensemble summary
  (`n_missing` counted, dropped from the numeric stats) rather than silently
  coerced — so a metric that only fires in some runs is reported honestly.

---

## 5. Documented extension points (where later phases plug in)

* **Events layer** (hurricanes, freezes, transport hazard): `start_date` +
  `location_profile` are threaded and recorded but inert. The events phase reads
  `Scenario.start_date_obj` and the location's `climate_zone` / lat-long to select
  weather/disaster behaviour — no scenario reshaping needed. `EventParams`
  already exists on the macro side for exogenous shocks.
* **Full `location_profile` behaviour**: only `population_scale` bites today; the
  climatology fields are the hook for population density curves, seasonal
  contact-rate modulation, and disaster climatology.
* **Macro → promoted inflow at the block boundary**: pair the one-way demote-side
  drain with a spawn rule so non-promoted neighbours can feed agents *into* the
  promoted block (turning the block into a true open meso tier).
* **Full spawn manifest** (still TODO from 4a): visibility weights / time-of-day
  density / tracked-vs-ephemeral NPC split — `flux.py` and `handoff.promote`
  currently spawn a representative uniform population.
* **Topology**: `GraphParams` is grid-only today but `ZoneGraph` consumes any
  weight matrix; the flux direction logic reads `graph.mix`, so a small-world or
  real-commute graph drops in without touching flux.

---

## 6. Conclusion for the larger project

Phase 4b delivers the platform the rest of the project builds on: **a trustworthy
scenario engine that makes every future experiment cheap, with all existing
findings provably intact and inter-zone flux conserved.** A run is now data; a
sweep is one command; the macro/micro/calibration cores are untouched and
re-runnable from a `Scenario`; inter-zone agent flux conserves population to
machine precision and reproduces the macro mobility to <1%. The `start_date` /
`location_profile` axes are wired and waiting for the events phase.

**Recommendation: proceed to the events layer.** The cheapest first step is to
let `start_date` × `location_profile` select a climatology and drive the existing
`EventParams` shocks — the scenario plumbing for it already exists.

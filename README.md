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

## Citizen spawn — who the player wakes up as

Part of the game is being **randomly spawned as an ordinary citizen** and having
to live a normal day before the world ends. `asphodel/citizen.py` owns the
*possibility space* that spawn draws from — occupation, age, where you live,
where you work, the shape of your workday (job tasks), and what's in your
pockets — and the deterministic sampler that draws one concrete citizen from it.

The design follows the same "data, not code" rule as the rest of the project,
with one deliberate twist:

> **Agnostic, but slightly determined by the city.** The `CitizenSpawnCatalog`
> (age bands, occupations, item kinds, timing knobs) is *shared and
> city-agnostic*: in principle a citizen of any city can hold any age-eligible
> job and carry any item. A `CityProfile` only ever **biases** that space — via
> age / occupation weight multipliers and, crucially, via which **districts**
> (and therefore which workplaces) exist on its map. A harbor city has a port,
> so it spawns more dock workers; a university town is thick with students.
> Nothing is hard-removed, only reweighted or gated by the city's map.

| Piece | What it is |
|---|---|
| **`CitizenSpawnCatalog`** | The agnostic catalog: weighted `AgeBand`s, `Occupation`s (age range, base weight, workplace category, shift, ordered job `tasks`, starting `inventory`), the common items everyone might carry, and `SpawnParams` (schedule timing, inventory jitter, weight temperature). |
| **`CityProfile`** | A city's `District` map (each district has a *kind*, a residential weight, the workplace categories it hosts, and an optional macro-grid `zone`) plus the occupation/age weight multipliers and inventory multiplier that bias the catalog. |
| **`CitizenProfile`** | The spawn result: age, occupation, home/work district (+ resolved grid zones), a full `ScheduleEntry` day, a rolled inventory, and where the clock found you (`current_location` / `current_activity`). |

Spawn is **deterministic from `(city, catalog, seed)`** — `spawn_population`
derives independent per-citizen RNGs from one base seed (via `SeedSequence`), so
a whole crowd is reproducible and order-stable. Districts carry optional
`ZoneGraph` zone indices, so home/work resolve onto the macro grid and a spawned
crowd can seed the micro `AgentZone`. A fresh citizen spawns **susceptible** —
the epidemic tiers own disease state; this layer is purely *who you are and what
your day looks like*.

```bash
# Spawn and print a few citizens for a city (generic / harbor / university / capital)
python -m asphodel.citizen --city harbor --n 8 --seed 1

# Re-emit the catalog + city presets as YAML (config-as-data)
python -m asphodel.citizen --emit       # -> cities/_catalog.yaml, cities/<city>.yaml

# Tests (determinism, age-eligibility, city biasing, schedule, YAML round-trip)
python tests/test_citizen.py            # or:  python -m pytest tests/test_citizen.py -q
```

The committed possibility space lives as data under
[`cities/`](cities/): the agnostic `cities/_catalog.yaml` plus one YAML per
city. Edit those (or build a `CityProfile` in code) to add a city — no sampler
changes needed.

```python
from asphodel import default_catalog, default_cities, spawn_population

city = default_cities()["university"]
for c in spawn_population(city, default_catalog(), n=5, seed=0):
    print(c.summary())
```

### Populating a real spatial world (`asphodel/world.py`)

The end goal is **choose a city → the world populates from OpenStreetMap →
procedural interiors → NPCs abound**. A `CityProfile` is the entry point to
that pipeline: alongside its biases it carries *how to source its world*, and
`resolve_world(profile, seed)` turns that into a `CityWorld` — a **street graph
+ categorised building footprints + procedural interiors** — that citizens spawn
*into*.

```
choose a city ──► resolve_world ──► CityWorld(StreetMap)
   profile.osm   = OSMSource(...)         ├─ nodes + edges     (real walking routes)
   profile.synth = SynthCitySpec(...)     └─ Building[]        (footprint, levels, category,
                                                 capacity, neighborhood, street_node, Interior)
                          │
   spawn_population_in_world(world, catalog, n, seed)
                          ▼
   CitizenProfile.home_building_id / work_building_id / home_xy / work_xy / commute_metres
```

| Source | What it does |
|---|---|
| **`OSMSource`** → `load_osm` | The real-city path: OSM ways become the street graph and building footprints become `Building`s, with **OSM tags mapped to workplace categories** (`amenity=hospital`→medical, `shop=*`→commercial, `landuse=industrial`→industrial …) via `category_from_osm_tags`. This is a lazily-imported adapter seam — it fails *loudly* with guidance if its GIS toolchain/network isn't available, rather than silently. |
| **`SynthCitySpec`** → `synthesize_city` | The dependency-light fallback: a deterministic gridded street network with zoned building stock (a harbor weights `industrial`/`transit` up, a university `education`). Lets the whole pipeline run and be tested **offline**, and doubles as procedural generation for areas OSM doesn't cover. |

Both sources produce the **identical `StreetMap` / `Building` types**, so
everything downstream is source-agnostic. With a world resolved, spawn changes
in three ways that matter:

- **home / work are real buildings**, weighted by occupant capacity (bigger
  buildings hold more people), not abstract districts;
- **occupation reachability is gated by the building categories actually on the
  map** — no hospital footprint, no nurses — which is the truest form of
  "agnostic, but determined by the city";
- the **commute is street-routed** (`StreetMap.route_length`, Dijkstra over edge
  lengths), and home/work **zones derive from building position**, so a spawned
  crowd still drops cleanly onto the macro `ZoneGraph`.

Building interiors are generated on demand by `generate_interior` (deterministic
room subdivision per floor) — somewhere for the NPCs to actually be.

```bash
# Resolve a city's procedural street map + buildings and spawn citizens into them
python -m asphodel.citizen --world --city harbor --n 6 --seed 1

# Tests for the world layer (synthesis, routing, interiors, world-spawn)
python tests/test_world.py        # or:  python -m pytest tests/test_world.py -q
```

```python
from asphodel import default_catalog, default_cities, resolve_world, spawn_population_in_world

world = resolve_world(default_cities()["harbor"], seed=0)   # synth fallback (offline)
for c in spawn_population_in_world(world, default_catalog(), n=5, seed=1):
    print(c.summary(), "| building", c.home_building_id, "| commute", c.commute_metres, "m")
```

The **OpenStreetMap ingestion is the one remaining seam** (`load_osm`): the
data model, tag→category mapping, routing, interiors, and NPC placement are all
in place and tested against the procedural source; wiring a GIS toolchain
(e.g. `osmnx` + `shapely`, or `pyrosm` for offline `.pbf` extracts) makes the
*real-city* path live.

### Game time & pacing (`asphodel/gametime.py`)

`TimeScale` bridges **real player seconds ↔ the in-game clock the schedule runs
on ↔ the simulation's tick/day axis**, with Project-Zomboid-style defaults:

- **A full 24-hour cycle = 1 real hour** (PZ's default Day Length; tunable via
  `real_seconds_per_day`). At the default `dt=0.25`, one sim tick = 900 real
  seconds.
- **Collapse lands within ~2 in-game days.** The epidemic is a long, calibrated
  arc, so rather than distort its dynamics, the player clock is *warped*:
  `collapse_warp` pins the player's day 2 onto the simulation's panic tipping
  day, so however long the pathogen actually takes, the player reaches collapse
  on schedule (`plan_session` reports the real-minutes-to-collapse). Near the
  tip the warp relaxes toward real-time for full tension.
- **Downtime fast-forwards** — `schedule_playback` compresses sleep/idle blocks
  (PZ's skip key) so a session is the interesting hours, and turns a citizen's
  in-game-hour day into a wall-clock timeline a game loop can drive directly.

```python
from asphodel import default_timescale
print(default_timescale().summary(sim_panic_day=42.0))
# day length: 60 real min/in-game day (900s per sim tick)
# collapse: sim day 42.0 -> player day 2.0 (warp x21.0), ~120 min in
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

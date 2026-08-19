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

### Vehicles & traffic (`asphodel/vehicles.py`)

Citizens don't teleport — they **move across the street map**, and when they all
move at once the roads **jam**. This closes the citizens → buildings → streets
loop:

- **Travel mode per commuter.** Driving/emergency jobs come with a **work
  vehicle** (`bus_driver`→bus, `truck_driver`→truck, `delivery_driver`→van,
  `paramedic`→ambulance, `police_officer`→police car …); everyone else picks
  walk / bike / car / motorcycle / transit by trip distance and age (short hops
  cycle, long hops drive, under-17s never drive, transit only where the city has
  it). Each `VehicleSpec` carries a free-flow speed and a **PCU** road-space
  weight (foot/bike = 0 — they don't jam).
- **Road network + congestion.** `RoadNetwork.from_street_map` gives every
  street segment a speed and capacity; `assign_traffic` routes a trip set and
  applies the standard **BPR volume-delay** relation
  `t = t₀·(1 + α·(V/C)^β)`, so a morning commute — or a panicked mass exodus —
  produces real travel times and bottlenecks, not instant movement.
- **Hook into the cascade.** `congestion_report` assigns a whole spawned
  population's commute and reports the network load (mean/worst V/C). This is the
  micro-tier origin of the macro model's *emergent transport hazard*
  (`EventParams`: panic-congestion ~ outflow², operator incapacitation ~ infected
  fraction of fleers) — a fleeing crowd drives these sharply up.

```bash
# Spawn into a real map AND print a morning-commute traffic snapshot
python -m asphodel.citizen --world --city harbor --n 6 --seed 2
#   ... 301 commuters, 133 motorized, 1018 PCU on 91 segments
#       network load 0.02 (mean V/C), worst 0.07, mean commute 2.9 min
```

```python
from asphodel import (default_catalog, default_cities, resolve_world,
                      spawn_population_in_world, congestion_report)
world = resolve_world(default_cities()["capital"], seed=0)
pop = spawn_population_in_world(world, default_catalog(), n=800, seed=0)
print(congestion_report(world, pop))   # commuters, PCU, network_load, max_voc, mean_commute_min
```

The single-pass (all-or-nothing) assignment is adequate for a commute snapshot
or an exodus pulse; iterating to user-equilibrium is the documented next step.

> **Job diversity.** The catalog ships **51 occupations** across medical,
> education, civic, commercial, industrial, transit and home categories —
> including the driving/logistics roles the traffic layer needs (taxi, delivery,
> truck, courier, postal, bus), on-site specialists (window washer, train
> conductor, corrections officer, landscaper) and aircrew (pilot, flight
> attendant, helicopter pilot, air-traffic controller). Add more by editing
> `default_catalog()` / `cities/_catalog.yaml`; a job spawns in any city whose
> map hosts its workplace category.

### Signature scenarios (`asphodel/signatures.py`)

Being spawned into a job isn't just a label and an inventory — it drops you into
**the one predicament that job authors naturally** when the world ends. Every
occupation owns a `SignatureScenario` (data): a defining location, the situation
unfolding when collapse hits, the **dilemma** it forces, the **assets** the job
hands you in that moment, the **hazards** working against you, and reusable
**tags** (`height`, `trapped`, `vehicle_moving`, `mass_casualty`, `crowd`,
`children`, `keys_access`, `tools`, `supplies`, `weapons`, …) a game layer can
switch on.

A few, to show the range:

| Occupation | Signature |
|---|---|
| **nurse** | on the ward as the casualties flood in — triage who you can save, or walk out |
| **window_washer** | stranded in a cradle thirty storeys up when the building's power dies |
| **train_conductor** | doing 90 between stations with a train full of people you're responsible for |
| **corrections_officer** | lockdown fails halfway — some cells open, some don't |
| **childcare_worker** | naptime, a dozen toddlers, and no parents answering |
| **landscaper** | three lawns from the truck — every house around you a possible shelter |
| **construction_worker** | a site full of power tools, generators and materials to barricade with |
| **mechanic** | a garage of working cars with the keys in the office |

The resolution is **location-aware** — `resolve_collapse_situation(citizen,
collapse_hour, world)` looks at *where the citizen physically is* at the moment
the world tips and picks accordingly:

| Where you are | What fires |
|---|---|
| **at the workplace** (on shift) | the occupation's **signature scenario**, bound to your concrete building + on-hand kit |
| **mid-commute** | a **vehicle/traffic event** keyed to the road you're on (below) |
| **out on an errand** | caught out in public |
| **at home** (off shift) | off-duty — your job's edge left back at work |

So whether you get the nurse-in-the-flood moment depends on shift vs *when* the
collapse lands (see `TimeScale.collapse_by_day`) — a nurse asleep at home has her
edge back at the hospital, not with her — which makes a random spawn genuinely
re-playable.

#### Travel / traffic events (`asphodel/travel_events.py`)

Being caught *in transit* is its own class of predicament, independent of your
job. Street segments carry a **structure** — surface / highway / bridge / tunnel
/ ramp (tagged procedurally, or from OSM `bridge`/`tunnel`/`highway` tags via
`structure_from_osm_tags`) — which also makes bridges and tunnels traffic
**chokepoints** (lower capacity) and highways fast. When a citizen is caught
mid-commute, the event is selected from the **road structure they're actually on**
(routed home↔work on the network) and their **vehicle**:

| Structure | Event |
|---|---|
| surface | total gridlock; junction pile-up |
| highway | a fuel **tanker goes up**; the motorway concertinas into a pile-up |
| ramp | **stranded on the flyover**, cars locked solid both ways, a long drop either edge |
| bridge | **trapped mid-span**, both ends choking, water below |
| tunnel | **the tunnel goes dark** — traffic stops, then the lights, then the engines |
| *(on a bus)* | packed transit, stopped dead | *(on foot/bike)* faster than the jam |

**Crashes from above.** Aircraft don't care what you drive. Anyone caught
*outdoors* (commuting or on an errand) can, with probability `aerial_prob`, be
struck instead by a **crash from above** — a light aircraft clipping the
rooftops, a helicopter spiralling into the street, an airliner coming down across
the blocks (`default_aerial_events`, `kind="aerial"`). The other side of it —
being *aboard* — is an occupation **signature**: the catalog includes **pilot**
(aloft with nowhere to land), **flight_attendant** (a cabin at 35,000 ft),
**helicopter_pilot** (over the city when the radio dies) and
**air_traffic_controller** (watching every blip on the scope go dark). So a jet
falling out of the sky is the same event seen from two ends — the crew's
signature and the pedestrian's hazard.

```bash
# Catch the morning commute (≈07:42) so traffic events fire by road structure
python -m asphodel.citizen --world --city capital --n 14 --collapse-hour 7.7
#   [▲ TRAFFIC ] postal_worker: Motorway folds up   (on the motorway, mid-commute)
#   [★ SIGNATURE] nurse: The doors won't stop opening   (on shift, at the hospital)
#   [▲ TRAFFIC ] commuter on the bridge: Trapped mid-span ...
```

#### Environmental events (`asphodel/environments.py`)

The three families above all answer "where are you and how are you moving". The
unifying layer is the **environment** — the *place* you're standing — and it can
produce its own hazards regardless of your job: fire, structural collapse, power
loss, gas, a crowd crush, and place-specific disasters keyed to an environment
taxonomy (residential, high-rise, retail, medical, education, civic, industrial,
transit-hub, street, **waterfront**, **underground**):

| Environment | Sample events |
|---|---|
| high-rise | trapped above the fire; the curtain wall lets go |
| medical | the oxygen system fails; the ward goes dark |
| industrial | a tank ruptures; the line won't stop; the racking comes down |
| waterfront | the surge comes over the wall; fuel ablaze on the water |
| underground | the tunnel floods; smoke fills the dark |
| street | a facade comes down; a car ploughs the crowd; a riot sweeps through |
| residential | the neighbours turn; the fire jumps the gap |

`resolve_collapse_situation(..., ambient_prob=0.12)` rolls this layer over the
base outcome: *usually* your job (signature) or the road defines the moment, but
sometimes the **building or street itself goes**, whatever your role — so an
on-shift nurse might face her ward flooding with casualties (signature) or the
hospital's oxygen system failing (environment). Every situation reports its
`environment`; adding a new environment or event is one entry in
`default_environment_events()`.

#### One taxonomy, five outcomes

`CollapseSituation` unifies all of it: `kind` ∈ {`signature`, `travel`,
`aerial`, `environment`, `generic`}, `context` (workplace / commute / errand /
home), the `environment`, the road `structure`, and reusable `tags` a game layer
switches on (`height`, `trapped`, `fire`, `flood`, `hazmat`, `structural`,
`tunnel`, `bridge`, `crowd`, `children`, `keys_access`, …). The hazard layers
(`aerial_prob`, `ambient_prob`) stack over the base and each disable to 0;
resolution is deterministic in `(citizen, collapse_hour, world)`.

```bash
python -m asphodel.citizen --world --city harbor --n 12 --collapse-hour 7.7
#   [★ SIGNATURE] nurse: The doors won't stop opening
#   [▲ TRAFFIC ] office_worker: Trapped mid-span        (on a bridge)
#   [✦ HAZARD   ] dock_worker: A tank ruptures           (waterfront)
#   [✈ CRASH    ] student: A helicopter comes down       (caught outdoors)
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

---

## OSM City Pipeline (Phase 1)

Turn a real city into an Asphodel **bundle** — a zone graph + density-weighted
population + major roads + a precomputed belief-cascade timeline — that the
Godot frontend (in [`godot/`](godot/)) renders as a low-poly "block city" whose
zones tint toward panic on playback. The city is divided into a square grid of
zones; each cell's population comes from the real OSM building density inside
it. The belief-cascade sim then runs on that geography **over a road-derived
zone-mobility graph**: two zones exchange infection/belief in proportion to the
real roads that cross between them (a `mobility.json` edge list persisted in the
bundle), not by mere grid adjacency — so a city's highways, rivers and
chokepoints shape the outbreak. Cities with no roads fall back to grid mobility.
See [`FINDINGS_ROAD_MOBILITY.md`](FINDINGS_ROAD_MOBILITY.md).

```bash
# Geocode a city, fetch OSM, run the sim, write a bundle
python -m asphodel.osm_city "Chicago" --out output/chicago --cache output/osm_cache

# Knobs: grid resolution, total population, sim horizon, RNG seed
python -m asphodel.osm_city "Boston" --out output/boston --grid 20 --total-pop 650000 --days 90
```

The pipeline is hybrid by design: Godot invokes this module as a subprocess and
then loads the bundle it writes. The bundle is JSON files — `meta.json`,
`zones.json`, `roads.json`, `timeline.json`, `mobility.json` (the road-derived
zone graph), and `citizens.json` — fully specified in
[`docs/superpowers/specs/2026-06-01-osm-city-scene-design.md`](docs/superpowers/specs/2026-06-01-osm-city-scene-design.md).
Network responses are cached by bbox (`--cache`), so re-runs are offline and
every bundle is byte-deterministic from `(city, grid, total-pop, seed)`.

```
asphodel/osm_city/
  geocode.py      # city name -> bbox (Nominatim), oversized-bbox capping
  overpass.py     # bbox -> major roads + building footprints (Overpass), cached
  tessellate.py   # bbox -> square grid; building footprint area -> per-zone population
  geometry.py     # equirectangular projection, polygon area, block/road layout
  mobility.py     # roads -> generic weighted zone-mobility graph (edge list)
  world_from_osm.py # roads+buildings -> canonical StreetMap for citizen spawn
  citizens.py     # bake a real-city spawnable citizen population
  bundle.py       # deterministic meta/zones/roads/timeline/mobility JSON writer
  pipeline.py     # build_bundle: tessellate -> roads -> mobility -> sim -> write
  __main__.py     # the CLI
```

```bash
python -m pytest tests/test_osm_city.py -q   # offline: inline fixtures, no network
```

> **Note:** real geography yields empty cells (water, parks, rural edges) with
> zero population. The macro sim gives such zones no population-driven burden (no
> infection, no observation- or infrastructure-driven belief) so the baked belief
> timeline stays finite — see the per-zone-population hook in
> [`asphodel/model.py`](asphodel/model.py). (They still participate in social
> contagion; that's a deferred modelling question, and since empty cells render
> no blocks it has no visual effect.)

On **Load City** the game picks a random pre-baked citizen (from the bundle's
`citizens.json`, spawned across the generic/capital/harbor/university profile
archetypes via `asphodel/osm_city/citizens.py`) and shows an ARK-style character
screen — name, age, occupation, the occupation's signature predicament, and
inventory — before entering the city.

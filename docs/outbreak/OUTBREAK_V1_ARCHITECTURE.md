# ASPHODEL_OUTBREAK_V1 — Architecture: the outbreak on persistent citizens

The outbreak is not a curve. It is a set of things that happen to identifiable
people in identifiable places, executed by the same authorities that run the
ordinary city (`docs/mobility/EMBODIED_MOBILITY_ARCHITECTURE.md`). This
document is the reference for what became canonical; the certification is
`OUTBREAK_V1_REPORT.md`; the donor-branch audit is `OUTBREAK_DONOR_AUDIT.md`.

## 0. The chain

```
health/world event ──► goal/constraint ──► CitizenRuntime replans ──► TripExecutor executes
      ▲                                                                   │
      │  HealthRecord (asphodel/outbreak/health.py) is THE health state    │ position, building_id,
      │  OutbreakRuntime (asphodel/outbreak/runtime.py) applies it          │ vehicle_id, override
      └──────────── contact from real co-presence ◄──────────────────────┘
```

| concern | authority | file |
|---|---|---|
| citizen identity | unchanged: `citizen_id` = citizens.json index | — |
| health state | `HealthRecord` per registered citizen, inside `OutbreakRuntime` | `asphodel/outbreak/health.py` |
| pathogen grammar | `OutbreakPathogen` archetypes (data) | `asphodel/outbreak/pathogen.py` |
| contact / exposure | `OutbreakRuntime._contacts` over `TripExecutor` situations (building, vehicle, outdoor proximity) + `_attack` (bite) | `asphodel/outbreak/runtime.py` |
| progression | timestamps decided at infection, applied by `_progress` on the movement clock | `health.py`, `runtime.py` |
| behaviour | goals pushed into the existing `CitizenRuntime` (`health`, `disruption`, `emergency` sources); no outbreak movement controller | `runtime.py` → `asphodel/citizens/runtime.py` |
| physical situation of the sick/dead/undead | `TripExecutor.override` (incapacitated / corpse / undead) holding position, building_id, vehicle_id | `asphodel/embodied/executor.py` |
| civil breakdown | `VehicleInstance.to_wreck` → `MobilityObstruction` on the street graph; `WORKPLACE_DISRUPTED` → workers' goals | `runtime.py` → `asphodel/transport`, `asphodel/mobility` |
| time | `World.advance_seconds` (mobility, then outbreak, 1 s substeps) | `asphodel/orchestrator.py` |
| persistence | save v3 `outbreak` block; restored by `World.enable_outbreak()` after mobility | `asphodel/save.py` |
| bridge | protocol v5: `START_WORLD.outbreak`, `SEED_OUTBREAK`, `GET_OUTBREAK`; mobility rows carry `health` | `asphodel/bridge/{protocol,session}.py` |
| embodiment | `EmbodiedMobility` looks: undead / corpse / sick; a corpse on the street is a solid body | `godot/scripts/embodied_mobility.gd` |
| FAR statistical tier | unchanged macro SEIR (`asphodel/model.py`, `PathogenGenome`) for the unregistered population; not coupled to the individual outbreak in V1 | — |

Nothing in Godot decides health, contact, death or reanimation; nothing in
the outbreak sets a position.

## 1. Population

The individual outbreak needs identifiable people who share context. The
canonical Houston population was grown from 60 to 300 citizens with the
existing bake (`osm_city.citizens.build_population_from_compiled`, seed 0):
the bake is deterministic and prefix-stable, so citizens 0–59 are
byte-identical to before (the mobility certification citizen 4 is unchanged)
and 240 new citizens have real homes and workplaces from the compiled world.
This yields 34 shared workplaces (largest: building 2318 with 6 day-shift
workers) and 5 shared homes. The 60-citizen bundles (Madisonville, Austin,
San Antonio) keep their sparse contact structure and report it honestly.

## 2. Health state (`HealthRecord`)

```
susceptible ─exposure(roll)─► incubating ─symptom_t─► symptomatic ─incapacitation_t─► incapacitated
                                   │ (asymptomatic)                     │ (non-fatal)        │ death_t
                                   └──► recovered ◄──────────────────────┘                    ▼
                                                                                    corpse ─reanimate_t─► undead
                                                                                    dead (will_reanimate False)
```

Persisted per citizen: pathogen name, source citizen, exposure context
(`building:<bid>` | `vehicle:<vid>` | `proximity` | `bite` | `index_case`),
exposure location, exposure/infection time, infectious_from_t, symptom_t,
incapacitation_t, death_t, recovery_t, fatal, asymptomatic, will_reanimate,
reanimate_t, corpse_xy/building/vehicle, undead_since_t, attacks, bitten_by,
lineage (source chain back to the index case), exposures_resisted.

**Determinism.** Every outcome is a pure draw `roll(world_seed, citizen_id,
purpose[, extra])` = splitmix64 `hash64` folded to [0,1). Timestamps are
computed once in `HealthRecord.infect` and stored; the runtime only compares
the clock against them. Contact rolls are keyed by `(victim, source,
minute-bucket)`, bites by `(victim, undead, attack index)`. A save/load or a
LOD change cannot re-roll anything because nothing is rolled later.

## 3. Pathogen grammar (`OutbreakPathogen`)

Fields: transmission route label; hazard rates per hour per infectious
contact for building co-occupancy, shared vehicle and outdoor proximity
(radius); pre-symptomatic infectiousness factor and window; bite probability;
undead infectiousness weight; incubation / symptomatic / incapacitated
durations with per-citizen jitter; asymptomatic and mortality fractions;
recovery time; reanimation fraction, delay and `turn_on_death`; undead speed,
sense radius, attack reach and cooldown; workplace disruption fraction.

Archetypes: `classic_zombie` (V1 certification: incubation 4 h ± 40 %,
2 h pre-symptomatic at 0.6, collapse 6 min after onset, death 30 min after
collapse, 95 % fatal, 90 % rise after 20 min, bite 0.85, shambler 0.9 m/s,
sense 60 m), `classic_shambler` (the donor's numbers in days),
`rage_virus`, `cordyceps`, `necro_latent` (turn_on_death). Only
`classic_zombie` is certified; the others build and run (smoke).

## 4. Contact model

Every game minute, for each infectious source (`infectious_weight` > 0) and
each susceptible registered citizen: co-occupancy of the same building
(`TripExecutor.inside and building_id` equal), the same vehicle
(`vehicle_id` equal), or outdoor proximity within `proximity_radius_m` when
neither is inside or in a car. Exposure probability over the minute is
`1 - exp(-rate × weight × 1/60 h)`; the roll is deterministic. An undead in
attack reach (or in the same building as its target) attacks every
`attack_cooldown_s`; a bite exposes with `bite_probability` if the victim is
susceptible. There is no second geography: the building ids are the compiled
building ids the executor entered, the vehicle ids are the persistent
VehicleInstances, positions are executor positions.

## 5. Progression → behaviour

* **SYMPTOM_ONSET** → `PLAN_INVALIDATED` (+ `TRIP_ABORTED` if a step was in
  progress): a `DO_ACTIVITY(rest)` goal at the home node with source
  `health` (priority 0.80, above every schedule goal) is pushed; the planner
  replans from the reported physical situation (inside work / in the car…)
  and the executor executes it. Schedule syncs cannot drop it
  (`_reissue_constraints`).
* **INCAPACITATED** → executor override `incapacitated`: the body holds where
  it is (inside a building, on the street, in the car). If the citizen was
  DRIVING, the car is abandoned (see §7).
* **DEATH** → `corpse` override; `corpse_xy/building/vehicle` recorded;
  `CORPSE_CREATED`. `will_reanimate` decides CORPSE vs DEAD.
* **REANIMATION** → `undead` override on the SAME executor and record
  (`original_citizen_id` = citizen_id; lineage kept): it leaves the car it
  died in (beside it), can no longer drive, and its `CitizenRuntime` receives
  the undead policy: **HUNT** (a `RETRIEVE` goal at the nearest living
  citizen's node within `undead_sense_m` outdoors or in the same building;
  prey are the living who are not already carrying the pathogen, so a bitten
  victim is not bitten again every cooldown; the planner routes, the
  executor walks at `undead_speed`, buildings are entered and left through
  their entrances: an undead that rose inside a building is still inside it)
  or **ROAM** (alternate between its home and its errand building when
  nothing is in range; a roam leg is a route query and is re-planned at most
  once per minute, the last roam time is saved with the world). **ATTACK** within
  reach → bite roll → `EXPOSURE(bite)`; the victim always **FLEEs**.
* **Fear** (`_witnesses`, every 5 s): a living citizen in the same building
  as an undead/corpse or within 25 m outdoors of an undead or an attack gets
  `THREAT_OBSERVED` and a `FLEE` goal (source `emergency`, 0.92) to home, or,
  when the threat is at its home (inside it or at its door), to the nearest
  other place it knows (work, errand) or a deterministic nearby refuge
  building chosen by the mobility runtime's errand picker; never the
  building under attack.

Planning stays with `CitizenRuntime`; movement stays with `TripExecutor`.

## 6. Death location and corpse identity

A corpse is not a global dead list entry: it is the same `TripExecutor` in
override `corpse` at its death pose with its `building_id` and `vehicle_id`,
plus `HealthRecord.corpse_*`. `World.physical_location` and
`building_occupants` therefore still resolve it (a corpse at work is an
occupant of that building; a corpse in a car is at the car). The mobility
snapshot row carries `health` so the client embodies it (a street corpse is
a solid lying body; an in-building or in-car corpse has no separate body).

## 7. Civil breakdown (feedback into the city)

* **Vehicle abandonment.** An incapacitated driver's `VehicleInstance`
  becomes `PERSISTENT_WRECK` at its position (`to_wreck`); the wreck's
  `MobilityObstruction` closes its street segment to `CAR`/`HEAVY`
  (`modes_affected`) and is applied to the one street graph, so every later
  route query avoids it and any car already heading there sees
  `road_closed_ahead`, waits, then replans (`VEHICLE_ABANDONED`,
  `ROAD_OBSTRUCTED`). Pedestrians pass. The wreck is a solid `VehicleBody`
  when NEAR.
* **Workplace disruption.** When an undead, a corpse or an incapacitated
  person is inside a workplace, or at least `workplace_disruption_fraction`
  of its registered workers are incapacitated/dead/undead, the building is
  `WORKPLACE_DISRUPTED`; every alive worker whose active schedule goal is
  that building gets a `disruption` goal home (0.78) and replans; the
  disruption persists (re-issued at every schedule sync).

Both are authoritative Python state saved with the world.

## 8. LOD

The outbreak runs on the movement clock for every registered citizen
regardless of LOD band (FAR/MID/NEAR are execution fidelity, never health
authority). Promotion creates a Godot body at the executor pose with the
health look; demotion frees it; the `HealthRecord` is untouched by either.
The undead's route-simulated walking continues with no body.

## 9. Persistence

`save.world_state` adds `outbreak` (pathogen, records, events, event_seq,
disruptions, obstruction ids, hunt/roam/cooldown/witness state, clocks).
`load_world` parks it; `World.enable_outbreak()` after `enable_mobility`
restores it and re-applies executor overrides; graph obstructions come back
through the mobility block. No index case is re-seeded on load.

## 10. Bridge and Godot

Protocol v5: `START_WORLD` accepts `outbreak: {pathogen, citizen_id,
seed_index_case}`; `SEED_OUTBREAK` enables/seeds at runtime; `GET_OUTBREAK
{since_seq}` returns counts, health rows, disruptions, obstructions and
events; summaries carry `outbreak_enabled`; mobility rows carry `health` and
`override`. `EmbodiedMobility` embodies the NEAR band: living bodies as
before, `undead` bodies with a grey-green tint in follow mode (the executor
walks them), street corpses/incapacitated as lying solid bodies, symptomatic
citizens pale. Godot never simulates the outbreak.

## 11. Extension points (for Smart Objects / work execution)

`OutbreakRuntime` reads only `TripExecutor` situation fields
(`inside`, `building_id`, `vehicle_id`, `pos`, `override`) and pushes goals
by source name; a future activity/work system can add richer co-presence
(rooms, stations) and richer reactions by adding goal sources and executor
situation fields without touching the health state machine.

## 12. Known limits (V1)

* Contact rooms are whole buildings (no room-level co-presence).
* Witness reactions are one FLEE goal; no avoidance of danger areas in
  routing, no memory beyond "threat seen".
* Undead do not open a fight; attacks are contact events with a bite roll,
  no injury model for the living beyond exposure.
* A wreck closes its whole segment; there is no partial-lane blockage.
* The macro SEIR tier and the individual outbreak are not coupled.
* Bystander `THREAT_OBSERVED` events depend on co-presence and did not occur
  in the certification day (the attacked citizens' FLEE reactions did).

# ASPHODEL_OUTBREAK_V1 — Report: embodied outbreak and civil breakdown

**Verdict: `ASPHODEL_OUTBREAK_V1: PASS`** (all 22 gates PASS; see §4 and the
remaining-debt list in §17 before reading anything into "PASS" beyond what the
gates measure).

## 1. Provenance

| item | value |
|---|---|
| base (spine) | `18e32d5e7fc5cae05f21be9c46a9cd435a3912da` — `ASPHODEL_EMBODIED_MOBILITY_V1: PASS` |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` (this milestone continues on the mobility branch) |
| final SHA | `FINAL_SHA_PLACEHOLDER` |
| commits since base | 26 (46 files, +33.5 k lines, of which ~30 k are the Houston population bake, traces and artifacts) |
| donor branch | `claude/outbreak-config-types-A8fTw` @ `bc34bfe` — audited (`OUTBREAK_DONOR_AUDIT.md`), never merged, never branched from |
| certification city | Houston (`godot/bundles/houston`, 300 citizens, 297 registered) |
| pathogen certified | `classic_zombie` (`asphodel/outbreak/pathogen.py`) |
| tooling | CPython 3.11.15, Godot 4.4 stable headless + xvfb/Mesa (software GL), 4-core container |

Artifacts: `artifacts/outbreak_v1/{one_day_trace,save_load_trace,godot_probe_trace,city_smoke,performance,regression}.json`.
Evidence: `docs/outbreak/evidence/` (§16). Architecture: `OUTBREAK_V1_ARCHITECTURE.md`.

## 2. Architecture (what became canonical)

The outbreak is a set of per-citizen facts applied by the authorities that
already run the city. Nothing new decides positions; nothing in Godot decides
health.

```
HealthRecord (health.py) ── OutbreakRuntime (runtime.py, on World.advance_seconds) ──► goal/constraint
        ▲                                                                                   │
        │ contact from real co-presence: TripExecutor.inside/building_id/vehicle_id/pos      ▼
        └──────────────────────────────────────────────── CitizenRuntime replans ──► TripExecutor executes
```

* **`asphodel/outbreak/health.py`** — `HealthState` (susceptible, exposed,
  incubating, symptomatic, incapacitated, recovered, dead, corpse, undead),
  `HealthRecord` with every timestamp decided once at infection from
  `roll(world_seed, citizen_id, purpose[, extra])` (splitmix64), lineage, corpse
  location, bite bookkeeping.
* **`asphodel/outbreak/pathogen.py`** — `OutbreakPathogen` grammar (transmission
  rates per context, presymptomatic window, incubation/symptomatic/incapacitated
  durations with jitter, asymptomatic/mortality/reanimation fractions,
  reanimation delay, `turn_on_death`, undead speed/sense/reach/cooldown,
  workplace disruption fraction); archetypes `classic_zombie` (certified),
  `classic_shambler` (donor values, days), `rage_virus`, `cordyceps`,
  `necro_latent` (build and run only).
* **`asphodel/outbreak/runtime.py`** — contacts every game minute (building
  co-occupancy, shared vehicle, outdoor proximity), progression every 1 s
  substep, undead hunt/roam/attack every 5 s, witnesses every 5 s, disruption
  scan on every health transition. Behaviour is expressed only as goals pushed
  into the existing `CitizenRuntime` (`health` 0.80, `disruption` 0.78,
  `emergency` FLEE 0.92, undead RETRIEVE 0.95 / roam 0.5); the existing
  `TripExecutor` executes them. There is no outbreak movement controller.
* **`asphodel/embodied/executor.py`** — three health overrides
  (`incapacitated`, `corpse`, `undead`) that hold the physical situation; the
  undead walks on the same executor at `undead_speed`.
* **civil breakdown** — `VehicleInstance.to_wreck` + `MobilityObstruction`
  closing the segment to CAR/HEAVY on the one street graph; `WORKPLACE_DISRUPTED`
  re-goals every registered worker of that building.
* **persistence** — save v3 `outbreak` block (records, events, disruptions,
  obstruction ids, hunt/roam/cooldown/witness state); restored after mobility
  by `World.enable_outbreak()`.
* **bridge v5** — `START_WORLD.outbreak`/`start_hour`, `SEED_OUTBREAK`,
  `GET_OUTBREAK`, summary `outbreak_enabled`, mobility rows carry `health` and
  `override`.
* **Godot** — `EmbodiedMobility` realises undead (grey-green, walking under
  physics in follow mode), street corpses/incapacitated (solid lying body),
  symptomatic (pale); it now also materializes bodies at a free spot and
  re-materializes a body that stays stuck (§17, absorbed mobility debt).
* **FAR statistical tier** — the macro SEIR (`asphodel/model.py`,
  `PathogenGenome`) is untouched and not coupled to the individual outbreak.

The one population change: the canonical Houston bundle grew from 60 to 300
citizens through the existing deterministic, prefix-stable bake
(`osm_city.citizens.build_population_from_compiled`, seed 0). Citizens 0–59 are
byte-identical to before; the mobility certification citizen 4 is unchanged.
With 60 citizens no two people ever shared a building, so there was nothing an
individual outbreak could do.

## 3. Old outbreak branch (`claude/outbreak-config-types-A8fTw`)

Full audit: `OUTBREAK_DONOR_AUDIT.md` (concept-by-concept disposition table).
Summary of what happened to it:

| donor concept | disposition | where it landed |
|---|---|---|
| archetype names and parameter values (classic shambler, rage, cordyceps, necro-latent) | **reused (values)** | `pathogen.py` archetypes; `classic_shambler` keeps the donor's day-scale numbers verbatim |
| `reanimation_fraction`, `reanimation_delay`, `turn_on_death`, `undead_infectious` fields | **reused (shape)** | fields of `OutbreakPathogen`; the audit recommended adding them to the macro `PathogenGenome` too — **not done** in V1 (the macro tier is untouched; recorded as debt §17) |
| `transmission_route` label | **reused** | label on `OutbreakPathogen`; mixing multipliers on the zone graph **rejected** for the individual tier |
| macro `U` / `C` compartments, `1/delay` exponential corpse drain | **rejected / rewritten** | per-citizen `reanimate_t` stamped at death; no aggregate compartment is authority |
| donor `model.py` / `run.py` / belief hunks | **rejected** | ~126 commits stale; ideas re-expressed against current code only where needed (none needed for V1) |
| donor state vocabulary (no incubating/incapacitated, dead ≡ corpse) | **rejected** | the eight-state per-citizen enum |
| donor test ideas (defaulted-off invariance, no re-roll on load, archetype round-trips) | **re-expressed** | `tests/test_outbreak_health.py`, `tests/test_outbreak_saveload.py` |
| anything modelling contact between two named people | **absent in the donor** — written from scratch | `runtime.py::_contacts/_attack` |

No file was merged from the donor; no second citizen or world authority was
introduced.

## 4. Certification table (`tests/test_outbreak_v1_day.py`, Houston, 05:00→18:00)

```
OUTBREAK_V1_CERTIFICATION
  O1   PASS     Individual index citizen exists: citizen 42 (home 6353, work 2318) seeded at 05:00 as the index case; symptom_t/incapacitation_t/death_t/reanimate_t fixed at infection
  O2   PASS     Exposure tied to real citizens: 9 onward exposures between registered citizens: [(247, 42, 'building:2318', 8.28), (117, 247, 'building:2318', 9.77), (170, 247, 'building:2318', 10.18), (127, 42, 'bite', 10.82), (294, 42, 'bite', 11.12), (87, 117, 'building:2318', 13.77)]
  O3   PASS     Exposure tied to real building/proximity/vehicle context: contexts ['bite', 'building']: building co-occupancy from executor building_id, bites from undead attacks
  O4   PASS     Infection progression deterministic: fresh world reproduces the index record and the first 3 h of events (2 events) exactly; timestamps rolled once via hash64(seed, cid, purpose)
  O5   PASS     Symptoms affect citizen planning: SYMPTOM_ONSET at 9.90 h in building 2318 -> 'health' goal go_home replaced the schedule (PLAN_INVALIDATED)
  O6   PASS     Existing mobility executes replanned behaviour: TripExecutor executed the replanned trip: ['on_foot'] (embodiment states after onset, same executor; left building 2318 at 10.08 h)
  O7   PASS     Death occurs at authoritative location: DEATH at 10.37 h in vehicle veh:42 on the street at (-1280.1,-1325.7), exactly where the citizen collapsed (corpse)
  O8   PASS     Corpse persists: corpse held by the executor override for 21 sampled minutes; HealthRecord.corpse_xy/building/vehicle persisted
  O9   PASS     Reanimation preserves identity: citizen 42 reanimated at 10.60 h at its death location as the same executor/record (jump 0 m); other reanimations keep lineage: {117: [42, 247], 127: [42], 170: [42, 247], 87: [42, 247, 117]}
  O10  PASS     Undead embodied in Godot: CitizenBody for cit:42 with the undead look, 244 frames
  O11  PASS     Living citizen reacts to nearby undead: citizen 127 FLEEs (emergency goal, target ent:9578) after undead 42 attacked it in building 6255; 1 bystander THREAT_OBSERVED events
  O12  PASS     Undead can cause new exposure/contact: 5 bite exposures: [(127, 42), (294, 42), (191, 117), (188, 127), (2, 87)]; bitten citizens progress like any infected citizen
  O13  PASS     City-system disruption feeds back into simulation: WORKPLACE_DISRUPTED [(6255, '1 incapacitated/dead/undead inside'), (2318, '3/6 workers down'), (4075, '1 incapacitated/dead/undead inside'), (8289, '1/1 workers down')] -> 5 workers replanned home; VEHICLE_ABANDONED veh:42 at 9.98 h -> segment bf368bb4 closed to cars (MobilityObstruction wreck:veh:42), wreck fidelity persistent
  O14  PASS     FAR progression works: with the focus 9 km away (no PHYSICAL band all day) the index case progressed incubating -> symptomatic -> incapacitated -> corpse -> undead
  O15  PASS     LOD promotion preserves state/location/identity: promotion to PHYSICAL kept the HealthRecord byte-identical and the position continuous (moved 0.90 m in 1 s); in-engine: PASS body recreated at the authoritative pose (jump 0.00 m)
  O16  PASS     Save/load during incubation: incubation save at 6.52 h: record/events/override/position identical, 10-min continuation byte-identical, no re-seed
  O17  PASS     Save/load corpse/reanimation: corpse save at 10.38 h and undead save at 10.60 h: identical restore, byte-identical continuation
  O18  PASS     Save/load civil-disruption state: save with active disruption at 10.83 h: disrupted buildings, obstructions and continuation identical
  O19  PASS     Headless and in-engine semantic parity: in-engine run reproduced the index case's biological events [('SYMPTOM_ONSET', 42.0), ('INCAPACITATED', 42.0), ('DEATH', 42.0), ('REANIMATION', 42.0)] at identical timestamps: True
  O20  PASS     Existing mobility regression suite green: 906 collected: 904 passed; 1 pre-existing environment failure (raw Overture parquet, identical on origin/main); 1 stale v4 pin fixed and re-verified (11 passed)
  O21  PASS     Existing canonical Godot gates green: existing headless gates (godot/tests/run_gates.sh: PhysicsGate, RegionGate, NavGate, ConvergenceGate): 85 PASS / 0 FAIL; ExteriorStream gate 0 failures; MobilityGate PASS; OutbreakGate 18/18 PASS (artifacts/outbreak_v1/godot_probe_trace.json)
  O22  PASS     Reduced multi-city smoke has no city-name special casing: houston: PASS; madisonville_tx: PASS; austin: INFO; san_antonio: PASS; boulder: INFO
.
17 passed in 208.30s (0:03:28)
```

The row texts are the test's own output (`artifacts/outbreak_v1/one_day_trace.json`
carries the events and gate details).

## 5. One-day trace (deterministic; index case citizen 42, home 6353, work 2318)

Headless (focus 9 km away, so no citizen ever had a Godot body: FAR progression):

| game time | event | detail |
|---|---|---|
| 05:00 | EXPOSURE/INFECTED 42 | index case seeded at home 6353; all timestamps fixed now |
| 08:17 | EXPOSURE 247 ← 42 | building 2318 co-occupancy (42 presymptomatic, factor 0.6) |
| 09:46 | EXPOSURE 117 ← 247 | building 2318 |
| 09:53 | SYMPTOM_ONSET 42 → PLAN_INVALIDATED | at work; `health` goal "going home" replaces the schedule; 42 walks (kerb-side) to its car and drives |
| 09:58 | INCAPACITATED 42 at the wheel → VEHICLE_ABANDONED veh:42 → ROAD_OBSTRUCTED | segment `bf368bb4…#1` closed to cars (persistent wreck) |
| 10:11 | EXPOSURE 170 ← 247 | building 2318 |
| 10:22 | DEATH 42 → CORPSE_CREATED | in veh:42 on the street at (-1269.4, -1334.7), exactly the collapse position |
| 10:35 | REANIMATION 42 | same executor, same record, same place; leaves the car; roams home ↔ errand |
| 10:49 | ATTACK 42 → 127 (bite) → EXPOSURE 127 → FLEE 127; **WORKPLACE_DISRUPTED 6255** | the undead is inside 6255 (127's workplace); 127 flees to its home ent:9578 |
| 11:07 | ATTACK 42 → 294 (bite) → FLEE 294 | in building 6366; second victim |
| 11:04–11:35 | 247 symptomatic → incapacitated → DEATH in 7630 | 247 does not reanimate (its `will_reanimate` roll) |
| 13:46 | EXPOSURE 87 ← 117 | building 2318 |
| 14:13–14:20 | 117 symptomatic → INCAPACITATED at 7928; **WORKPLACE_DISRUPTED 2318** (3/6 down) | 87, 135, 170 replanned home (PLAN_INVALIDATED) |
| 14:46–15:01 | DEATH 117 → REANIMATION 117 | |
| 15:26 | 127 incapacitated at 9578 | |
| 15:38 | ATTACK 117 → 191 (bite) → FLEE 191; WORKPLACE_DISRUPTED 4075 | building 4075 |
| 16:00–16:43 | deaths and reanimations of 127, 170; ATTACK 127 → 188 (bite) in 9091; WORKPLACE_DISRUPTED 8289; death of 294 | |
| 17:05–18:28 | 87 symptomatic → dead → undead; ATTACK 87 → 2 (bite) in 16469 | |

End of day (05:00→18:45): 9 onward exposures (4 building co-occupancy,
5 bites), 7 deaths, 5 reanimations, 5 attacks, 5 FLEEs (all attack victims),
4 disrupted workplaces, 1 obstruction. **No bystander THREAT_OBSERVED occurred
in this headless day** (it did in the in-engine gate: four co-workers in 2318
saw the first attack and fled; and in an earlier headless run a passer-by saw
an undead in the street). The witness path is real but its occurrence is
contingent on co-presence.

In-engine (OutbreakGate, live bridge, real physics, the player following 42)
the *same seed* produced the same biological timeline for 42 (onset 09:53,
collapse 09:58, death 10:22, reanimation 10:35 — identical timestamps, O19)
but a different physical day: 42 reached its car and collapsed at the wheel at
(-548.7, -1909.5) (the headless run collapsed at (-1269.4, -1334.7)), because
Godot physics held the walk to the car differently. That is the expected
relation: health is authoritative and identical; position is authoritative but
physics-reconciled.

## 6. Infection

* **Individual, not aggregate**: `HealthRecord` per registered citizen; the
  macro SEIR never touches it.
* **Contact is real co-presence**: building co-occupancy uses the compiled
  building id the executor entered; shared-vehicle uses the persistent
  `VehicleInstance` id; proximity uses executor positions (2.5 m, outdoors, both
  on foot). Bites are undead attacks in reach or in the same building. No
  second geography exists.
* **Deterministic**: contact rolls are keyed by (victim, source, minute bucket),
  bites by (victim, undead, attack index), every progression timestamp by
  (seed, citizen, purpose) — rolled once, stored, compared to the clock. Save/
  load and LOD changes cannot re-roll anything (O4, O16–O18).
* **Presymptomatic transmission** is what makes a one-day chain possible with
  a 4 h incubation: 42 exposed 247 at 08:17, 1 h 37 min before its own onset.
* What did **not** occur in the certification day: a shared-vehicle exposure
  (no two registered citizens share a car) and an outdoor-proximity exposure
  (the sources were indoors when near others). Both paths are unit-tested
  (`tests/test_outbreak_contacts.py`) but not exhibited by the day trace.

## 7. Behavioural disruption

`SYMPTOM_ONSET → PLAN_INVALIDATED → health goal → CitizenRuntime replans →
TripExecutor executes` is exactly the chain in the trace (O5, O6): 42 left work
under its own executor (on foot, then its car). Workers of a disrupted
workplace get a `disruption` goal home and replan; the goal survives schedule
syncs (re-issued). Attack victims and witnesses get `emergency` FLEE goals; a
citizen whose home is the threatened place takes refuge in the nearest other
place it knows or a deterministic nearby building — never the building under
attack (fixed during certification: the first in-engine run had a victim
"flee" into the building it was attacked in).

## 8. Death and reanimation

Death happens where the executor is: in the car (headless day), on the street
(early in-engine runs), inside a building (247 at 7630). The corpse is the same
`TripExecutor` in `corpse` override with its `building_id`/`vehicle_id`, so
`World.physical_location` and building occupancy still resolve it (O7, O8).
Reanimation flips the override on the same executor and record; lineage is
kept; the undead leaves the car it died in and can no longer drive (O9). An
undead that rose inside a building is inside it and leaves through the entrance
(fixed during certification, §17).

## 9. Civil breakdown

* **Vehicle abandonment → obstruction**: 42 collapsed at the wheel; veh:42
  became a `PERSISTENT_WRECK` at that position; its `MobilityObstruction`
  closes the segment to CAR/HEAVY on the one graph (`traverse_cost(CAR)` is
  infinite, FOOT stays finite; `tests/test_outbreak_disruption.py`); cars
  already heading there see `road_closed_ahead`, wait, then replan. The wreck
  is a solid `VehicleBody` in Godot (gate `abandoned_car_is_persistent_wreck_body`).
* **Workplace failure**: 6255 was disrupted at 10:49 (an undead inside);
  2318 at 14:20 (3 of 6 registered workers down) — 87, 135, 170 were sent home
  and replanned; 4075 (undead inside) and 8289 (its only worker down) followed.
* Both are authoritative Python state and survive save/load (O18).

## 10. LOD

The outbreak runs on the movement clock for every registered citizen regardless
of band; bands only change execution fidelity. The headless day never had a
PHYSICAL band and progressed fully (O14); in-engine, demotion freed the undead
body, the undead kept walking (28 m authoritative movement with no body), and
promotion recreated the body at the authoritative pose with a 0.00 m jump and an
unchanged `HealthRecord` (O15). `max_active` was raised to 1024 so the
ABSTRACT overflow tier never freezes a registered citizen at 300 (that tier is
still tested in `tests/test_embodied_lod.py`).

## 11. Save/load

`artifacts/outbreak_v1/save_load_trace.json`: saves at incubation (06:31),
symptomatic/incapacitated (09:54), corpse (10:23), undead (10:36) and the
first active disruption (10:50, workplace 6255 with the undead inside); each restore is record/events/override/position identical
and the 10-minute continuation is **byte-identical** to the un-saved world; no
index case is re-seeded. The in-engine gate also saved/loaded an undead
mid-walk (`saveload_undead_identical`). Persisting the goal-stack sequence,
congestion/obstructions, and the last-roam time were all needed to reach
byte-identity.

## 12. Godot

`OutbreakGate` (19/19, `tools/run_outbreak_gate.sh`): world started with the
outbreak at 05:00; index case incubating at work with an ordinary morning;
onset → left the workplace under the executor with a body within the leash;
collapse at the authoritative place (this run: at the wheel, wreck body
present); corpse frozen; reanimation at the same place; undead body with the
undead look walked 25 m under physics within the leash for 100 % of frames;
demoted when the focus left, progressed while far (28 m with no body),
promoted back with a 0 m jump; attacked citizen 294 in building 6366; the
victim fled to ent:6189 and left the building on foot as a `CitizenBody`. In
this final run the collapse was at the wheel at (-541.4, -1916.7) and the
abandoned car was a persistent-wreck `VehicleBody`.
Godot never decided any of it: every transition is a bridge event.

## 13. Multi-city smoke (`tools/outbreak_city_smoke.py`, 05:00→17:00, 60 s steps)

| city | status | citizens | index | events | onward exposures | end health | disrupted | obstructions | determinism (3 h) | ms/game-min |
|---|---|---|---|---|---|---|---|---|---|---|
| houston | PASS | 297 | 42 @ 2318 | 121 | 8 (4 building, 4 bite) | 288 S / 3 incub / 2 dead / 4 undead | 4 | 1 (wreck) | identical | 147 |
| madisonville_tx | PASS | 53 | 11 @ 580 | 582 | 10 (2 building, 8 bite) | 42 S / 2 incub / 1 corpse / 1 dead / 7 undead | 5 | 0 | identical | 8 |
| austin | INFO | 60 | none | — | — | — | — | — | — | — |
| san_antonio | PASS | 60 | 20 @ 4111 | 39 | 2 (bite) | 57 S / 1 incub / 1 dead / 1 undead | 2 | 0 | identical | 36 |
| boulder | INFO | — | — | — | — | — | — | — | — | — |

Every PASS city completed symptom → incapacitation → death → reanimation for
its data-driven index case. Austin: no workplace has two day-shift workers
among its 60 citizens, so `choose_index_case` finds no data-driven index case
and the tool reports INFO rather than inventing one; Boulder has no compiled
world. There is no city-name special casing (`tests/test_outbreak_city_smoke.py`
runs the same code on each bundle; O22 checks the tool source).

## 14. Performance (`tools/outbreak_perf.py`, Houston 297 citizens, 4-core container)

| scenario | total ms / game-min | mobility | outbreak |
|---|---|---|---|
| off-peak 05:00, 1 incubating | 21.4 | 21.2 | 0.27 |
| commute peak 07:00–08:00, 1 incubating | 168.7 | 168.3 | 0.29 |
| infection-heavy 12:00, 20 seeded index cases, 19 undead, 40 infectious | 245.8 | 82.7 | 171.1 |
| mobility-only baseline 05:00 / 07:00 | 23.5 / 186.9 | | |

Contact scan: 0.45 / 1.5 / 6.0 ms per game minute for 1 / 5 / 20 infectious
sources (linear in sources × citizens). Progression: 3.0 ms per game minute at
69 records (60 substeps). Snapshot 0.1 ms (68 KB). Save+dumps 5 ms, load
3.4 ms (211 KB). FAR and NEAR focus cost the same (the outbreak does not depend
on the band). At 24× (2.5 s real per game minute) the heaviest measured minute
uses 9.8 % of the budget (10.2× headroom). Wall time of the whole measurement:
208 s.

The first measurement of the heavy scenario was **15.5 s** per game minute,
96 % in mobility: every undead re-planned a route every second (§17, fixed);
the numbers above are after the fix (a 63× reduction). These are single-machine numbers taken on a
shared 4-core container while other jobs ran; treat absolute values as ±20 %.

## 15. Regression (`artifacts/outbreak_v1/regression.json`)

* Python: 906 collected, 905 passed, 1 pre-existing environment failure
  (`test_world_from_compiled::test_compile_writes_only_presentation_files`
  needs raw Overture parquet; identical on `origin/main`). Two tests were
  updated for the milestone itself: the bundle population test now reads the
  bundle's citizen count instead of pinning 60, and the bridge test accepts a
  protocol version ≥ 4.
* Mobility day suites (`test_embodied_mobility_day.py`, `test_embodied_executor_day.py`): 25 passed, re-run after the executor changes.
* Outbreak package: 90 tests (health, contacts, progression/behaviour, save/
  load, LOD, bridge, disruption) + 12 smoke tests, all green.
* Godot: `godot/tests/run_gates.sh` 89 PASS / 0 FAIL after the embodiment
  changes; MobilityGate: MOBILITY_GATE_PLACEHOLDER.

## 16. Rendered evidence (`docs/outbreak/evidence/`)

Produced by `tools/run_outbreak_shots.sh houston 42 docs/outbreak/evidence`:
the real `IsometricWorld` scene under xvfb (software GL), live Python bridge,
world started by the scene, outbreak seeded through the bridge at 05:00, then
stepped at 0.1 game-second per physics frame through the moving stretches and
in 4 s chunks through the still ones. `manifest.json` carries the script's own
captions; the column "what the frame actually shows" is a review of the pixels
and is the caption that counts.

| file | script caption (authoritative rows) | what the frame actually shows |
|---|---|---|
| `00_infected_ordinary_morning.png` | incubating citizen 42 inside building 2318 (doing_activity) before onset | the flat roof of the workplace from above and the player marker; **no citizen is visible** (an interior has no body). Proves only that the camera is at the workplace while the authority says "incubating, inside". The HUD clock (`Day 1 10:41`) is the scene's paused clock, not the simulation hour. |
| `01_symptomatic_leaving_work.png` | symptomatic, schedule invalidated, heading home (on_foot) | **the same roof view as 00; no walking body is visible in the frame.** It does not show the citizen leaving; the leaving is evidenced by the gate's body frames (§12), not by this image. |
| `02_collapse.png` | incapacitated at (-274.4, -2164.9), building −1, vehicle veh:42 | a red car stopped in the middle of the carriageway among parked cars, i.e. the citizen's own car halted mid-street where the driver collapsed. The driver is inside the car, so no separate body. |
| `03_corpse.png` | corpse of citizen 42 at the same coordinates (same place as the collapse: true) | the same car in the same place; a corpse in a car has no separate body, so the frame is visually identical to 02. The equality of coordinates is from the rows, not from the pixels. |
| `04_reanimated_same_place.png` | citizen 42 reanimated at the same coordinates, same identity | a green-tinted figure (the undead look) standing beside the driver's door of that car: the undead has left the car it died in, at the death location. |
| `05_undead_walking.png` | undead body walking under physics, 13 m from the death location | the same green figure on the road about a car-length-and-a-half from the car, the car unchanged. Shows a body displaced from the death spot; the fact that physics moved it is from the gate's leash metric, not the pixels. |
| `06_abandoned_vehicle_obstruction.png` | abandoned veh:42: persistent wreck, segment closed to cars | the red car alone in the carriageway with the undead further up the road. The frame shows a car stopped in the road; that it is a wreck that closes the segment to cars is authoritative state (`MobilityObstruction`), not visible here. |
| `07_attack.png` | undead 42 attacks citizen 294 in building 6366 (exposed=true) | the roof of building 6366 and the player marker; **no bodies** (the attack happened inside). The image proves the camera was at 6366 when the ATTACK event fired; nothing more. |
| `08_victim_flees.png` | citizen 294 fleeing on foot after the attack (FLEE goal) | the corner of building 6366 at street level; **no fleeing body is clearly visible** in this frame. The flight is evidenced by the gate (`fleeing_citizen_embodied_on_foot`: a CitizenBody for 294 left 6366 on foot), not by this image. |

Net: frames 02–06 are genuine in-world evidence of the collapse at the wheel,
the car left in the road, the undead rising beside it and walking away; frames
00, 01, 07, 08 show only where the camera was (interiors have no bodies) and
must not be read as showing the captioned behaviour. A first rendered pass
(discarded) captioned an already-undead citizen as "incubating" because the
script added an absolute clock time to the current hour; the script now
computes onset from the movement clock and prefixes any caption whose
condition the window did not reach.

## 17. Remaining debt

Found and **fixed** during certification (each is a real defect the outbreak
exposed in the mobility tier; all are now covered by tests or gates):

1. An undead that died indoors had the outdoor idle pose, so the runtime
   thought it was outside; it never left, never attacked co-occupants and
   re-planned a roam every 5 s.
2. A bitten victim was re-bitten every cooldown (thousands of no-op ATTACK
   events; the 5000-event ring rolled over inside a morning). Prey now excludes
   the already infected; roam legs are rate-limited and the last roam time is
   persisted.
3. A hunt or flee issued mid-walk re-planned from the last node passed; the
   walk leg refused to start 8 m away; the failure policy replanned every
   second (one route query per second per undead: the 15.5 s/game-minute
   scenario). Walk legs now approach their start; identical re-plans keep the
   failure streak; failed trips hold.
4. The hunter's planner did not know the prey's building node.
5. A Godot body spawned at an entrance anchor sat inside the building hull and,
   because the authority's 3 m physics leash equalled the body's 3 m stuck
   leash, was never reported blocked: a permanent hold. Bodies now materialize
   at a free spot, count as stuck below the authority leash, and are
   re-materialized when they stay stuck.
6. A victim attacked at home "fled" home.
7. With 300 citizens a pedestrian walking the street centreline stood in a
   physical car's lane and the car crawled behind it (the mobility gate's
   drive failed on the certification population). Walking legs now run along
   the kerb, 4.5 m off the centreline on street segments; connectors and leg
   end points keep their true geometry. MobilityGate 24/24 again.

Still open (not graded as PASS by any gate; do not read the verdict as covering
them):

* **Contact rooms are whole buildings.** No room-level co-presence, no
  stations; a workplace of 6 is one room.
* **Shared-vehicle and outdoor-proximity exposure did not occur in the
  certification day** (unit-tested only).
* **Reactions are one FLEE goal.** No routing around danger, no memory beyond
  the threat set, no barricading, no group behaviour; witnesses only react to
  an undead/attack/corpse in their building or within 25 m outdoors.
* **Undead behaviour is hunt/roam/attack** with a bite roll; no injury model,
  no combat (out of scope), no doors (an undead enters any building through
  its entrance like anyone else).
* **A wreck closes its whole segment**; there is no partial-lane blockage and
  no towing/removal.
* **The macro SEIR and the individual outbreak are not coupled**; the donor's
  genome fields were not added to `PathogenGenome`.
* **`EmbodimentState.UNDEAD` is only the outdoor idle pose**; a walking undead
  reports `on_foot` with `override == "undead"` and `health == "undead"`; an
  undead indoors reports `inside_building`. Consumers must read `health`.
* **Austin has no data-driven index case** at 60 citizens; growing the other
  bundles the way Houston was grown is the obvious next step for smoke depth.
* **Performance headroom is 9.9× on one machine** with 19 undead; nothing has
  been measured at hundreds of undead, and the contact scan is O(sources ×
  citizens) per minute.
* The event ring (5000) can still roll over in a dense outbreak for a consumer
  that only polls `snapshot()` occasionally (the tools drain it every minute).

## 18. Next milestone recommendation

**Smart Objects and work/activity execution.** Every extension point this
milestone needed is a place where "the building" is too coarse: exposure wants
rooms and stations, disruption wants "the person who runs the till is dead",
flight wants "somewhere with a door", and the undead want something to be
attracted by. `OutbreakRuntime` reads only executor situation fields
(`inside`, `building_id`, `vehicle_id`, `pos`, `override`) and pushes goals by
source name; a Smart-Object layer can add richer co-presence and richer
reactions without touching the health state machine (architecture §11).

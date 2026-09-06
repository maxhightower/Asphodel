# ASPHODEL_EMBODIED_MOBILITY_V1 — Certification Report

Session: 2026-09-05. Verdict, evidence and remaining debt for the milestone
that closes the last runtime split: a canonical citizen physically executes a
complete ordinary day through the real city with one identity, one itinerary,
one movement authority, real collision, persistence and LOD.

## Verdict

**ASPHODEL_EMBODIED_MOBILITY_V1: PASS**

All fourteen pass gates (A–N) hold on the final tree; see "Pass gates" for
the evidence behind each, and "Remaining debt" for what is real and open.

## Provenance

| item | value |
|---|---|
| STARTING_MAIN_SHA | `bee2f18a1827e216f8d998fcf995e9fe935b4a86` (origin/main, "main is the canonical Asphodel branch") |
| STARTING_BRANCH | `main` |
| MERGE_BASE_SHA | `bee2f18a1827e216f8d998fcf995e9fe935b4a86` |
| BRANCH | `claude/asphodel-embodied-mobility-v1-6gl4a8` |
| FINAL_SHA | see the last commit on the branch (this report is committed with the code) |

The outbreak branch `claude/outbreak-config-types-A8fTw` was not touched.

## Authority changes

| concern | authority now | file |
|---|---|---|
| planning | `CitizenRuntime` (schedule → goals → typed `Itinerary[PlanStep]`), re-planned from the reported physical situation | `asphodel/citizens/{runtime,planning,goals}.py` |
| movement clock | `World.advance_seconds` (sub-tick game seconds inside the epidemic tick; auto-tick) | `asphodel/orchestrator.py` |
| execution | `MobilityRuntime` → one `TripExecutor` per registered citizen; `World.physical_location` reads it | `asphodel/embodied/{runtime,executor}.py` |
| walking | `PedestrianController` on the route's street polyline; NEAR: `CitizenBody` follow mode | `asphodel/embodied/pedestrian.py`, `godot/scripts/citizen_body.gd` |
| driving | `VehicleController` on the persistent `VehicleInstance`; NEAR: `VehicleBody` follow mode | `asphodel/embodied/vehicle_control.py`, `asphodel/transport/instances.py`, `godot/scripts/vehicle_body.gd` |
| route → road | access nodes + connectors with real street partial polylines; `PhysicalPath.from_route` | `asphodel/embodied/pathing.py` |
| parking | compiled PARKING/DRIVEWAY anchors, validated and occupied | `asphodel/embodied/parking.py` |
| building transitions | LEAVE/ENTER_BUILDING against compiled BUILDING_ENTRANCE anchors, canonical building ids, `World.building_occupants` unchanged | `asphodel/embodied/executor.py` |
| LOD | distance bands (`lod/entity.LODController`) inside the runtime; ROUTE_SIMULATED for all registered, PHYSICAL within 150 m, ABSTRACT overflow | `asphodel/embodied/runtime.py` |
| persistence | save v3 `mobility` block + `subtick_s`; restored by `World.enable_mobility` | `asphodel/save.py` |
| bridge | protocol v4: `ADVANCE_TIME`, `MOBILITY_REPORT`, `GET_MOBILITY`, `SET_FOCUS xy` | `asphodel/bridge/{protocol,session}.py`, `godot/scripts/sim_bridge.gd` |
| embodiment | `EmbodiedMobility` node (NEAR bodies, reports), `GameClock` movement clock | `godot/scripts/{embodied_mobility,game_clock,isometric_world}.gd` |
| legacy traffic | `traffic.gd` = EXPLICIT_NONCANONICAL_PRESENTATION, first-person scene only | `godot/scripts/traffic.gd` |

`embodiment.resolve_physical_location` is now only the FAR authority for
citizens the runtime does not register (no home building, or a home entrance
farther than 60 m from a walkable street: Houston 2/60, Madisonville 7/60,
reported as `unregistered` events), and for worlds without a street graph.
Full design: `EMBODIED_MOBILITY_ARCHITECTURE.md`; the census of what moved:
`EMBODIED_MOBILITY_AUTHORITY_CENSUS.md`.

## One-day trace (citizen 4, Houston; home 13106, work 4517, car veh:4)

`tests/test_embodied_mobility_day.py` (authoritative path, 15 s advance steps,
1 s substeps) + `godot/tests/EmbodiedMobilityGate.tscn` (in-engine, real
physics, 0.1 game-s per physics frame). Table as printed by the test with the
gate's probe trace present:

```
  home                     PASS     citizen 4 starts inside home building 13106 (stored identity), activity sleep
  leave_interior           PASS     LEAVE_BUILDING executed at 9002 s: citizen on foot at the compiled entrance anchor (1210,687)
  pedestrian_navigation    PASS     6 walk legs on the street graph, 392 m walked at 1.4 m/s (no teleport); in-engine CitizenBody within leash 300/300 frames
  vehicle_entry            PASS     ON_FOOT -> ENTERING_VEHICLE -> IN_VEHICLE for persistent veh:4 (owner 4); in-engine PASS
  road_navigation          PASS     DRIVE leg 3713 m over 76 real streetmap segments (MobilityGraph route projected onto street polylines)
  physical_driving         PASS     VehicleBody drove 3700 m under physics following the canonical route; within leash 3832/3850 frames; impacts 171 (all in the blocker phase)
  traffic_interaction      PASS     solid vehicle ahead: body stopped, authority held; following / junction / closed-road logic in tests/test_embodied_controllers.py
  parking                  PASS     PARKING_ANCHOR #44971 chosen 61 m from the work entrance, reached by the DRIVE leg, veh:4 parked at it; in-engine PASS
  vehicle_exit             PASS     PARKED -> EXITING_VEHICLE -> ON_FOOT beside veh:4
  destination_building     PASS     ENTER_BUILDING at the compiled entrance of building 4517 == stored work_building_id
  interior                 PASS     descriptor 1 room / 3 fixtures; at 11:00 the citizen's location is building 4517; GET_INTERIOR occupants include citizen 4 (in-engine)
  scheduled_duty           PASS     'work' began at 10800 s only after arrival at 9424 s (scheduled != arrived)
  return_trip              PASS     second DRIVE leg 3732 m executed
  return_home              PASS     home again at 46851 s; evening activity leisure
  save_load                PASS     saved during walking, driving, parked and inside work; identity, itinerary, step, progress, building, vehicle restored; continuation bit-identical
  lod_promotion_demotion   PASS     3 authoritative band transitions; in-engine: demoted, progressed 170 m while far, promoted back at the authoritative pose (jump 0.00 m)
```

Whole day (05:00 → 05:00): states in order
`doing_activity → on_foot → entering_vehicle → in_vehicle → driving → parked →
exiting_vehicle → on_foot → inside_building → doing_activity → …` (mirror trip
at 16:00, errand at 16:30, leisure, sleep). No scripted relocation anywhere:
every position is a controller integration or a ≤ 3 m transition; the
executor-day test samples every 1 s substep and asserts the no-teleport bound.
Artifacts: `artifacts/mobility/one_day_trace.json`, `vehicle_trace.json`,
`parking_trace.json`, `save_load_trace.json`, `lod_promotion_trace.json`,
`godot_probe_trace.json` (per-frame authoritative vs body positions).

## In-engine gate (tools/run_mobility_gate.sh → EmbodiedMobilityGate.tscn)

24/24 PASS on the final tree (`artifacts/mobility/godot_probe_trace.json`,
`results`): world started with mobility; citizen registered; home before the
commute; left home on foot; CitizenBody on CollisionLayers.NPC; walked to the
car physically (38.9 m, 300/300 frames within leash); entered vehicle;
VehicleBody on layer VEHICLE; one body per identity; save/load mid-drive
identical; physical driving followed the route (3700 m); a solid vehicle ahead
stopped the body and the authority waited; parked at destination; vehicle
identity preserved; exited on foot; entered work; no bodies inside; interior
occupant because arrived; scheduled duty after arrival (08:01 work);
LOD demoted when the player left, progressed 170 m while far, promoted back
with a 0.00 m jump; returned home.

The scene streams the compiled Houston city (ExteriorWorld building colliders
+ ground) and runs real Godot physics headless. Bugs this gate found and
fixed: the vehicle body counted ground contact as an impact and aborted its
substeps; substeps applied the full velocity n times; the vehicle speed cap
did not scale with clock pacing; building colliders were bounding boxes that
bulged over streets (now extruded footprint hulls); the schedule hour was
stale inside a long `ADVANCE_TIME`.

## Rendered evidence (tools/run_mobility_shots.sh → EmbodiedMobilityShot.tscn)

The real `IsometricWorld` scene under xvfb/software GL with the live bridge,
camera on the citizen (`docs/mobility/evidence/`, `manifest.json` records
file, caption, hour, state, authoritative position and the bodies present):

| shot | what it shows |
|---|---|
| 00_home_before_commute | 07:27, citizen inside home 13106, no body (inside) |
| 01_leaving_home | CitizenBody at the compiled entrance anchor |
| 02_walking_to_car | the citizen body walking the street toward the parked blue car |
| 03_entering_car | at the car door (ENTERING_VEHICLE) |
| 04_driving_real_street | the red VehicleBody on the canonical route through the streamed city |
| 05_vehicle_interaction | the rendered pass did **not** capture the hold behind the blocker (the run-until timed out with `blocked=false`, car out of frame); the vehicle-ahead interaction is evidenced by the headless gate's probe trace (body stopped, authority held) |
| 06_parked_near_work | the red car parked at the chosen anchor in the lot beside work, among static parked props |
| 07_exiting_car | citizen on foot beside the car |
| 08_walking_into_work | at the work entrance |
| 09_inside_workplace | inside building 4517 (the player entered through the same interior system); the occupant is citizen 4 |
| 10_return_trip_driving | 16:0x driving home |
| 11_home_again | inside 13106 again |

## Vehicle result (veh:4)

| metric | value |
|---|---|
| route length (DRIVE leg, home → work parking) | 3713.4 m over 76 street segments |
| physical distance driven by the VehicleBody (gate) | 3700 m |
| authoritative distance driven, whole day | 7445 m (two legs) |
| collisions | 171 slide contacts, all while held behind the blocker vehicle; 0 elsewhere |
| blocked events | 1 (the blocker; authority held, resumed on removal) |
| parking | PARKING_ANCHOR #44971, 61 m from the work entrance, connector 8 m, no rejections; morning: DRIVEWAY_ANCHOR #31968, 7 m from home |
| identity | `veh:4`, owner 4, driver 4 while driving, `driver=None` after exit, across spawn/park/enter/drive/exit/save/load/promote/demote |

## LOD result

Python: registered citizens are ROUTE_SIMULATED; citizen 4 promoted to
PHYSICAL at the home focus, demoted when it drove out of the 150 m radius,
promoted again on return (3 transitions, `lod_promotion_trace.json`). In
engine: bodies freed with the focus 1.5 km away, the authoritative trip kept
progressing (170 m in 20 s), the body was recreated at the authoritative pose
(jump 0.00 m), same `cit:4` / `veh:4` ids; the gate counted 26 promotions and
25 demotions of bodies over the day with never two bodies per identity.
Overflow ABSTRACT band (freeze + catch-up) is exercised in
`tests/test_embodied_lod.py`.

## Save/load

Interruption points tested (Python): walking, driving, parked (walk-from-
parking leg), inside work; each restores `physical_location`, executor state,
itinerary (verbatim route), vehicle and building identically, and a
continuation of both worlds is byte-identical (`world_state` JSON,
`sort_keys`). In engine: SAVE + LOAD mid-drive through the bridge, citizen and
vehicle rows identical. Save schema v3; v1/v2 saves still load with mobility
disabled (`tests/test_embodied_saveload.py`, 12 tests). The existing
bit-identical save/load certification (`tests/test_save.py`) is green.

## Multi-city (tools/mobility_city_smoke.py → artifacts/mobility/city_smoke.json)

| city | status | registered | vehicles | trips in 4 h | failures | route ms median / max |
|---|---|---|---|---|---|---|
| houston | PASS | 58/60 | 40 | 22 | 0 | 0.005 / 87.9 |
| madisonville_tx | PASS | 53/60 | 34 (2 lost their car: no valid parking) | 19 | 0 | 0.005 / 8.1 |
| austin | PASS | 60/60 | 42 | 23 | 0 | 0.006 / 191.7 |
| san_antonio | PASS | 60/60 | 40 | 26 | 0 | 0.006 / 205.4 |
| boulder | INFO | — | — | — | — | no compiled world |

No city-name special cases; the smoke selects cities purely by the presence
of a compiled world. `tests/test_embodied_city_smoke.py` runs a reduced form
for Houston, Madisonville and San Antonio.

## Performance (tools/mobility_perf.py → artifacts/mobility/performance.json, Houston)

| measure | value |
|---|---|
| route home→work (FOOT / CAR) | 36 ms / 32 ms (pure-Python Dijkstra, 16k segments) |
| random routes (20, seed 0) | 57 ms FOOT, 41 ms CAR per route |
| pedestrian controller | 0.002 ms / substep |
| vehicle controller | 0.013 ms / substep alone; 0.5 ms with 10–50 neighbours (before the windowed scan) |
| runtime advance, 58 citizens | 6.1 ms / game-minute off-peak, 43.9 ms at the 07:00 peak |
| promotion (catch-up after 1 h frozen) / band update | 0.75 ms / 0.05 ms |
| snapshot (58 citizens, 40 vehicles, 34 KB) | 0.31 ms |
| save / restore | 1.6 ms / 225 ms (restore now skips vehicle re-spawn) |
| live 1 citizen + 1 car (gate) | ~50 physics frames/s headless at 6× compression incl. chunk streaming |
| budget at 24× pacing | 2.5 s real per game-minute; 58 citizens use 0.24 % (1.8 % at peak); ~410× headroom |

Live 10 / 50 moving bodies were not measured in-engine (one embodied trip
plus other citizens' parked bodies within 150 m); the Python tier scales
linearly (0.1 ms/citizen/game-minute), so the physical-body count, not the
simulation, is the frame budget question.

## Regression

| suite | result |
|---|---|
| `python -m pytest` (whole tree, excluding the two long day tests) | 803 passed, 1 failed — `test_world_from_compiled::test_compile_writes_only_presentation_files` needs the raw Overture parquet, fails identically on origin/main (environment, not a regression) |
| `tests/test_embodied_*.py` (8 files) | 71 passed |
| `tests/test_embodied_mobility_day.py` | 18 passed, table above |
| `tests/test_living_city_vertical.py`, `test_convergence_gates.py`, `test_save.py`, `test_embodiment.py` | green |
| `godot/tests/run_gates.sh` (PhysicsGate 16, RegionGate, NavGate, ConvergenceGate) | 85 PASS, 0 FAIL |
| `res://tests/ExteriorStream.tscn` | 0 failures |
| `tools/run_mobility_gate.sh` | 24/24 PASS |

## Pass gates

| gate | verdict | evidence |
|---|---|---|
| A one planner | PASS | `World.advance_seconds` → `MobilityRuntime` executes `CitizenRuntime.itinerary`; `build_itinerary` now has a production caller |
| B one citizen authority | PASS | `World.physical_location` / `_zone_embodiment` read the executor for every registered citizen; schedule-fraction placement only for unregistered (FAR) citizens |
| C physical walking | PASS | gate: CitizenBody on NPC layer followed the planned route, 300/300 frames within leash |
| D vehicle identity | PASS | `veh:4` persistent through spawn/park/enter/drive/exit/save/load/LOD |
| E physical driving | PASS | gate: VehicleBody drove 3700 m along the canonical route under physics |
| F parking | PASS | validated anchor chosen at plan time, reached by the drive, occupied |
| G building transitions | PASS | LEAVE/ENTER at compiled entrances, canonical ids, interior occupancy in engine |
| H scheduled duty | PASS | `work` only after arrival (08:01 in engine, 10800 s in Python) |
| I return trip | PASS | second drive + walk home, evening at home |
| J collision | PASS | bodies stamped from CollisionLayers; PhysicsGate green; hull colliders; blocker contact held the car |
| K persistence | PASS | four interruption points, bit-identical continuation, in-engine SAVE/LOAD |
| L LOD | PASS | demote/promote with identity and 0.00 m jump, abstract progress while far |
| M no teleport | PASS | every transition ≤ 3 m; per-substep jump bound asserted in `test_embodied_executor_day.py` |
| N regression | PASS | suites above; the one failure is pre-existing and environmental |

## Remaining debt (real)

* **Crash escalation** is not wired: `VehicleBody._on_impact` counts contacts;
  PHYSICAL_CRASH → wreck → `MobilityObstruction` is future work (the blocked
  report already holds the simulation).
* **Junction yielding on fast roads**: `junction_yield_m` (14 m) is shorter
  than the stopping distance at the 16 m/s ceiling, so a car can roll through
  a yield on a trunk road; correct on calm streets (tested).
* ~~**Pedestrians walk the road polyline** (no sidewalk offset)~~ — closed by
  `ASPHODEL_OUTBREAK_V1`: walking legs run 4.5 m kerb-side of the centreline
  (`asphodel/embodied/executor.py::walk_path`); they still yield to
  moving cars. Kerb-side geometry is a later refinement.
* **Materialization safety** (`lod/materialize.py`) is not applied at body
  spawn; anchors are outside footprints by construction.
* **Unregistered citizens**: home entrances > 60 m from a walkable street stay
  FAR (Houston 2, Madisonville 7); explicit `unregistered` events.
* **Madisonville parking**: 2 of 34 car owners find no valid anchor near home
  and walk (explicit event).
* **Routing cost**: cold routes 30–200 ms in pure Python; fine for the bounded
  canonical population, a hitch risk if run on a render thread with many
  simultaneous replans.
* **Restore cost** ~225 ms for 58 citizens (anchor re-attachment).
* **Live determinism boundary**: the Godot path passes frame deltas; the
  semantic trip is reproducible to the 1 s substep, not bit-for-bit.
* **Pacing**: at the default 24× clock, NEAR bodies move at 24× real speed
  (documented in the architecture); the evidence scenes run at 6× / real
  time. Choosing the gameplay pacing is a product decision, not made here.
* **Concave footprints** get hull colliders (a courtyard is solid).
* Vehicle parked-route fields (`progress`, `segment`) are not persisted for a
  finished route (identity and pose are).

## Next milestone

**ASPHODEL OUTBREAK V1 — Epidemiology + Civil Breakdown on the Embodied Living
City.** The outbreak now has real citizens, real trips, real cars and real
buildings to act on: a `MobilityObstruction` reroutes a commute, an abandoned
car is a `VehicleInstance` with `driver=None`, "never got home" is an
executor that never reached `INSIDE_BUILDING` at `home_building_id`.

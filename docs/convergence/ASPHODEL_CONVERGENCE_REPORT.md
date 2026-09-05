# Asphodel — Canonical Convergence Report

Session: 2026-09-05. Verdict, evidence and remaining debt for the canonical
convergence. Companion documents: `ASPHODEL_BRANCH_CENSUS.md`,
`ASPHODEL_BRANCH_DISPOSITION.md`, `ASPHODEL_CANONICAL_ARCHITECTURE.md`.

## Verdict

**ASPHODEL_CANONICAL_CONVERGENCE: PARTIAL** — see "Remaining splits" for the
precise, unresolved architectural splits. Everything else in the PASS list is
met on the recorded final SHA.

## Provenance

| item | value |
|---|---|
| starting default branch | `claude/asphodel-belief-cascade-kvKKv` @ `35d0c86695dd373b5e78a68889f90fd2603f3f22` |
| chosen spine | `main` (== `claude/asphodel-houston-scene-outdated-k9aetu`) @ `57ef86a6d73b8d0b5269f8753b41a45f5442f182` |
| merged line | `claude/asphodel-regional-physics-navigation-v1-1bpcqs` @ `b5cf43a967405fd2383ef8dc37db4b9af0e91345` |
| convergence branch | `claude/asphodel-canonical-convergence-i6h105` |
| final certified SHA | `7244855` (all code, bundles and evidence); the report commit on top of it is docs-only and is the landing tip named in the PR |
| landing | fast-forward `main` to the final SHA (the landing PR from `claude/asphodel-canonical-convergence-i6h105` into `main`); switch the GitHub default branch to `main`; close PR #3 |

Remote re-fetched before landing: no branch moved since the census.

## Branch census (counts)

| | |
|---|---|
| inspected | 18 |
| canonical spine | `main` (2 refs) |
| integrated this session | 1 (regional-physics-navigation) |
| already contained | 12 |
| superseded | 2 (+ the flux half of scenario-engine-flux) |
| experiment only | 1 (scenario-engine-flux harness) |
| requires architectural decision | 1 (outbreak-config-types: zombie compartments) |
| blocked | 0 |
| safe to retire | 15 `claude/*` refs (all but outbreak-config-types, kept for its port) |

## Authority table

| domain | canonical implementation | supersedes |
|---|---|---|
| World state | `asphodel/orchestrator.py` `World` (+ `model.py` macro ledger, `micro.py` agents) | any Godot-local state; `first_person.gd` inventory (removed) |
| Public-data ingestion | `asphodel/world_source/` (Overture, provenance-gated, normalized `WorldSourceV1`) | OSM Overpass pipeline (`osm_city`, now the zone-grid baker only) |
| Regional world | `asphodel/geo.py` + `asphodel/region/` + `region_bundle.py` (region.json v2, city plateau) | flat-only world; per-scene ad-hoc terrain in shot scripts |
| Buildings | `world_source.compile` → `buildings.json` v1 (index == id) + chunks + `world/identity.json.gz` | `building_builder.gd` cluster, `osm_city/synth.py` (deleted); `generate_procedural` is the synthetic fallback only |
| Residential architecture | `world_source/residential_grammar.py` + `city_visual/residential_architecture.py` → `residential_house_renderer.gd` | GDScript porch/garage rolls (legacy fallback for record-less bundles only) |
| Interiors | `asphodel/interiors.py` descriptor v1 → `interior_builder.gd` | `interior_generator.gd`/`furniture_factory.gd` (deleted); `world.py generate_interior` (synthetic helper) |
| Mobility | `asphodel/mobility/` `MobilityGraph` over `streetmap.json` v2 (Overture connectors) | `roads.json` polylines (legacy fallback), three duplicated graph builders in `osm_city`, `vehicles.RoadNetwork` as a road model |
| Citizen simulation | `World` + `citizen.py` profiles + `bundle_population` + `npc.py` + `embodiment.py` + `roster.py`; planner `asphodel/citizens/` | blocks-scatter citizen bake (legacy for bundles without buildings.json) |
| Citizen visuals | `citizen_visual_identity.gd` (mirror of `npc.visual_seed`) + `citizen_meshes/avatar/render.gd` | capsules/pills (gone) |
| LOD | `asphodel/lod/` bands + `World` promotion + `ExteriorWorld` tiers + `RegionLoader` near/far | — |
| Vehicles | `asphodel/transport/` `VehicleInstance` + `TrafficReconciler`; `vehicle_body.gd` | `traffic.gd` ambient movers (legacy presentation); `vehicles.py` = trip estimator only |
| Collision | `asphodel/physics/layers.py` → `collision_layers.gd`; every shipped body stamped | Godot default layers everywhere |
| Persistence | `asphodel/save.py` (SAVE_VERSION, now with building ids) | — |
| Godot runtime | `IsometricWorld.tscn` default, `StreetScene.tscn` legacy first-person; `SimBridge` protocol 3; Gate I schema contract in `bundle_loader.gd` | `CityScene.tscn` (deleted) |

## Schema table

| schema | version | status |
|---|---|---|
| `meta/zones/roads/timeline.json` | "1" | canonical (macro tier); `roads.json` legacy fallback only |
| `mobility.json` (zone edges) | 1 | canonical, derived from streetmap |
| `streetmap.json` | 2 (1 read) | canonical street graph |
| `buildings.json` | 1 | canonical, validated in Python (`validate_buildings_doc`) and Godot (`check_buildings`) |
| `world/chunks`, `identity`, `spawn_anchors`, `world_meta` | 1 | canonical |
| `citizens.json` | list (+ `home_building_id`/`work_building_id`) | canonical |
| `region.json` | 2 | canonical (plateau, provenance) |
| `physics.json` / `collision_layers.gd` | "1" | canonical, byte-identical across bundles |
| `playback.json` | 2 | dev/demo |
| interior descriptor | 1 | canonical |
| bridge protocol | 3 | canonical |
| save | `SAVE_VERSION` | canonical |
| asset catalog v1 | 1 | canonical, regenerated from `tools/build_catalog_v1.py` |

## City matrix

`python tools/city_matrix.py` on the final tree (Gate H, Python half):

```
capability         houston         madisonville_tx austin          san_antonio     boulder         denver_region   
bundle_loads       PASS            PASS            PASS            PASS            PASS            N/A             
terrain_loads      PASS            PASS            PASS            PASS            PASS            PASS            
streetmap_loads    PASS            PASS            PASS            PASS            PASS            N/A             
roads_align        PASS            PASS            PASS            PASS            N/A             N/A             
buildings_load     PASS            PASS            PASS            PASS            PASS            N/A             
building_identity  PASS            PASS            PASS            PASS            N/A             N/A             
citizens_spawn     PASS            PASS            PASS            PASS            PASS            N/A             
vehicles_spawn     PASS            PASS            PASS            PASS            PASS            N/A             
collision_matrix   PASS            PASS            PASS            PASS            PASS            PASS            
world_starts       PASS            PASS            PASS            PASS            PASS            N/A
CITY_MATRIX: PASS (0 failing cells)
```

roads_align = Gate C street/mobility parity: 100.0 % / 100.0 % (streetmap→chunks / chunks→streetmap, 120 samples per city, 4 m) for all four compiled cities. Boulder is a synthetic city (no compiled world, no identity table) and denver_region is a terrain-only proving ground; those cells are N/A by design, not failures.

Godot half (`ConvergenceGate.tscn`, in-engine): bundle / buildings /
streetmap / region / physics / region_chunks / exterior — PASS for Houston,
Madisonville, Austin, San Antonio; Boulder: streetmap/region/physics/chunks
PASS, no compiled world (INFO).

## Living-city vertical (one citizen, one day; `tests/test_living_city_vertical.py`)

```
  home                     PASS      citizen 4 sleeps in building 13106 (stored identity)
  exit                     PASS      interior entrance room 2, exterior anchor at (1210,687); in-engine walk-in/out certified by LiveWalkIn
  pedestrian_navigation    PASS      foot route 3466 m over 70 real segments (41 min); physical walking of a CitizenBody along a route certified in NavGate, not yet driven by World
  vehicle                  PASS      itinerary [leave_building, enter_vehicle, drive, park, exit_vehicle, enter_building] mode=car
  road_navigation          PARTIAL   veh:4 progressed 1.00 of 3685 m on car-legal segments (route-simulated); a VehicleBody driving this route in-engine is a seam (PhysicsGate proves the body, not the drive)
  parking                  PARTIAL   PARK/EXIT_VEHICLE are plan steps and the instance records a parked location; PARKING_ANCHOR selection at the destination is not wired
  destination_building     PASS      at 11:00 the citizen is at building 4517 == stored work_building_id; it has a compiled entrance anchor
  interior                 PASS      descriptor: 1 rooms, 3 fixtures == containers; occupants at 11:00 include citizen 4: True
  scheduled_duty           PASS      schedule -> activity 'work' at 11:00 (World) and goal do_activity 'work' (CitizenRuntime)
```

Read strictly: **home → exit → pedestrian navigation → destination → interior → duty is PASS** at the authority level, and the in-engine half of it (street → enter a real building → walk the interior → search containers → leave → re-enter → save/load) is the certified `LiveVertical` scene. **Vehicle and road navigation are PARTIAL**: a persistent vehicle with one identity routes on car-legal real streets and its plan parks it, but no physical car drives that route in the playable scene. A scripted teleport was not counted anywhere; a marker following a route was counted as PARTIAL, not PASS.

## Test evidence

| command | result |
|---|---|
| `python -m pytest -q` (final tree, 7244855) | **740 passed, 0 failed** (13 min); baseline on the spine was 543 passed + 1 network-only failure, regional line 272 |
| `python -m pytest tests/test_convergence_gates.py` (Gates A, B, D, E, F, H) | 27 passed |
| `python -m pytest tests/test_gate_street_parity.py` (Gate C) | 100 % / 100 % parity, Houston + Madisonville |
| `python -m pytest tests/test_living_city_vertical.py -s` | 10 passed; step table above |
| `godot --headless --path godot res://tests/{TestRunner,StreetSmoke,ExteriorStream,CitizenHumanoidSmoke,IsometricExteriorSmoke,IsometricCameraSmoke,AssetCatalogSmoke}.tscn` | all exit 0 |
| `godot/tests/run_gates.sh` (PhysicsGate 16, RegionGate 8, NavGate 4) | all PASS |
| `godot --headless --path godot res://tests/ConvergenceGate.tscn` (Gates G, I, E, H in-engine) | PASS, 0 failures |
| `tools/final_cert.sh` (live bridge: LiveSmoke, save/destroy/reload, LiveSurvival, LiveInterior, LiveWalkIn, LiveVertical, InteriorBench, LiveBench) | all 0 failures; save/load BIT-IDENTICAL |
| `python tools/city_matrix.py` | PASS, 0 failing cells |
| `python tools/build_catalog_v1.py` + `tests/test_asset_catalog_conformance.py` | twins identical |

Every suite was run on the converged tree, not trusted from older reports.
`tools/convergence_cert.sh` reproduces the whole table in one command.

## Godot evidence

Godot 4.4.1-stable, headless for logic and xvfb + software OpenGL for
captures (no GPU in this environment; frame rate was therefore not measured).

Headless suites (all exit 0 on the final tree): TestRunner, StreetSmoke,
ExteriorStream, CitizenHumanoidSmoke, IsometricExteriorSmoke,
IsometricCameraSmoke, AssetCatalogSmoke, PhysicsGate (16/16), RegionGate
(8/8), NavGate (4/4), ConvergenceGate (Gates G/I/E/H in-engine, 0 failures).

Live bridge (`tools/final_cert.sh`, Python server + Godot client): LiveSmoke
0 failures; save → destroy process → reload BIT-IDENTICAL; LiveSurvival,
LiveInterior, LiveWalkIn, LiveVertical (30-step interiors vertical) all 0
failures; InteriorBench 40 descriptors, 3.36 ms build avg; LiveBench Houston
317 live agents, IPC 236 ms, apply 9.4 ms.

Captures (`docs/convergence/evidence/`): Houston isometric exterior, crowd,
wide, interior cutaway; Madisonville exterior and wide; the living-city
commute on the region v2 plateau; Boulder with the Front Range behind it;
Denver and Houston regional horizons. Inspection found no world displaced
from terrain, no road/building misalignment, no floating citizens, no
capsule NPCs, no duplicate layers. Limitations: software GL only; the
regional terrain is not yet visible in the isometric captures at gameplay
zoom (it sits beyond the 3 km plateau); `traffic.gd` ambient cars exist only
on the legacy first-person path and were not captured.

## Performance

Measured on the final tree in this environment (4 vCPU, no GPU); the spine
`main` @ `57ef86a` was benchmarked in the same session on the same box for
comparison, so the numbers below isolate the convergence from the machine.

| metric | spine `57ef86a` | converged tree | note |
|---|---|---|---|
| ExteriorWorld T1 build (ground + masses), ms/chunk avg / max | 46.2 / 82.2 | 45.3 / 77.6 | `OwPerfBench`, Houston 7×7 sweep, 96 resident chunks, 5,924 MultiMesh instances — no change |
| ExteriorWorld T2 build (grammar + roads + collision) | 31.5 / 146.6 | 31.7 / 150.0 | no change (collision-layer stamping is free) |
| ExteriorWorld T3 build (props/vehicles/trees) | 7.15 / 21.8 | 7.18 / 21.9 | no change |
| IsometricPerfBench T1 / T2 / T3 avg | — | 44.7 / 60.1 / 7.9 | 98 chunks, 6,461 instances (T2 is heavier in the isometric scene: cutaway metadata) |
| LiveBench Houston, 317 live agents: IPC / apply | 211 ms / 3 ms (OW10 record) | 236 ms / 9.4 ms | same order; the apply now drives humanoid buckets |
| InteriorBench descriptor build | — | 3.36 ms avg, 84 resident nodes | |
| RegionLoader (RegionGate) | — | 64 chunks + 16 near colliders per city, ~1 s scene | |
| `MobilityGraph.load` Houston / San Antonio | (1,088-segment v1) | 1.55 s / 3.37 s (15,988 / 27,336 segments) | new cost of the full street graph |
| route query median, car, Houston / San Antonio / Madisonville | — | 183 ms / 339 ms / 15 ms | pure-Python Dijkstra; see debt |
| `nearest_segment_point` | — | 0.4–0.9 ms after a 1 s index build | |
| `World` build / step, Houston | — | 3.6 s / 3.2 ms per tick | unchanged tier |
| citizens + spatial context load, Houston / San Antonio | — | 9.4 s / 15.3 s | 22.5k / 35.7k footprints + graph index |
| Python heap peak (Houston world + graph + context) | — | 139 MB | |

The OW10 findings quoted much lower T1/T2 numbers (9.7 / 4.0 ms); the spine
already measures 46 / 31 ms on this machine before any convergence change, so
that gap is environment/renderer-package history, not this session. LOD and
materialization boundaries were not moved: the crowd cap, avatar pool, chunk
tiers and near-only terrain colliders are unchanged, and no scene
materializes the metropolitan population.

## Remaining splits (why PARTIAL)

1. **Planner ↔ World.** `CitizenRuntime` (goals, itineraries, replanning) is the
   designated navigation planner and is exercised on the canonical citizens
   (`living_city.py`, the vertical proof), but `World.step` does not drive its
   promoted citizens through it: commuters are placed along the road network by
   `embodiment` from schedule progress. One citizen authority, two motion
   models until `World` consumes itineraries.
2. **Vehicles in the playable scene.** `VehicleInstance`/`VehicleBody` are one
   identity in Python and are proven in physics gates, but the playable scenes
   still show `traffic.gd` ambient movers (first-person path) and static parked
   props; no vehicle in the gameplay scene is a `VehicleInstance`.
3. **Terrain is synthetic and the city is flat.** Region v2 places the city on
   its plateau and the region around it, but no DEM is baked (USGS egress
   blocked) and the compiled city does not drape on relief.
4. **Zombie epidemiology is unmerged.** `outbreak-config-types` (undead/corpse
   compartments) needs a cross-tier port; recorded, not landed.

## Remaining debt (real, not minimized)

* Route queries on the full Houston graph (15,988 segments) take ~180 ms
  median in pure-Python Dijkstra (San Antonio ~340 ms). Fine for bakes and
  occasional replans; hundreds of simultaneous replans need A*/bidirectional
  search or a compiled router.
* Loading a compiled city's spatial context (22.5k footprints + graph index)
  takes ~9 s for Houston, ~15 s for San Antonio, once per session.
* `region_loader.gd` still omits the LOD skirts the Python mesh has; the
  regional terrain is drawn in the gameplay scenes but not yet visible at
  gameplay zoom, and terrain draping of the compiled city is not implemented.
* The exterior compiler does not emit `ground_markings` (parking stall
  paint) or the four newer vehicle kinds; the `tools/repatch_*.py` scripts
  that patched those into chunks are one-shot legacy patchers whose effect the
  Houston re-bake dropped. The vocabulary now lives in the compiler tables;
  the generators still need to place them.
* `interior_builder.gd` reads fixture `variant` (only decor carries one) and
  the descriptor's `notes`/`fixture_state` are unread; chunk `parcels` and
  chunk-level `anchors` have no Godot reader.
* Only Houston chunks carry residential `architecture` records (the other
  three compiled cities need a compile with the current grammar).
* Austin and San Antonio citizens were re-baked on the compiled path this
  session, but their `world/certification.json` was never generated.
* `citizen_body.gd`, `vehicle_body.gd`, `mobility_loader.gd`, `debug_overlay.gd`
  are exercised by gates only; the playable scenes do not instantiate them yet.
* Version fields: `meta/roads/physics` still carry `"1"` strings; new schemas
  use integers. Harmless, inconsistent.

## Retired development lines

Every `claude/*` branch except `claude/outbreak-config-types-A8fTw` (kept
until its port lands). See the disposition document.

## Next development base

**All new Asphodel development begins from `main` once the landing PR is
fast-forwarded; until then from `claude/asphodel-canonical-convergence-i6h105`
@ the landing tip named in the PR (docs-only commit on top of `7244855`).**

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
| final SHA | FINAL_SHA_PLACEHOLDER |
| landing | fast-forward `main` to the final SHA (PR LANDING_PR_PLACEHOLDER); switch the GitHub default branch to `main`; close PR #3 |

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

CITY_MATRIX_PLACEHOLDER

Godot half (`ConvergenceGate.tscn`, in-engine): bundle / buildings /
streetmap / region / physics / region_chunks / exterior — PASS for Houston,
Madisonville, Austin, San Antonio; Boulder: streetmap/region/physics/chunks
PASS, no compiled world (INFO).

## Living-city vertical (one citizen, one day; `tests/test_living_city_vertical.py`)

VERTICAL_PLACEHOLDER

## Test evidence

TESTS_PLACEHOLDER

## Godot evidence

GODOT_EVIDENCE_PLACEHOLDER

## Performance

PERF_PLACEHOLDER

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

DEBT_PLACEHOLDER

## Retired development lines

Every `claude/*` branch except `claude/outbreak-config-types-A8fTw` (kept
until its port lands). See the disposition document.

## Next development base

**All new Asphodel development begins from `main` once the landing PR is
fast-forwarded; until then from `claude/asphodel-canonical-convergence-i6h105`
@ FINAL_SHA_PLACEHOLDER.**

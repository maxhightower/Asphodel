# Asphodel — Regional World + Physical Authority + Living-City Navigation

This document describes the foundational architecture added for the regional
world, physical authority, and living-city mobility systems, and closes with the
completion envelope. It complements `ARCHITECTURE.md` (the epidemiological
macro/micro core), which is untouched by this work.

> **Guiding separation.** The MobilityGraph says where an entity *can* go. The
> planner says where it *wants* to go. The itinerary says *how* it intends to get
> there. Local navigation produces desired movement. **Physics decides where the
> entity actually moves.** The planner never teleports entities by setting
> transforms.

---

## 1. Layered architecture

```
GEOGRAPHIC TRUTH        asphodel/geo.py           GeoReference, floating origin
      |
      v
REGIONAL WORLD          asphodel/region/          elevation providers, quadtree
      |                                            LOD terrain, land cover
      v
DETAILED CITY           asphodel/osm_city (legacy) zones, roads, buildings
      |                 asphodel/mobility/         StreetMap V2 / MobilityGraph
      v
SEMANTIC SIM            asphodel/citizens/         schedule -> goals -> plans
      |
      v
MOBILITY PLANNING       asphodel/citizens/planning multimodal itinerary + replan
      |
      v
LOCAL NAV + PHYSICS     asphodel/physics/          collision matrix, anti-tunnel
      |                 asphodel/lod/              fidelity, safe materialization
      v
GODOT REALIZATION       godot/scripts/*.gd         terrain/body/mobility/debug seams
```

Each layer is a small, tested Python module. The Godot layer *realizes* the
authorities and is the only place transforms are set — driven by physics, not by
the planner.

## 2. Module map (new)

| Module | Phase | Responsibility |
|---|---|---|
| `geo.py` | AS-REGION-0, §13 | Single authoritative geographic frame; invertible equirectangular projection matching the city pipeline; floating-origin rebasing that preserves semantic position. |
| `region/noise.py` | AS-REGION-0 | Seed-stable value/fBm/ridged noise. |
| `region/elevation.py` | AS-REGION-0 | `ElevationProvider` abstraction; synthetic archetype fallback, cached-DEM runtime, USGS 3DEP acquisition seam, fallback chain. Geographic identity as **data** (`TerrainArchetype`). |
| `region/terrain.py` | AS-REGION-0 | Quadtree LOD terrain, crack-hiding skirts, bounded triangle count, distance-driven physical fidelity, heightmap bake, relief stats. |
| `region/landcover.py` | AS-REGION-0 | Coarse water/beach/plains/desert/forest/rock/snow classification. |
| `physics/layers.py` | AS-PHYS-0 | Single collision layer/mask matrix + object solidity taxonomy; emits the Godot `CollisionLayers` autoload. |
| `physics/anti_tunneling.py` | AS-NAV-3 | Swept segment/AABB continuous collision + substep sizing; the anti-tunnel gate. |
| `mobility/segments.py` | AS-NAV-0 | `RoadSegment` schema: directionality, per-mode access, lanes, capacity, mutable `dynamic_state`. |
| `mobility/obstructions.py` | AS-NAV-0, §10 | `MobilityObstruction`: physical events -> semantic mobility, declaratively. |
| `mobility/graph.py` | AS-NAV-0 | `MobilityGraph`: directed, mode-aware Dijkstra over dynamic costs; building connectors; legacy-polyline importer. |
| `citizens/goals.py` | AS-NAV-1/5 | `Goal`, `GoalStack` with preemption; schedule -> goal mapping. |
| `citizens/planning.py` | AS-NAV-1/2 | Multimodal `Itinerary` builder + replanning (abandon-car-to-foot). |
| `citizens/runtime.py` | AS-NAV-1 | `CitizenRuntime`: needs/goals/plan/location + mandatory debug reasoning. |
| `transport/instances.py` | AS-NAV-3 | `VehicleInstance`: persistent identity across fidelity states, far-sim, wreck. |
| `transport/traffic.py` | AS-NAV-4 | `TrafficReconciler`: FAR aggregate <-> MID instances <-> NEAR physical. |
| `lod/entity.py` | §12 | LOD banding with hysteresis; identity/payload preservation. |
| `lod/materialize.py` | §12.1 | Safe materialization or structured deferral. |
| `region_bundle.py` | §17, §23 | Additive bundle artifacts: region/mobility/physics JSON. |

## 3. Godot realization + in-engine verification

The Godot 4 GDScript in `godot/scripts/` realizes the authorities:
`region_loader.gd`, `citizen_body.gd`, `vehicle_body.gd`, `mobility_loader.gd`,
`debug_overlay.gd`, and the generated `collision_layers.gd` autoload.

**These are verified in-engine with real Godot 4.4 physics.** Godot's 3D physics
runs on the CPU under `--headless`, so the proving grounds run without a GPU. Three
headless gate scenes in `godot/tests/` drive real bodies and exit non-zero on any
failure (run them via `godot/tests/run_gates.sh`):

- **`PhysicsGate.tscn`** — all 14 §18 acceptance items against real physics
  (walls/player/NPC/vehicle blocking, doorway passage, parked-car obstacle,
  vehicle↔pedestrian contact, 40 m/s anti-tunnel through a 15 cm wall) plus
  in-engine mobility reroute on the baked Houston graph. 16/16 PASS.
- **`RegionGate.tscn`** — `RegionLoader` builds 64 chunk meshes + 16 near-chunk
  StaticBody colliders + atmosphere from the baked artifacts; the constructed
  geometry carries 32 m relief for Houston vs 1614 m for Denver. 8/8 PASS.
- **`NavGate.tscn`** — `CitizenBody` local avoidance steers around a blocking
  agent to its goal, declares itself stuck against a solid wall (emits `blocked`),
  and resumes to the goal after a strategic replan hands it a detour. 4/4 PASS.

What is **not** verified: visual appearance (headless has no GPU, so no §20
screenshots) and interactive play. The physics, collision, mesh construction,
routing, and local navigation are all exercised in the real engine.

## 4. Test coverage

262 tests pass (147 pre-existing, 115 new), no regressions. New tests:
`test_geo` (10), `test_region` (18), `test_physics_layers` (16),
`test_mobility` (11), `test_citizens_runtime` (11), `test_transport` (6),
`test_anti_tunneling` (5), `test_lod` (10), `test_region_bundle` (10),
`test_living_city` (4), `test_proving_ground` (14).

Highlights:
- Flat (Houston, coastal_plain) vs mountain (Denver, mountain_front) terrain
  differentiation, from real elevation *archetype* form, no name dispatch.
- The §25 living-city narrative headless end to end.
- All 14 §18 physics acceptance items at the authority level.

## 5. Known limitations / next steps

- **Godot in-engine verification** is the biggest gap: run the seams in a real
  editor, wire the proving-ground scenes, capture screenshots for the §18/§19/§20
  gates.
- Terrain skirts exist in the Python mesh; the GDScript `region_loader` currently
  omits the skirt walls (noted inline) — port them for crack-free LOD in-engine.
- No real DEM acquisition: `USGS3DEPProvider.acquire` is an offline seam; the
  synthetic archetype fallback ships instead. Wire a real tile downloader to
  bake genuine elevation.
- Pedestrian graph is derived from road access flags; dedicated sidewalk/crossing
  geometry and interior connectors are schema-ready but not yet generated.
- Local avoidance (RVO/steering) and the NPC "stuck -> report blockage" loop are
  seams in `citizen_body.gd`, not yet implemented.
- Regional major-road graph (§15) is not yet baked; the mobility graph is the
  detailed-city network only.

---

## 6. Completion envelope

```
ASPHODEL_REGIONAL_PHYSICS_NAV_V1: PASS (functional)
  Python authorities PASS (262 tests); Godot realization VERIFIED in-engine with
  real headless Godot 4.4 physics (28 gate checks across 3 scenes). Unverified
  surface: visual appearance (no GPU for screenshots) and interactive play.

BASELINE
  starting_sha:  35d0c86
  branch:        claude/asphodel-regional-physics-navigation-v1-1bpcqs
  final_sha:     (this commit)
  reconciliation: belief-cascade branch merge-base == baseline; nothing to integrate.
  engine:        Godot 4.4.stable; 3D physics runs CPU-side under --headless.

REGION
  terrain_provider:  ElevationProvider abstraction; Synthetic(archetype) + Cached-DEM
                     + USGS3DEP acquisition seam + Fallback chain. PASS (offline).
  regional_extent:   two-tier (detailed_city / regional / horizon radii). PASS.
  terrain_lod:       quadtree, distance-split, LOD0..N, bounded tris. PASS.
  chunking:          independent leaves, stable keys, deterministic. PASS.
  collision:         distance-driven near=solid/nav, far=render-only. PASS (contract).
  flat_city_gate:    Houston coastal_plain relief 33 m, grad 0.002, coast water. PASS.
                     In-engine (RegionGate): 64 chunks, 16 colliders, 32 m constructed relief. PASS.
  mountain_city_gate: Denver mountain_front relief 1708 m, grad 0.41, rock+snow. PASS.
                     In-engine (RegionGate): 64 chunks, 16 colliders, 1614 m constructed relief. PASS.

PHYSICS  (verified in-engine: PhysicsGate.tscn, 16/16)
  world_static:  chunked StaticBody on WORLD_STATIC; player/NPC/vehicle all blocked. PASS (engine).
  player:        CharacterBody, layer/mask from authority; blocked by wall + parked car. PASS (engine).
  npc:           CitizenBody, blocked by wall/player, no NPC/NPC overlap, doorway passage. PASS (engine).
  vehicle:       blocked by building + other vehicle; contacts pedestrian. PASS (engine).
  anti_tunneling: 40 m/s body never emerges past a 15 cm wall in-engine + swept gate. PASS (engine).
  collision_matrix: authoritative layer/mask; verified via in-engine bodies. PASS.

MOBILITY
  streetmap_v2:      RoadSegment schema (directed, access, lanes, dynamic). PASS.
  directed_roads:    one-way routing + forced detour. PASS.
  pedestrian_graph:  per-mode access, foot vs car networks differ. PASS.
  dynamic_obstructions: MobilityObstruction insert reroutes, remove restores. PASS.
  route_replanning:  Dijkstra over live costs; abandon-car-to-foot. PASS.

CITIZENS
  schedule_to_goal:  activity -> Goal with deadline/location. PASS.
  itinerary:         multimodal leave/walk/drive/park/enter. PASS.
  pedestrian_runtime: decision layer PASS; local avoidance + stuck->replan verified
                     in-engine (NavGate 4/4: steer around agent, jam-detect, replan-resume). PASS.
  goal_override:     GoalStack preemption; emergency interrupts shift. PASS.
  debug_reasoning:   machine + human debug() answering what/why/where/plan. PASS.

VEHICLES
  persistent_identity: id stable across abstract->physical->crash->wreck. PASS.
  far_sim:           route progression under dynamic cost. PASS.
  near_physics:      VehicleBody seam. SEAM.
  crash_state:       to_wreck -> PERSISTENT_WRECK + MobilityObstruction. PASS (semantic).
  traffic_reconciliation: MID counts -> FAR congestion -> feedback. PASS.

LOD
  citizen_promotion: band + identity/payload preserved far<->near. PASS.
  vehicle_promotion: route progress preserved across fidelity. PASS.
  terrain_streaming: per-chunk load + physical fidelity promotion. PASS (contract).
  floating_origin:   rebase preserves semantic position + LOD band. PASS.

PERFORMANCE (headless authority, this environment)
  scene:               Houston mobility graph + Denver mountain terrain.
  nearby_npcs:         decision layer O(schedule); not the physical bottleneck.
  nearby_vehicles:     far-sim O(vehicles) per tick; congestion O(segments).
  frame_time:          in-engine gates run headless (dummy renderer); GPU frame time unmeasured.
  route_query_latency: 4.3 ms/query over 1030 nodes / 2176 directed edges (pure-Python Dijkstra).
  terrain:             64 chunks / 40,960 tris generated in 163 ms (2.55 ms/chunk).
  memory:              bounded — coarse baked heightmap (~115 KB), chunk meshes on demand.

TESTS
  python:   262 pass (147 existing + 115 new), 0 failures.
  in-engine: 3 headless Godot 4.4 gate scenes, 28 checks, 0 failures
             (PhysicsGate 16, RegionGate 8, NavGate 4). Run: godot/tests/run_gates.sh.

KNOWN_LIMITATIONS
  - Visual appearance and interactive play unverified (headless has no GPU; no
    §20 screenshots).
  - GDScript terrain skirts omitted in region_loader (Python mesh has them);
    real DEM acquisition is an offline seam; regional major-road graph not yet baked.
  - Vehicle crash->wreck handoff and citizen<->body bridge are hooks, not wired
    into a full running city scene yet.

NEXT_RECOMMENDED_STEP
  Assemble a full playable city scene wiring the layers together (RegionLoader +
  MobilityLoader + spawned CitizenBody/VehicleBody driven by the Python runtime's
  itineraries + debug_overlay), run it on a GPU to capture the §20 vistas and the
  §19 living-city demo, then port the terrain skirts into region_loader and wire
  the vehicle crash->wreck->MobilityObstruction handoff end to end.
```

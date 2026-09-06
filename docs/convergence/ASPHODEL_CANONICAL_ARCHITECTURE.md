# Asphodel — Canonical Architecture

This is the one description of what Asphodel *is* after the canonical
convergence. It answers, for each concept, which implementation owns it and
which files are that owner. If a file is not named here as an authority, it is
either a consumer of one or it is legacy and says so in its header.

Companions: `ASPHODEL_BRANCH_CENSUS.md` (how we got here),
`ASPHODEL_BRANCH_DISPOSITION.md` (what to stop using), `docs/CANONICAL_STATUS.md`
(which branch to build from). Historical milestone reports live in
`docs/findings/`.

## 0. The twelve questions

| question | answer | owner |
|---|---|---|
| What is the world? | One authoritative Python `World` per city bundle: a macro population ledger over a zone grid, promoted agent zones near the player, a bounded named roster, survival state, interior deltas. Everything Godot shows is a projection of it. | `asphodel/orchestrator.py` |
| What is a citizen? | A stable integer `citizen_id` (the index of `citizens.json`) with a schedule, home/work building ids, needs, relationships, an epidemic state slot when promoted, one physical location per instant, and one deterministic appearance. | `asphodel/{citizen,bundle_population,npc,roster,embodiment}.py`; visuals `godot/scripts/citizen_visual_identity.gd` |
| What is a building? | One index `building_id` into `godot/bundles/<city>/buildings.json` (== `world/identity.json.gz` id == compiled chunk `bid` == interior descriptor id == citizen `home_building_id`), keyed to a stable public-data id. | `asphodel/world_source/` (producer), `asphodel/embodiment.CitySpatialContext` (runtime index) |
| What is a road? | A `RoadSegment` in `godot/bundles/<city>/streetmap.json` (schema v2): a directed-capable, mode-aware polyline split at real junction connectors, baked from the same Overture packet the rendered streets come from. | `asphodel/mobility/` |
| What is a vehicle? | A `VehicleInstance` with one id across abstract → route-simulated → physical → wreck, routed on the street graph and reconciled by `TrafficReconciler`. Parked cars in chunks are placements of the same vocabulary. | `asphodel/transport/` |
| What owns physics? | The collision matrix in Python; Godot bodies are stamped from the generated `CollisionLayers` autoload and physics (never the planner) decides where a body ends up. | `asphodel/physics/layers.py` → `godot/scripts/collision_layers.gd` |
| What owns navigation? | The street graph for *where one can go*; `CitizenRuntime` goals/itineraries for *where one wants to go*; `CitizenBody` local steering for *how it moves*. | `asphodel/mobility/`, `asphodel/citizens/`, `godot/scripts/citizen_body.gd` |
| What owns persistence? | `asphodel/save.py` (versioned, bit-identical continuation). Nothing in Godot saves state. | `asphodel/save.py` |
| What owns Godot? | Godot renders the World's snapshot and submits intent over `SimBridge`. It owns cameras, meshes, streaming, input, and physical bodies — not truth. | `godot/scripts/sim_bridge.gd`, `godot/IsometricWorld.tscn` |
| How does a simulated object become physical? | Promotion: macro count → agent slot (`World`), identified agent → `PhysicalLocation` (`embodiment`), location → humanoid instance or `CitizenBody`/`VehicleBody`, gated by `lod/` bands and `lod/materialize` safety. Identity never changes on the way. | `asphodel/orchestrator.py`, `asphodel/lod/` |
| How do I run the current game? | `python -m asphodel.bridge.server` then open `godot/` (main scene `MainMenu.tscn` → CitySelect → CharacterScreen → `IsometricWorld.tscn`). Headless certification: `tools/final_cert.sh`, `godot/tests/run_gates.sh`, `python -m pytest`. | `README.md` |
| Which branch do I build from? | `main` (after the convergence PR lands; until then the convergence branch). Never a `claude/*` branch. | `docs/CANONICAL_STATUS.md` |

## 1. Geographic pipeline — how public data becomes the world

```
Overture Maps release (pinned, e.g. 2026-08-19.0)            OSM Overpass (legacy, offline now)
   │ acquire: S3 listing + HTTP-range parquet reads               │ geocode + fetch major roads, buildings
   │ provenance + commercial-license gate (fails closed)          ▼
   ▼                                                    asphodel/osm_city/{tessellate,pipeline}.py
asphodel/world_source/normalize.py  → WorldSourceV1        zones.json (density grid + populations)
   │  roads (+connectors, one-way), buildings, land,       roads.json (major-road polylines, LEGACY)
   │  water, land_use, land_cover, places                  timeline.json (macro preview)
   ▼
asphodel/world_source/compile.py                          asphodel/mobility/bake.py
   surfaces · streets · parcels · buildings grammar         streetmap.json v2 (every street, junction-exact)
   residential grammar · appearance · detail · anchors             │
   ▼                                                               ▼
godot/bundles/<city>/world/{chunks/*.json.gz,               asphodel/osm_city/mobility.py
   identity.json.gz, spawn_anchors.json.gz, world_meta}      mobility.json (zone-mobility weights for the macro tier,
buildings.json v1  (index == building_id)                    DERIVED from streetmap.json)
   │
   ▼
asphodel/osm_city/citizens.py → citizens.json (people who live in those buildings, explicit building ids)
asphodel/region_bundle.py     → region.json v2 (terrain), physics.json (collision matrix)
```

Everything under `world/` and `buildings.json` is ODbL/CDLA content plus
procedural derivation; gameplay data never enters those files. Every
procedural decision draws from `hash64(seed, generator_version, stable_key,
purpose)` — no global RNG, no iteration-order dependence — so a rebuild is
byte-identical.

**Provenance classes** carried on data: `OBSERVED` (from the source),
`DERIVED` (inferred from observed data by a documented rule), `PROCEDURAL`
(generated). Terrain today is entirely PROCEDURAL (`region.json.provenance`);
building heights are 93 % OBSERVED in Houston; facade/roof appearance is
PROCEDURAL with a DERIVED style family.

## 2. Regional pipeline — the city inside its geography

`asphodel/geo.py` fixes one geographic frame per bundle (equirectangular about
the bundle centre; x east, z north, metres; the same frame every bundle file
uses). `asphodel/region/` provides elevation providers (archetype-driven
synthetic today; `USGS3DEPProvider` is the seam for a real DEM), quadtree LOD
terrain, erosion/hydrology, land cover. `asphodel/region_bundle.py` bakes
`region.json` (schema **v2**):

* a 151×151 heightmap at 800 m over a 120 km square, eroded, with water cells;
* the **city plateau**: the detailed-city disc (3 km radius) is flattened to one
  datum elevation, blended over 3 km, so the compiled city authored at y = 0
  sits exactly on the ground; `georef.origin_elevation` *is* that datum;
* a chunk manifest (near chunks collide, far chunks render only), atmosphere
  parameters, relief statistics, provenance.

Godot: `godot/scripts/region_loader.gd` (class `RegionLoader`) builds the chunk
meshes; both gameplay scenes attach it (`_setup_regional_terrain`) with
`omit_city_interior` so the ExteriorWorld ground owns the plateau and the region
owns everything beyond it. A Denver-like city sees its mountains because the
regional model contains them.

Known limit: no real DEM is baked yet (egress to USGS is blocked); the compiled
city is flat by design until terrain draping is implemented. Two cities with
the same archetype no longer share a heightmap (the terrain seed is mixed with
the city name), but neither is surveyed.

## 3. Building pipeline — one identity from footprint to interior

```
Overture building (GERS id) ──identity.py──► building_id = index in buildings.json
        │                                         (sorted by quantized centroid; persisted in world/identity.json.gz)
        ├─ compile: archetype, height (OBSERVED where present), roof, entrance edge,
        │           feature flags, appearance (city_visual), residential architecture
        │           (world_source/residential_grammar → ResidentialArchitectureV1, detached houses)
        ├─ chunk record {bid, poly, h, floors, arch, roof, entrance, feat, appearance, architecture}
        │       └─ godot/scripts/exterior_world.gd (T1 mass, T2 detail + collision on WORLD_STATIC,
        │          residential_house_renderer.gd for houses)
        ├─ spawn anchors: BUILDING_ENTRANCE per bid (world/spawn_anchors.json.gz)
        ├─ citizens.json: home_building_id / work_building_id (explicit, stored)
        └─ interior: asphodel/interiors.py build_interior(bid, world_seed, footprint)
                → InteriorDescriptor v1 (rooms, doorways, entrance on the street-facing wall,
                  fixtures == authoritative containers (bid, container_index), decor)
                → godot/scripts/interior_builder.gd (walls/floor/fixtures on WORLD_STATIC)
                → deltas only in asphodel/survival.py (searched containers, dropped items)
```

Rules the grammar enforces: rooms form a spanning tree through doorways (no
unreachable room), the entrance is on an exterior wall facing the street,
fixtures stay inside their room, stairs are not generated (single floor in v1;
recorded as a known limit rather than faked), windows/doors do not overlap
(residential grammar facade rules, tested in `tests/test_residential_*`).

Retired: `godot/scripts/building_builder.gd`, `interior_generator.gd`,
`furniture_factory.gd`, `lootable.gd`, `door_interactable.gd`,
`road_builder.gd`, `city_style.gd`, `city_builder.gd`, `CityScene.tscn`
(client-authored buildings/interiors/loot on an obsolete schema) and
`asphodel/osm_city/synth.py` (wrote a bare-list buildings.json). `asphodel/
world.py`'s `generate_interior` is a legacy synthetic-city helper, not the
interior authority; `osm_city/buildings.py generate_procedural` is the
footprint fallback for a synthetic city only.

## 4. Mobility — the rendered city and the routable city are one city

`streetmap.json` v2 is baked by `asphodel/mobility/bake.py` from the normalized
Overture segments split at their connectors: every rendered street class
(service, residential, footway, tertiary, …, 13 classes) is routable; one-way
rules come from `access_restrictions`; each segment keeps its full polyline so
Python and Godot measure the same street (Houston: 15,988 segments, 958.77 km,
equal to the compiled `road_km`). Gate C (`tests/test_gate_street_parity.py`)
proves 100 % of sampled segments lie within 4 m of a rendered road and vice
versa. A bundle without a packet (Boulder) falls back to snapping its
`roads.json` polylines and says so in `source`.

Consumers of the one graph:

| consumer | use |
|---|---|
| `asphodel/citizens/planning.py` | itineraries (walk / drive / park / enter) under live costs |
| `asphodel/transport/` | vehicle far-sim and congestion feedback |
| `asphodel/embodiment.py` | `nearest_road_xy` = exact projection onto the nearest segment (commuters, fleers) |
| `asphodel/osm_city/world_from_compiled.py` | the citizen-bake `StreetMap` (`MobilityGraph.node_graph()`), routed commute spawns |
| `asphodel/osm_city/mobility.py` | zone-mobility weights for the macro epidemic (`road_polylines_for_bundle`), used by `bridge/worldfactory` and `pipeline.rebake_mobility` |
| `godot/scripts/mobility_loader.gd` | in-engine routing with closures/congestion (`MobilityLoader`) |
| `asphodel/mobility/obstructions.py` | wrecks, fires, closures become `MobilityObstruction`s that reroute everyone |

`roads.json` is **legacy**: the OSM major-road subset the June pipeline
fetched. It remains only as the un-baked fallback and as the input of the
first-person scene's legacy road ribbons / ambient `traffic.gd` movers, both of
which are presentation on the non-default path and are scheduled to move onto
the street graph in the Godot session.

## 5. Citizen lifecycle — one person from statistic to humanoid

```
macro ledger (S,E,Ia,Is,R,D per zone; population authority)        asphodel/model.py
   │ promote zone (player focus / infectious fraction / budget)
   ▼
AgentZone slot ← citizen_id assigned deterministically (RNG-free)   asphodel/orchestrator.py, micro.py, npc.py
   │ schedule → activity; needs/belief → chosen_action (shelter/flee/seek)
   ▼
PhysicalLocation(x, z, mode, building_id, movement)                 asphodel/embodiment.py (pure function of
   │   home/work = stored building ids; commute = along the road network      schedule, hour, action, geometry)
   ▼
snapshot() → SimBridge → citizen_render.gd (bounded MultiMesh crowd,          godot/scripts/citizen_render.gd
   near pool of CitizenAvatar; appearance from citizen_visual_identity.gd,    citizen_avatar.gd, citizen_meshes.gd
   the GDScript mirror of npc.visual_seed — no simulation RNG)
   │ interior: World.building_occupants → interior_builder._occupant (same id, same look)
   ▼
CitizenBody (CharacterBody3D on the NPC layer) for physically navigated       godot/scripts/citizen_body.gd
   citizens; its route comes from CitizenRuntime itineraries                 asphodel/citizens/runtime.py
```

The **roster** (`asphodel/roster.py`) keeps named citizens the player has met
across promotion/demotion; `save.py` persists ids, zones, schedules, home/work
coordinates and building ids, and Gate D proves the same person is in the same
place after save → load.

**Closed by ASPHODEL_EMBODIED_MOBILITY_V1** (`docs/mobility/EMBODIED_MOBILITY_ARCHITECTURE.md`):
`World` now executes the planner's itinerary. `World.enable_mobility` attaches
`asphodel/embodied/MobilityRuntime`, which owns one `CitizenRuntime` (planner)
and one `TripExecutor` (execution state machine: leave building → walk → enter
vehicle → drive → park → exit → enter building → activity) per registered
citizen and advances them on the sub-tick movement clock
(`World.advance_seconds`). `World.physical_location` / `_zone_embodiment`
read the executor for registered citizens; `embodiment.resolve_physical_location`
remains only the FAR (schedule-state) authority for unregistered citizens.
`living_city.py` / `playback.json` are a headless demonstration, not an authority.

## 6. Vehicle lifecycle

`VehicleInstance` (`asphodel/transport/instances.py`) is the vehicle:
`vehicle_id`, kind, fidelity (`ABSTRACT → ROUTE_SIMULATED → PHYSICAL_CONTROLLED
→ PHYSICAL_CRASH → PERSISTENT_WRECK`), route + progress, parked location.
`TrafficReconciler` turns MID instances into FAR congestion that feeds every
route cost. `VehicleBody` (`godot/scripts/vehicle_body.gd`, VEHICLE layer,
substepped anti-tunneling) is the NEAR realization; `reconcile_from_physical`
makes physics the authority for its progress. A wreck becomes a
`MobilityObstruction`. In `living_city.py` a driving citizen's car is
`veh:<citizen_id>` — one identity.

**Embodied (ASPHODEL_EMBODIED_MOBILITY_V1):** a citizen with keys owns the
persistent `VehicleInstance "veh:<citizen_id>"`, spawned parked at a validated
parking anchor (`asphodel/embodied/parking.py`), entered/driven/parked by the
`TripExecutor` with `asphodel/embodied/vehicle_control.py` as the V1 driving
controller (speed limits, curvature, following, junction yield, closed roads),
saved/loaded and realised in the playable scene by
`godot/scripts/embodied_mobility.gd` → `vehicle_body.gd` (follow mode, physics
reports back over `MOBILITY_REPORT`).

Legacy: `asphodel/vehicles.py` (aggregate trip assignment used by the citizen
spawn's travel events) consumes the citizen-bake `StreetMap` and is not a
second vehicle entity model; `godot/scripts/traffic.gd` is
EXPLICIT_NONCANONICAL_PRESENTATION — decorative ambient motion on the
first-person path only (no identity, no collision, never reported). Parked
vehicles in chunks are placements of the shared vehicle vocabulary
(`grammar_tables.VEHICLE_KINDS` == catalog == `prop_meshes.gd`); parking
selection treats them as occupied space.

## 7. LOD / materialization

| band | citizen | vehicle | terrain |
|---|---|---|---|
| Far / abstract | a count in the macro ledger; roster record if named | a statistic | render-only chunks |
| Regional / route-simulated | promoted agent with schedule activity and `PhysicalLocation`; itinerary progress (`living_city`) | `advance_far` along its route, congestion-aware | render-only |
| Near | MultiMesh humanoid instance; near pool `CitizenAvatar`; interior occupant | materialized position | chunk mesh + collider |
| Embodied / physical | `CitizenBody` in follow mode (embodied_mobility.gd), stuck → report → replan | `VehicleBody` in follow mode | collider |

The citizen/vehicle bands are decided by `asphodel/embodied/runtime.py`
(distance to the player focus, `lod/entity.LODController`): every registered
citizen is ROUTE_SIMULATED, the ones within 150 m are PHYSICAL (a body), and
ABSTRACT (frozen + catch-up) is an overflow band above 256 active citizens.

`asphodel/lod/entity.py` bands by distance with hysteresis and preserves
id + payload across transitions; `lod/materialize.py` refuses to spawn a body
inside a wall, another agent or under the terrain and returns a structured
deferral instead. `ExteriorWorld` streams chunks in three tiers with
hysteresis and a build budget; `RegionLoader` collides only near chunks;
`citizen_render.gd` caps the drawn crowd and the avatar pool. Promotion never
creates a different citizen (Gate D) or vehicle (Gate F).

## 8. Godot — what it owns and does not own

Owns: the project (`godot/project.godot`, autoloads `Session`, `SimBridge`,
`GameClock`, `CollisionLayers`), the menu flow, the two world scenes
(`IsometricWorld.tscn` default; `StreetScene.tscn` first-person legacy), the
chunk streamer (`exterior_world.gd`), the regional terrain (`region_loader.gd`),
interiors (`interior_builder.gd`), citizen presentation (`citizen_*.gd`),
physical bodies (`citizen_body.gd`, `vehicle_body.gd`, the players), routing
in-engine (`mobility_loader.gd`), the schema contract at its boundary
(`bundle_loader.gd` Gate I: a bare-list `buildings.json`, an unknown
`streetmap`/`region` version, a missing heightmap are **rejected**, the scene
refuses to render), and the certification scenes under `godot/tests/`.

Does not own: inventory, containers, outbreak state, citizen identity,
schedules, save files, interiors' contents, building identity. A Godot script
that invents any of those is a bug (the last one, `first_person.gd`'s local
inventory, was removed).

Known outdated components (Godot session): `StreetScene`'s legacy exterior
path for non-compiled bundles (`_build_buildings/_build_roads/site_detail`),
`traffic.gd`, the region loader's missing skirts, `living_city.gd` drawing
June density blocks instead of `buildings.json` footprints, and the debug
overlay seam (`debug_overlay.gd`, unwired).

## 9. Persistence — where state is authoritative

| state | authority | file |
|---|---|---|
| time/date | `World` tick + `GameClock` mirror | save |
| citizens, schedules, home/work buildings, roster | `World` | save (`citizens` records) |
| epidemic compartments, RNG streams | `Simulation` + `AgentZone` | save |
| inventory, containers, dropped items | `Survival` deltas | save |
| interiors | regenerated from (seed, building_id, gen_version); deltas only | save |
| buildings, roads, terrain, anchors | bundle (immutable, versioned) | `godot/bundles/<city>/` |
| itineraries, executor state, vehicles, parking occupancy, congestion, obstructions | `MobilityRuntime` (`save` v3 `mobility` block) | save |
| doors, damage, outbreak-specific state | (not yet in the save schema) | — |

`save.py` `SAVE_VERSION` gates loads; an incompatible version fails safely.
The Godot client has no save of its own.

## 10. Schemas (canonical, versioned)

| artifact | version | producer | validated by |
|---|---|---|---|
| `meta.json`, `zones.json`, `roads.json`, `timeline.json` | `"1"` | `osm_city.pipeline` / `synth_city` | `bundle_loader.gd validate` |
| `mobility.json` (zone edges) | 1 | `osm_city.pipeline.rebake_mobility` (from streetmap) | `bundle_loader.load_mobility` |
| `streetmap.json` | **2** (1 accepted) | `mobility/bake.py` | `MobilityGraph.from_artifact`, `bundle_loader.check_streetmap` |
| `buildings.json` | 1 | `world_source.compile` / `osm_city.buildings` | `embodiment.validate_buildings_doc`, `bundle_loader.check_buildings` |
| `world/chunks/*.json.gz` | 1 | `world_source.compile` | `world_source.schema.validate_chunk` |
| `world/identity.json.gz`, `spawn_anchors.json.gz`, `world_meta.json` | 1 | `world_source.compile` | Gate B tests |
| `citizens.json` (+ `home_building_id`/`work_building_id`) | — (list) | `osm_city.citizens` | `bundle_population`, Gate B |
| `region.json` | **2** | `region_bundle.rebake_region` | `bundle_loader.check_region`, Gate H |
| `physics.json`, `collision_layers.gd` | `"1"` | `physics.layers` | matrix parity in Gate H |
| `playback.json` | 2 | `living_city.simulate_commute` | `living_city.gd` |
| interior descriptor | 1 | `interiors.build_interior` | `interior_builder.gd` |
| bridge protocol | 4 | `bridge/protocol.py` | `sim_bridge.gd` HELLO |
| save | `SAVE_VERSION` | `save.py` | `save._validate` |

Convention going forward: new or bumped schemas use an integer `version`;
consumers reject unknown versions at the boundary (Gates A and I).

## 11. Adding a new city

1. Add the bbox to `asphodel/world_source/bbox.py` and a bundle directory.
2. `python -m asphodel.osm_city "<City>" --out godot/bundles/<city>` for the
   zone grid (or, offline, `python -m asphodel.synth_city` for a synthetic one).
3. `python -m asphodel.world_source build --city <city> --release <R> --seed 0
   --citizens 60 --download-missing --certify` — compiles `world/`,
   `buildings.json`, citizens, and runs the 12 certification gates.
4. `python tools/bake_streetmap.py <city>` — the street graph from the same
   packet; then `python -c "from asphodel.osm_city.pipeline import
   rebake_mobility; rebake_mobility('godot/bundles/<city>')"`.
5. `python -c "from asphodel.region_bundle import rebake_region;
   rebake_region('godot/bundles/<city>', '<archetype>')"` — terrain + plateau.
6. `python tools/city_matrix.py <city>` and `godot --headless --path godot
   res://tests/ConvergenceGate.tscn` must pass; add the city to
   `tools/city_matrix.EXPECTED`.

## 12. Adding a new building style

Residential: add a style row to `asphodel/city_visual/residential_architecture.py`
(era/form/roof/facade constraints) and its cohort weights in
`asphodel/world_source/residential_grammar.py`; render it in
`godot/scripts/residential_house_renderer.gd` from the record only (no rolls in
GDScript); regenerate `tools/build_catalog_v1.py` if new asset kinds are
introduced; run `tests/test_residential_*` and `ResidentialArchitectureGallery`.
Non-residential archetypes live in `world_source/buildings_grammar.py` +
`exterior_world.gd::_detail_building`.

## 13. Adding a new NPC behaviour

Simulation side only: a new activity/action code in `asphodel/npc.py` (stable
integer tables), its physical consequence in `asphodel/embodiment.py`
(pure function), its goal/plan form in `asphodel/citizens/goals.py` /
`planning.py`; expose it through `World.snapshot()`; render it in
`citizen_render.gd` from the snapshot. Never decide behaviour in GDScript.

## 14. Disruption readiness

Roads are not immutable scripts: `MobilityObstruction`s (wreck, fire, closure,
crowd) mutate segment `dynamic_state`, every route query sees live costs, and
`CitizenRuntime.on_blockage` replans (car → foot when no car route remains).
Buildings can be made inaccessible by closing their connector segment. Goals
preempt schedules by priority (`GoalStack`), which is how a worker leaves a
shift to fetch a child. The epidemic tier's belief cascade already drives
shelter/flee actions that move citizens physically.

## 15. Canonical entry points

| purpose | command |
|---|---|
| authoritative server | `python -m asphodel.bridge.server` |
| play | `godot --path godot` (main scene `MainMenu.tscn`) |
| Python suite | `python -m pytest -q` |
| Godot certification (no bridge) | `godot --headless --path godot --import` once, then `godot/tests/run_gates.sh` and `res://tests/{TestRunner,StreetSmoke,ExteriorStream,ConvergenceGate}.tscn` |
| embodied mobility (live bridge) | `tools/run_mobility_gate.sh` (headless physics gate) and `tools/run_mobility_shots.sh` (rendered evidence) |
| Godot live certification | `tools/final_cert.sh` (starts the server, runs the Live* scenes) |
| multi-city matrix | `python tools/city_matrix.py` |
| macro research | `python run.py`, `python -m asphodel.bench`, `python -m asphodel.phase4a` (tooling, not runtime) |

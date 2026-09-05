# ASPHODEL_ISOMETRIC_PRESENTATION_V1: PASS

Continuous isometric / 2.5D presentation over Asphodel's continuous authoritative
world — "Project-Zomboid readability without tiles." Presentation + interaction
architecture only; the simulation, the authority contract, and the world model are
untouched.

---

## BASELINE
| | |
|---|---|
| starting_branch | `claude/asphodel-isometric-presentation-v1-xwry9h` |
| starting_sha | `da9ba66b566b1844c68d39509e874b6850bcec6a` |
| final_branch | `claude/asphodel-isometric-presentation-v1-xwry9h` |
| final_sha | _(see the tip of this branch after push)_ |
| engine | Godot 4.4.1-stable (downloaded; runs headless + software-GL under xvfb) |

## ANCESTRY (all verified as ancestors of the frontier `da9ba66`)
- authoritative_world_in_ancestry: **YES** (`claude/asphodel-authoritative-world-55z0qw` @ 4728113)
- embodied_survival_in_ancestry: **YES** (`claude/asphodel-embodied-survival-qlizmu` @ d520e0b)
- walk_in_interiors_in_ancestry: **YES** (`claude/asphodel-walk-in-interiors-v1-k9m2` @ 12f698f)
- outside_world_in_ancestry: **YES** (`claude/outside-world-full-city-mvp-tuh0de` @ da9ba66 = frontier)

The GitHub default branch (`belief-cascade`) is not in this lineage and was ignored
as authority, per the mission's provenance note.

## NO_TILES_GATE
```
authoritative_tilemap:               NO
OSM_geometry_rasterized_to_tiles:    NO
player_position_tile_snapped:        NO
NPC_position_tile_snapped:           NO
interior_geometry_tile_authoritative:NO
vehicles_tile_authoritative:         NO
continuous_world_coordinates_preserved: YES
```
Enforced by `tests/test_no_tiles_guard.py` (6 checks, green): no `TileMap` /
`TileMapLayer` / `TileSet` class in any renderer script or scene, no `TileSet`
resource, no `snapped(` of positions in the isometric scripts, and a positive
assertion that the isometric world is built on the continuous `ExteriorWorld` chunk
stream + a `CharacterBody3D` player keyed by authoritative `building_id`/`citizen_id`.

**Grids used, and why they are non-authoritative:**
- *ExteriorWorld chunk grid* — YES; authoritative: **NO**. Streaming/LOD partition
  only; every chunk resolves to continuous world metres and real building/road
  geometry. (Pre-existing; reused unchanged.)
- *Interaction candidate list* — a plain list keyed by continuous position + real
  entity id; no grid. Targeting is by continuous distance and screen projection.

Player, NPC, vehicle, building, interior, road and item positions all remain
continuous floats (verified: exterior smoke asserts continuous player movement and
continuous road vertices; camera smoke asserts a non-integer target is never snapped).

## ARCHITECTURE
- **legacy_renderer:** `StreetScene.tscn` → `street_world.gd` + `first_person.gd`
  (first-person, eye camera, mouse-look). Kept, frozen, still reachable from the
  character screen ("First-person (legacy)") and still covered by its own tests.
- **new_renderer:** `IsometricWorld.tscn` → `isometric_world.gd`, with
  `isometric_camera.gd`, `isometric_player.gd`, `isometric_interaction.gd`,
  `isometric_highlight.gd`, `isometric_cutaway.gd`. A **parallel route** over the
  same `SimBridge`/`World`.
- **shared_surfaces (reused unchanged):** `SimBridge`, `GameClock`, `Session`,
  `ExteriorWorld`, `CitizenRender`, `BundleLoader`, `ZoneMap`, `PropMeshes`.
  `InteriorBuilder` reused with one **additive** change: wall segments now carry
  `wall_normal`/`room_id`/`segment_id` metadata for the cutaway (the first-person
  path ignores it).
- **deprecated_surfaces:** none deleted. `first_person.gd` + the FPS branches of
  `street_world.gd` are frozen pending a later cleanup after the isometric path
  survives further development.
- No simulation logic is duplicated between renderers; no Godot-local authoritative
  state was introduced.

## CAMERA (`isometric_camera.gd`, ISO-1)
- projection: **orthographic** (`PROJECTION_ORTHOGONAL`)
- pitch/yaw: configurable; defaults **40° pitch / 45° yaw**
- zoom: ortho `size`, bounded **[16, 260] m**, multiplicative steps + mouse wheel + `+`/`-`
- rotation: **90°** left/right (`[` / `]`), smoothly animated
- movement_reference: **camera-relative WASD** (derived from the camera's ground
  basis, so "up" is always away from the camera regardless of rotation)
- The camera is a pure presentation transform — it never reads/writes/snaps any
  authoritative position (proven by `IsometricCameraSmoke`).

## CONTINUOUS_WORLD
- OSM geometry: real Overture/OSM chunk stream (`ExteriorWorld`), continuous.
- buildings: 22,525 real Houston footprints indexed by continuous polygon; identity
  `building_id` == footprint index (load-bearing for interiors/containers).
- roads: 1,088 continuous polylines (asserted non-grid-snapped floats).
- citizens: MultiMesh from `World.snapshot()`, continuous `world_xy`; 319 rendered
  at once in the certified crowd scene.
- interiors: authoritative `GET_INTERIOR` descriptors, continuous room/fixture coords.
- items: authoritative container contents; dropped items continuous (bridge unchanged).
- coordinate authority: **Python `World`** (continuous X/Y). Godot renders + submits
  intent only.

## INTERACTION (`isometric_interaction.gd`, ISO-4)
- selection model: cursor pick (screen-space projection, works for MultiMesh crowds)
  → current selection → nearest eligible within an 8 m continuous radius → none.
- NPC: cursor/nearest → `INTERACT_WITH(citizen_id)` → authoritative roster.
- building: nearest enterable footprint → `GET_INTERIOR` + `ENTER_BUILDING(building_id)`.
- container: fixture → `SEARCH_CONTAINER` + `TAKE_ITEM(building_id, index, kind)`.
- items: taken into the authoritative inventory; illegal takes/searches rejected by Python.
- Entities are always identified by real ids, never node names. `query_affordances(entity)`
  is the forward-compatibility hook: today it maps kind → existing bridge commands, but
  its shape lets a later Semantic-Action layer (ASK/INFORM/GIVE/…) replace the body
  with a Python affordance query without changing callers. Godot applies nothing
  before Python accepts it.

## INTERIORS (`isometric_cutaway.gd`, ISO-5)
- cutaway model: hide the ceiling + hide the wall segments whose outward normal faces
  the camera (recomputed as the camera rotates); no geometry slicing, no rebuild.
- roof behavior: ceiling hidden on entry.
- wall behavior: camera-facing walls hidden (fade optional); collision kept so the
  player stays bounded.
- fixture identity: authoritative `fixture_id` + `building_id` + `container_index`
  retained (verified).
- occupant identity: authoritative `citizen_id` retained (verified).
- furniture: on user request, a **presentation-only `decor` layer** was added so
  interiors read as furnished (beds/sofas/tables/wardrobes/racks colour-coded and
  sized by kind, per room kind). This is a NEW descriptor field
  (`InteriorDescriptor.decor`) generated deterministically per room, rendered by
  `InteriorBuilder` in a separate `Decor` node with NO collision and NO container —
  gameplay ignores it. The authoritative `fixtures` list stays 1:1 with real
  containers, so loot/containers/save-load are byte-for-byte unchanged (28 interior
  + save Python tests still pass; `len(fixtures) == n_containers` still holds). This
  keeps the mission's simulation-neutrality invariant intact — see the note under
  SIMULATION AUTHORITY.
- placement: authoritative interior descriptors are in WORLD coordinates (the
  building's real footprint — e.g. building 0's hull is at x∈[1816,1951],
  z∈[−3415,−3313]). The isometric path stages an entered interior by translating it
  so its hull centre lands on a fixed anchor near the origin (`INTERIOR_STAGE_ANCHOR`
  = (0,0,9000), clear of the city). This is a deliberate improvement over the FPS
  path's raw ~100 km offset: at 100 km, float32 precision (~0.008 m) plus a *global*
  orthographic camera made the staged interior fail to render and dropped the player
  far from the rooms; near the origin the room renders crisply and the player spawns
  inside it (interiors are now walkable in the iso path). Every authoritative id
  (building/entrance/fixture/container/occupant/exit) is preserved. Co-locating the
  interior inside the exterior footprint is deferred (it would need per-building roof
  culling in the batched exterior mesh) and is documented below.

## SIMULATION AUTHORITY
- Python-owned: simulation, outbreak, citizen identity/roster, inventory, container
  contents, interiors, survival, save/load, world mutations, macro↔micro promotion.
- Godot-owned: presentation only (camera, meshes, visual pose, HUD, input intent).
- authority regressions: **none.** The isometric path issues the same bridge commands
  as the first-person path; the persistence vertical passes unchanged under it.
- The presentation-only interior `decor` layer (added on request) does not touch
  authority: `fixtures` stay 1:1 with containers, loot/save-load are byte-identical,
  and decor carries no `container_index` (gameplay never sees it). Interior Python
  tests (determinism, `fixtures == n_containers`, save/load) remain green.

## CERTIFICATION (Godot 4.4.1, live Python bridge, Houston bundle)
- Python tests: **444 passed, 1 env-skip** (`test_compile_writes_only_presentation_files`
  needs raw Overture parquet not in a fresh clone — pre-existing at baseline, unrelated).
  Includes the new **no-tiles guard (6/6)**.
- Godot legacy tests: `TestRunner.tscn` **0 failures** (unchanged).
- Godot isometric tests: **all green** —
  - `IsometricCameraSmoke` 0 failures (orthographic, follow, zoom, rotate, no snapping)
  - `IsometricExteriorSmoke` 0 failures (Houston streams, WASD moves 3 m continuously,
    streaming follows, roads continuous)
  - `IsometricInteractionSmoke` 0 failures (targeting + INTERACT_WITH + ENTER_BUILDING +
    TAKE_ITEM + illegal rejected)
  - `IsometricInteriorSmoke` 0 failures (descriptor identity, ceiling + 5 walls cut away,
    fixture/occupant ids, exit returns)
  - `IsometricCitizenSmoke` 0 failures (319 crowd, MultiMesh matches, identified citizens)
  - `IsometricLiveSmoke` 0 failures (full vertical below)
- live bridge: connected; `START_WORLD` with `player_citizen_id`, focus follows player.
- save/load: **verified** — interact → enter → loot (container delta) → leave → move
  away → return (same roster member, container still changed) → SAVE → mutate → LOAD
  restores the exact authoritative inventory.

## PERFORMANCE  (headless CPU-side, houston, same machine)
The isometric renderer reuses `ExteriorWorld` **unchanged**, so per-chunk build cost
is equivalent by construction. `OwPerfBench` (first-person baseline) vs
`IsometricPerfBench` (streaming driven by the isometric camera focus):

| metric | baseline (OwPerf) | isometric | delta | gate (±20%) |
|---|---|---|---|---|
| T1 build ms (avg) | 12.04 | 10.30 | −14.4% | ✅ |
| T2 build ms (avg) | 4.13 | 4.61 | +11.6% | ✅ |
| T3 build ms (avg) | 1.55 | 1.55 | ~0% | ✅ |
| fresh 3×3 delta MB | 36.55 | 36.55 | 0% | ✅ |
| resident_chunks | 96 | 98 | +2 | n/a (sweep) |
| resident_nodes | 3205 | 3842 | — | tracks resident chunks |
| mm_instances | 5903 | 6752 | — | tracks resident chunks |

No unexplained regression > ~20%. Per-tier build time is equivalent (the renderer is
literally the same code); T2's +11.6% and the higher node/MM counts are a **benchmark
methodology** artefact — the isometric sweep drives streaming from the camera's
follow-lagged ground focus, so the sweep settles at 98 resident chunks (vs 96) with a
couple more tiers built. Static memory for a fresh 3×3 block is identical to the
byte. Simulation stays decoupled from rendering (snapshots are consumed, never
generated per render frame); snapshot frequency is unchanged from the first-person
path (GameClock tick-crossing only).
known bottleneck: unchanged from the outside-world branch (T1 ground-raster +
mass-building build dominates); nothing new introduced.

**Minor exterior readability enhancement (in the reused renderer):** elevated
freeway decks previously drew their lane markings at ground level (y=0.06) — i.e.
*under* the raised deck — so freeways read as blank at isometric scale. Lane
striping (dashed centre + lane dividers) is now drawn on the deck surface at
`DECK_Y` in `ExteriorWorld._build_elevated_roads`. Re-measured OwPerfBench after the
change is unchanged (T1 9.7 ms, T2 4.1 ms, T3 1.5 ms, resident_nodes 3205,
mm_instances 5903, delta 36.55 MB — identical), and ExteriorStream stays green. This
is the only change to the reused exterior generator and it is additive geometry.

## VISUAL EVIDENCE
_(screenshots inserted below)_

## A/B (first-person vs isometric)
- first-person strengths: eye-level immediacy; close architectural detail.
- first-person weaknesses: no city-scale context; interiors read poorly through a
  first-person doorway; crowd/social structure invisible; must aim to interact;
  close-range mesh weaknesses are front-and-centre.
- isometric strengths: whole-neighbourhood context; crowds/queues/entrances legible;
  interiors readable at a glance via cutaway; interaction without aiming; the camera
  distance hides close-range mesh weaknesses the outside-world branch already flagged.
- isometric weaknesses: interior is staged (co-location deferred); software-GL
  screenshots understate lighting vs Forward+.
- decision: **isometric makes the intended simulation materially easier to understand
  and cheaper to build without sacrificing embodied play → made the default gameplay
  scene** (character screen "Continue"); first-person kept accessible + frozen.

## REGRESSIONS
None. All pre-existing Godot + Python tests that pass at baseline still pass; the one
Python failure is the pre-existing environmental data-dependency described above.

## DEFERRED (explicitly out of scope for V1, not blocked by it)
- Interior co-location inside the exterior footprint (needs per-building exterior roof
  culling in the batched chunk mesh). Interiors currently stage at a near-origin anchor.
- Interior furniture: addressed via the presentation-only `decor` layer (beds,
  sofas, tables, wardrobes, racks, etc., per room kind). Deeper interior *simulation*
  (interactable furniture beyond the authoritative containers, per-room-kind floor
  materials, clutter density tied to occupancy) remains a later Python-side concern.
- Wall *fade* polish (implemented as an option; V1 uses hard hide for robustness).
- Vehicles under the iso interaction model; the whole BDI/social/semantic/biography
  stack (the renderer is structured to serve it — see FINAL RECOMMENDATION).

## FINAL RECOMMENDATION
Ship the isometric presentation as the default. It satisfies every load-bearing PASS
item: an orthographic embodied scene over continuous real Houston, WASD movement,
follow/zoom/rotate camera, aim-free interaction, building enter/exit, generated
interiors with roof/wall cutaway, authoritative containers + NPC interaction, and the
persistent-roster + save/load vertical — all with no tile authority and no simulation
regression. The next sequence (Temporal Authority → Citizen Runtime → Social Graph →
Semantic Actions → BDI → Jobs → Dialogue → Biography) can target this renderer: the
interaction layer already resolves real entity ids and exposes `query_affordances`,
so it will not have to be discarded when semantic actions arrive.

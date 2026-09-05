# Asphodel — Branch Census (canonical convergence)

Census date: 2026-09-05. Every ref under `refs/remotes/origin/` was enumerated
with `git for-each-ref`; nothing below was taken from prose in the repository.
Merge bases, ahead/behind counts and unique-commit lists were computed with
`git merge-base`, `git rev-list --left-right --count` and `git log A..B`;
"already exists elsewhere" claims were checked by blob SHA (`git ls-tree`) or by
`git grep <symbol> <sha>`.

## Reference points

| ref | SHA | note |
|---|---|---|
| GitHub default branch at session start | `claude/asphodel-belief-cascade-kvKKv` @ `35d0c86` | June 12 2026, the divergence point of every modern line; **stale** |
| Prior consolidation ("unified") branch | `claude/asphodel-houston-scene-outdated-k9aetu` @ `57ef86a` | identical to `origin/main` |
| `origin/main` | `57ef86a` | pushed Sep 4 2026, open PR #3 (`main` → belief-cascade, backwards) |
| Selected spine | `origin/main` @ `57ef86a` | see §"Spine selection" |
| Convergence branch | `claude/asphodel-canonical-convergence-i6h105` | starts as `main` + merge of the regional line |

## The real topology

The seventeen `claude/*` branches are not seventeen parallel realities. Thirteen
of them are **points on one linear chain** that was built branch-on-branch from
August 19 to September 4 and already sits inside `main`:

```
35d0c86 (June default) ─┬─ cc671fd gameplay-integrity
                        │  └ 4728113 authoritative-world
                        │     └ d520e0b embodied-survival
                        │        └ 12f698f walk-in-interiors
                        │           └ da9ba66 outside-world-full-city-mvp
                        │              └ cab278e isometric-presentation
                        │                 └ 477b902 city-assets-visual-identity ─┬─ 270708f residential-architecture
                        │                                                        └ d056d54 humanoid-npc ──┐
                        │                          3dcaaa9 merge humanoid ◄──────────────────────────────┘
                        │                          cc91f18 Houston re-bake
                        │  97bf96b city-streets-building-interiors (from cc671fd) ──┐
                        │                          57ef86a = main = houston-scene-outdated ◄┘
                        ├─ c1e1bec project-zomboid-lessons (6 doc commits, replayed into main)
                        └─ b5cf43a regional-physics-navigation (16 commits) ── NOT in main
   a06f865 ─ bc34bfe outbreak-config-types (1 commit, June)              ── NOT in main
   df5e7ef ─ 4b715a2 scenario-engine-flux (5 commits, May)               ── NOT in main
```

So the convergence problem is precisely: **`main` (89 commits, 2,666 files) versus
the regional-physics-navigation line (16 commits, 229 files)**, plus two small
June-era branches that touch the macro epidemic model, plus a doc-only branch
whose content main already carries.

## Per-branch census

Columns: HEAD, merge-base with `main`, behind/ahead of `main`, unique commits,
what the unique work touches, whether it already exists in the convergence tree,
classification. "Systems" names the Python packages / Godot scenes the branch
introduced *at the time* (all of it is now inside `main` unless stated).

| # | branch | HEAD | merge-base(main) | behind / ahead | unique | systems / schemas / scenes / tests introduced by the branch | exists in convergence tree? | classification |
|---|---|---|---|---|---|---|---|---|
| 1 | `claude/asphodel-belief-cascade-kvKKv` (GitHub default) | `35d0c86` | itself | 89 / 0 | 0 | Phase 3a–8 macro/micro core (`model.py`, `micro.py`, `orchestrator.py`), OSM city pipeline v1 (`osm_city/`), June Godot menu flow + `CityScene`, citizen spawn configs, Madisonville selector | yes (ancestor) | **SUPERSEDED** (stale default; ancestor of everything) |
| 2 | `claude/citizen-spawn-configs-K4iZW` | `5a32177` | itself | 124 / 0 | 0 | `citizen.py` spawn catalog, environmental events | yes (ancestor of #1) | **ALREADY_CONTAINED** |
| 3 | `claude/scenario-engine-flux-yXt1w` | `4b715a2` | `df5e7ef` (May 29) | 132 / 5 | 5 | Phase 4b research harness: `engine.py` (ensembles/sweeps), `scenario.py` (`Scenario` object), `metrics.py`, `episodes.py` (run-to-termination), `flux.py` (multi-zone micro flux), `phase4b.py`; 4 `scenarios/scn_*.yaml`; 3 tests | **no** — none of the six modules exist at any later SHA; the inter-zone flux concern was re-solved by Phase 5's orchestrator (`orchestrator.py` reconcile step) | **SUPERSEDED** (flux) + **EXPERIMENT_ONLY** (ensemble/sweep/episode harness); see disposition |
| 4 | `claude/outbreak-config-types-A8fTw` | `bc34bfe` | `a06f865` (Jun 1) | 126 / 1 | 1 | Zombie genome archetypes (`classic_shambler`, `rage_virus`, `cordyceps`, `necro_latent`), `PathogenGenome` reanimation fields, macro `U` (undead) and `C` (corpse) compartments in `model.py`, `run.py --archetype`, 4 scenario YAMLs, `tests/test_outbreak_types.py` | **no** — `git grep reanimation\|GENOME_ARCHETYPES\|undead 6cd5a2b` is empty; the macro ledger is still S,E,Ia,Is,R,D | **REQUIRES_ARCHITECTURAL_DECISION** (adds compartments the micro tier, save schema, snapshot wire and calibration do not know) — see disposition |
| 5 | `claude/project-zomboid-lessons-mwoke7` | `c1e1bec` | `35d0c86` | 89 / 6 | 6 | docs only: PZ lessons, NPC precedent research, Phase 11 design + SP1–SP3 TDD plans | **yes, byte-identical** (all six blobs match; `git cherry` marks all six as upstream-equivalent; main also carries the implementations M2–M4) | **ALREADY_CONTAINED** |
| 6 | `claude/asphodel-gameplay-integrity-de72g6` | `cc671fd` | itself | 82 / 0 | 0 | real-road zone-mobility graph (`osm_city/mobility.py`, `mobility.json`), authoritative GameClock/outbreak/pause in Godot, citizen spawn on the real city, `tests/test_gameplay_integrity.py`, `test_mobility.py`; first headless Godot certification | yes | **ALREADY_CONTAINED** |
| 7 | `claude/asphodel-authoritative-world-55z0qw` | `4728113` | itself | 55 / 0 | 0 | M0–M6: live Python↔Godot bridge (`bridge/`), citizen identity + schedule activity (`npc.py`), reactive affordances, named roster (`roster.py`), deterministic save/load (`save.py`), living-city renderer (`citizen_render.gd`), extruded footprints, road network, traffic, site detail, `docs/CANONICAL_STATUS.md` | yes | **ALREADY_CONTAINED** (was the canonical line before this session) |
| 8 | `claude/asphodel-embodied-survival-qlizmu` | `d520e0b` | itself | 50 / 0 | 0 | P1 canonicalization, P2 physical embodiment (`embodiment.py`, `PhysicalLocation`), P3 survival loop (`items.py`, `survival.py`), Gate 0 in-engine closure | yes | **ALREADY_CONTAINED** |
| 9 | `claude/asphodel-walk-in-interiors-v1-k9m2` | `12f698f` | itself | 45 / 0 | 0 | `interiors.py` descriptor + generator, `interior_builder.gd`, walk-in streaming in `street_world.gd`, interior NPC occupancy, `GET_INTERIOR` protocol v3, Live* certification scenes, save v2 | yes | **ALREADY_CONTAINED** |
| 10 | `claude/outside-world-full-city-mvp-tuh0de` | `da9ba66` | itself | 37 / 0 | 0 | `world_source/` (Overture acquisition, provenance, normalize, identity, compiler, streets, parcels, detail, certify), compiled `world/` chunk stream + `exterior_world.gd`, regenerated `buildings.json` schema `{poly,height,key,arch,cat}`, `world_from_compiled.py`, spawn anchors | yes | **ALREADY_CONTAINED** |
| 11 | `claude/asphodel-isometric-presentation-v1-xwry9h` | `cab278e` | itself | 32 / 0 | 0 | `IsometricWorld.tscn` + isometric camera/player/interaction/cutaway/highlight, no-tiles guard, exterior batches 1–5 | yes | **ALREADY_CONTAINED** |
| 12 | `claude/city-assets-visual-identity-v1` | `477b902` | itself | 8 / 0 | 0 | `city_visual/` (asset catalog v1, appearance inference, business identity, city profile), `prop_meshes.gd`, `furniture_meshes.gd`, vehicles/fences/parking/vegetation, appearance provenance in chunks | yes | **ALREADY_CONTAINED** |
| 13 | `claude/residential-architecture-grammar-v1-kx5hpz` | `270708f` | itself | 5 / 0 | 0 | `world_source/residential_grammar.py`, `city_visual/residential_architecture.py` (`ResidentialArchitectureV1`), `residential_house_renderer.gd`, gallery + screenshots | yes | **ALREADY_CONTAINED** |
| 14 | `claude/asphodel-humanoid-npc-v1-j8o8sb` | `d056d54` | itself (2nd parent of `3dcaaa9`) | 7 / 0 | 0 | `citizen_visual_identity.gd`, `citizen_meshes.gd`, `citizen_avatar.gd`, humanoid `citizen_render.gd`, `citizen_material.gdshader`, humanoid smoke/gallery | yes | **ALREADY_CONTAINED** |
| 15 | `claude/city-streets-building-interiors-55xxq9` | `97bf96b` | itself (2nd parent of `57ef86a`) | 88 / 0 | 0 | An older parallel take (from `cc671fd`, Aug 23): OSM-true street ribbons (`road_builder.gd`), footprint extrusion + client-generated interiors and loot (`building_builder.gd`, `interior_generator.gd`, `furniture_factory.gd`, `lootable.gd`, `door_interactable.gd`, `city_style.gd`), `osm_city/synth.py`, a `buildings.json` in the obsolete `{footprint,kind,storeys}` shape | contained by SHA; 15 files landed unchanged, 13 were overridden by main, `first_person.gd` was blended (Godot-local inventory) | **SUPERSEDED** — the seven scripts and `synth.py` are dead second implementations; retired in this convergence (see disposition) |
| 16 | `claude/asphodel-houston-scene-outdated-k9aetu` | `57ef86a` | itself | 0 / 0 | 0 | the prior consolidation attempt = `main` | yes (it *is* the spine) | **CANONICAL_SPINE** (as `main`) |
| 17 | `claude/asphodel-regional-physics-navigation-v1-1bpcqs` | `b5cf43a` | `35d0c86` | 89 / 16 | 16 | `geo.py`, `region/` (elevation archetypes, quadtree terrain, erosion, landcover), `physics/` (collision matrix, anti-tunneling), `mobility/` (`MobilityGraph`, `RoadSegment`, obstructions), `citizens/` (goals, itinerary planning, `CitizenRuntime`), `transport/` (`VehicleInstance`, `TrafficReconciler`), `lod/`, `region_bundle.py`, `synth_city.py`, `living_city.py`; artifacts `region.json`, `physics.json`, street graph (was `mobility.json`), `playback.json`; boulder + denver_region bundles; Godot `region_loader.gd`, `citizen_body.gd`, `vehicle_body.gd`, `mobility_loader.gd`, `collision_layers.gd`, `debug_overlay.gd`; PhysicsGate/RegionGate/NavGate/CityShot/HorizonShot/LivingCity scenes; 115 tests | **yes** — merged as the second parent of the convergence branch (`6cd5a2b`), with the `mobility.json` schema collision resolved (street graph → `streetmap.json`) | **INTEGRATE** (done) |
| 18 | `main` | `57ef86a` | — | — | — | union of #6–#15 | — | **CANONICAL_SPINE** |

Not a branch but relevant: **PR #3** (open) proposes merging `main` *into* the
stale default branch. That direction is backwards; the disposition document
records the replacement landing path.

## Spine selection

Candidates were the two lines with modern work: `main` (`57ef86a`) and the
regional line (`b5cf43a`). Evidence, in the order the mandate lists it:

| criterion | `main` @ 57ef86a | regional @ b5cf43a |
|---|---|---|
| modern world data | Overture-compiled worlds for four cities (22.5k Houston buildings, 958 km road cross-sections, 431k placements), provenance manifest, byte-identical rebuild | June-era `zones/roads` bundles only; no buildings, no compiled world |
| modern schemas | `buildings.json` v1 `{poly,height,key,arch,cat}`, chunk schema v1 with `validate_chunk`, interior descriptor v1, save v2, protocol v3 | `region.json`, `physics.json`, street graph v1 (all new, additive) |
| simulation integrity | authoritative `World` (macro ledger + promoted agents + roster), embodiment, survival, save/load bit-identical, 543 Python tests | goals/itinerary/vehicle/LOD authorities, 115 tests, **not connected to `World`** |
| physical embodiment | humanoid citizens, walk-in interiors, collision on chunk buildings, but **no collision authority** | collision matrix, anti-tunneling, `CitizenBody`/`VehicleBody` verified in real physics |
| Godot compatibility | full menu → play flow, 20 certification scenes, isometric default | 6 gate/shot scenes, no play flow (its `living_city.gd` draws June density blocks) |
| current NPC/world work | yes (humanoids, roster, interiors, residential grammar) | no |
| provenance / determinism | `DetRand`/splitmix per stable key, identity table, provenance manifest | seed-stable noise, deterministic bakes |
| duplicated authorities / stale layers | carries the dead `city-streets` cluster, the June `CityScene`, four road-graph copies | clean but small |

`main` is the spine: it holds every schema the game renders and every certified
gameplay contract, and the regional line is 16 additive commits that merge into
it with seven conflicts (one real: the `mobility.json` name collision). Choosing
the regional line as spine would have meant re-landing 89 commits onto 229 files.

Recorded provenance:

```
STARTING_DEFAULT_BRANCH = claude/asphodel-belief-cascade-kvKKv
STARTING_DEFAULT_SHA    = 35d0c86695dd373b5e78a68889f90fd2603f3f22
SPINE_BRANCH            = main (== claude/asphodel-houston-scene-outdated-k9aetu)
SPINE_SHA               = 57ef86a6d73b8d0b5269f8753b41a45f5442f182
MERGED_LINE             = claude/asphodel-regional-physics-navigation-v1-1bpcqs @ b5cf43a967405fd2383ef8dc37db4b9af0e91345
CONVERGENCE_BRANCH      = claude/asphodel-canonical-convergence-i6h105
MERGE_COMMIT            = 6cd5a2bea175ecbd2e3e40c73386ed9676257ef3
```

## Counts

| classification | branches |
|---|---|
| inspected | 18 (17 `claude/*` + `main`) |
| CANONICAL_SPINE | 2 (`main`, `asphodel-houston-scene-outdated` = same SHA) |
| INTEGRATE (merged this session) | 1 (regional-physics-navigation) |
| ALREADY_CONTAINED | 12 |
| SUPERSEDED | 2 (belief-cascade default; city-streets-building-interiors) — plus the flux half of scenario-engine-flux |
| EXPERIMENT_ONLY | 1 (scenario-engine-flux, harness half) |
| REQUIRES_ARCHITECTURAL_DECISION | 1 (outbreak-config-types) |
| CERTIFICATION_ONLY / BLOCKED / CONFLICTING_AUTHORITY | 0 |

The raw per-branch evidence (commands and outputs) that this table condenses is
reproducible with the commands named at the top of this file.

# Asphodel — Branch Disposition

Companion to `ASPHODEL_BRANCH_CENSUS.md`. For every branch: what it
contributed, whether that contribution survives, where it lives now, and what
the branch is *for* from here on. **No remote branch was deleted or
force-pushed in this session.**

Status vocabulary:

* **RETIRED** — never receive new development; safe to delete after the
  landing below is confirmed. History is preserved through `main`.
* **HISTORICAL_EVIDENCE** — keep the ref for archaeology; do not build on it.
* **STILL_REQUIRED** — carries work the canonical tree does not have and a
  decision is recorded for it.
* **CANONICAL** — the development base.

## Landing path (the only two refs that matter)

```
CANONICAL DEVELOPMENT BRANCH (target):   main
CONVERGENCE BRANCH (this session):       claude/asphodel-canonical-convergence-i6h105
```

`main` currently points at the pre-convergence spine (`57ef86a`). The
convergence branch is a strict descendant of it, so landing is a fast-forward
(no force-push, no history rewrite):

1. Review the convergence PR opened against `main` (see the final report for
   its number) and merge it fast-forward, or run
   `git push origin claude/asphodel-canonical-convergence-i6h105:main` from a
   checkout where `git merge-base --is-ancestor origin/main <convergence>` is
   true.
2. In GitHub → Settings → Branches set the **default branch to `main`**. This
   cannot be done from the sandbox (no repository-settings API access); until it
   is done, agents that clone with defaults will land on the June 12 tree.
3. Close PR #3 (`main` → `claude/asphodel-belief-cascade-kvKKv`): it merges the
   spine *into the stale default*, which is the wrong direction once `main` is
   default.

## Per-branch disposition

| branch | contributed | survives? | lives now in | status |
|---|---|---|---|---|
| `claude/asphodel-belief-cascade-kvKKv` | Phase 3a–8 macro/micro epidemic core, OSM city pipeline v1, June Godot menu, citizen catalog | yes (as ancestors) | `asphodel/{model,micro,handoff,orchestrator,config,graph}.py`, `asphodel/osm_city/`, `godot/{MainMenu,CitySelect,CharacterScreen,Settings}.tscn` | **RETIRED** — stop using as the default branch; it is 89 commits behind the spine and 100+ behind the convergence tree |
| `claude/citizen-spawn-configs-K4iZW` | citizen spawn catalog, environments | yes | `asphodel/citizen.py`, `asphodel/environments.py` | **RETIRED** |
| `claude/scenario-engine-flux-yXt1w` | Phase 4b: `Scenario` object, ensemble/sweep engine, metrics, run-to-termination episodes, multi-zone micro flux | **no** (never merged) | nowhere | **HISTORICAL_EVIDENCE**. Decision: (a) `flux.py` is superseded — Phase 5's `orchestrator.World` owns inter-zone flux with an exact conservation ledger and every later system (save, roster, embodiment) is built on it; re-introducing a second flux path would create a second population authority. (b) The ensemble/sweep/episode harness is research tooling over the *frozen June engine* (`Simulation`/`AgentZone` verbatim) and would need to be rebuilt against `World`; nothing in the game runtime depends on it. If sweeps are wanted again, port `metrics.py` (pure functions of the aggregate frame) and re-express `engine.run_ensemble` over `World.run`; do not merge the branch. |
| `claude/outbreak-config-types-A8fTw` | zombie genome archetypes; macro `U` (undead) / `C` (corpse) compartments; transmission routes | **no** (never merged) | nowhere | **STILL_REQUIRED — REQUIRES_ARCHITECTURAL_DECISION**. This is the only branch carrying zombie-specific epidemiology, which the product needs. It cannot be merged as-is: it adds compartments to the macro ledger that the micro `AgentZone` (state codes S,E,Ia,Is,R,D), the `snapshot()` wire, `save.py` v2, calibration (`macro_ref.py`) and `citizen_render.gd`'s state palette do not know, so a promoted zone would silently drop the undead. The port belongs to the outbreak milestone and must land as one change across macro + micro + handoff + save + snapshot + renderer, with the reanimation fields defaulted off so ordinary genomes stay byte-identical (the branch already designed for that). Until then, keep the branch. |
| `claude/project-zomboid-lessons-mwoke7` | PZ lessons, NPC precedent research, Phase 11 design + SP1–SP3 plans | yes, byte-identical | `docs/PROJECT_ZOMBOID_LESSONS.md`, `docs/NPC_PRECEDENT_RESEARCH.md`, `docs/superpowers/**` | **RETIRED** |
| `claude/asphodel-gameplay-integrity-de72g6` | real-road zone mobility, authoritative clock/outbreak/pause, first headless Godot certification | yes | `asphodel/osm_city/mobility.py`, `godot/scripts/game_clock.gd`, `godot/tests/{TestRunner,StreetSmoke}.tscn` | **RETIRED** |
| `claude/asphodel-authoritative-world-55z0qw` | live bridge, citizen identity/activity, reactive affordances, roster, save/load, living-city renderer | yes | `asphodel/bridge/`, `asphodel/{npc,roster,save,affordances}.py`, `godot/scripts/{sim_bridge,citizen_render}.gd` | **RETIRED** (was "canonical" per the old `docs/CANONICAL_STATUS.md`; superseded by `main`) |
| `claude/asphodel-embodied-survival-qlizmu` | embodiment (one physical location per citizen), survival loop, Gate 0 closure | yes | `asphodel/{embodiment,items,survival}.py` | **RETIRED** |
| `claude/asphodel-walk-in-interiors-v1-k9m2` | interior descriptor/generator, walk-in streaming, furniture → containers, interior occupants, protocol v3 | yes | `asphodel/interiors.py`, `godot/scripts/interior_builder.gd`, `godot/tests/Live{WalkIn,Interior,Vertical}.tscn` | **RETIRED** |
| `claude/outside-world-full-city-mvp-tuh0de` | Overture acquisition → normalized world source → compiled chunk world; canonical `buildings.json`; spawn anchors; streaming renderer | yes | `asphodel/world_source/`, `godot/scripts/exterior_world.gd`, `godot/bundles/*/world/` | **RETIRED** |
| `claude/asphodel-isometric-presentation-v1-xwry9h` | isometric presentation (default gameplay scene) | yes | `godot/IsometricWorld.tscn`, `godot/scripts/isometric_*.gd` | **RETIRED** |
| `claude/city-assets-visual-identity-v1` | asset catalog, appearance inference, business identity, props/vehicles/vegetation | yes | `asphodel/city_visual/`, `godot/scripts/{prop_meshes,furniture_meshes}.gd` | **RETIRED** |
| `claude/residential-architecture-grammar-v1-kx5hpz` | Python-authoritative residential architecture grammar + renderer | yes | `asphodel/world_source/residential_grammar.py`, `asphodel/city_visual/residential_architecture.py`, `godot/scripts/residential_house_renderer.gd` | **RETIRED** |
| `claude/asphodel-humanoid-npc-v1-j8o8sb` | deterministic low-poly humanoids, one visual identity authority, crowd LOD | yes | `godot/scripts/citizen_{visual_identity,meshes,avatar,render}.gd`, `godot/shaders/citizen_material.gdshader` | **RETIRED** |
| `claude/city-streets-building-interiors-55xxq9` | an alternative streets/buildings/interiors/loot client stack built on an obsolete `buildings.json` shape | **no** — the seven scripts, `osm_city/synth.py` and the Godot-local inventory in `first_person.gd` were dormant second implementations of systems `main` already had (compiled exterior, `interiors.py` + `interior_builder.gd`, authoritative `items/survival`). They are **deleted** in the convergence tree. Its one idea not otherwise present (swinging door props) is not an authority and can be re-done as presentation later. | history only | **RETIRED** |
| `claude/asphodel-houston-scene-outdated-k9aetu` | the prior consolidation attempt (== `main`) | yes | `main` | **RETIRED as a name** — identical to `main`; do not develop on it |
| `claude/asphodel-regional-physics-navigation-v1-1bpcqs` | regional terrain, physics authority, street graph, citizen intention runtime, vehicle identity, LOD, living-city commute, Godot gates | yes — merged; `mobility.json` collision resolved to `streetmap.json`; region schema advanced to v2 (city plateau) | `asphodel/{geo,region,physics,mobility,citizens,transport,lod}/`, `asphodel/{region_bundle,synth_city,living_city}.py`, `godot/scripts/{region_loader,citizen_body,vehicle_body,mobility_loader,collision_layers,debug_overlay}.gd`, `godot/tests/{PhysicsGate,RegionGate,NavGate,CityShot,HorizonShot,LivingCity}.tscn` | **RETIRED** (integrated) |
| `main` | the spine | — | — | **CANONICAL** once the convergence PR lands and the default is switched |

## What future agents must stop doing

* Starting from the GitHub default branch without checking `docs/CANONICAL_STATUS.md`.
* Creating a new `claude/asphodel-*` line from any branch other than `main`.
* Re-baking a bundle from a branch's private schema. The schemas are versioned
  in `docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md`; loaders reject
  anything else.

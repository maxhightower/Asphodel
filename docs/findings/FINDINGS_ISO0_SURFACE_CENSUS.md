# FINDINGS — ISO-0 Surface Census & Baseline

**Mission:** Asphodel Continuous Isometric Presentation V1 — pivot the *presentation*
(renderer, camera, interaction, interior cutaway) over the continuous authoritative
world, without tiles and without touching the simulation.

**Verdict: `ISO0_SURFACE_CENSUS: PASS`** — the presentation/authority seams are
mapped, the reusable surfaces are identified, and the baseline is certified.

---

## Baseline

| | |
|---|---|
| starting_branch | `claude/asphodel-isometric-presentation-v1-xwry9h` (branched from the verified frontier) |
| starting_sha | `da9ba66b566b1844c68d39509e874b6850bcec6a` |
| frontier branch | `claude/outside-world-full-city-mvp-tuh0de` @ `da9ba66` (re-verified: HEAD matches) |

**Ancestry (all confirmed as ancestors of the frontier):**
- `claude/asphodel-authoritative-world-55z0qw` — IN ANCESTRY (`4728113`)
- `claude/asphodel-embodied-survival-qlizmu` — IN ANCESTRY (`d520e0b`)
- `claude/asphodel-walk-in-interiors-v1-k9m2` — IN ANCESTRY (`12f698f`)
- `claude/outside-world-full-city-mvp-tuh0de` — IN ANCESTRY (`da9ba66`, = frontier)

The GitHub default branch (`claude/asphodel-belief-cascade-kvKKv`) is **not** in this
lineage and was correctly ignored as authority, per the mission's provenance note.

**Baseline certification (this environment, Godot 4.4.1-stable, Python 3.11):**
- **Python:** `444 passed, 1 failed`. The single failure —
  `test_world_from_compiled.py::test_compile_writes_only_presentation_files` — is a
  pure **data-dependency**: it requires raw Overture parquet
  (`data/raw/overture/2026-08-19.0/madisonville_tx/segment.parquet`) that is not in a
  fresh clone (it is fetched by `python -m asphodel.world_source acquire`). It fails
  identically on the untouched baseline SHA and is unrelated to this work. All 444
  other tests pass. (Runtime deps installed for the suite: numpy, pytest, pyarrow,
  shapely.)
- **Godot `TestRunner.tscn`:** green — `== done: 0 failure(s) ==` (bundle validation,
  GameClock, ZoneMap, CitizenRender, menu-flow scenes).
- **Godot `OwPerfBench` (houston):** T1 avg **12.0 ms**, T2 avg **4.1 ms**,
  T3 avg **1.5 ms**; resident_chunks **96**, resident_nodes **3205**,
  mm_instances **5903**, fresh 3×3 delta **+36.6 MB**. These match the mission's
  quoted baseline within noise (T1 ~9.7, T2 ~4.0, T3 ~1.5), establishing the
  same-machine reference for the ISO-10 perf gate.

---

## The presentation stack (what each surface is)

Reusable, authoritative, or FPS-specific — the seam map that the parallel isometric
route is built on.

### Autoloads — authoritative, renderer-independent (REUSE AS-IS)
| Surface | Role | Verdict |
|---|---|---|
| `scripts/sim_bridge.gd` (**SimBridge**) | The single authoritative bridge to the Python `World`: `START_WORLD`, `ADVANCE`, `INTERACT_WITH`, `ENTER_BUILDING`/`LEAVE_BUILDING`, `GET_INTERIOR`, `SEARCH_CONTAINER`/`TAKE_ITEM`, `USE_ITEM`, `SNAPSHOT`, `SAVE`/`LOAD`, `PAUSE`/`RESUME`. Protocol v3. | **Authoritative** — both renderers speak it; no Godot-local truth. |
| `scripts/game_clock.gd` (**GameClock**) | Time + pause authority + outbreak (driven by `ADVANCE`). Exposes `time_scale` (the ISO-8 acceleration hook) and `set_paused`. | **Authoritative / shared.** |
| `scripts/session.gd` (**Session**) | Cross-scene handoff: `bundle_dir`, `citizen`. | **Shared.** |

### Presentation surfaces that are cleanly reusable (REUSE)
| Surface | Role | Verdict |
|---|---|---|
| `scripts/exterior_world.gd` (**ExteriorWorld**, `class_name`) | Chunked continuous OSM city stream: `setup(dir)`, `update_focus(pos)`, `force_materialize(pos)`, tiered T1/T2/T3 MultiMesh build + per-building collision, LRU cache. **Touches no SimBridge/Session.** | **Shared presentation** — drive `update_focus` from the iso camera focus. |
| `scripts/citizen_render.gd` (**CitizenRender**) | `render_snapshot(snap, zone, offset, extent)` — MultiMesh crowd from `World.snapshot()`, stable `visual_seed` tint, pooled nameplates. Pure snapshot consumer. | **Shared presentation.** |
| `scripts/interior_builder.gd` (**InteriorBuilder**, static) | `build(descriptor, offset)` — floor/ceiling/walls/fixtures/occupants/exit from a `GET_INTERIOR` descriptor. Fixtures carry authoritative `building_id`/`fixture_id`/`container_index`; occupants carry `citizen_id`. | **Shared presentation** (extended additively with wall metadata for the cutaway — see ISO-5). |
| `scripts/zone_map.gd`, `scripts/bundle_loader.gd`, `scripts/prop_meshes.gd` | Zone resolution, bundle loading, prop MultiMeshes. | **Shared.** |

### First-person-specific surfaces (FORKED, not modified)
| Surface | Why it is FPS-specific | Isometric replacement |
|---|---|---|
| `scripts/first_person.gd` | Eye-height `Camera3D` **child of the player**, mouse-look, capture-gated WASD. | `scripts/isometric_player.gd` (no eye camera) + `scripts/isometric_camera.gd` (external orthographic rig). |
| `scripts/street_world.gd` `_ensure_input` (mouse capture), `_pause`/`_resume` (`MOUSE_MODE_*`), `screenshot_reposition` (eye tilt) | Assume captured mouse + eye camera. | `isometric_world.gd` input map (+ camera rotate/zoom), overlay pause without mouse capture. |
| `street_world.gd` E-key interaction (`_try_interact` → nearest-by-distance) | Already **not** a raycast — targets by continuous distance + node meta. | Generalised into `isometric_interaction.gd` (cursor → selected → nearest), same authoritative ids. |

### Deletable only after the isometric gate passes
`first_person.gd` and the FPS-only branches of `street_world.gd` remain during A/B
comparison. They are kept (frozen) in this branch; deletion is a later cleanup.

---

## The seams that mattered (and how the isometric route handles them)

1. **Player spawn / positioning** — authoritative: `Session.citizen.spawn_xy`, with a
   road/centre fallback, validated clear of building AABBs (`_find_clear_spawn` /
   `_inside_building_footprint`). *Isometric reuses the identical resolution; the
   spawn coordinate is continuous.*
2. **Camera ownership** — FPS: `Camera3D` child of the player at eye height, mouse-look.
   *Isometric: a separate orthographic `IsometricCamera` that follows the player and
   is never parented to it — the clean fork point.*
3. **Interaction** — there is **no camera raycast** even in the FPS path; targeting is
   nearest-by-continuous-distance, and identity comes from snapshot `citizen_id` or
   node `get_meta` (`building_id`/`fixture_id`/`container_index`) — never node names.
   *Isometric keeps ids, adds cursor + selection to nearest.*
4. **Building enter/leave** — `_nearest_building` (AABB, index == Python `building_id`)
   → `GET_INTERIOR` → `InteriorBuilder.build` at a staged offset `(100000,0,0)` →
   `ENTER_BUILDING`, player teleported to the entrance; leave requires proximity to the
   `ExitMarker`. *Isometric reuses this staging (proven, identity-preserving) and adds
   the cutaway.*
5. **Roof/ceiling** — **no show/hide logic exists** anywhere; roofs are always-on baked
   geometry (exterior batched mesh; interior single `Ceiling` node). *This is exactly
   what ISO-5 adds — for the interior, via a cutaway that needs no exterior mesh
   surgery.*
6. **Chunk streaming focus** — driven by player position on a 0.5 s timer via
   `ExteriorWorld.update_focus`. *Isometric drives it from the camera's ground focus
   (which follows the player), frozen while inside the staged interior.*
7. **Citizens** — MultiMesh from snapshots; NPC identity by `citizen_id`. *Reused
   verbatim under the iso camera.*

---

## No code migration began before understanding the seams

The parallel route adds only presentation (`IsometricWorld.tscn` + six
`isometric_*.gd`) and one additive change to a shared helper (wall metadata in
`interior_builder.gd`). The simulation, the bridge protocol, and the FPS path are
untouched. **`ISO0_SURFACE_CENSUS: PASS`.**

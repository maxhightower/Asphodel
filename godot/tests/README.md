# Godot gameplay-integrity tests

Headless harnesses that certify the client's contracts. They run as **scenes**
(not `--script`) so the `Session` / `GameClock` / `SimBridge` / `CollisionLayers`
autoloads are loaded — `--script` mode does not register autoloads. Requires
Godot 4.4+.

## Prerequisite: import the project once

Before running ANY scene in a fresh checkout or worktree:

```sh
godot --headless --path godot --import
```

This builds `.godot/global_script_class_cache.cfg`. Without it every
`class_name` lookup (`BundleLoader`, `CitizenBody`, `RegionLoader`, …) fails
with *"Identifier not declared in the current scope"*.

## 1. Pure-logic + menu-flow checks (`TestRunner.tscn` → `run_tests.gd`)

Bundle validation, `GameClock` time / outbreak / pause logic, and that every
pre-world flow scene (MainMenu → CitySelect → CharacterScreen, plus Settings)
instances and builds its UI on `_ready` with the citizen data handoff intact.
No physics frame required.

```sh
godot --headless --path godot res://tests/TestRunner.tscn
```

## 2. Runtime spawn/pause/outbreak smoke (`StreetSmoke.tscn` → `test_street_scene.gd`)

Instances `StreetScene` with a selected bundle + citizen, runs real physics
frames, and asserts: player spawns near the citizen's authoritative coordinate,
starts on/above valid ground and not inside a building, the clock/outbreak
advance while unpaused (fast-forwarded so a real tick change is observed),
pause freezes the tree + clock + outbreak + player physics while resume advances
again, and an out-of-bounds fall recovers.

```sh
godot --headless --path godot res://tests/StreetSmoke.tscn
```

Both quit with code `0` on success, `1` on failure — suitable for CI.

## 3. Proving-ground gates (`tests/run_gates.sh`)

Four gates that run real in-engine physics and geometry against the shipped
bundles. Godot's 3D physics runs on CPU under `--headless`, so no GPU is needed.
Each prints `PASS` / `FAIL` lines and a `==== PASS/FAIL (N failure(s)) ====`
summary, and exits `0` / `1`.

| Gate | Scene | What it certifies |
| --- | --- | --- |
| Physics | `PhysicsGate.tscn` | The Python collision matrix (`asphodel/physics/layers.py` → `CollisionLayers`) produces the intended in-engine interactions: what blocks what, what passes through what. |
| Region | `RegionGate.tscn` | `RegionLoader` realizes baked terrain — chunk meshes, near-chunk collision, atmosphere — and flat (Houston) vs mountain (Denver) relief is real in the constructed geometry. |
| Nav | `NavGate.tscn` | Navigation/pathing over built world geometry. |
| Convergence | `ConvergenceGate.tscn` | Gates G / I / E / H below. |

```sh
godot --headless --path godot --import          # once
GODOT=/path/to/godot ./godot/tests/run_gates.sh # all four
```

### `ConvergenceGate.tscn` → `convergence_gate.gd`

Needs **no Python bridge** — it runs entirely against the checked-in bundles.

- **G — collision-layer unification.** Every `StaticBody3D` the shipping path
  builds (the streamed `ExteriorWorld` chunks, `InteriorBuilder` floors / walls /
  fixtures) is on `WORLD_STATIC` with mask 0; both player bodies
  (`first_person.gd`, `isometric_player.gd`) carry the `player` profile;
  `CitizenBody` / its perception `Area3D` / `VehicleBody` carry the `npc` /
  `trigger` / `vehicle` profiles. Then a real drop test: a player body released
  above a `WORLD_STATIC` slab must land on it — proving the layers still *meet*,
  not merely that the numbers were written down.
- **I — schema contract at the bundle boundary.** `BundleLoader` rejects a bare
  JSON array for `buildings.json` (the obsolete pre-v1 form) and an unknown
  `streetmap.json` version, while still accepting the legacy `sample_bundle`
  shape and loading Houston's 22 525 footprints in full.
- **E — deterministic visual identity.** A citizen's appearance is a pure
  function of their id: identical across repeat computation and across a
  reseeded global RNG (`seed(1)` vs `seed(2)`), and distinct between ids.
- **H — multi-city load matrix.** For houston / madisonville_tx / austin /
  san_antonio: bundle, buildings, streetmap (cross-checked against the file's own
  declared node/segment counts, with every sampled endpoint resolving to a real
  node), region, `physics.json` collision matrix, in-engine `RegionLoader` chunk
  meshes, and `ExteriorWorld.setup`. The synthetic region-only `boulder` bundle
  is reported in the same matrix, but only its streetmap / region / physics
  checks are counted — it ships no compiled `world/` and no citizen roster, so
  those rows print as `INFO`. A matrix table is printed at the end.

## Bridge-dependent scenes

`Live*.tscn`, `IsometricLiveSmoke.tscn`, `IsometricInteractionSmoke.tscn`,
`IsometricInteriorSmoke.tscn`, `LiveBench.tscn` and `InteriorBench.tscn` talk to
the authoritative Python sim over `SimBridge`. Start it first:

```sh
python -m asphodel.bridge.server
```

Without it they report *"no live bridge"* and fail; they are not part of the
bridge-free CI set.

## Execution status

**Executed and green on Godot 4.4.1-stable** (headless): `TestRunner` 22/22,
`StreetSmoke` 14/14, `ExteriorStream`, `CitizenHumanoidSmoke`,
`IsometricExteriorSmoke`, `IsometricCameraSmoke`, `AssetCatalogSmoke`,
`PhysicsGate`, `RegionGate`, `NavGate` and `ConvergenceGate` all exit 0 with no
runtime script errors. The Python side of every gameplay-integrity contract is
covered by the `pytest` suite in `../../tests/`.

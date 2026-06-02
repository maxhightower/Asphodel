# Design — Play as a Random Citizen, First-Person on the Street

**Date:** 2026-06-01
**Status:** Approved (design); pending implementation plans
**Branch:** `claude/asphodel-belief-cascade-kvKKv`

## 1. Summary

After the player picks a city (Houston / San Antonio / Austin) and clicks **Load
City**, the game randomly selects a **spawn config** (a city-profile archetype)
and spawns a random **citizen** from it, shows the player who they are on an
ARK-style **character screen** (name, age, occupation, the occupation's
*signature* collapse predicament, inventory, home district), and then — on
**Continue** — drops them into a **first-person, human-scale street scene** at
their spawn, walkable with WASD / Shift-sprint / mouse-look.

This deliberately layers a player-facing micro experience on top of the existing
macro abstract block-city, matching Asphodel's two-tier (macro/micro) design: the
block-city is the *map*; the street scene is *where you actually stand*.

## 2. What already exists (and is reused)

- **`claude/citizen-spawn-configs` branch (unmerged, ~6,900 lines):** the citizen
  model — `spawn_citizen(city, catalog, rng) -> CitizenProfile` (age, sex,
  occupation, home/work zone, daily schedule, inventory), `CityProfile` +
  `CitizenSpawnCatalog`, `signatures.py` (each occupation's defining
  collapse-moment), plus `environments.py`, `vehicles.py`, `gametime.py`,
  `world.py` (a `CityWorld`), and `cities/{capital,harbor,university,generic}.yaml`
  + `cities/_catalog.yaml`. This is the source of "citizen and config".
- **Trunk:** the OSM bundle pipeline (`asphodel/osm_city`), the three checked-in
  city bundles, the Godot project (MainMenu → CitySelect dropdown → CityScene
  block-city), and `orchestrator.py` (a separate `World`).

## 3. Goals / Non-goals

**Goals**
- On Load City: randomly pick a spawn-config archetype + spawn a random citizen.
- A character screen presenting that citizen evocatively, with Continue/Back.
- A walkable first-person street scene at spawn (WASD, Shift-sprint, mouse-look,
  collision, mouse-capture + Esc to release).
- Reuse the branch's `citizen.py` rather than reinventing citizen generation.

**Non-goals (explicit, deferred)**
- Live Python at play time (citizens are pre-baked into the bundle; see §5).
- OSM-faithful local geometry (the street block is procedural-generic; see §6).
- Simulating the outbreak in first person, NPCs, interaction, inventory use,
  combat, or the signature scenario actually *playing out* — the screen only
  *describes* it for now.
- Reconciling `world.py` (`CityWorld`) and `orchestrator.py` (`World`) into one
  abstraction — they coexist after the merge; unifying them is future work.

## 4. Sub-projects (sequenced; each its own plan → implementation)

| # | Sub-project | Deliverable | Demoable result |
|---|---|---|---|
| **1** | **Integrate the citizen branch** | Merge `citizen-spawn-configs` into trunk; reconcile `README.md` + `asphodel/__init__.py`; all tests green (trunk's + the branch's). | `import asphodel.citizen` works on trunk; full suite passes. |
| **2** | **Random citizen+config → character screen** | Pipeline bakes a citizen *population* into each bundle; Godot random-picks one on Load City and shows the ARK-style character screen. | Pick city → see "who you are." |
| **3** | **First-person street scene** | Continue → procedural human-scale street block + first-person `CharacterBody3D` controller. | Walk around as the citizen. |

## 5. Data flow — how the citizen reaches Godot (Sub-project 2)

**Bake a population into the bundle; Godot random-picks at runtime.** This keeps
Godot a pure consumer and needs no Python at play time (consistent with how
bundles already work).

- The OSM pipeline gains an optional citizen step: for the bundle's city, spawn a
  population spanning the profile archetypes — e.g. for each of
  `{capital, harbor, university, generic}` spawn K citizens via
  `spawn_population` (seeded) — and write them to **`citizens.json`** in the
  bundle: a list of `{profile, name, age, sex, occupation, home_district,
  home_zone, work_zone, signature_title, signature_text, inventory}` records
  (a flattened, render-ready projection of `CitizenProfile` + its occupation
  signature). `home_zone`/`work_zone` are the citizen model's own
  district-based indices; mapping them onto the OSM bundle's grid zones is **out
  of scope** — the street scene (§6) is themed by district *kind*, not by a
  specific bundle zone, so no alignment is required.
- On **Load City**, Godot loads `citizens.json` and picks one at random (a fresh
  pick each load → the "randomly selected" feel). The chosen citizen is stashed
  in the `Session` autoload alongside `bundle_dir`.
- **Determinism / variety:** the bake is deterministic from `(city, seed)`, but
  baking K≈40–80 citizens across 4 profiles gives ample runtime variety. (A
  live-spawn subprocess bridge for unbounded variety is a deferred enhancement.)

## 6. First-person street scene (Sub-project 3)

**Revised (2026-06-01): the full loaded city is walkable**, not a small
procedural block. `Continue` drops the player into the *actual OSM city
geometry* (the same blocks + roads the bundle already carries) at its real metre
scale, made walkable.

- **`Continue`** loads a new scene `StreetScene.tscn` (`Node3D` + `street_world.gd`),
  reading the chosen citizen from `Session`. The bird's-eye `CityScene` stays as a
  now-vestigial map view.
- **Geometry:** the bundle's density-scaled blocks (visual `MultiMeshInstance3D`)
  and major-road line-strips, at real scale — kept self-contained in
  `street_world.gd` rather than refactoring the proven `city_builder.gd` (which
  can't be re-verified without a Godot CLI here).
- **Collision:** one ground `StaticBody3D` (a thin box whose top is at y=0) plus
  one buildings `StaticBody3D` holding a `BoxShape3D` per block at the *same*
  transform as its visual instance (single body, many shapes — efficient). So the
  player walks the ground and is blocked by buildings.
- **Controller (`first_person.gd` on a `CharacterBody3D`):** capsule collider +
  eye-height `Camera3D` (both built in code), gravity, **WASD** walk, **Shift**
  sprint, mouse-look (mouse captured). First-person only. Movement/look are gated
  on `mouse_mode == CAPTURED`, so the pause overlay naturally freezes the player.
- **Spawn:** at the first major-road point (on a street, not inside a building),
  a few metres up so it settles onto the ground.
- **Esc → pause overlay** (`Resume` / `Back to Menu`), releasing the mouse;
  Resume re-captures. **HUD:** a small "{name} · {occupation}" label + a controls
  hint; **no** signature text in-world.
- Input actions (`move_forward/back/left/right`, `sprint`, physical WASD/Shift)
  are registered at runtime via `InputMap` (idempotent), avoiding fragile
  `project.godot` `[input]` hand-editing.
- **Scale caveat:** the city is abstract km-scale blocks (no detailed
  streets/sidewalks/interiors); first-person is a large, sparse, explorable
  expanse with the road network as ground lines. Per-block collision is
  hundreds–~1.8k box shapes for the bundled cities (acceptable; flagged).

## 7. Character screen (Sub-project 2)

A `CharacterScreen.tscn` (Control + script), reached after Load City:
- **Identity:** "You are **{name}**, {age}, {occupation}." + sex/home district.
- **Signature:** the occupation's signature title + one-paragraph predicament
  (from `signatures.py`, baked into `citizens.json`).
- **Inventory:** the citizen's starting items (name × count).
- **Buttons:** **Continue** → `StreetScene`; **Back** → CitySelect (re-roll on
  return, since selection happens on Load).
- Built in code (like the other Godot screens), so the `.tscn` stays a trivial
  Control root.

## 8. Integration risk (Sub-project 1)

- **Conflict surface is just two files:** `README.md` and `asphodel/__init__.py`
  (resolve by keeping both sides' additions — the branch's citizen exports + the
  trunk's osm/orchestrator content).
- `world.py` (branch) and `orchestrator.py` (trunk) are different filenames → no
  git conflict; both define a "world" abstraction (documented redundancy, not
  reconciled here).
- The branch's new modules were written against the pre-Phase-5 base; they import
  `config`/`graph` symbols that still exist on trunk (trunk only *added* fields),
  so imports should resolve. **Verification:** the branch's tests
  (`test_citizen`, `test_world`, `test_environments`, `test_vehicles`,
  `test_gametime`, `test_signatures`, `test_travel_events`) must pass post-merge
  alongside trunk's suite.

## 9. Testing strategy

- **Sub-project 1:** run the full `pytest` suite post-merge — trunk's tests
  (osm/model/phase4a/orchestrator/topology/interventions) **and** the branch's 7
  new test files all green.
- **Sub-project 2:** Python test that the pipeline writes a well-formed
  `citizens.json` (records have the required keys; zones in range; ≥1 citizen per
  profile). Godot side editor-verified (Load City → a citizen shows).
- **Sub-project 3:** editor-verified (Continue → walk with WASD/sprint/mouse-look;
  Esc releases). No Godot CLI here, so first-person is user-verified.

## 10. Open items / future

- Live-spawn subprocess bridge for unbounded citizen variety.
- The signature scenario actually *playing out* in first person.
- Unifying `CityWorld` and `World`.
- OSM-faithful local geometry; NPC citizens on the street; day/night from
  `gametime.py`.

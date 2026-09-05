# Package 3 — First Authoritative Survival-Resource Loop (Findings)

**Working branch:** `claude/asphodel-embodied-survival-qlizmu`
**Verdict:** **PASS** (Python-certified end-to-end through the real command
dispatch; Godot client code-updated but not engine-executed here — see the
environment caveat in `FINDINGS_P1_CANONICALIZATION.md`).

The required loop is closed:

    move -> enter/search a place -> inspect container/item -> take item ->
    inventory changes -> use/drop item -> authoritative state changes ->
    save/load preserves it.

---

## Pre-change state (audited)

Before this package there was **no item, container, inventory, or survival state**
in the authoritative world. Citizens carried an `inventory` dict (data only) and
the bundles' `citizens.json` even carried `inventory_scopes`
(home/on_person/vehicle/workplace) — but nothing consumed them. Buildings were
anonymous polygons (`poly` + `height`, no id, no category). The old
`city-streets-building-interiors` donor branch had explored enterable buildings /
interiors / loot, but as **Godot-local** gameplay state — which the milestone
forbids resurrecting.

## What was built (all authoritative Python)

### 3A — Item authority model (`asphodel/items.py`)

`ItemKind` registry (data): kind, category (food/drink/medical/tool/misc), stack
semantics, `consumed_on_use`, and minimal survival effects (hunger/thirst/health/
stamina deltas). `ItemStack` (kind + quantity). A permissive fallback keeps
unknown bundle kinds round-tripping. **Godot never owns the inventory.**

### 3B — Persistent containers, at city scale (`items.container_*`)

Container contents are a **pure function of `(world_seed, building_id,
container_index)`** — implicit until observed, regenerable from the seed forever.
`container_flavour` gives each building a stable residential/commercial/medical
loot character (buildings carry no category, so it is a seeded hash). This is the
scalability rule made literal: **untouched containers cost zero bytes**; only
*touched* containers enter a bounded world-delta store.

### 3C — Minimal interiors / building access

Building identity is the **stable index into `buildings.json`** — and Godot's
`BundleLoader.load_buildings` returns that same order, so the Godot building index
equals the Python `building_id` (verified). Authoritative access is `enter_building`
/ `inspect_building` / `search_container`; a full continuous interior is not
required — `building_id` + container index is enough for the loop, and the
authoritative state always refers to the same building id.

### 3D — Player inventory (`asphodel/survival.py`)

`PlayerSurvival` (health/stamina/hunger/thirst + on-person inventory +
`current_building`). Operations — `inspect_inventory`, `take_item`, `drop_item`,
`use_item`, `pick_up_dropped` — each **validate legality authoritatively, mutate
Python state, and return the new state**. Illegal actions raise a typed
`SurvivalError` (stable machine code) rather than mutating.

### 3E — Minimal needs/effects

Hunger and thirst rise each tick (`on_tick`, scaled by dt); a maxed need bleeds
health; stamina slowly regenerates. Food lowers hunger, drink lowers thirst,
medical restores health — enough to make resources matter. **Player-level
infection/exposure was deliberately deferred** (the brief's guidance): the player
is already a citizen in the authoritative SEIR population, and a parallel
player-disease track would risk contradicting that truth. The needs tick is pure,
RNG-free, and never touches the sim.

### 3F — Interaction protocol (v2)

`PROTOCOL_VERSION` → **2**. New commands: `ENTER_BUILDING`, `LEAVE_BUILDING`,
`INSPECT_BUILDING`, `SEARCH_CONTAINER`, `TAKE_ITEM`, `DROP_ITEM`, `USE_ITEM`,
`INSPECT_INVENTORY`. Strict validation (`building_id` range-checked against the
bundle geometry; typed argument errors); rejected actions return a stable
`illegal_action` error; ordering is deterministic (the server answers one request
before reading the next — inherited from M1). No Godot-side hidden mutations. The
GDScript `sim_bridge.gd` mirrors every command and bumps to v2.

### 3G — Save/load (v2 + explicit migration)

`SAVE_VERSION` → **2**, adds a `survival` section (player state, world-delta
container store, dropped items, drop counter). A **v1 save is explicitly migrated**
(survival starts absent, not silently reinterpreted); an unknown version is
rejected. The bridge `START_WORLD` seeds the player inventory from the citizen's
on-person loadout; `LOAD` restores everything.

## Certification — required tests

`tests/test_survival.py` — **all pass**:

* **Container persistence**: seed → search → take → "leave & return" (re-derive) →
  item still gone; full re-search does not respawn; untouched containers
  regenerate identically from the seed.
* **Inventory legality**: cannot take a nonexistent item; cannot duplicate via
  repeated take; cannot use an unowned item; drop transfers ownership exactly once
  (and pick-up returns it exactly once).
* **Determinism**: same seed + command sequence ⇒ identical contents, instance
  ids, inventory, needs, dropped locations; a different seed diverges.
* **Save/load**: `start → enter → loot → consume/drop → save` then *continue* vs
  *destroy + reload + continue* → **bit-identical** authoritative continuation;
  container delta persists across reload.
* **Regression guard**: a world running the survival loop has a **bit-identical
  SEIR trajectory** to one without it — survival is epidemic-neutral.

**Vertical proof:** `tests/test_survival_vertical.py` drives the brief's full
final sequence **through the real `WorldSession` command dispatch** (the exact
authoritative path Godot uses, minus the socket): start → spawn as a real bundled
citizen → coherent player location → advance → observe other identified citizens
on routines → enter a real building → search a real container → take food/water →
it leaves the container and enters inventory → use it (survival changes) → drop
one → interact with an NPC (roster persists) → leave & return (looted-container
persistence holds) → **save → destroy the session → load → continuation
bit-identical**. **PASS.**

## Known limitations (explicit)

* **No Godot execution here** (no `godot4`): the survival HUD, the E-key
  enter/search/loot flow, and the v2 bridge wiring in GDScript are code-complete
  and use the verified building-id convention, but are certified by inspection
  only in this environment. The **entire authority** they call is executed and
  green.
* **Interiors are minimal**: `building_id` + containers, not walk-in geometry.
  Streamed interiors from the donor branch are a clean follow-up; the authoritative
  contract already supports them (mode `interior` exists).
* **Player disease coupling deferred** by design (see 3E).
* **One container flavour per building** via a seed hash (buildings lack
  categories); richer, geometry-aware loot is a later refinement.

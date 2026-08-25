# Walk-In Building Interiors v1 — Final Findings

**Branch:** `claude/asphodel-walk-in-interiors-v1-k9m2` (from the Gate-0 closure
commit `d520e0b`).
**Verdict: PASS.** Gate 0 converted the prior milestone to a fully certified
in-engine PASS; Walk-In Interiors v1 (Packages 1–6) is complete and certified in
real Godot 4.4.1 against the live Python authority on the committed Houston bundle.

The decisive evidence: the milestone's **30-step Houston vertical runs end-to-end
in-engine with 0 failures** — stand on a street, enter a real building, walk a
streamed interior, search physical furniture mapped to authoritative containers,
take/use/drop an authoritative item, meet an interior NPC, leave/unload, return
and see the same persistent changes, save, reload, and see them still.

---

## Gate 0 — prior milestone PARTIAL → PASS

Godot 4.4.1 was installed (the prior environment lacked it) and the full in-engine
surface run against the real server + bundles: Python **278** (now 299),
TestRunner 0-fail, StreetSmoke 0-fail, LiveSmoke 0-fail, save/destroy/reload
**BIT-IDENTICAL**, a new in-engine survival cert 0-fail, LiveBench. See
`FINDINGS_GATE0_CERT_CLOSURE.md`. The prior milestone is now **PASS**.

## Interior authority contract (Package 1)

`asphodel/interiors.py` — a versioned `InteriorDescriptor` (rooms, doorways,
entrances, fixture anchors) produced by a **pure, deterministic, RNG-isolated**
generator keyed by `(world_seed, building_id, gen_version)` + the real footprint.

* **Immutable base vs persistent deltas.** The descriptor is regenerable and
  costs zero persistent bytes; the only stored state is player-caused deltas,
  held in the *existing* survival stores keyed by `(building_id, container_index)`.
* **Building → room → fixture → container identity.** A fixture's
  `container_index` **is** the authoritative container id — the module creates no
  new container/item authority. Fixtures are 1:1 with `items.n_containers`,
  indices `0..n-1`.
* **Lifecycle.** unloaded → materializing → active → unloading; only authoritative
  mutations survive unload, and re-entry regenerates identical base geometry.

Certified: `tests/test_interiors_contract.py` (8/8).

## Deterministic generator (Package 2)

BSP room partition of the footprint AABB hull (non-rectangular footprints use a
recorded AABB simplification); doorways on split seams form a **spanning tree so
every room is reachable**; entrance biased to the street-facing wall; archetypes
(house/retail/office/clinic) aligned with the container loot flavour; single
active floor (upper floors explicitly unsupported in v1).

Certified: `tests/test_interiors_generator.py` (8/8) — deterministic hash,
reachability, furniture-in-bounds, fixtures↔containers, valid doorways, footprint
tolerance, repeated-reload stability, multiple archetypes.

## Physical entry, doors, collision, streaming (Package 3)

`godot/scripts/interior_builder.gd` materializes a descriptor into floor, ceiling,
per-room walls with **doorway/entrance gaps + collision**, furniture with
collision, an interior fill light, and an exit marker. `street_world.gd` streams
the interior into an **offset cell** on enter (so it never clips the batched
exterior), teleports the player just inside the entrance, and returns them to the
exterior entrance on leave — **coordinate continuity** preserved. AABB-based
`_nearest_building` (index == Python building_id) makes large buildings enterable
from their walls.

Certified in-engine: `LiveWalkIn.tscn` — enter → materialize → teleport into cell
→ leave → unload → coordinate continuity, **no node leak over 25 enter/leave
cycles**; `LiveInterior.tscn` — floor/walls/collision materialized, **no leak over
60 build/free cycles**.

## Furniture → authoritative containers (Package 4)

Each fixture carries `building_id`/`fixture_id`/`container_index` meta; E-interact
resolves `container_index → SEARCH_CONTAINER/TAKE_ITEM` over the socket. Python
owns contents; Godot renders returned state. Indoor drops bind to the building
interior (`drop_item(..., building_id)`) and persist. No duplication; illegal
actions rejected authoritatively.

Certified in-engine (`LiveInterior`): fixture→container authority, SEARCH/TAKE,
no-duplication, persistent searched-delta; the 30-step vertical exercises
take/use/drop + indoor-drop persistence + save/reload.

## Interior NPC occupancy (Package 5)

`orchestrator.building_occupants` reuses the certified embodiment: identified
citizens whose authoritative physical location resolves **inside** a building get
a deterministic interior anchor (`interiors.occupant_anchor`). Schedule-aware (a
day worker is inside their workplace at noon, home at 3am), **bounded** by the
registered citizen set, epidemic-neutral, and stable across unload/reload and
save/load. Occupant capsules carry `citizen_id`; E-interact → `INTERACT_WITH`.

Certified: `tests/test_interiors_occupancy.py` (5/5); in-engine `LiveInterior`
occupancy block (materialized, correct citizen_id, same occupant after reload);
the vertical interacts with an interior NPC.

## Regression table

| Gate | Result |
|---|---|
| Python full suite | ✅ **299 passed** (278 → +21 interior) |
| Population conservation / epidemiological determinism | ✅ (interiors + occupancy epidemic-neutral) |
| Road mobility / embodiment / identity / roster | ✅ |
| Survival/resource loop | ✅ |
| Save/load determinism | ✅ (v2; +interior deltas) |
| Godot TestRunner | ✅ 0 failures |
| Godot StreetSmoke | ✅ 0 failures |
| Live cert (LiveSmoke) | ✅ 0 failures |
| Save/destroy/reload (process destroyed) | ✅ BIT-IDENTICAL |
| Survival loop in-engine | ✅ 0 failures |
| **Interior builder/fixtures/occupancy (LiveInterior)** | ✅ 0 failures |
| **Walk-in enter/leave streaming (LiveWalkIn)** | ✅ 0 failures |
| **30-step interiors vertical (LiveVertical)** | ✅ 0 failures |
| LiveBench (render+IPC) | ✅ houston 316 agents |

## Performance (measured separately)

| Stage | Cost |
|---|---|
| Interior descriptor generation (Python) | ~0.17 ms |
| Interior state (+occupants +delta overlay) | ~1.86 ms |
| Building occupancy resolution | ~1.73 ms (bounded by registered citizens) |
| GET_INTERIOR wire size | ~2.0 KB |
| Godot interior materialization | ~1.8 ms / interior |
| Resident interior node count | 37 nodes / interior |
| Interior static memory | ~1.3 MB (batched meshes/materials) |
| Node leak over 60 build/free + 25 enter/leave | **none** (5→5, 4407→4407) |
| Save growth per modified building | **+31 B** (untouched buildings: 0 B) |
| Base living-city IPC (houston, 316 agents) | ~211 ms advance+snapshot+wire; ~3 ms Godot apply |

## Scale acceptance

* Only the building the player enters is materialized (offset cell), and it is
  freed on leave — verified no residency/leak over repeated cycles.
* Untouched buildings carry **zero** persistent mutable state (regenerated from
  seed); modified buildings store ~31 B of delta each.
* Occupancy is bounded by the registered citizen set and is a pure function.
* A solution requiring every Houston building live would be a FAIL — this is the
  opposite: one interior resident at a time, deltas only.

## Visual evidence

`docs/evidence/houston_interior.png` (enclosed walk-in room + furniture),
`docs/evidence/houston_street.png`, `docs/evidence/houston_overhead.png`.

## Known limitations (not minimized)

* **Single floor.** Upper floors of tall buildings are not generated (explicitly
  out of v1 scope); the descriptor carries `floor_count=1`.
* **AABB interior hull.** Non-rectangular footprints use a simplified axis-aligned
  hull (recorded per descriptor as `simplified_hull`), so rooms trace the bounding
  box, not the exact polygon.
* **Streamed offset cell, not in-place.** The interior is a local cell the player
  is teleported into (permitted by the brief); coordinate *continuity* is
  preserved logically (enter at doorway / return to the exterior entrance), but it
  is not a seamless in-place cutaway of the exterior mass.
* **Doors are transitions, not swinging props.** The doorway is a gap; entering/
  leaving is the "door." Locks/breaching are out of scope.
* **Occupancy iterates the full registered citizen set** (~60 in the bundles);
  for a city with thousands of registered citizens this should be pre-indexed by
  building — a clean, non-blocking follow-up.
* **In-engine interiors were run headless** (opengl3/software-mesa under xvfb);
  they pass and screenshot correctly, but were not exercised on GPU hardware here.

## Exact next frontier (recommended, not started)

Play exposes it clearly: interiors are now walkable and lootable, and NPCs stand
in them, but the NPCs are static idle occupants. The smallest high-value next
milestone is **interior NPC local movement + reaction v1** — entrance→anchor and
room-to-room navigation (Godot NavigationRegion baked per interior) plus having
occupants visibly respond to the authoritative shelter/flee reaction already in
the model. This deepens the causal-NPC dimension the slice now makes obvious,
needs no combat/vehicles/new outbreak types, and builds directly on the certified
occupancy + embodiment layers. (Combat/injury and vehicle embodiment remain the
larger forks after that.)

# Package 2 — Physical Citizen Embodiment (Findings)

**Working branch:** `claude/asphodel-embodied-survival-qlizmu`
**Verdict:** **PASS** (Python-certified; Godot client code-updated but not
engine-executed here — see the environment caveat in
`FINDINGS_P1_CANONICALIZATION.md`).

---

## Pre-change state (audited, not assumed)

Before this package, a promoted `citizen_id` had **identity, a schedule-derived
activity label, a reactive `chosen_action` label, and a torus position** — but the
torus position (`AgentZone.pos ∈ [0,L]²`) is a calibration device for the epidemic
proximity model, **not** a place in the city. The renderer (`citizen_render.gd`)
scattered that torus across the zone's extent to *approximate* a crowd. So:

* schedule said "hospital", roster said "persistent citizen", the micro agent sat
  at an arbitrary torus coordinate, and Godot drew the person on a spread of the
  zone — exactly the contradictory-locations problem the brief calls out.

There was **one** thing missing: a single canonical *physical* interpretation of
"where is citizen N, in the coordinate/building system Godot renders".

## What was built

### 2A — Authoritative spatial identity (`asphodel/embodiment.py`)

A versioned `PhysicalLocation` (schema v1): `zone`, world `x`/`y` (bundle metres,
the Godot frame), `mode` (`outdoors`/`street`/`building`/`interior`),
`building_id`, `activity`, `action`, `movement` (`stationary`/`walking`/
`commuting`), `destination_x/y`, `route_frac`. The contract *supports* interiors
/rooms without requiring an architectural simulator — `building_id` + `mode` is
enough for now.

`CitySpatialContext` loads a bundle's **static geometry once** (building
centroids, road vertices, zone centres, bbox, cell size) and answers pure
queries: `nearest_building`, `building_xy`, `nearest_road_xy`, `distance_to_road`,
`zone_center`, `approx_world_xy`.

`resolve_physical_location(...)` is the **one canonical interpretation** — a pure,
deterministic, **RNG-free** function of (schedule, hour, home/work coords, action,
static geometry). This is the load-bearing design choice: embodiment is *derived*
exactly like the M2 activity label, so it is **calibration-neutral by
construction** — it consumes no `AgentZone.rng` draw and mutates no
`pos`/`state`/compartment.

### 2B — No arbitrary positioning for identified citizens

`World.physical_location(cid)` and the per-agent `embodiment` block in
`World.snapshot()` now give every *identified* citizen a **meaningful** world
position resolved from their real home/work coordinates and schedule — never the
torus. Anonymous fill keeps an explicitly **`authoritative: false`**, documented
*approximate* position (torus mapped into the zone cell). The torus remains solely
the epidemic's internal device.

Promotion/demotion needed **no** new checkpoint: because embodiment is a pure
function of state that already persists (citizen schedule + home/work coords +
roster `chosen_action` + hour), a citizen re-uprezzes to a coherent location for
free, and a demoted citizen still has a coherent location on demand.

### 2C — Schedules are spatial

A schedule activity now implies a **destination**: sleep/leisure/idle → home
building; work → workplace building; commute → a point **snapped onto the real
road network** at the block's progress fraction (a commuter is on a real road,
not a straight-line coordinate); errand → nearest local building. Fidelity is
attention-scaled: only identified citizens are resolved to this detail; anonymous
fill is never routed, and there is no citywide per-frame pathfinding.

### 2D — Reactions are physically consequential (carefully)

`shelter` selects a **valid shelter building** (nearest to current position; home
counts) and moves the citizen there. `flee` selects an **outward/safety
destination** (marched to the map edge from the city centre) and streams the
citizen along a real road toward it. Crucially this is kept **separate from the
macro epidemic causal channel**: physical movement here changes only the *rendered
physical position*, never SEIR/shelter/flux — the certified belief-driven shelter
channel is untouched. Coupling physical movement back into exposure is explicitly
deferred to a future certified channel rather than double-counted.

### 2E — Godot consumes authoritative physical state

`citizen_render.gd` now places each drawn agent at its absolute `embodiment.
world_xy` when present (bundle metres map directly to Godot X/Z — confirmed
against `street_world.gd` building placement), falling back to the torus-spread
only when embodiment is absent. The session injects the player's authoritative
`player_location` into every snapshot/advance/start reply. Interpolation between
authoritative updates remains a presentation choice, never truth.

Bridge/session wiring: `START_WORLD` attaches the bundle's `CitySpatialContext`;
`LOAD` re-attaches it from the saved bundle so embodiment survives reload.
Save schema additively carries `home_xy`/`work_xy`/`work_zone` per citizen
(version-safe: old fields untouched, new fields optional).

## Certification — required embodiment tests

`tests/test_embodiment.py` — **all 10 required tests pass** (run directly and
under pytest):

| # | Requirement | Result |
|---|---|---|
| 1 | same city+citizen+seed+time ⇒ same physical location | ✅ |
| 2 | on-shift nurse resolves to real workplace building | ✅ |
| 3 | off-shift citizen resolves home | ✅ |
| 4 | commuter on a real road route (not synthetic) | ✅ (snapped, dist-to-road < 1 m) |
| 5 | promote→demote→re-promote spatial continuity | ✅ |
| 6 | roster citizen leaves & returns as same identity + place | ✅ |
| 7 | embodiment on/off does **not** alter epidemic outputs | ✅ (bit-identical SEIR) |
| 8 | population conservation exact (with embodiment active) | ✅ |
| 9 | replay determinism intact | ✅ |
| 10 | save/load restores physical state deterministically | ✅ |

**Vertical proof:** `tests/test_embodiment_vertical.py` executes the brief's exact
sequence for a known bundle citizen — spawn at home → commute on a real road →
work at the correct workplace building → high-belief shelter response moves them
to a valid shelter → leave focus (demote) → return → same identity + coherent
location restored. **PASS.**

Full inherited Python suite: green (see commit message / regression table in the
final report).

## Known limitations (explicit)

* **Commute route** is a straight-line interpolation *snapped* to the nearest
  road vertex, not a full street-routed path. It guarantees "on a real road" and
  is deterministic and cheap; true turn-by-turn routing for identified commuters
  is a clean follow-up (the road graph already exists in `vehicles.RoadNetwork`).
* **Interiors** are represented by `building_id` + `mode`, not geometry — Package
  3 adds the first real interior/container access.
* **Godot path not engine-executed here** (no `godot4`); the GDScript change is
  minimal, mechanical, and matches the confirmed coordinate convention, but is
  certified by inspection only in this environment.
* Physical shelter/flee movement is **presentation-authoritative only** and
  deliberately decoupled from the epidemic; a future package may introduce an
  explicit, separately-certified exposure coupling.

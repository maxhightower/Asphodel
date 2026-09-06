# Asphodel — Embodied Mobility Architecture (ASPHODEL_EMBODIED_MOBILITY_V1)

This document describes what now owns movement in Asphodel after the embodied
mobility milestone. It supersedes §5 ("Where the split still is"), §6 and §7
of `docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md` for everything that
moves, and is the reference for the next milestone (the outbreak acting on
real citizens, trips, cars and buildings). The census that preceded it is
`EMBODIED_MOBILITY_AUTHORITY_CENSUS.md`; the certification is
`EMBODIED_MOBILITY_REPORT.md`.

## 0. The chain

```
schedule (citizens.json / CitizenProfile.schedule)
   ↓ asphodel/citizens/goals.py            goal_from_schedule -> GoalStack (priority, preemption)
goals
   ↓ asphodel/citizens/runtime.py          CitizenRuntime.sync_schedule / _plan_for_active
CitizenRuntime planner
   ↓ asphodel/citizens/planning.py         build_itinerary -> Itinerary[PlanStep] (typed, §2)
itinerary
   ↓ asphodel/orchestrator.py              World.advance_seconds -> World.mobility.advance
World.step (movement clock)
   ↓ asphodel/embodied/runtime.py          MobilityRuntime: one TripExecutor per citizen
motion execution
   ↓ asphodel/embodied/executor.py         TripExecutor state machine (§3)
   ↓ asphodel/embodied/pedestrian.py       PedestrianController (WALK)
   ↓ asphodel/embodied/vehicle_control.py  VehicleController (DRIVE) on a VehicleInstance
   ↓ asphodel/embodied/parking.py          parking anchor selection (PARK)
   ↓ asphodel/embodied/pathing.py          graph route -> street polyline (the physical path)
snapshot["mobility"]  (World.mobility_snapshot)
   ↓ asphodel/bridge (protocol v4)         ADVANCE_TIME / GET_MOBILITY / MOBILITY_REPORT
Godot embodiment
   ↓ godot/scripts/embodied_mobility.gd    NEAR band -> CitizenBody / VehicleBody (follow mode)
   ↓ godot/scripts/citizen_body.gd, vehicle_body.gd   physics on the CollisionLayers matrix
physical result
   ↑ MOBILITY_REPORT {id, x, z, blocked}   -> TripExecutor.reconcile_physical (holds progress back)
```

One citizen identity (`citizen_id`), one itinerary, one movement authority.
`World.step` no longer invents where a promoted citizen is from a schedule
fraction: `World.physical_location` and `World._zone_embodiment` read the
executor of every registered citizen, and `embodiment.resolve_physical_location`
is only the FAR authority for citizens that are not registered (no home
building, no street access, or a world without a street graph).

## 1. Time: the movement clock inside World

The epidemic tick is `dt` days (0.25 d = 6 h in every bundle). Movement needs
continuous time, so `World` carries a **sub-tick clock**:

| API | meaning |
|---|---|
| `World.advance_seconds(seconds, focus_xy=None, auto_tick=True)` | advance game time; drives `World.mobility.advance` in fixed 1 s substeps; when the sub-tick clock crosses `tick_seconds` (= dt × 86400) and `auto_tick`, `World.step()` runs the epidemic tick and the remainder carries over |
| `World.current_hour()` | tick hour + sub-tick seconds (unchanged when the clock is unused) |
| `World.game_seconds` | continuous game time since start |
| `World.step()` | the epidemic tick; resets the sub-tick clock (bit-identical to before when `advance_seconds` was never called) |

The Godot `GameClock` sends `ADVANCE_TIME {seconds, focus_xy, snapshot:"mobility"}`
throttled to 10 requests/s and reads the tick back; on a tick crossing it
fetches the full snapshot. There is one time axis: game seconds. Physical
bodies must keep up with the clock's pacing (`EmbodiedMobility.time_scale` =
game seconds per real second; 24 at the default Project-Zomboid pacing, 1 in
the real-time evidence scenes). Determinism: the headless path (fixed
`advance_seconds` sequence) is deterministic and reproducible from the save;
the live Godot path passes frame deltas, so the *semantic* trip is
reproducible only to the resolution of the 1 s substep (documented boundary,
§8).

## 2. The itinerary execution contract (typed steps)

`asphodel/citizens/planning.py::PlanStep` — the planner chooses WHAT; every
step carries the parameters execution needs (no string parsing):

| kind | parameters |
|---|---|
| `LEAVE_BUILDING` | `building_id`, `anchor_xy` (compiled BUILDING_ENTRANCE), `from_node` |
| `WALK` | `from_node`, `to_node` (street-graph nodes), `route` (MobilityGraph route), `anchor_xy` (destination anchor) |
| `ENTER_VEHICLE` | `vehicle_id`, `anchor_xy` (where the car is parked) |
| `DRIVE` | `vehicle_id`, `from_node`, `to_node`, `route` (car-legal), `anchor_xy` (parking anchor) |
| `PARK` | `vehicle_id`, `to_node` (`park:<anchor index>`), `anchor_xy` |
| `EXIT_VEHICLE` | `vehicle_id` |
| `ENTER_BUILDING` | `building_id`, `anchor_xy`, `to_node` |
| `DO_ACTIVITY` | `activity`, `building_id` |

`Itinerary.to_state()/from_state()` serialize the plan **verbatim** (nodes,
segments, cost) so a save restores the exact route, not a re-route under
possibly changed costs.

Planner changes that closed Split A:

* `CitizenRuntime.note_situation(node, inside_building, in_vehicle, vehicle_node)`
  — the executor reports where the citizen physically is; every (re)plan
  starts from reality (`build_itinerary(start_inside_building=…,
  start_in_vehicle=…)`).
* A `DO_ACTIVITY`/`IDLE` goal at a node the citizen is not at first travels
  there with the activity appended — the activity begins because the citizen
  **arrived** (§15), never because the clock said so.
* `parking_resolver` — the runtime chooses the parking anchor near the
  destination at plan time (§5); `node_meta` carries building ids and anchors
  for the nodes the citizen plans between; `vehicle_id` names the persistent
  car.
* `GoalStack.seq` — goal ids are per-citizen sequences, reproducible across
  save/load (the module counter was process-global).

## 3. Execution: TripExecutor (asphodel/embodied/executor.py)

Explicit embodiment state machine (§9 of the brief), identity preserved at
every transition:

```
INSIDE_BUILDING → ON_FOOT → APPROACHING_VEHICLE → ENTERING_VEHICLE → IN_VEHICLE
   → DRIVING → PARKED → EXITING_VEHICLE → ON_FOOT → INSIDE_BUILDING → DOING_ACTIVITY
(TRIP_FAILED is the bounded terminal of the failure policy)
```

Per step:

| step | executes as |
|---|---|
| LEAVE_BUILDING | 3 s dwell, position = entrance anchor, `inside=False`; fails "cannot leave building" without an anchor |
| WALK | `PedestrianController` over `PhysicalPath.from_route` (1.4 m/s, yields to a moving vehicle ≤ 4 m ahead, stops at the destination anchor); blocked > 20 s → replan |
| ENTER_VEHICLE | vehicle must exist, be undriven, not a wreck; ≤ 6 m: 2.5 s dwell, `driver = citizen`, parking released; farther (≤ 30 m) walks straight to the door; else "vehicle unavailable" → walk fallback |
| DRIVE | `VehicleController` on the VehicleInstance (`assign_route`), `fidelity = PHYSICAL_CONTROLLED` when a body exists else `ROUTE_SIMULATED`; road closed ahead + blocked > 45 s → replan |
| PARK | 1.5 s dwell, must be ≤ 6 m from the anchor (else failure), `parked_location`, engine off, anchor occupied |
| EXIT_VEHICLE | 2 s dwell, citizen steps 1.3 m beside the car, `driver = None` |
| ENTER_BUILDING | ≤ 6 m from the entrance anchor (approach ≤ 30 m), 2 s dwell, `building_id` set, `inside=True` |
| DO_ACTIVITY | only when inside the step's building; `activity` = the scheduled one, `arrived=True` |

Nothing teleports: every position change is a controller integration, a
bounded straight approach (≤ 30 m at walking speed) or a transition that
moves ≤ 3 m. Failures (§16) go to `MobilityRuntime.on_failure`: vehicle
unavailable → walk this trip; other failures → wait 120 s and replan; more
than 3 failures on one goal → `TRIP_FAILED` with the reason exposed in the
snapshot (`failure`, `trip_failed`) until the next goal.

## 4. Route → physical path (asphodel/embodied/pathing.py)

Anchors are attached to the street graph as **access nodes**
(`attach_anchor`): node `ent:<bid>` / `park:<i>` at the anchor, joined to the
two junctions of the street it projects onto by connector segments
`conn:<key>:0/1` whose polyline is `[anchor, kerb projection] + the street's
own polyline to the junction`. One-way streets produce one-way connectors (a
car cannot leave a driveway against traffic; pedestrians get a foot twin).
Connectors are not indexed for nearest-segment queries and inherit the
street's class/speed. The physical path of a leg is exactly
`route_polyline` of its graph route (`PhysicalPath.from_route`), with one
geometric simplification: two anchors on the same street connect along that
street between their kerb points instead of via the junction. Graph route,
physical road and rendered road are therefore one geometry (Gate C).

## 5. Parking (asphodel/embodied/parking.py)

Candidates: the compiled `PARKING_ANCHOR` / `DRIVEWAY_ANCHOR` rows within
220 m of the destination entrance, nearest first, deterministic ties by
index. Valid iff reachable (kerb projection on a car street ≤ 60 m), not
inside a footprint, ≥ 5 m from every entrance, ≥ 3 m from static chunk
vehicle placements (loaded lazily per chunk) and from live parked
`VehicleInstance`s, not occupied. Rejections are counted and reported. The
chosen anchor becomes the DRIVE leg's destination node and the PARK step's
anchor; the car physically reaches it. No candidate → the trip plans on foot
(explicit `no_parking_for_vehicle` event), never a car at the door.

## 6. Vehicles

A citizen with `keys`/`car_keys` in its inventory owns `VehicleInstance
"veh:<citizen_id>"` (`owner = citizen_id`), spawned parked at a valid anchor
near the building the day starts in. The same instance is entered, driven
(`assign_route`, `distance_along` written by the controller,
`current_segment` feeds `TrafficReconciler` congestion), parked, exited,
saved, loaded, promoted (a `VehicleBody` with `semantic_id == vehicle_id`)
and demoted. `driver`, `owner`, `parked_location`, `fidelity` are explicit.

`VehicleController` V1: accelerate to the segment limit (≤ 16 m/s), brake for
curvature ahead, IDM-lite following (3 m + 1.4 s headway) behind a vehicle
projected onto the path within 60 m, yield at a junction (graph degree ≥ 3)
to the vehicle with the earlier ETA (deterministic tie by id, 8 s deadlock
breaker), stop before a segment closed to the mode, stop at the destination.
Roads are never re-planned in the controller or in Godot.

## 7. LOD (asphodel/embodied/runtime.py + lod/entity.py)

| band | who | cost | representation |
|---|---|---|---|
| FAR / abstract (unregistered) | citizens without a home building / street access, and worlds without a graph | none | `resolve_physical_location` schedule state |
| ABSTRACT (overflow) | registered citizens beyond `route_radius` once more than `max_active` (256) are registered | none while frozen; catch-up integration on activation (5 s substeps) | last executed situation |
| ROUTE_SIMULATED (MID) | every registered citizen | ~0.1 ms/citizen/game-minute (0.75 at the commute peak) | executor position; MultiMesh crowd in Godot |
| PHYSICAL (NEAR) | within `physical_radius` (150 m, 40 m hysteresis) of the focus | Godot body + reports | `CitizenBody` (on foot) / `VehicleBody` (driving or parked nearby) |

Promotion creates the body at the authoritative pose; demotion frees it and
the executor keeps integrating. Identity (`cit:<id>`, `veh:<id>`) is the body
name; one body per identity; a citizen inside a building or a car has no
citizen body. Transitions are logged (`MobilityRuntime.transitions`).
The `LODBand.NEAR_SIMPLIFIED` band is folded into ROUTE_SIMULATED in V1.

## 8. Physical authority contract (Godot ↔ Python)

* Python integrates the **intended** progress every substep and publishes the
  pose a NEAR entity should be at (`x, y, heading, speed`) plus the route
  ahead (`routes["cit:<id>"]`).
* `EmbodiedMobility` puts each NEAR entity in **follow mode**: the body moves
  toward the authoritative pose under `move_and_slide` with the collision
  matrix; speed is capped at 1.5× the plan speed (× `time_scale`), so it
  closes small lags and never overshoots.
* Every 0.25 s Godot sends `MOBILITY_REPORT` with each body's position and
  `blocked` (no progress for ≥ 1 s while more than the leash behind). Python
  projects the body onto the path and **clamps progress to the body + leash**
  (3 m on foot, 4 m driving): physics can hold a trip back, never push it
  ahead; blocked time feeds the failure policy (replan).
* Non-deterministic boundary: the live Godot frame deltas and physics results
  make the NEAR trip reproducible only to substep resolution; the semantic
  itinerary and the MID progress are deterministic.

This is the narrowest correct V1 authority: no silent divergence (the report
reconciles every 0.25 s and the leash bounds the gap), no Godot-side
planning, and no Python-side pretence that a wall is not there.

## 9. Bridge protocol v4

| command | fields | reply |
|---|---|---|
| `ADVANCE_TIME` | `seconds`, `focus_xy?`, `snapshot: "mobility" \| true \| absent` | summary (`tick`, `hour`, `game_seconds`, `ticks_crossed`) + `mobility` block or full `world` |
| `MOBILITY_REPORT` | `bodies: [{id, x, z, blocked}]`, `dt` | `applied` count |
| `GET_MOBILITY` | `routes?` | `mobility` block |
| `SET_FOCUS` | `zones`, `xy?` | as before |
| `START_WORLD` | `mobility?` (default true) | summary gains `mobility_enabled`, `hour`, `game_seconds` |

The movement block (`MobilityRuntime.snapshot`): `citizens[]` (position,
heading, speed, state, activity, building_id, vehicle_id, step, step_index,
progress, destination, band, goal, failure, blocked), `vehicles[]` (position,
heading, speed, fidelity, driver, owner, parked, progress, segment, band),
`near[]`, `routes{}`.

## 10. Persistence (save v3)

`save.world_state` adds `world.subtick_s` and a `mobility` block:
per citizen the planner state (current node, situation, itinerary verbatim,
goals + sequence, node meta) and the executor state (state, position,
building, vehicle, step index, controllers' progress, distances, trace tail);
vehicles; parking occupancy and parking nodes; per-segment congestion and
obstructions. `load_world` stores it as pending; `World.enable_mobility`
restores it once the session has re-attached the bundle's street graph. A v2
save (no block) loads with mobility disabled. Continuation after reload is
byte-identical (tests/test_embodied_saveload.py, test_embodied_mobility_day.py).

## 11. What is presentation-only now

* `godot/scripts/traffic.gd` — EXPLICIT_NONCANONICAL_PRESENTATION: ambient
  movers on the first-person StreetScene only, no identity, no collision,
  never reported. Not on the default scene.
* `citizen_render.gd` — the MultiMesh crowd draws `world_xy` from the snapshot
  (now executor positions for registered citizens); its interpolation is
  presentation.
* Static chunk vehicle placements (`exterior_world.gd`) — decorative parked
  props with no identity; parking selection treats them as occupied space.
* `living_city.py` / `playback.json` / `living_city.gd` — a headless
  demonstration of the traffic layer; not the movement authority.

## 12. Known limits (V1)

* Physical-crash escalation (`VehicleBody._on_impact` → `PHYSICAL_CRASH` →
  wreck → `MobilityObstruction`) is not wired; impacts are counted and the
  blocked report holds the simulation.
* Pedestrians walk the street polylines (kerb-side offsets/sidewalk
  geometry are not modelled); a pedestrian on a road yields to cars.
* Materialization safety (`lod/materialize.py`) is not applied at body spawn;
  anchors are outside footprints by construction, and a body spawned into
  geometry is held by the blocked report rather than teleported.
* Citizens whose home entrance is > 60 m from a foot street are not embodied
  (explicit `unregistered` event; Houston 2/60, Madisonville 7/60).
* Routing is pure-Python Dijkstra (30–200 ms per cold route); fine for the
  bounded canonical population, not for hundreds of simultaneous replans.

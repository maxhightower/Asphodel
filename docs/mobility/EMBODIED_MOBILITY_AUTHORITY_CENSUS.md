# Embodied Mobility — Authority Census

**Question this document answers:** for a citizen or a vehicle, *which line of code
decides where it is and how it moves* — and is that line the only one that does?

**Method.** Every path below was read in the tree at
`claude/asphodel-embodied-mobility-v1-6gl4a8` (== `origin/main` @ `bee2f18`) and
every call site was grepped. Nothing was inferred from documentation; where the
prose in a docstring disagrees with the code, the code is reported and the
disagreement is noted.

**Context read first:** `docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md`
§4 (Mobility), §5 (Citizen lifecycle), §6 (Vehicle lifecycle), §7 (LOD) and
`docs/convergence/ASPHODEL_CONVERGENCE_REPORT.md` "Remaining splits" (items 1
and 2 — planner ↔ World, and vehicles in the playable scene). This census is the
line-level substantiation of those two items, plus three splits they do not name.

**Classification vocabulary**

| tag | meaning |
|---|---|
| `CANONICAL` | this path is the intended single authority for what it decides, and something in the shipping runtime actually calls it |
| `PRESENTATION_ONLY` | it moves pixels; it must never be read back as truth |
| `LEGACY` | superseded by a canonical path, still reachable |
| `DUPLICATE_AUTHORITY` | two paths independently decide the same fact, and can disagree |
| `DEV_ONLY` | bake/tool/screenshot path, not in the play loop |
| `TEST_ONLY` | only pytest / a Godot gate constructs it |
| `DEAD` | nothing constructs or calls it |

**Tier vocabulary** — the bands *actually named in code* (see §6):
`FAR` = macro ledger / `LODBand.ABSTRACT`; `MID` = promoted `AgentZone` +
`PhysicalLocation` + `VehicleInstance.advance_far` / `ROUTE_SIMULATED`;
`NEAR-physical` = `CharacterBody3D`/`CharacterBody3D` bodies under Godot physics
(`LODBand.PHYSICAL`).

---

## 1. Summary table

### 1a. Citizen position / activity

| path (file:lines) | decides | tier | class | evidence (call sites) | note |
|---|---|---|---|---|---|
| `asphodel/orchestrator.py:390-454` `World.step` | tick advance, membership, then activity + reaction labels | FAR+MID | CANONICAL | `bridge/session.py:184-185` (`ADVANCE`), `World.run` 456-458, all Python tests | **Never sets any position.** It calls `_update_membership`, the macro step, `_update_zone_activity`, `_update_zone_reactions`. No itinerary, no route, no `PhysicalLocation`. |
| `asphodel/orchestrator.py:794-809` `_update_zone_activity` | activity label from `schedule × hour` | MID | CANONICAL | `World.step:435`, `_promote_zone:699` | Pure label; `npc.activity_at_hour` → `citizen._current_block`. |
| `asphodel/orchestrator.py:811-837` `_update_zone_reactions` | `chosen_action` (shelter/flee/seek/signature) | MID | CANONICAL | `World.step:436`, `_promote_zone:701` | Per-citizen RNG keyed `[cid, tick, seed]`, deliberately not `zone.rng`. This is the *only* input by which behaviour becomes movement (embodiment §2 branch). |
| `asphodel/orchestrator.py:293-315` `World.physical_location` | the one canonical `PhysicalLocation` for one citizen | MID | CANONICAL | `World.building_occupants:266`; `World._citizen_action`; `bridge/session.py:339-348` `_inject_player_location`; `tests/test_embodiment*.py` | Derived, RNG-free; recomputed on demand, never stored. |
| `asphodel/orchestrator.py:535-580` `_zone_embodiment` | per-agent `world_xy` / `mode` / `building_id` / `movement` for the snapshot | MID | CANONICAL | `World.snapshot:532` only | Loops every slot of every promoted zone and calls `resolve_physical_location` per agent per snapshot. This is what Godot draws. |
| `asphodel/embodiment.py:393-520` `resolve_physical_location` | x, y, mode, building_id, movement, destination, route_frac | MID | CANONICAL | `orchestrator.py:309`, `:558`; `tests/test_embodiment.py`, `test_living_city_vertical.py:180-187` | The single citizen-position function in the shipping loop. |
| `asphodel/embodiment.py:438-457` (commute branch) | commute position from **schedule progress**, straight-line lerp then road-snap | MID | CANONICAL but **Split A** | reached from both call sites above | Quoted in §2. This is the motion model `CitizenRuntime` was meant to replace. |
| `asphodel/embodiment.py:361-371` `_commute_point` | lerp(home,work,frac) → `nearest_road_xy` | MID | CANONICAL | `resolve_physical_location:454` | The snap is a *projection*, not a route: the citizen teleports between unrelated streets as `frac` grows. |
| `asphodel/embodiment.py:297-314` `nearest_road_xy` | exact projection onto the nearest `streetmap.json` segment | MID | CANONICAL | `_commute_point:368`, flee branch `:505`, `distance_to_road:317` | Uses `MobilityGraph.nearest_segment_point`; falls back to nearest polyline vertex. |
| `asphodel/embodiment.py:478-496` (shelter branch) | overrides position → nearest building; sets `WALKING` | MID | CANONICAL | as above | Reaction is physically consequential but instantaneous — no path, no travel time. |
| `asphodel/embodiment.py:497-511` (flee branch) | moves **50 % of the remaining distance to the map edge in one tick**, road-snapped | MID | CANONICAL | as above | `fx = x + (dest.x - x) * 0.5`. A fleeing citizen crosses kilometres per tick. |
| `asphodel/embodiment.py:186-249` `CitySpatialContext.from_bundle_dir` | the static geometry every position resolves against | — | CANONICAL | `bridge/session.py:118-122` (START_WORLD), `:377-380` (LOAD), tests | Loads `buildings.json` + `MobilityGraph.load`; ~9 s Houston (recorded debt). |
| `asphodel/orchestrator.py:251-277` `building_occupants` | who is *inside* a building + their interior anchor | MID | CANONICAL | `World.interior_state:248`; `bridge` GET_INTERIOR; `interior_builder.gd:136-143` | Iterates **every registered citizen** and calls `physical_location` for each — O(citizens) per interior query. |
| `asphodel/orchestrator.py:685-702` `_promote_zone` | which zone becomes agents; agent torus size | FAR→MID | CANONICAL | `_update_membership:642` | Promotion creates `AgentZone` slots; it does **not** create positions — see §2. |
| `asphodel/orchestrator.py:704-726` `_assign_citizens` | which citizen id lands on which agent slot | FAR→MID | CANONICAL | `_promote_zone:697` | Roster members first, then ascending id. RNG-free. |
| `asphodel/orchestrator.py:839-853` `_demote_zone` | drops the zone; checkpoints roster `chosen_action` only | MID→FAR | CANONICAL | `_update_membership:644` | Positions are *not* checkpointed because they are derived. |
| `asphodel/micro.py:307-314` `AgentZone._move` | `zone.pos` — a Brownian walk on an L×L torus | MID (epidemic only) | CANONICAL **for contact**, `PRESENTATION_ONLY` for space | `AgentZone.step:433+` | `zone.pos` is contact-mixing geometry, not a place in the city. It reaches the client (`snapshot` `positions`) and `citizen_render._world_pos` falls back to it when `world_xy` is null. |
| `asphodel/embodiment.py:268-279` `approx_world_xy` | approximate world position for **anonymous fill** | MID | CANONICAL (documented-approximate) | `_zone_embodiment:573` | Maps the torus into the macro cell. Explicitly not authoritative. |
| `asphodel/osm_city/citizens.py:98-145` `_spawn_point` | the citizen's `spawn_xy` written into `citizens.json` | bake | **DUPLICATE_AUTHORITY** | `build_citizen_record` `:158`; consumed by `street_world.gd:764-768`, `isometric_world.gd:337-341` | A **second** commute-progress model — see §2. |
| `asphodel/osm_city/citizens.py:86-95` `_commute_frac` | commute progress fraction at bake time | bake | DUPLICATE_AUTHORITY | `_spawn_point:124` | Byte-for-byte the same formula as `embodiment.py:440-445`, on a different clock (`citizen.spawn_hour`). |
| `asphodel/osm_city/world_from_compiled.py:227-259` `SpawnAnchors.commute_point` | commute position by walking the **routed** polyline | bake | DUPLICATE_AUTHORITY | `citizens.py:124` | The *good* commute model (real route, footprint-avoiding) — and it is the one the live sim does **not** use. |
| `asphodel/osm_city/world_from_compiled.py:197-226` `SpawnAnchors.route` | a third routing implementation (over spawn-anchor adjacency) | bake | LEGACY / DUPLICATE_AUTHORITY | `commute_point:230` | Not `MobilityGraph.route`. |
| `asphodel/citizens/runtime.py:74-83` `sync_schedule` | active goal from schedule, then replan | MID (intended) | **TEST_ONLY** | `tests/test_citizens_runtime.py`, `tests/test_living_city.py`, `tests/test_living_city_vertical.py:127,209` — **no `asphodel/` or `godot/` caller** | Split A: the designated planner has zero production call sites. |
| `asphodel/citizens/runtime.py:115-138` `_plan_for_active` | mode choice + itinerary for the active goal | MID (intended) | TEST_ONLY | `_reselect:113` | |
| `asphodel/citizens/runtime.py:141-153` `on_blockage` | strategic replan after a local nav failure | MID (intended) | TEST_ONLY | tests only; the `CitizenBody.blocked` signal that should drive it is only wired in `godot/tests/nav_gate.gd:111-123` | |
| `asphodel/citizens/planning.py:98-147` `build_itinerary` | the 8-step plan: leave → walk → enter vehicle → drive → park → exit → walk → enter | MID (intended) | TEST_ONLY | `runtime._plan_for_active:123,126`; `replan_travel:161,168`; tests | Produces the *only* representation in the codebase of parking and building transitions. Consumed by nothing that runs. |
| `asphodel/citizens/planning.py:150-173` `replan_travel` | reroute, or abandon the car and walk | MID (intended) | TEST_ONLY | `runtime.on_blockage:145` | |
| `asphodel/citizens/goals.py:28-35,` `GoalStack` | goal priority / preemption | MID (intended) | TEST_ONLY | `runtime.py` | |
| `godot/scripts/citizen_render.gd:127-269` `render_snapshot` | which agents are drawn, their transforms, avatar promotion | NEAR (draw) | PRESENTATION_ONLY | `isometric_world.gd:440`, `street_world.gd:938` | Caps at `MAX_RENDER=320`, `MAX_AVATARS=24`. |
| `godot/scripts/citizen_render.gd:272-281` `_world_pos` | falls back to `zone.pos` torus coords when `world_xy[i]` is null | NEAR (draw) | PRESENTATION_ONLY | `render_snapshot:179` | The one place torus coordinates become metres on screen. |
| `godot/scripts/citizen_render.gd:106-114` `_process` + `_write_transforms` | interpolation between snapshots | NEAR (draw) | PRESENTATION_ONLY | engine | Documented as presentation, correct. |
| `godot/scripts/citizen_body.gd:77-100` `_physics_process` | actual physical citizen motion under collision | NEAR-physical | **TEST_ONLY** | `godot/tests/nav_gate.gd:59`, `physics_gate.gd:194`, `convergence_gate.gd:108`. **No `godot/scripts/*` or `*.tscn` instantiates it.** | Split A's other half: the body exists, nothing spawns it in a playable scene. |
| `godot/scripts/citizen_body.gd:65-71` `set_route` | the body's only route input | NEAR-physical | TEST_ONLY | gates only | Takes `Array[Vector3]`; nothing converts an `Itinerary` into one. |
| `godot/scripts/isometric_player.gd:58-94` | the **player** citizen's position | NEAR-physical | CANONICAL (player only) | `IsometricWorld.tscn` | The player is the only citizen in the game whose position is decided by physics. |
| `godot/scripts/first_person.gd` (via `street_world.gd:790`) | player position, legacy scene | NEAR-physical | LEGACY | `StreetScene.tscn` | |
| `godot/scripts/interior_builder.gd:136-143,161-180` `_occupant` | interior NPC placement from `descriptor.occupants` | NEAR (draw) | PRESENTATION_ONLY | `isometric_world.gd`/`street_world.gd` interior entry | Anchors come from Python (`interiors.occupant_anchor`); GDScript only draws. |

### 1b. Vehicle position / route

| path (file:lines) | decides | tier | class | evidence | note |
|---|---|---|---|---|---|
| `asphodel/transport/instances.py:121-129` `assign_route` | route + polyline + reset progress; `ABSTRACT→ROUTE_SIMULATED` | MID | CANONICAL (design) / DEV+TEST (reality) | `living_city.py:134`, `traffic.py:37`, `tests/test_transport.py`, `test_living_city_vertical.py:147`, `tools/city_matrix.py:196` | No gameplay call site. |
| `asphodel/transport/instances.py:156-173` `advance_far` | vehicle distance along route from segment cost | MID | same | `traffic.TrafficReconciler.step:66`, `living_city.py:149`, tests | Congestion-aware; the only vehicle motion integrator in Python. |
| `asphodel/transport/instances.py:139-143` `position` | vehicle world xy | MID | same | `living_city.py:59`, `traffic.materialize_position:75` | |
| `asphodel/transport/instances.py:185-189` `reconcile_from_physical` | MID progress **from** NEAR physics (physics wins) | NEAR→MID | TEST_ONLY | `traffic.reconcile_physical:71`; `tests/test_transport.py:56-64`, `test_convergence_gates.py:294-302` | The seam is implemented and proven; nothing in the engine ever calls the other side. |
| `asphodel/transport/instances.py:191-207` `to_wreck` | parked location + `PERSISTENT_WRECK` + a `MobilityObstruction` | MID | TEST_ONLY | `tests/test_transport.py:66-89` | |
| `asphodel/transport/traffic.py:51-61` `update_congestion` | per-segment congestion (BPR) that feeds every route cost | FAR | DEV+TEST | `living_city.py:150`, `traffic.step:67`, tests | The FAR↔MID feedback loop exists and is exercised only in `simulate_commute` and pytest. |
| `asphodel/mobility/graph.py:222-267` `MobilityGraph.route` | the route (Dijkstra over live dynamic costs) | all | CANONICAL | `planning.build_itinerary:118,124,131,137`; `living_city.py:123,125`; tests; `tools/city_matrix.py` | ~180 ms median on Houston (recorded debt). |
| `asphodel/mobility/segments.py:152-166` `traverse_cost` | edge cost incl. congestion + blockage; `inf` = closed | all | CANONICAL | `graph.route:246`, `instances.advance_far:167` | The single place closures become reroutes. |
| `asphodel/mobility/graph.py:271-296` `apply_obstruction` / `_recompute_segment` | which segments are blocked/closed | all | CANONICAL | `tests/test_transport.py:66-89`, `test_living_city.py:90-99` | No production caller creates an obstruction; nothing in `World` produces wrecks or fires as obstructions. |
| `asphodel/transport/instances.py:35-51` `route_polyline` | route → renderable geometry | MID | CANONICAL | `living_city.py:129,134`, `assign_route:123` | The only route→geometry conversion in Python. |
| `asphodel/living_city.py:119-136` (trip build) | each citizen's mode, route, and car identity `veh:<cid>` | MID | DEV_ONLY | `tests/test_living_city_sim.py`, `test_convergence_gates.py:236-239`, `godot/tests/living_city.gd` | Calls `graph.route` **directly**; see §2 for the docstring discrepancy. |
| `asphodel/living_city.py:142-175` (step loop) | positions written into `playback.json` frames | MID | DEV_ONLY | as above | Pedestrians move at a flat 1.4 m/s along the route; cars via `advance_far`. |
| `asphodel/vehicles.py:296-352` `assign_traffic` | aggregate trip volumes and congested times | FAR | LEGACY | `citizen.py:1400` (`congestion_report`, CLI display), `tests/test_vehicles.py` | Not an entity model; header at `vehicles.py:25-29` says so. |
| `asphodel/vehicles.py:154-193` `choose_commute` | a citizen's `commute_mode` + `vehicle` string | bake | CANONICAL (as a *label*) | `citizen.py:709` | This label is what `living_city.py:99-101` re-reads as "has car keys". It is never a `VehicleInstance`. |
| `asphodel/vehicles.py:199-266` `RoadNetwork` | a fourth graph model over the citizen-bake `StreetMap` | bake | LEGACY | `citizen.py:588`, `tests/` | Superseded by `MobilityGraph` (arch §4 authority table). |
| `asphodel/travel_events.py:156-181` `select_travel_event` | a narrative event for a trip; **no position** | bake | LEGACY | `citizen.py:1019` | Decides nothing spatial. |
| `godot/scripts/traffic.gd:137-171` `_process`/`_place` | ambient car positions along `roads.json` polylines | NEAR (draw) | PRESENTATION_ONLY / LEGACY | `street_world.gd:589-598` (`StreetScene.tscn` only; **not** `IsometricWorld.tscn`) | 900 movers, no identity, no collision, respawn on a random road at the end (`:166-171`). Self-declared legacy at `traffic.gd:3-7`. |
| `godot/scripts/exterior_world.gd:1972-2064` `_build_t3` | **parked** vehicle placement in the playable scene | NEAR (draw) | PRESENTATION_ONLY | `_build_chunk` T3 tier | Reads `chunk["vehicles"]` rows `[kind, x, z, rot_deg, variant]`; emits one `MultiMesh` per `kind:variant` and returns `"collisions": 0` (`:2064`). **Parked cars have no collider and no id.** |
| `asphodel/world_source/chunks.py:48,109` + `schema.py:106,185` | which parked vehicles exist and where (bake) | bake | CANONICAL (for props) | compile pipeline | Vocabulary shared with `prop_meshes.gd`; a placement is a decoration record, not an entity. |
| `godot/scripts/vehicle_body.gd:40-52` `_physics_process` | physical vehicle motion, substepped | NEAR-physical | TEST_ONLY | `godot/tests/physics_gate.gd:199`, `convergence_gate.gd:125`. No scene instantiates it. | Its only input is the public var `drive_velocity` (`:18`) — there is no route API, no target, no arrival signal, no position report. See §3. |
| `godot/scripts/vehicle_body.gd:54-58` `_on_impact` | crash → `PHYSICAL_CRASH` | NEAR-physical | **DEAD** | nothing; body is `pass` | The documented crash→wreck→obstruction chain terminates in an empty function. |
| `godot/scripts/mobility_loader.gd:147-183` `route` | in-engine Dijkstra over `streetmap.json` | NEAR | TEST_ONLY | `godot/tests/physics_gate.gd:171-191` | Mirrors `MobilityGraph`; no scene constructs a `MobilityLoader`. |
| `godot/tests/living_city.gd:182-222` `_draw_frame` | playback rows → `MultiMesh` markers | NEAR (draw) | DEV_ONLY | `LivingCity.tscn` (screenshot harness) | Cars are orange boxes; peds blue. No bodies. |

### 1c. LOD / persistence / bridge

| path (file:lines) | decides | tier | class | evidence | note |
|---|---|---|---|---|---|
| `asphodel/orchestrator.py:620-644` `_update_membership` | which zones are promoted (hysteresis + focus + budget) | FAR↔MID | CANONICAL | `World.step:392` | Distance is **not** an input — promotion is by infectious fraction and player focus (`handoff.should_promote/should_demote`). |
| `asphodel/orchestrator.py:646-684` `_apply_budget` | hard agent cap | FAR↔MID | CANONICAL | `_update_membership` | |
| `asphodel/lod/entity.py:62-85` `LODController.band_for` | the distance bands + hysteresis | all | **TEST_ONLY** | `tests/test_lod.py` only | The distance-banded LOD model the architecture describes is not wired to `World` or to Godot. |
| `asphodel/lod/entity.py:97-106` `EntityLODState.transition` | id + payload preservation across bands | all | TEST_ONLY | `tests/test_lod.py:37-48` | |
| `asphodel/lod/materialize.py:89-132` `resolve_materialization` | *whether* a body may spawn at a pose, or defer | MID→NEAR | TEST_ONLY | `tests/test_lod.py`, `tests/test_proving_ground.py` | The "never spawn inside a wall" guarantee has no engine caller. |
| `godot/scripts/exterior_world.gd` T1/T2/T3 tiers | chunk streaming + which chunks get colliders | NEAR | CANONICAL | `isometric_world.gd:299-307` focus timer | The *only* distance-banded LOD actually running. Concerns terrain, not agents. |
| `asphodel/save.py:105-123` `agentzone_state` | persists `pos`, `state`, `citizen_id`, `activity`, `chosen_action`, `rng` | MID | CANONICAL | `world_state:283` | `pos` here is the torus, not the city. |
| `asphodel/save.py:211-231` `_citizen_records` | persists `home_xy/work_xy/home_zone/work_zone/home_building_id/work_building_id/schedule` | — | CANONICAL | `world_state:285` | See §5 for the complete list of what is *absent*. |
| `asphodel/bridge/session.py:175-191` `_cmd_advance` | ticks + optional embedded snapshot | — | CANONICAL | `sim_bridge.gd:88-98` | |
| `asphodel/bridge/session.py:339-348` `_inject_player_location` | adds `player_location` to a snapshot | MID | CANONICAL | `_cmd_snapshot:337`, `_cmd_advance:189` | The only per-citizen `PhysicalLocation` that crosses as a first-class object. |
| `godot/scripts/game_clock.gd:123-152` `_advance`/`_advance_world` | when the sim ticks | — | CANONICAL | `_process:115-120` | Tick cadence, §4. |

---

## 2. Split A — Planner ↔ World

### 2.1 What `World.step` actually does with a promoted citizen

`World.step` (`asphodel/orchestrator.py:390-454`) has five numbered phases. None
of them is a movement phase:

```python
    def step(self) -> WorldTick:
        # --- 1. membership: decide the promoted set (hysteresis + focus) -----
        self._update_membership()
        ...
        # --- 3+4. agent internal step, then write-back & realise flux --------
        for z, zone in self.promoted.items():
            ...
            zone.step()
            ...
            zone.reconcile_to_counts(largest_remainder_counts(new_float))

        # --- 4b. refresh citizen activity labels for the new in-game hour -----
        if self.citizens:
            for z, zone in self.promoted.items():
                self._update_zone_activity(z, zone)
                if self.reactions_enabled:
                    self._update_zone_reactions(z, zone)
            self._update_roster_promotion()
```
(`orchestrator.py:390-437`)

`zone.step()` moves `zone.pos` — but that is the Brownian contact torus
(`micro.py:307-314`), an L×L square sized from the calibrated reference density
(`_promote_zone:693-694`), not a place in Houston. So after `World.step` returns,
**no citizen has a city position at all.** Positions do not exist as state.

### 2.2 Where a promoted citizen's position is computed

Only at read time, in two places, both of which call the same pure function:

* `World.snapshot` → `_zone_embodiment` (`orchestrator.py:535-580`), per agent
  slot, per snapshot;
* `World.physical_location(cid)` (`orchestrator.py:293-315`), per citizen, on
  demand (player location, `building_occupants`).

`_zone_embodiment`'s loop is the hot path:

```python
        for slot in range(n):
            cid = int(zone.citizen_id[slot])
            if cid >= 0 and cid in self.citizens:
                home_xy, work_xy, hz, wz = self._spatial.get(
                    cid, (None, None, None, None))
                home_bid, work_bid = self._buildings.get(cid, (None, None))
                loc = embodiment.resolve_physical_location(
                    citizen_id=cid, schedule=self._schedules.get(cid, []),
                    hour=hour, home_xy=home_xy, work_xy=work_xy,
                    home_zone=hz, work_zone=wz,
                    action=npc.action_name(int(zone.chosen_action[slot])),
                    zone=z, ctx=ctx,
                    home_building_id=home_bid, work_building_id=work_bid)
                world_xy[slot] = [loc.x, loc.y]
```
(`orchestrator.py:552-568`)

Note what is *not* passed: no previous position, no route, no itinerary, no
`dt`. `resolve_physical_location` is a function of `(citizen, hour, action,
static geometry)` alone. Position is therefore **stateless and history-free**:
a citizen's location at tick *n* has no causal relationship to its location at
tick *n−1* beyond both being functions of the clock.

### 2.3 The schedule-progress formula

```python
    elif activity == "commute":
        # Progress through the commute block (handle past-midnight wrap).
        if block is not None and block.end_hour > block.start_hour:
            h = hour % 24.0
            if block.end_hour > 24.0 and h < block.start_hour:
                h += 24.0
            route_frac = min(1.0, max(0.0, (h - block.start_hour)
                                      / (block.end_hour - block.start_hour)))
        else:
            route_frac = 0.5
        # Direction: a "commute" block whose destination is work runs home->work;
        # one whose destination is home runs work->home. We infer from the block's
        # location label when present, else assume morning outbound.
        loc = (block.location if block is not None else "") or ""
        outbound = not any(t in loc.lower() for t in ("home", "h"))  # heuristic
        a, b = (home_anchor, work_anchor) if outbound else (work_anchor, home_anchor)
        x, y = _commute_point(a, b, route_frac, ctx)
        mode = LocationMode.STREET
        movement = Movement.COMMUTING
        destination = b
```
(`asphodel/embodiment.py:438-457`)

and

```python
def _commute_point(home_anchor, work_anchor, frac, ctx):
    lx = home_anchor[0] + (work_anchor[0] - home_anchor[0]) * frac
    ly = home_anchor[1] + (work_anchor[1] - home_anchor[1]) * frac
    if ctx is not None:
        snapped = ctx.nearest_road_xy((lx, ly))
        if snapped is not None:
            return snapped
    return (lx, ly)
```
(`asphodel/embodiment.py:361-371`)

Three consequences, each observable:

1. **The path is a straight line, projected.** The citizen is always on *some*
   real street (`nearest_road_xy` is an exact segment projection,
   `embodiment.py:297-314`), but consecutive ticks can project onto streets that
   are not connected to each other. There is no continuity guarantee and no
   graph traversal — `MobilityGraph.route` is never called on this path.
2. **`outbound` is a substring heuristic that is almost always true.** Line 452:
   `outbound = not any(t in loc.lower() for t in ("home", "h"))`. The token
   `"h"` matches any location label containing the letter *h* — `"hospital"`,
   `"warehouse"`, `"school"` (no), `"church"`. Where `block.location` is empty
   (the common case for baked schedules) `outbound` is `True`, so the evening
   commute is rendered as a second morning commute.
3. **Mode is invisible.** A driving commuter and a walking commuter produce the
   same `LocationMode.STREET` / `Movement.COMMUTING` at the same coordinate.
   `commute_mode` (`citizen.py:289`, set by `vehicles.choose_commute`) is never
   read by `embodiment`.

The `flee` branch is the sharpest case: `embodiment.py:501-503` moves the
citizen **half the remaining distance to the map edge in a single tick**,
regardless of `dt`.

### 2.4 How a `CitizenRuntime` itinerary is produced

```python
    def sync_schedule(self, now_hour: float, graph: MobilityGraph) -> None:
        """Update the active goal from the schedule and (re)plan if needed."""
        slot = self.current_slot(now_hour)
        if slot is not None:
            g = goal_from_schedule(slot.activity, slot.location_node, now_hour,
                                   slot.end_hour, slot.task)
            self.goals.goals = [x for x in self.goals.goals if x.source != "schedule"]
            self.goals.push(g)
        self._reselect(graph)
```
(`asphodel/citizens/runtime.py:74-83`)

`_reselect` → `_plan_for_active` (`runtime.py:115-138`) picks a mode
(`choose_mode`, `planning.py:86-91`) and calls `build_itinerary`
(`planning.py:98-147`), which is the only code in the repository that models
parking and building transitions as discrete events:

```python
    if mode in (Mode.CAR, Mode.HEAVY):
        veh = vehicle_node or origin_node
        park = parking_node or dest_node
        if veh != origin_node:
            wr = graph.route(origin_node, veh, Mode.FOOT)
            ...
            it.steps.append(PlanStep(StepKind.WALK, Mode.FOOT, origin_node, veh, wr,
                                     "walk to parked car"))
        it.steps.append(PlanStep(StepKind.ENTER_VEHICLE, detail="get in car"))
        dr = graph.route(veh, park, mode)
        ...
        it.steps.append(PlanStep(StepKind.DRIVE, mode, veh, park, dr, "drive route"))
        it.steps.append(PlanStep(StepKind.PARK, detail="park"))
        it.steps.append(PlanStep(StepKind.EXIT_VEHICLE, detail="get out"))
```
(`asphodel/citizens/planning.py:113-129`)

`StepKind` (`planning.py:22-30`) is the vocabulary: `LEAVE_BUILDING`, `WALK`,
`ENTER_VEHICLE`, `DRIVE`, `PARK`, `EXIT_VEHICLE`, `ENTER_BUILDING`,
`DO_ACTIVITY`. Each travel step carries a concrete `Route` from the live graph.

### 2.5 Where the itinerary is NOT consumed

`grep -rn "CitizenRuntime\|sync_schedule\|build_itinerary\|Itinerary\|on_blockage" --include=*.py --include=*.gd .`
returns, outside `asphodel/citizens/` itself:

* `tests/test_citizens_runtime.py`, `tests/test_living_city.py`,
  `tests/test_living_city_vertical.py` — pytest;
* `godot/scripts/debug_overlay.gd:7,20` — a *comment* and a variable named
  `citizen_debug` that would hold a `CitizenRuntime.debug()` dict; nothing
  populates it;
* `asphodel/living_city.py:5` — a **docstring claim that is false**.

That last one matters, because it is the vertical proof:

```
builds each citizen a route with the CitizenRuntime's mode logic,
```
(`asphodel/living_city.py:5-6`)

but the code is:

```python
    for cid, home, work, has_vehicle in trips:
        depart = min(end_hour - 0.5,
                     max(start_hour, rng.gauss(peak_hour, peak_spread)))
        mode = Mode.CAR if has_vehicle else Mode.FOOT
        route = graph.route(home, work, mode)
```
(`asphodel/living_city.py:119-123`)

`living_city.py` imports nothing from `asphodel.citizens`
(`living_city.py:29-31`: `mobility`, `transport`, `transport.instances`). It
calls `MobilityGraph.route` directly and picks the mode with a boolean, not
`choose_mode`. So the "planner + traffic layer on the canonical citizens" the
architecture document credits to `living_city.py` (§5) is, in fact, the traffic
layer only. **`build_itinerary` has no non-test caller anywhere.**

The NEAR half is equally unconnected: `CitizenBody.set_route`
(`citizen_body.gd:65-71`) takes `Array[Vector3]`; the only producers of that
array are literal `Vector3` lists in `godot/tests/nav_gate.gd:75-124`. There is
no function anywhere that converts an `Itinerary` (or a `Route`) into
`CitizenBody` waypoints.

### 2.6 Split A restated in one sentence

Three commute-position models exist and none of them agrees with another:

| model | where | when it runs | geometry |
|---|---|---|---|
| straight line + road projection | `embodiment.py:361-371,438-457` | every snapshot, live | not a path |
| routed polyline traversal | `world_from_compiled.py:227-259` | citizen bake only | a real path |
| itinerary with modes, parking, buildings | `citizens/planning.py:98-147` | tests only | a real plan |

and the schedule-progress fraction is implemented twice, identically, in
`embodiment.py:440-445` and `osm_city/citizens.py:86-95`.

---

## 3. Split B — Vehicles in the playable scene

### 3.1 Which scenes instantiate vehicles

| scene | vehicles present | source | is any a `VehicleInstance`? |
|---|---|---|---|
| `IsometricWorld.tscn` (default) | **parked props only** | `exterior_world.gd:1972-2064` T3 `MultiMesh` from `chunk["vehicles"]` | No |
| `StreetScene.tscn` (legacy FP) | parked props + 900 ambient movers | `street_world.gd:589-598` → `traffic.gd` | No |
| `godot/tests/LivingCity.tscn` | orange `MultiMesh` boxes | `living_city.gd:201` from `playback.json` `cars` | No — but the rows *carry* `veh:<cid>` identity upstream, which the renderer discards (`living_city.py:165` writes `[x, z, state, cid]` and `living_city.gd:204-222` reads only x/z) |
| `PhysicsGate.tscn`, `ConvergenceGate.tscn` | one `VehicleBody` each | `physics_gate.gd:199`, `convergence_gate.gd:125` | No — layer smoke test only, never driven |

`grep -rn "VehicleBody" godot/ --include=*.gd --include=*.tscn` yields exactly
four hits: the class declaration, a comment in `traffic.gd:6`, and the two
gates. **No vehicle in any playable scene is a `VehicleInstance`, and no
`VehicleBody` exists outside a gate.**

### 3.2 What `traffic.gd` does

`street_world.gd:589-598` builds it from `roads.json` polylines (the legacy road
subset, arch §4), 900 movers:

```gdscript
	var traffic: Node3D = load("res://scripts/traffic.gd").new()
	traffic.process_mode = Node.PROCESS_MODE_PAUSABLE   # freezes with pause
	add_child(traffic)
	traffic.setup(polylines, 900)
```

Each mover is a `MeshInstance3D` with a `BoxMesh` (`traffic.gd:99-107`) — no
`CollisionShape3D`, no `collision_layer`, no id. Motion is
`v.along += v.speed * step` (`traffic.gd:142`) with a lane offset
(`traffic.gd:159-160`) and, at the end of a polyline, teleportation to a random
other road:

```gdscript
			if v.seg >= n - 1:
				# End of the polyline: respawn on a random road (keeps traffic full).
				v.lane = _lanes[_rng.randi() % _lanes.size()]
				v.seg = 0
				v.along = 0.0
```
(`traffic.gd:166-171`)

It never reads the simulation and never writes to it. `traffic.gd:3-7` already
declares itself legacy. Classification: `PRESENTATION_ONLY` + `LEGACY`,
reachable only on the non-default scene.

### 3.3 What `exterior_world.gd` does with parked vehicle placements

`_build_t3` (`exterior_world.gd:1972-2064`) merges `chunk["props"]`,
`chunk["vehicles"]`, `chunk["trees"]` into one placement pass. A vehicle row is
`[kind, x, z, rot_deg, variant]` (`world_source/schema.py:106`), grouped by
`kind:variant` because colour is baked per mesh (`:1988-1998`), yaw corrected by
−90° because prop meshes are +X-forward (`:2026-2031`), and emitted as:

```gdscript
		var mmi := PropMeshes.make_multimesh(kind_s, xforms, int(g["variant"]),
			shadow_kinds.has(kind_s))
		root.add_child(mmi)
		mm_count += xforms.size()

	return {"quads": 0, "verts": 0, "buildings": 0, "mm_instances": mm_count, "collisions": 0}
```
(`exterior_world.gd:2059-2064`)

`"collisions": 0` is literal — the only `StaticBody3D` the streamer creates is
`BuildingCollision` (`exterior_world.gd:743-771`). So a parked car in the
playable scene is a transform in a `MultiMesh`: it cannot be collided with, it
has no `vehicle_id`, it cannot be entered, it cannot become a wreck, and it does
not obstruct the mobility graph. The `VehicleInstance.parked_location` field
(`instances.py:109`) has no relationship to any of these placements.

### 3.4 `vehicle_body.gd` API — what it needs, and what it lacks

Complete public surface (`godot/scripts/vehicle_body.gd`, 58 lines):

| member | line | kind |
|---|---|---|
| `min_barrier_thickness: float = 0.2` | `:15` | `@export` |
| `max_speed: float = 40.0` | `:16` | `@export` (declared, **never read**) |
| `drive_velocity: Vector3` | `:18` | public var — the *only* control input |
| `semantic_id: String` | `:19` | public var — identity carrier, never set by anything |
| `_ready()` | `:22-31` | stamps `CollisionLayers.VEHICLE` / `PROFILES["vehicle"]["mask"]`, creates a 2.0×1.4×4.5 `BoxShape3D` |
| `_required_substeps(speed, delta)` | `:34-37` | anti-tunneling substep count |
| `_physics_process(delta)` | `:40-52` | substepped `move_and_slide`, breaks on first contact |
| `_on_impact()` | `:54-58` | `pass` |

What it does **not** have, and would need to be driven by a `VehicleInstance`:

* no `set_route(...)` / `set_target(...)` — the citizen body has `set_route`
  (`citizen_body.gd:65`), the vehicle body has nothing;
* no lane-following or steering — the comment at `:18` says `drive_velocity`
  comes "from lane-following / route controller"; that controller does not exist
  in either language;
* no `arrived` or `blocked` signal — `CitizenBody` declares both
  (`citizen_body.gd:16-17`); `VehicleBody` declares none, so there is no way for
  physics to tell the semantic layer anything;
* no position report — `reconcile_from_physical` (`instances.py:185-189`) is
  waiting for a caller that cannot exist until the body emits or exposes one;
* `_on_impact` is empty, so the documented
  `PHYSICAL_CRASH → PERSISTENT_WRECK → MobilityObstruction` chain
  (`instances.py:191-207`) is unreachable from the engine.

### 3.5 What `sim_bridge.gd` transmits about vehicles

Nothing. The full command list (`sim_bridge.gd:73-198`) is `start_world`,
`set_focus`, `advance`, `intervene`, `interact_with`, `enter_building`,
`leave_building`, `inspect_building`, `search_container`, `take_item`,
`drop_item`, `get_interior`, `use_item`, `inspect_inventory`, `pause`, `resume`,
`snapshot`, `save`, `load`. `World.snapshot` (`orchestrator.py:461-533`)
contains no vehicle key of any kind. The word "vehicle" does not appear in
`protocol.py`, `session.py`, or `sim_bridge.gd`.

Consequently the vehicle stack has **two disjoint halves**: a complete semantic
model in Python that only `simulate_commute` and pytest ever run, and a complete
physics body in GDScript that only gates ever instantiate, with no protocol
between them.

---

## 4. Bridge contract today

**Version:** `PROTOCOL_VERSION = 3` (`protocol.py:32`), mirrored at
`sim_bridge.gd:23`. Exact-match policy (`protocol.py:130-132`).

**Framing:** newline-delimited JSON over TCP, one request → one response,
`asphodel/bridge/server.py:95-120`.

**Commands (Godot → sim)** — `protocol.py:35-70`:

| group | commands |
|---|---|
| lifecycle | `HELLO`, `START_WORLD`, `PAUSE`, `RESUME`, `SHUTDOWN` |
| time | `ADVANCE` (`ticks`, `snapshot: bool`), `SNAPSHOT` |
| attention | `SET_FOCUS` (zone list) |
| world edit | `INTERVENE` (action + zones + params) |
| social | `INTERACT_WITH` (`citizen_id`) |
| survival v2 | `ENTER_BUILDING`, `LEAVE_BUILDING`, `INSPECT_BUILDING`, `SEARCH_CONTAINER`, `TAKE_ITEM`, `DROP_ITEM`, `USE_ITEM`, `INSPECT_INVENTORY` |
| interiors v3 | `GET_INTERIOR` |

**Intents Godot can submit that concern motion: none.** There is no "citizen X
should go to Y", no "spawn a body for citizen X", no "this body is now at
position P", no vehicle command. The only spatial intents are `SET_FOCUS`
(which zone is promoted) and `ENTER_BUILDING` / `DROP_ITEM` (which carry a
`building_id` and an x/y). The player's own body position is never sent to
Python at all — `street_world.gd:929-938` and `isometric_world.gd:428-441` use
it locally to pick the focus zone and the render focus point.

**Snapshot fields** (`World.snapshot`, `orchestrator.py:461-533`):

top level — `day`, `tick`, `hour`, `rows`, `cols`, `official_signal`,
`authority_perceived`, `zones[]`, `agents{}`, `activity_names`, `action_names`,
optional `activity_occupancy`, `roster`, `survival`, and (injected by the
session, `session.py:339-348`) `player_location`.

per promoted zone, `agents[str(zone)]` (`orchestrator.py:483-533`):

| key | shape | meaning |
|---|---|---|
| `positions` | `[[x, y], …]` | **torus** coordinates, not city metres |
| `state` | int8[] | SEIR compartment |
| `citizen_id` | int64[] | `-1` = anonymous fill |
| `activity` | int8[] | index into `activity_names` |
| `chosen_action` | int8[] | index into `action_names` |
| `named` | bool[] | roster membership |
| `area_size` | float | torus L |
| `embodiment.world_xy` | `[[x, y] or null, …]` | **city metres** — the real position |
| `embodiment.mode` | str[] | `outdoors`/`street`/`building`/`interior` |
| `embodiment.building_id` | int[] | `-1` when not at a building |
| `embodiment.movement` | str[] | `stationary`/`walking`/`commuting` |
| `embodiment.authoritative` | bool[] | identified vs approximate |
| `embodiment.schema_version` | int | `LOCATION_SCHEMA_VERSION = 1` |

`player_location` is a full `PhysicalLocation.to_dict()` (`embodiment.py:78-93`),
the only place `destination_x`/`destination_y`/`route_frac` cross the wire.
The per-agent embodiment block deliberately drops them — so the client cannot
know where anyone is heading.

**No vehicle field exists anywhere in the snapshot.**

**Tick cadence** (`godot/scripts/game_clock.gd`):

```gdscript
	var ticks_per_hour := (1.0 / _dt_days) / HOURS_PER_DAY
	var target := int(floor(_elapsed_ingame_hours * ticks_per_hour))
	if target > sim_tick:
		_advance_world(target - sim_tick)
		sim_tick = target
```
(`game_clock.gd:132-136`)

Real time → in-game hours at `REAL_SECONDS_PER_DAY / HOURS_PER_DAY`
(`:118-120`), and a tick boundary crossing sends `ADVANCE(delta_ticks, true)`
(`:147`). So snapshots arrive at sim-tick granularity — irregularly, in bursts,
and possibly several ticks at once — while `citizen_render.gd:106-114`
interpolates against a fixed `_snap_interval = 0.25` s (`citizen_render.gd:60`).
Motion smoothness in the client is therefore unrelated to the sim's actual
cadence.

---

## 5. Persistence today

`save.py` `SAVE_VERSION = 2` (`save.py:39`). `world_state`
(`save.py:254-289`) writes: `config`, `world` (seed, promo counter, start hour,
budgets, focus, reactions flag, proximity counters, signature citizens, citizen
tags, micro params, handoff params), `sim`, `promoted`, `roster`, `citizens`,
`survival`.

**Motion-relevant fields that ARE persisted:**

| field | where | note |
|---|---|---|
| `AgentZone.pos` | `save.py:115` | the contact torus, not a city position |
| `AgentZone.state`, `sheltered` | `:116-117` | |
| `AgentZone.citizen_id` | `:118` | which citizen is on which slot |
| `AgentZone.activity` | `:119` | schedule label |
| `AgentZone.chosen_action` | `:120` | the reaction label that drives shelter/flee in embodiment |
| `AgentZone.rng` bit-generator state | `:121` | |
| roster `chosen_action`, `schedule_cursor`, `needs` | `:153-155` | |
| per citizen: `home_xy`, `work_xy`, `home_zone`, `work_zone` | `:215,223-224` | |
| per citizen: `home_building_id`, `work_building_id` | `:219-220` | |
| per citizen: `schedule` (start, end, activity, location) | `:225-226` | |
| `world.start_hour`, `sim.tick` | `:270`, `sim_state` | together these reconstruct `current_hour()` |

**Motion-relevant state that does NOT exist to be persisted:**

* **no citizen position.** There is no `x`/`y` per citizen anywhere in the save,
  and none is needed: `physical_location` is a pure function of
  `(schedule, hour, action, geometry)`, all of which *are* saved. Gate D's
  "same person in the same place after save→load"
  (`tests/test_embodiment.py:315`) holds by construction, not by storage. The
  cost is that continuity of *path* cannot be persisted because it never exists.
* **no itinerary, goal, plan step, destination, or route.** `Itinerary`,
  `Goal`, `PlanStep` and `Route` have no serializer that `save.py` calls, and no
  `CitizenRuntime` is ever attached to a `World`, so there is nothing to write.
* **no vehicle state at all.** `VehicleInstance` has `to_dict`
  (`instances.py:209-222`) but `save.py` never imports `asphodel.transport`.
  `vehicle_id`, `fidelity`, `route`, `distance_along`, `speed`, `fuel`,
  `condition`, `engine_state`, `parked_location`, `lane`, `cargo`,
  `driver`/`passengers` — none survive a save.
* **no obstructions.** A wreck (`to_wreck`, `instances.py:191-207`) or closure
  applied via `graph.apply_obstruction` (`graph.py:271-275`) lives only in the
  in-memory `MobilityGraph._obstructions`. `save.py` does not touch the graph,
  so every road reopens on load.
* **no congestion.** `DynamicState.congestion` (`segments.py:80-93`) is
  in-memory only.
* **no LOD band.** `EntityLODState` is never instantiated in production, so
  `band`/`payload`/`transitions` are not persisted.
* **no body state.** Godot-side transforms of `CitizenBody`/`VehicleBody`/the
  player are not sent to Python and not saved; on load the player respawns from
  `Session.citizen["spawn_xy"]` (`street_world.gd:764-768`,
  `isometric_world.gd:337-341`) — i.e. from the *bake-time* commute point, a
  different model than the live one (§2.6).

---

## 6. LOD today

**Band names that appear in code:**

| enum | members | file |
|---|---|---|
| `LODBand` (IntEnum) | `PHYSICAL=0`, `NEAR_SIMPLIFIED=1`, `ROUTE_SIMULATED=2`, `ABSTRACT=3` | `lod/entity.py:17-23` |
| `CitizenLOD` | `abstract`, `route_simulated`, `near_simplified`, `physical`, `interior_physical` | `lod/entity.py:26-31` |
| `VehicleFidelity` | `ABSTRACT`, `ROUTE_SIMULATED`, `PHYSICAL_CONTROLLED`, `PHYSICAL_CRASH`, `PERSISTENT_WRECK` | `transport/instances.py:23-29` |

`LODController` thresholds: `physical_radius=120`, `near_radius=400`,
`route_radius=3000`, `hysteresis=40` (`lod/entity.py:57-60`).

**But `LODBand` is not the promotion mechanism the world runs.** `World`
promotes by *zone*, not by entity, and by *epidemiology and player focus*, not
by distance:

```python
        for z in range(self.Z):
            currently = z in self.promoted
            if z in self.focus:
                want = True
            elif currently:
                want = not should_demote(float(frac[z]), True, h)
            else:
                want = should_promote(float(frac[z]), False, h)
```
(`orchestrator.py:626-633`)

`frac` is the infectious fraction (`infectious_fraction`, `:380-384`); `h` is
`self.handoff`. Focus zones (set by `SET_FOCUS`, ultimately by the player's
grid cell — `isometric_world.gd:469-476`) are force-promoted, then a hard agent
budget prunes (`_apply_budget:646-684`).

**Payload across promotion** (`_promote_zone:685-702`): a fresh `AgentZone` from
`promote(counts, genome, params, dt, seed)`, then `_assign_citizens`
(citizen ids onto slots, roster first), then `_restore_roster` (stamps the
persisted `chosen_action` back onto the slot), then activity + reaction labels.
Positions are not part of the payload — they are re-derived.

**Payload across demotion** (`_demote_zone:839-853`): only rostered members'
`chosen_action` is checkpointed into the roster; the zone is dropped. Compartment
counts already live in the macro ledger, so nothing else needs to survive.

**The three-tier vocabulary that *is* running** is `exterior_world.gd`'s chunk
streamer (T1/T2/T3 by distance with hysteresis, `exterior_world.gd:13`) — that
bands *terrain*, not agents — plus `citizen_render.gd`'s two visual tiers
(`MAX_RENDER=320` crowd instances, `MAX_AVATARS=24` near pool within
`NEAR_RADIUS=22.0` m, `citizen_render.gd:31-35`), which is presentation.

So: **there is no agent-level LOD in the running system.** A citizen is either a
slot in a promoted `AgentZone` (MID) or a number in the macro ledger (FAR).
`LODBand.PHYSICAL` is never entered by any non-player citizen, and
`resolve_materialization` — the function whose job is to refuse to spawn a body
inside a wall (`lod/materialize.py:89-132`) — has no engine caller, because no
engine code spawns bodies.

---

## 7. Godot body APIs

### `citizen_body.gd` (`CitizenBody extends CharacterBody3D`, 139 lines)

| member | line | notes |
|---|---|---|
| `signal blocked(at: Vector3)` | `:16` | emitted from `_update_stuck` after `stuck_frames` without `progress_epsilon` metres |
| `signal arrived()` | `:17` | emitted when `_wp` passes the last waypoint |
| `@export walk_speed = 1.4` | `:19` | matches `living_city.py:45` `speed_walk` |
| `@export arrive_radius = 0.6` | `:20` | |
| `@export avoid_radius = 2.0` | `:21` | also the `Sensor` sphere radius |
| `@export stuck_frames = 90` | `:22` | ~1.5 s @ 60 Hz |
| `@export progress_epsilon = 0.3` | `:23` | |
| `var semantic_id: String` | `:25` | stable citizen id across LOD — nothing assigns it |
| `var waypoints: Array` | `:26` | `Array[Vector3]` |
| `var is_stuck: bool` | `:27` | |
| `func set_route(points: Array)` | `:65-70` | resets `_wp`, `is_stuck`, progress reference |
| `func has_arrived() -> bool` | `:73-74` | |
| `_physics_process` | `:77-100` | waypoint seek + `_steer` + gravity + `move_and_slide` |
| `_steer` | `:103-126` | repulsion **plus tangential** component so head-on obstacles are skirted, not deadlocked |
| `_update_stuck` | `:129-139` | escalation to `blocked` |

Collision stamping (`:37-38`): `collision_layer = CollisionLayers.NPC` (bit 4),
`collision_mask = CollisionLayers.PROFILES["npc"]["mask"]` (31). Auto-creates a
`CapsuleShape3D` r=0.35 h=1.8 named `Collision` (`:39-46`) and an `Area3D`
`Sensor` on `CollisionLayers.TRIGGER` with the `trigger` profile mask
(`:47-59`).

### `vehicle_body.gd` (`VehicleBody extends CharacterBody3D`, 58 lines)

Full surface listed in §3.4. Collision stamping (`:23-24`):
`collision_layer = CollisionLayers.VEHICLE` (bit 8),
`collision_mask = PROFILES["vehicle"]["mask"]` (31); auto `BoxShape3D`
2.0×1.4×4.5 (`:25-31`). **No signals, no route API.**

### `collision_layers.gd` (generated, 32 lines)

`WORLD_STATIC=1, PLAYER=2, NPC=4, VEHICLE=8, DYNAMIC_PROP=16, TRIGGER=32,
NAV_QUERY=64, DAMAGE_QUERY=128` (`:6-13`) with a `PROFILES` dict (`:16-25`).
Header: "GENERATED by `asphodel.physics.layers.emit_gdscript()` — DO NOT EDIT."
Stamped by `citizen_body.gd:37`, `vehicle_body.gd:23`,
`isometric_player.gd:33`, `first_person.gd`, `exterior_world.gd:762`. Not
stamped by: parked vehicle `MultiMesh`es, `traffic.gd` movers,
`interior_builder.gd` occupants.

### `mobility_loader.gd` (`MobilityLoader extends RefCounted`, 183 lines)

| member | line | notes |
|---|---|---|
| `const SUPPORTED_VERSIONS := [1, 2]` | `:21` | hard error on anything else |
| `version`, `source` | `:23-24` | |
| `nodes: {id -> Vector2}` | `:25` | (x, z) |
| `segments: {id -> {u,v,class,length,modes,directionality}}` | `:26` | |
| `points: {id -> PackedVector2Array}` | `:27` | v2 per-segment polyline |
| `load_mobility(dir_path) -> bool` | `:33-79` | reads `streetmap.json` |
| `segment_points(seg_id) -> PackedVector2Array` | `:81-92` | v1 falls back to the straight u→v line |
| `close_segment(seg_id, modes)` / `open_segment(seg_id)` | `:94-98` | the obstruction API |
| `set_congestion(seg_id, factor)` | `:100-102` | |
| `route(origin, dest, mode) -> Array` | `:147-183` | Dijkstra over `_cost`; returns a node-id path |

`route` returns **node ids**, not points. Turning that into `CitizenBody`
waypoints requires `segment_points` per hop; no code does this.

---

## 8. Recommendation

*Nothing below was changed. These are proposals, cited to the lines that would
have to move.*

### 8.1 The single authority per domain

| domain | must become the one authority | why, in lines |
|---|---|---|
| **Planning** (schedule → goal → plan) | `asphodel/citizens/runtime.py` `CitizenRuntime` + `planning.build_itinerary` | It is the only model with modes, parking, vehicle entry/exit and building transitions as first-class steps (`planning.py:22-30,113-144`), the only one that replans under live costs (`planning.py:150-173`), and the only one that fails loudly (`Itinerary.ok/failure`). It needs one production caller: `World.step` phase 4b, next to `_update_zone_activity` (`orchestrator.py:433-437`). |
| **Routing** | `asphodel/mobility/graph.py` `MobilityGraph.route` + `segments.traverse_cost` | Already canonical and already the only router that reads obstructions and congestion (`graph.py:246`, `segments.py:152-166`). |
| **Walking (MID)** | a new "advance along the current `PlanStep.route`" integrator, mirroring `VehicleInstance.advance_far` (`instances.py:156-173`) | Today `living_city.py:153-154` implements pedestrian advance (`a.dist + speed_walk * dt`) as a local in a dev script. That is exactly the missing MID walking authority; lifting it next to `advance_far` gives citizens and cars one shape. |
| **Walking (NEAR)** | `godot/scripts/citizen_body.gd` | It already has avoidance, stuck detection and the `blocked` escalation the planner's `on_blockage` (`runtime.py:141-153`) is written to receive. It needs waypoints, which requires an `Itinerary`→`Array[Vector3]` bridge (see 8.3). |
| **Driving (MID)** | `asphodel/transport/instances.py` `VehicleInstance` + `traffic.TrafficReconciler` | Complete, tested (`tests/test_transport.py`), congestion-closed. Needs to be *owned* — see 8.2. |
| **Driving (NEAR)** | `godot/scripts/vehicle_body.gd` — **after** it gains a route API | Currently only `drive_velocity` (`vehicle_body.gd:18`). Minimum additions to make it the NEAR authority: `set_route(points: Array)`, `signal arrived()`, `signal blocked(at)`, and a position report so `reconcile_from_physical` (`instances.py:185-189`) has a caller. `_on_impact` (`:54-58`) must actually drive `to_wreck` (`instances.py:191-207`). |
| **Parking** | `planning.StepKind.PARK` / `EXIT_VEHICLE` (`planning.py:128-129`) + `VehicleInstance.parked_location` (`instances.py:109`) | Note `build_itinerary` currently defaults `parking_node = dest_node` (`planning.py:115`) — "park at the door". A real PARKING_ANCHOR selection is missing; `tests/test_living_city_vertical.py:171-172` already records this as PARTIAL. |
| **Building transitions** | `planning.StepKind.LEAVE_BUILDING` / `ENTER_BUILDING` (`planning.py:110,143`) reconciled with `World.building_occupants` (`orchestrator.py:251-277`) and `graph.attach_building` (`graph.py:298-322`) | These are three different notions of "at a building" today: a plan step, a `PhysicalLocation.mode == BUILDING` test, and a graph connector node. |
| **LOD** | `asphodel/lod/entity.py` `LODController`/`EntityLODState`, driven from `World` | `World._update_membership` (`orchestrator.py:620-644`) must keep deciding *zone* promotion by epidemiology, but *entity* band must become distance-based via `band_for` (`entity.py:62-85`), and `resolve_materialization` (`materialize.py:89-132`) must gate every NEAR body spawn. |
| **Persistence** | `asphodel/save.py` | Must gain: per-citizen `current_node` + serialized active `Itinerary` + step index; the `TrafficReconciler`'s vehicles (`instances.to_dict`, `:209-222` already exists); `MobilityGraph._obstructions` (`obstructions.to_dict`, `:72-82` already exists); per-segment congestion. All four serializers exist; none is called. |

### 8.2 Concrete wiring, in order

1. **Give `World` a `MobilityGraph` and a `CitizenRuntime` per identified
   citizen.** The graph is already loaded and hanging off the spatial context —
   `CitySpatialContext.street_graph` (`embodiment.py:172`, set at `:248`). It is
   currently used only for `nearest_road_xy`. `World.set_spatial_context`
   (`orchestrator.py:187-191`) is the hook.
2. **Call `sync_schedule` in `World.step` phase 4b**, immediately after
   `_update_zone_activity` (`orchestrator.py:434`), for identified slots only —
   the same bounded set `identified_slots()` already returns
   (`micro.py:269-271`). This is the smallest change that closes Split A's
   planning half.
3. **Make `resolve_physical_location` read the itinerary.** Add an optional
   `itinerary`/`progress` parameter to `resolve_physical_location`
   (`embodiment.py:393-402`) and replace the `activity == "commute"` branch
   (`:438-457`) with a point along the current `PlanStep.route` polyline
   (`route_polyline`, `instances.py:35-51`, already exists). Everything else in
   that function — home/work anchors, `_bid`, shelter, flee — stays.
   `_commute_point` (`:361-371`) then becomes the no-context fallback.
4. **Publish the plan in the snapshot.** `_zone_embodiment`
   (`orchestrator.py:535-580`) already emits five parallel arrays; add
   `destination_xy`, `route_frac` and `mode` (the `PhysicalLocation` already
   carries all three, `embodiment.py:88-90`, and the *player's* copy already
   crosses via `_inject_player_location`, `session.py:339-348`). Bump
   `LOCATION_SCHEMA_VERSION` (`embodiment.py:49`).
5. **Add vehicles to the snapshot and the protocol.** `TrafficReconciler.snapshot`
   (`traffic.py:77-78`) returns exactly the right shape. This is a protocol v4
   change (`protocol.py:32`) and needs the matching reader in `sim_bridge.gd:23`.
6. **Add the two motion intents Godot needs**: a NEAR body registration
   (`citizen_id`/`vehicle_id` → this client owns physics for it) and a position
   report (→ `reconcile_from_physical`, `instances.py:185-189`). Without these
   the NEAR tier can never be authoritative for anything.

### 8.3 Becomes PRESENTATION_ONLY (keep, but never read back)

* `godot/scripts/citizen_render.gd` in full — already correctly scoped;
  `_world_pos`'s torus fallback (`:272-281`) should be removed once
  `world_xy` is non-null for every drawn agent, because it is the one place a
  contact-mixing coordinate becomes a screen position.
* `godot/scripts/interior_builder.gd:161-180` `_occupant`.
* `godot/scripts/exterior_world.gd` T3 vehicle/prop `MultiMesh`es
  (`:1972-2064`) — *unless* a parked car is meant to be enterable, in which case
  the T3 placement rows need `vehicle_id`s and colliders, and become the spawn
  source for `VehicleInstance.parked_location`.
* `godot/tests/living_city.gd` — a screenshot harness; keep as DEV_ONLY.

### 8.4 DELETE candidates (with the condition that must hold first)

| candidate | lines | condition |
|---|---|---|
| `godot/scripts/traffic.gd` (whole file) + `street_world.gd:589-598` | 171 + 10 | once `StreetScene.tscn` is retired or its vehicles come from playback / `VehicleBody`. Already self-declared legacy (`traffic.gd:3-7`). |
| `asphodel/embodiment.py:438-457` commute branch + `_commute_point` `:361-371` | ~30 | once step 3 above lands. **Do not delete before**: it is the only thing placing commuters today. |
| `asphodel/osm_city/citizens.py:86-95` `_commute_frac` and the commute branch of `_spawn_point` `:122-125` | ~15 | once `spawn_xy` is derived from the same authority as the live position, i.e. once `World` can be asked "where is citizen N at hour H" *before* the session starts. Until then this duplicate is load-bearing for `street_world.gd:764` / `isometric_world.gd:337`. |
| `asphodel/osm_city/world_from_compiled.py:188-226` `_adjacency`/`route` | ~40 | once `commute_point` routes on `MobilityGraph` instead of spawn-anchor adjacency. This is the third router in the tree. |
| `asphodel/vehicles.py:199-266` `RoadNetwork` + `:296-352` `assign_traffic` | ~120 | once `congestion_report` (`citizen.py:1400`) is re-pointed at `TrafficReconciler.update_congestion` (`traffic.py:51-61`). `choose_commute` (`:154-193`) and the `VehicleSpec` catalogue (`:44-104`) must **stay** — they are the vocabulary `living_city.py:99-101` and `citizen.py:709` depend on. |
| `godot/scripts/vehicle_body.gd:16` `max_speed` | 1 | dead export, never read. |
| `godot/scripts/debug_overlay.gd:20` `citizen_debug` | 1 | dead until `CitizenRuntime.debug()` (`runtime.py:162-178`) actually crosses the bridge — better to *wire* it than delete it. |

### 8.5 What must NOT be deleted despite having no callers

`asphodel/lod/entity.py`, `asphodel/lod/materialize.py`,
`asphodel/citizens/*`, `asphodel/transport/*`, `godot/scripts/citizen_body.gd`,
`godot/scripts/vehicle_body.gd`, `godot/scripts/mobility_loader.gd`. Every one
of these is TEST_ONLY today, and every one is the *intended* authority for its
domain. They are unreached, not wrong. The census's central finding is that the
gap between the shipping system and the designed system is almost entirely a
gap of **call sites**, not of missing implementations.

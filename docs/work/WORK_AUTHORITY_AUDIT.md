# WORK AUTHORITY AUDIT — pre-milestone survey for ASPHODEL_SMART_OBJECTS_WORK_V1

Repo `/home/user/Asphodel`, branch `claude/asphodel-embodied-mobility-v1-6gl4a8`, HEAD `a9192b1`.
Read-only audit; every claim is a `file:line` at that SHA.

> **In-flight work.** `asphodel/smart/` exists **untracked** on this worktree
> (`__init__.py`, `objects.py`, `rooms.py`, `reservations.py`, `jobs.py`;
> `runtime.py` imported by `__init__.py:24` but not yet written). A parallel
> session is already implementing this milestone, and by the end of this audit it
> had also begun modifying tracked files in this worktree (`bridge/protocol.py`,
> `bridge/session.py`, `embodied/runtime.py`, `orchestrator.py`,
> `outbreak/runtime.py`, `save.py`). **All line numbers below are against the
> committed HEAD `a9192b1`** (`git show a9192b1:<path>`), not the dirty working
> tree, where some have already shifted by a few lines. Nothing below was written
> against `asphodel/smart/`; it is flagged so the two do not collide.

---

## 1. ACTIVITY AUTHORITY TODAY

### 1.1 The chain

```
citizens.json (occupation/shift)
 -> citizen.py _build_schedule        -> list[ScheduleEntry]
 -> MobilityRuntime._slots            -> list[ScheduleSlot] (activity + graph node + task)
 -> CitizenRuntime.sync_schedule
      + goals.goal_from_schedule      -> Goal(DO_ACTIVITY, activity="work")
 -> CitizenRuntime._plan_for_active   -> Itinerary ending in PlanStep(DO_ACTIVITY)
 -> TripExecutor._do_activity/_in_place -> state=DOING_ACTIVITY, activity="work"
 -> MobilityRuntime.citizen_row       -> {"state":"doing_activity","activity":"work"}
 -> bridge GET_MOBILITY / ADVANCE_TIME -> Godot
```

No other producer of "the citizen is working" exists. `activity` is a free
string on the executor; nothing is consumed, produced or touched.

### 1.2 Schedule slots, shift, on_duty

`ScheduleEntry` (`asphodel/citizen.py:115-124`): `start_hour, end_hour,
activity (sleep/commute/work/errand/leisure), location, task`.

Shift times are **global constants, not per-citizen** (`citizen.py:136-141`):
`day_start=8.0, day_end=16.0, night_start=20.0, night_end=28.0` (04:00 next day),
`wake_before_work=1.5`, `commute_hours=0.5`. `citizens.json`'s `shift`
("day"/"night"/"none") comes from the `Occupation` record and selects the branch
of `_build_schedule` (`citizen.py:385-440`). `on_duty` is **derived, not input**:
`citizen.py:944` — `on_duty = activity == "work"`.

**The key existing hook**: the work block is already subdivided by task
(`citizen.py:372-382`):

```python
def _spread_tasks(tasks, start, end):
    labels = tasks or ["on shift"]
    span = (end - start) / len(labels)
    for i, label in enumerate(labels):
        out.append(ScheduleEntry(s, s + span, "work", "", label))
```

Every occupation carries an ordered task spine (`citizen.py:1109-1114`):

```python
Occupation("office_worker", 21, 66, 1.3, "commercial", "day",
           ["email", "standup", "meetings", "spreadsheets", "calls"], ...),
Occupation("grocery_clerk", 16, 67, 1.0, "commercial", "day",
           ["open till", "restock", "checkout", "cash up"], ...),
```

A day-shift grocery clerk therefore already has four ~2 h `activity="work"` slots
with distinct `task` strings. `task` survives into `ScheduleSlot.task`
(`citizens/runtime.py:33`, filled at `embodied/runtime.py:227-228`) and into the
goal's `reason` (`goals.py:150-153`) — but is **dropped before the executor**:
`Goal.activity` is the bare `"work"`. Cheapest place to inject affordance intent.

`MobilityRuntime._slots` (`embodied/runtime.py:212-229`) maps `work` → work node,
`errand` → derived errand building, `commute` → work-or-home by the *next* slot,
else home.

### 1.3 Goals

`goals.py:128-153`: `commute*` → `ARRIVE_AT` (deadline = slot end); `sleep` →
`IDLE`; everything else (`work`/`errand`/`leisure`) → `DO_ACTIVITY(target, activity)`.
Priority `SOURCE_BASE_PRIORITY["schedule"] = 0.55` (`goals.py:28-35`).
`sync_schedule` **replaces all schedule-sourced goals every sync**
(`citizens/runtime.py:95`) — the reason the outbreak must re-push (§5).

### 1.4 Planning

`citizens/runtime.py:174-209`: a `DO_ACTIVITY` goal at a *different* node becomes
a trip plus a trailing activity step:

```python
activity = None
if not travel and g.target and g.target != self.current_node and g.target in graph.nodes:
    travel = True
    activity = g.activity or g.kind.value
```

`build_itinerary` appends it last (`citizens/planning.py:219-225`):

```python
it.steps.append(PlanStep(StepKind.ENTER_BUILDING, to_node=dest_node, ...))
if activity:
    it.steps.append(PlanStep(StepKind.DO_ACTIVITY, detail=activity,
                             activity=activity, building_id=dest_building_id,
                             to_node=dest_node))
```

`replan_travel` recovers it by scanning for that step (`planning.py:241-242`).

### 1.5 The executor

`embodied/executor.py:604-612` — a **one-shot, zero-duration** step:

```python
def _do_activity(self, dt, step, rt, env) -> bool:
    if not self.inside or (step.building_id is not None and self.building_id != step.building_id):
        self.fail("activity requires being inside the destination building", rt, env)
        return False
    self.state = EmbodimentState.DOING_ACTIVITY
    self.activity = step.activity or "activity"
    self.event(env.now_s, "activity", activity=self.activity, building_id=self.building_id, arrived=True)
    return True
```

It returns `True` immediately, so `current_step` becomes `None` and the **steady
state of a working citizen is `_in_place`** (`executor.py:314-339`), re-entered
from `_advance:282-285` and step completion `:310-312`:

```python
g = rt.active_goal
if self.inside and g is not None and g.target == rt.current_node \
        and self.building_id == (rt.node_meta.get(rt.current_node) or {}).get("building_id", self.building_id):
    act = g.activity or {"idle": "sleep", "arrive_at": "arrived"}.get(g.kind.value, g.kind.value)
    if self.state != EmbodimentState.DOING_ACTIVITY or self.activity != act:
        self.state = EmbodimentState.DOING_ACTIVITY
        self.activity = act
        self.event(env.now_s, "activity", activity=act, building_id=self.building_id)
elif self.inside:
    self.state = EmbodimentState.INSIDE_BUILDING
    self.activity = "idle"
```

Position is frozen at the entrance anchor (`executor.py:597`), `speed = 0`.

`EmbodimentState` is a `str`-Enum (`executor.py:34-49`); `DOING_ACTIVITY =
"doing_activity"`. `inside` (`:149-151`) = `INSIDE_BUILDING ∪ DOING_ACTIVITY` —
**many consumers depend on `DOING_ACTIVITY` implying `inside`**.

### 1.6 The performance shortcut a work runtime collides with

`embodied/runtime.py:464-471`:

```python
if ex.override in ("incapacitated", "corpse"):
    continue
if ex.current_step is None and ex.inside and self.citizens[cid].plan_serial == ex.plan_serial:
    continue
```

Working citizens are **skipped entirely** in every 1 s substep; `_in_place` runs
only when a sync or plan change makes those diverge. This is why 297 citizens
cost 21 ms/game-minute off-peak.

Sync is once a game minute (`runtime.py:458`), and `_sync` (`:477-487`) replans
only when the slot key `f"{start_hour}:{activity}:{location_node}"` changes —
**`task` is not in the key**, so task sub-slots produce no replan today.

### 1.7 Consumers of `activity == "work"` / `DOING_ACTIVITY`

**Python production**

| Site | Use |
|---|---|
| `embodied/executor.py:151` | `inside` property |
| `embodied/executor.py:219-220` | `adopt()` demotes DOING_ACTIVITY → INSIDE_BUILDING on a new plan |
| `embodied/executor.py:302-303, 604-612` | the step |
| `embodied/executor.py:314-339` | `_in_place` steady state |
| `embodied/executor.py:635, 661` | `activity` in `to_state` / `from_state` |
| `embodied/runtime.py:197-202` | register: initial `activity`, `start_bid = work_building_id` if the block says work |
| `embodied/runtime.py:530` | `citizen_row["activity"]`, `["state"]` |
| `orchestrator.py:353` | `PhysicalLocation.activity = ex.activity` |
| `orchestrator.py:447` | `building_occupants[i]["activity"]` |
| `outbreak/runtime.py:137` | `choose_index_case`: `s.activity == "work" and 6.0 <= s.start_hour <= 10.0` |
| `outbreak/runtime.py:247-248` | `_go_home` TRIP_ABORTED guard excludes INSIDE_BUILDING/DOING_ACTIVITY |
| `outbreak/runtime.py:521-522` | a corpse only frightens someone `wx.inside and wx.state == DOING_ACTIVITY` |
| `citizen.py:944`, `citizen.py:800` | `on_duty`; `_environment_of` |

**Python tests** pinning the shape: `tests/test_embodied_mobility_day.py:109,170,323,326`;
`test_embodied_executor_day.py:48,173,277`; `test_embodied_saveload.py:173`;
`test_outbreak_lod.py:13`; `test_living_city.py:78`; `test_citizens_runtime.py:50,90,103`;
`test_living_city_vertical.py:211`; `test_citizens_bake.py:95,123`. The sharpest,
`test_embodied_mobility_day.py:316-326`:

```python
acts = [e for e in ex.trace if e["event"] == "activity" and e.get("activity") == "work"]
assert acts and arrived and acts[0]["t"] >= arrived[0]["t"]
s8 = min((s for s in day["samples"] if 8.02 <= s["hour"] < 9.0), key=lambda s: s["hour"])
assert s8["activity"] == "work" and s8["state"] == "doing_activity"
```

**Godot**: `embodied_mobility_gate.gd:181` (pre-commute), `:359-362` (arrival),
`:381-382` (`activity=="work" and state=="doing_activity"` at 08:01), `:438`
(return leg); `embodied_mobility_shot.gd:200,203,223`; `character_screen.gd:36-41`
(reads `current_activity` from the roster/snapshot path);
`embodied_mobility.gd:74,95` — **only** `on_foot / approaching_vehicle /
entering_vehicle / exiting_vehicle / undead` plus outdoor corpses get bodies;
`doing_activity` citizens are explicitly not embodied.

### 1.8 Hand-off points

1. `goals.py:150` — `Goal.activity` loses `slot.task`.
2. `planning.py:222-225` — the trailing `PlanStep(DO_ACTIVITY)`; natural carrier
   for a station/affordance target.
3. `executor.py:604-612` — `_do_activity` returning `True` immediately; a
   duration-bearing step would change `step_index`/`trips_completed` in the save.
4. `executor.py:314-339` — `_in_place`, the real steady state; safest hook is
   "after `_in_place` establishes DOING_ACTIVITY, delegate".
5. `embodied/runtime.py:469-470` — the inside-building skip.
6. `embodied/runtime.py:526-546` — `citizen_row`, where new wire fields surface.
7. `orchestrator.py:424-451` — `building_occupants`, whose hashed anchor a
   station position replaces.

---

## 2. INTERIORS TODAY

**A full interior model already exists** — authoritative, deterministic, rendered;
just not wired to work or to the mobility executor.

### 2.1 `asphodel/interiors.py` (602 lines)

Dataclasses (`interiors.py:66-193`): `Entrance(entrance_id,x,y,nx,ny,room_id)`
(inward normal); `Room(room_id,x0,y0,x1,y1,kind)` axis-aligned rect with
`center()`; `Doorway(door_id,room_a,room_b,x,y,width=1.1)` (`room_a == -1` =
exterior); `Fixture(fixture_id,room_id,x,y,kind,facing,container_index)` **1:1
with an authoritative container**; `Decor(decor_id,room_id,x,y,kind,facing,variant)`
presentation-only; `InteriorDescriptor(...)` with `to_dict()` and
`geometry_hash()` (`:183-186`).

`INTERIOR_GEN_VERSION = 1`, `INTERIOR_SCHEMA_VERSION = 1` (`:47-49`). Contract
(`:12-28`): **immutable base regenerated from `(world_seed, building_id,
gen_version)` + footprint; persistent deltas only for player-caused change, keyed
by `container_index`, stored in `asphodel/survival.py`.** A room/station model
that follows this rule costs zero save bytes.

`build_interior(...)` (`:397-484`): AABB the footprint inset by `WALL_MARGIN=0.5`
→ hull; `simplified_hull = not _is_axis_aligned_rect(poly)` (`:320-326,418-420`);
`archetype_for` (`:290-308`) — loot flavour `medical` → `clinic`, else
`_ARCH_HINT_MAP` (`:276-287`) exterior `arch` → interior archetype, else
commercial splits office/retail on `height >= 9.0 or area >= 1200`; BSP
`_partition` (`:332-377`) largest-leaf-first, ratio in [0.4,0.6], `MIN_ROOM=3.0`,
each split recording a doorway → spanning tree; room kinds round-robin from
`_ARCH_ROOMS`; one entrance on the hull edge nearest `road_xy`; fixtures =
exactly `items.n_containers(...)` against walls (`_fixture_anchor:591-602`);
`_place_decor` (`:487-...`) on a perimeter-first 3 m grid.

Room vocabulary already covers workplaces (`:214-223`): `retail:
shop_floor/back_room/storeroom`; `office: open_office/meeting/break_room/storeroom`;
`clinic: waiting/exam/supply/office`; `industrial: warehouse/workshop/loading/office`;
`school: classroom/hallway/cafeteria/library`; `civic: lobby/assembly/office/meeting`.
Decor already names the objects a station model wants (`:235-259`): `gondola,
checkout, fridge_case, pallet_rack, cubicle, printer, filing_cabinet, exam_table,
med_cart, workbench, forklift, chalkboard, teacher_desk, counter, stove, sink`.

**Decor is presentation-only by explicit design** (`:122-139`) with no id stable
across gen_version. Smart objects must not retrofit gameplay meaning onto `Decor`
without promoting it or adding a parallel list.

### 2.2 Bridge

`Command.GET_INTERIOR` (`bridge/protocol.py:31,66,82`, protocol v3), handled at
`bridge/session.py:378-386` → `World.interior_state(bid, gv)`
(`orchestrator.py:394-422`) = `descriptor.to_dict()` + `fixture_state`
(per-fixture `searched`/`empty`) + `dropped_here` + `occupants`.

### 2.3 Geometry available per building

| Source | Fields |
|---|---|
| `godot/bundles/<city>/buildings.json` | `poly` (list `[x,y]`, world metres), `arch`, `cat`, `height`, `key` — **array index = `building_id`** |
| `CitySpatialContext` (`embodiment.py:158-267`) | `building_polys[]`, `building_heights[]`, `building_archs[]`, `building_centroids` (N,2); accessors `building_poly/height/arch/xy`, `nearest_road_xy`, `nearest_building` (`:252-310`) |
| `world/spawn_anchors.json.gz` | 83 859 rows `["BUILDING_ENTRANCE", x, y, bid]` (Houston); loaded by `load_entrances` (`embodied/runtime.py:57-70`) — the anchor the executor walks to |
| `world/chunks/c_<i>_<j>.json.gz` | per building: `poly`, **`entrance: {edge, t, w}`** (footprint edge index + fraction + width), `floors`, `h`, `arch`, `roof`, `feat` (e.g. `["garage","porch"]`), `appearance`, `architecture` |
| `zones.json` | zone `id`, `center_xy` |

So a room/station generator has, per building: **exact footprint polygon (world
metres, arbitrary vertex count), AABB, centroid, height in metres, floor count,
exterior archetype, category, an entrance anchor xy AND a parametric entrance on
a named footprint edge, plus the nearest road point.** More than enough.

Houston's 169 used workplace footprints: 53 are 4-gons, 21 6-gons, 17 8-gons,
tail to 36 — only ~31 % are true rectangles; the rest hit AABB simplification.

### 2.4 Occupancy today

`World.building_occupants` (`orchestrator.py:424-451`) iterates **every**
registered citizen, calls `physical_location(cid)`, and emits for matches:

```python
anchor = interiors.occupant_anchor(descriptor, cid)
occ.append({"citizen_id": cid, "room_id": anchor["room_id"], "x": anchor["x"],
            "y": anchor["y"], "activity": loc.activity, "action": loc.action,
            "in_roster": bool(self.roster.contains(cid))})
```

`occupant_anchor` (`interiors.py:572-588`) = `rooms[cid % len(rooms)]` plus a
hashed 25–75 % offset. Deterministic but arbitrary — job-blind. Exactly the
placement a station model replaces. O(citizens) per interior query, already
flagged in `docs/mobility/EMBODIED_MOBILITY_AUTHORITY_CENSUS.md:56`.

### 2.5 Godot interiors

`interior_builder.gd` (337 lines) — `InteriorBuilder.build(descriptor, offset)`
→ `Node3D` with `Floor`, `Ceiling`, `InteriorLight`, `InteriorCollision`
(`StaticBody3D`, layer `WORLD_STATIC`) with per-room walls cut at doorway/entrance
gaps, `Fixtures` (collision + meta `building_id`/`fixture_id`/`container_index`),
decor, `ExitMarker`, `Occupants`. Header (`:4-13`): *"PRESENTATION ONLY — it never
invents rooms, fixtures, or container assignments; it draws exactly what Python
reported."* `isometric_world.gd:17,31,650-703` stages interiors at
`INTERIOR_STAGE_ANCHOR = Vector3(0,0,9000)`; `isometric_interaction.gd` targets
`Occupants`/`Fixtures`/`ExitMarker` (`isometric_world.gd:534-556`). Gates:
`live_interior.gd`, `live_walkin.gd`, `iso_interior_smoke.gd`,
`iso_interaction_smoke.gd`, `convergence_gate.gd:207`.

### 2.6 Interior navigation: none

No interior navmesh, no `NavigationRegion3D` anywhere. `godot/tests/nav_gate.gd`
is a *street* avoidance/blocked/replan gate on `CitizenBody` steering
(`citizen_body.gd:11`) run on a flat box floor (`nav_gate.gd:32-42`). Interior
walls exist only as `StaticBody3D` collision (`interior_builder.gd:110-118`).
Station-to-station movement means straight-line steering with collision, or new
interior nav over the doorway spanning tree.

`asphodel/lod/entity.py:31,42-45` already defines `CitizenLOD.INTERIOR_PHYSICAL`
and `band_to_citizen_lod(band, interior=True)` — **declared but unused in
production** (only `tests/test_lod.py:51-52`). A reserved slot for this milestone.

### 2.7 Warning: AABB blowup on real workplaces

Running the real generator on Houston's ≥3-worker workplaces:

| bid | exterior arch | interior arch | rooms | kinds | fixtures | decor | hull |
|---|---|---|---|---|---|---|---|
| 2318 | CIVIC_SPECIAL | civic | 1 | `lobby` | 4 | **13 249** | 413×388 m |
| 6059 | BIG_BOX_COMMERCIAL | retail | 3 | shop_floor/back_room/storeroom | 1 | 5 131 | 186×339 m |
| 4384 | CIVIC_SPECIAL | civic | 4 | lobby/assembly/office/meeting | 2 | 479 | 92×68 m |
| 7466 | SMALL_COMMERCIAL | retail | 2 | shop_floor/back_room | 2 | 2 113 | 157×167 m |
| 3735 | SMALL_COMMERCIAL | retail | 2 | shop_floor/back_room | 4 | 3 299 | 287×142 m |
| 3995 | CIVIC_SPECIAL | civic | 3 | lobby/assembly/office | 3 | 1 213 | 136×113 m |
| 4587 | OFFICE_HIGHRISE | office | 3 | open_office/meeting/break_room | 2 | 227 | 38×81 m |

All seven are `simplified_hull = True`. Building 2318 is a 56 341 m² school whose
AABB is 160 000 m² — one `lobby` the size of a city block with 13 249 decor items.
`_ARCH_HINT_MAP` also maps `CIVIC_SPECIAL` → `civic` regardless of `cat`, so an
education building gets lobby/assembly, not classrooms (`interiors.py:276-287`
ignores `cat`; only `items.container_flavour` overrides, and only to `clinic`).

**Consequence**: today's rooms are not usable station containers for large
commercial/civic buildings without (a) area-scaled room counts — `target =
rng.integers(1, len(room_names)+1)` (`interiors.py:437`) ignores area entirely,
(b) real polygon clipping instead of AABB, or (c) a work-zone model on the
footprint rather than on `Room`. (a) and (b) bump `INTERIOR_GEN_VERSION` and
invalidate every `geometry_hash` an existing gate asserts.

---

## 3. BUILDING AND CITIZEN DATA

`buildings.json` is identical across bundles: `{"buildings":[...], "source",
"storey_m", "version"}`, each `{"arch","cat","height","key","poly"}`. **No name,
no use, no area, no tags** — `arch` + `cat` + derived polygon area is the whole
signal. Array index = `building_id`.

`citizens.json` job fields: `occupation`, `shift` ∈ {day,night,none}, `on_duty`
(derived), `profile`, `environment` (derived label), `work_building_id`,
`work_xy`, `work_district`, `current_activity`, `spawn_context`, `signature_*`.
**`tasks` are not in the bundle** — re-derived from `occupation` at load.

### 3.1 Per city

| | houston | madisonville_tx | san_antonio | austin |
|---|---|---|---|---|
| buildings | 22 525 | 2 940 | 35 658 | 29 205 |
| citizens | 300 (297 registered) | 60 | 60 | 60 |
| DETACHED_RESIDENTIAL | 17 691 | 2 464 | 32 569 | 24 234 |
| MULTIFAMILY | 1 456 | 56 | 1 110 | 2 521 |
| SMALL_COMMERCIAL | 1 259 | 193 | 699 | 1 096 |
| BIG_BOX_COMMERCIAL | 182 | 16 | 57 | 69 |
| OFFICE_HIGHRISE | 8 | 0 | 15 | 57 |
| INDUSTRIAL | 697 | 35 | 382 | 81 |
| CIVIC_SPECIAL | 522 | 51 | 662 | 1 075 |
| GENERIC_UNKNOWN | 710 | 125 | 164 | 72 |
| cat commercial/industrial/education/civic/medical | 1447/698/331/141/51 | 209/35/11/25/15 | 767/383/326/245/94 | 1194/81/587/354/162 |
| no workplace | 86 | 14 | 14 | 14 |
| shift day/night/none | 163/51/86 | 34/12/14 | 35/11/14 | 35/11/14 |
| on_duty at spawn hour | 78 | 17 | 15 | 17 |
| distinct workplaces | 169 | 32 | 41 | 45 |
| workplaces with ≥3 workers | 7 | 4 | 1 | 0 |
| max workers at one building | 6 | 4 | 3 | 2 |

### 3.2 Workplace kind of citizens' `work_building_id`

| arch / cat | houston | madisonville | san_antonio | austin |
|---|---|---|---|---|
| BIG_BOX_COMMERCIAL / commercial | **74** | 16 | 11 | 8 |
| SMALL_COMMERCIAL / commercial | **63** | 13 | 11 | 15 |
| CIVIC_SPECIAL / education | 31 | 6 | 8 | 8 |
| INDUSTRIAL / industrial | 22 | 4 | 5 | 3 |
| CIVIC_SPECIAL / medical | 12 | 6 | 2 | 0 |
| OFFICE_HIGHRISE / commercial | 6 | 0 | 7 | 5 |
| CIVIC_SPECIAL / civic | 4 | 1 | 1 | 2 |
| OFFICE_HIGHRISE / medical, education, civic | 2 | 0 | 1 | 1, 3, 1 |
| (none) | 86 | 14 | 14 | 14 |

**137 of Houston's 214 employed citizens (64 %) work in a commercial building.**

### 3.3 Houston occupations (300 citizens, 36 distinct)

`child 34, retiree 30, student 24, grocery_clerk 23, office_worker 18, cleaner 15,
homemaker 14, barista 14, security_guard 12, landscaper 12, waiter 11, it_support 10,
unemployed 8, courier 8, accountant 7, delivery_driver 6, nurse 5, doctor 5,
mechanic 4, factory_worker 4, childcare_worker 4, chef 4, truck_driver 4, …`

Occupation × workplace-arch (top): `student×CIVIC 24, grocery_clerk×BIG_BOX 16,
office_worker×SMALL 10, office_worker×BIG_BOX 8, cleaner×BIG_BOX 7,
cleaner×SMALL 7, barista×BIG_BOX 7, security_guard×BIG_BOX 6,
security_guard×SMALL 6, waiter×BIG_BOX 6, landscaper×SMALL 6,
grocery_clerk×SMALL 6, courier×BIG_BOX 6, it_support×BIG_BOX 5, accountant×BIG_BOX 5`.
Assignment is category-driven, not semantic: a landscaper and a courier are both
filed into BIG_BOX_COMMERCIAL. Station assignment must degrade gracefully when
occupation and building disagree.

### 3.4 Workers per workplace (the sparsity problem)

Houston: **135 buildings have exactly 1 worker**, 27 have 2, 5 have 3, 1 has 4,
1 has 6. Austin: 44 of 45 workplaces have a single worker.

Houston ≥3 workers:

| bid | n | arch | cat | h | area | verts | occupations | shifts |
|---|---|---|---|---|---|---|---|---|
| 2318 | 6 | CIVIC_SPECIAL | education | 16.7 | 56 341 m² | 20 | student ×5, childcare_worker | all day |
| 6059 | 4 | BIG_BOX_COMMERCIAL | commercial | 8.5 | 19 778 m² | 8 | accountant, grocery_clerk ×2, courier | all day |
| 4384 | 3 | CIVIC_SPECIAL | medical | 8.9 | 5 575 m² | 14 | care_worker, nurse, doctor | day, night, day |
| 7466 | 3 | SMALL_COMMERCIAL | commercial | 9.2 | 11 684 m² | **4** | office_worker, grocery_clerk, window_washer | all day |
| 3735 | 3 | SMALL_COMMERCIAL | commercial | 8.79 | 21 399 m² | 26 | grocery_clerk, barista, office_worker | all day |
| 3995 | 3 | CIVIC_SPECIAL | education | 15.5 | 10 118 m² | 16 | student ×3 | all day |
| 4587 | 3 | OFFICE_HIGHRISE | commercial | 49.0 | 2 272 m² | 36 | cleaner, grocery_clerk, barista | night, day, day |

2318 is the outbreak certification's index-case building
(`docs/outbreak/OUTBREAK_V1_REPORT.md:272,227` — citizen 42 @ 2318, disruption at
14:20 with 3 of 6 down). **Changing what happens inside 2318 changes the certified
outbreak trace.**

Workplace footprint areas (Houston, 169 used): BIG_BOX n=54 min 2 096 / med 4 632 /
max 19 778; SMALL n=55 158 / 947 / 21 399; CIVIC n=34 210 / 4 886 / 56 341;
INDUSTRIAL n=21 435 / 3 665 / 29 029; OFFICE_HIGHRISE n=5 1 776 / 1 917 / 2 815.
(`SMALL_COMMERCIAL` is a shape label, not a size label.)

### 3.5 Recommended three job archetypes

1. **RETAIL_FLOOR** — 137/214 Houston workers (64 %). `grocery_clerk (23),
   barista (14), waiter (11), chef, courier` onto `shop_floor/back_room/storeroom`
   with existing `gondola/checkout/fridge_case/pallet_rack` decor. Task spines are
   already station-shaped verbs: `open till → restock → checkout → cash up`
   (`citizen.py:1113`), `open → morning rush → restock → clean` (`:1166`),
   `set up → service → bus tables → close` (`:1163`).
2. **DESK_OFFICE** — `office_worker (18) + it_support (10) + accountant (7) +
   social_worker` = 35+. Rooms `open_office/meeting/break_room` exist with
   `cubicle/printer/filing_cabinet/monitor`. `email → standup → meetings →
   spreadsheets → calls` maps desk / meeting-table / desk / desk.
3. **CLEAN_PATROL** — `cleaner (15) + security_guard (12) + window_washer (3) = 30`,
   and the only **building-agnostic** archetype: works in retail, office, civic and
   industrial shells alike, and is the natural fit for Houston's 51 night-shift
   citizens who otherwise have an empty building. `supplies → offices → restrooms →
   lock up` and `briefing → patrol → monitor cctv → patrol` are room-traversal, not
   station-dwell — a different affordance shape.

Not recommended for V1: stocking as its own archetype (it is a task inside
RETAIL_FLOOR); medical (only 14 Houston workers, and `_ARCH_HINT_MAP` sends
`CIVIC_SPECIAL` → `civic`, so the rooms will not be clinic rooms).

Demo buildings (Houston, ≥3 compatible workers): **6059** (BIG_BOX, 4 workers,
retail rooms, 8-vertex footprint — cleanest RETAIL_FLOOR), **7466** (a true 4-gon,
no AABB simplification) and **3735**, **4587** (office rooms, night cleaner + two
day workers — exercises DESK_OFFICE and CLEAN_PATROL across shifts). Avoid 2318
and 3995 (education → civic rooms; 2318 is the outbreak cert building).

---

## 4. LOD, SAVE/LOAD, BRIDGE, GODOT SHAPES

### 4.1 Save

`save.py:42` — `SAVE_VERSION = 3`. `world_state` (`:257-300`) embeds two opaque
blocks; `load_world` (`:302-327`) stashes them as `_pending_mobility_state` /
`_pending_outbreak_state`:

```python
"mobility": (None if world.mobility is None else world.mobility.to_state()),
"outbreak": (None if world.outbreak is None else world.outbreak.to_state()),
```

`MobilityRuntime.to_state` (`embodied/runtime.py:586-609`): `now_s`, `accum`,
`focus_xy`, per citizen `{runtime, executor, band, frozen_at, last_slot,
retry_at}`, plus `vehicles`, `vehicle_of`, `parking_occupied`, `parking_nodes`,
non-unit `congestion`, `obstructions`. `_runtime_state` (`:628-…`) persists
`current_activity`, goals, itinerary; `from_state` at `:657-744`.

`TripExecutor.to_state` (`executor.py:629-654`) — 25 keys including `state`,
`activity`, `step_index`, `plan_serial`, `dwell_s`, `trips_completed`, `override`,
`itinerary`, `ped`, `car`, and **`trace[-50:]` / `state_log[-50:]`**. Every
`ex.event(...)` a work runtime emits lands in the save and in the byte-identical
comparison.

`OutbreakRuntime.to_state` (`outbreak/runtime.py:615-627`): `seed`, `pathogen`,
`now_s`, `accum`, `next_contact_s`, `next_undead_s`, `event_seq`,
`events[-5000:]`, `records`, `disrupted_buildings`, `obstructions`,
`undead_targets`, `undead_roam`, `undead_roam_t`, `attack_cooldown`,
`known_threats`.

### 4.2 Bridge rows

`citizen_row(cid)` (`embodied/runtime.py:521-546`) — 23 keys: `citizen_id, x, y,
heading, speed, state, activity, building_id, vehicle_id, step, step_index,
n_steps, progress, destination, band, goal, goal_target, override, failure,
trip_failed, blocked, in_vehicle_speed`. `snapshot()` (`:567-583`) wraps
`{version, t_s, focus_xy, n_citizens, n_vehicles, near:["cit:<id>"…], citizens,
vehicles, routes}`. `World.mobility_snapshot` (`orchestrator.py:318-324`) then
calls `_merge_health` (`:326-332`) which stamps `row["health"]` — **the exact
"stamp the row" shape a work runtime should copy.**

Session: `ADVANCE_TIME` with `snapshot="mobility"` (`bridge/session.py:232-238`);
`GET_MOBILITY` (`:291-296`); `MOBILITY_REPORT` (`:241-253` →
`apply_physical_report`, `embodied/runtime.py:495-518`).

### 4.3 Godot `EmbodiedMobility`

`embodied_mobility.gd:55-123`, per id in `block["near"]`:

```gdscript
if st in ["on_foot","approaching_vehicle","entering_vehicle","exiting_vehicle","undead"]:
    var body := _ensure_citizen(id, row)
    body.set_follow_target(Vector3(row.x, _ground_y + body_height, row.y), row.speed * time_scale)
elif st in ["corpse","incapacitated"] and int(row.get("building_id",-1)) < 0 and row.get("vehicle_id") == null:
    ...
```

then vehicles, then `for id in bodies.keys(): if not keep.has(id): queue_free()`.
**Citizens in `inside_building`/`doing_activity` get no body and are actively
freed**; `embodied_mobility_gate.gd:366` asserts `no_bodies_inside`.
`_physics_process` (`:126-137`) posts `collect_report()` (`{id,x,z,blocked}`).
Because interiors are staged at `Vector3(0,0,9000)` (`isometric_world.gd:31`), an
interior worker body's world position is **not** its authoritative xy — a work
body cannot be driven from `row.x/row.y` without an interior offset transform.

### 4.4 Gate pattern for a WorkGate

`tools/run_outbreak_gate.sh`: pkill stale server → `python3 -m
asphodel.bridge.server --host 127.0.0.1 --port $PORT` in background → poll
`connect_ex` ≤30 s → `godot --headless --path godot res://tests/OutbreakGate.tscn
-- --bundle houston --citizen 42 --trace <abs> --game-dt 0.1` → kill server →
`echo GATE_EXIT=$CODE TRACE=$TRACE` → exit with the gate's code.

`outbreak_gate.gd`: `_ok(name, cond, detail)` appends `"PASS|FAIL name detail"`
and bumps `_fail` (`:37-42`); `_info` (`:44-46`); `_ready` parses
`--bundle/--citizen/--trace/--game-dt` (`:49-62`); `_finish` (`:403-420`) enforces
a **minimum check count** (`if n < 12: _ok("all_checks_ran", false, …)`), prints
the block, writes `{version, bundle, citizen_id, game_dt, results, stats, events,
rows}` JSON, and `get_tree().quit(1 if _fail > 0 else 0)`.

### 4.5 LOD

`LODController` (`lod/entity.py:49-90`): defaults `physical_radius=120`,
`near_radius=400`, `route_radius=3000`, `hysteresis=40`; mobility overrides to
`physical_radius=150.0, near_radius=400.0` (`embodied/runtime.py:92-93`) with
`max_active = 1024` (`:94`). `_update_bands` (`:333-364`) folds `NEAR_SIMPLIFIED`
back into `ROUTE_SIMULATED` ("V1: no separate near-simplified citizen tier",
`:349-350`), uses `ABSTRACT` only as overflow past `max_active` (`:351-352`), and
sets `ex.has_body = (band == PHYSICAL)` (`:364`).

Semantics (`embodied/runtime.py:14-22`):
**ABSTRACT** — not registered here; `embodiment.resolve_physical_location` (pure
schedule state) is the FAR authority; also the frozen-overflow band
(`deactivate:326-331`, `activate:309-325` catching up in `CATCHUP_SUBSTEP_S=5.0`).
**ROUTE_SIMULATED** — registered + active; the itinerary executes in
`SUBSTEP_S=1.0` steps, no Godot body. **PHYSICAL** — within `physical_radius` of
focus; a Godot body exists and `apply_physical_report` reconciles.

---

## 5. EXTENSION POINTS — what the outbreak reads off `TripExecutor`

| field / property | defined | read by |
|---|---|---|
| `ex.inside` (`INSIDE_BUILDING ∪ DOING_ACTIVITY`) | `executor.py:149-151` | `_contacts:354,358`; `_undead:405,406,413`; `_witnesses:511,512,529,530`; `_flee:264`; `_disruption_scan:576`; `_on_reanimation:225` |
| `ex.building_id` | `executor.py:98` | `_contacts:354,355`; `_undead:406`; `_witnesses:511,529`; `_flee:265`; `_disruption_scan:576`; `_where:116`; `_on_death:202` |
| `ex.vehicle_id` | `executor.py:99` | `_contacts:356,357`; `_where:116`; `_on_reanimation:217-221`; `_on_death:203` |
| `ex.pos` | `executor.py:96` | `_contacts:359,366`; `_undead:408,412`; `_witnesses:512,530`; `_flee:266,276`; `_where:115`; `_on_death:201` |
| `ex.in_vehicle` | `executor.py:144-147` | `_contacts:358`; `_undead:410` |
| `ex.override` | `executor.py:123` | `_witnesses:504`; `_advance:275`; `alive_for_contact:270-272` |
| `ex.state` | `executor.py:97` | `_on_incapacitation:191`; `_go_home:247-248`; `_witnesses:521`; `_where:117` |
| `ex.current_step`, `ex.step_index` | `executor.py:136,103` | `_go_home:249-250` (TRIP_ABORTED) |
| `ex.set_override(kind, now_s, speed)` | `executor.py:238-268` | the only **write** into the executor |
| `ex.car`, `ex.speed` | `executor.py:115,101` | `_abandon_vehicle:555-557` |

Plus, off the runtime: `mobility.execs`, `.citizens`, `.records`
(`CitizenRecord.work_building_id`, `.schedule`), `.vehicles`, `.graph`,
`.entrances`, `.node_for_building`, `._errand_building`, `.reconciler`.

**`_contacts` (`outbreak/runtime.py:331-368`)** — the whole building is one
well-mixed compartment (`:354`):

```python
if sx.inside and vx.inside and sx.building_id == vx.building_id and sx.building_id >= 0:
    context, rate = f"building:{sx.building_id}", p.building_rate_per_h
```

With rooms this becomes `room:{bid}:{room_id}` at a higher rate, with a lower or
zero cross-room rate. `context` already appears in `EXPOSURE`/`INFECTED` events,
`HealthRecord.exposure_context` and the cert trace — refining it is
**trace-visible**. `_d(sx.pos, vx.pos)` is deliberately unused indoors because all
indoor positions are the same entrance anchor; station positions would make
indoor distance meaningful for the first time.

**`_disruption_scan` (`:565-586`)** — building-granular hazard test (`:574-576`):
a corpse in the `storeroom` need not disrupt the `shop_floor`; and station
occupancy would let "the checkout is unmanned" be a disruption reason distinct
from `workplace_disruption_fraction` (`:580`).

**`_witnesses` (`:492-536`)** — two same-building proximity tests (`:511-512`,
`:529-530`). Today everyone inside a 56 000 m² school sees every corpse in it
instantly. And `:521-522` is the **only** place `DOING_ACTIVITY` is distinguished
from `INSIDE_BUILDING` in outbreak logic:

```python
elif wx.inside and wx.state == EmbodimentState.DOING_ACTIVITY:
    self._flee(wcid, tcid, f"corpse of citizen {tcid} here")
```

A work runtime introducing a `WORKING` state, or leaving workers in
`INSIDE_BUILDING` between stations, silently changes this rule.

**`_reissue_constraints` (`:303-328`)** — called once a game minute from
`_substep:157`; re-pushes health goals and, per disrupted building, a
`DO_ACTIVITY(home, activity="rest", source="disruption", priority=0.78)` for every
worker still on the schedule work goal (`:320-321`). It exists because
`sync_schedule` wipes schedule goals every sync (`citizens/runtime.py:95`).
**A WorkRuntime must obey the same rule**: anything it pushes into the goal stack
must be re-pushed, or live outside the stack.

`workers_by_building` (`:87,91-96`) is built once at construction from
`records[cid].work_building_id`, is not re-indexed on later registration, and is
not saved (rebuilt in `from_state`, `:631`) — the natural index to share.

`choose_index_case` (`:132-141`) scans `s.activity == "work" and 6.0 <=
s.start_hour <= 10.0`. Restructuring work slots **changes the index case and the
entire certified Houston trace.**

---

## 6. RISKS

**Byte-identical save/load.** `tests/test_embodied_saveload.py:162` saves at four
interruption points (walking / driving / parked / **inside_work**), steps live and
restored worlds at `DT = 1.0`, compares `json.dumps(_state(w), sort_keys=True)`
(`:114,130`); `:173` asserts `states["inside_work"] in ("inside_building",
"doing_activity")`. `tests/test_outbreak_saveload.py:173` does the same for a
ten-minute continuation, plus identical records (`:135`), events + disrupted
buildings (`:144`), overrides (`:153`). Breakers: any new `to_state` key not
restored identically; any `ex.event(...)` (trace is saved, `executor.py:651`); any
change to `state_log` cadence (`executor.py:232-235` appends on every state change
— WORKING↔INSIDE_BUILDING oscillation would flood it and the `[-50:]` window would
diverge between runs with different pre-save history); float drift once indoor
`pos` stops being exactly the entrance anchor (`executor.py:597`); **any new RNG**
(`embodied/runtime.py:11-12` documents zero simulation RNG — station choice must
be a pure hash like `occupant_anchor:583` or `outbreak.health.roll`); and any
change to the `_last_slot` key (`runtime.py:480`, saved at `:596`).

**Day-test and gate expectations.** `test_embodied_mobility_day.py:323` (08:02
`activity=="work" and state=="doing_activity"`), `:109`, `:170`, `:342`;
`test_embodied_executor_day.py:48,173,277`;
`embodied_mobility_gate.gd:381-382` (same 08:01 assertion in engine), `:366`
`no_bodies_inside`, `:181`, `:438`; `embodied_mobility_shot.gd:200,203,223`;
`outbreak_gate.gd:408` (≥12 checks) plus the citizen-42-at-2318 storyline.
**A new `EmbodimentState` member for work breaks all of these at once, in both
languages.** The compatible move: keep `DOING_ACTIVITY` + `activity == "work"` as
the outer state and put station detail in *new* fields.

**GET_INTERIOR contract.** `to_dict()` (`interiors.py:165-181`) is the wire shape;
`interior_builder.gd:97-98` reads `hull[0]`/`hull[2]` as opposite corners, so a
non-rectangular hull breaks the floor/ceiling code silently. `geometry_hash()`
(`:183-186`) hashes the whole dict — **adding a `stations` key to the descriptor
changes every building's hash**, which `convergence_gate.gd:207` and
`live_interior.gd` compare. `INTERIOR_GEN_VERSION` must be bumped for any change
to partition, fixture placement or archetype mapping (`:44-47`), and an older-
gen_version delta must be *surfaced, never silently reinterpreted*. The
`fixtures ↔ containers` 1:1 invariant (`:462-472`) is load-bearing for survival
save/load — **stations must not be fixtures**. `building_occupants` returns
`{citizen_id, room_id, x, y, activity, action, in_roster}` consumed by
`embodied_mobility_gate.gd:368-375` and `isometric_world.gd:538-544`.

**Performance.** Baseline (`docs/outbreak/OUTBREAK_V1_REPORT.md:285-297`, Houston
297 citizens, 4-core, per game minute): off-peak 05:00 **21.4 ms** (mobility 21.2,
outbreak 0.27); commute peak **168.7 ms**; infection-heavy 12:00 with 19 undead
**245.8 ms**. At 24×, the heaviest minute uses 9.8 % of budget (10.2× headroom).
Exposures: `SUBSTEP_S = 1.0` means 60 substeps/game-minute, and today working
citizens are skipped in all 60 (`runtime.py:469-470`) — ticking ~78 on-duty Houston
citizens is 4 680 extra per-citizen calls per game minute, which at the 21 ms
off-peak baseline is the difference between 10× and ~2× headroom if the per-call
cost approaches the mobility per-citizen cost. `_contacts` is already
O(sources × citizens) at 1/60 Hz; room-aware context adds a lookup per pair,
distance-aware adds a `hypot`. `building_occupants` is O(registered citizens) per
`GET_INTERIOR` (`orchestrator.py:438-449`) — polling per visible workplace makes
it O(buildings × citizens). `build_interior` runs fresh on every `GET_INTERIOR`
(no cache, `orchestrator.py:374-392`) and already emits 13 249 decor items for
building 2318. In Godot, materialising interior worker bodies adds bodies,
`collect_report()` rows and `MOBILITY_REPORT` payload where today there are none.

**Others.** `ex.inside` is `INSIDE_BUILDING ∪ DOING_ACTIVITY` and ten outbreak
call sites assume it — a work state outside that union silently disables contact,
hunting, witnessing and disruption for workers. `adopt()` demotes DOING_ACTIVITY →
INSIDE_BUILDING on every plan change (`executor.py:219-220`) and `sync_schedule`
replaces schedule goals every game minute, so work progress held on the executor
state machine resets once a minute unless it lives outside the plan. Two positions
for one indoor citizen already exist (executor entrance anchor vs
`occupant_anchor` hashed room point); a station adds a third unless one is made
authoritative. Building 2318 is the certified outbreak index-case site. And
nothing in `citizens.json` distinguishes a workplace beyond `arch`/`cat`.

---

## Recommended handoff design

**Hook.** `WorkRuntime.advance(dt)` from `World.advance_seconds`
(`orchestrator.py:303-306`) immediately after `mobility.advance` and before
`outbreak.advance`, so it sees a settled situation and the outbreak sees its
result. Per citizen it acts only when `ex.state == DOING_ACTIVITY and ex.activity
== "work"` — it *consumes* the existing state, adds no `EmbodimentState` member,
changes no existing string. Relax `embodied/runtime.py:469-470` to
`… and cid not in work.active` so working citizens stop being unconditionally
skipped. Read `ScheduleSlot.task` (already present, `citizens/runtime.py:33`) as
the intent; do not route it through `Goal.activity`.

**It must never own:** position/movement (the `TripExecutor` is the only body
authority; a station move is `ex.pos = station.xy`, never a parallel controller);
goals or plans (`CitizenRuntime` only — and `sync_schedule` wipes schedule goals
every minute, so re-issue like `_reissue_constraints` or store outside the stack);
health (`OutbreakRuntime`); containers/items (`survival` + `items`, keyed
`(building_id, container_index)`); interior geometry (`interiors.build_interior`);
the `fixtures ↔ containers` 1:1 invariant; LOD banding; and the wire shape of
`state`/`activity`.

**Minimal data model** — derived, not stored; a pure function of
`(world_seed, building_id, gen_version)` + the `InteriorDescriptor` the bundle
geometry already yields, exactly like `occupant_anchor` (`interiors.py:572-588`):

```
Station(station_id, building_id, room_id, x, y, facing, kind, capacity=1)
   kind ∈ {checkout, register, shelf_bay, stockroom_rack, desk,
           meeting_seat, patrol_node, supply_closet}
Affordance(station_kind, action, min_s, max_s)      # a static table, not state
WorkPost(citizen_id, building_id, station_id)       # derived: stable integer hash
```

Generate stations from `Room` rects (`room_id`, `x0..y1`, `kind`) reusing the
perimeter-first 3 m slot grid `_place_decor` already computes
(`interiors.py:507-520`), so stations and decor cannot overlap. Emit them under a
**new `stations` key on `interior_state()`, not on `InteriorDescriptor`** — that
leaves `geometry_hash()` and `INTERIOR_GEN_VERSION` untouched and
`interior_builder.gd` working unchanged.

Runtime state — the only new save bytes — as a `"work"` block beside
`"mobility"`/`"outbreak"` in `save.py:292-296`, never inside
`TripExecutor.to_state`: `{cid: {station_id, action, started_s, elapsed_s}}`, four
scalars per on-duty citizen (~78 in Houston). No RNG; selection by integer hash of
`(seed, citizen_id, building_id, task)`.

Fix before building on rooms: `interiors.py:437` picks a room count ignoring area
and `:417-429` AABBs any non-rectangular footprint — together they yield one
413×388 m `lobby` for building 2318 (§2.7). Scale `target` by hull area, or place
stations on the footprint rather than on `Room`.

Ship a `WorkGate` (`godot/tests/WorkGate.tscn` + `work_gate.gd` +
`tools/run_work_gate.sh`, artifacts `artifacts/work_v1/`) mirroring
`outbreak_gate.gd` — `_ok/_info`, the same four CLI flags, minimum check count,
JSON trace, `quit(1 if _fail)`. Demo on 6059 (retail, 4 workers) and 4587 (office
plus a night cleaner). Do not certify against 2318.

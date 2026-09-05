# ASPHODEL_SMART_OBJECTS_WORK_V1 — Report: smart objects, rooms, stations and real work execution

**Verdict: `ASPHODEL_SMART_OBJECTS_WORK_V1: PASS`** — all 28 gates PASS (§4).
Read §19 (remaining debt) before reading anything into "PASS" beyond what
the gates measure.

## 1. Provenance

| item | value |
|---|---|
| starting SHA | `a9192b1` (two documentation commits after the certified outbreak SHA `d72d63c`), branch `claude/asphodel-embodied-mobility-v1-6gl4a8` |
| merge base with `origin/main` | `bee2f18a1827` |
| final SHA | `FINAL_SHA_PLACEHOLDER` (pushed to `origin/claude/asphodel-embodied-mobility-v1-6gl4a8`) |
| commits in this milestone | COMMITS_PLACEHOLDER |
| certification city | Houston (`godot/bundles/houston`, 300 citizens, 297 registered, 211 employed) |
| tooling | CPython 3.11.15, Godot 4.4 stable headless + xvfb/Mesa, 4-core shared container |

Artifacts: `artifacts/smart_objects_work_v1/{one_day_trace,save_load_trace,godot_probe_trace,city_smoke,performance,regression}.json`.
Evidence: `docs/work/evidence/` (§17). Architecture: `SMART_OBJECTS_WORK_V1_ARCHITECTURE.md`. Audit: `WORK_AUTHORITY_AUDIT.md`.

## 2. Authority census (what owns what)

| concern | owner | new / unchanged |
|---|---|---|
| citizen identity, CitizenRuntime goals/planning, typed itinerary steps, TripExecutor, vehicles, entrances, LOD bands, bridge session, save/load framing, outbreak health and overrides, Godot exterior embodiment | unchanged owners | unchanged |
| rooms, doorways, entrance, furniture positions | `asphodel/interiors.py` (canonical, deterministic; gen version 2: retail back rooms gained seating) | extended |
| functional zones, doorway graph, interior routing | `asphodel/smart/rooms.py::RoomGraph` | new |
| smart objects (identity, kind, capabilities, affordances, capacity, mutable state) | `asphodel/smart/objects.py::SmartObjectRegistry` per building | new |
| reservations / occupancy | `asphodel/smart/reservations.py::ReservationLedger` (one per world) | new |
| jobs, tasks, employment | `asphodel/smart/jobs.py` (grammar + `employment_for`) | new |
| task execution, interior locomotion, customers, residents, queues, workplace function | `asphodel/smart/runtime.py::WorkRuntime` on `World.advance_seconds` after mobility and outbreak | new |
| errand destination | `MobilityRuntime._errand_building` (unchanged owner; now prefers a staffed shop open at the errand hour, data from the bundle) | extended |
| bridge | protocol v6: `GET_WORK`, `GET_ROOMS`, `SET_OBJECT_STATE`, `START_WORLD.work`; mobility rows carry `work` | extended |
| Godot | `EmbodiedMobility` interior mode: bodies inside the staged interior at the authoritative position, holder markers | extended |

No second citizen, navigation, schedule or object authority was introduced.
The audit (`WORK_AUTHORITY_AUDIT.md`) found the existing interior
descriptor, the `DOING_ACTIVITY` steady state and the outbreak's
`_where` as the three hook points; all three are used as-is.

## 3. Architecture (summary; full text in the architecture document)

```
building ─► room/zone ─► station ─► smart object ─► affordance ─► action
CitizenRuntime (goal) ─► TripExecutor (to the building, DOING_ACTIVITY) ─► WorkRuntime (rooms, objects, tasks)
                       ◄──────── executor leaves DOING_ACTIVITY (new plan / override) ◄── session ends, holds released
```

* **Room model**: the descriptor's BSP rooms (world-metre rectangles) with a
  semantic zone per room kind and BFS routing over doorway points.
* **Object model**: every furniture piece of the descriptor is a
  `SmartObject` with a stable id `so:<building>:<k>`; behaviour is composed
  from capabilities (`station`, `transact`, `desk_work`, `shelf`, `stock`,
  `storage`, `seat`, `bed`, `table`, …), never keyed on a name; at most 40
  objects per room; only changed state is persisted.
* **Affordance model**: `Affordance(name, exclusive, duration, requires,
  effects)`; a checkout is `occupy_station + transact + clean`, a cubicle
  `occupy_station + desk_work + clean`, a shelf `restock + browse + clean`, a
  bed `sleep`, a chair `sit`.
* **Reservation model**: exclusive objects have one holder; shared objects
  a capacity; a citizen holds one exclusive object; every hold/release is
  an event and is persisted.
* **Job/task grammar**: `JobRole → TaskDefinition[] (affordance, selector,
  preconditions, duration range, effect, hold)`; the runtime is a generic
  interpreter; employment is `employment_for(seed, cid, occupation,
  workplace, objects)`.
* **Procedural generation**: a generated retail interior knows its
  registers, shelves, racks and (v2) back-room seats; a generated office its
  cubicles, desks, break-room chairs; homes their beds and chairs. No
  hand-authored layout exists for any city.

## 4. Certification table (`tests/test_work_v1_day.py`, Houston, 05:00→18:30)

```
FINAL_TABLE_PLACEHOLDER
```

Workers and workplaces are chosen from the data by the test itself (the
retail workplace with the most day-shift cashiers and midday errand visitors;
the workplace with the most desk workers; the day-shift cleaner with the most
cleanable objects). The day's stressor is the certified Outbreak V1 index
case, which supplies the health, threat and workplace-disruption
interruptions deterministically.

## 5. Certification trace: one citizen's workday

Citizen **297** (occupation courier, employed as a **cashier** at retail
workplace **15873**, assigned station `so:15873:5` in room 0 / sales_floor).
Times are game clock; ids are the authoritative ones from
`artifacts/smart_objects_work_v1/one_day_trace.json`.

| time | event | detail |
|---|---|---|
| 05:00 | asleep at home 3448 (resident session on a bed object) | non-work affordance |
| 07:2x | leaves home, commutes with existing mobility (`left_building 3448`, `walk_done`, `entered_building 15873`) | TripExecutor, unchanged |
| 07:36 | `CLOCK_IN` at 15873; `RESERVED so:15873:5` (exclusive); `TASK_START man_register`; `MOVE_TO_OBJECT` (4 waypoints through doorways) | WorkRuntime takes over inside |
| 07:37 | `USE_START` at `so:15873:5`, 0.01 m from its interaction point | S7 |
| 08:11 … 10:32 | `man_register` instances of 30–40 min each on the same station (the station stays held across instances) | S10 |
| 10:39–10:59 | **14 customers served** (`SERVED` 222, 82, 277, 8, 19, 169, 143, 25, 132, 167, 287, 221, 40, 81), each after browsing a shelf and queueing at the register; the register's `served` state reaches 14 | S13, S11 |
| 11:30 | LOD probe: focus onto the shop for 1 s → band PHYSICAL, same object/task, progress continuous, one holder; back to ROUTE_SIMULATED | S18/S19 |
| 12:00 | scripted stressor: `so:15873:5` set `working=false` → `OBJECT_UNAVAILABLE`, hold evicted; **within the same second `RESERVED so:15873:50`** (the alternative station) and `USE_START` there | S9 |
| 12:35 | the station is repaired (12:20); at the next task boundary the cashier switches back: `RESERVATION_RELEASED so:15873:50 (switched station)`, `RESERVED so:15873:5` | S9 |
| 13:13 … 15:38 | further `man_register` instances | |
| 15:59 | schedule ends the shift: `RESERVATION_RELEASED (shift_end)`, **`CLOCK_OUT` served=14** | S14 |
| 16:00+ | existing mobility carries the citizen home; at home a `sit` (chair) session | S16 |

The cashier took no break in this day: the break-room seating added in
interior v2 is used by 51 cashiers city-wide before 14:00, but 297's
break-due check fires only at a task boundary and its long queue window
coincided with one. Honest note, not a gate.

Second thread, the **cleaner**: citizen 243 at workplace 4587 (office/retail
mix): `fetch_supplies` at storage `so:4587:1` (07:37) → `clean_object`
`so:4587:113` (07:40) → `so:4587:77` → `so:4587:10` → `so:4587:3` → new
supplies at `so:4587:42` → … 190 tasks over 18 distinct objects, 11 objects
set `dirty → False` (S12, S11), shift ends `CLOCK_OUT cleaned=11`.

Third thread, the **desk workers** at civic building 2318 (42, 87, 117, 135,
247): each holds its own desk in room 2 (office zone), `desk_work` instances
of 45–90 min increment the desk's `documents_done`; at 11:00 the outbreak
query can tell 87 (on a break seat), 117/135/247 (at desks
`so:2318:9185/9173/9182`) apart (S17).

## 6. Contention

* **Natural**: 9 `RESERVATION_DENIED` city-wide over the day (desk workers
  whose preferred desk is held); each resolved by an alternative station or
  a 30 s bounded wait in the role's zone; 4260 `WAIT` events are workers
  with nothing doable (mostly cleaners with everything clean) standing in
  their zone and retrying — never a deadlock, never a duplicate hold.
* **Scripted**: the cashier's register broke at 12:00 (S9 above): eviction,
  immediate substitution, return after repair.
* **Invariants**: 810 per-minute samples of the ledger, 0 exclusive objects
  with two holders, 0 citizens with two exclusive holds (S8); the smoke tool
  repeats the check 721× per city (§14).

## 7. Mutable world state ("what did this employee accomplish?")

`shift_log` per completed session: 297 served 14; 243 cleaned 11; 42
completed 1 document before its health override. City-wide in the day: 926
`STATE_CHANGE` events — registers' `served`, desks' `documents_done`,
objects `dirty → False` by cleaners (and `→ True` by use, a 0.30 hash roll),
shelf `stock` depleted by browsing customers and restored by stockers,
supplies drawn from storage. All of it is authoritative Python state saved as
deltas and restored identically (S20–S22).

## 8. Interruption

Seven `WORK_INTERRUPTED` events in the certification day, all caused by
existing systems:

| time | citizen | reason | at |
|---|---|---|---|
| 09:54 | 42 | `health:do_activity` (symptom onset → health goal) | desk_work at `so:2318:9179` |
| 11:05 | 247 | `health:do_activity` | take_break at `so:2318:9183` |
| 14:14 | 117 | `health:do_activity` | desk_work at `so:2318:9185` |
| 14:20 | 87, 135, 170 | `disruption:do_activity` (WORKPLACE_DISRUPTED 2318) | desk / break seat / cleaning |
| 15:39 | 191 | `emergency:flee` (attacked by an undead) | inspect at `so:4075:449` |

In each case the executor left `DOING_ACTIVITY` under the planner's new
goal, every hold was released at that instant (S15: 0 leaks), and the
planner/executor owned what followed (S16: 42 later `trip_failed` under an
emergency goal as an undead, 191 became a corpse, the disrupted workers went
home). Object unavailability (S9) and shift end (148 `CLOCK_OUT`) are the
other two interruption classes.

## 9. Outbreak interaction

`OutbreakRuntime._where` now stamps `room_id`, `zone` and `object_id` on
every outbreak event (the day trace shows 76+ such events), `GET_ROOMS`
returns occupants per room and objects with holders, and
`workplace_status` gives a functional reading (stations, staffed stations,
workers present, queued customers; `open / reduced_function / closed`). The
exposure model is unchanged in V1 (building co-occupancy); the substrate to
weight by room or station is in place.

## 10. LOD

Headless: the runtime is band-agnostic (the day ran with the focus 9 km
away); a 1 s promotion of the shop kept the session's object, task, progress
and single holder (S18). In-engine (WorkGate): the player left the building
and moved 1.5 km away — no bodies for the shop's workers, the session
continued on the same object/task for 20 game minutes; on return the body
was recreated 0.000 m from the authoritative interior pose on the same
object (S19). Performance is identical FAR vs NEAR (§13).

## 11. Save/load

`artifacts/smart_objects_work_v1/save_load_trace.json`: saves while walking
to a station (08:01), using a station (08:31), waiting (a queued customer,
10:35), mid multi-step task (cleaner carrying supplies, 07:38), just after an
interruption (09:55) and in the work-to-home transition (16:01). Every
restore has identical sessions, ledger and object state and the 10-minute
continuation of the whole world is byte-identical. Two persistence defects
were found and fixed on the way: the shop predicate was not applied when a
saved mobility runtime was restored (errand nodes diverged), and a restored
walking undead lost its shambling speed.

## 12. Godot

WorkGate (`tools/run_work_gate.sh`, houston / cashier 68 / workplace 12013,
live bridge, the real IsometricWorld scene, player following the worker):
22 PASS / 0 FAIL. It proves, with the CitizenBody inside the staged interior:
the commute into the workplace by existing mobility; the body materialized
0.00 m from the authoritative interior pose; `to_object → using` with the body
walking 41.6 m inside the interior; the station held exclusively in 8/8
samples; a customer served by that worker at that station; the broken
station substituted within 5 game seconds; STATE_CHANGE in the building;
save/load mid-use identical; no bodies while far, session unchanged, body
recreated on return; CLOCK_OUT at shift end with an empty ledger and the
citizen on foot outside. Godot decides nothing: interior bodies follow the
authority; physics reports are not fed back for interiors (documented in the
script header).

## 13. Performance (`tools/work_perf.py`, Houston 297 citizens, 4-core shared container)

| measurement | ms | detail |
|---|---|---|
| smart-object registration, all 167 workplaces | 713 | 12 046 objects, mean 4.3 ms, max 74 ms (building 2318); descriptors cached after the first build |
| registration, all 295 homes | 544 | 9 595 objects |
| task selection | 0.096 / call | 38.6 calls per game minute (3.7 ms) |
| reservation queries | 0.84 µs hold+release, 0.10 µs is_free / holders_of | |
| work.advance 06:00 (297 residents asleep) | 5.7 per game-min | total 20.1 (mobility 14.4) |
| work.advance 09:00 (159 workers walking to stations) | 13.3 | total 28.5 |
| work.advance 11:00 (80 customers, 159 workers) | 17.0 | total 52.8 (mobility 34.7) |
| work.advance 17:00 (shift end, commute) | 7.3 | total 24.0 |
| interior navigation | 2.6–4.4 µs per route; `_walk` 1.0 ms per game-min (7 % of work) | rooms are 3 per building today |
| FAR vs NEAR focus | work 12.2 vs 12.6 | band-agnostic |
| commute peak 07:00 with workers active | mean 545 per game-min, **worst minute 10 887 ms at 07:30 (10 879 of it mobility route planning at mass departure)** | pre-existing mobility spike; work 5 ms in that minute |
| outbreak + work 11:00 | total 40.1 (mobility 21.3, outbreak 5.7, work 12.9) | |
| worker-heavy (297 employed at 5 workplaces) | work 9.5 | |

At 24× (2.5 s real per game minute) the work layer uses < 1 % of the budget
in every scenario; the heaviest whole-block total (52.8 ms) is 2 % of it.
The one budget breach is the mobility mass-departure minute, which predates
this milestone (the outbreak report measured 20-minute blocks and missed it);
it is listed as debt with the measurement, not fixed here. Hotspots (cProfile,
20 game minutes at 10:00): `_session_kind`/`_substep` scanning 297 citizens ×
60 substeps (mitigated by the sleeping-session skip), `_walk` 1.9 %,
`room_of` 1.2 % (linear over rooms; trivial at 3 rooms per building).

## 14. Multi-city smoke (`tools/work_city_smoke.py`, 05:00→17:00, 60 s steps)

| city | status | citizens | employed (roles) | workplaces with objects | objects | registers / desks / shelves | clock-ins | uses | state changes | served / queued / unserved | denied | interrupted | clock-outs | workers who used an object | invariants (721 checks) | 3 h replay | ms per game-min |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| houston | PASS | 297 | 211 (cashier 52, cleaner 118, desk 31, stocker 10) | 166 | 11 935 | 848 / 282 / 3 882 | 155 | 16 794 | 929 | 31 / 99 / 94 | 13 | 0 | 155 | 155 / 155 | 0 violations | identical | 133 |
| madisonville_tx | PASS | 53 | 41 (cashier 8, cleaner 25, desk 7, stocker 1) | 30 | 2 390 | 178 / 36 / 833 | 29 | 3 543 | 164 | 4 / 11 / 13 | 3 | 0 | 29 | 29 / 29 | 0 violations | identical | 6 |
| austin | PASS | 60 | 46 (cashier 6, cleaner 26, desk 14) | 45 | 3 385 | 156 / 177 / 808 | 35 | 3 679 | 262 | 2 / 14 / 20 | 0 | 0 | 35 | 35 / 35 | 0 violations | identical | 42 |
| san_antonio | PASS | 60 | 46 (cashier 4, cleaner 29, desk 11, stocker 2) | 41 | 3 185 | 132 / 138 / 746 | 35 | 3 666 | 243 | 1 / 11 / 18 | 0 | 0 | 35 | 35 / 35 | 0 violations | identical | 32 |
| boulder | INFO | — | no compiled world (`world/spawn_anchors.json.gz` absent) | | | | | | | | | | | | | | |

Every usable city employs its citizens from its own data, generates objects
for its own workplaces, clocks in, uses objects, changes state, serves
customers where a staffed shop is open when errands happen, never violates a
reservation invariant (721 checks per city) and replays 3 game hours
identically from two fresh worlds. Boulder has no compiled world (INFO). No
city-name branching exists (S28 greps the layer and the tools).

## 15. Regression

* Python: 1 126 collected, 1 125 passed, 1 pre-existing environment failure
  (`test_world_from_compiled::test_compile_writes_only_presentation_files`,
  raw Overture parquet; identical on `origin/main`). The new work packages
  (205 tests: smart objects, reservations, jobs, runtime day, save/load, LOD,
  bridge) and the smoke test are included.
* Mobility day suites (25) and outbreak certification (O1–O22, all PASS)
  re-run after the errand change and the kerb/interior changes.
* Godot: `godot/tests/run_gates.sh` 85 PASS / 0 FAIL; MobilityGate
  24/24 PASS; OutbreakGate 18/18 PASS (the abandoned-car row is INFO in this run: the index case collapsed on foot); WorkGate 22/22 PASS, re-run on the final runtime.
  (`artifacts/smart_objects_work_v1/regression.json`.)
* Two tests were updated for the milestone: the outbreak bridge test accepts
  protocol ≥ 5.

## 16. Work archetypes actually implemented

| role | pattern stressed | what the day showed |
|---|---|---|
| cashier (52 citizens) | fixed exclusive station, customer queue, break seat (v2), substitution when the station breaks | 297: 14 served, station switch and return; 51 cashier breaks city-wide |
| desk_worker (31) | selected free workstation, long tasks, contention on desks, breaks | 2318's five desk workers on five desks, `documents_done` increments, 9 denials resolved |
| cleaner (118) | dynamic target selection over many objects, carrying supplies between storage and target, state change | 243: 190 tasks over 18 objects, 11 cleaned |
| stocker (10, data-driven fourth) | retrieve goods from a rack, restock the most depleted shelf | 134 shelf stock changes city-wide |
| customer (errand-goers) and resident (sleep/sit) | the same affordance layer outside work | 286 customer arrivals, 31 served, 297 residents on beds/chairs at 06:00 |

## 17. Rendered evidence (`docs/work/evidence/`, `manifest.json`)

Frames come from the real IsometricWorld scene with the player inside the
staged interior of workplace 12013 (cutaway camera), live bridge; captions
in the manifest carry the authoritative rows at capture time.

| file | what the frame shows |
|---|---|
| `00_arrival.png` | the shop floor cutaway with gondolas/fridge cases; the worker's body on the floor after the commute delivered it inside (a holder ring is visible) |
| `01_walk_to_station.png` | the same room seconds later, the worker mid-floor between shelf rows walking to `so:12013:5` |
| `02_using_station.png` | the worker at the register mesh, tinted with the `using` look, a gold holder ring at the station |
| `03_service_interaction.png` | the register at the instant the SERVED event was drained; the cashier at the station. The customer body is not distinguishable in this frame — the service is evidenced by the event, not the pixels |
| `04_task_switch.png` | **NOT REACHED**: the cashier kept `man_register` for the captured hour; the frame shows it at the register. Task switching is evidenced by the cleaner's trace (§5) and by `05_contention.png`, not by this frame |
| `05_contention.png` | after `working=false`: the worker has left the register and the holder ring has moved to the substitute station on the right |
| `06_interruption.png` | the back room after the shift ended: no interior body for the worker (it is outside), matching `state on_foot` |
| `07_leaving.png` | the exterior parking lot; **the body exists but is not visible** — exterior bodies sit below this lot's surface mesh because the scene never calls `set_ground_y` (pre-existing, §19) |
| `08_after_promotion.png` | two bodies in the room: the re-promoted worker highlighted at its station with the ring, and a co-worker |

## 18. Multi-agent interaction

Customers are ordinary citizens on their schedule's errand slot whose errand
destination is a staffed shop open at that hour. In the certification day 14
of them queued at 297's register and were served one by one (~90 s each);
city-wide 84 queued, 31 served, 117 left (shops closed for the evening
errands of day workers, a cashier on break, or the customer's schedule moving
it on — each `CUSTOMER_UNSERVED` carries the reason). A shop whose workers are
present but no register is staffed is flagged `WORKPLACE_REDUCED_FUNCTION`
(19 flips in the day) and `WORKPLACE_RESTORED` when a till is manned again.

## 19. Remaining debt (explicit)

* **Rooms are AABB rectangles**: Houston's largest buildings (2318, 6059)
  have 3 rooms each; a 400 m school hall is one room. Interior navigation is
  therefore lightly stressed (straight lines through ≤ 2 doorways).
* **No furniture avoidance indoors**: the authority walks straight lines
  through a room; Godot bodies collide with fixtures and are re-materialized
  when stuck; physics is not fed back for interiors.
* **Exposure still keys on the building**; room/object context is queryable
  (`_where`, `GET_ROOMS`, `occupants_by_room`) but not yet used to weight
  contacts.
* **Customers only via the errand slot**; day workers' errands fall outside
  shop hours, so most of the day's customers are home-anchored citizens.
* **Cashier breaks depend on a task boundary**; a long service window can
  postpone one past the shift.
* **No inventory**: carrying is a flag; goods/supplies have quantities on
  objects only.
* **Mobility mass-departure spike** (10.9 s in the 07:30 game minute,
  route planning) breaks the 24× budget for two minutes a day; pre-existing,
  measured here for the first time minute by minute.
* **Exterior body ground height**: `EmbodiedMobility.set_ground_y` is never
  called by the isometric scene, so exterior bodies can render below raised
  surfaces (`07_leaving.png`).
* **Event ring**: 5000 rows roll over in ~45 game minutes at Houston scale;
  consumers must drain `GET_WORK since_seq` every minute (`counts` are
  persistent).
* **Static interior occupants** (`GET_INTERIOR` anchors) and live interior
  bodies coexist; the renderer hides the static one when a live body exists.
* One session per bridge process (`START_WORLD` cannot restart), so the
  Godot gate spends ~5 min advancing from 00:00 to the shift.

## 20. Recommended next milestone

**NPC decision, social behaviour and memory.** The world now has enough to
reason about: who is at which station, what they accomplished, who served
whom, which object broke, which room a threat is in. A bounded next step is
a per-citizen memory of observed facts (objects, coworkers, threats) feeding
the existing goal stack (help / substitute / complain / avoid a room), with
dialogue lines generated from `context()` and `shift_log` — no new spatial
authority needed.

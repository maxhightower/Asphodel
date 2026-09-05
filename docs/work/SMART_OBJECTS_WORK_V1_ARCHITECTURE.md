# ASPHODEL_SMART_OBJECTS_WORK_V1 — Architecture: rooms, smart objects and work execution

The building stops being one room with a timer in it. A citizen the
TripExecutor delivered into a building now walks to a room, reserves and uses
a smart object, changes its state, and is interrupted by the same events that
already interrupt trips. This document is the reference for what became
canonical; the certification is `SMART_OBJECTS_WORK_V1_REPORT.md`; the audit
that preceded the design is `WORK_AUTHORITY_AUDIT.md`.

## 0. The hierarchy and the chain

```
building ─► room / zone ─► station ─► smart object ─► affordance ─► action
(interiors.py)  (smart/rooms.py)      (smart/objects.py)            (smart/runtime.py)

CitizenRuntime ──goal──► TripExecutor ──DOING_ACTIVITY inside B──► WorkRuntime
     ▲  (schedule / health / emergency / disruption)                  │ interior locomotion,
     │                                                                │ task selection,
     └──────── executor leaves DOING_ACTIVITY (new plan / override) ◄─┘ reservations, object state
```

| concern | authority | file |
|---|---|---|
| rooms, doorways, entrance, furniture positions | the canonical interior descriptor (deterministic from seed + footprint; zero persistent bytes) | `asphodel/interiors.py` |
| functional zone of a room, doorway graph, interior routing | `RoomGraph` (regenerable view over the descriptor) | `asphodel/smart/rooms.py` |
| smart object identity, kind, capabilities, affordances, capacity, **mutable state** | `SmartObjectRegistry` per building; state *deltas* persisted | `asphodel/smart/objects.py` |
| who holds what | `ReservationLedger` (one per world; persisted) | `asphodel/smart/reservations.py` |
| roles, tasks, employment | `JobRole` / `TaskDefinition` grammar; `employment_for` (pure function of seed, citizen, occupation, workplace objects) | `asphodel/smart/jobs.py` |
| task execution, interior locomotion, customers/residents, queues, workplace function | `WorkRuntime` on the movement clock (after mobility and outbreak) | `asphodel/smart/runtime.py` |
| getting to the building, the entrance, leaving, the trip home | unchanged: `CitizenRuntime` + `TripExecutor` | `asphodel/citizens`, `asphodel/embodied` |
| health, threats, disruption | unchanged: `OutbreakRuntime`; it now *reads* room/object context | `asphodel/outbreak/runtime.py::_where` |
| persistence | save v3 `work` block (employment, sessions, ledger, object deltas, queues, events, counts) | `asphodel/save.py`, `World.enable_work()` |
| bridge | protocol v6: `GET_WORK`, `GET_ROOMS`, `SET_OBJECT_STATE`, `START_WORLD.work`; mobility rows carry `work` | `asphodel/bridge/{protocol,session}.py` |
| embodiment | Godot places live bodies inside the staged interior at the authoritative interior position; it decides nothing | `godot/scripts/embodied_mobility.gd` |

Nothing in Godot decides a task, a reservation or an object state; nothing in
the WorkRuntime plans a city trip or touches health.

## 1. Rooms and zones

Rooms are the descriptor's rectangles (a BSP partition of the footprint
AABB inset by the wall margin) joined by doorways into a spanning tree, with an
entrance on the street-facing wall. `RoomGraph` adds:

* a **zone** per room kind (`shop_floor → sales_floor`, `back_room →
  employee_area`, `storeroom → stock_room`, `open_office → workspace`,
  `meeting → meeting_room`, `break_room`, `office`, `waiting`, `exam →
  treatment`, `supply → storage`, `living → living_room`, `bedroom`,
  `kitchen`, `bathroom`, …);
* `room_of(xy)`, `rooms_of_zone(zone)`;
* `route(from_xy, to_xy)`: BFS over doorways; the waypoints are the doorway
  points between the two rooms followed by the target. This is the whole of
  interior navigation in V1: rooms are convex rectangles, so a straight line
  inside a room is always walkable, and a doorway is a point on the shared
  wall.

All coordinates are world metres (the descriptor is built on the real
footprint), so an interior position is a normal `TripExecutor.pos`.

## 2. Smart objects

`SmartObject`: `object_id = so:<building>:<k>` (k = generation order:
container fixtures first, then decor), `kind`, `building_id`, `room_id`,
pose (`x`, `y`, `facing`), `use_xy` (0.9 m in front along `facing`),
`caps` (capabilities), `affordances`, `exclusive`, `capacity`, `state`.

`OBJECT_KINDS` composes behaviour from capabilities, never from names:

| kind | caps | affordances (exclusive?) | state |
|---|---|---|---|
| checkout | station, transact, counter | occupy_station (excl, cashier), transact (excl, cashier), clean | working, dirty, served |
| cubicle / desk / teacher_desk | station, desk_work | occupy_station, desk_work (excl, desk_worker), clean | working, dirty, documents_done |
| gondola / shelf / fridge_case | shelf, stock, browse | restock (shared, stocker → stock=100), browse (shared), clean | stock, dirty |
| pallet_rack / crate / freezer_case | storage, goods | retrieve_goods (shared, stocker) | stock |
| cabinet / locker / filing_cabinet / fridge | storage | use_storage (excl) | locked / stock |
| chair / stool / armchair | seat | sit (excl) | dirty |
| sofa / bench / pew | seat | sit (shared, capacity 2–4) | — |
| table / cafeteria_table | table, surface | eat (shared), clean | dirty |
| bed | bed | sleep (excl) | made |
| toilet / sink / stove | toilet / sink / stove+cook | use_toilet / wash / cook, clean | dirty, on |
| workbench / machine / exam_table / printer / med_cart / water_cooler | station or machine or storage | occupy_station / use_machine / retrieve_supplies / drink | working, supplies, stock |

Any decor kind without an entry is registered as a `prop` (stable identity,
no affordances) so it can gain behaviour later without renumbering.

**Generation.** `SmartObjectRegistry(building_id, descriptor)` converts every
container fixture and decor piece into an object. A room contributes at most
40 objects and at most 12 of one kind (the interaction layer stays bounded
even for a 400 m school hall dressed with thousands of presentation pieces);
ids are assigned before the cap so they never shift. `state_deltas()` returns
only objects whose state differs from the kind default; that is all the save
carries.

**Initial condition.** A deterministic 25 % of cleanable objects start the day
dirty and 40 % of shelves start partly depleted (hash rolls on the object id),
so maintenance roles have real work from the first shift.

## 3. Reservations

`ReservationLedger.hold(obj, cid, now, exclusive)` succeeds only when an
exclusive object has no holder or a shared one has free capacity; a citizen
holds at most one exclusive object (a new exclusive hold releases the old
one). `release(cid[, object_id])`, `release_object(object_id)` (eviction when
an object breaks), `holders_of`, `held_by`, `is_free`. Fully persisted; every
hold and release is an event (`RESERVED`, `RESERVATION_DENIED`,
`RESERVATION_RELEASED`, `OBJECT_UNAVAILABLE`).

## 4. Job / task grammar

```
JobRole(name, workplace_zones, tasks, break_after_s, break_s, required_caps)
TaskDefinition(task_id, affordance, selector, caps, duration_s=(lo,hi), priority,
               interruptible, precondition, effect, hold, carry)
```

selectors: `assigned` (the employment's station, else nearest free with the
caps), `any_free`, `dirtiest`, `depleted`, `supplies`/`goods` (storage),
`seat` (break-room seating first); preconditions: `break_due`,
`customer_waiting`, `has_supplies`/`needs_supplies`, `has_goods`/`needs_goods`;
effects: `served`, `documents`, `clean`, `restock`, `rest`, `supplies`,
`goods`. The WorkRuntime is a generic interpreter: it walks the role's tasks
by priority, keeps the first whose precondition holds and whose target can be
reserved, executes it (walk → use → complete → effect), and otherwise waits
in the role's idle zone and retries every 30 s.

Certified roles (`ROLES`): **cashier** (man_register on the assigned
checkout; serve_customer while a customer is queued; clean_station;
take_break on a seat), **desk_worker** (desk_work on any free workstation;
tidy_desk; take_break), **cleaner** (fetch_supplies from storage →
clean_object on the dirtiest object → repeat; inspect shelves when nothing is
dirty). A fourth data-driven role, **stocker** (fetch_goods from a rack →
restock the most depleted shelf), is assigned where a retail workplace has
more clerks than tills.

**Employment** (`employment_for`): occupation → preferred roles
(`grocery_clerk → cashier, stocker, cleaner`; `office_worker → desk_worker,
cleaner`; `cleaner → cleaner` …); the first role whose required
capabilities the workplace's objects offer is taken; cashiers and desk
workers get an assigned station chosen by `hash64(seed, cid, "station")`
among the stations not yet assigned at that workplace. Employment is computed
for every registered citizen with a workplace at `World.enable_work()` and
persisted; a fresh world reproduces it exactly.

## 5. Sessions

`WorkRuntime._session_kind(cid)` decides, every substep, whether a citizen is
in an interior session: the executor must be inside a building in
`DOING_ACTIVITY` with no pending step and no health override. Then:

* activity `work` at the citizen's workplace → **worker** session (`CLOCK_IN`);
* activity `sleep` (or any activity at home) → **resident** session (sleep in
  a bed, sit on a chair/sofa: the non-work affordances);
* activity `errand`/`leisure`/`arrived` elsewhere → **customer** session
  (browse a shelf, then queue at a staffed register and get served; a visitor
  in a non-shop sits).

A session is an `ActivityState` (kind, role, phase `idle | to_object | using
| waiting | done`, task, object, room, waypoints, progress, worked time
since the last break, carried item, tallies of served / documents / cleaned
/ restocked, `next_s` wake time). Sessions sleep between substeps that cannot
change anything (a 45-minute desk task wakes at its end; a cashier with an
empty queue wakes every minute), so the runtime costs milliseconds per game
minute for 300 citizens.

**Interior locomotion.** `to_object` moves the executor's `pos` along the
room-graph waypoints at 1.3 m/s (the citizen enters through the door point
first when it stands at the entrance). This is the only place the
WorkRuntime moves a citizen and it only happens inside a building the
executor already delivered it to.

**Customers.** `CUSTOMER_ARRIVED` → browse (shared hold on a shelf, stock
−8) → `CUSTOMER_QUEUED` at the least-loaded staffed register (queue positions
are 1 m apart behind the interaction point) → served by the cashier's
`man_register` task in ~90 s (`SERVED`, register `served += 1`) → done. A
customer with no staffed register waits up to 10 min then leaves
(`CUSTOMER_UNSERVED`) and the workplace is flagged
`WORKPLACE_REDUCED_FUNCTION` until a register is staffed again
(`WORKPLACE_RESTORED`).

**Object state.** Completing a use applies the affordance's effect (dirty →
False, stock → 100, documents_done += 1, supplies/goods carried); each
completed service or desk task dirties the object with probability 0.30 (hash
roll), each browse depletes the shelf. `set_object_state(object_id, key,
value)` is the authoritative external change (a register breaks, a door
closes): holders are evicted with `OBJECT_UNAVAILABLE`, their session goes
back to `idle` and re-selects (an alternative station, or a bounded wait).

## 6. Interruption

The WorkRuntime never traps a citizen: on every substep it re-derives the
session kind from the executor. The moment the executor leaves
`DOING_ACTIVITY` (the schedule's next slot was adopted, a `health` goal, an
`emergency` FLEE, a `disruption` goal, an override `incapacitated / corpse /
undead`), the session ends: every hold is released, queue entries are
removed, and `WORK_INTERRUPTED` (reason `health:*`, `emergency:*`,
`disruption:*`, `left`) or `CLOCK_OUT` (`shift_end`) is emitted with the
task, object and progress at that instant. The planner and executor are not
touched; they already own what happens next.

## 7. Outbreak integration

`OutbreakRuntime._where` stamps every event with `room_id`, `zone` and
`object_id` from `WorkRuntime.context(cid)` when the layer is enabled;
`occupants_by_room(building)` partitions a building's occupants by room;
`GET_ROOMS` exposes objects with holders and queues. Exposure itself still
uses building co-occupancy in V1 (the substrate is in place; the contact
model is next). Workplace failure gains a functional meaning:
`workplace_status(bid)` reports stations, staffed stations, workers present
and queued customers, and a shop with no staffed register is
`reduced_function` (workers present) or `closed`.

## 8. LOD

The runtime is band-agnostic: sessions progress identically whether the
citizen is ROUTE_SIMULATED or PHYSICAL (there is no ABSTRACT freezing of
registered citizens since the outbreak milestone). Promotion creates a body
at the authoritative interior position; demotion frees it; the ledger and the
session are untouched by either. Interior bodies follow the authority
(follow mode); physics reports are not fed back for interiors in V1 (the
authority does not hold back for an interior body).

## 9. Persistence

The `work` block: employment, sessions (all `ActivityState` fields incl.
waypoints and wake times), ledger, per-building object deltas, queues,
reduced flags, the last 5000 events plus persistent per-kind counts, the
completed-session log (what each shift accomplished). `World.enable_work()`
after `enable_mobility` restores it; the registries are regenerated from the
descriptor and the deltas re-applied; no task target is re-rolled.

## 10. Extension points

* **Dialogue / social**: `context(cid)` (role, task, object, room, zone) and
  `shift_log` (what a worker accomplished, why the session ended) are the
  facts an NPC can talk about; coworkers are `occupants_by_room`.
* **Outbreak**: doors are `Doorway`s of the descriptor; a `door` kind with
  `open/locked` state and a `lock` affordance fits `OBJECT_KINDS` without
  touching the runtime; `route()` can honour locked doorways; rooms give
  "hide in" targets.
* **Survival / base building**: fixtures already anchor to the authoritative
  containers; a player-placed object is a registry entry with the same
  affordance vocabulary.
* **Richer exposure**: `_contacts` can use `room_id`/`object_id` from the
  context instead of `building_id`.

## 11. Known limits (V1)

* Rooms are rectangles from an AABB; large non-rectangular footprints get one
  hall (the school in Houston is one 400 m room with three zones).
* Interior movement is straight lines through doorway points; no obstacle
  avoidance around furniture (bodies in Godot collide with fixtures and are
  re-materialized when stuck).
* No inventory: "carrying supplies/goods" is a flag on the session.
* Customers exist only through the schedule's errand slot and only at shops
  (retail interiors with an employed cashier).
* The exposure model still keys on the building; the room/object context is
  queryable but not yet used to weight contacts.

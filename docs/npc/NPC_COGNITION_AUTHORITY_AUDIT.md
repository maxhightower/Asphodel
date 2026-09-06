# NPC COGNITION AUTHORITY AUDIT — pre-milestone survey for ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1

Repo `/home/user/Asphodel`, branch `claude/asphodel-embodied-mobility-v1-6gl4a8`, HEAD `285828b`.
Read-only audit; every claim is a `file:line` at that SHA. Nothing was implemented here.

> **In-flight work.** While this audit was written, a parallel session began the
> milestone in this worktree: `asphodel/cognition/` exists **untracked**
> (`beliefs.py`, `memory.py`, `personality.py`, `relationships.py`, `social.py`)
> and tracked files are already dirty (`citizens/goals.py` — a
> `"belief": 0.60` entry added to `SOURCE_BASE_PRIORITY`; `outbreak/runtime.py`,
> `smart/jobs.py`, `smart/runtime.py`). **All line numbers below are against
> committed HEAD `285828b`** (`git show 285828b:<path>`), not the working tree.

---

## 1. DECISION AUTHORITY TODAY

### 1.1 The chain

```
CitizenProfile.schedule (citizen.py:272)
 -> MobilityRuntime._slots        (embodied/runtime.py:212-229) -> ScheduleSlot
 -> CitizenRuntime.sync_schedule  (citizens/runtime.py:88-97)
      + goal_from_schedule        (citizens/goals.py:128-153) -> Goal
 -> GoalStack.select_active       (goals.py:103-117)            [hysteresis]
 -> CitizenRuntime._plan_for_active (citizens/runtime.py:174-209) -> Itinerary
 -> TripExecutor.advance/_in_place  (embodied/executor.py:226-235, 314-338)
 -> WorkRuntime._substep            (smart/runtime.py:202-234)  [consumes DOING_ACTIVITY]
 -> OutbreakRuntime                 (pushes competing goals, §2)
```

Everything an NPC "decides" is a `Goal` in a `GoalStack`. There is no second
decision producer.

### 1.2 `GoalStack` — sources, priorities, hysteresis

`Goal` (`goals.py:38-59`): `kind, target, reason, source, priority, deadline,
activity, id`; `to_dict` (`:49-59`) is the debug/wire shape. `GoalKind`
(`:19-24`): `ARRIVE_AT, DO_ACTIVITY, RETRIEVE, FLEE, IDLE`.

`SOURCE_BASE_PRIORITY` (`goals.py:28-35`) is the whole priority vocabulary:
`idle 0.10, need 0.35, social 0.45, schedule 0.55, emergency 0.92, player 1.0`.
**`"social": 0.45` already exists with no producer** — nothing in `asphodel/`
constructs `Goal(source="social")`; its only reader is the `_drop_goals` wipe
list at `outbreak/runtime.py:235`.

Selection: `_best` sorts by `(-priority, deadline, id)` (`:93-101`) — no RNG.
Hysteresis in `select_active` (`:103-117`): a different goal preempts only when
`best.priority >= active.priority + preempt_margin` (default `0.05`, `:70`) or
the active goal is gone. `would_preempt` (`:119-123`) is the read-only test.
`push` assigns ids from `self.seq` (`:79-82`, `:77`), persisted as `goal_seq`
(`embodied/runtime.py:660`, restored `:746`) — reproducible across save/load.

### 1.3 `CitizenRuntime` (`citizens/runtime.py:37-74`)

Owns `schedule`, `needs` (`:47-48`, energy/hunger/safety/social), `goals`,
`active_goal`, `itinerary`, `current_node`, `inside_building`/`in_vehicle`
(`:65-67`), `node_meta` (`:68-70`), `plan_serial` (`:74`).

* `sync_schedule` (`:88-97`) — **replaces all `source == "schedule"` goals every
  sync** (`:95`). A new layer's goals must use a non-`schedule` source *and* be
  re-pushed on a cadence, or be lost.
* `push_goal(goal, graph)` (`:100-106`) — the one sanctioned mutation point for a
  competing goal; returns whether it preempts. `push_emergency` (`:108-115`) is
  the existing wrapper.
* `note_situation(node, inside_building, in_vehicle, vehicle_node)` (`:130-142`)
  — the execution layer reports *physical situation* back. It carries no other
  agents: there is no perception channel today.
* `_reselect` (`:117-127`) replans only when the active goal id changed or there
  is no itinerary, so pushing a losing goal is side-effect-free.
* `debug()` (`:233-249`) already publishes `candidate_goals` and `needs`.

**The V1 stubs.** `self.beliefs: Dict[str, float] = {}` (`:49`) and
`self.relationships: Dict[str, float] = {}` (`:50`) are **dead**: repo-wide the
only other mentions are docstrings (`citizens/runtime.py:3`, `goals.py:4`). Never
written, never read, never saved (`embodied/runtime.py:655-676` omits them),
never on the wire. Flat `str -> float`, so they cannot carry provenance, decay,
timestamps or a subject id. **Supersede them with the new typed stores — do not
add a second belief dict beside them.** Being unsaved, replacing them costs no
save compatibility.

### 1.4 `_sync` cadence (`asphodel/embodied/runtime.py`)

`advance` (`:466-475`) integrates in fixed `SUBSTEP_S = 1.0` s substeps (`:47`);
`CATCHUP_SUBSTEP_S = 5.0` (`:48`) is only for re-activating a frozen citizen
(`:340-345`). In `_substep` (`:477-496`), `sync_now = (int(self.now_s) % 60 == 0)`
(`:479`) — schedules re-sync **once a game minute**, or on first sight (`:483`).
`_sync` (`:498-508`) is further keyed on
`f"{slot.start_hour}:{slot.activity}:{slot.location_node}"` (`:501`) and only
calls `sync_schedule` when that key changed or a failed trip is due for retry
(`:502-507`).

Two skips matter to perception: `ex.override in ("incapacitated","corpse")`
skips the citizen (`:487`), and an idle citizen inside a building with no step and
unchanged `plan_serial` is skipped (`:489-490`). A per-substep cognition tick
would defeat both; the 1/60 Hz precedent is `outbreak._reissue_constraints` and
`smart/runtime.py:860` `_minute_scan`.

### 1.5 The executor (`asphodel/embodied/executor.py`)

`_in_place` (`:314-338`) runs when there is no executable step. It sets
`DOING_ACTIVITY` **only** when `self.inside`, the active goal's target is
`rt.current_node`, and the building matches (`:322-330`), with
`activity = g.activity` (`:325`); else `INSIDE_BUILDING` + `"idle"` (`:334-336`)
or `ON_FOOT` (`:337-338`). `undead` is special-cased first (`:320-323`).
`_do_activity` (`:604-612`) is the one-shot, zero-duration arrival step.

`inside` = `INSIDE_BUILDING ∪ DOING_ACTIVITY` (`:150-151`). Health overrides
(`:122-126`, `set_override` `:238-268`) are the only external writes into the
executor; `_advance` refuses to move an `incapacitated`/`corpse` body
(`:274-275`); `adopt()` demotes `DOING_ACTIVITY` on every plan change (`:219-220`),
so cognition state parked on the executor is lost on replan. A social interaction
expressed as a goal is therefore rendered by `_in_place` as `DOING_ACTIVITY` with
`activity == goal.activity`; a new `EmbodimentState` member would instead break
Python and GDScript assertions at once (`docs/work/WORK_AUTHORITY_AUDIT.md:664-690`).

---

## 2. EXISTING CONSUMERS OF GOAL `source` STRINGS

The helper is `_drop_goals(rt, *sources)` (`outbreak/runtime.py:19-27`) — removes
by source *through the stack* so `active_goal` stays consistent (load-bearing for
byte-identical save/load).

| site | file:line | sources |
|---|---|---|
| schedule wipe | `citizens/runtime.py:95` | keeps all but `schedule` |
| `_on_recovery` | `outbreak/runtime.py:192` | `health` |
| `_on_incapacitation` | `outbreak/runtime.py:203` | `health, emergency, disruption` |
| `_on_reanimation` | `outbreak/runtime.py:235` | `schedule, health, emergency, disruption, idle, need, social, player`, then clears the stack (`:236-238`) |
| `_go_home` | `outbreak/runtime.py:246-255` | drops `health`; pushes `DO_ACTIVITY(home, activity="rest", source="health", 0.80)` (`:251-252`) |
| `_flee` | `outbreak/runtime.py:257-300` | dedups an in-flight flee (`:289-291`), drops `emergency` (`:292`), pushes `FLEE(source="emergency", 0.92)` (`:293`) |
| `_reissue_constraints` | `outbreak/runtime.py:302-337` | re-pushes `health` when missing (`:320-321`); per disrupted building pushes `DO_ACTIVITY(home, source="disruption", 0.78)` for workers whose active goal is still the `schedule` work goal (`:329-335`) |
| undead retarget / roam | `outbreak/runtime.py:450-453`, `:479-482` | `emergency, schedule, health, disruption` |
| `WorkRuntime._interruption_reason` | `smart/runtime.py:314-325` | `ex.override` first (`:315-316`); `emergency/health/disruption` -> `f"{source}:{kind}"` (`:317-318`); `schedule` -> `"shift_end"` (`:319-320`); not inside -> `"left"` (`:322-323`) |

Priority constants: `outbreak/runtime.py:47-50` — `FLEE 0.92`, `HEALTH 0.80`,
`DISRUPTION 0.78`, `UNDEAD 0.95`. A belief/social goal must sit **below 0.78**
unless it is meant to outrank a workplace disruption, and at least
`preempt_margin` (0.05) above `schedule` (0.55) to actually take over a shift.

**Unhandled-source hazard:** `_interruption_reason` falls through to
`"shift_end"` (`smart/runtime.py:324`), so a citizen leaving a shift for a social
goal would be logged as having *finished* it (`CLOCK_OUT` instead of
`WORK_INTERRUPTED`, `smart/runtime.py:296-303`). That branch is the minimum edit
a new source requires.

---

## 3. PERCEPTION-RELEVANT STATE WITHOUT OMNISCIENCE

### 3.1 Room-level co-presence

* `WorkRuntime.context(cid)` (`smart/runtime.py:893-907`) — `building_id,
  room_id, zone, object_id, task_id, phase, role`; all `None` when not inside
  (`:896-899`).
* `WorkRuntime.occupants_by_room(bid)` (`:909-917`) — `{room_id: [cid,…]}` from
  `ex.inside and ex.building_id == bid` plus the session's `room_id` (fallback
  `g.room_of(ex.pos)`). **The only room-granular "who is with whom" query today.**
* `WorkRuntime.row(cid)` (`:919-933`) — role/workplace/task/phase/object/room/
  zone/carrying, stamped on every mobility row by `_merge_work`
  (`orchestrator.py:316-319`); `workplace_status(bid)` (`:840-851`) — stations,
  staffed, workers present, customers queued, open/reduced/closed.
* `ActivityState` (`smart/runtime.py:54-92`) carries `room_id`, `object_id`,
  `task_id`, `phase`, `carrying`, and `served_by` (`:76`) — an existing truthful
  **dyadic** record (cashier ↔ customer).
* `WorkRuntime.events` (`:110`, vocabulary `EV` `:45-51`): `SERVED`,
  `CUSTOMER_ARRIVED`, `CUSTOMER_QUEUED`, `USE_START/USE_END`, `BREAK_START/END` —
  service and queue encounters, with citizen ids, already emitted.

`RoomGraph` (`smart/rooms.py:51-124`): `rooms`/`zones` (`:57-58`), doorway `adj`
(`:59-63`), `entrance_xy` (`:65`), `inside_xy` (`:68`), `room_of(xy)` (`:74`),
`zone()` (`:85`), `rooms_of_zone` (`:88`), `route()` BFS over doorways (`:91`),
`rows()` (`:119`); zone vocabulary `_ZONES` (`:22-40`). Ready-made substrate for
"same room" and "adjacent through a doorway", regenerable from the descriptor, so
it costs no save bytes.

### 3.2 Outbreak observation events and `_witnesses`

`event()` (`outbreak/runtime.py:104-111`); `_where(ex)` (`:113-126`) stamps
`x, y, building_id, vehicle_id, embodiment` and — when the work runtime is
attached — `room_id`, `zone`, `object_id` from `work.context` (`:119-125`), so
outbreak events are already room-tagged where rooms exist.

Kinds: `THREAT_OBSERVED` (`:529-531`, `:545-547`), `ATTACK` (`:494-496`),
`FLEE` (`:297-299`), `DEATH`/`CORPSE_CREATED` (`:212-216`), `REANIMATION`
(`:253-255`), `WORKPLACE_DISRUPTED` (`:597-599`); also `SYMPTOM_ONSET` (`:186`),
`INCAPACITATED`/`PLAN_INVALIDATED` (`:204-206`), `VEHICLE_ABANDONED`/
`ROAD_OBSTRUCTED` (`:568-575`).

`_witnesses` (`:504-548`) is the existing perception model, and its "near" test is
**building-level, not room-level** (`:511-512`, repeated for attacks `:529-530`):

```python
near = (wx.inside and tx.inside and wx.building_id == tx.building_id) or \
       (not wx.inside and not tx.inside and _d(wx.pos, tx.pos) <= THREAT_RADIUS_M)
```

`THREAT_RADIUS_M = 25.0` (`:46`) applies **outdoors only** — indoors, everyone in
a 56 000 m² school sees every corpse in it instantly. `_known_threats` (`:86`,
written `:517`, `:525`, `:538`, `:544`) is the only per-citizen memory in the
codebase: a `set` of threat ids, persisted `:639`, restored `:657-660`. It never
forgets and carries no timestamp, source or confidence — the honest precursor to
an episodic store, to be *migrated into* the new layer, not shadowed. The corpse
rule (`:531-533`) is the only outbreak logic distinguishing `DOING_ACTIVITY` from
`INSIDE_BUILDING`.

Refining `near` to room level (via `occupants_by_room` / `RoomGraph.room_of`) is
the highest-value perception change available — and it **changes the certified
Houston outbreak trace**, so it must be gated and re-certified in this milestone,
not slipped in.

### 3.3 Positions, bands, vehicles

* `TripExecutor.pos/heading/speed/state/building_id/vehicle_id/inside/override`
  (`embodied/executor.py:96-151`, `:122-126`) — the only body truth. Indoors,
  positions are the entrance anchor until `WorkRuntime._walk` moves them
  (`smart/runtime.py:375-390`, which writes `ex.pos`/`ex.heading` directly).
  `citizen_row` (`embodied/runtime.py:542-567`) is the wire row (position, state,
  activity, band, goal, override, failure); `snapshot` `:588-604`.
* LOD: `LODBand` (`lod/entity.py:17-23` — `PHYSICAL, NEAR_SIMPLIFIED,
  ROUTE_SIMULATED, ABSTRACT`), assigned in `_update_bands`
  (`embodied/runtime.py:354-386`). `NEAR_SIMPLIFIED` collapses into
  `ROUTE_SIMULATED` (`:371-372`); `ABSTRACT` is an overflow band only (`:357-365`)
  whose citizens are frozen (skipped at `:481-482`) and fast-forwarded on
  reactivation (`:336-345`). Cognition must survive that gap: tick only non-frozen
  citizens, or timestamp the store so a gap decays instead of replaying.
* Vehicles: `VehicleInstance` (`transport/instances.py:96-111`) declares
  `driver` and `passengers` (`:100-101`, serialised `:214`), but **`passengers` is
  never populated anywhere in `asphodel/`** — shared vehicle occupancy has no
  producer today. `driver` is the only maintained occupancy fact
  (`outbreak/runtime.py:243-247`, `:559`; read in `_contacts` `:356-358`).
* Building-level cohorts: `_contacts` (`outbreak/runtime.py:331-368`) mixes per
  `f"building:{bid}"`; `workers_by_building` (`:87`, built `:91-96`) is a ready
  workplace-cohort index.

---

## 4. EVENT STREAMS, RINGS, AND THE `since_seq` DRAIN

| stream | ring cap | seq | snapshot |
|---|---|---|---|
| `OutbreakRuntime.events` | `MAX_EVENTS = 5000` (`outbreak/runtime.py:51`), trimmed `:110-111` | `event_seq` (`:75`, `:106`) | `snapshot(since_seq=0, max_events=200)` (`:613-625`) — filters `seq > since_seq`, then keeps the **last 200** (`:624`) |
| `WorkRuntime.events` | `MAX_EVENTS = 5000` (`smart/runtime.py:43`), trimmed `:180-181` | `event_seq` (`:111`, `:175`) + persistent per-kind `counts` (`:112`, `:176`) | `snapshot(since_seq)` (`:935-944`), uncapped |
| `MobilityRuntime.events`/`.transitions` | **uncapped** (`embodied/runtime.py:110-111`) | none (`{"t","event",…}`) | not in `snapshot` |
| `TripExecutor.trace` | per-executor (`executor.py:129-135`), saved | none | — |

Both capped streams are drained by sequence, never index (`session.py:290`,
`:298`). Engine pattern: `godot/tests/work_gate.gd:125-146` — keep `_seq`, call
`SimBridge.get_work(_seq)`, advance `_seq = max(_seq, e["seq"])`, record the
persistent `counts` because the ring drops old rows (~45 game minutes at Houston
scale, `docs/work/SMART_OBJECTS_WORK_V1_REPORT.md:368`). **Consequence:** a
cognition stream needs its own ring + `event_seq` drained with `since_seq`, and
memory must form at emit time — the source events will be gone before a later
scan. Event lists are persisted (`outbreak/runtime.py:631`,
`smart/runtime.py:954`), so any new event enters byte-identical save/load tests.

---

## 5. EXISTING PER-CITIZEN IDENTITY DATA (read, never duplicate)

* **`CitizenProfile`** (`citizen.py:257-291`): `citizen_id, city, age, age_band,
  occupation, shift` (`:260-265`); districts/zones (`:267-270`); `schedule`
  (`:272`); `inventory` (`:273`); `spawn_hour, current_location,
  current_activity, current_task` (`:276-279`); resolved spatial refs
  `home_building_id, work_building_id, home_xy, work_xy, commute_metres,
  commute_mode, vehicle` (`:284-290`). **`home_building_id` is the household
  key** — co-residents are already derivable and must not be re-stored.
  `occupation` + `shift` drive schedule shape (`citizen.py:385-440`); shift hours
  are global constants, not per-citizen (`citizen.py:136-141`); `ScheduleEntry`
  (`:115-124`) carries the per-occupation `task` spine.
* **`roster.py`** — the bounded persistence LOD. `RosterRecord` (`:19-31`):
  `citizen_id, profile, needs, chosen_action, schedule_cursor,
  last_interaction_tick, promoted_tick, interactions`; `promote` (`:51-60`) is
  interaction-keyed, eviction least-recently-interacted with id tie-break
  (`:8-11`). **It already answers "which citizens are worth remembering in
  detail"** — key the detailed cognition tier off roster membership instead of
  inventing a second bound or fighting its eviction.
* **`npc.py`** — the *macro-tier* vocabulary: activity codes (`:25-28`), action
  codes `CONTINUE/SHELTER/FLEE/SEEK/SIGNATURE` (`:56-59`), needs
  `("safety","fatigue","hunger","social")` (`:62`), `_ACTION_NEED` (`:65-70`);
  contract at `:6-12` (activity is a label that never moves an agent; pure and
  deterministic). Its need names differ from `CitizenRuntime.needs`
  (`citizens/runtime.py:47-48`) — two need vocabularies already exist; pick one
  rather than adding a third.
* **`affordances.py`** — the Sims inversion: `_TAG_AFFORDANCE` (`:20-25`) maps
  place tags to `(action, utility)`; `advertise(tags, belief)` (`:38-50`) scales a
  `shelter` offer by a **scalar zone belief** and its inverse by
  `continue_schedule`. That is the codebase's existing meaning of "belief" (a zone
  float, macro tier); a per-citizen store must feed it or be distinguished by
  name — one word, two tiers, different semantics is this milestone's main
  vocabulary hazard.

---

## 6. PERSISTENCE

`SAVE_VERSION = 3` (`save.py:42`, history `:39-41`). `world_state`
(`save.py:257-302`) writes sibling nullable blocks: `"mobility"` (`:293`),
`"outbreak"` (`:295`), `"work"` (`:296`), `"survival"` (`:298-299`).
`load_world` (`save.py:303+`) constructs nothing; it parks the blocks
(`:327-329`):

```python
world._pending_mobility_state = state.get("mobility")
world._pending_outbreak_state = state.get("outbreak")
world._pending_work_state     = state.get("work")
```

Consumption is in the orchestrator (`orchestrator.py:157`/`:244-249`,
`:161`/`:272-276`, `:164`/`:301-305`) — each `enable_*` prefers the pending state
so employment/health are never re-derived. A cognition block follows exactly this
shape: `world.cognition` + `_pending_cognition_state`, a `"cognition"` key beside
`"work"`, an `enable_cognition()` that restores first. `"work"` was added without
bumping `SAVE_VERSION`; the per-block `{"version": …}` field is the convention
(`smart/runtime.py:947`, `outbreak/runtime.py:628`).

**Bridge LOAD ordering** (`bridge/session.py:532-566`), strictly sequential:
1. `load_world_file` (`:539`); 2. re-attach `CitySpatialContext` from the bundle
(`:552-556`); 3. mobility if pending (`:557-559`); 4. outbreak if pending **and
mobility exists** — "never re-seed" (`:560-562`); 5. work if pending and mobility
exists (`:563-565`). The whole block is wrapped in a bare
`except Exception: pass` (`:566-567`), so a failed restore is silent — a
cognition restore must be proven by a test, not by the session.

Advance order (`orchestrator.py:321-345`): mobility, then `outbreak.advance`
(`:341-342`), then `work.advance` (`:343-344`). Snapshot merges (`:356-364`):
`_merge_health` (`:366-372`) then `_merge_work` (`:316-319`), both stamping the
mobility citizen rows.

---

## 7. BRIDGE PROTOCOL v6 AND WHERE v7 SLOTS IN

`PROTOCOL_VERSION = 6` (`bridge/protocol.py:38`), history `:30-37` (v4 mobility,
v5 outbreak, v6 work). `is_compatible` requires an **exact** match (`:151-153`)
and the Godot client pins the same constant (`godot/scripts/sim_bridge.gd:23`) —
a v7 bump is a two-language, same-commit change.

Commands live in `Command` (`protocol.py:41-92`) and are validated against
`Command.ALL` (`:83-92`) by `request()` (`:120-122`): core `:44-55`, survival v2
`:58-65`, `GET_INTERIOR` v3 `:68`, `ADVANCE_TIME/MOBILITY_REPORT/GET_MOBILITY` v4
`:71-73`, `SEED_OUTBREAK/GET_OUTBREAK` v5 `:76-77`,
`GET_WORK/GET_ROOMS/SET_OBJECT_STATE` v6 `:79-81`. Handlers: `session.py:288-294`
(outbreak), `:296-301` (work), `:303-325` (rooms, objects with `holders`/`queue`,
entrance, `occupants` by room, `workplace_status`); clients `sim_bridge.gd:165`,
`:173`, `:184`.

A **v7 `GET_COGNITION`** slots in identically: constant beside `GET_ROOMS`
(`protocol.py:80-81`) plus `Command.ALL` (`:91`) and a version comment at `:38`;
a handler beside `_cmd_get_work` reading `since_seq` via `_opt_int`
(`session.py:296-301`); an orchestrator passthrough beside `work_snapshot`
(`orchestrator.py:312-313`); a `START_WORLD` option and `cognition_enabled` flag
mirroring `work_enabled` (`sim_bridge.gd:51`, set `:104`); and a client method
beside `get_work` (`:173-182`). Per-citizen summaries should ride the existing
row merge (`orchestrator.py:316-319`) as `row["cognition"]`, not a second
full-population query.

---

## 8. GODOT: HOW AUTHORITATIVE STATE IS DRAWN

`godot/scripts/sim_bridge.gd` is the only transport: `_send` (`:352`),
`get_work` (`:173`), `get_rooms` (`:184`), `get_outbreak` (`:165`),
`get_mobility` (`:202`); caches `last_work`/`last_rooms`/`last_outbreak`
(`:45`, `:52-53`).

`godot/scripts/embodied_mobility.gd`:
* `apply(block, game_dt)` (`:120+`) realises the NEAR band; rows keyed
  `"cit:%d"` (`:130-131`); on-foot/undead bodies `:137-146`, outdoor corpses
  `:159-166`, vehicles `:168-183`; interior bodies are drawn for everyone whose
  `building_id == interior_building`, **not** gated on the NEAR band (`:185-200`).
* `_apply_work_look` (`:401-427`) is the presentation rule to copy: it reads only
  `row["work"]["phase"]` (`:407-408`), guards with a `work_look` meta so
  re-application is free (`:409-412`), and **defers to a health look** if one is
  set (`:413-414`) — "nothing here decides a phase, it only draws one"
  (`:402-404`). `_apply_health_look` at `:324`.
* Holder rings: `refresh_object_markers` (`:455-500`) polls `GET_ROOMS` every
  `MARKER_REFRESH_S = 2.0` s (`:65`, `:447-453`), makes one `TorusMesh` per object
  with a non-empty authoritative `holders` array (`:466-469`, `:487-497`), keyed
  by `object_id` in `_markers` (`:74`), positioned at
  `interior_offset + (o.x, floor_y + 0.05, o.y)` (`:476`), and frees rings whose
  object lost its holders (`:500-505`). `marker_ids()` (`:508`) is the test hook;
  `_clear_markers` (`:512-520`).

A **social-action marker should follow this shape exactly**: periodic
authoritative poll, one node per authoritative record keyed by a stable id, a meta
guard, deference to stronger health looks, an id-list accessor for the gate — and
never an interaction inferred from positions.

---

## 9. RISKS OF DUPLICATION, AND RECOMMENDED INTEGRATION POINTS

**Where a naive implementation creates a second authority**

1. **Movement** — writing `ex.pos` outside the `WorkRuntime._walk` idiom
   (`smart/runtime.py:375-390`) makes a second body controller; `TripExecutor`
   owns the body (`executor.py:96-151`). "Stand next to X" is a goal or a
   work-layer walk, never a new integrator.
2. **Schedule** — deciding what a citizen should be doing now anywhere but
   `goal_from_schedule` (`goals.py:128-153`) duplicates the schedule authority and
   is overwritten once a game minute (`citizens/runtime.py:95`,
   `embodied/runtime.py:498-508`).
3. **Activity** — setting `ex.state`/`ex.activity` directly duplicates
   `_in_place` (`executor.py:314-338`) / `_do_activity` (`:604-612`); a new
   `EmbodimentState` member breaks both languages' assertions.
4. **Interior sessions** — a "conversation session" outside `WorkRuntime` gives
   one citizen two session owners: `_session_kind` (`smart/runtime.py:236-258`)
   already claims every `DOING_ACTIVITY` citizen inside a building as
   worker/customer/resident.
5. **Threat memory** — a second store beside `_known_threats`
   (`outbreak/runtime.py:86`, persisted `:639`) drifts from the flee rules that
   read it (`:517`, `:525`, `:538`).
6. **Beliefs** — two per-citizen stores (`citizens/runtime.py:49`), or two
   meanings of "belief" (per-citizen vs the zone scalar in
   `affordances.advertise`, `affordances.py:38-50`).
7. **Persistence** — restoring cognition before mobility, or outside the
   `_pending_*` pattern (`save.py:327-329`, `session.py:557-565`), breaks
   byte-identical save/load.
8. **RNG** — `embodied/runtime.py:11-12` records that the simulation has **zero**
   RNG; every derived choice is a pure hash (employment
   `smart/runtime.py:158-169`, `interiors.occupant_anchor`). Any social selection
   must hash `(seed, cid, other_cid, tick)`.

**Recommended integration points**

* **Goal push** — `CitizenRuntime.push_goal` (`citizens/runtime.py:100-106`) with
  the unused `source="social"` (0.45, `goals.py:32`) and/or a new `"belief"`
  source added to `SOURCE_BASE_PRIORITY` *and* to every list in §2. Whatever is
  pushed must be re-issued on a cadence mirroring `_reissue_constraints`
  (`outbreak/runtime.py:302-337`), or the once-a-minute sync wins.
* **Work task selection filter** — `_select_work_task`
  (`smart/runtime.py:396-417`) walks `sorted(role.tasks, key=-priority)` and skips
  a task whose `_precondition` (`:419-441`) is false. "Avoid the room where I saw
  a corpse" / "prefer the station beside my friend" belongs here as an extra
  precondition or selector filter — inside the existing task authority, changing
  no state machine. Fix `_interruption_reason` (`:314-325`) in the same edit.
* **Perception refinement** — `_witnesses` `near` (`outbreak/runtime.py:511-512`,
  `:529-530`): replace building equality with a room check via
  `occupants_by_room` (`smart/runtime.py:909-917`) / `RoomGraph.room_of`
  (`rooms.py:74`), with `RoomGraph.adj` (`rooms.py:59-63`) for "heard through the
  door". Trace-visible: gate it and re-certify.
* **Situation channel** — extend `note_situation` (`citizens/runtime.py:130-142`)
  or add a sibling `note_perception(...)`, so what was perceived arrives through
  one door, as physical situation does today.
* **Supersede the stubs** — replace `beliefs`/`relationships`
  (`citizens/runtime.py:49-50`) with typed, timestamped stores owned by the new
  runtime, exposed through `CitizenRuntime.debug()` (`:233-249`).
* **Wire and draw** — `GET_COGNITION` at protocol v7 (§7), a marker node
  following `refresh_object_markers` (`embodied_mobility.gd:455-500`), and a gate
  draining by `since_seq` like `work_gate.gd:125-146`.

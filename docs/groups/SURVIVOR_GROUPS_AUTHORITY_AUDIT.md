# ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 — Authority Census & Integration Audit

Status: audit only. This document changes no production code. It maps the existing
authorities a persistent survivor-**GROUP** social layer must integrate with (and
never bypass), documents each public API surface with `file_path:line` references,
and closes with a concrete integration plan for a `GroupRuntime`.

Scope reminder: groups sit **on top of** individual citizens. Every fact a group
"knows" must have entered some member's memory through the existing perception /
transmission path (`receive_fact`), every movement a group causes must be a
`Goal` pushed onto an individual `CitizenRuntime`, every conversation a group
triggers must go through `DialogueRuntime`, and every task must be a real
`WorkRuntime` task. The group layer owns **membership, shared objectives, and a
provenance-preserving shared record** — nothing physical.

---

## 0. The runtime stack at a glance

`World` (`asphodel/orchestrator.py:120`) owns an ordered chain of optional
runtimes, each depending on the one before:

```
mobility (MobilityRuntime)         asphodel/embodied/runtime.py:83   — THE physical authority
  └─ outbreak (OutbreakRuntime)    asphodel/outbreak/runtime.py:68   — health authority
  └─ work (WorkRuntime)            asphodel/smart/runtime.py:103     — rooms/objects/tasks
  └─ cognition (CognitionRuntime)  asphodel/cognition/runtime.py:82  — memory/beliefs/relationships
       └─ dialogue (DialogueRuntime) asphodel/dialogue/runtime.py:57 — grounded conversations
  [proposed] groups (GroupRuntime)  — membership + shared objectives + shared record
```

Enable dependencies are enforced with explicit `raise ValueError` guards:
`enable_outbreak`/`enable_work`/`enable_cognition` need `mobility`
(`orchestrator.py:277,306,329`); `enable_dialogue` needs `cognition`
(`orchestrator.py:348`). **A `GroupRuntime` should require `cognition`** (it reads
relationships/memory) and use `dialogue`/`work`/`mobility` when present.

Every runtime follows the same five-part contract, which the group layer must
copy verbatim:
1. `__init__(self, <upstream runtime>, world_seed, …)` — pure, deterministic.
2. `advance(dt_s)` — integrates in fixed 1 s substeps internally.
3. `snapshot(since_seq=0) -> dict` — event tape delta + counts + aggregate.
4. `to_state() -> dict` / `from_state(cls, st, …)` — JSON-safe, exact restore.
5. An event tape: `self.events`, `self.event_seq`, `self.counts`, an `event()`
   helper, capped at `MAX_EVENTS`.

---

## 1. World / orchestrator — `asphodel/orchestrator.py`

### Runtime slots and enable pattern
Slots are initialised to `None` with a paired `_pending_*_state` field
(`orchestrator.py:155–171`):
- `self.mobility` / `_pending_mobility_state` (`:155,:157`)
- `self.outbreak` / `_pending_outbreak_state` (`:160,:161`)
- `self.work` / `_pending_work_state` (`:163,:164`)
- `self.cognition` / `_pending_cognition_state` (`:167,:168`)
- `self.dialogue` / `_pending_dialogue_state` (`:170,:171`)

Each `enable_*` method (`enable_mobility:229`, `enable_outbreak:271`,
`enable_work:300`, `enable_cognition:323`, `enable_dialogue:344`) has the same shape:

```python
def enable_cognition(self, priors: bool = True):
    if self.mobility is None:
        raise ValueError("enable_cognition needs enable_mobility first")   # dependency guard
    pending = self._pending_cognition_state
    if pending is not None:                                                # LOAD path
        self.cognition = CognitionRuntime.from_state(pending, self.mobility, work=self.work,
                                                     outbreak_fn=lambda: self.outbreak)
        self._pending_cognition_state = None
        return self.cognition
    c = CognitionRuntime(self.mobility, self._seed, work=self.work, outbreak_fn=lambda: self.outbreak)  # fresh
    self.cognition = c
    if priors:
        c.init_priors(self.citizens)                                       # one-time seeding
    return c
```

**Where `enable_groups()` hooks in:** add `self.groups = None` +
`self._pending_groups_state = None` beside the others (`~:171`), and an
`enable_groups()` method after `enable_dialogue` (`~:357`) that guards on
`self.cognition is None`, restores from `_pending_groups_state` when present, and
otherwise constructs `GroupRuntime(self.cognition, self._seed, dialogue=self.dialogue)`.

### Snapshot merge (`_merge_*`)
The snapshot merge helpers stamp per-citizen mobility rows with each runtime's
context: `_merge_dialogue:364`, `_merge_cognition:375`, `_merge_work:380`,
`_merge_health:457`. Each iterates `snap.get("citizens", [])` and adds a keyed
sub-dict via `runtime.row(cid)`:

```python
def _merge_cognition(self, snap):
    c = self.cognition
    for row in snap.get("citizens", []):
        row["cognition"] = c.row(int(row["citizen_id"]))
```

`mobility_snapshot(include_routes=True)` (`:443`) builds the mobility snapshot then
applies each merge in order: health, work, cognition, dialogue (`:446–455`). **A
`_merge_groups` would stamp `row["group"] = self.groups.row(cid)`** (membership +
role) and be called at `:455` after `_merge_dialogue`. The whole-world
`snapshot()` (`:826`) also embeds `mobility` and `outbreak` (`:888–892`); a top-level
`out["groups"] = self.groups.snapshot()` block would go at `~:892`.

### The substep interleave — `advance_seconds` / `_advance_runtimes`
`advance_seconds(seconds, focus_xy, auto_tick)` (`:386`) runs the continuous clock:
it sets focus (`:398`), then loops in chunks bounded by the epidemic-tick length,
calling `_advance_runtimes(chunk)` (`:405`), advancing `_subtick_s`, and running
the coarse epidemic `step()` when the sub-tick clock crosses a tick (`:410`).

`_advance_runtimes(chunk)` (`:417`) is the load-bearing ordering — **every runtime
integrates in lock-step 1 s substeps** so an event in one second is visible to the
others the same second (`:427–441`):

```python
hour = self.current_hour()
remaining = float(chunk)
while remaining > 1e-9:
    step = min(1.0, remaining)
    self.mobility.advance(step, hour)      # 1. movement executes
    if self.outbreak: self.outbreak.advance(step)   # 2. health/threats
    if self.work:     self.work.advance(step)       # 3. tasks
    if self.cognition:self.cognition.advance(step)  # 4. perceive/decide/share
    if self.dialogue: self.dialogue.advance(step)   # 5. conversations step
    hour += step / 3600.0
    remaining -= step
```

**Where the group advance step hooks in:** immediately after `self.dialogue.advance(step)`
(`:439`), add `if self.groups is not None: self.groups.advance(step)`. Rationale:
groups react to what cognition perceived and what dialogue said *this* second
(new members learned facts, a member fled), and push objectives that mobility /
work / dialogue execute on the *next* second — the same one-substep latency every
other cross-runtime effect already has. Do **not** run groups before dialogue: it
would act on stale perception.

Note the group layer's own decision cadence should be coarse (a `_next_decision_s`
gate like cognition's `DECISION_INTERVAL_S`, `cognition/runtime.py:203`), not every
second — the 1 s `advance` is just the clock.

### Clock, hour, focus/LOD
- `current_hour()` (`:209`): `npc.hour_of_day(tick, dt, start_hour)` plus
  `_subtick_s/3600`. `game_seconds` (`:222`) is continuous seconds since start.
- `focus_xy` is a mobility concern: `advance_seconds` forwards it via
  `self.mobility.set_focus_xy(focus_xy)` (`:398`), which drives the LOD bands.
  Groups are LOD-independent (they operate on citizen ids and relationship edges,
  not bodies), so they need no focus input — but their *effects* (pushed goals) are
  executed by whichever band the target citizen is in.

---

## 2. Cognition runtime — `asphodel/cognition/runtime.py`

This is the epistemics authority. **The group layer reads from it and pushes facts
through it; it must never write a member's memory or relationship directly except
via these methods.**

### Ownership / construction
`CognitionRuntime.__init__` (`:83`) owns:
- `self.memories: Dict[int, MemoryStore]` (`:88`) — per-citizen memory.
- `self.rels: RelationshipGraph` (`:89`) — per-ordered-pair relationships.
- `self.events/event_seq/counts` (`:90–92`) — the event tape.
- social bookkeeping: `told`, `pair_last_s`, `calls`, `help_cooldown`,
  `help_pairs`, `help_log`, `avoid_goals`, `safe_since`, `pending_help`,
  `room_avoid_reported` (`:100–110`) — all persisted.
- caches (never persisted): `_beliefs`, `_avoid_cache`, `_pers`, `_occ_cache`
  (`:112–115`).
- `self.dialogue = None` (`:117`) — set when dialogue is enabled; `self.work` /
  `mobility.cognition = self` back-references (`:118,:120`).

### The public methods a group layer may call

| Method | Signature / line | What it gives the group layer |
|---|---|---|
| `store(cid)` | `:126` → `MemoryStore` | a citizen's memory store (read salient facts) |
| `personality(cid)` | `:133` → `Personality` | 5 traits; pure fn of (seed, cid) |
| `beliefs(cid)` | `:650` → `Dict[str, Belief]` | derived danger/safety beliefs, cached per game-minute |
| `relate(owner, other, rule, scale, **ctx)` | `:276` | apply a *named* relationship rule (only path to change a relationship) |
| `rels` (`RelationshipGraph`) | `:89` | read edges: `rels.of(cid)`, `rels.get(a,b)` |
| `help_score(helper, beneficiary, problem, rel_override=None)` | `:724` → `(score, comps)` | the weighted helpfulness/affinity/obligation model |
| `_closeness(a, b)` | `:741` → `float` | `familiarity + affinity + obligation` (candidate-ranking) |
| `avoid_rooms(cid, bid)` | `:675` → `Set[int]` | rooms the citizen refuses (feeds WorkRuntime) |
| `_can_perceive(cid)` | `:247` → `bool` | not incapacitated/corpse/undead |
| `_room_mates(cid, bid, rid)` | `:228` → `List[int]` | who can currently see `cid` (same room / outdoor radius) |
| `_ctx(cid)` | `:209` → `dict` | building_id/room_id/zone/object/task/role |
| `_occupants(bid)` | `:217` → `{room_id: [cid]}` | occupants by room (cached per substep) |
| `citizen_context(cid, n_memories=8)` | `:984` → `dict` | the full §19 context bundle (location, needs, health, personality, memories, people_nearby, relationships, beliefs, perceived_danger, avoiding) |
| `receive_fact(recipient, sender, f, channel, bid, rid)` | `:571` | **THE transmission path** into a member's store |
| `_share(sender, recipient, channel, bid, rid, only)` | `:534` → `bool` | roll-gated share (respects cooldowns/dedupe/sociability) |
| `remember(cid, kind, source, **kw)` | `:252` → `MemoryFact` | direct memory write (perception only — not for injecting hearsay) |
| `event(kind, **info)` | `:140` | append to the cognition tape |

### `_share` and `receive_fact` — the provenance path (critical)
`_share(sender, recipient, channel, …)` (`:534`) enforces: both must perceive
(`:535`), a `PAIR_COOLDOWN_S` (`:544`), skips facts the recipient already knows
first-hand (`:551`), and a `share_roll` gate on non-`call` channels
(`:557`). When `self.dialogue is not None` it routes through
`self.dialogue.warn(...)` (`:566`); otherwise it calls `receive_fact` directly (`:568`).

`receive_fact(recipient, sender, f, channel, bid, rid)` (`:571`) is where a told
copy is created with **full provenance**: `source=M.TOLD`, `source_citizen=sender`,
`origin_witness=f.origin_witness`, `origin_id=f.origin_id`, `hops=f.hops+1`,
and a `told_confidence` scaled by the recipient's trust in the sender and its
suspicion (`:588`). It also records `WARNED_BY` (`:594`), applies the `warned_by`
and (for threats) `told_threat` relationship rules (`:614–617`), and triggers an
immediate `_decide_avoid_one` for threats (`:619`). Returns `(told_fact, created,
confidence)`.

**Implication for the group's shared record:** a group must NOT hold facts nobody
communicated. The correct pattern is: the shared record stores only origin ids
that a member *deliberately shared*; propagation to other members happens by
calling `_share`/`receive_fact` for each member so every member acquires the fact
with its own trust-scaled confidence and hop count. No omniscient broadcast.

### How a citizen acquires a new goal (the goal-push mechanism)
Cognition never moves a citizen. It pushes a `Goal` onto the individual
`CitizenRuntime`. The canonical example is `_decide_avoid_one` (`:854`):

```python
goal = Goal(GoalKind.DO_ACTIVITY, target=rt.home_node, source="belief",
            priority=SOURCE_BASE_PRIORITY["belief"] + 0.12 * min(1.0, danger),
            activity="rest", reason=f"avoiding building {dest_bid}: …")
preempt = rt.push_goal(goal, self.mobility.graph)     # runtime/runtime.py:100
self.avoid_goals[cid] = {"building_id": …, "goal_id": goal.id, "since_s": self.now_s, …}
```

`rt = self.mobility.citizens.get(cid)` (`:855`) is the `CitizenRuntime`;
`rt.push_goal(goal, graph)` adds a competing goal and reselects (`preempt` = did it
take over). Goal removal is symmetric (`:892`): `rt.goals.remove(g.id)` then
`rt._reselect(graph)`. Cognition tracks its own pushed goals in `avoid_goals` so it
can retract them when the belief fades/expires (`:876–898`). **The group layer uses
exactly this mechanism** to send members to a shelter (see §5 and integration plan).

### Priors — the existing "social grouping" seed
`init_priors(profiles)` (`:154`) is the only non-experience relationship source. It
buckets citizens by `home_building_id` and `work_building_id` and calls
`rels.prior(a, b, origin, now_s)` for every ordered pair in a bucket, tagging the
relationship `origin` as `"household"` or `"workplace"` (`:169–174`). These origin
tags are the closest thing to a pre-existing group and are prime **formation seeds**
(see §11).

### Decisions / cadence
`advance(dt_s)` (`:181`) loops 1 s substeps calling `_substep` (`:189`), which every
second: clears the occupant cache, `_perceive_work`, `_perceive_outbreak`,
`_alarmed_encounters`, and — gated by interval timers — `_copresence` (`:461`,
every `COPRESENCE_INTERVAL_S`), `_decide` (`:692`, every `DECISION_INTERVAL_S`),
`_consolidate` (`:972`). `_decide` runs `_decide_help` (`:761`), `_decide_avoid`
(`:846`), `_observe_safety` (`:920`). Note `_decide_avoid` only scans citizens
holding a threat fact (`:848` — "an index, not a scan"), the anti-O(N²) idiom the
group layer must copy.

### Snapshot / event tape / persistence
- `snapshot(since_seq)` (`:1050`): `{version, now_s, counts, events (delta), event_seq, avoiding, …}`.
- `row(cid)` (`:1040`): compact per-citizen (`n_memories`, `n_relationships`,
  `top_belief`, `avoiding`, `helping`) — the merge payload.
- `to_state()` (`:1060`) / `from_state(st, mobility, work, outbreak_fn)` (`:1082`):
  full JSON-safe save; memories via `MemoryStore.to_state`, relationships via
  `RelationshipGraph.to_state`; caches rebuilt lazily.

### Relationship & personality internals (`relationships.py`, `personality.py`)
`Relationship` (`relationships.py:22`) dimensions: `familiarity, trust(=0.3 base),
affinity, fear, hostility, obligation` plus `interactions, last_t, origin`
(`:24–33`). `RULES` (`:56`) maps a named event → bounded saturating deltas
(`helped_by`, `warned_by`, `fled_with`, `attacked_by`, `false_warning`, …). `PRIORS`
(`:77`): household `{fam .80, trust .70, aff .60}`, workplace `{fam .30, trust .40,
aff .15}`. `RelationshipGraph`: `get/of/prior/apply/to_state/from_state`
(`:95–137`). `_closeness` (runtime `:741`) = `fam+aff+obl`; `help_score` (`:724`)
weights `0.50*helpfulness + 0.25*fam + 0.35*aff + 0.60*(0.7+0.6*loyalty)*obl +
0.15*trust − 0.5*(fear+hostility) − cost`.

`Personality` (`personality.py:16`) — five traits in [0,1]: `sociability,
helpfulness, risk_tolerance, loyalty, suspicion` (`TRAITS`, `:12`). Pure function of
`(world_seed, cid)` via `hash64` (`:27–35`); never stored, cannot drift. Group
formation/leadership can read these but must not persist them.

---

## 3. Dialogue runtime — `asphodel/dialogue/runtime.py`, `acts.py`, `session.py`, `grounding.py`

### Ownership / construction
`DialogueRuntime.__init__(cognition, names=None)` (`:58`) owns `conversations`,
`requests`, `events/event_seq/counts`, `seq`, `ask_last`, `request_last`,
`player_sessions`, `rendered` (a UI ring), and sets `cognition.dialogue = self`
(`:74`). It reads `mobility` and `work` from cognition (`:60–61`).

### Channels (`session.py:16–21`)
`FACE_TO_FACE`, `SHOUT`, `CALL`, `PLAYER`, `PROBE` (`CHANNELS`, `:21`). `PROBE` is a
**read-only inspection** — a question whose grounded answer is rendered with its true
epistemic frame but is NOT written into the asker's store (`runtime.py:427`,
`_answer`). This is the harness/player "what would you say" channel and is the safe
way for a group query UI to inspect a member without perturbing state.

### Availability / co-presence gates
- `available(cid, channel)` (`:96`) → `(bool, reason)`: not registered / override
  (incapacitated/corpse/undead) / fleeing (face-to-face) / asleep.
- `co_present(a, b)` (`:118`) → same room indoors or within `TALK_RADIUS_M`
  outdoors.
- `can_call(a, b)` (`:131`): a `household`/`workplace` origin tie OR
  `familiarity >= 0.55`. **This is exactly the tie test a group would use to
  "call all members".**

### Speech acts (`acts.py`)
Act constants (`acts.py:16–33`): `GREET, INFORM, WARN, ASK_FACT, ANSWER,
ASK_LOCATION, ASK_PERSON, ASK_SAFETY, ASK_FOR_HELP, OFFER_HELP, ACCEPT, REFUSE,
THANK, ACKNOWLEDGE, CLARIFY, EXPRESS_UNCERTAINTY, REPORT_PROBLEM, END_CONVERSATION`.
`ACTS` tuple (`:34`), `QUESTIONS` (`:37`). Proposition kinds (`:40–52`), epistemic
frames (`:55–61`), `Proposition` dataclass (`:65`), `Request` dataclass (`:112`)
with states `REQ_PENDING/ACCEPTED/REFUSED/COMPLETED/FAILED/CANCELLED` (`:93–98`) and
refusal reasons (`:101–108`).

**Adding a new speech act / group flow:** add the constant to `acts.py`, extend
`ACTS` (and `QUESTIONS` if it expects an answer), add a render template in
`render.py`, and emit it from a new method that reuses `_start`/`say`/`_end`. A
group-conversation flow (e.g. a leader rallying members to a shelter) is a
*planned* conversation: `warn` (`:260`) already builds a `conv.plan` list of
`{speaker, act}` steps stepped one-per-second by `_step_plan` (`:309`). A
`rally(leader, members, target)` method would, per co-present member, `_start` a
conversation with a plan `[GREET, INFORM(place_is_safe/objective), ANSWER(location),
ACKNOWLEDGE]`, and for non-co-present members with a call tie, use the `CALL`
channel path. Reuse, don't reinvent.

### Core methods to reuse
- `_start(a, b, channel, topic)` (`:136`) — open a conversation, stamps building/room.
- `say(conv, speaker, act, prop, …)` (`:178`) — emit one act; **grounds any
  proposition against the SPEAKER's own store** (`:187`, `G.ground`) and rejects/
  downgrades unsupported ones. This is what keeps dialogue honest — a group can't
  make a member "say" something the member doesn't know.
- `transmit(conv, speaker, listener, fact, act)` (`:229`) — **the one path a fact
  travels from speaker to listener**: `say` then `cog.receive_fact` (`:243`). Emits
  `FACT_SHARED`/`FACT_RECEIVED` with lineage.
- `warn(sender, recipient, fact, channel, bid, rid)` (`:260`) — cognition's chosen
  telling; SHOUT/passing = one act, FACE_TO_FACE/CALL = a short planned exchange.
- `ask(asker, answerer, act, subject/building_id/room_id/event_ref, channel, thank)`
  (`:356`) — one question + grounded answer. A group's "does anyone know X?" poll is
  a set of `ask(..., channel=PROBE)` calls.
- `request_help(requester, helper, problem, channel)` (`:453`) — **how a request
  becomes a WorkRuntime task**: evaluates via `evaluate_request` (`:432`, which calls
  `cog.help_score` + checks `work.help_target`), and on accept calls
  `w.assist(helper, task_id, oid, requester)` (`:480`) — a real Smart Object task —
  then records `HELP_DECIDED` and `pending_help` in cognition. Refusal writes a
  `REFUSED_BY` memory and `refused_by` relationship (`:524–527`). Cooldown
  `REQUEST_COOLDOWN_S` per (requester, helper) (`:463`).
- `player_talk(player, npc, act, args)` (`:551`) — the bridge `TALK` entry; player is
  a registered citizen, acts are structured, answers grounded in the NPC store.

### Advance / persistence
`advance(dt_s)` (`:673`) → 1 s substeps → `_substep` (`:681`) steps planned
conversations (`_step_plan`), handles player-session timeouts/separation, and times
out accepted-but-unstarted requests (writing `abandoned_by`). `snapshot(since_seq)`
(`:728`) = active conversations + pending/accepted requests + event delta +
`recent_lines`. `to_state()` (`:737`) / `from_state(st, cognition, names)` (`:748`).

---

## 4. Work runtime — `asphodel/smart/runtime.py`

### Ownership
`WorkRuntime.__init__(mobility, world_seed, descriptor_fn)` (`:104`) owns:
`self.registries` (per-building `SmartObjectRegistry`, lazily built by `registry(bid)`
`:129`), `self.graphs` (per-building `RoomGraph`, via `graph(bid)` `:143`),
`self.ledger` = `ReservationLedger` (`:111`), `self.activities: {cid: ActivityState}`
(`:112`), `self.employment`, `self.queues`, `self.reduced`, `_pending_deltas`
(`:120`), and `self.room_filter` (`:125`) — set by cognition to `avoid_rooms`
(`cognition/runtime.py:120`), the hook by which beliefs constrain work.

### Key methods
- `employ_all(profiles)` (`:157`) — deterministic employment from seed/citizen/workplace.
- `problems(bid)` (`:875`) → `List[dict]` — **observable** work problems in one
  building: `unstaffed_queue`, `queue_overload`, `station_failed`,
  `cleaning_workload`, `restock_workload`; each row names the `citizen_id` it is a
  problem for. This is the "what a co-present citizen can see" surface a group could
  scan to assign collective tasks.
- `help_target(helper, problem)` (`:919`) → `(task_id, object_id) | None` — the task
  a helper would run; respects `_avoided` rooms (`:452`).
- `assist(helper, task_id, object_id, beneficiary)` (`:958`) → `bool` — runs one help
  task: releases the helper's holds, reserves the object, walks it there via the
  normal task path, sets `a.help_for = beneficiary` (`:988`). **This is the only way
  to make one citizen do work for another**; a group "supply run" or "cover the
  register" objective must ultimately call `assist` (directly or via
  `dialogue.request_help`).
- `set_object_state(object_id, key, value)` (`:1057`) → `SmartObject` — authoritative
  external state change (a register breaks, a door closes); releases holders and can
  flag the building `reduced_function`. Object ids are `so:<building>:<k>`;
  `key`/`value` are free-form in `o.state` (`:1064`).
- `workplace_status(bid)` (`:1031`) — open/reduced_function/closed + stations/staffed/
  queued.
- `context(cid)` (`:1084`) — building/room/zone/object/task/role of a citizen.
- `occupants_by_room(bid)` (`:1100`) → `{room_id: [cid]}` — used by cognition's
  `_occupants`.
- `row(cid)` (`:1110`) — the merge payload (role, workplace, task, phase, object,
  room, help_for).

### Object state & "supply/quantity-like" fields
`SmartObject` state is a free dict. Object archetypes are defined in
`smart/objects.py:40` (`_ARCH`): `checkout`, `shelf`/`gondola` (caps `shelf,stock,
browse`; state carries `stock`), `supply_closet`/`med_cart` (caps `storage,
supplies`), `crate`/`pallet_rack`/`freezer_case` (caps `storage, goods`), etc.
`problems` reads `int(o.state.get("stock", 100)) < RESTOCK_BELOW` (`:912`) — **so a
supply level already exists as an object-state field.** A group "supply run"
objective can be phrased against `storage`/`supplies`/`goods` objects and their
stock, using `assist(..., "help_restock", oid, ...)` or a new group task that moves
`goods` between buildings.

### "Guard at entrance" / "supply run" today
There is no dedicated combat/guard task in `HELP_TASKS`. The closest primitives:
- A **guard at an entrance** = a citizen whose active goal targets the building's
  entrance node and holds position. `RoomGraph.entrance_xy`/`entrance_room`
  (`rooms.py:65,66`) and the building's entrance node (`mobility.node_for_building`)
  give the anchor. Expressed as a `Goal(GoalKind.DO_ACTIVITY, target=<entrance
  node>, activity="idle"/"guard", source="social"|"belief")` pushed onto the
  guard's `CitizenRuntime` — a mobility/goal concern, not a Smart Object task (no
  object to reserve). The group layer would own the assignment and the goal push;
  no new WorkRuntime task is strictly required for V1.
- A **supply run** = a trip goal to a `storage`/`supplies` building plus (optionally)
  a `help_restock`-style task at destination. Again a goal push + optional `assist`.

### Rooms/entrance/anchor semantics
`RoomGraph` (`rooms.py:51`): `rooms`, `zones` (`zone_of_room_kind`, `:43`), `adj`,
`entrance_xy`/`entrance_room`/`inside_xy` (`:65–68`), `room_of(xy)` (`:74`),
`zone(room_id)` (`:85`), `rooms_of_zone(zone)` (`:88`), `rows()` (`:119`). Object
capacities live in the archetype table (`objects.py:40`).

### Persistence
`snapshot(since_seq)` (`:1127`), `to_state()` (`:1138`) / `from_state(st, mobility,
descriptor_fn)` (`:1152`). Note `to_state` stores only object *deltas*
(`r.state_deltas()`) and `known_buildings`; `from_state` rebuilds registries and
replays deltas via `_pending_deltas` (`:1163`).

---

## 5. Mobility / embodied — `asphodel/mobility/`, `asphodel/embodied/`

### The physical authority
`MobilityRuntime` (`embodied/runtime.py:83`) owns `self.graph` (street graph),
`self.citizens: {cid: CitizenRuntime}` (`:99`), `self.execs: {cid: TripExecutor}`
(`:100`), `self.bands: {cid: LODBand}` (`:104`), `self.frozen_at` (`:105`),
`self.now_s`, `self.lod` (`LODController`, `:93`), `self.max_active=1024` (`:95`).

### Sending a citizen to a building/room (goal/trip)
1. Find the target's graph node: `node = mobility.node_for_building(bid)`
   (`runtime.py:117`).
2. Build a `Goal` (`citizens/goals.py:40`) with `target=node`, an appropriate
   `GoalKind` (`ARRIVE_AT`/`DO_ACTIVITY`/`FLEE`, enum `:19`) and `source`
   (`SOURCE_BASE_PRIORITY`, `:28`: idle .10, need .35, social .45, schedule .55,
   belief .66, emergency .92, player 1.0).
3. `rt = mobility.citizens[cid]; rt.push_goal(goal, mobility.graph)`
   (`citizens/runtime.py:100`). Highest-priority goal wins; `GoalStack`
   (`goals.py:63`) handles preemption with `preempt_margin`.

A goal "targets a building" through `node_meta`: `rt.node_meta[node] =
{"building_id": …, "xy": …}` is filled at `register` (`embodied/runtime.py:201–205`),
and cognition reads it back via `_building_of_goal` (`cognition/runtime.py:840`):
`rt.node_meta.get(g.target)["building_id"]`. **For a shelter that is not a citizen's
home/work/errand node, the group layer must ensure a node_meta entry exists** — the
cleanest is a mobility helper that resolves an arbitrary building id to a node and
registers the meta (see integration plan §e).

`CitizenRuntime` (`citizens/runtime.py:36`): `home_node`, `work_node`, `schedule`,
`goals` (`GoalStack`), `active_goal`, `node_meta`, `needs`; `push_goal`/`push_emergency`
(`:100,:108`), `_reselect` (`:117`), `sync_schedule` (`:88`, replaces the schedule
goal each tick — a pushed non-`schedule` goal survives it as long as priority wins).

### execs / LOD
`TripExecutor` (`embodied/executor.py`) `ex` fields used across runtimes: `ex.pos`,
`ex.inside`, `ex.building_id`, `ex.override` (`""|incapacitated|corpse|undead`),
`ex.state` (`EmbodimentState`), `ex.activity`, `ex.has_body`. LOD bands
(`lod/entity.py`, `LODBand`): `ABSTRACT` (frozen, overflow > `max_active`),
`ROUTE_SIMULATED` (default: itinerary executed, no body), `NEAR_SIMPLIFIED`
(collapsed to ROUTE in V1, `:371`), `PHYSICAL` (within focus radius, has a body).
`snapshot(include_routes)` (`embodied/runtime.py`, body shown earlier) →
`{version, t_s, focus_xy, near, citizens: [row per cid], vehicles, routes}`. Groups
operate on `execs`/`citizens` keys (ids), so they work identically across all bands
— a member frozen at ABSTRACT still holds its group membership and pushed goals; the
goal executes when the band promotes.

---

## 6. Outbreak — `asphodel/outbreak/`

`OutbreakRuntime(mobility, seed, pathogen)` (`runtime.py:68`) owns
`self.records: {cid: HealthRecord}` (`:73`), `attack_cooldown`, `_known_threats`
(`:85,:86`). Key methods:
- `seed_index_case(cid, context)` (`:129`) / `choose_index_case()` (`:141`).
- `advance(dt_s)` (`:153`) — contact infection, undead hunt/attack, threat
  perception.
- `_attack(ucid, vcid)` (`:486`) → the victim always flees (`_flee`, `:500`).
- `_flee(cid, threat_id, reason)` (`:261`) — the emergency goal-push exemplar:
  builds `Goal(GoalKind.FLEE, target=<refuge/home node>, source="emergency",
  priority=FLEE_PRIORITY=0.92)` and `rt.push_goal(g, graph)` (`:293–294`); "threat is
  at my home" reroutes to a deterministic nearby refuge (`:266–286`).
- Threats are **perceived** through cognition, not read omnisciently:
  `cognition._perceive_outbreak(ob)` (`cognition/runtime.py:371`) turns undead/attack
  proximity into first-hand threat memory via `_threat_memory` (`:442`) and
  `_share_burst` (`:622`). `records` is exposed for `_merge_health`
  (`orchestrator.py:457`) and safety checks.

**Group relevance:** a threat is the primary rally trigger, but the group must learn
of it the same way individuals do — through a member's first-hand threat memory or a
warning it received — never by reading `ob.records`. The group reads
`cognition.beliefs(member)` / member threat facts, not the outbreak runtime.

---

## 7. Save / load — `asphodel/save.py`

`SAVE_VERSION = 3`, `_READABLE_VERSIONS = (1, 2, 3)` (`:42,:43`). Note the version
comment (`:36–41`) documents v1–v3; the outbreak/work/cognition/dialogue blocks were
added to `world_state`/`load_world` **without** a version bump (they serialise as
`null` when absent and restore cleanly, so old saves stay readable) — a groups block
should follow the same additive, null-tolerant convention, and ideally the version
comment should be extended (bumping `SAVE_VERSION` is optional but cleaner).

### Each runtime's block
`world_state(world, bundle, player_citizen)` (`:257`) writes one key per runtime,
each `None` when the runtime is off (`:293–304`):
```python
"mobility":  None if world.mobility  is None else world.mobility.to_state(),
"outbreak":  None if world.outbreak  is None else world.outbreak.to_state(),
"work":      None if world.work      is None else world.work.to_state(),
"cognition": None if world.cognition is None else world.cognition.to_state(),
"dialogue":  None if world.dialogue  is None else world.dialogue.to_state(),
"survival":  …,
```

### The `_pending_*_state` pattern
`load_world(state)` (`:308`) constructs the bare `World`, restores sim/roster/
citizens, and stashes each runtime block into a `_pending_*_state` field WITHOUT
building the runtime (`:332–336`):
```python
world._pending_mobility_state  = state.get("mobility")
world._pending_outbreak_state  = state.get("outbreak")
world._pending_work_state      = state.get("work")
world._pending_cognition_state = state.get("cognition")
world._pending_dialogue_state  = state.get("dialogue")
```
The runtimes are actually rebuilt later, in dependency order, when the *session*
calls `enable_*` (which detects the pending state and calls `from_state` instead of
constructing fresh) — see `bridge/session.py:_cmd_load` (`:583`), which re-attaches
the spatial context then calls `_enable_mobility` → `enable_outbreak` →
`enable_work` → `enable_cognition` → `enable_dialogue`, each guarded by
`if world._pending_*_state is not None` (`:607–621`). Fresh `START_WORLD` enables in
the same order (`session.py:139–186`).

### Where a `groups` block hooks in
1. `world_state`: add `"groups": None if world.groups is None else world.groups.to_state()`
   at `:301` (after `dialogue`).
2. `load_world`: add `world._pending_groups_state = state.get("groups")` at `:336`.
3. `_cmd_load` (`session.py:621`): after dialogue, add
   `if world._pending_groups_state is not None: world.enable_groups()`.
4. `_cmd_start_world` (`session.py:186`): after `enable_dialogue`, add the groups
   enable gated on a `groups: true` option.
5. Optionally extend `SAVE_VERSION`/comment (`save.py:36–43`).

Ordering rule: groups restore **after** cognition (and dialogue), because
`from_state` needs the restored `cognition`/`dialogue` runtimes to re-link.

---

## 8. Bridge — `asphodel/bridge/protocol.py`, `session.py`

`PROTOCOL_VERSION = 8` (`protocol.py:43`); version history in `:30–42`. Exact-match
policy: `is_compatible(client_version)` requires equality (`:165`). Bumping to **9**
is the mechanism for adding group commands.

### Adding a command
1. Add the constant to `class Command` (`protocol.py:46`) and to `Command.ALL`
   (`:94`).
2. Add a handler `_cmd_<lower>(self, msg, rid)` on `WorldSession`
   (`session.py:35`); dispatch is automatic via `getattr(self, f"_cmd_{cmd.lower()}")`
   (`:60`).
3. Bump `PROTOCOL_VERSION` and extend the version comment.

### How `START_WORLD` enables runtimes
`_cmd_start_world` (`session.py:89`) builds the world, sets citizens/spatial context,
`_enable_mobility` (`:139`), then optional `outbreak` (`:167`), `work` (default on,
`:178`), `cognition` (default on, `:182`) and, nested under cognition, `dialogue`
(`:185`). **Group enable** slots in after `enable_dialogue` (`:186`), gated on a new
`groups` option (default your choice; suggest opt-in for V1).

### Snapshot commands
Each runtime has a `GET_*` command that returns its snapshot delta:
`GET_MOBILITY` (`:393`), `GET_OUTBREAK` (`:295`), `GET_WORK`/`GET_ROOMS` (`:303,:310`),
`GET_COGNITION`/`GET_CITIZEN_CONTEXT` (`:350,:357`), `GET_DIALOGUE` (`:387`), and the
interactive `SET_OBJECT_STATE` (`:334`) and `TALK` (`:368`). All take a `since` seq
and call `world.<runtime>_snapshot(since_seq=since)`.

### Where GROUP commands hook in
Add to `protocol.py`:
- `GET_GROUPS` — `world.groups.snapshot(since_seq)` (roster of groups, membership,
  objectives, shared-record summaries, event delta). Mirrors `GET_DIALOGUE`.
- `GET_GROUP` — one group's detail (members, roles, shared record, active objective).
- `JOIN_GROUP` / `REQUEST_JOIN` — the player (a registered citizen) asks a group to
  join; routes through the group's admission logic which reads
  `cognition.help_score`/`_closeness`/relationships (never omniscient acceptance).
Add matching `world.groups_snapshot()` / `world.group_query(gid)` /
`world.request_join(player, gid)` facades on `World` (mirroring `talk`
`orchestrator.py:361` and `citizen_context` `:372`), and `_cmd_*` handlers in
`session.py`. The player ask-to-join must go through the same admission decision NPCs
use.

---

## 9. Buildings / rooms / geography

- **How a citizen knows a building:** through `CitizenRuntime.node_meta[node] =
  {"building_id", "xy"}`, filled at `MobilityRuntime.register` for the home, work and
  one errand building (`embodied/runtime.py:201–205`). A citizen only "knows" the
  buildings it visits — there is no global building directory in a `CitizenRuntime`.
  `mobility.node_for_building(bid)` (`:117`) resolves an arbitrary building id to its
  graph node (entrance anchor) regardless of who visits it.
- **A building's rooms / capacity / entrances:** via the work runtime —
  `work.registry(bid)` (`SmartObjectRegistry`) and `work.graph(bid)` (`RoomGraph`,
  `smart/rooms.py:51`): `g.rooms`, `g.zones`, `g.entrance_xy`, `g.entrance_room`,
  `g.rows()`, `g.rooms_of_zone(zone)`. Object capacities from the archetype table
  (`smart/objects.py:40`). The bridge surfaces this via `GET_ROOMS`
  (`session.py:310`).
- **`resolve_bundle_dir(bundle)`** (`bridge/worldfactory.py:35`) resolves a bundle
  name to its on-disk directory; used to load population, spatial context, entrances.
- **Spatial context:** `CitySpatialContext.from_bundle_dir(bundle_dir)`
  (`asphodel/embodiment.py`) carries the street graph and building geometry; attached
  via `world.set_spatial_context` and consumed by `enable_mobility`
  (`orchestrator.py:236`).
- **What a "shelter" building/room reference looks like:** there is no first-class
  "shelter" today. A shelter is just a `building_id` (plus optionally a `room_id`).
  It is referenced the same way a home is: a graph node via
  `mobility.node_for_building(shelter_bid)`, with `node_meta` ensured on each member's
  `CitizenRuntime`, and its rooms/entrance read through `work.graph(shelter_bid)`.
  Signatures already speak of "a familiar, stocked house" and "gather the household
  and run" (`asphodel/signatures.py:77,195`) as narrative shelter concepts — the group
  layer would give them a mechanical home.

---

## 10. Existing gates & tests

### Godot in-engine gates (`godot/tests/`)
`*Gate*` scenes + drivers: `EmbodiedMobilityGate` (`embodied_mobility_gate.gd`),
`WorkGate` (`work_gate.gd`), `OutbreakGate` (`outbreak_gate.gd`), `CognitionGate`
(`cognition_gate.gd`), `DialogueGate` (`dialogue_gate.gd`), `ConvergenceGate`,
`PhysicsGate`, `NavGate`, `RegionGate`; runner `godot/tests/run_gates.sh`.

### Shell gate launchers (`tools/run_*_gate.sh`)
`run_mobility_gate.sh`, `run_outbreak_gate.sh`, `run_work_gate.sh`,
`run_cognition_gate.sh`, `run_dialogue_gate.sh` — each boots the live Python bridge
(`python3 -m asphodel.bridge.server`), waits for the port, runs the matching Godot
`*Gate.tscn` under `xvfb`, writes a trace JSON, returns the gate verdict. A
`run_groups_gate.sh` would clone `run_dialogue_gate.sh` verbatim (bundle `houston`,
player `82`, a `GroupsGate.tscn`). Certification aggregators: `tools/final_cert.sh`,
`run_live_cert.sh`, `run_saveload_cert.sh`, `convergence_cert.sh`.

### Certification-day test pattern (reuse these idioms)
`tests/test_npc_dialogue_v1_day.py` and `tests/test_npc_cognition_v1_day.py` are the
templates. Key idioms:
- **World builder** `_mk(d, start_hour)` (`dialogue day:90`): `world_from_bundle` →
  `set_citizens(load_bundle_population(d))` → `set_spatial_context` →
  `enable_mobility` → `enable_work` → `enable_cognition` → `enable_dialogue` →
  `enable_outbreak(..., seed_index_case=False)`. A groups day-test adds
  `enable_groups()` last.
- **Restore harness** `_restore(js, d)` (`:104`): `load_world(json.loads(js))` →
  reattach spatial context → re-enable each runtime guarded by `_pending_*_state`.
  Add the groups guard.
- **`Tape`** (`:139`) drains each runtime's `snapshot(since_seq)` event delta into a
  growing list, tracking the last `event_seq` per runtime. Add a `groups` lane.
- **`_saveload(w, d, key, hour)`** (`:281`): serialize (`_blob` = `world_state` JSON,
  `:118`), restore, assert `*_identical` state equality, then advance both 10 min and
  assert `continuation_bit_identical` (`_blob(w)==_blob(w2)`), and `no_reroll_on_load`
  (event_seq unchanged by load). The bit-identical continuation is THE save/load gate;
  the group runtime's `to_state`/`from_state` must satisfy it.
- **`_lod_probe`** (`:301`): save, restore, advance one under focus (PHYSICAL) and one
  FAR (ROUTE), assert state matches while physical and after demotion — LOD must not
  change authoritative state. Groups must pass this trivially (they're band-agnostic).
- **PROBE inspection** `_probe(dl, asker, answerer, act)` (`:169`) uses
  `channel=PROBE` to read a citizen without writing its store — the pattern for a
  read-only group query.
- Picks are **data-driven** (`_busiest_shop`, `:135`; first customer; first helper),
  never hard-coded names — a group test should pick, e.g., the densest household or
  the pair with the highest `_closeness`.

---

## 11. Formation seeds, traits, closeness, and the "is there already a group?" finding

### Existing relationship "origin" tags (formation seeds)
`Relationship.origin` (`relationships.py:33`) is `"household"`, `"workplace"`, or
`""` (experience-only). Set exclusively by `RelationshipGraph.prior`
(`relationships.py:106`), driven by `CognitionRuntime.init_priors`
(`cognition/runtime.py:154`) bucketing on `home_building_id` / `work_building_id`.
These tags carry real social meaning and gate behaviour already: `can_call`
(`dialogue/runtime.py:133`) trusts a household/workplace tie, and `_share_burst`
(`cognition/runtime.py:639`) calls strong ties including those origins. **They are the
natural seed for group formation** — a household is a latent group; a workplace is a
latent group.

### Personality traits available
`sociability, helpfulness, risk_tolerance, loyalty, suspicion` — all [0,1], pure fn
of `(seed, cid)` (`personality.py:12,34`). Relevant to groups: `loyalty` (already
amplifies obligation in `help_score`, `cognition/runtime.py:734`) is the obvious
membership-stability / leadership trait; `sociability` gates sharing; `suspicion`
scales down told-confidence and would gate admission.

### How `_closeness` and the relationship dimensions are computed
- `_closeness(a, b)` (`cognition/runtime.py:741`) = `familiarity + affinity +
  obligation` of the directed relationship `a→b` (0 if none). Used to rank who a
  coworker asks for help (`:800`).
- `trust` base 0.3, moves via `warned_by`(+.12) / `warning_confirmed`(+.20) /
  `false_warning`(−.35) / `helped_by`(+.25) / threat rules (−.80..−.90)
  (`relationships.py:56`). `affinity`/`obligation`/`familiarity`/`fear`/`hostility`
  move via the same `RULES` table; deltas saturate (`_sat`, `:83`).
- `help_score` weights (`runtime.py:733`): the full obligation/affinity/trust model.

### Is there already a group / faction / household concept? — **NO.**
A wide grep (`faction`, `community`, `clan`, `guild`, `coalition`, `household`,
`group`, `GroupRuntime` across `asphodel/**.py`) finds:
- **No** `faction`, `clan`, `guild`, `coalition`, or `GroupRuntime` anywhere.
- `community`: one cosmetic string, a business name template
  (`city_visual/business_identity.py:151` "Community Church"). Not a concept.
- `household`: exists ONLY as a **relationship origin tag** and its prior weights
  (`relationships.py:33,78`), the `init_priors` bucketing (`cognition/runtime.py:169`),
  the `can_call` tie test (`dialogue/runtime.py:133`), the `_share_burst` tie set
  (`cognition/runtime.py:639`), and narrative signature text
  (`signatures.py:77,195`; `citizen.py:1240`). There is **no persistent household
  object, no membership set, no shared state** — the "household" is emergent from
  per-pair relationships keyed by shared `home_building_id`.
- `group` (as a word) appears only as loop variables / row-groups / business-name
  fragments — never a domain concept.

**Conclusion:** the survivor-GROUP layer is genuinely new. It has clean seeds
(origin tags, co-location, `_closeness`) but no existing object to extend or collide
with.

---

## 12. Integration plan for a groups layer

Design invariant: **the group owns membership, shared objectives, and a
provenance-preserving shared record — nothing physical, nothing omniscient.** All
physical effects go through the existing goal-push / dialogue / work paths.

### (a) A `GroupRuntime` owned by World, advanced after dialogue
- New file `asphodel/groups/runtime.py`, class `GroupRuntime(cognition, world_seed,
  dialogue=None)`. Reads `cognition.mobility`, `cognition.work`,
  `cognition.rels`, `cognition.memories`; back-link `cognition.groups = self`
  (mirroring `cognition.dialogue`).
- `World`: add `self.groups=None` + `self._pending_groups_state=None`
  (`orchestrator.py:~171`); `enable_groups()` after `enable_dialogue`
  (`~:357`), guarded on `cognition`, with the `_pending_groups_state`/`from_state`
  branch.
- `_advance_runtimes` (`orchestrator.py:439`): append
  `if self.groups is not None: self.groups.advance(step)` **after** dialogue, so the
  group sees this second's new memories/relationships/conversations and pushes
  effects for the next second — the same one-substep latency every cross-runtime
  effect already carries. Internally gate real decisions behind a
  `_next_decision_s` interval (copy `cognition/runtime.py:203`), not every second.
- Data model: `Group{group_id, members:set[int], roles:{cid:role}, leader,
  objective, shared_record, formed_s, origin}`. Membership state is authoritative and
  persisted; personality/relationships are read-through (never copied).

### (b) Formation candidates WITHOUT omniscience
- **Never scan all N² citizen pairs.** Index by existing edges and co-location:
  - Seed candidates from relationship edges: iterate `cognition.rels.rels` (already a
    sparse edge dict, `relationships.py:93`), keep pairs with `origin in
    {"household","workplace"}` or `_closeness(a,b) >= threshold`. This is O(E), E =
    number of real relationships, not O(N²).
  - Or seed from co-location: `cognition._occupants(bid)` (`runtime.py:217`) /
    `work.occupants_by_room(bid)` — people already in the same room are cheap
    candidates. `_room_mates` (`:228`) gives current co-perceivers.
  - A member proposes/admits others only from citizens it has a relationship with or
    is co-present with — the group never "discovers" a stranger. This is the same
    "index, not a scan" discipline as `_decide_avoid` (`runtime.py:846`).
- Admission reuses cognition: score a candidate with `help_score` / `_closeness` /
  personality `loyalty`,`suspicion`; require mutual `co_present` or a `can_call`
  tie for the invitation to actually be delivered (via dialogue).

### (c) Pushing shared objectives down to individual runtimes
The group sets an `objective` (e.g. `regroup_at(shelter_bid)`,
`supply_run(storage_bid)`, `guard(entrance_node)`) and realises it **per member**
through the existing authorities — the group itself moves nothing:
- **Mobility/relocate:** for each member, ensure `node_meta` for the target building
  (see (e)), build a `Goal(GoalKind.DO_ACTIVITY/ARRIVE_AT, target=node,
  source="social", priority=SOURCE_BASE_PRIORITY["social"]=0.45, reason="group:
  regroup")` and `rt.push_goal(goal, mobility.graph)` (`citizens/runtime.py:100`).
  Use `source="belief"` (0.66) or a bespoke priority for urgent regroup so it beats a
  schedule (0.55) but not an emergency flee (0.92) — a member under attack should
  still flee first. Track pushed goal ids per member so they can be retracted when the
  objective ends (copy the `avoid_goals` retract logic, `runtime.py:876–898`).
- **Coordination/communication:** the leader announcing an objective is a
  `DialogueRuntime` conversation — reuse `warn`/`ask`/`say`/`_start` with a `conv.plan`
  (`dialogue/runtime.py:260,309`), and `can_call` (`:131`) to reach non-co-present
  members. A "does anyone have supplies / seen the threat?" poll is `ask(...,
  channel=PROBE)` (read-only) or a real telling via `transmit` (`:229`).
- **Work/help:** a "cover the register" or "restock for the group" objective becomes
  `dialogue.request_help(requester, helper, problem)` (`:453`) → `work.assist`
  (`smart/runtime.py:958`), or a direct `work.assist` when there is no requester.
  `guard at entrance` is a held-position goal (no Smart Object), not a work task.
- **Every objective effect is idempotent and retractable**, so re-running the coarse
  group decision doesn't restart plans (mirror the "identical flee is kept"
  guard, `outbreak/runtime.py:289`).

### (d) Provenance-preserving shared knowledge
- The shared record holds **only deliberately-communicated facts** — never a member's
  private first-hand memory copied in behind their back. Concretely: the record
  stores `origin_id`s (the information-lineage key, `memory.py:99`) that a member
  chose to share with the group, plus who contributed and when — metadata, not a
  second copy of the truth.
- Propagation to other members is **one `receive_fact` per member**, so each member's
  copy gets its own trust-scaled `told_confidence`, `hops+1`, `source_citizen`, and
  `origin_witness` (`cognition/runtime.py:571,588`). Reuse `_share`
  (`:534`) where possible so cooldowns, dedupe and the sociability roll still apply;
  when a group "briefing" is deliberate (a leader telling the group), route it through
  `dialogue.transmit` (`:229`) exactly like any warning, emitting `FACT_SHARED`/
  `FACT_RECEIVED` with correct lineage.
- Result: `lineage(fact_id)` (`cognition/runtime.py:1028`) still explains who-told-whom
  for group-propagated facts, and a member who was offline (ABSTRACT / not co-present /
  no call tie) simply doesn't learn it yet — no omniscient fill. The shared record is a
  coordination index over member memories, not an oracle.

### (e) Save/load & snapshot hooks
- `save.py`: `world_state` adds `"groups": None if world.groups is None else
  world.groups.to_state()` (`:301`); `load_world` adds `world._pending_groups_state =
  state.get("groups")` (`:336`). Extend the version comment (`:36`).
- `GroupRuntime.to_state()` persists membership, roles, objectives, the shared record
  (origin ids + contributor metadata), event tape, and decision-timer; `from_state(st,
  cognition, dialogue)` re-links to the restored runtimes. It must produce
  **bit-identical continuation** under the `_saveload` harness
  (`test_npc_dialogue_v1_day.py:281`) — so keep all state JSON-safe and rebuild caches
  lazily, exactly like cognition (`runtime.py:1060,1082`).
- Enable ordering on load (`bridge/session.py:_cmd_load:621`): after
  `enable_dialogue`, `if world._pending_groups_state is not None:
  world.enable_groups()`. On `START_WORLD` (`session.py:186`) enable after dialogue,
  gated by a `groups` option.
- Snapshot: add `_merge_groups(snap)` stamping `row["group"] = self.groups.row(cid)`
  and call it in `mobility_snapshot` (`orchestrator.py:455`); add
  `world.groups_snapshot(since_seq)` + a `GET_GROUPS` command (`protocol.py`/`session.py`,
  §8) mirroring `GET_DIALOGUE`. Bump `PROTOCOL_VERSION` to 9.

### O(N²) risks and how to avoid them
| Risk | Avoidance |
|---|---|
| Formation matching all pairs (`for a in N: for b in N`) | Iterate `rels.rels` edges (O(E)) and `_occupants(bid)` co-location buckets (O(occupants)); never enumerate the full population. Mirror `_decide_avoid`'s "index, not a scan" (`runtime.py:846`). |
| Re-scoring every candidate every second | Gate real group decisions behind `_next_decision_s` (coarse interval), like cognition (`:203`). The 1 s `advance` is only the clock. |
| Broadcasting a fact to all members via direct writes | One `receive_fact`/`_share` per member (bounded by membership size), preserving cooldowns and provenance — not an omniscient set-write. |
| Recomputing beliefs/occupants per member | Reuse cognition's cached `beliefs(cid)` (per game-minute, `:650`) and `_occupants` (per substep, `:217`); do not re-derive. |
| Objective goal-push thrash | Track pushed goal ids per member and keep an identical objective in place instead of re-pushing (retract logic from `avoid_goals`, `:876`; "identical flee kept", `outbreak/runtime.py:289`). |

---

## Appendix — quick reference (file : line)

- Enable chain & guards: `orchestrator.py:229,271,300,323,344`
- Substep interleave (add groups after dialogue): `orchestrator.py:417–441` (dialogue `:439`)
- Snapshot merges: `orchestrator.py:364,375,380,443,457`; whole-world snapshot `:826`
- Goal push / retract: `citizens/runtime.py:100,117`; `Goal`/`GoalKind`/priorities `citizens/goals.py:19,28,40`; `GoalStack` `:63`
- Transmission path: `cognition/runtime.py:_share:534`, `receive_fact:571`, `_share_burst:622`
- Relationship model: `cognition/relationships.py:22` (dims), `:56` (RULES), `:77` (PRIORS), `:95` (graph)
- Personality: `cognition/personality.py:12,16,34`
- help_score/_closeness: `cognition/runtime.py:724,741`; init_priors `:154`
- Dialogue reuse: `dialogue/runtime.py:_start:136, say:178, transmit:229, warn:260, ask:356, request_help:453`; channels `dialogue/session.py:16–21`
- Work: `smart/runtime.py:problems:875, help_target:919, assist:958, set_object_state:1057, context:1084, occupants_by_room:1100`; RoomGraph `smart/rooms.py:51`; archetypes `smart/objects.py:40`
- Mobility: `embodied/runtime.py:register:169, node_for_building:117, snapshot`; node_meta build `:201–205`
- Outbreak flee/goal-push: `outbreak/runtime.py:_flee:261, seed_index_case:129`
- Save/load: `save.py:world_state:257, load_world:308, _pending_* :332–336`; session load enable order `bridge/session.py:583–621`
- Bridge: `protocol.py:PROTOCOL_VERSION:43, Command:46, ALL:94`; start-world enable `session.py:89`; GET_* handlers `session.py:295–391`
- No existing group concept: household is only a relationship origin tag (`relationships.py:33,78`; `cognition/runtime.py:169`)

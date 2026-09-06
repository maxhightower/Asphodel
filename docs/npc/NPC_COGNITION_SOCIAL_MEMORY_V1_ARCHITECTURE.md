# NPC Cognition, Social Memory V1 — Architecture

`asphodel/cognition/` is the one owner of what a citizen knows, believes, feels
about other citizens and decides socially. It sits *between* the existing
authorities and never replaces one:

```
perception  ->  memory / belief  ->  evaluation  ->  existing CitizenRuntime goal
                                                      existing WorkRuntime constraint / help task
                                                      existing execution (TripExecutor, interior walk)
```

| concern | owner | what cognition does with it |
|---|---|---|
| citizen identity, profile, schedule | `citizen.py`, bundles | reads home/work building for priors, nothing else |
| goal selection, planning, replanning | `CitizenRuntime` / `GoalStack` | pushes `Goal(DO_ACTIVITY, source="belief")`; removes only its own goals |
| city movement, building transitions | `TripExecutor`, `MobilityRuntime` | reads canonical positions and bands; writes nothing |
| rooms, smart objects, reservations, tasks | `WorkRuntime` | reads `context`, `occupants_by_room`, `problems`; supplies `room_filter`; asks `assist()` to run a help task |
| health, threats, flee, disruption | `OutbreakRuntime` | reads its events; the outbreak's own flee/disruption goals keep precedence |
| LOD | `LODController` / bands | ignored: cognition runs on canonical state at every band |
| save/load | `save.py` | one `cognition` block, restored by `World.enable_cognition()` |
| bridge / Godot | protocol v7 | `GET_COGNITION`, `GET_CITIZEN_CONTEXT`; the renderer draws, never decides |

## Modules

### `memory.py` — structured episodic facts

`MemoryFact`: `fact_id` (`<owner>:<n>`), `owner`, `kind`, `actor`, `target`,
`building_id`, `room_id`, `object_id`, `t`, `source` (`direct` /
`participant` / `told`), `source_citizen`, `origin_witness`, `origin_id`,
`hops`, `confidence`, `salience`, `valence`, `count`, `last_t`, `detail`.
Kinds are a closed vocabulary (`KINDS`): work/social (`WORKED_BESIDE`, `MET`,
`SERVED`, `SERVED_BY`, `HELPED`, `HELPED_BY`, `SAW_HELP`, `STATION_FAILED`,
`COWORKER_INTERRUPTED`, `WORKPLACE_DISRUPTED`, `WARNED_BY`, `FALSE_WARNING`,
`FLED_WITH`, `ABANDONED_BY`) and threat (`THREAT_PERSON`, `ATTACK_SEEN`,
`ATTACKED_BY`, `CORPSE_SEEN`, `DEATH_SEEN`, `PLACE_SAFE`). No prose is ever
authoritative.

`MemoryStore` (per citizen, `CAPACITY = 64`):

* **merge** — the same `(kind, actor, target, building, room)` reinforces one
  fact (`count`, `last_t`); a first-hand account supersedes hearsay of the same
  fact;
* **decay** — `effective(now) = confidence · 0.5^(age / half_life(salience))`
  with half-lives from 2 h (trivial) to ~3 days (salience 1);
* **forgetting** — `consolidate()` (every 10 game minutes) drops non-durable
  facts whose effective confidence fell under 0.05 and, over capacity, the
  least effective first; durable facts (`salience ≥ 0.8`: help, attacks,
  deaths, threats) go last.

### `beliefs.py` — derived, cached, possibly wrong

`derive(store, now)` recomputes every belief from the facts:
`danger:person:<cid>`, `danger:room:<bid>:<rid>`, `danger:building:<bid>`
(noisy-OR over evidence weights: first-hand = effective confidence; hearsay =
told confidence × `0.75^(hops-1)`; a later `PLACE_SAFE` observation of the same
place halves the earlier evidence). Building danger aggregates room dangers
(× 0.9). Beliefs carry their evidence ids and source citizens, so any belief
can be traced to the facts and tellers behind it. Cached per citizen and
invalidated when the store changes.

### `relationships.py` — six bounded dimensions, one rule table

`Relationship(owner, other)`: `familiarity`, `trust`, `affinity`, `fear`,
`hostility`, `obligation` in [0, 1], plus `interactions`, `last_t`, `origin`.
Only `RelationshipGraph.apply(owner, other, rule)` changes them, through
`RULES` (saturating deltas): `worked_beside`, `met`, `served(_by)`,
`helped(_by)`, `saw_help`, `reciprocated`, `warned_by`, `warning_confirmed`,
`false_warning`, `attacked_by`, `threat_seen`, `attack_seen`, `fled_with`,
`abandoned_by`, `told_threat`. Priors: household (`familiarity 0.8, trust
0.7, affinity 0.6`) and workplace (`0.3 / 0.4 / 0.15`), applied once at
`enable_cognition`; everything after is experience.

### `personality.py` — five traits, pure function

`personality_for(seed, cid)` → `sociability, helpfulness, risk_tolerance,
loyalty, suspicion` (mean of two hash uniforms). Never stored, cannot drift
or reroll. They bias thresholds and rolls only.

### `social.py` — the grammar and the limits

Actions: `HELP`, `WARN`, `SHARE_INFORMATION`, `CHECK_ON`, `AVOID_PERSON`,
`AVOID_LOCATION`, `FOLLOW`; utterance labels `OFFER_HELP`, `WARN_THREAT`,
`SHARE_INFO`, `THANK`, `ACKNOWLEDGE` (V1 demonstrates HELP, WARN,
AVOID_LOCATION and the thanks). Sharing limits: `SHAREABLE` kinds with a
minimum effective confidence, `MAX_HOPS = 2`, `PAIR_COOLDOWN_S = 1800`,
duplicate suppression by `(sender, recipient, origin_id)`, a deterministic
sociability roll for casual encounters, calls only to household/workplace
ties or familiarity ≥ 0.55, `MAX_CALLS_PER_FACT = 3`;
`told_confidence = sender_conf · (0.45 + 0.55·trust) · (1 − 0.4·suspicion)`.

### `runtime.py` — `CognitionRuntime`

Advanced by `World._advance_runtimes` in the same 1 s substep as movement,
outbreak and work (the world clock now interleaves the four runtimes per
second, so a result never depends on the caller's chunk size).

**Perception channels** (the only ways a fact enters a store):

| channel | source value | what |
|---|---|---|
| own room | `direct` | work events in the citizen's room (`occupants_by_room`), outbreak events in its room; outdoors within 20 m of its canonical position |
| participation | `participant` | served / served by, helped / helped by, attacked, fled with, station failed on it, disrupted workplace |
| telling | `told` | an encounter (same room, outdoors ≤ 20 m), a shout through the building at the moment of a first-hand threat, a call to a strong tie |

The work and outbreak event streams are drained by `since_seq` every second;
every row is mapped to participants and same-room observers before it becomes
anyone's memory. Co-presence is scanned every 5 game minutes (indoors per
room with a partner cap of 6, outdoors through a 20 m grid) and feeds
`WORKED_BESIDE` / `MET` reinforcement, familiarity and encounter sharing.
Alarmed citizens (a first-hand threat in the last 30 min) check passers-by
every second, so a fleeing witness warns whoever it passes.

The outbreak's own witness rule was refined to room level when the work
layer is on (`OutbreakRuntime._same_room`): a citizen sees an attack in its own
room, not through walls. That is the minimal change that makes "the back-room
worker did not see it" true.

**Decisions** (`_decide`, every game minute; avoidance also at once on a
received warning):

* *help* — for every building with ≥ 2 workers, `WorkRuntime.problems(bid)`
  (unstaffed queue, queue overload, a coworker's broken station, a cleaning or
  restocking backlog) × available helpers (present, not on break, not serving
  a queue, off cooldown). `help_score = 0.5·helpfulness + 0.25·familiarity +
  0.35·affinity + 0.6·(0.7+0.6·loyalty)·obligation + 0.15·trust −
  0.5·(fear+hostility) − cost(problem)`, threshold 0.40. The best helper runs
  `WorkRuntime.assist(helper, task, object, beneficiary)` — a real task
  through the job grammar (`cover_station`, `help_clean`, `help_restock`,
  `repair_station`), reservations and interior walking included. Every
  `HELP_DECIDED` row carries the components and the score the same citizen
  would have had with no relationship history.
* *avoid a building* — a destination (the active goal's building) whose
  believed danger ≥ `0.35 + 0.3·risk_tolerance` gets a `belief` goal home
  (priority 0.66 + 0.12·danger: above any schedule goal, below health and
  emergencies), held ≤ 4 h and dropped when the belief fades.
* *avoid a room* — `avoid_rooms(cid, bid)` (danger ≥ `0.25 +
  0.3·risk_tolerance`) is the `WorkRuntime.room_filter`: task targets, the
  assigned station, wait zones, shelves and tills in those rooms are skipped
  while the citizen keeps working elsewhere in the building.
* *observe safety* — ten minutes in a room believed dangerous with no threat
  present records `PLACE_SAFE` (belief halves); a told threat about that room
  contradicted within 15 min of its claimed time is a `FALSE_WARNING` (trust
  in the teller drops).

**Context API** — `citizen_context(cid)` (also bridge `GET_CITIZEN_CONTEXT`):
location (building, room, zone, band), task, goal, needs, health,
personality, salient memories with effective confidence, people nearby with
relationship and danger, top relationships, beliefs, perceived danger,
current avoidance, avoided rooms here, recent social events. `lineage(fact)`
answers "who told whom" from the origin witness down.

**Events** (ring of 5000, persistent `counts`): `PRIORS`, `PERCEIVED`,
`MEMORY_CREATED`, `MEMORY_REINFORCED`, `MEMORY_DECAYED`, `BELIEF_UPDATED`,
`RELATIONSHIP_CHANGED`, `TRUST_CHANGED`, `HELP_DECIDED`, `HELP_STARTED`,
`HELP_COMPLETED`, `RECIPROCATED`, `WARNING_SHARED`, `WARNING_RECEIVED`,
`AVOID_DECIDED`, `AVOID_ROOM_DECIDED`, `AVOID_ENDED`, `SOCIAL_ACTION`,
`ENCOUNTER` (counted).

**Persistence** — memories, relationships, told-set, pair cooldowns, calls,
help cooldowns/pairs/log, pending help, avoidance goals, safety timers,
events, counts, drain cursors. Caches (beliefs, avoided rooms, personality,
occupants) are rebuilt on demand.

## What was added to existing authorities (and nothing else)

* `smart/jobs.py`: `HELP_TASKS` (four task definitions, targets given not
  selected). `smart/runtime.py`: `problems()`, `help_target()`, `assist()`,
  `_move_queue_to()`, the `room_filter` hook in `_candidates` / assigned
  station / wait zone / customer browse and queue, `repair` effect,
  `cover_station` serving, `HELP_TASK` / `HELP_DONE` / `QUEUE_MOVED` events,
  `help_for` / `helped` on the session.
* `citizens/goals.py`: `SOURCE_BASE_PRIORITY["belief"] = 0.66`.
* `outbreak/runtime.py`: `_same_room` line of sight for witnesses; the
  incapacitation / reanimation goal wipes also drop `belief` goals;
  `pathogen.py`: `classic_zombie_fast` archetype (the certification stressor).
* `orchestrator.py`: `enable_cognition`, `cognition_snapshot`,
  `citizen_context`, `_merge_cognition`, `_advance_runtimes` (1 s interleave).
* `save.py`: `cognition` block. `bridge`: v7 commands, `cognition` START_WORLD
  option, LOAD restore, `cognition_enabled` summary. `godot/scripts/sim_bridge.gd`
  v7.

## Bounds and complexity

* memory: ≤ 64 facts per citizen; merged aggregates; salience-weighted decay;
* co-presence: per room ≤ 6 partners per citizen per 5 min; outdoors a grid;
* transmission: cooldowns, told-set, hop limit, per-fact call cap; alarm
  window 30 min;
* decisions: help evaluation only in buildings with ≥ 2 workers and a
  problem; avoidance only for citizens holding threat facts (an index of
  stores, not a scan of the city); beliefs cached per minute per citizen.

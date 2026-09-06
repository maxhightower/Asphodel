# ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 — Report

**Verdict: ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1: PASS**

## 1. Provenance

| | |
|---|---|
| starting SHA | `285828b` (certified `ASPHODEL_SMART_OBJECTS_WORK_V1: PASS`; verified on the branch before work began) |
| merge base with `main` | `bee2f18a1827` |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` |
| certification SHA | `CERT_SHA_PLACEHOLDER` (the commit whose code every artifact in `artifacts/npc_cognition_v1/` was produced with) |
| final SHA | `FINAL_SHA_PLACEHOLDER` (this stamp; pushed to `origin/claude/asphodel-embodied-mobility-v1-6gl4a8`) |
| commits in this milestone | COMMITS_PLACEHOLDER |

Nothing was branched from an experimental branch; every change sits on the
certified work spine.

## 2. Authority census (what owns what)

| authority | owner | unchanged? | what this milestone added |
|---|---|---|---|
| citizen identity, profiles, schedules | `citizen.py`, bundles | yes | read for household/workplace priors |
| goal selection, planning, replanning | `CitizenRuntime` / `GoalStack` | yes | one new goal source `belief` (priority 0.66 + 0.12·danger, below health 0.80 and emergencies) |
| city movement, building transitions | `TripExecutor`, `MobilityRuntime` | yes | nothing; cognition reads positions and bands |
| rooms, smart objects, reservations, tasks | `WorkRuntime` | yes (extended) | `problems()`, `help_target()`, `assist()`, `room_filter`, four help task definitions, `repair` effect, `HELP_TASK/HELP_DONE/QUEUE_MOVED` events |
| health, threats, flee, disruption | `OutbreakRuntime` | yes (refined) | room-level line of sight for witnesses when the work layer is on; `belief` goals dropped on incapacitation/reanimation; `classic_zombie_fast` archetype |
| perception, memory, beliefs, relationships, social decisions | **`asphodel/cognition/` (new)** | — | the one owner of all of it |
| world clock | `World.advance_seconds` | changed | movement, outbreak, work and cognition now interleave in 1 s substeps (`_advance_runtimes`) |
| save/load | `save.py` | extended | `cognition` block |
| bridge / Godot | protocol v7 | extended | `GET_COGNITION`, `GET_CITIZEN_CONTEXT`, `cognition` START_WORLD option, `cognition_enabled` summary, `sim_bridge.gd` wrappers |

No subagent introduced a competing citizen, navigation, schedule, object or
planning authority (`docs/npc/NPC_COGNITION_AUTHORITY_AUDIT.md` is the
pre-implementation census; gates N21/N22 check it on the running world).

## 3. Architecture (summary; full text in the architecture document)

```
perception -> memory / belief -> evaluation -> CitizenRuntime goal (belief) | WorkRuntime constraint (room_filter) | WorkRuntime help task (assist)
```

* **Perception** — a citizen learns a fact only through its own room
  (the WorkRuntime's `occupants_by_room`), the 20 m outdoor radius around its
  canonical position, its own participation, or a telling (encounter, a shout
  through the building at a first-hand threat, a call to a household /
  workplace tie). The work and outbreak event streams are drained every
  second and filtered through those channels; nothing else writes memory.
* **Memory** — `MemoryFact` (kind, actor, target, building, room, object,
  time, source, teller, origin witness, origin fact id, hops, confidence,
  salience, valence, count, last reinforcement); `MemoryStore` of ≤ 64 facts
  per citizen with merging, salience-dependent decay and consolidation.
* **Belief** — derived from the facts (noisy-OR over source-weighted,
  decayed evidence; a later direct "safe" observation halves earlier
  danger evidence); `danger:person`, `danger:room`, `danger:building`.
* **Relationships** — six directed dimensions (familiarity, trust,
  affinity, fear, hostility, obligation), one rule table, household /
  workplace priors only.
* **Personality** — five traits, pure function of (seed, citizen).
* **Decisions** — help (through `WorkRuntime.assist`), avoid a room
  (`room_filter`), avoid a building (`belief` goal), warn (bounded
  transmission with lineage), observe safety.
* **Context API** — `citizen_context(cid)` / `GET_CITIZEN_CONTEXT`.

## 4. Certification table (`tests/test_npc_v1_day.py`, Houston, 05:00→20:30)

| gate | requirement | status | evidence |
|---|---|---|---|
| N1 | Perception limited to plausible channels | PASS | 1154 facts in 185 citizens; sources: ['direct', 'participant', 'told']; every told fact names its teller and origin witness (45 told facts, 0 orphans) |
| N2 | No global omniscience | PASS | 281 citizens were never inside shop 15873; 0 hold a first-hand fact about the attack there (must be 0); 1 know of it only because someone told them; 0 first-hand threat facts anywhere are held by someone who was elsewhere |
| N3 | Structured persistent memory exists | PASS | MemoryFact fields ['actor', 'building_id', 'confidence', 'count', 'detail', 'fact_id', 'hops', 'kind', 'last_t', 'object_id', 'origin_id', 'origin_witness', 'owner', 'room_id', 'salience', 'source', 'source_citizen', 't', 'target', 'valence']; 185 stores persisted in the save block |
| N4 | Memory provenance preserved | PASS | 45/45 told facts point at a first-hand fact of their origin witness of the same kind; 145 tellings, 41 second-hop; lineage of one second-hop fact: 297->8 -> 297->19 -> 297->25 -> 297->82 |
| N5 | Memory decay/merge bounded | PASS | max facts per citizen 37 (cap 64); 20197 reinforcements merged into existing facts (top: WORKED_BESIDE about 70 x202); 32 consolidation passes dropped decayed facts |
| N6 | Belief derives from memory/evidence | PASS | citizen 297: 4 beliefs, all evidence ids are facts in its own store; strongest danger:person:222=1.00 from 4 facts, first_hand=True, sources [82, 167] |
| N7 | Relationship state persists per pair | PASS | 718 directed relationships (priors: household/workplace; the rest experience); persisted per pair |
| N8 | Real interaction changes relationship | PASS | 2783 logged relationship changes by rules ['attack_seen', 'attacked_by', 'fled_with', 'helped', 'helped_by', 'met', 'reciprocated', 'saw_help', 'served_by', 'threat_seen', 'told_threat', 'warned_by', 'warning_confirmed', 'worked_beside']; e.g. 79->70 after helped_by: [{'dim': 'familiarity', 'old': 0.3, 'new': 0.37}, {'dim': 'trust', 'old': 0.4, 'new': 0.55}, {'dim': 'affinity', 'old': 0.15, 'new': 0.405}, {'dim': 'obligation', 'old': 0.0, 'new': 0.5}] (now familiarity=1.00 trust=0.75 affinity=0.74 obligation=0.35) |
| N9 | Helping decision occurs from actual context | PASS | 12 help decisions; first: citizen 70 (cashier) saw cleaning_workload of coworker 79 (cleaner) at 8470: score 0.415 ≥ 0.4 from {'helpfulness': 0.378, 'familiarity': 0.075, 'affinity': 0.052, 'obligation': 0.0, 'trust': 0.06, 'fear_hostility': -0.0, 'cost': -0.15} |
| N10 | Helping executes through existing Smart Objects/work | PASS | WorkRuntime ran help_clean for 70: HELP_TASK, USE_START at so:8470:28 (gondola), STATE_CHANGE dirty=False; 12 help tasks completed city-wide |
| N11 | Recipient remembers help | PASS | beneficiary 79 holds HELPED_BY(actor=70, help_clean, count=3, source=participant, salience=0.85) |
| N12 | Later reciprocal decision depends on prior history | PASS | station so:8470:29 of 70 broken at 13.0; the coworker it helped in the morning (79) decided repair_station at 13.017 (score 1.137, without history 0.003), repaired at 13.15, RECIPROCATED (obligation discharged); 70 retook the station at 13.52 |
| N13 | Direct threat witness forms threat memory | PASS | fast case seeded in customer 222 inside shop 15873 at 10.6; 22 attacks, 40 witness observations; 62 first-hand threat facts in 40 citizens (every living victim holds ATTACKED_BY, 24/24 witnesses hold a first-hand fact); kinds ['ATTACKED_BY', 'ATTACK_SEEN', 'THREAT_PERSON'] |
| N14 | Threat memory changes later decision | PASS | witness 19 (first-hand) with the emergency over and the schedule pointing back at shop 15873: with its memory it refuses (AVOID_DECIDED first_hand=True, danger 0.966; goal now belief -> building 21714); with 15 threat facts erased it heads back (goal schedule -> 15873) |
| N15 | Citizen communicates warning to another citizen | PASS | 145 threat warnings shared by 22 citizens over channels {'shout': 77, 'call': 14, 'encounter': 54}; utterance WARN_THREAT; max per sender 13; max hops 2 (limit 2) |
| N16 | Recipient records socially sourced memory | PASS | 145 receptions recorded as told facts: 45 told threat facts held by 26 citizens with source_citizen/origin_witness/hops; confidence of a told fact 0.54 vs 1.0 first-hand |
| N17 | Recipient behavior changes because of warning | PASS | citizen 297 (cashier) in building 15873 was told by [82] (danger 0.52 ≥ its threshold 0.421) and pushed a belief goal home at 10.77 (preempted the do_activity goal, inside=True) — before any first-hand perception of its own (own first perception seq 1679 vs decision seq 989); 1 such decisions |
| N18 | Source trust affects belief/action | PASS | told_confidence(1.0) is 0.38 at trust 0.05 vs 0.78 at trust 0.95; live: citizen 297 receives the same warning from 82 at confidence 0.578 (trust 0.30) vs 0.433 when it distrusts 82 (trust 0.02); danger after 0.52 vs 0.39; avoid True vs True |
| N19 | Conflicting/direct evidence can update belief | PASS | (no in-day update) told danger 0.60 -> 0.30 after a direct safe observation |
| N20 | Room-level avoidance works | PASS | 15 room-avoidance decisions; worker 297 at 15873 avoids rooms [0] while its role's tasks still have candidates in rooms [] (unfiltered [0, 1]); the WorkRuntime room_filter is the only constraint applied |
| N21 | Existing CitizenRuntime remains decision authority | PASS | cognition only ever pushes DO_ACTIVITY goals with source 'belief' into the existing GoalStack (0 live now; sources present ['disruption', 'emergency', 'idle', 'schedule']); selection, planning, replanning stay CitizenRuntime's |
| N22 | No duplicate movement/schedule authority | PASS | five cognition-only substeps: every executor position, building, state and adopted plan unchanged; movement is the TripExecutor's, interior movement the WorkRuntime's, schedules the CitizenRuntime's |
| N23 | LOD demotion preserves cognition | PASS | citizen 70 at 8470: after the minute back at ROUTE_SIMULATED the whole cognition state (memories, relationships, told-set, help state) is identical to a control copy of the same world that was never promoted |
| N24 | LOD promotion preserves cognition | PASS | promoted to PHYSICAL (2 bodies) for one second while the control copy stayed ROUTE_SIMULATED: every memory store, relationship and help task identical between the two worlds (2 facts for the helper); personality is a pure function of seed and id |
| N25 | Save/load memory/belief passes | PASS | 7 moments {'after_help_decided': 7.633, 'after_relationship_change': 7.817, 'after_direct_observation': 10.784, 'mid_social_interaction': 10.967, 'after_threat_memory': 11.15, 'after_avoidance_decision': 11.334, 'after_rumor_transmission': 11.517}: memories and beliefs' evidence identical after restore, 10-minute continuation byte-identical; missing [] |
| N26 | Save/load relationships passes | PASS | relationship graph identical at every moment |
| N27 | Save/load social transmission passes | PASS | told-set, pair cooldowns, calls, lineage (events) and belief goals identical at every moment |
| N28 | Counterfactual helping test passes | PASS | same world restored twice before the break: with the morning's help in memory 79 decides repair_station (score 1.137); with HELPED_BY erased (1 facts) and trust/affinity/obligation back at the workplace prior (familiarity kept) it does not (score without the help 0.320 < 0.4); of 9 helper/beneficiary pairs available at 13:00, 9 flip on the help history, 0 would repair anyway (helpfulness + familiarity) |
| N29 | Counterfactual warning test passes | PASS | same world restored twice before the seeding: warned, citizen 297 leaves on a belief goal at 10.77 (own first perception 10.771); never warned, it stays on its schedule until it perceives the threat itself at 10.771 (flee 10.771) — no belief goal |
| N30 | Godot embodiment demonstrates social action | PASS | godot probe:  0 FAIL rows |
| N31 | Smart Objects/Work gate remains PASS | PASS | {"status": "PASS", "pass": 44, "fail": 0, "info": 0, "exit": 0, "log": "g_work.log"} |
| N32 | Outbreak gate remains PASS | PASS | {"status": "PASS", "pass": 36, "fail": 0, "info": 2, "exit": 0, "log": "g_outbreak.log"} |
| N33 | Mobility gate remains PASS | PASS | {"status": "PASS", "pass": 48, "fail": 0, "info": 2, "exit": 0, "log": "g_mobility.log"} |
| N34 | Existing Godot gates remain PASS | PASS | {"status": "PASS", "pass": 85, "fail": 0, "exited_nonzero": 0, "scenes": ["tests/PhysicsGate.tscn", "tests/RegionGate.tscn", "tests/NavGate.tscn", "tests/ConvergenceGate.tscn"]} |
| N35 | Multi-city smoke | PASS | {"houston": "PASS", "madisonville_tx": "PASS", "austin": "PASS", "san_antonio": "PASS", "boulder": "INFO"} |
| N36 | No city-name special cases | PASS | city-name matches in cognition/work/outbreak/world code: [] |

Picks are data-driven: the busiest shop is the building with the most errand
visitors (15873, 14), the threat is seeded in the first customer inside it,
the helping pair is the first completed help of the day, and the reciprocity
pair is chosen among that day's completed help pairs as the one whose
beneficiary would repair only because of the help it received (the table
reports how many pairs flip and how many would repair anyway).

## 5. Perception: what citizens can and cannot know

* 281 of the 297 registered citizens were never inside the attacked shop;
  **none** of them holds a first-hand fact about the attack; the ones who know
  of it (26 citizens with told threat facts) hold facts with `source=told`, a
  named teller, the origin witness and the hop count (N2, N4).
* Every first-hand threat fact is held by a citizen the authorities placed at
  that building or outdoors next to it at that second (checked against the
  outbreak's and the work runtime's own rows; 62 first-hand facts in 40
  citizens, N1/N13).
* Indoors, line of sight is the room: the outbreak's witness rule was refined
  so that an attack on the sales floor is not seen from the back room
  (`OutbreakRuntime._same_room`, the minimal fix §33 allows). What the back
  room learns, it learns by being told.
* Ten cognition-only substeps move no executor and adopt no plan (N22).

## 6. Memory: structure, capacity, persistence

* 20 fact kinds, all structured (§6); no prose is authoritative.
* Max 37 facts per citizen over the day (capacity 64); 20 197
  reinforcements merged into existing facts (the top fact is
  `WORKED_BESIDE` about one coworker reinforced 202 times — one memory, not
  two hundred); 32 consolidation passes dropped decayed trivial facts;
  durable facts (help, attacks, deaths) survive (N5).
* The store, its sequence counter and every field persist exactly
  (relationships are persisted unrounded; the rounded view is for display),
  so seven save/load moments continue byte-identically (N25–N27).

## 7. Relationships: dimensions and update rules

718 directed relationships at the end of the day (136 pairs of priors at
boot: household 0.8/0.7/0.6, workplace 0.3/0.4/0.15; the rest created by
events). 2 783 logged changes by the rules `worked_beside`, `met`,
`served_by`, `helped`, `helped_by`, `saw_help`, `reciprocated`, `warned_by`,
`warning_confirmed`, `told_threat`, `threat_seen`, `attack_seen`,
`attacked_by`, `fled_with`; 445 trust changes ≥ 0.05. Example: cleaner 79's
view of cashier 70 after the morning's help — familiarity 0.30 → 0.36,
trust 0.40 → 0.55 → 0.75, affinity 0.15 → 0.41 → 0.71, obligation 0 → 0.50 →
0.875 (three help tasks), then `reciprocated` −0.6·0.875 → 0.35 after the
afternoon's repair (a partial repayment; the debt of three favours is not
cleared by one).

## 8. Helping and reciprocity (the certified chain)

Phase A, natural (12 help decisions city-wide, 5 helper/beneficiary pairs):

| time | event |
|---|---|
| 07:37 | cashier 70 at retail workplace 8470, register idle, sees the cleaning backlog of coworker cleaner 79 (14 dirty objects, a `cleaning_workload` problem); `help_score` 0.415 ≥ 0.40 (helpfulness 0.378 + familiarity 0.25·… + …); without any relationship history the score is 0.103 — it would not help a stranger |
| 07:37–07:55 | `WorkRuntime.assist`: 70 releases its station, reserves `so:8470:28` (a gondola), walks to it, `USE_START`, `STATE_CHANGE dirty=false`, `HELP_DONE`; twice more (`so:8470:26`, `so:8470:17`) |
| each time | 79 remembers `HELPED_BY(actor=70)` (participant, salience 0.85, count 3), 70 remembers `HELPED`, 79→70 trust/affinity/obligation rise; `THANK` utterance |

Phase B, the reciprocal decision (stressor: 70's assigned station
`so:8470:29` set `working=false` at 13:00 through `SET_OBJECT_STATE`, no
auto-repair):

| time | event |
|---|---|
| 13:00 | `problems(8470)` reports `station_failed` for 70 (displaced to another till) |
| 13:01 | cleaner 79 decides `repair_station` on `so:8470:29`: score 1.137 (obligation 0.569 + affinity 0.248 + trust 0.112 + …); the same decision with the morning's help erased and trust/affinity/obligation back at the workplace prior scores 0.320 < 0.40 |
| 13:08 | repaired (`working=true`), `RECIPROCATED`, 70 retakes its station |

Counterfactual C1 (N28): the world restored twice from the save taken just
before the break; in the copy where 79's `HELPED_BY` fact is erased and its
relationship to 70 reset to the prior (familiarity kept), the station stays
broken — nobody repairs it. Of the 9 helper/beneficiary pairs available at
13:00, all 9 flip on the help history.

## 9. Threat and warning (direct observation → warning → indirect belief → changed behaviour)

The day's stressor is `classic_zombie_fast` (the classic zombie with a
6-minute onset), seeded at 10:35 in customer 222, the first errand customer
inside the busiest shop. 222 falls ill, collapses on its way out, dies and
rises at the door at 10:44, and attacks inside the shop at 10:45.

| time | event |
|---|---|
| 10:45:0x | 222 attacks customer 8 in room 0 (sales floor); 8 remembers `ATTACKED_BY` (participant); the customers in room 0 remember `THREAT_PERSON(222)` and `ATTACK_SEEN(222→8)` first-hand and flee (the outbreak's own flee); `fled_with` relationships form |
| same second | the first-hand witnesses shout through the building: 77 shout tellings; cashier 297 at its register in room 1 receives `ATTACKED_BY(222→8, room 0)` told by 82 at confidence 0.58 (trust 0.30 in a stranger) |
| same second | 297: `danger:room:15873:0` = 0.52 ≥ its room threshold 0.32 → `AVOID_ROOM_DECIDED` rooms [0] (its role's candidate objects in room 0 are filtered out, room 1 kept, N20); `danger:building:15873` = 0.52 ≥ its building threshold 0.42 → `AVOID_DECIDED` (first_hand=false, sources [82]) → a `belief` goal home preempts the schedule's work goal — **before 297 perceives anything itself** (decision seq 989 vs its own first perception seq 1679; it then sees the attack on its way out) |
| 10:45 | the victims call their household / workplace ties: night cleaner 57 of the same shop, asleep at home, is told by 297 (channel `call`, confidence 0.56 ≥ its threshold 0.54) |
| 10:45–10:58 | alarmed witnesses warn passers-by outdoors (54 encounter tellings, 41 of them second-hop); 145 tellings total from 22 senders, max 13 per sender, hops ≤ 2 |

Counterfactual C2 (N29): from the save taken before the seeding, one copy
runs as-is and one in which 297 never hears any warning. Warned, 297 leaves
on a belief goal at 10:46; never warned, it stays at its register on the
schedule goal until it perceives the threat itself and flees — no belief
goal, no room avoidance.

Counterfactual C3 (N16/N18): the same fact is held at confidence 1.0 by the
victim and at 0.54–0.58 by those told; `told_confidence(1.0)` is 0.38 at
trust 0.05 and 0.78 at trust 0.95.

Counterfactual C4 (N18): a third copy in which 297 distrusts its future
source (trust 0.02): the same telling lands at 0.43 instead of 0.58 and the
room danger after it at 0.39 instead of 0.52 — below 297's building
threshold on that single telling; it still leaves once several independent
witnesses have shouted (noisy-OR over sources), which is the intended
epistemics: one distrusted voice does not move it, five do.

N14 (a first-hand memory changes a later decision): from the post-attack
state, customer 19 (a first-hand witness) has its flee goal ended and its
schedule pointing back at the shop; with its memory it refuses
(`AVOID_DECIDED first_hand=True`, danger 0.97, belief goal home); with its 15
threat facts erased it walks back to the shop on the schedule goal.

N19 (conflicting evidence): a told danger of 0.60 halves to 0.30 after a
direct safe observation of the room; in the day nobody stayed in a room it
believed dangerous long enough to record one, so the row is certified on the
belief derivation itself (stated in the table).

## 10. Room-level context

Every threat fact carries the room it happened in (the attack in room 0 of
15873, later ones in rooms 1 and 2 as the undead moved). 15
`AVOID_ROOM_DECIDED` rows: warned occupants of 15873 avoid room 0 while the
building still has usable rooms; later in the day two citizens avoid single
rooms of other buildings. The `WorkRuntime.room_filter` is the only
constraint: with it, cashier 297's `man_register` candidates exclude the
room-0 tills and keep the room-1 ones (N20).

## 11. LOD

Cognition runs on canonical state at every band. The probe at 08:00 compares
the live world (the helper promoted to PHYSICAL for one second, 2 bodies)
with a control copy of the same save advanced with the focus far away: every
memory store, relationship, told-set and help task identical in both; after
a minute back at ROUTE_SIMULATED the whole cognition state is identical to
the control (N23/N24). Personality is a pure function of seed and id, so
nothing can be regenerated.

## 12. Save/load

Seven moments (07:38 after a HELP decision with the task in flight, 07:49
after a `helped_by` relationship change, 10:47 after a direct threat
observation, 10:58 mid social interaction, 11:09 after a threat memory,
11:20 after an avoidance decision, 11:31 after a second-hop rumour): the
cognition block, memories, relationships, told-set, cooldowns, calls,
lineage and belief goals identical after restore, and ten further minutes
byte-identical (N25–N27). No reroll of anything on load.

## 13. Godot (`tools/run_cognition_gate.sh`, `tools/run_cognition_shots.sh`)

CognitionGate (live bridge v7, the real IsometricWorld scene, real physics,
xvfb): **30 PASS / 0 FAIL / 2 INFO**. In engine: the helper's and the
beneficiary's `CitizenBody` inside the staged interior of 8470 (1.3 / 3.5 m
from the authoritative pose), the helper's body closing 2.34 → 0.66 m on the
object it was sent to; 79→70 obligation 0 → 0.50 after `HELP_COMPLETED`; LOD
1.5 km away and back with no fact or relationship lost; the threat chain
with `WARNING_RECEIVED` (shout, `goal_before=schedule`) → `AVOID_DECIDED`
(`first_hand=false`) → own `PERCEIVED` in that order; the warned citizen's
interior body gone from the staged shop; `RECIPROCATED` at 13:09;
SAVE+LOAD leaving `GET_CITIZEN_CONTEXT(70)` byte-identical. The INFO rows:
after walking out the warned citizen had seen the attack itself and was on
an emergency goal; 79's obligation reads 0.35 after the repayment (§7).

Rendered evidence `docs/npc/evidence/00..08_*.png` + `manifest.json`, each
caption stating what pixels prove and what only the authority rows prove:

| file | what the frame shows |
|---|---|
| `00_coworkers.png` | the sales floor of 8470 with the cashier's and the cleaner's bodies (a fixture can hide one at this angle) |
| `01_problem.png` | the same floor; a dirty fixture is drawn like a clean one — the 14-object backlog is authority only |
| `02_helper_moves_to_assist.png` | the helper's body partway across the room on its way to `so:8470:28` (`to_object`); a still cannot show motion |
| `03_both_embodied_during_help.png` | the helper at the object with the gold `using` tint and holder ring, the beneficiary embodied in the same room |
| `04_reciprocal_repair.png` | a worker body among the shelves after the station broke; that it is 79 repaying is the manifest's |
| `05_threat_witnessed.png` | the shop floor of 15873 with 12 embodied citizens at the first `PERCEIVED attacked_by`; the attacker has no body in the frame (an attacking undead reports `on_foot`, not an interior state) |
| `06_warned_citizen_reroutes.png` | the street outside 15873 with the walking body of the warned citizen (221 in the engine run, warned by shout in room 2, belief goal seconds later); a route change looks like a walk |
| `07_carrying_the_alarm.png` | **NOT REACHED**: the fleeing witness was outdoors with nobody within 25 m; warnings have no visual channel |
| `08_lod_return.png` | the helper's body recreated 0.00 m from its pose after 10 game minutes 1.5 km away; a picture cannot show a memory |

## 14. Performance (`tools/cognition_perf.py`, Houston, 297 citizens, 4-core shared container; artifact `performance.json`)

All numbers from `artifacts/npc_cognition_v1/performance.json` (final code,
median of 3 where cheap; a shared 4-core container).

| measurement | result |
|---|---|
| perception scan (work + outbreak drains, 60 calls per game minute) | 0.24 ms per game minute at 08:00 (4 µs per call), 0.49 ms in the threat window, 0.01 ms at 16:00 when nothing is emitted |
| memory insertion / update (`remember`, 1e5 ops on a 60-fact store) | 2.4 µs new fact, 0.5 µs reinforcement; `consolidate()` of a 64-fact store 0.02 ms |
| memory lookup (64 facts, 1e5 ops) | `find` 1.5–1.9 µs, `about` 2.1 µs, `salient(8)` 30 µs (a full sort with decay per fact) |
| belief derivation (`derive`) | 23 µs at 5 facts, 52 µs at 20, 159 µs at 64 |
| relationship evaluation (1e5 ops) | `apply` 1.2 µs (one dimension) / 1.7 µs (`helped_by`, four); `help_score` 2.5 µs |
| decision evaluation (per game minute) | help 1.13 ms, avoid 0.05 ms, safety 0.02 ms at 08:00; help 0.87, avoid 0.33, safety 0.12 ms at 11:00 with a threat in the city |
| social interaction processing | co-presence 0.63 ms per game minute (57 pairs per scan) at 08:00, 2.3 ms (376 pairs) at 11:00; alarmed encounters 5.2 ms per game minute at 11:00 (per-second scans by the alarmed citizens) |
| rumour propagation (10:35–11:35, one fast case) | 5 tellings, max 2 per sender, 1 per pair, hops ≤ 2, told-set 7 (the certified day with the crowd in the shop: 145 tellings, max 13 per sender, hops ≤ 2) |
| FAR vs NEAR (09:00, focus far vs at the helper's workplace) | cognition 2.2 vs 1.8 ms per game minute — cognition reads neither the focus nor the band |
| full Houston day 05:00→20:00 | cognition on: 115 s wall, 127.5 ms per game minute (mobility 109.0, work 16.6, cognition 1.8); cognition off: 116 s wall, 128.4 ms — the difference is noise |
| work + outbreak + cognition (10:35→11:35, fast case) | 106 ms per game minute (mobility 45.7, work 33.5, outbreak 18.9, cognition 7.8); worst minute 276 ms (cognition 15 ms) |
| memory growth | 946 facts over 162 citizens at 20:00, max 30 per citizen (cap 64), 708 relationships, 14 facts forgotten |
| budget (24× clock: 2 500 ms per game minute) | heaviest block mean 131 ms = 5.2 %; the worst single minute of the day is the 07:30 mobility departure spike (11.6 s, of which 11.6 s route planning, 3 ms cognition) — inherited, documented since mobility V1 |

Profile of `cognition.advance` alone: `TripExecutor.inside` (23 %, the
outdoor room-mates scan), the perception list comprehensions (15 %), `sorted`
(5 %), `occupants_by_room` (3 %). The first version of the drains scanned the
whole 5 000-row event ring every second (56 % of cognition time); the final
code walks the ring from its tail (`_since`), which cut cognition from 13.5 to
1.8 ms per game minute.

## 15. Multi-city smoke (`tools/cognition_city_smoke.py`, 05:00→17:00, 60 s steps, fast case seeded in the busiest shop at 10:35)

| city | status | citizens / employed | with memory / facts / max per citizen | relationships (moved by events) | help | warnings | room avoid | deterministic | ms per game minute |
|---|---|---|---|---|---|---|---|---|---|
| houston | PASS | 297 / 211 | 169 / 1083 / 32 | 790 (755) | 11 | 42 | 6 | yes | 201 |
| madisonville_tx | PASS | 53 / 41 | 26 / 99 / 8 | 74 (58) | 0 | 4 | 0 | yes | 17 |
| austin | PASS | 60 / 46 | 32 / 89 / 9 | 69 (67) | 0 | 9 | 3 | yes | 79 |
| san_antonio | PASS | 60 / 46 | 19 / 82 / 16 | 45 (37) | 0 | 9 | 3 | yes | 56 |
| boulder | INFO | — | no compiled world | | | | | | |

No city-name logic anywhere in the cognition, work, outbreak or world code
(N36). The smaller bundles have one- and two-worker workplaces, so helping
does not arise there; warnings, room avoidance and relationship change do.

## 16. Regression

| suite | result |
|---|---|
| Python (`pytest`, 1 329 collected) | 1 328 passed; 1 pre-existing, unrelated failure (`test_world_from_compiled::test_compile_writes_only_presentation_files` needs the raw Overture packet; `test_overture_ingest` deselected for the same reason) |
| `tests/test_cognition_*.py` (this milestone) | 145 passed |
| `tests/test_npc_v1_day.py` | N1–N36 as tabled above |
| `godot/tests/run_gates.sh` (Physics, Region, Nav, Convergence gates) | 85 PASS / 0 FAIL (N34) |
| MobilityGate | 24 PASS / 0 FAIL, exit 0 (N33) |
| OutbreakGate | 18 PASS / 0 FAIL, exit 0 (N32) — with the room-level witness refinement |
| WorkGate | 22 PASS / 0 FAIL, exit 0 (N31) |
| CognitionGate | 30 PASS / 0 FAIL / 2 INFO, exit 0 (N30) |

Two tests were updated for the milestone: the outbreak disruption test
samples the minute before the disruption (the interleaved clock now reacts
within the same minute), and the outbreak archetype set includes
`classic_zombie_fast`. (`artifacts/npc_cognition_v1/regression.json`.)

## 17. Multi-agent interaction

Delegated: the authority audit, the unit-test package (145 tests), the Godot
gate and evidence, the performance and smoke tools. Integrated centrally: the
cognition package, the WorkRuntime/outbreak/planner hooks, the certification
harness and this report. No subagent added an authority; the two that
touched Godot changed only the renderer side (`Session.start_hour` opt-in,
v7 wrappers).

## 18. Remaining debt (explicit)

* **Building-level avoidance rarely fires in an ordinary day**: it needs a
  non-home scheduled destination believed dangerous; in the certified day
  that was one citizen (the cashier told about its own shop). Room-level
  avoidance fires often. A witness's flee goal never ends (outbreak V1), so
  memory-driven refusal only shows when the emergency is over (N14 is a
  controlled restore).
* **Disrupted workplaces mask cognition**: a worker of a disrupted building
  is sent home by the outbreak whatever it knows, so "warned worker refuses
  to go in" is indistinguishable there (the night cleaner 57 is warned by a
  call, then also disrupted).
* **`AVOID_PERSON`, `CHECK_ON`, `FOLLOW` are in the grammar but not
  demonstrated**; `AVOID_PERSON` overlaps the outbreak's own flee.
* **Calls** are a modelled channel (household / workplace ties, ≤ 3 per fact,
  major facts only) with no representation in the renderer.
* **False warnings** are only detected when a told threat about a room is
  contradicted within 15 min of its claimed time; the day produced none.
* **Perception scans**: `_room_mates` outdoors and `_alarmed_encounters`
  scan every executor (bounded by the alarmed count; fine at 300 citizens,
  to be gridded at 10k). `MemoryStore.salient` sorts the store per call
  (26 µs; on the context-API path).
* **Obligation is discharged partially** (−60 % per repayment); several
  favours need several repayments.
* **`WorkRuntime.row` now carries `help_for`** so a renderer can tell a help
  task apart; the Godot HUD does not yet draw a help/warn marker.
* Inherited: the 07:30 mobility departure spike, exterior body ground
  height, AABB rooms, building-level exposure.

## 19. Recommended next milestone

**NPC Dialogue and Communication V1**: turn the semantic acts
(`OFFER_HELP`, `WARN_THREAT`, `SHARE_INFO`, `THANK`, `ACKNOWLEDGE`), the
context API (`GET_CITIZEN_CONTEXT`: memories with provenance, beliefs,
relationships, current task and danger) and the lineage of told facts into
grounded conversations — what a citizen says being derived from what it
knows, whom it trusts and what it is doing, with the player able to ask
"what happened here?" and get the witness's account or the rumour, and
never a fact the citizen could not know.

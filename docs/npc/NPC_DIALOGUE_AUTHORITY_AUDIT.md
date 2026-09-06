# NPC DIALOGUE AUTHORITY AUDIT — pre-milestone survey for ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1

Repo `/home/user/Asphodel`, branch `claude/asphodel-embodied-mobility-v1-6gl4a8`, HEAD `4b7ba1f`.
Read-only audit; every claim is a `file:line` at that SHA. Nothing was implemented here.

> **In-flight work.** While this audit was written, a parallel session was building
> the milestone in this worktree: `asphodel/dialogue/` appeared **untracked**
> (`acts.py`, `grounding.py`, `render.py`, `session.py`) alongside edits to tracked
> files, and landed as `9bce5cd` before the audit was filed. **All line numbers below
> are against HEAD `4b7ba1f` as commissioned** (`git show 4b7ba1f:<path>`), not the
> working tree or `9bce5cd`. Where that implementation and this audit disagree about
> an integration point, the committed code at `4b7ba1f` is the evidence cited here.

The predecessor milestone has shipped: `asphodel/cognition/` is tracked, the protocol
is **v7**, `save.py` carries a `"cognition"` block. Below: what dialogue builds on,
and what it must not duplicate.

---

## 1. THE COGNITION SURFACES DIALOGUE BUILDS ON

### 1.1 `_share` — the one social transmission path

`CognitionRuntime._share(sender, recipient, channel, bid, rid, only=None)`
(`cognition/runtime.py:531-598`) is **the only place in the repo where one citizen's
knowledge becomes another's**. In order: `_can_perceive` both ends (`:533-534`);
candidates from `only` or `_shareable(sender)` (`:535`, `:519-529` — `S.SHAREABLE`
minimum confidence, `hops >= S.MAX_HOPS`, decayed `effective()`, sorted
`-(salience*effective), fact_id`); the per-pair cooldown `S.PAIR_COOLDOWN_S`
(`:539-540`); duplicate suppression via the `told` set keyed
`(sender, recipient, origin_id)` and "the recipient is the origin witness"
(`:544-546`), plus a skip when the recipient already holds it **first-hand**
(`:548-551`); the sociability roll `S.share_roll` for every channel but `"call"`,
whose negative result is memoised into `told` so it is never re-rolled (`:554-556`).

The write (`:562-566`) is `rst.remember(..., source=M.TOLD, source_citizen=sender,
origin_witness=f.origin_witness, origin_id=f.origin_id, hops=f.hops+1,
confidence=S.told_confidence(...), t=f.t)` — **provenance, hop depth and the
original event time survive; the recipient's confidence is the sender's decayed
confidence rescaled by trust and suspicion.** Then a companion `WARNED_BY` fact
about the social act itself (`:569-570`, salience 0.5, distinct from the fact told);
recipient cache invalidation (`:567-568`); three events — `WARNING_SHARED`
(`:571-576`), `WARNING_RECEIVED` (`:579-587`, stamping `goal_before`,
`goal_building`, `danger_after`, `threshold`, `trust_in_sender`, `created`) and
`SOCIAL_ACTION` (`:589-591`); the `warned_by` rule on the recipient toward the
sender (`:592`) plus `told_threat` about the threat person scaled by received
confidence (`:593-594`); and **immediate action** —
`if f.kind in M.THREAT_KINDS: self._decide_avoid_one(recipient)` (`:595-596`), "a
warning is acted on at once, not next minute". It returns after **one** fact
(`:597`). Call sites: `_meet` (`:515-516`), `_share_burst` (`:613`, `:624`),
`_alarmed_encounters` (`:698`).

`_share_burst(witness, fact)` (`:600-625`) is shout + calls: everyone in the building,
walls included (`:605-608`, channel `"shout"`), or outdoor `_room_mates` (`:610`);
then calls to strong ties — `familiarity >= S.CALL_FAMILIARITY` or household/workplace
origin (`:616-617`), sorted `(-familiarity, other)` (`:618`), capped by
`S.MAX_CALLS_PER_FACT` per origin fact (`:620`, `:625`), only for
`salience >= S.CALL_SALIENCE` (`:615`). It fires from `_threat_memory` (`:455`). Calls
skip the sociability roll and reach citizens who are not co-present: **the only
non-co-present channel that exists.**

### 1.2 Encounters and perception

`_copresence()` (`:458-503`) every `COPRESENCE_INTERVAL_S = 300.0` (`:52`, scheduled
`:197-199`): indoors per building then per `_occupants(bid)` room bucket, pairing each
citizen with up to `PAIR_CAP = 6` ring-neighbours (`:55`, `:479-485`); outdoors a grid
hash of canonical positions at `OUTDOOR_RADIUS_M = 20.0` (`:51`, `:486-503`).
`_meet(a, b, bid, rid)` (`:505-516`) writes `WORKED_BESIDE`/`worked_beside` when both
are workers there (`:507-510`) else `MET`/`met`, symmetric memory and relationship
(`:511-513`), then `_share` **both ways** (`:515-516`) — the encounter primitive a
conversation is made of. `_room_mates(cid, bid, rid)` (`:227-244`) is who can see what
happens to `cid`: same room indoors (`:233-237`), else within `OUTDOOR_RADIUS_M`
(`:238-244`) — the audience test for shouts, `PERCEIVED` observers and
`citizen_context.people_nearby`; `_occupants(bid)` (`:216-225`) wraps
`occupants_by_room` behind a per-substep cache cleared at `:189`. `_can_perceive`
(`:246-248`) is `ex.override not in ("incapacitated","corpse","undead")`: **a dialogue
partner must pass it on both sides**, as `_share` does. `_alarmed_encounters()`
(`:683-699`) runs every second while `_alarmed` is non-empty (`:195-196`; refreshed
`:677-681` over `ALARM_S = 1800.0` `:64`) — a witness warning passers-by between scans.

### 1.3 Help decisions

`help_score(helper, beneficiary, problem, rel_override=None)` (`:702-717`) returns
`(score, components)` from personality `helpfulness`, relationship
`familiarity/affinity/obligation(×loyalty)/trust/-(fear+hostility)` and a per-kind
`HELP_COST` (`:59-60`); `rel_override=False` gives the no-history counterfactual
(`:780`). `_helpers_at(bid, w)` (`:719-733`) is availability: worker, `help_for < 0`,
not on break, off `HELP_COOLDOWN_S = 300.0` (`:57`), `_can_perceive`, no
`ex.override`, `state is DOING_ACTIVITY`, not a cashier with a live queue
(`:730-731`). `_decide_help()` (`:735-796`), once a game minute
(`DECISION_INTERVAL_S = 60.0` `:53`, `:200-202`, `:670-674`): per building with >= 2
workers it reads `w.problems(bid)` (`:744`), takes the best eligible helper above
`HELP_THRESHOLD = 0.40` (`:56`, `:769`) with a non-None `w.help_target(h, pr)`
(`:771-772`), capped at `HELP_MAX_PER_PAIR = 6` (`:58`, `:763`), and **`w.assist(h,
task_id, oid, ben)` is the action** (`:781`). It emits `HELP_DECIDED` with the
component breakdown, counterfactual and `would_help_without_history` (`:785-790`), a
`SOCIAL_ACTION` (`:791-792`), and parks the row in `pending_help` until `HELP_DONE`
(`:793`, consumed `:359-365`). **A complete offer-help pipeline missing only the
utterances**; ask/evaluate/accept-refuse is a split of `:768-781`, not a second scorer.

### 1.4 Context, lineage, and the four stores

* `citizen_context(cid, n_memories=8)` (`:943-985`) already is the dialogue input:
  location/band, task, `goal.to_dict()`, needs, health, personality, salient
  memories with `effective`, `people_nearby` with per-person relationship and
  `danger_of_person`, top relationships and beliefs, `perceived_danger`, `avoiding`,
  `avoid_rooms_here`, and the last 6 social events involving the citizen
  (`:958-960`). A dialogue turn needs no new global read. `lineage(fact_id)`
  (`:987-997`) is every `WARNING_RECEIVED` for the origin fact — the who-told-whom
  chain a conversation can cite.
* `memory.py`: `MemoryFact` (`:82-103`) — `fact_id, owner, kind, actor, target,
  building_id, room_id, object_id, t, source, source_citizen, origin_witness,
  origin_id, hops, confidence, salience, valence, count, last_t, detail`; sources
  `DIRECT/PARTICIPANT/TOLD` (`:53-55`); 20 kinds (`:26-50`); `THREAT_KINDS` (`:73`);
  `merge_key` (`:106-107`); `effective()` decaying on `half_life_s`, 2 h to 3 days
  (`:76-79`, `:109-112`); `first_hand()` (`:117-118`); `CAPACITY = 64`,
  `DURABLE_SALIENCE = 0.80`, `FORGET_BELOW = 0.05` (`:70-72`); `remember` merges
  equivalents and lets first-hand supersede hearsay (`:143-178`, esp. `:157-161`);
  `consolidate` (`:186-201`); `salient` (`:225-227`); `about(cid)` (`:221-223`) is the
  "what do I know about you" query. **A proposition is a `MemoryFact`, never prose**
  (`memory.py:5-7`).
* `beliefs.py`: `derive` (`:64-113`) recomputes everything from facts — noisy-OR
  `_combine` (`:56-61`), `HOP_DISCOUNT = 0.75` (`:26`, `:49-53`), `PLACE_SAFE`
  halving older danger evidence (`:70-73`, `:94`), a room->building aggregate
  (`:102-112`); readers `danger_of_room`/`danger_of_building`/`danger_of_person`
  (`:116-128`); `Belief` carries `evidence` fact ids, `first_hand` and
  `source_citizens` (`:30-46`) — the citable justification for an answer. Cached per
  citizen per game minute (`runtime.py:628-641`).
* `relationships.py`: `RULES` (`:56-74`) is the closed update table — `warned_by`
  (`:65`), `warning_confirmed` (`:66`), `false_warning` (`:67`),
  `helped_by`/`helped`/`saw_help`/`reciprocated` (`:61-64`), `told_threat` (`:73`);
  `PRIORS` household/workplace (`:76-79`, applied `runtime.py:153-177`); six bounded
  dims (`:18`); saturating `_sat` (`:82-87`); `apply` returns per-dim deltas
  (`:114-129`). **A dialogue outcome that changes a relationship is a new `RULES`
  entry applied through `CognitionRuntime.relate` (`runtime.py:275-293`)**, which
  already emits `RELATIONSHIP_CHANGED`/`TRUST_CHANGED`.
* `social.py`: the transmission bounds used above — `SHAREABLE` (`:35-36`, six
  kinds), `MAX_HOPS = 2`, `PAIR_COOLDOWN_S = 1800`, `CALL_FAMILIARITY = 0.55`,
  `CALL_SALIENCE = 0.85`, `MAX_CALLS_PER_FACT = 3`, `SHARE_ROLL_BASE = 0.55`
  (`:37-42`), `share_roll` (`:45-47`), `told_confidence` (`:50-53`) — plus the act
  vocabulary `HELP, WARN, SHARE_INFORMATION, CHECK_ON, AVOID_PERSON, AVOID_LOCATION,
  FOLLOW` with `UTTERANCE` labels and `THANK`/`ACKNOWLEDGE` (`:21-32`), whose
  docstring names this milestone: labels "a later dialogue milestone can verbalize"
  (`:6-8`). **Speech acts extend this vocabulary; they do not start a second one.**
* `personality.py`: five traits from `hash64(seed, cid, "trait", …)` (`:12`,
  `:27-35`), never stored. `sociability` gates telling (`social.py:47`), `suspicion`
  discounts it (`:53`), `risk_tolerance` sets the avoidance thresholds
  (`runtime.py:647-651`), `helpfulness`/`loyalty` weight `help_score` (`:713-714`).
  A refusal probability comes from these, hashed — there is no RNG.

---

## 2. WORK: WHERE A REQUEST BECOMES A REAL ACTION

`problems(bid)` (`smart/runtime.py:875-917`) is the observable problem list —
`unstaffed_queue`/`queue_overload` (`:885-894`), `station_failed` (`:896-903`),
`cleaning_workload`/`restock_workload` (`:905-916`) — each row naming the
`citizen_id` it is a problem *for*: the beneficiary of a request.
`help_target(helper, problem)` (`:919-957`) returns `(task_id, object_id)` or None,
already honouring the cognition room constraint through `_avoided` (`:926`,
`:452-455`): the feasibility check behind "yes, I can".

`assist(helper, task_id, object_id, beneficiary)` (`:959-996`) is **the one
execution path for an accepted request**: validates worker/task/`help_for` (`:966`),
object availability and the reservation ledger (`:969-979`), emits
`TASK_END(abandoned)` and `RESERVATION_RELEASED` for what is dropped (`:982-986`),
`_take` (`:987`), sets `a.help_for` (`:989`), emits `HELP_TASK` (`:991-992`),
`_begin_task` walks the helper (`:993`), and for `cover_station` moves the queue
(`:994-995`). It returns False rather than forcing. `HELP_TASKS`
(`smart/jobs.py:108-121`) — `cover_station`, `help_clean`, `help_restock`,
`repair_station` — is **the entire vocabulary of "things one citizen can do for
another"**; a request whose accept has no entry there has no execution and must be
refused, or the task added. `HELP_DONE` (`smart/runtime.py:659-664`) is consumed at
`cognition/runtime.py:342-365`: memories both ways, `helped_by`/`helped`,
`reciprocated` when obligation remains, bystander `SAW_HELP`, `HELP_COMPLETED`, a
`THANK` `SOCIAL_ACTION` and the helper cooldown.

Also: `context(cid)` (`:1084-1098`, docstring "for outbreak, dialogue…" `:1085`);
`occupants_by_room(bid)` (`:1100-1108`), the only room-granular who-is-with-whom;
`room_filter` (`:125`, read via `_avoided`) — belief-as-constraint needs no new hook.
`_interruption_reason` (`:320-331`) already maps `belief` and `social` goal sources to
`f"{source}:{kind}"` (`:325`); a dialogue-sourced goal outside that tuple is logged as
`shift_end` (`:327-331`).

---

## 3. PLANNER / EXECUTOR: WHAT A GOAL MAY BE

`SOURCE_BASE_PRIORITY` (`citizens/goals.py:28-36`): `idle 0.10, need 0.35,
social 0.45, schedule 0.55, belief 0.66, emergency 0.92, player 1.0`. **`"social"`
still has no producer** — dialogue is its natural owner, but at 0.45 it loses to any
schedule goal under the 0.05 `preempt_margin` hysteresis (`goals.py:104-118`).
Outbreak constants: `FLEE 0.92`, `HEALTH 0.80`, `DISRUPTION 0.78`, `UNDEAD 0.95`
(`outbreak/runtime.py:47-50`).

Producers: `goal_from_schedule` (`goals.py:129-154`); belief goals from
`_decide_avoid_one` (`cognition/runtime.py:864-868` — `DO_ACTIVITY(home,
activity="rest", source="belief", priority 0.66 + 0.12*danger)` through
`rt.push_goal`, recorded in `avoid_goals` `:869-870`, released by the
hold/fade/supersede test `:831-846` with `AVOID_HOLD_S = 4 h` `:61`, and declining to
push over an `emergency`/`health`/`disruption` active goal `:848-849`);
health/disruption/flee/undead from outbreak (`:246-255`, `:261-296`, `:312-337`,
`:450-453`). The one sanctioned mutation point is `CitizenRuntime.push_goal`
(`citizens/runtime.py:100-106`); `sync_schedule` (`:88-97`) replaces every
`source == "schedule"` goal each game minute, so a dialogue goal needs another source
and a re-issue cadence; `_reselect` (`:117-127`) replans only when the active goal id
changes.

> **A "request accepted -> real action" goes through `WorkRuntime.assist`
> (`smart/runtime.py:959-996`), never a new mover.** The body belongs to
> `TripExecutor`; the interior walk belongs to `WorkRuntime._walk` (`:367`).
> "Come here", "follow me", "take over my till" are either an existing `HELP_TASKS`
> entry through `assist` or a goal pushed to the citizen's own `GoalStack`.

---

## 4. OUTBREAK: WHAT MUST INTERRUPT A CONVERSATION

`_witnesses()` (`outbreak/runtime.py:515-561`) is the perception test — room-level
indoors via `_same_room` (`:504-513`, degrading to "the building is one room" when
work is off) and `THREAT_RADIUS_M` outdoors (`:534-536`, `:553-555`). A sighting
emits `THREAT_OBSERVED` (`:541-542`, `:559-560`) and calls `_flee` at once (`:544`,
`:546`, `:561`); `ATTACK` is emitted at `:494-496`. `_flee` (`:261-296`) drops all
`emergency` goals and pushes `FLEE` at 0.92 (`:292-294`), re-targeting away from a
threatened home (`:272-286`) and de-duplicating an in-flight identical flee
(`:289-291`). `_on_incapacitation` (`:203`) and `_on_reanimation` (`:235`) wipe goal
sources including `belief`; executor overrides are what `_can_perceive`
(`cognition/runtime.py:246-248`) and `_helpers_at` (`:727`) already screen on.

**Interrupt rules, all already expressed elsewhere:** a participant acquiring an
`emergency`/`health` active goal; any `ex.override` being set; a participant leaving
the room (`_room_mates`/`occupants_by_room` stop pairing them); `_can_perceive`
turning False. A conversation that survived a `FLEE` would be the first thing in this
codebase to outrank an emergency.

---

## 5. BRIDGE v7 AND GODOT: WHERE A PANEL AND A `TALK` COMMAND SLOT IN

`PROTOCOL_VERSION = 7` (`bridge/protocol.py:41`, history `:28-40`); `GET_COGNITION`/
`GET_CITIZEN_CONTEXT` at `:85-87` and in `Command.ALL` (`:89-99`);
`godot/scripts/sim_bridge.gd:23` pins the same constant — **a v8 bump is a
two-language, same-commit change.** Handlers: `_cmd_get_cognition`
(`bridge/session.py:347-352`, `since_seq` via `_opt_int`), `_cmd_get_citizen_context`
(`:354-362`, refusing when cognition is off, validating the citizen against
`mobility.execs`), `_cmd_interact_with` (`:405-413` — roster promotion only,
`orchestrator.py:1115-1127`; **not** a conversation). `START_WORLD` reads
`player_citizen`/`player_citizen_id` (`session.py:102-104`), validates it against the
bundle population (`:141-151`), seeds the survival inventory from that profile
(`:152-156`), stores `self.player_citizen` (`:188`) and echoes it (`:192`);
`_inject_player_location` (`:534-542`) and `SAVE` (`:550-551`) reuse it; `LOAD`
restores it from `game_identity` (`:572`); `cognition_enabled` rides the summary
(`:620`).

**A `TALK` command slots in exactly like `GET_CITIZEN_CONTEXT`**: a constant beside
it (`protocol.py:87`) plus `Command.ALL` (`:98`) and a version comment (`:38-40`); a
`_cmd_talk` beside `_cmd_get_citizen_context` (`session.py:354`) taking `citizen_id`
and the act, defaulting the speaker to `self.player_citizen`; an orchestrator
passthrough beside `citizen_context` (`orchestrator.py:343-344`); a `sim_bridge.gd`
wrapper beside `get_citizen_context` (`:224-233`).

Godot. `session.gd:9` `Session.citizen` is the player identity — a bundle
`citizens.json` record chosen at `city_select.gd:105-111`; its `citizen_id` is sent as
`player_citizen_id` (`isometric_world.gd:408-410`) and `Session.start_hour`
(`session.gd:14`) at `:413-414`: **that is how the player's citizen id is known
client-side**, the server's copy being `WorldSession.player_citizen`.
`_setup_interaction` (`isometric_world.gd:529-537`) wires `IsometricInteraction` to
`INTERACT_REACH` and `_gather_candidates` (`:544-599` — interior
occupants/fixtures/exit, else outdoor citizens from the live snapshot plus the nearest
building, each with a real id, never a node name). `_update_highlight` (`:511-526`)
resolves a target each frame and writes `_target_label.text = "%s   [E / click: %s]"`
from `describe` and `query_affordances` (`:522-525`). E-key flow: bound at `:142`;
`_unhandled_input` -> `interact()` (`:929-930`, mouse `:936-937`) ->
`resolve_target(true)` -> `execute_on` (`:621-637`), whose `CITIZEN, OCCUPANT` branch
today only calls `SimBridge.interact_with` and sets a status line (`:625-629`) —
**the single edit point for opening a dialogue panel.** In
`isometric_interaction.gd`: `resolve_target` (`:58-78`), `_pick_under_cursor`
(`:81-97`), `_nearest_within_radius` (`:107-121`), `query_affordances` (`:147-160`),
`describe` (`:164-179`); the `query_affordances` docstring (`:142-146`) already
reserves the shape for "a later Semantic-Action layer … (ASK / INFORM / GIVE /
RETRIEVE / …) without changing any caller" — **dialogue verbs belong there**, and
`describe`'s `"Citizen %d"` (`:169-171`) is where a name would appear. HUD
(`isometric_world.gd:750-793`): player line from `Session.citizen["name"]` (`:755`),
`_target_label` bottom-centre (`:768-778`), `_status_label` below it (`:780-790`, via
`_set_status` `:830-832`), hint text `:764-765`; a dialogue panel is another
`CanvasLayer` child built here. `sim_bridge.gd` v7 wrappers: `get_cognition`
(`:212-221`, `since_seq` drain), `get_citizen_context` (`:224-233`), caches
`last_cognition`/`last_context` (`:60-61`), `cognition_enabled` from `START_WORLD`
(`:113`) and the summary (`:356`). No Godot script reads cognition beyond these yet.

---

## 6. PERSISTENCE: WHERE A `dialogue` BLOCK GOES

`SAVE_VERSION = 3` (`save.py:42`). `world_state` writes sibling nullable blocks
`"mobility"`/`"outbreak"`/`"work"`/`"cognition"`/`"survival"` (`:293-302`);
`load_world` constructs nothing and parks them as `_pending_*` (`:330-333`;
`_pending_cognition_state` declared `orchestrator.py:167-168`). Each `enable_*`
prefers the pending state (`enable_work` `orchestrator.py:299-314`;
`enable_cognition` `:320-338`, whose restore returns *before* `init_priors`, so
nothing is re-rolled). Bridge LOAD order is strictly mobility -> outbreak -> work ->
cognition, each guarded on `world.mobility is not None`, inside a bare
`except Exception: pass` (`session.py:578-591`) — **a restore must be proven by a
test, not by the session.**

A `"dialogue"` block follows exactly: `world.dialogue` + `_pending_dialogue_state`; a
`"dialogue"` key beside `"cognition"` (`save.py:299`), parked at `:333`; an
`enable_dialogue()` requiring cognition as `enable_cognition` requires mobility
(`orchestrator.py:326-327`); a LOAD step after cognition (`session.py:587-589`); a
per-block `{"version": …}` field (`cognition/runtime.py:1020`,
`smart/runtime.py:1139`). Cognition persists its whole event ring and every social
bookkeeping set (`cognition/runtime.py:1019-1038`) — dialogue sessions and
transcripts must be persisted the same way or byte-identical save/load breaks.
Advance order is mobility, outbreak, work, cognition in interleaved 1 s substeps
(`orchestrator.py:388-410`); dialogue ticks after cognition or not at all.

---

## 7. NAMES: WHAT A RENDERER CAN ACTUALLY USE

**There is no display name anywhere in the Python simulation.** `CitizenProfile`
(`citizen.py:257-291`) carries `citizen_id, city, age, age_band, occupation, shift`,
districts/zones, schedule, inventory, spawn state and the resolved building/xy refs —
**no name field**; `summary()` prints `#id` and the occupation (`:292-300`).
`bundle_population.load_bundle_population` reads the bundle `citizens.json` and
**never copies `"name"`** into the profile it builds (`:158-192`); the only `name` it
touches is the *city* name from `meta.json` (`:155`). `roster.py`'s `RosterRecord`
stores the profile, not a name.

Names exist only in the **bake**: `osm_city/citizens.py:_name_for` (`:55-58`)
composes `_FIRST` × `_LAST` (`:39-43`) deterministically from the citizen id and
writes it as the bundle row's `"name"` (`:162`) — e.g.
`godot/bundles/houston/citizens.json:36 "name": "Maria Diallo"`. Client-side,
`BundleLoader.load_citizens` (`bundle_loader.gd:241-259`) requires
`name`/`occupation`/`spawn_hour` and returns the raw rows; `city_select.gd:105-111`
puts one in `Session.citizen`; `character_screen.gd:30` and `isometric_world.gd:755`
render **the player's** name from it.

**Precisely:** a renderer today has the player's name via `Session.citizen.name` in
Godot, and for any NPC only `citizen_id` (+ `occupation` from the profile). To name
an NPC, either Godot loads the bundle's `citizens.json` itself and indexes by
`citizen_id` (ids *are* the array indices — `bundle_population.py:158`
`for cid, c in enumerate(raw)`), or the bundle name is threaded into `CitizenProfile`
and served over the wire. A Python-side renderer must not invent names;
`isometric_interaction.describe` (`:164-179`) is the one place a client-side name
replaces `"Citizen %d"`.

---

## 8. RISKS, AND THE RECOMMENDED INTEGRATION POINTS

### (a) Reading world truth instead of a citizen's store

| tempting global | file:line | why it is wrong | read instead |
|---|---|---|---|
| `outbreak.records` | `outbreak/runtime.py:73` | omniscient health; `citizen_context` reports only the **subject's own** (`cognition/runtime.py:971`) | the asker's threat facts and `danger_of_person` (`beliefs.py:126-128`) |
| `work.activities` of others | `smart/runtime.py:112` | what a coworker is doing is knowledge, not air | `_room_mates` (`cognition/runtime.py:227-244`); `COWORKER_INTERRUPTED`/`STATION_FAILED` memories (`:314-337`) |
| `work.queues` / `work.employment` | `:113`, `:110` | building-wide truth | `problems(bid)` **plus** the co-presence gate in `_helpers_at` (`:719-733`) |
| `mobility.execs[*].pos` for anyone | `embodied/runtime.py:100` | positions are body authority, not perception | `_room_mates`, `_occupants`, `OUTDOOR_RADIUS_M` |
| `mobility.citizens[*].active_goal`/`needs` | `:99` | another citizen's plan is private | ask: an answer generated from the **answerer's** `citizen_context` |
| `cognition.memories[other]` | `cognition/runtime.py:88` | reading another store is telepathy | `_share` (`:531-598`), which writes with provenance |
| `cognition.rels` for a pair the speaker is not in | `:89` | views are directional and private (`relationships.py:3-5`) | `self.rels.get(speaker, other)` only |
| `outbreak._known_threats` | `outbreak/runtime.py:86` | a flee-rule index, not a belief | `beliefs()` / `avoid_rooms` (`:628-641`, `:653-667`) |

The layer's own statement — "The world knows everything; no citizen does"
(`cognition/runtime.py:16`) — is the acceptance test for every dialogue read.

### (b)-(e) The four duplications, and two more hazards

* **A second transmission path.** Writing a fact into another citizen's
  `MemoryStore` outside `_share` (`:531-598`) duplicates provenance, `told`,
  `pair_last_s`, `calls`, `MAX_HOPS`, `told_confidence`, the `WARNED_BY` companion
  fact, the `WARNING_SHARED`/`WARNING_RECEIVED` pair and the immediate
  `_decide_avoid_one`. Two paths means `lineage()` (`:987-997`) stops being complete
  and `false_warning` (`:923-928`) can fire against a telling that never happened.
* **A second help authority.** Scoring helpers in the dialogue layer duplicates
  `help_score` (`:702-717`), `_helpers_at` (`:719-733`), `HELP_THRESHOLD`,
  `help_cooldown` and `help_pairs`; starting a task there duplicates `assist`
  (`smart/runtime.py:959-996`) and desynchronises `a.help_for`, the reservation
  ledger and the `HELP_DONE` -> `HELP_COMPLETED`/`THANK` chain
  (`cognition/runtime.py:342-365`).
* **Moving citizens.** A conversation that walks people together is a second body
  controller. `TripExecutor` owns the body; `WorkRuntime._walk`
  (`smart/runtime.py:367`) is the only interior mover; a new `EmbodimentState` member
  breaks Python and GDScript assertions at once. Conversation is a *state a
  co-present pair is in*, expressed by memories, events and at most a goal.
* **RNG.** The simulation has none; every derived choice is a hash
  (`personality.py:29-30`, `social.py:45-47`). A refusal roll, topic pick or turn
  order must be `hash64(seed, speaker, listener, act, tick)`.
* **The event ring.** `MAX_EVENTS = 5000` (`cognition/runtime.py:50`), trimmed
  `:145-146`, drained by `since_seq` (`:1009-1016`) and **persisted whole** (`:1037`)
  — every new event kind enters the byte-identical save/load tests.

### Recommended integration points

1. **`_share` routed through a dialogue transmit.** Keep `_share` (`:531-598`) as
   the memory-write authority and give it a verbalization seam: the dialogue layer
   produces the act and utterance, then **calls back into cognition** for the write,
   so `told`/`pair_last_s`/`calls`/hops/`WARNING_SHARED`/`_decide_avoid_one` stay in
   one place. The existing `utterance=` fields on `WARNING_SHARED` (`:575`),
   `WARNING_RECEIVED` (`:587`) and `SOCIAL_ACTION` (`:589-591`) are the attachment
   points; `S.UTTERANCE` (`social.py:29-32`) is the vocabulary to extend.
2. **`_decide_help` split into ask / evaluate / accept-refuse.** `:768` (score) is
   the request, `:769-772` (threshold + `help_target`) the evaluation, `:781`
   (`w.assist`) the accept; a below-threshold or `help_target is None` outcome is the
   refusal and already carries its reason. Emit acts around those three lines.
3. **A `TALK` bridge command** at protocol v8, shaped like `_cmd_get_citizen_context`
   (`session.py:354-362`), defaulting the speaker to `self.player_citizen` (`:188`),
   reached from the `CITIZEN, OCCUPANT` branch of `execute_on`
   (`isometric_world.gd:625-629`) with the verb published through
   `query_affordances` (`isometric_interaction.gd:147-160`).
4. **`World.enable_dialogue`** beside `enable_cognition` (`orchestrator.py:320-338`),
   requiring cognition, preferring `_pending_dialogue_state`, ticked after cognition
   in `_advance_runtimes` (`:400-410`), snapshotted like `cognition_snapshot`
   (`:340-341`), saved beside `"cognition"` (`save.py:299`).
5. **Grounding reads one surface.** `citizen_context` (`:943-985`) plus
   `MemoryStore.about(cid)` (`memory.py:221-223`) and `lineage` (`:987-997`) suffice
   to answer, to cite evidence (`Belief.evidence`, `beliefs.py:34`) and to refuse
   honestly. A grounding validator should assert that every proposition in a reply
   resolves to a `fact_id` in the **speaker's** store, and that no field of the reply
   came from a global in the table in §8a.

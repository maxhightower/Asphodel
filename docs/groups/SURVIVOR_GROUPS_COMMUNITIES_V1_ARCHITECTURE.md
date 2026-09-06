# ASPHODEL — Survivor Groups & Communities v1 — Architecture

A persistent survivor-group social layer built **from citizens who remain
individuals**. Groups emerge from real cooperation, keep membership and a
shelter, divide responsibilities, share information without becoming a hive
mind, admit or refuse outsiders, act collectively against danger, and persist
through save/load and LOD.

## 1. The two hard rules

1. **The group never replaces the citizen.** Every citizen still owns its
   perception, memory, beliefs, relationships, goals, dialogue, movement and
   work. The group holds only *social* state (identity, membership, shelter,
   objectives, roles, a shared record, decisions). It moves nobody and writes
   no belief. `GroupRuntime` reads cognition/relationships/mobility/work to
   decide, then acts only by **pushing a goal** into a citizen or **speaking**
   through Dialogue V1 — the citizen decides and executes.
2. **Group knowledge may never bypass individual epistemic channels.** A
   group-relevant fact reaches a member only through cognition's own
   `receive_fact` (via `dialogue.warn`), which preserves provenance, told
   confidence and origin witness. The group's shared record holds only facts a
   member deliberately communicated, with their lineage; it is not a channel
   into anyone's memory. An uncontacted member stays uninformed.

## 2. Authority census

| authority | owner | groups layer |
|---|---|---|
| identity, schedules, bodies, movement | citizen / mobility | reads position/band; pushes a `group`-source goal |
| perception, memory, beliefs, relationships, personality | `CognitionRuntime` | reads for formation/roles/shelter/admission; transmits only via `receive_fact` |
| grounded conversation | `DialogueRuntime` | reuses `warn` / `say` / `_start` for warnings, role requests, admission |
| rooms, Smart Objects, work tasks | `WorkRuntime` | a supply run reads `registry`/`with_caps('stock')` and `set_object_state` |
| health, threats, flee | `OutbreakRuntime` | threats drive the shared danger that seeds formation and the collective response |
| **group identity, membership, shelter, objectives, roles, decisions** | **`GroupRuntime` (new)** | the only new authority |
| world clock | `World.advance_seconds` | `groups.advance(step)` runs last in each 1 s substep |
| save/load | `save.py` | a `groups` block, restored after cognition/dialogue |

`GroupRuntime.advance` runs **after** dialogue in `_advance_runtimes`
(`orchestrator.py`), so a group sees this second's new perception and
conversation and pushes its effects into the next second — the same
one-substep latency every cross-runtime effect uses.

## 3. Group state (structured, `groups/model.py`)

`SurvivorGroup`: stable `group_id`, `created_s`, `founders`, `members`
(cid→state) with a `membership_history` of caused transitions, `shelter_*`
(building/room/node) + `shelter_history`, `objectives`, `roles`, `coordinator`,
`influence`, `shared_record` (provenance-preserving `GroupFact`s),
`applications`, `decisions`, `supplies`, `threat_state`. Membership states:
CANDIDATE / INVITED / PROVISIONAL / MEMBER / DEPARTED / EXPELLED. Everything
round-trips through `to_state`/`from_state` for byte-identical save/load.

## 4. Formation (§2, §7) — emergent, never seeded

`_scan_formation` is **edge-driven**: for each ungrouped citizen it reads its
own strong relationship edges (`rels.of`, O(degree) — never an all-pairs scan)
and tries to close a mutually-bonded cluster of ≥3 whose pairs each clear
familiarity ≥ 0.30, trust ≥ 0.45, low hostility and a combined bond. A group
forms only with a **traceable cause** (`_cause`): shared household/workplace,
repeated help (obligation), mutual trust, or shared first-hand danger. The
formed event records the cause. The certification builds that cause through
real mutual aid and fleeing-together (the `helped_by` / `fled_with`
relationship rules) and then lets the scan fire; the GQ1 counterfactual removes
the cooperation and the group does not form.

## 5. Shelter (§9, §10) — from member knowledge only

`select_shelter` aggregates candidate buildings from each member's *own*
`node_meta` (home, workplace, visited/told places) — never a citywide scan.
Each candidate is scored by how many members know it, whether it is a
defensible member home, believed safety (member danger beliefs), and capacity.
A bounded group decision records member preferences. On selection the group
**communicates the address** (adds the entrance node to each member's
`node_meta`) so a member told where to shelter can navigate to and enter a
building it did not previously know — the epistemic "shelter address". Each
member gets a `REACH_SHELTER` objective, realized as a `group`-source hold
goal that both travels there and keeps them regrouped. GQ2 removes the
proposer's knowledge of the winning shelter and it can no longer be selected.

## 6. Objectives → individual goals (§11, §12)

Objective grammar: REGROUP, REACH_SHELTER, MAINTAIN_SHELTER, WATCH_ENTRANCE,
SEEK_SUPPLIES, HELP_MEMBER, LOCATE_MEMBER, WARN_GROUP, EVACUATE,
ADMIT_OR_REFUSE_PERSON. A shared objective becomes a real `Goal(source="group",
priority 0.62)` pushed with `push_goal` — above a routine schedule, **below**
belief-avoidance, health and emergency, so a citizen's own survival always
overrides a group task (§30). The group never teleports a consequence.

## 7. Roles (§13–§20)

Three demonstrated roles — coordinator (highest emergent influence at
formation), guard (holds a real shelter entrance, warns the group and abandons
the post under a fresh threat), scavenger (leaves for a known supply source).
`_role_fit` weighs availability, influence/trust, work history, personality and
risk; the request is a real Dialogue V1 exchange (`ASSIGN_ROLE` → `ACCEPT` /
`REFUSE`). `_role_decision` lets the member refuse for itself (a frightened or
unwell member declines a dangerous role — GQ5). An accepted role creates a real
goal/action; a refused one creates none.

## 8. Supplies (§26, §27)

`check_supplies` detects a shortage and assigns a scavenger through the role
path. `_supply_source` picks a shop the scavenger **knows** (its `node_meta`)
holding a stocked Smart Object — never a citywide best-shelf query. The
scavenger travels there, decrements the object's `stock` via `set_object_state`,
returns, and the group's `supplies` rise. Events: SUPPLY_NEED /
SUPPLY_RUN_ASSIGNED / SUPPLY_ACQUIRED / SUPPLY_RETURNED.

## 9. Group knowledge & warnings (§23, §24)

`warn_group` records the reported threat in the shared record (origin witness,
source, confidence) and tells each **co-present** member through
`dialogue.warn` → `receive_fact`. Members not co-present are left uninformed
and listed as `uncontacted`. GQ4 removes the warning and those members do not
perform the collective response.

## 10. Admission, decisions, departure (§18–§22, §31)

`request_admission` collects a vote from each member that can assess the
outsider, grounded in that member's own knowledge (known threat blocks;
trust/affinity/obligation support), weighted by influence, resolved by the
coordinator within capacity. Acceptance sets PROVISIONAL membership; refusal
preserves non-membership and cools the outsider's regard (`refused_by`). GQ3
removes the outsider's helpful history and the decision flips. `_decide` is the
bounded decision protocol (proposal, influence-weighted preferences, recorded
dissent). A member whose trust in the group collapses departs (`MEMBER_LEFT`,
GQ6); a member known by another to have harmed the group can be expelled.

## 11. Threat response (§29, §30)

A guard or member that perceives a fresh first-hand threat warns the group and
abandons its post; `evacuate` drops the group holds and lets each member's own
flee/avoidance take over — a coordinated response that still runs through
individual knowledge and goals.

## 12. Bridge & Godot (§34, §40)

Protocol **v9**: `GET_GROUPS` (snapshot + events) and `GROUP_QUERY`
(membership / where / a bounded player ask-to-join). `START_WORLD` enables
groups with dialogue; LOAD restores them. The Godot client (v9) reads the group
row merged onto each mobility citizen and renders a bounded group panel; the
live gate demonstrates formation, regrouping, a role, a guard, a supply run,
and an admission with machine-readable group snapshots.

## 13. LOD & performance (§35, §42)

`GroupRuntime` keeps no band-specific state, so promoting a member to PHYSICAL
and demoting it leaves group/membership/role state identical to a control copy.
Formation is edge-indexed and timer-gated (scan ≤ every two minutes); objective
processing touches only members; group knowledge reuses the single dialogue
transmission path — no O(N²) matching, no duplicated rumor propagation.

## 14. Out of scope (§46)

No faction diplomacy/wars, base building, crafting, deep inventory/economy,
politics/elections, romance, or Rust. The focus is the causal chain:
cooperate → form → shelter → roles → share → admit/refuse → act collectively.

## 15. File map

| area | file |
|---|---|
| structured group state | `asphodel/groups/model.py` |
| GroupRuntime (formation, membership, shelter, roles, supply, knowledge, admission, decisions, threat, save) | `asphodel/groups/runtime.py` |
| `group` goal source | `asphodel/citizens/goals.py` |
| group speech acts + render | `asphodel/dialogue/acts.py`, `render.py` |
| world enable/advance/snapshot, save block | `asphodel/orchestrator.py`, `asphodel/save.py` |
| bridge v9 | `asphodel/bridge/protocol.py`, `session.py`; `godot/scripts/sim_bridge.gd` |
| certification day (G1–G54, GQ1–GQ6) | `tests/test_survivor_groups_v1_day.py` |
| authority audit | `docs/groups/SURVIVOR_GROUPS_AUTHORITY_AUDIT.md` |

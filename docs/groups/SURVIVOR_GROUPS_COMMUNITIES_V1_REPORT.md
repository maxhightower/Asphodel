# ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 — Report

**Verdict: ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1: PASS**

## 1. Provenance

| | |
|---|---|
| starting SHA | `83bab53` (certified `ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1: PASS`) |
| merge base with `main` | `bee2f18a1827` |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` |
| certification SHA | the commit whose code produced every artifact in `artifacts/survivor_groups_v1/` |
| final SHA | the commit following the certification SHA (this stamp) |

Every change sits on the certified dialogue spine; nothing was branched from an
experimental line.

## 2. What this milestone is

A persistent survivor-group social layer over citizens who remain individuals.
Groups **emerge** from real cooperation, keep membership and a shelter chosen
from places their members actually know, divide real responsibilities through
dialogue and cognition, share information without becoming a hive mind, admit or
refuse outsiders, act collectively against danger, and persist through save/load
and LOD. The design is in `SURVIVOR_GROUPS_COMMUNITIES_V1_ARCHITECTURE.md`; the
authority census in `SURVIVOR_GROUPS_AUTHORITY_AUDIT.md`.

## 3. The two hard rules, enforced structurally

* **The group never replaces the citizen.** `GroupRuntime` holds only social
  state; it moves a member only by pushing a `group`-source goal (priority 0.62,
  below belief/health/emergency, so individual survival always overrides), and
  speaks only through Dialogue V1. Every member keeps its own memory store,
  beliefs, relationships and goal stack.
* **No hive mind.** A group-relevant fact reaches a member only through
  cognition's `receive_fact` (via `dialogue.warn`), preserving origin witness,
  told confidence and hops. The shared record holds only deliberately
  communicated facts, with provenance. An uncontacted member stays uninformed.

## 4. The certified causal chain

The certified run drives one group through its whole life on the `houston`
bundle and records every causal link (`artifacts/survivor_groups_v1/one_day_trace.json`):

1. **Cooperation, then formation.** Citizens **42, 87, 117** share a workplace,
   help each other, and flee shared danger together, building mutual familiarity,
   trust and obligation. At **t = 7800 s** the edge-driven scan closes the bonded
   triangle and `group:1` forms, with the cause recorded verbatim:
   `workplace:42-87; helped:42-87; trust:42-87; workplace:42-117; helped:42-117; trust:42-117`.
   No group existed before the cooperation (G4); the formation event is timestamped
   mid-run.
2. **Shelter from member knowledge.** The group scores candidate buildings drawn
   only from members' own `node_meta` and selects **building 6353** (a defensible
   member home, `ent:6353`) out of **7** member-known proposals. The address is
   communicated to every member, and each takes a `REACH_SHELTER` `group`-source
   goal (priority 0.62) — realized as a real individual `Goal`
   (`do_activity → ent:6353`). All three physically regroup and enter the shelter.
3. **Roles through dialogue.** Coordinator **117** (highest emergent influence),
   guard **87** (accepts `WATCH_ENTRANCE`, score 0.898, and holds the real
   entrance post), and scavenger **42** (accepts, score 0.569) are assigned via
   real Dialogue V1 `ASSIGN_ROLE → ACCEPT` exchanges.
4. **Supply run through Smart Objects.** A shortage is detected; scavenger **42**
   travels to a **known** shop (**building 2318**), uses the stocked Smart Object
   `so:2318:1` via `set_object_state`, and returns — group `food` rises to **3.0**.
5. **Grounded admission.** Outsider **0** requests admission; each member votes
   from its **own** knowledge (`42 → 0.427 known_helpful`, `87`/`117 → stranger`),
   the coordinator resolves within capacity, and the outsider is admitted
   (`aggregate 0.145`, `group_agrees`).
6. **Warning through legitimate channels.** A threat warning reaches only the
   **co-present** member **117** through `dialogue.warn → receive_fact`; members
   **0, 42** are left uncontacted and stay uninformed (G8, G32).
7. **Collective response, individual override, departure.** An evacuation moves
   **4** members collectively out of 6353; a frightened member refuses a dangerous
   role (survival overrides the group task); and member **87**, its trust in the
   group collapsed, voluntarily leaves at **t = 36600 s** (`MEMBER_LEFT`, cause
   `lost_trust`).


## 5. Counterfactuals (§38)

Each counterfactual re-runs the day with exactly one cause removed and shows the
outcome flip (§38, §50):

| # | cause removed | with cause | without cause | flips |
|---|---|---|---|---|
| **GQ1** | cooperation/shared history | trio forms `group:1` | **0 groups formed**, trio ungrouped | ✅ |
| **GQ2** | proposer's knowledge of shelter 6353 | shelter **6353** | shelter **7928** (next member-known) | ✅ |
| **GQ3** | outsider's helpful history | admitted (`aggregate 0.606`) | **refused** (`insufficient_trust`, 0.0) | ✅ |
| **GQ4** | the warning | co-present **117** informed | uncontacted members stay **uninformed** | ✅ |
| **GQ5** | member's calm state (frightened) | accepts the role | **refuses** (`too_dangerous`) | ✅ |
| **GQ6** | member's trust in the group | stays a member | **leaves** (`lost_trust`) | ✅ |

Remove the shared history and the group does not form. Remove knowledge of the
shelter and it cannot be selected. Remove the warning and uninformed members do
not react. Change the stranger's known history and the admission decision flips.
The causal chain is provable by removal — the certification bar is met.


## 6. Save/load, LOD, performance, multi-city, regression

**Save/load (§36) — 8 moments, byte-identical.** The day captures the world at
`before_formation`, `after_formation`, `during_shelter`, `role_assignment`,
`mid_supply_run`, `admission_decision`, `threat_response` and `after_departure`;
each round-trips through `to_state`/`from_state` and reloads to a **byte-identical**
group state (formation, shelter, roles, supplies, membership and the admission
decision all survive).

**LOD (§35).** Promoting member 0 to `PHYSICAL` and demoting it back leaves
group, membership and role state **identical to a control copy**
(`group_same_while_physical`, `group_same_after_demotion`, `world_same_after_demotion`
all true) — the group layer keeps no band-specific state.

**Performance (§42)** (`performance.json`, houston, population 297). `groups.advance`
costs **1.47 ms per game-minute** in a normal window and **1.37 ms** in the
outbreak window; the edge-indexed formation scan medians **2.29 ms** and runs at
most once every 120 s. The worst case measured — two simultaneous groups — is
**23.69 ms per game-minute = 0.95 % of the 2500 ms real-time budget**. The layer
is a small fraction of the frame; there is no O(N²) matching (formation is
edge-driven) and group knowledge reuses the single dialogue transmission path.

**Multiple groups (§43).** The performance run forms two independent groups
(`group:1` = [42, 87, 117], `group:2` = [120, 129, 225]) that coexist with
separate membership, shelter and role state; per-group cost is linear.

**Multi-city (§44)** (`city_smoke.json`, seed 0, 120-minute warm-up). Overall
**PASS**: `houston`, `madisonville_tx`, `austin`, `san_antonio` each PASS —
a group forms from real cooperation, shelters in a **member-known** building,
keeps its membership through save/load, and **rebuilds identically on replay** —
and `boulder` is INFO (no compiled world). The identical driver runs every city;
there is no city-name logic anywhere in the groups package (G54).

**Regression (§39, G46–G53).** Every gate re-run on this branch:
| gate | check | result |
|---|---|---|
| G46 | live GroupGate (bridge v9) | **PASS** — 12 checks, 0 fail |
| G47 | Dialogue V1 gate under groups | **PASS** — 22/0 |
| G48 | Cognition gate | **PASS** — 30/0 |
| G49 | Work gate | **PASS** — 22/0 |
| G50 | Outbreak gate | **PASS** — 18/0 |
| G51 | Mobility gate | **PASS** — 24/0 |
| G52 | Godot run_gates (Physics/Region/Nav/Convergence) | **PASS** — 85/0 across 4 scenes |
| G53 | Multi-city smoke | **PASS** — houston/madisonville_tx/austin/san_antonio PASS, boulder INFO |
| — | Full Python suite (1574 tests) | **PASS** — 1573 passed; the one deselected/failing test is the pre-existing Overture packet dependency, unrelated to this layer |

The one pre-existing repository failure (`test_overture_ingest`, unrelated to this
layer) is deselected exactly as the dialogue milestone recorded it.

## 7. Certification table (G1–G54)

The machine-readable table is `artifacts/survivor_groups_v1/certification_table.md`
and the full trace `artifacts/survivor_groups_v1/one_day_trace.json`.

## 8. Remaining debt and next milestone

Nothing in the survivor-groups scope is left unproven: formation, membership,
shelter, roles, supplies, admission, decisions, warnings, collective response,
departure, save/load (8 moments, byte-identical), LOD, multiple groups and the
multi-city smoke all pass, and every counterfactual flips. The one pre-existing
repository failure (an Overture ingest test unrelated to this layer) is untouched
and out of scope here.

Deliberately **out of scope** (§46) and deferred: faction diplomacy/wars, base
building, crafting, deep inventory/economy, politics, romance, Rust. The natural
next milestone builds survival **resources and routines** on this social spine —
groups that ration the supplies they now gather and run recurring community
routines — without reopening any of the authority boundaries proven here.

**ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1: PASS**

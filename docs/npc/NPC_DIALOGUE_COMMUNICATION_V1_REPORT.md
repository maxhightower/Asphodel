# ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 — Report

**Verdict: ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1: PASS**

## 1. Provenance

| | |
|---|---|
| starting SHA | `a1ec5ed` (the certification SHA of `ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1: PASS`) |
| merge base with `main` | `bee2f18a1827` |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` |
| certification SHA | the commit whose code every artifact in `artifacts/npc_dialogue_v1/` was produced with |
| final SHA | the commit following the certification SHA (this stamp only) |

Every change sits on the certified cognition spine; nothing was branched from an
experimental line.

## 2. What this milestone is

Dialogue turns the existing cognition system into grounded conversation.
Citizens ask, answer, warn, request, refuse, agree, thank and clarify — and a
citizen **never states as fact anything it does not actually know or believe.**
The dialogue layer sits on top of cognition and holds no handle to global world
truth; what a citizen says comes only from its own perception, memory, beliefs,
relationships, goals and context, plus what the interlocutor supplies.

The design is documented in `NPC_DIALOGUE_COMMUNICATION_V1_ARCHITECTURE.md`; the
authority census in `NPC_DIALOGUE_AUTHORITY_AUDIT.md`.

## 3. The PASS standard (§45)

> Ask two citizens the same question. The one who knows can answer. The one who
> does not know cannot. Tell the second citizen, and only then can their
> knowledge and subsequent behaviour change.

In the certification day (busiest Houston shop, fast-onset threat):

* **The witness** (citizen 19) is asked what happened and answers first-hand:
  *"I saw citizen 222 attacked citizen 8 in room 0 of building 15873, just now."*
  — `DIRECT_OBSERVATION`, confidence 1.0, hops 0.
* **A citizen told by a call** (citizen 227, told by 169) answers second-hand,
  naming its source: *"citizen 169 told me citizen 222 attacked citizen 8 in
  room 0 of building 15873, just now."* — `SECOND_HAND`, source 169, hops 1.
* **An uninformed citizen** (citizen 0) asked the same question answers *"I don't
  know."* — a genuine `UNKNOWN`, not a fabricated guess.
* The real call to citizen 227 is the telling: **after** it, 227's danger belief
  for the shop rises to 0.57 and it would avoid the attacked room — knowledge and
  behaviour change only after being told, and the Q4 counterfactual (below) shows
  that with the call removed, 227 learns nothing and avoids nothing.

## 4. Scenarios (§31–§33)

* **Scenario A — the epistemic threat conversation.** Witnesses warn over
  shouts, warnings in passing and sequenced calls (GREET / WARN / ASK_LOCATION /
  ANSWER / THANK / END). Asked the same questions, a direct witness answers
  first-hand, a told citizen second-hand naming its source, a two-hop holder as
  hearsay with the origin witness preserved, and an ignorant citizen "I don't
  know". Every spoken proposition is grounded in the speaker's own store.
* **Scenario B — the actionable work conversation.** A coworker with a visible
  problem asks the co-present coworker it knows best; that one accepts or refuses
  through cognition's help score. An acceptance becomes a real `WorkRuntime` help
  task and completes when the smart object's state actually changes; a refusal
  creates no task, is remembered as `REFUSED_BY`, and moves the relationship.
* **Scenario C — the player interaction.** The player (bridge `World.talk`)
  greets a co-present witness, asks what happened, where, asks for help, says
  goodbye; a worker asks an uninformed coworker the same question and hears "I
  don't know"; addressing a citizen who is not co-present is refused for
  distance; and a live conversation is interrupted the moment a participant
  perceives a fresh threat.

## 5. Counterfactuals (§34)

| | question | result |
|---|---|---|
| Q1 | erase the witness's threat memory | it can no longer answer — "I don't know" |
| Q2 | direct vs. second-hand | the witness says "I saw…"; the told citizen says "X told me…" |
| Q3 | reset the helper's relationship to a stranger | the same request is refused (low trust), no help task runs |
| Q4 | remove the warning conversation | the told citizen never learns and avoids nothing |
| Q5 | acceptance path only | with the real relationship the request is accepted and a help task runs |

Each is produced from a restored world or an erased memory, not by inspecting
global truth.

## 6. Determinism, save/load, LOD

* **Save/load** is certified at seven moments — an active conversation, an
  unanswered question, after a fact transfer, a pending accepted request, a
  completed request, a refusal, and after a threat interruption. Each restores
  byte-identically, emits no act on load, and continues identically for ten
  minutes (`artifacts/npc_dialogue_v1/save_load_trace.json`).
* **LOD** — promoting a citizen to PHYSICAL for a moment and demoting it again
  leaves dialogue and cognition state identical to a control copy; no semantic
  act is duplicated.

## 7. Performance (§38)

From `artifacts/npc_dialogue_v1/performance.json` (Houston, 300 citizens):

* Dialogue costs **~0.24–0.53 ms per game-minute**, against a full world step of
  ~112 ms per game-minute — under **0.5 %** of the step.
* A player `TALK` round-trips in **~0.16 ms median** (max ~0.37 ms); an NPC↔NPC
  sequenced call ~0.11 ms per act.
* Chatter is bounded: a conversation ring, capped acts/transcripts, per-pair
  cooldowns and per-fact call limits keep the volume flat across the day.

## 8. Multi-city smoke (§41)

`artifacts/npc_dialogue_v1/city_smoke.json`: houston, madisonville_tx, austin,
san_antonio all **PASS**; boulder **INFO** (no compiled bundle). No city-name
special-casing exists in the dialogue or cognition code (D42).

## 9. Godot evidence (§37)

Bridge protocol **v8** (`TALK`, `GET_DIALOGUE`). The live `DialogueGate` scene
runs the real world, the real bounded `DialoguePanel` and real physics; the
probe trace (`artifacts/npc_dialogue_v1/godot_probe_trace.json`) shows the
player greeting a witness, receiving a grounded answer, an uninformed citizen
answering "I don't know", an NPC warning exchange, a help request that a coworker
services at the object, a refusal, and an interruption. Rendered shots are in
`docs/npc/evidence_dialogue/`.

## 10. Certification table and regression (D1–D42, D36–D40)

The machine-readable table is `artifacts/npc_dialogue_v1/certification_table.md`
and the full trace `artifacts/npc_dialogue_v1/one_day_trace.json` — **every gate
D1–D42 is PASS**. Every gate is derived from authoritative state; every pick is
data-driven.

`artifacts/npc_dialogue_v1/regression.json` records the guard rerun (D36–D40):
CognitionGate 30/0, WorkGate 22/0, OutbreakGate 18/0, MobilityGate 24/0, the
four foundation gates (run_gates) 85/0, and the new DialogueGate 22/0 — all
PASS. The full Python suite is **1551 passed / 1 failed** (1552 collected); the
single failure is the pre-existing `test_compile_writes_only_presentation_files`,
which needs the raw Overture packet and was already recorded failing in the
cognition milestone — no net regression. Two work-surface tests that briefly
regressed were fixed: one stale exact-key assertion updated to include the
authority's `help_for`, and the work-runtime day test isolated from dialogue
(on by default since this milestone) so it again exercises the WorkRuntime alone.

One latent authority bug surfaced by the live Godot gate was fixed: `_substep`
now snapshots and re-fetches conversation keys, so ending one conversation and
trimming others mid-loop can no longer raise `KeyError`.

## 11. What changed, and the epistemic guarantee

The one hard rule — the dialogue system may not inspect global world truth to
decide what a citizen says — is enforced structurally: the `asphodel/dialogue`
package imports only `acts` and `cognition.memory`, and the grounding validator
takes a single `MemoryStore`. Every spoken proposition is checked against the
**speaker's own** store; an unsupported claim is rejected ("I don't know") and an
over-claim is downgraded to the epistemic status the fact actually supports.
Information enters a listener's mind only through cognition's single
`receive_fact` write path — the same one warnings already used — so a told fact
carries its provenance, its told confidence, and its origin witness, and the
listener's later behaviour changes because its beliefs changed, not because the
dialogue layer moved it.

**ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1: PASS**

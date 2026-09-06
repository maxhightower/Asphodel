# ASPHODEL — NPC Dialogue & Communication v1 — Architecture

This milestone turns the existing cognition system into grounded conversation.
Citizens ask, answer, warn, request, refuse, agree, thank and clarify — and a
citizen never states as fact anything it does not actually know or believe.
Dialogue sits **on top of** cognition; it never becomes a second brain.

## 1. The hard epistemic rule (§2)

The dialogue package holds **no handle to global world truth**. What a citizen
says is decided only from that citizen's own perception, memory, beliefs,
relationships, goals and immediate context, plus whatever the interlocutor
supplies in the conversation. The grounding validator that gates every spoken
proposition takes exactly one argument that touches knowledge: a single
`MemoryStore` (the speaker's). It cannot read another citizen's memory, the
outbreak's global state, the omniscient event log, or any world object.

Concretely: `asphodel/dialogue/grounding.py` imports only `acts` and
`cognition.memory`; `ground(store, prop, now_s)` retrieves and checks against
`store` alone. `DialogueRuntime` never calls into `world`/`outbreak` truth to
build an utterance — it reads the speaker's `MemoryStore`, `beliefs()`,
`rels`, mobility embodiment (position/availability) and the WorkRuntime for
problems the citizen can itself see.

## 2. Authority model (§3, §42)

The cognition pipeline is unchanged and remains authoritative:

```
Perception → Memory → Belief → Relationship → Decision → CitizenRuntime
```

Dialogue is a presentation-and-transfer layer over it:

* **Cognition decides who speaks to whom, on what channel.** `_share` /
  `_share_burst` in `cognition/runtime.py` pick recipients (room mates, shout,
  calls to ties) and route each telling through `self.dialogue.warn(...)`.
* **Dialogue turns a decision into a conversation.** It renders the semantic
  act, checks channel feasibility (co-presence / contact channel), and hands
  the fact to the one write path.
* **Cognition owns the write.** `receive_fact(recipient, sender, fact, ...)` is
  the single method that writes a told fact into a listener's memory, applies
  told-confidence, the `warned_by` / `told_threat` relationship rules and an
  immediate avoidance decision. Dialogue's `transmit()` calls it; nothing else
  writes dialogue-sourced knowledge.
* **A request pushes a goal; existing authorities execute.** An accepted help
  request becomes a real `WorkRuntime` help task; the smart-object system does
  the work. Dialogue never moves a body or changes an object itself.

No subsystem bypasses cognition to obtain a dialogue fact.

## 3. Speech acts and propositions (§4, §5)

`asphodel/dialogue/acts.py` defines the grammar:

* **Speech acts** (semantic, the authority): GREET, INFORM, WARN, ASK_FACT,
  ANSWER, ASK_LOCATION, ASK_PERSON, ASK_SAFETY, ASK_FOR_HELP, OFFER_HELP,
  ACCEPT, REFUSE, THANK, ACKNOWLEDGE, CLARIFY, EXPRESS_UNCERTAINTY,
  REPORT_PROBLEM, END_CONVERSATION. Natural-language wording is presentation.
* **Propositions** — a structured claim: `kind` (PERSON_IS_DANGEROUS,
  ATTACK_HAPPENED, PLACE_IS_DANGEROUS, PERSON_SEEN, HELP_RECEIVED,
  STATION_BROKEN, …), `subject`/`target`, place, `event_ref` (the backing
  fact id), and the epistemic block: `epistemic`, `source_citizen`,
  `origin_witness`, `origin_id`, `hops`, `confidence`, `t`.

The proposition, not the sentence, is the unit that is validated and
transmitted.

## 4. Grounding validator and epistemic status (§6, §7)

`grounding.ground(store, prop, now_s)` is a hard PASS gate:

* It finds the backing fact in the **speaker's** store (bounded retrieval,
  `TOP_K = 5`, `RETRIEVAL_FLOOR = 0.12`).
* An unsupported claim is **rejected** (the runtime emits `GROUNDING_REJECTED`
  and the citizen instead says "I don't know"). An over-claim (e.g. "I saw"
  for a fact the store holds only as told) is **downgraded** to the epistemic
  status the fact actually supports.
* Epistemic status comes only from the fact's source and hops:
  `DIRECT_OBSERVATION` → "I saw"; `EXPERIENCED` → "it happened to me";
  `SECOND_HAND` (told, 1 hop) → "X told me"; `HEARSAY` (≥2 hops or decayed) →
  "I heard"; `BELIEF` → "I think"; `UNCERTAIN` → "I'm not sure"; `UNKNOWN` →
  "I don't know".

The renderer (`render.py`) is a deterministic template over the semantic act;
the epistemic status chooses the frame and the frame is never dropped — a told
sighting is never surfaced as a first-hand "I saw".

## 5. Conversations, turn-taking, channels (§8–§10)

* **`Conversation`** (`session.py`) is bounded persistent state: participants,
  channel, whose turn, the recent acts (capped), topic, open questions, open
  requests, facts introduced, a queued plan, and a termination state. A short
  rendered transcript is kept for UI/debug only; the acts are the state.
* **Turn-taking** is deterministic. NPC↔NPC warnings/calls run as a short
  **sequenced plan**, one act per second, so a real threat can interrupt them.
  Threat, health and planner overrides win: `_step_plan` drops a conversation
  the moment a participant perceives a fresh first-hand threat (unless the
  conversation is itself a threat warning), and an idle player conversation is
  interrupted the same way in `_substep`.
* **Channels** — `FACE_TO_FACE` (co-present: same room indoors, or within
  `TALK_RADIUS_M = 6 m` outdoors), `SHOUT` (one act, carries through a
  building), `CALL` (remote, needs a household/workplace tie or familiarity ≥
  0.55), `PLAYER` (the bridge), and `PROBE` (a read-only inspection question
  used by the player UI and the certification harness — it renders what a
  citizen *would* say without writing anything into the asker's memory).
  Every face-to-face entry point — `ask()`, `warn()`, `request_help()` and
  `_step_plan()` — enforces the same `co_present` rule; a request to a
  coworker who is out of the room but on a workplace tie is placed over a
  call instead.

## 6. Question answering and information transfer (§13–§15)

`ask()` opens a question and its grounded answer. `_answer()` retrieves from
the answerer's store and builds the proposition; if the answer carries a fact
and the channel is a real one, `transmit()` speaks it and calls
`receive_fact` — the listener now genuinely knows it, as a told fact one hop
further from the origin, with the origin witness preserved. On the read-only
`PROBE` channel the answer is rendered but not transmitted.

This is the §45 standard: ask two citizens the same question; the one who
knows answers (first-hand or naming its source), the one who does not says "I
don't know"; tell the second citizen and only then does its knowledge — and
its later avoidance behaviour — change.

## 7. Requests, acceptance, refusal (§16–§23)

A visible work problem makes the affected citizen **ask the coworker it knows
best** (`_decide_help` picks by closeness among reachable coworkers).
`evaluate_request()` is the decision boundary: it uses cognition's `help_score`
and returns a structured refusal reason (too dangerous, busy, no capability,
low trust, urgent task, shift, cost). An acceptance becomes a real
`WorkRuntime.assist` task at once; the request completes when the object's
state actually changes. A refusal creates no task and is remembered
(`REFUSED_BY`), and both outcomes feed the relationship rules (`helped_by`,
`refused_by`).

## 8. Determinism, save/load, LOD (§24, §29, §30)

* **Deterministic renderer** — no model, no network, no per-call state. A
  future LLM could only ever be a realizer of the same validated frame.
* **Save/load** — `DialogueRuntime.to_state/from_state` persists conversations,
  requests, cooldowns, player sessions, the event tape and counts. A restored
  world continues byte-identically and emits no act on load (no response
  reroll). Certified at seven moments: an active conversation, an unanswered
  question, after a fact transfer, a pending accepted request, a completed
  request, a refusal, and after a threat interruption.
* **LOD** — dialogue reads embodiment band/availability but keeps no
  band-specific state, so promoting a citizen to PHYSICAL for a moment and
  demoting it again leaves dialogue and cognition state identical to a control
  copy that never promoted; no semantic act is duplicated.

## 9. Bridge and Godot (§11, §37)

Bridge protocol is **v8**: `TALK` (a structured player act — from a bounded
option set, never free text) and `GET_DIALOGUE` (a snapshot). `START_WORLD`
enables dialogue by default when cognition is on. The Godot client (v8) drives
a bounded `DialoguePanel` — the player picks from ASK_FACT / ASK_LOCATION /
ASK_PERSON / ASK_SAFETY / ASK_FOR_HELP / END; there is no text entry and no
model in the loop. The live `DialogueGate` scene exercises the real world, the
real panel and real physics.

## 10. Out of scope (§41)

No free-text player input, no LLM in the runtime, no deception/lying, no
romance modelling, no Rust. Wording is deterministic; the proposition and its
validator stay authoritative.

## 11. File map

| Area | File |
|---|---|
| Speech-act & proposition grammar | `asphodel/dialogue/acts.py` |
| Grounding validator, bounded retrieval, answers | `asphodel/dialogue/grounding.py` |
| Deterministic surface renderer | `asphodel/dialogue/render.py` |
| Conversation session state | `asphodel/dialogue/session.py` |
| DialogueRuntime (channels, say/transmit/warn, ask/answer, requests, player, save, LOD) | `asphodel/dialogue/runtime.py` |
| The one write path + share routing | `asphodel/cognition/runtime.py` (`receive_fact`, `_share`, `_decide_help`) |
| World interleave, `talk()`, snapshot merge | `asphodel/orchestrator.py` |
| Save block | `asphodel/save.py` |
| Bridge v8 (`TALK`, `GET_DIALOGUE`) | `asphodel/bridge/protocol.py`, `asphodel/bridge/session.py` |
| Godot client v8, DialoguePanel, DialogueGate | `godot/scripts/*.gd`, `godot/tests/DialogueGate.tscn` |
| Certification day (D1–D42, Q1–Q5) | `tests/test_npc_dialogue_v1_day.py` |
| Unit suites | `tests/test_dialogue_*.py` |
| Authority audit | `docs/npc/NPC_DIALOGUE_AUTHORITY_AUDIT.md` |

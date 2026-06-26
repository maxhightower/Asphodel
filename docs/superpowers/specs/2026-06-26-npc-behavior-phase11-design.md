# Design — Phase 11: NPCs (citizens as live, behaving agents)

**Date:** 2026-06-26
**Status:** Draft (design); pending implementation plans
**Branch:** `claude/project-zomboid-lessons-mwoke7`
**Evidence base:** [`PROJECT_ZOMBOID_LESSONS.md`](../../PROJECT_ZOMBOID_LESSONS.md),
[`NPC_PRECEDENT_RESEARCH.md`](../../NPC_PRECEDENT_RESEARCH.md)

## 1. Summary

Today the micro tier (`micro.py`) resolves a promoted zone into **anonymous
epidemiological particles**: a position on a torus, an `int8` disease state, a
random walk. Separately, `citizen.py` produces **rich people** — occupation,
home/work, a daily `schedule`, inventory, a signature collapse moment — that are
never embodied as live agents. Phase 11 **bridges the two**: a promoted zone's
agents *become* citizens executing their daily routine, deflected by the live
belief field, and a bounded few are tracked as **persistent named individuals**
across promote/demote churn. The whole layer stays **deterministic** and **data-
driven**, and is calibrated to **not perturb** the validated epidemic curve.

This is the part Project Zomboid spent a decade failing to ship. The research
(`NPC_PRECEDENT_RESEARCH.md`) shows every shipped large-population sim that
succeeds does it the way proposed here — LOD-for-behavior (Cities: Skylines II,
Dwarf Fortress), schedule-driven defaults (Watch Dogs: Legion), a small utility/
needs layer with the *environment* advertising affordances (The Sims), a bounded
named roster over a disposable crowd (Nemesis, Census), and strict determinism
(Factorio) — and that the failure mode to avoid is a powerful *unconstrained*
autonomous AI that overrides designed content (Oblivion's Radiant AI).

## 2. What already exists (and is reused)

- **`micro.py` — `AgentZone`:** agents as parallel numpy arrays (`pos`, `state`),
  spatial-hash neighbour search, `from_counts` spawn manifest, `step()`
  proximity transmission. Phase 11 *adds arrays*, it does not rewrite this.
- **`orchestrator.py` — `World`:** per-tick promote/demote (`_promote_zone` /
  `_demote_zone`), the macro ledger as authoritative, `set_focus`, `intervene`,
  `snapshot`. **The key gap:** `_demote_zone` just drops the `AgentZone` — no
  identity survives. Phase 11 makes identity persist for the bounded roster.
- **`citizen.py`:** `CitizenProfile` (occupation, `home_zone`/`work_zone`,
  `schedule: list[ScheduleEntry]`, `current_location`/`current_activity`),
  `ScheduleEntry` (`start_hour`, `end_hour`, `activity`, `location`, `task`),
  `spawn_population` (seeded, `SeedSequence`-per-citizen). This is the identity
  source.
- **`signatures.py` / `environments.py` / `travel_events.py`:** per-place / per-
  role **data tables** of "what this situation affords." These become the
  *advertisers* in the utility layer (§6).
- **`gametime.py` — `TimeScale`:** maps sim tick ↔ in-game hour, so an agent can
  look up "what does my schedule say I'm doing at this hour."
- **`model.py`:** the belief field per zone (already drives macro shelter/flee);
  the override channel the agent behavior reads (§5).

## 3. Goals / Non-goals

**Goals**
- Promoted-zone agents carry a **citizen identity** and follow their **schedule**
  as the cheap default behavior (home → commute → work → errand → home).
- A small **advertised-affordance utility layer** lets agents react to danger
  (shelter / flee / seek) when the world deviates from routine — subordinate to
  designed signature moments, never overriding them.
- A **bounded roster** of persistent named citizens survives demote→re-promote
  reproducibly; everyone else is an anonymous statistical fill.
- **Determinism preserved:** behavior is a pure function of `(citizen identity,
  world state, tick)`; a run is bit-reproducible across promotion churn.
- **Epidemiology unchanged:** schedule/utility behavior affects the curve *only*
  through the already-calibrated shelter→β and flee→flux couplings.

**Non-goals (explicit, deferred)**
- Behavior trees / GOAP / planning. Deliberately excluded (Oblivion evidence).
- Per-agent pathfinding on the street graph inside a promoted zone (agents move
  on the torus; street-routed movement stays in `vehicles.py` at spawn/commute
  granularity).
- Relationships / memory / dialogue between named citizens (the Nemesis "rich
  social graph" — a later phase; the roster *mechanism* is built now, its
  social depth is not).
- Rendering. Godot consumes `snapshot()`; visual NPCs are Phase 12.

## 4. The three behavior LOD tiers

Mirror the existing epidemiology LOD with a **behavior LOD**. A citizen's
behavioral fidelity is a function of attention, exactly as its epidemic fidelity
is a function of promotion.

| Tier | Who | Behavior | Cost |
|---|---|---|---|
| **B0 statistical** | macro (un-promoted) zones | none — shelter/flee are aggregate multipliers in `model.py` (today) | ~0 |
| **B1 scheduled** | agents in a promoted zone | look up the citizen's `ScheduleEntry` for the current in-game hour → an *intent* (sleep/work/commute/errand); the belief field can override it (§5) | one array lookup + a compare, vectorised |
| **B2 reactive** | roster + agents near player focus | B1 **plus** the advertised-affordance utility pick (§6) and signature-moment eligibility (`signatures.py`) | small, bounded by roster + focus size |

Promotion to B1 is automatic (zone promoted). Promotion to B2 is the **roster /
focus** membership of §7. The tier is carried as an `int8` per agent so the step
can branch vectorised.

## 5. The identity↔agent bridge (Sub-project 1 — do first)

The seam everything hangs off, analogous to how Phase 5's orchestrator was the
seam for epidemiology.

- **Spawn manifest carries identity.** `AgentZone` gains parallel arrays:
  `citizen_id: int64` (−1 = anonymous fill) and `behavior_tier: int8`. When a
  zone promotes, instead of `from_counts` drawing anonymous agents, the
  orchestrator draws from the zone's **citizen population** (the
  `spawn_population` set whose `home_zone`/`work_zone` resolves to this zone),
  matching each citizen to a compartment slot. Surplus slots (more macro people
  than baked citizens) are filled anonymously (`citizen_id = −1`) — the GTA-V
  anonymous-crowd half.
- **Schedule → intent.** Each tick, B1+ agents map `TimeScale.tick→hour` and
  look up their citizen's active `ScheduleEntry`. The intent biases the agent's
  movement target on the torus (a "home" region vs a "work" region vs "moving")
  — enough that aggregate occupancy reads correctly (homes empty at work hours)
  without per-agent pathfinding. **Crowd phenomena emerge from aggregation:** a
  shared work-start hour produces a commute pulse; a shared flee response
  produces an exodus — both already legible through `vehicles.py` congestion.
- **The disease state is unchanged.** Identity rides *alongside* `state`; the
  transmission step in `AgentZone.step()` is untouched, preserving Phase 4a
  calibration by construction.

**Why first:** it converts particles into citizens with the least code and no new
AI paradigm, and it is the data structure §6–§8 extend.

## 6. The reactive layer — advertised affordances (Sub-project 2)

Adopt **The Sims' inversion**: the agent does not score a fixed internal menu;
the **environment advertises** weighted affordances and the agent picks. This is
strictly better for Asphodel because our world is *already* data tables of
affordances.

- **Advertisers.** A building/road/zone exposes `advertise(citizen, world) ->
  list[(action, utility)]` sourced from existing data: `environments.py`
  ("this high-rise affords `shelter` 0.4 but `fire` hazard 0.8"),
  `signatures.py` (the role's defining action), `travel_events.py` (road
  affordances). Adding a hazard or refuge is **one data entry**, our house rule.
- **Needs.** Each citizen carries a tiny fixed need vector: `safety`, `fatigue`,
  `hunger`, `social`. `safety` is driven by the **live belief field** of the
  agent's zone (closing the gap ARCHITECTURE.md §3 flags — micro shelter
  currently uses static `MicroParams`, not live belief).
- **Selection — seeded top-k, not argmax.** Score each advertised action by
  `utility × need`, then **draw one of the top-k at random from the agent's
  seeded RNG** (The Sims' anti-robotic rule). Because the draw is seeded
  (§8), the crowd looks varied yet stays bit-reproducible.
- **Subordinate to designed content (the Oblivion guard).** The utility pick may
  only choose among `{continue_schedule, shelter, flee, seek}`. It can **never**
  override an eligible **signature moment** or a player intervention — those take
  precedence. The reactive layer fills gaps; it does not author drama.

## 7. The bounded named roster (Sub-project 3)

Cap persistence so it is independent of city size (the principled escape from
PZ's "simulate everyone").

- **Two populations:** a **named roster** (size `max_roster`, e.g. 64) of
  persistent `CitizenProfile`s, and an **anonymous crowd** that is spawned/
  despawned freely (`citizen_id = −1`), never persisted.
- **Promotion is event-driven and interaction-keyed** (Nemesis / Census
  evidence — *not* spawn-order or timer-based): a citizen enters the roster when
  the player **interacts with / profiles / is near** them, or when they hit a
  signature moment in view. This keeps promotion reproducible (§8).
- **Persistence across demote→re-promote ("uprezzing", Watch Dogs: Legion).**
  `_demote_zone` today drops the `AgentZone` wholesale. Change: on demote,
  **roster members' state is checkpointed** into the roster store (position
  bucket, disease compartment, need vector, schedule cursor); anonymous agents
  are discarded to the macro ledger as today. On re-promote, roster members are
  **restored** to their checkpoint; anonymous slots re-fill from counts. This is
  the DF "the world vanishes except historical figures" rule applied to our
  promote/demote boundary.
- **Eviction:** when the roster is full and a new promotion fires, evict the
  least-recently-interacted member back to anonymous (its identity is logged,
  not simulated) — a fixed, deterministic policy.

## 8. The determinism contract (cross-cutting — the Factorio caution)

The most important technical guard the research surfaced: **determinism +
interdependence forces a fixed update order.** An agent's behavior reads the live
belief field and feeds visible burden back — interdependent — so the order must
be identical every run or determinism breaks at exactly the promote/demote seam
Phase 5 already guards for population.

- **Per-agent RNG** derived via `SeedSequence` keyed by `citizen_id` (reusing
  `citizen.py`'s existing scheme), so a citizen's "random" choices are stable
  across promotions. Anonymous fill uses a slot-index-keyed stream.
- **Fixed decision order, declared and tested:** within a tick —
  `(1) macro belief/field update → (2) agent schedule lookup → (3) agent utility
  pick → (4) transmission → (5) reconcile)` — is part of the engine contract,
  not an implementation accident.
- **No wall-clock, no global RNG, no dict-iteration-order dependence** in any
  behavior path. Roster membership and eviction are deterministic functions of
  interaction history + tick.

## 9. Sub-projects (sequenced; each its own plan → implementation)

| # | Sub-project | Deliverable | Demoable result |
|---|---|---|---|
| **1** | **Identity↔agent bridge + schedule-following** | `AgentZone` carries `citizen_id`/`behavior_tier`; promote draws from the zone's citizen population; B1 schedule→intent movement. | A promoted zone shows citizens at home/work by hour; commute pulse emerges. |
| **2** | **Advertised-affordance reactive layer** | `advertise()` on environments/roles; need vector with belief-driven `safety`; seeded top-k pick; subordinate to signatures. | Under rising belief, agents shelter/flee instead of walking routine; signature moment still fires. |
| **3** | **Bounded named roster + uprezzing** | Roster store; event-driven promotion; checkpoint/restore across demote→re-promote; eviction. | Leave a named citizen's zone and return — same person, same state. |

## 10. Testing strategy (the project's "invariant + findings" culture)

- **Epidemiological invariant (gate on Sub-project 1):** turning agents from
  random-walkers into schedule-followers must keep the micro epidemic curve
  within the Phase 4a agreement band of the macro reference. Extend
  `tests/test_phase4a.py` / `test_orchestrator.py` with a schedule-on vs
  schedule-off agreement assertion.
- **Determinism invariant (gate on Sub-project 3):** a promote→demote→re-promote
  cycle reproduces identical roster state and identical aggregate counts
  bit-for-bit; two runs from the same `(config, seed)` produce identical
  behavior traces. Extend the existing conservation test with *decision
  reproducibility*.
- **Believability smoke test:** a simulated day yields sane occupancy (homes
  empty during work hours; commute traffic spikes at shift change via
  `congestion_report`); under a forced belief spike, shelter/flee fractions rise.
- **Roster bound test:** with `max_roster=K`, the persistent set never exceeds K
  regardless of city size or session length; eviction is deterministic.
- **`FINDINGS_PHASE11.md`** records the readout: does schedule-driven behavior
  leave the curve intact, and does the city *read* as alive (occupancy/commute/
  exodus numbers)?

## 11. Open items / future

- **Roster size & promotion economics** are a tuning parameter, not inherited
  from precedent (the research could not pin exact numbers) — set empirically in
  `FINDINGS_PHASE11.md`.
- Social graph / memory / dialogue among roster members (the deep Nemesis layer).
- Street-graph pathfinding inside a promoted zone (vs torus-region intents).
- Coupling agent shelter to live belief is partially done here (§6); full
  belief↔behavior↔infrastructure loop inside micro is a refinement.
- Godot rendering of named vs anonymous agents from `snapshot()` (Phase 12).

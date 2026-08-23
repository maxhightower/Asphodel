# Initiative — Authoritative Playable World (M0 → M6)

**Status:** M0–M5 PASS, M6 PARTIAL (Godot rendering written but not engine-executed).
See `FINDINGS_M<N>_*.md` and `FINDINGS_INITIATIVE_SUMMARY.md`.
**Canonical branch:** `claude/asphodel-authoritative-world-55z0qw`
**Baseline:** descendant of `claude/asphodel-gameplay-integrity-de72g6` (real-road mobility head)
plus the Phase 11 NPC design/research/plan documents carried forward from
`claude/project-zomboid-lessons-mwoke7`.

## Governing principle

**One world, one authority, scalable fidelity.**

The Python simulation (`asphodel.orchestrator.World`) owns truth. Godot renders
truth and submits player intent. Citizens may exist at different simulation
fidelities, but they must never become contradictory parallel representations of
the world.

## Milestone ordering

This initiative **re-orders** the previously drafted Phase 11 work. The original
Phase 11 design (`docs/superpowers/specs/2026-06-26-npc-behavior-phase11-design.md`)
assumed an in-process `World`; this initiative first makes that `World` the
**live authority behind Godot**, and only then layers NPC identity, reaction, and
persistence on top of the live runtime. The correct order is:

| Milestone | Scope | Source design |
|-----------|-------|---------------|
| **M0** | Canonical baseline: one clean initiative line; Phase 11 docs carried forward; full baseline test surface certified. | this document |
| **M1** | **Live runtime authority bridge** — Godot plays against a live `World` over a versioned IPC protocol; retire baked-timeline authority; focus follows the player; interventions change the future; pause freezes everything. | this document |
| **M2** | NPC identity + schedule activity (SP1) — promoted agents carry `citizen_id`/`activity`; identity assignment consumes zero RNG; epidemiology bit-identical with citizens on/off. | `plans/2026-06-26-npc-identity-bridge-sp1.md` |
| **M3** | Reactive affordances (SP2) — environment advertises a bounded action set; deterministic seeded top-k selection; aggregate shelter/flee stays governed by certified macro behavior (label/reselection only). | `plans/2026-06-26-npc-reactive-affordances-sp2.md` |
| **M4** | Bounded named roster + uprezzing (SP3) — event-driven roster promotion, deterministic eviction, demote-checkpoint / re-promote-restore; macro remains authoritative. | `plans/2026-06-26-npc-named-roster-sp3.md` |
| **M5** | Deterministic save/load — versioned explicit save schema; destroy-and-reload continuation is bit-identical to uninterrupted execution. | this document |
| **M6** | Visible living city — Godot renders the citizen simulation from snapshots; legible daily rhythm; minimal interaction for roster promotion; separated sim/IPC/render benchmarks; final vertical demo. | this document |

**Gate discipline:** complete milestones strictly in order. Do not begin the next
milestone until the previous receives a written **PASS**. Each milestone ends with
an implementation summary, architecture decisions, tests executed, determinism and
conservation results where applicable, known limitations, branch/head SHA, and an
explicit verdict (PASS / PARTIAL / FAIL).

## Non-negotiable invariants (whole initiative)

- **A. Python owns simulation authority.** Godot renders snapshots, provides
  camera/focus, submits actions, and requests pause/save/load. Godot never decides
  outbreak progression, belief, infection, behavior, intervention effects,
  population movement, or persistent NPC state.
- **B. Population conservation is load-bearing.** The macro float ledger is
  authoritative. NPC identity, persistence, rendering, and save/load may not create
  or destroy population.
- **C. Determinism is a product feature.** Same `config + city + seed + player-input
  sequence` ⇒ same authoritative trajectory. No wall-clock randomness, no global
  unseeded RNG, no nondeterministic iteration, no presentation-side randomness that
  alters simulation truth.
- **D. Fidelity is attention-scaled.** Macro/statistical people, promoted local
  agents, and a bounded set of persistent important people — never full simulation
  of every citizen.
- **E. Preserve calibrated epidemiology.** A simulation-neutral feature must be
  proven neutral; a feature that intentionally affects outcomes must route through a
  certified causal channel.

## Deferred (explicitly out of scope for this initiative)

Combat, weapons, injuries, hunger/thirst survival loop, advanced looting,
procedural character art, relationship/social graphs, dialogue generation,
citywide per-agent pathfinding, exact offscreen individual disease continuity,
vehicle gameplay, new outbreak archetypes, scenario-engine rework, and
consolidation of the divergent `scenario-engine-flux` / `outbreak-config-types`
branches. Record seams for these; do not implement them.

## Milestone reports

Per-milestone certification reports are recorded as `FINDINGS_M<N>_*.md` at the
repository root, matching the existing `FINDINGS_*.md` convention.

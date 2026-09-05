# Asphodel — Simulation Architecture & Roadmap

> **Status note (convergence, 2026-09):** this file documents the epidemic
> engine contract (macro/micro tiers, `World` façade). The whole-system
> architecture — geography, buildings, streets, citizens, vehicles, physics,
> Godot — is `docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md`.
>
> **Status note (canonicalization):** the roadmap table in §4 below pre-dates the
> live bridge and save/load work — it still lists "Phase 9" (save/load) as *next*
> and "Phase 10" (Godot) as after. Both are **done and certified**. The current
> record is the M0–M6 findings (`FINDINGS_M0_*` … `FINDINGS_M6_*`) and
> `docs/findings/FINDINGS_BW_LIVING_CITY.md` (live Python↔Godot bridge, embodied citizens,
> roster, deterministic save/load). See [`docs/CANONICAL_STATUS.md`](docs/CANONICAL_STATUS.md).
> The engine-contract sections (§2, §3) remain accurate.

This document defines the **engine contract** the rest of the game is built
against, and the **roadmap** for fleshing out the simulation *before* any game
engine (Godot) work. The guiding principle:

> **The simulation is a self-contained, headless, deterministic Python core.
> Godot (or any front-end) only *renders* a snapshot and *sends* input.** If a
> behaviour can be decided by the front-end it does not belong here; if it
> changes the world state it does.

Keeping that boundary clean is the whole point of this phase: when the sim is
"done," wiring up Godot should be a rendering-and-input job, not a
re-architecture.

---

## 1. Where the simulation stands

Two tiers exist and are independently validated (see `FINDINGS.md`,
`docs/findings/FINDINGS_PHASE4A.md`):

| Tier | Module | What it is | Status |
|---|---|---|---|
| **Macro** | `model.py` | Whole-map coupled fields: SEIR + belief + behaviour + infrastructure + authority over a zone graph. | Trusted. The `Day −1 → Day 0 → collapse` arc emerges and is controllable. |
| **Micro** | `micro.py` | One zone resolved into discrete agents in continuous 2D, proximity transmission, calibrated to reproduce the macro curve in expectation. | Trusted **single-zone**. Sized at ≈1000 agents. |
| **Handoff** | `handoff.py` | Promote / derived-update / demote messages, mass-conserving, no kink at the seams. | Trusted **single-zone**. Inter-zone flux **stubbed to zero**. |

The gap between "two validated tiers" and "a game-ready simulation core":

1. There is **no orchestrator** — nothing runs the whole map with zones flipping
   between macro and micro *at runtime* under a frame budget.
2. **Inter-zone agent flux is stubbed** (`handoff.py`): a promoted zone exchanges
   nobody with its neighbours.
3. The **player-proximity / visibility** promotion trigger is named but not
   built; promotion currently keys off infectious fraction only.

This document's **first implemented step (Phase 5)** closes #1 and #2.

---

## 2. The engine contract (the façade)

The front-end sees exactly one object: `World` (`orchestrator.py`). Everything
else (`Simulation`, `AgentZone`, the handoff messages) is an implementation
detail behind it.

```python
world = World(config, micro_params=..., handoff=..., seed=0)

world.set_focus([zone_a, zone_b])   # player camera → force-promote these zones
tick = world.step()                 # advance exactly one dt; returns a WorldTick
world.run(n_days=10.0)              # convenience: many steps

snap = world.snapshot()             # everything the renderer needs this frame
```

### `WorldTick` (returned by `step`)
Lightweight per-tick summary: `tick`, `day`, `n_promoted`, `total_pop`, and the
macro `TickRecord` (so existing reporting/plotting keeps working unchanged).

### `snapshot()` (what the renderer reads)
A plain dict, JSON-friendly, with **no live references into engine internals**:

- `day`, `tick`
- `zones`: per-zone `belief`, compartment counts (`S,E,Ia,Is,R,D`),
  `infectious_fraction`, `power_ok`, `water_ok`, and a `promoted` flag.
- `agents`: for each promoted zone, the agent `positions` (N×2 in zone-local
  continuous coords) and integer `state` codes — i.e. the individuals Godot
  draws. Macro zones contribute aggregates only.
- `official_signal`, `authority_perceived`.

This maps **directly** onto the two-tier rendering model: draw macro zones as
heat/aggregate; draw promoted zones as moving individuals.

### Reserved (later phases, contract sketched now so they slot in)
- `world.intervene(action)` — player actions (broadcast, shelter order,
  staffing reallocation, cordon). Phase 8.
- `world.save() / World.load()` — full deterministic state serialization
  (macro arrays + every live `AgentZone` + RNG state). Phase 9.

---

## 3. The orchestration algorithm (Phase 5)

The orchestrator advances macro and micro tiers together, **once per `dt`**, with
agents driving the *internal* dynamics of promoted zones and the macro owning
*inter-zone flux*. The macro float array is the **authoritative, exactly-conserved
population ledger**; a promoted zone's agents are its integer realization, used
for internal dynamics and rendering.

Per tick, in order:

1. **Membership update.** For each zone compute the infectious fraction; combine
   with the player focus set and hysteresis (`should_promote` /
   `should_demote`) to decide the promoted set. Newly promoted zones spawn an
   `AgentZone` from their macro counts (the *spawn manifest*); newly demoted
   zones merge their agent counts back (the *merge*).

2. **Macro step with frozen internals.** Call `Simulation.step(frozen_internal=
   promoted)`. For promoted zones the macro **skips the SEIR internal update**
   (agents will provide it) but still:
   - applies **fleeing flux** (belief-driven people movement) to/from them, and
   - lets them act as **infection sources** to their macro neighbours (their
     agent-derived infectious fraction still enters the mixing term), and
   - evolves their **belief / infrastructure** from the agent-derived visible
     burden — so promoted zones stay full participants in the belief cascade.

   After this call, a promoted zone's macro counts = `agent_pre + flux`.

3. **Agent step.** Each promoted `AgentZone.step()` runs proximity transmission
   and the per-agent genome transitions (no zone change). This yields an integer
   `internal_delta = agent_post − agent_pre`.

4. **Reconcile (derived update).** Write `macro_float + internal_delta` back into
   the macro array for each promoted zone, then re-derive the agent population to
   match (spawn arrivals / despawn departures by compartment). Migrants enter the
   agent zone *in their compartment*, so infected fleers transport infection
   across the boundary — the cross-boundary coupling is **people-movement-based**,
   which is the physical analogue for an agent zone.

### Conservation guarantee
`Simulation.step` conserves total population (fleeing redistributes; frozen
internals change nothing). `internal_delta` sums to zero per promoted zone
(agent transitions move people *between* compartments, never create/destroy).
Therefore **`Σ macro_float` after the tick equals `Σ macro_float` before** —
exactly. This is asserted in `tests/test_orchestrator.py`.

### Calibration stays valid at any zone size
`analytic_contact_prob` reduces to `p = β / (density · π r²)` — it depends on
agent **density**, not count. The orchestrator sizes each promoted zone's
`area_size` to hold its population at a fixed reference density (the validated
N=1000 / L=100 case), so the ≈1.04× geometry correction keeps applying whether a
zone holds 800 or 5000 people.

### Documented simplifications (extension points, not bugs)
- Cross-boundary infection reaches promoted zones via **migrating infected
  agents only**, not via the macro's abstract mixing import. (Defensible for an
  agent zone; revisit if zones need to infect neighbours' *agents* without
  movement.)
- Belief→agent-behaviour (sheltering) inside a promoted zone uses the
  `MicroParams` shelter config, not the live macro belief. Flux (fleeing) *is*
  belief-driven via the macro. Coupling agent shelter to live belief is Phase 8.

---

## 4. Roadmap

| Phase | Deliverable | Status |
|---|---|---|
| 3a | Macro belief-cascade tier | ✅ done |
| 4a | Single-zone micro tier + calibration + handoff | ✅ done |
| 5 | Orchestrator (`World`) + inter-zone agent flux + runtime promote/demote + player-focus trigger | ✅ done |
| **6** | **O(n) spatial-hash neighbour search + measured real-time budget + live-bubble budget cap** | ✅ done — see `docs/findings/FINDINGS_PHASE6.md` |
| **7** | **Swappable topology (grid / small-world / commute-hub) + heterogeneous population + multi-seed outbreaks** | ✅ done — see `FINDINGS.md` §9 |
| **8** | **Player interventions (broadcast / shelter order / staffing / cordon) through `world.intervene`; agent shelter coupled to live belief** | ✅ done |
| 9 | Save/load: full deterministic state serialization (macro + agents + RNG) | next |
| 10 | Godot integration: render `snapshot()`, forward input to `intervene()` — **rendering only** | after the above |

The ordering is deliberate: 5 builds the seam everything hangs off; 6–9 are
independent and can be tackled in any order; 10 is intentionally last and small
because the contract in §2 was fixed up front.

---

## 5. Module map (after Phase 5)

```
asphodel/
  config.py        # all tunables as dataclasses (+ MicroParams, HandoffParams)
  graph.py         # ZoneGraph: swappable topology + mobility mixing
  model.py         # Simulation: trusted macro coupled-field step (+ frozen_internal)
  micro.py         # AgentZone: proximity-transmission agent tier (+ flux reconcile)
  macro_ref.py     # passive single-zone macro = the calibration ground truth
  calibration.py   # genome → micro params, agreement metrics
  handoff.py       # promote / derived-update / merge messages, hysteresis
  orchestrator.py  # World: the engine façade — runs macro + dynamic micro zones
  bench.py         # Phase 6: real-time tick-cost benchmark + live-bubble budget
  runner.py        # batch scenario runner + RunResult
  viz.py           # plots / heatmaps / GIF
  experiments.py   # parameter sweeps
  phase4a.py       # micro calibration experiments
```

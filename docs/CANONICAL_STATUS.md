# Asphodel — Canonical Status

_Single source of truth for "which line is the real one." Read this before
trusting any older prose in this repo._

## The canonical line

**All new Asphodel development begins from `main`.**

The canonical convergence tree landed on `main` on 2026-09-05 through PR #4
(merge commit `d9c1629`; certified tip `1a1e3ac`, certified code `7244855` —
`main`'s tree is identical to the certified tree). The convergence branch
`claude/asphodel-canonical-convergence-i6h105` is now history, like every other
`claude/*` branch.

The GitHub repository's **configured default branch is still**
`claude/asphodel-belief-cascade-kvKKv` (June 12, 2026, stale). Switching the
default to `main` is a repository-settings action (Settings → Branches) that
could not be performed from the development sandbox; until it is done, a fresh
clone or an agent that trusts the default lands on the June tree. Do not build
there. PR #3, which merged `main` into that stale branch, is closed.

Every other `claude/*` branch is retired or historical evidence. The census
(`docs/convergence/ASPHODEL_BRANCH_CENSUS.md`) shows that thirteen of them were
already inside `main`, the regional-physics-navigation line was merged in the
convergence, and the two remaining unmerged June branches (zombie outbreak
archetypes; Phase 4b research harness) carry recorded decisions in
`docs/convergence/ASPHODEL_BRANCH_DISPOSITION.md`.

## What the canonical tree is

`docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md` is the architecture:
one world (`asphodel/orchestrator.py`), one building identity
(`buildings.json` index), one street graph (`streetmap.json` v2 baked from the
same Overture packet as the rendered city), one citizen identity from
statistic to humanoid, one vehicle identity across fidelity, one collision
matrix, one terrain pipeline (region v2 with the city plateau), one Godot
runtime that renders truth and submits intent.

Certified on this tree (`docs/convergence/ASPHODEL_CONVERGENCE_REPORT.md`):
740/740 Python tests, the in-engine Godot suites (TestRunner, StreetSmoke,
ExteriorStream, CitizenHumanoidSmoke, the isometric smokes,
PhysicsGate/RegionGate/NavGate, ConvergenceGate), the live-bridge Live*
scenes with bit-identical save/load, and the multi-city matrix (Houston,
Madisonville, Austin, San Antonio, Boulder, Denver region). Verdict:
`ASPHODEL_CANONICAL_CONVERGENCE: PARTIAL` — the four remaining architectural
splits are named in that report.

## Architectural invariants (preserve unless a package needs a new causal channel)

* Python owns simulation truth; Godot renders and submits input.
* The macro float ledger is authoritative for population.
* Macro → promoted agents → bounded persistent named roster is the fidelity
  hierarchy; promotion never changes an identity.
* Same config + city + seed + player-input sequence ⇒ same authoritative
  trajectory. Visual randomness never consumes simulation RNG.
* One schema per artifact, versioned; loaders reject what they do not know.
* Simulation-neutral presentation work stays simulation-neutral.
* Any gameplay feature that changes outcomes flows through an explicit
  authoritative Python state transition.
* Save/load preserves deterministic continuation.

## Embodied mobility (2026-09-05)

`ASPHODEL_EMBODIED_MOBILITY_V1` closed the Planner ↔ World and vehicles-in-
the-playable-scene splits: `asphodel/embodied/` executes CitizenRuntime
itineraries on a sub-tick movement clock inside `World`, persistent
`VehicleInstance`s drive the canonical road route, and Godot realises the NEAR
band as `CitizenBody`/`VehicleBody` with physics reported back. See
`docs/mobility/EMBODIED_MOBILITY_ARCHITECTURE.md` and
`docs/mobility/EMBODIED_MOBILITY_REPORT.md`.

## Embodied outbreak (2026-09-05)

`ASPHODEL_OUTBREAK_V1` put the outbreak on the same persistent citizens:
`asphodel/outbreak/` holds one `HealthRecord` per registered citizen
(susceptible → incubating → symptomatic → incapacitated → corpse → undead,
every outcome a seeded draw stamped at infection), exposure comes from real
co-presence in buildings, vehicles and the street, sickness changes plans
through the ordinary `CitizenRuntime` → `TripExecutor` chain, the dead stay
where they died, the risen keep their `citizen_id`, abandoned cars become
wrecks that close their segment and disrupted workplaces send workers home.
The June `claude/outbreak-config-types-A8fTw` branch was audited as a donor
(`docs/outbreak/OUTBREAK_DONOR_AUDIT.md`) and its archetype values were
carried into the per-citizen grammar; its macro-compartment engine was not.
See `docs/outbreak/OUTBREAK_V1_ARCHITECTURE.md` and
`docs/outbreak/OUTBREAK_V1_REPORT.md`.

## Smart objects and work (2026-09-05)

`ASPHODEL_SMART_OBJECTS_WORK_V1` replaced "arrived at the building, doing
work" with execution through `building → room/zone → station → smart object →
affordance → action` (`asphodel/smart/`): rooms come from the canonical
interior descriptor, smart objects are generated from its furniture with
capability-composed affordances and persisted mutable state, one reservation
ledger prevents double occupancy, a data-driven job/task grammar with
deterministic employment drives cashiers, desk workers and cleaners (and
customers and residents through the same affordances), and the existing
planner/executor interrupt work exactly as they interrupt trips. See
`docs/work/SMART_OBJECTS_WORK_V1_ARCHITECTURE.md` and
`docs/work/SMART_OBJECTS_WORK_V1_REPORT.md`.

## Historical reports

The milestone findings that used to sit at the repository root are in
`docs/findings/` (M0–M6, embodiment, interiors, outside world, isometric
presentation, residential architecture, the regional/physics/nav
architecture). They describe how each system was certified when it landed;
where they name a branch as "canonical", this file supersedes them.

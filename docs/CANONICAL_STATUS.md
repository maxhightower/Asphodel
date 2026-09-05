# Asphodel — Canonical Status

_Single source of truth for "which line is the real one." Read this before
trusting any older prose in this repo._

## The canonical line

**All new Asphodel development begins from `main`.**

`main` is being fast-forwarded to the canonical convergence tree
(`claude/asphodel-canonical-convergence-i6h105`); until that lands, build from
that convergence branch. The GitHub default branch was
`claude/asphodel-belief-cascade-kvKKv` (June 12, 2026) — it is **stale** and
must be switched to `main` in the repository settings; see
`docs/convergence/ASPHODEL_BRANCH_DISPOSITION.md` for the exact landing steps.

Every other `claude/*` branch is retired or historical evidence. The census
(`docs/convergence/ASPHODEL_BRANCH_CENSUS.md`) shows that thirteen of them are
already inside `main`, the regional-physics-navigation line was merged in the
convergence, and the two remaining unmerged June branches (zombie outbreak
archetypes; Phase 4b research harness) carry recorded decisions.

## What the canonical tree is

`docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md` is the architecture:
one world (`asphodel/orchestrator.py`), one building identity
(`buildings.json` index), one street graph (`streetmap.json` v2 baked from the
same Overture packet as the rendered city), one citizen identity from
statistic to humanoid, one vehicle identity across fidelity, one collision
matrix, one terrain pipeline (region v2 with the city plateau), one Godot
runtime that renders truth and submits intent.

Certified on the convergence tree: the Python suite, the in-engine Godot suites
(TestRunner, StreetSmoke, ExteriorStream, CitizenHumanoidSmoke, the isometric
smokes, PhysicsGate/RegionGate/NavGate, ConvergenceGate), the live-bridge
Live* scenes, and the multi-city matrix (Houston, Madisonville, Austin,
San Antonio, Boulder, Denver region). The exact commands and results are in
the convergence report in the pull request that lands this tree.

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

## Historical reports

The milestone findings that used to sit at the repository root are in
`docs/findings/` (M0–M6, embodiment, interiors, outside world, isometric
presentation, residential architecture, the regional/physics/nav
architecture). They describe how each system was certified when it landed;
where they name a branch as "canonical", this file supersedes them.

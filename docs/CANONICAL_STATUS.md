# Asphodel — Canonical Status

_Single source of truth for "which line is the real one." Read this before
trusting any older prose in this repo._

## The canonical line

The current canonical implementation line is the **authoritative-world** line,
continued by the **embodied-survival** milestone branch:

* `claude/asphodel-authoritative-world-55z0qw` — the certified authoritative
  living-city substrate (head `4728113` at milestone start).
* `claude/asphodel-embodied-survival-qlizmu` — the active milestone branch,
  started from that head. **New work goes here.**

The GitHub repository's configured **default branch is stale**
(`claude/asphodel-belief-cascade-kvKKv`, an ancestor 34 commits behind). Do not
treat it as the frontier. Changing the default is a manual repo-settings action
(see `FINDINGS_P1_CANONICALIZATION.md`).

## What is proven (inherited, do not rebuild)

The **Authoritative Playable World** initiative (M0–M6) is CLOSED/PASS and the
follow-on **Bundle-Wired Living City** initiative PASSed in real Godot 4.4.1:

* one world, one authority, scalable fidelity — **Python owns simulation truth;
  Godot renders truth and submits intent**;
* real OSM-derived city bundles (`godot/bundles/{houston,austin,san_antonio,madisonville_tx}`)
  — real roads, real/synthesized building footprints, road-derived mobility graph;
* live Python↔Godot bridge (newline-delimited JSON, versioned protocol);
* player-position-driven promotion/focus; live citizens rendered from snapshots;
* bounded persistent named roster; interaction → roster persistence;
* interventions change future authoritative world state;
* deterministic versioned save → destroy server → reload → bit-identical
  continuation;
* **255 Python tests green** on the canonical baseline.

## Architectural invariants (preserve unless a package needs a new causal channel)

* Python owns simulation truth; Godot renders and submits input.
* The macro float ledger is authoritative for population.
* Macro → promoted agents → bounded persistent named roster is the fidelity
  hierarchy.
* Same config + city + seed + player-input sequence ⇒ same authoritative
  trajectory.
* Simulation-neutral presentation work stays simulation-neutral.
* Any gameplay feature that changes outcomes flows through an explicit
  authoritative Python state transition.
* Save/load preserves deterministic continuation.

## In flight (this milestone)

See `FINDINGS_P1_CANONICALIZATION.md`, `FINDINGS_P2_EMBODIMENT.md`,
`FINDINGS_P3_SURVIVAL.md`:

1. Canonical repository closure — **done**.
2. Physical citizen embodiment.
3. First authoritative survival-resource loop.

## Environment note

The certification environment used for this milestone has `xvfb-run` but **no
`godot4` binary**, so the in-engine certification surfaces are not executable
there. Python-side authority is fully executable and green; the Godot client is
kept code-current against the authoritative contract. See
`FINDINGS_P1_CANONICALIZATION.md` §1B.

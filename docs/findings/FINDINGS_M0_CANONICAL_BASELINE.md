# M0 — Canonical Baseline — Findings

**Milestone:** M0 (Canonical Baseline)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PASS**

## Implementation summary

Established a single canonical initiative line without changing runtime behavior:

1. The designated branch `claude/asphodel-authoritative-world-55z0qw` sat exactly at
   `35d0c86` — the merge-base and the previous default line. `claude/asphodel-gameplay-integrity-de72g6`
   is a **strict descendant** (7 commits ahead) carrying the gameplay-integrity
   repairs and real-road mobility. The reconciliation was therefore a clean
   **fast-forward** (`35d0c86 → cc671fd`) — no merge conflicts, no behavior edits.
2. Brought the Phase 11 design/research/plan documents forward from
   `claude/project-zomboid-lessons-mwoke7` by **cherry-picking its 6 doc-only
   commits** (`473afc4 4c544fe 9fccc16 67b86cb 9a009c8 c1e1bec`). Every one applied
   cleanly — they touch only `docs/`. The full zomboid branch was **not** merged
   (it added nothing else).
3. Added `docs/INITIATIVE_AUTHORITATIVE_WORLD.md` reconciling the roadmap to the new
   ordering: **live bridge (M1) first**, then NPC identity (M2), reaction (M3),
   roster (M4), save/load (M5), rendering (M6). The existing SP1/SP2/SP3 plans are
   mapped onto M2/M3/M4.

The divergent `scenario-engine-flux` and `outbreak-config-types` branches were
**not** merged, per initiative rules.

## Architecture decisions

- **Reuse the designated branch as the initiative branch.** The harness-designated
  development branch (`claude/asphodel-authoritative-world-55z0qw`) already carries
  the initiative's name and sits at the exact baseline the initiative prescribes, so
  it *is* the canonical `m0-m6` line. No second branch was created (the suggested
  `...-m0-m6` name would only fragment the line).
- **Fast-forward over merge.** Because gameplay-integrity strictly descends from the
  branch head, a `--ff-only` update guarantees "no runtime behavior changed except
  unavoidable conflict-resolution changes" — there were zero conflicts.
- **Cherry-pick docs rather than wholesale-merge** the research branch, keeping the
  runtime line clean.

## Phase 11 documents carried forward (present on canonical branch)

- `docs/PROJECT_ZOMBOID_LESSONS.md`
- `docs/NPC_PRECEDENT_RESEARCH.md`
- `docs/superpowers/specs/2026-06-26-npc-behavior-phase11-design.md`
- `docs/superpowers/plans/2026-06-26-npc-identity-bridge-sp1.md`
- `docs/superpowers/plans/2026-06-26-npc-reactive-affordances-sp2.md`
- `docs/superpowers/plans/2026-06-26-npc-named-roster-sp3.md`

## Tests executed

| Surface | Result |
|---------|--------|
| Python full suite (`pytest -q`) | **180 passed** in ~48s |
| — includes `tests/test_mobility.py` (road-mobility: conservation + determinism on real bundles) | included in 180 |
| — includes `tests/test_gameplay_integrity.py` (citizen/city/outbreak/clock coherence) | included in 180 |
| Committed city-bundle JSON validity (30 files across 5 bundles) | **30/30 valid, 0 invalid** |
| Godot TestRunner (23/23) | **NOT RUN** — Godot engine not available in this environment |
| Godot StreetSmoke (14/14) | **NOT RUN** — Godot engine not available in this environment |

For reference, the pre-reconciliation branch head (`35d0c86`) ran **147 passed**;
the reconciled canonical head runs **180 passed**, matching the previously reported
road-mobility head count exactly (the 33 additional tests are the mobility and
gameplay-integrity suites introduced on the gameplay-integrity line).

## Determinism result

`tests/test_mobility.py::test_derivation_is_deterministic` and
`test_derivation_deterministic_on_real_bundle` pass — the road-mobility graph
derivation is deterministic. Full determinism harnessing is the subject of later
milestones.

## Conservation result

`tests/test_mobility.py::test_macro_conservation_with_mobility` and
`test_macro_micro_conservation_with_mobility` pass — the macro float ledger and
macro+micro totals are conserved under the road-weighted mobility graph.

## Known limitations

- **Godot-side tests could not be executed here:** the Godot engine (4.4.1) is not
  installed in this environment, so the reported `TestRunner 23/23` and
  `StreetSmoke 14/14` counts are inherited from the gameplay-integrity certification,
  not re-run. The `.gd`/`.tscn` test assets are present and unchanged on the
  canonical branch.
- Roadmap reconciliation was done additively (a new authoritative roadmap doc)
  rather than by rewriting the existing Phase 11 design's internal ordering, to avoid
  destructive edits to research documents.

## Branch / head SHA

- Canonical branch: `claude/asphodel-authoritative-world-55z0qw`
- Head after M0: `d85f3e4` (`docs: Phase 11 SP2 + SP3 plans`), with the M0 roadmap +
  this findings file committed on top.
- Pre-reconciliation head: `35d0c86`
- Gameplay-integrity head merged: `cc671fd`

## Verdict

**PASS** — one canonical initiative branch exists; runtime behavior unchanged
(fast-forward, zero conflicts); all runnable baseline tests pass (180 Python + 30/30
bundle JSON); Phase 11 plans are present on the canonical branch; working tree clean;
branch pushed. The only exit-gate item not directly re-verified in this environment
is the Godot-engine test execution (engine unavailable), noted explicitly above.

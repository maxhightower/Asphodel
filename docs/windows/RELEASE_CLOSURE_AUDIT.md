# Playable release closure — scope and integration audit

Candidate source: `886ed5dc980f678bcad408d4a8203ef305b03871`.
Integration base: `bee2f18a1827e216f8d998fcf995e9fe935b4a86` (`main`).
GitHub compare confirmed 106 commits ahead, zero behind. Preserve the donor
branch. Closure work is reviewed in PR #5; do not treat opening a PR as landing.

## Implemented release repairs

- Export failure cannot pass using a stale file. An absent, wrong-platform or
  stale-identity authority cannot validate or produce a new release ZIP.
- Frozen source identity is stamped at freeze time, never rewritten to relabel
  an old executable. Exported clients enforce matching client/authority identity
  and cannot fall back to a development Python interpreter.
- LOAD reconstructs saved runtimes before publishing a new session. Failure
  reports an error and preserves the previous world, identity and pause state.
- Normal IsometricWorld startup explicitly requires the full runtime stack;
  a failed mobility initialization cannot silently yield a playable empty viewer.
- W48–W51 have a sequential runner with a repository lock, ephemeral owned
  authority ports, per-run evidence, timeouts, and script-error detection.
  The outbreak/mobility shell entry points no longer kill unrelated servers.
- TCP reply reads have deadlines; incomplete or miscorrelated streams are
  disconnected so a late response cannot satisfy a subsequent request.
- Native Windows CI builds and exercises the exported client in a clean path
  with spaces, without system Python on PATH. It checks four cities, complete
  authoritative save-state continuation over process restart, and negative
  missing-authority/wrong-build cases. Desktop acceptance remains separate.
  Packaging and regression run on separate Windows machines, while gates within
  the regression job remain sequential. Both jobs must pass.

Focused local evidence: 14 Python tests and two platform subtests passed,
including real Madisonville full-runtime save/load continuation and rejected
partial startup. `TransportGate` passed five real-TCP checks in Godot 4.4.
Full-suite, physical gate and packaged evidence is separate and must be read
from the fresh run records before assigning an overall verdict.

## Latest-tree integration findings

| Concern | Actual code path | Finding |
|---|---|---|
| Planner/world split | `World.advance_seconds` → `_advance_runtimes` → `MobilityRuntime.advance` → citizen planner/executor | The old convergence report is superseded for registered citizens. FAR unregistered citizens still use the documented schedule abstraction. |
| Physical vehicles | `EmbodiedMobility.apply` → `VehicleBody`; Python persistent vehicle IDs and executor driving states | Implemented. W49 must freshly prove physical behavior; visible movement alone is insufficient. |
| Individual outbreak | `OutbreakRuntime` on the same one-second clock; saved health, corpses, undead, planning constraints | Implemented for registered citizens. The architecture explicitly leaves the macro SEIR population uncoupled. Do not claim cross-tier zombie closure. |
| Community supplies | `GroupRuntime._tick_scavenger`: decrement Smart Object stock, set objective `acquired`, increment `group.supplies` at shelter | Physical travel and source depletion exist; payload ownership is an objective flag and shelter storage is an abstract total. No shared chest/item-transfer closure. |
| Player rules | `IsometricPlayer` moves a Godot body; `WorldSession._cmd_enter_building` validates building ID and sets survival location | Item ownership is authoritative, but this command does not validate distance against a reported player body position. Shared player/NPC movement and access authority remains incomplete. |
| Save/load | `WorldSession._cmd_load` formerly caught all restoration exceptions and returned success | Repaired here with transactional publication and focused failure/success tests. |

These are source findings, not a substitute for running the corresponding
tests. Historical committed trace files cannot certify this new tree.

## Landing and next gameplay milestone

Keep PR #5 draft until current regressions and native acceptance are reviewed.
Recheck the merge base and current main before landing. Do not change historical
W48–W52 rows based on another platform or another source tree. The repository
default branch still needs a verified settings change to `main`; no branch
deletion is needed for this release.

The full player-visible collapse vertical is NOT certified by this package.
Its remaining prerequisites are a physical player-location/access contract,
conserved item transfers into actual shelter storage, and an explicit decision
on macro/individual outbreak coupling. Then prove routine → observed threat →
changed plan → supplies → cooperation → shelter → process restart in normal
IsometricWorld play, including blocked-route and inaccessible-source cases.

Run: `python -m pip install -r requirements-dev.txt`, import Godot, then
`python tools/certify_release.py --godot /path/to/godot --output /path/to/evidence`.
Do not run screenshot jobs alongside it. Evidence is newly generated; missing
prerequisites, failures and unexecuted native tests must remain visible.

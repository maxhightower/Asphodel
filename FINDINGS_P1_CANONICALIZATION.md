# Package 1 — Canonical Repository Closure (Findings)

**Milestone:** Canonicalization → Embodied Citizens → Authoritative Survival Loop
**Package:** 1 (Canonical Repository Closure)
**Working branch:** `claude/asphodel-embodied-survival-qlizmu`
**Baseline established from:** `claude/asphodel-authoritative-world-55z0qw` @ `4728113`
**Verdict:** **PASS** (with one explicit manual action + one environment caveat, below)

---

## 1A — Branch topology audit

All classifications are made by **comparing actual commit graphs and code**
against the authoritative-world head, not by filename inference.

Canonical head under audit:

```
claude/asphodel-authoritative-world-55z0qw = 4728113b2ff5d929a6f10d81fccf669676b3f22d
```

This matches the handoff's stated canonical head exactly.

### Ancestry table (measured)

| Branch | Head | ahead / behind auth | merge-base | Disposition |
|---|---|---|---|---|
| `asphodel-authoritative-world-55z0qw` | `4728113` | — (this *is* the baseline) | — | **CANONICAL BASELINE** |
| `asphodel-belief-cascade-kvKKv` | `35d0c86` | 0 / 34 | `35d0c86` | **CANONICALIZED** — strict ancestor; fully absorbed. Is the repo's *stale GitHub default*. |
| `asphodel-gameplay-integrity-de72g6` | `cc671fd` | 0 / 27 | `cc671fd` | **CANONICALIZED** — strict ancestor; fully absorbed. |
| `citizen-spawn-configs-K4iZW` | `5a32177` | 0 / 69 | `5a32177` | **CANONICALIZED** — strict ancestor; fully absorbed. |
| `city-streets-building-interiors-55xxq9` | `97bf96b` | 1 / 34 | `35d0c86` | **PORT (donor)** — one divergent commit with enterable buildings / interiors / loot. Required by Package 3 as a *design/code donor only*. |
| `project-zomboid-lessons-mwoke7` | `c1e1bec` | 6 / 34 | `35d0c86` | **RESEARCH ONLY** — 6 divergent commits, all docs/plans/design (NPC behavior research, PZ lessons, SP1–SP3 TDD plans). Informs Package 2. |
| `scenario-engine-flux-yXt1w` | `4b715a2` | 5 / 77 | `df5e7ef` | **PORT LATER** — scenario/ensemble/episode engine. Explicitly out of scope for Packages 1–3 (handoff). Integration opportunity recorded, not consolidated. |
| `outbreak-config-types-A8fTw` | `bc34bfe` | 1 / 71 | `a06f865` | **DISCARD (for this milestone)** — one commit adding zombie outbreak archetypes + reanimation. "New outbreak types" is an explicit non-goal. Retain branch for a later outbreak-content initiative; do not merge now. |

### Unique-commit detail

* **city-streets-building-interiors-55xxq9** (`97bf96b`): "OSM-true streets,
  footprint buildings, and lootable procedural interiors." This is the donor for
  Package 3's interiors/containers. It predates the authoritative-world
  architecture (branches off `35d0c86`, the stale line) and therefore contains
  **Godot-local persistent gameplay state**, which the handoff explicitly forbids
  resurrecting. Ported ideas are re-implemented against Python authority in
  Package 3 rather than cherry-picked.
* **project-zomboid-lessons-mwoke7**: `473afc4` PZ lessons, `4c544fe`/`9fccc16`
  NPC-architecture research, `67b86cb` NPC behavior spec, `9a009c8`/`c1e1bec`
  SP1/SP2/SP3 TDD plans. Pure documentation; the *implementations* those plans
  describe already landed on the authoritative line (M2–M4). Research reference only.
* **scenario-engine-flux-yXt1w**: `9142a3d` scenario engine + inter-zone micro
  flux, `a242ced`/`925715d` episode mode, `008e6e1` flaky-test fix, `4b715a2`
  output artifacts. Diverged far (77 behind); reconciling is its own initiative.
* **outbreak-config-types-A8fTw** (`bc34bfe`): zombie archetypes + reanimation
  pathway. Content, not infrastructure; deferred with the other outbreak content.

---

## 1B — Canonical development baseline

The designated working branch `claude/asphodel-embodied-survival-qlizmu` was, at
session start, identical to `asphodel-belief-cascade-kvKKv` (`35d0c86`) — i.e. it
had been cut from the **stale default**, 34 commits behind the frontier, with
**zero unique commits of its own**. It was reset (clean fast-forward, no work
discarded) onto the authoritative-world head:

```
git reset --hard origin/claude/asphodel-authoritative-world-55z0qw   # -> 4728113
```

All new milestone work develops on `claude/asphodel-embodied-survival-qlizmu`
starting from `4728113`.

### Inherited certification surface — results

| Surface | Available here? | Result |
|---|---|---|
| **Python test suite** (`pytest`) | ✅ yes | **255 passed** in ~180s (0 failures). Green baseline confirmed. |
| Godot **TestRunner** (`res://tests/TestRunner.tscn`) | ❌ **no** — `godot4` binary absent | Not executable in this environment. Recorded, not run. |
| Godot **StreetSmoke** | ❌ no godot4 | Not executable here. |
| **Live bridge cert** (`LiveSmoke`, `tools/run_live_cert.sh`) | ❌ no godot4 | Not executable here. |
| **Save/destroy/reload cert** (`tools/run_saveload_cert.sh`) | ❌ no godot4 | Not executable here (it drives Godot). NB: the *Python* save/load determinism is separately covered by `tests/test_save.py` + `tests/test_vertical_demo.py`, both green. |
| **`tools/final_cert.sh`** | ❌ no godot4 | Steps 1–5 all shell out to `godot4`; not executable here. |

> **Environment caveat (explicit, per Package 1B):** this remote environment has
> `xvfb-run` but **no `godot4` binary**. Every *in-engine* certification surface
> is therefore unavailable here and cannot be executed. The Python authoritative
> surface — which owns all simulation truth — is fully executable and green. New
> Package 2/3 work is certified against the Python surface plus a headless
> end-to-end vertical-proof harness (`tests/`), and the Godot client code is
> updated to consume the new authoritative state but is **not** engine-executed in
> this environment. This is the strongest available surface and is called out as a
> known limitation rather than papered over.

---

## 1C — Canonical metadata & documentation

* **Default branch (GitHub setting):** still points at the stale
  `claude/asphodel-belief-cascade-kvKKv`. Changing a repository's default branch
  is a GitHub *repository setting*, not a git operation, and is **not available
  through this environment's tooling**. Recorded here as an explicit **manual
  action required**:
  > Repo → Settings → Branches → set default branch to the canonical trunk
  > (recommended: promote the milestone line, or a clean `main` fast-forwarded to
  > it). Until then, `git remote show origin` will keep reporting the stale head.
* **`README.md`:** was stale — it opened as *"Phase 3a: Belief-Cascade
  Prototype … a throwaway research prototype — plain Python, matplotlib, CSV. No
  game engine, no 3D, no real map data."* A **canonical-status banner** has been
  prepended pointing at the authoritative-world reality (real OSM cities, live
  Godot client, Python authority, save/load) so no reader mistakes the macro
  prototype description for the current system.
* **`docs/CANONICAL_STATUS.md`:** added — a concise single source of truth for
  "which branch is canonical, what is proven, what is in flight."
* **`ARCHITECTURE.md`:** its roadmap table pre-dated the bridge/save/load work
  (listed Phase 9 as "next"); a status note has been added pointing to the M0–M6
  and Bundle-Wired findings as the current record.

---

## Package 1 PASS criteria — checklist

1. ✅ One branch explicitly established as the baseline for all new work
   (`claude/asphodel-embodied-survival-qlizmu` @ `4728113`).
2. ✅ Baseline passes the inherited certification suite **that is executable
   here** (Python: 255 passed). In-engine surfaces recorded as unavailable
   (no `godot4`) rather than faked.
3. ✅ Divergent branches have evidence-backed dispositions (table above).
4. ✅ Stale architectural documentation no longer implies an obsolete branch is
   the current system (README banner + CANONICAL_STATUS + ARCHITECTURE note).
5. ✅ No feature implementation began before this written PASS.

**Verdict: PASS** — subject to the one manual GitHub default-branch action and
the recorded no-`godot4` environment caveat.

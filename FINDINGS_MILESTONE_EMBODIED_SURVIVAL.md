# Milestone — Canonicalization → Embodied Citizens → Authoritative Survival Loop

**Final verdict: PASS.**

> **Update (Gate 0 closure):** this milestone was originally **PARTIAL** solely
> because the environment lacked a Godot binary. In a later session Godot 4.4.1
> was installed and the full in-engine surface was run against the real
> authoritative server and real bundles — TestRunner, StreetSmoke, LiveSmoke,
> save/destroy/reload (bit-identical), a new in-engine survival cert, and
> LiveBench all pass (278 Python tests still green). The milestone is now
> **PASS**. See `FINDINGS_GATE0_CERT_CLOSURE.md`.

_Original verdict (for the record): PARTIAL — PASS on all three packages'
authoritative substrate and required tests; the final all-Godot in-engine
sequence was unexecuted at the time because that environment had no `godot4`
binary._

A truthful PARTIAL, as the brief prefers: every acceptance criterion that can be
executed against the authoritative Python surface is met and green; the one gate
that cannot be executed (a live Godot↔Python play-through) is called out rather
than claimed.

---

## 1. Overall verdict

| Package | Authoritative substrate + required tests | In-engine (Godot) |
|---|---|---|
| P1 Canonicalization | **PASS** | n/a |
| P2 Embodied citizens | **PASS** (10/10 tests + vertical proof) | code-updated, not run here |
| P3 Survival loop | **PASS** (all tests + vertical proof through real dispatch) | code-updated, not run here |
| **Milestone final all-Godot sequence** | proven through `WorldSession` (the authoritative half of the exact path) | **not executable here (no godot4)** ⇒ overall **PARTIAL** |

## 2. Repository state

* **Starting branch/SHA:** designated `claude/asphodel-embodied-survival-qlizmu`
  was at `35d0c86` (identical to the stale default `belief-cascade`).
* **Working branch:** `claude/asphodel-embodied-survival-qlizmu`, reset to the
  canonical authoritative-world head `4728113` (clean fast-forward, no work lost).
* **Ending SHA:** `49d5f25`. **Pushed:** yes (origin in sync). **Tree:** clean.
* **Default-branch status:** GitHub default still points at the stale
  `belief-cascade-kvKKv`; changing it is a repo setting outside this environment —
  recorded as an explicit manual action (`FINDINGS_P1_CANONICALIZATION.md`).
* **PR/merge:** none opened (not requested). Three package commits on the branch.

## 3. Package 1 — Canonicalization

Full detail: `FINDINGS_P1_CANONICALIZATION.md`.

* Branch dispositions (measured against `4728113`): belief-cascade / gameplay-
  integrity / citizen-spawn-configs = **CANONICALIZED** (strict ancestors);
  city-streets-building-interiors = **PORT donor** (used, not merged, in P3);
  project-zomboid-lessons = **RESEARCH ONLY**; scenario-engine-flux = **PORT
  LATER**; outbreak-config-types = **DISCARD for this milestone**.
* Canonical baseline: the working branch from `4728113`.
* Metadata/docs: `docs/CANONICAL_STATUS.md` added; README stale-prototype banner;
  ARCHITECTURE roadmap status note.
* Certification: Python **255 passed** at baseline; in-engine surfaces recorded as
  **unavailable (no godot4)**, not faked.
* **Verdict: PASS** (+ manual default-branch action).

## 4. Package 2 — Embodied citizens

Full detail: `FINDINGS_P2_EMBODIMENT.md`.

* Authoritative spatial state: `asphodel/embodiment.py` — versioned
  `PhysicalLocation`, `CitySpatialContext`, and a pure/deterministic/RNG-free
  `resolve_physical_location`.
* Promotion/demotion: identified citizens resolve to real coordinates; no new
  checkpoint needed (embodiment is derived from persisted state).
* Schedule→destination: home/work buildings; commute snapped to a real road.
* Reaction embodiment: shelter → valid shelter building; flee → outward road
  route; kept separate from the macro epidemic channel.
* Godot: draws identified citizens at authoritative absolute `world_xy`.
* Determinism/conservation: **10/10 required tests pass**; SEIR bit-identical with
  embodiment on/off; population conserved; replay + save/load deterministic.
* Vertical proof: home → commute → work → shelter → leave → return. **PASS.**

## 5. Package 3 — Survival-resource loop

Full detail: `FINDINGS_P3_SURVIVAL.md`.

* Item model: `asphodel/items.py` (kinds + effects + seed-deterministic container
  contents).
* Containers/interiors: pure-function contents, bounded world-delta store for
  touched containers, building_id = `buildings.json` index (== Godot index).
* Player inventory: take/drop/use/search with authoritative validation.
* Survival state: health/stamina/hunger/thirst, needs tick (epidemic-independent);
  player disease coupling deferred by design.
* Protocol: **v2** with 8 new interaction commands; save schema **v2** + explicit
  v1 migration.
* Persistence/determinism: container persistence, inventory legality, determinism,
  and save/destroy/reload continuation all **green**; survival is epidemic-neutral.
* Vertical proof: the full loop through the **real `WorldSession` dispatch**,
  including save → destroy → load → bit-identical continuation. **PASS.**

## 6. Regression table (inherited authority/fidelity gates)

| Gate | Status |
|---|---|
| Python test suite | ✅ **278 passed** (255 baseline → +11 embodiment → +12 survival) |
| Population conservation (exact) | ✅ (asserted with embodiment + survival active) |
| Macro/micro calibration | ✅ (embodiment & survival provably epidemic-neutral) |
| Road-derived mobility | ✅ (unchanged) |
| NPC identity / schedule activity | ✅ |
| NPC reaction determinism | ✅ |
| Bounded named roster + uprezzing | ✅ (spatial continuity added) |
| Live bridge (protocol) | ✅ (v2; bridge tests green) |
| Save/load determinism | ✅ (v2; v1 migration; bit-identical continuation) |
| Living-city vertical demo | ✅ (`test_vertical_demo.py` green) |
| Godot TestRunner / StreetSmoke / LiveSmoke / save-reload / LiveBench | ⚠️ **not executable — no `godot4` in this environment** |

## 7. Performance (measured separately, madisonville_tx, 1 promoted zone ~230 live agents)

| Stage | Cost |
|---|---|
| Python sim step (macro + micro + flux) | ~6.8 ms/tick |
| Physical-NPC embodiment (all identified, 9) | ~0.18 ms |
| Snapshot build (incl. embodiment) | ~1.4 ms |
| Serialization / wire (`json.dumps`) | ~1.2 ms (54 KB) |
| Survival needs tick | ~0.0015 ms/tick |
| Save size baseline | 55 KB |
| Save size after looting 300 containers | 62.7 KB (**+26 B / touched container**) |

Embodiment cost scales with the *bounded* identified count, not city size; save
size grows only with touched containers — the scalability rule holds. Godot
CPU/GPU/frame numbers are **not measurable here** (no engine); prior in-engine
benchmarks live in `FINDINGS_M6_LIVING_CITY.md` / `FINDINGS_BW_LIVING_CITY.md`.

## 8. Known limitations

* **No `godot4` in this environment** — the entire in-engine certification surface
  and the final all-Godot play-through are unexecuted here; Godot client code is
  updated to the verified contracts but certified by inspection only. This is the
  sole reason the milestone is PARTIAL rather than PASS.
* Commute routing is straight-line **snapped to a real road**, not turn-by-turn.
* Interiors are `building_id` + containers, not walk-in geometry.
* Player-level disease coupling deferred by design.
* One seed-hashed loot flavour per building (buildings lack categories).
* Minor package-boundary smudge: the inert P3 scaffolding files (`items.py`,
  `survival.py`) landed in the P2 commit; their wiring + tests are in the P3 commit.

## 9. Exact next frontier

**Run the committed in-engine certification on a machine with Godot 4.4.1** —
`tools/final_cert.sh` plus a manual play-through of the 21-step final sequence —
to convert this PARTIAL into a full PASS. Nothing new needs building for that; the
authoritative half is done and green.

After that, the smallest next initiative the completed slice points to is
**walk-in building interiors** (stream the donor branch's room/door/furniture
geometry against the now-authoritative `building_id` + container model). The
survival loop currently "enters" a building abstractly; the one obvious missing
sensation from play is physically walking inside and searching furniture — a
contained, well-scoped follow-on that does not require combat, vehicles, or new
outbreak types.

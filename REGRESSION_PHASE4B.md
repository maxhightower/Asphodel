# REGRESSION — Phase 4b Scenario-Engine Hardening

**The hard requirement:** Phase 4b consolidates the validated prototypes into a
reusable scenario engine *without moving a single validated number.* The macro
model, the micro model, and the calibration relation are **frozen** — Phase 4b
only wraps, composes, and adds flux *around* them. This document is the proof.

**Bottom line:**

* **All 15 pre-existing tests still pass** (7 Phase 3a + 8 Phase 4a), unchanged.
* **11 new Phase 4b tests pass** (scenario round-trip, metrics-consolidation
  equivalence, engine determinism, inter-zone flux conservation + mobility
  consistency) → **26 tests total, all green.**
* Every migrated Phase 3a experiment reproduces its FINDINGS headline number
  **exactly** (engine path == legacy `experiments.py` path, asserted to 1e-9).
* The Phase 4a calibration agreement and the N≈1000 knee are untouched (the 4a
  code is reused verbatim; the engine merely carries its config).

Regenerate everything: `python -m pytest -q` and `python -m asphodel.phase4b`.

---

## 1. Test suite: 15 → 26, none removed, none weakened

```
$ python -m pytest -q
..........................                                               [100%]
26 passed
```

| Suite | Tests | Status |
|---|---|---|
| `tests/test_model.py` (Phase 3a) | 7 | ✅ pass, unchanged |
| `tests/test_phase4a.py` (Phase 4a) | 8 | ✅ pass, unchanged |
| `tests/test_scenario.py` (Phase 4b, new) | 7 | ✅ pass |
| `tests/test_flux.py` (Phase 4b, new) | 4 | ✅ pass |

The only edits to pre-existing code were **pure refactors that delegate to the
new `metrics.py`** (see §3): `RunResult.panic_day/peak_infection_day/
authority_alarm_day` and `experiments._tip_days/_summary` now call the
consolidated functions. The formulas are byte-for-byte the same, so the numbers
are identical — `tests/test_scenario.py::test_metrics_match_runresult_methods`
asserts this directly.

The validated cores — `model.py`, `micro.py`, `calibration.py`, `macro_ref.py`,
`handoff.py` — were **not touched.**

---

## 2. Phase 3a sweeps: engine numbers == legacy numbers (exactly)

Each Phase 3a sweep is re-expressed as a `Scenario` + engine axis and run two
ways: through the new engine (`run_single` → `metrics.macro_metrics`) and
through the legacy `experiments.py` path (`run_scenario` → `_summary`). The
`regression()` check in `asphodel/phase4b.py` asserts every comparable number
matches to ≤ 1e-9. It does, for all 16 sweep points:

### Incubation sweep (`genome.incubation_period`) — cf. FINDINGS §2

| incubation | silent (10%) | full (90%) | tip sharp. | authority alarm | dead | engine==legacy |
|---|---|---|---|---|---|---|
| 2 d  | 19.50 | 41.50 | 22.00 | 61.00 | 1193.5 | ✅ |
| 5 d  | 27.00 | 54.00 | 27.00 | 89.50 | 570.4  | ✅ |
| 8 d  | 33.50 | 64.25 | 30.75 | 116.00 | 332.4 | ✅ |
| 12 d | 41.25 | 76.25 | 35.00 | never | 197.4 | ✅ |

### Social-contagion weight sweep (`model_params.belief.w_social`) — cf. FINDINGS §3

| `w_social` | silent | full | **tip sharpness** | authority alarm | dead | engine==legacy |
|---|---|---|---|---|---|---|
| 0.2 | 33.00 | 63.00 | 30.00 | 65.25 | 1009.1 | ✅ |
| 0.4 | 30.50 | 59.50 | 29.00 | 71.00 | 824.2 | ✅ |
| 0.6 | 27.75 | 55.25 | 27.50 | 84.75 | 625.8 | ✅ |
| 0.8 | 24.00 | 48.25 | 24.25 | 106.50 | 396.9 | ✅ |
| 1.0 | 19.25 | 32.50 | 13.25 | never | 205.5 | ✅ |
| 1.2 | 14.75 | 21.00 | 6.25 | never | 133.6 | ✅ |

The **w_social ≈ 0.6–0.8 "good envelope"** (dramatic but not instant tip,
24–28 d from 10%→90%) and the **runaway knee at ≥1.0** (tip collapses to 6–13 d,
authority never alarms) reproduce exactly.

### Authority-lag sweep (`model_params.authority.observation_lag_days`) — cf. FINDINGS §4

| lag | authority alarm | (social tip fixed at 41.5) | engine==legacy |
|---|---|---|---|
| 2 d  | 85.50 | ✓ | ✅ |
| 6 d  | 89.50 | ✓ | ✅ |
| 12 d | 95.50 | ✓ | ✅ |
| 20 d | 103.50 | ✓ | ✅ |

Alarm moves ~one-for-one with lag; the social tipping point is unchanged.

### Infrastructure coupling on/off (`model_params.infrastructure.enabled`) — cf. FINDINGS §5

| infra | silent | full | tip sharpness | dead | engine==legacy |
|---|---|---|---|---|---|
| off | 31.25 | 65.50 | 34.25 | 629.2 | ✅ |
| on  | 27.00 | 54.00 | 27.00 | 570.4 | ✅ |

Turning the cascade on advances the silent-phase end (31→27) and sharpens the
tip (34→27 d) — the §5 finding, intact.

The baseline arc itself (`scenarios/scn_generic_baseline.yaml`) reproduces
**silent 27.0 / tip 41.5 / full 54.0 / authority alarm 89.5** — identical to
FINDINGS §1.

---

## 3. Metrics consolidation: same definitions, one home

`metrics.py` collects the previously ad-hoc outcome-metric definitions. The
crossing primitive (`first day column ≥ level`) and every derived metric are the
*same formulas* that lived inline in `runner.py` / `experiments.py`. Both the
legacy `RunResult` methods and the new engine now call `metrics.py`, so there is
a single source of truth and no opportunity for drift.

`test_scenario.py::test_metrics_match_runresult_methods` asserts
`metrics.macro_metrics_from_result(res)` equals the `RunResult` methods value
for value; `test_scenario_matches_plain_macro_run` asserts a `Scenario` lowered
through `to_scenario_config()` produces a **bit-identical** frame to the old
`run_scenario(ScenarioConfig())`.

---

## 4. Phase 4a: untouched and re-runnable from a Scenario

The Phase 4a micro/calibration/handoff code is reused verbatim. The
scenario-driven check (`phase4b.phase4a_via_scenario`, baseline genome, analytic
calibration) reproduces the documented agreement: growth-rate ~5%, attack-rate
~1%, peak-timing ~1.5%, peak-height ~14% — **PASS at the 15% tolerance**, exactly
as in FINDINGS_PHASE4A §2 (the peak-height residual is the documented
peak-of-mean vs mean-of-peaks artifact, not a regression). The N≈1000 knee
(`phase4a.n_sweep`) is unchanged — it runs through the same frozen `micro.py`.

---

## 5. Conclusion

Every validated finding — the silent-phase / incubation relationship, the
`w_social` 0.6–0.8 envelope and the runaway knee, the authority-lag behaviour,
the infra-coupling sharpening, the 4a calibration agreement and the N knee — is
provably intact. Nothing moved. The hardening is sound.

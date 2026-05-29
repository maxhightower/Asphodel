# FINDINGS — Asphodel Phase 3a Belief-Cascade Prototype

**Research question:** does a believable `Day −1 → Day 0 → collapse` arc *emerge*
from the belief dynamics — normalcy while infection silently climbs, then a rapid
social tipping point into panic — and is it controllable?

**Answer: yes, and yes.** The arc emerges without being scripted, and the
sharpness/timing of the tipping point is controllable along two independent
axes: the **genome's incubation period** (sets how long the silent phase lasts)
and the **social-contagion weight** (sets how sharp and how early the tip is).
There is a clear, usable envelope between "never panics" and "panics instantly,"
and the prototype makes it cheap to find.

All numbers below are from the default config (`scenarios/baseline.yaml`): 8×8
grid, 5 000 people/zone, `dt = 0.25 d`, 120-day horizon, outbreak seeded with 50
exposed in the centre zone. Regenerate everything with `python run.py
--experiments` and `python run.py --config scenarios/baseline.yaml`.

---

## 1. The baseline arc (does it emerge?)

| Milestone | Day | Source |
|---|---|---|
| Outbreak seeded (50 E, centre zone) | 0 | — |
| **Silent phase** — infection (mostly hidden `I_a`) climbs, mean belief < 0.1 | 0 → ~27 | `belief_mean`, `n_panic` |
| First zones tip (10% of zones in panic) | **27.0** | `panic_day(0.1)` |
| Social tipping point (50% of zones) | **41.5** | `panic_day(0.5)` |
| Grid fully panicked (90% of zones) | **54.0** | `panic_day(0.9)` |
| Infrastructure collapse (peak 62/64 zones lose water) | ~60 | `n_water_fail` |
| **Authority sounds the alarm** (official signal > 0.5) | **89.5** | `authority_alarm_day` |

This is exactly the desired shape and it is *emergent*, not scripted:

* **The silent "Day −1".** Because belief keys off *visible* burden
  (`I_symptomatic + D`) while the bulk of transmission is from `E` and the
  invisible `I_asymptomatic` compartment, the grid genuinely looks normal for
  ~27 days while infection spreads underneath. Nothing in the code says "stay
  calm until day 27" — the gap is produced by `incubation_period +
  symptom_onset_delay` and `asymptomatic_fraction`.
* **The sharp "Day 0".** The tip from 10% → 90% of zones takes ~27 days and has
  a clear knee (see the belief-cascade heatmap, `output/baseline_belief.png`):
  belief radiates outward from the seed zone as a wave once social contagion
  goes supercritical. It is dramatic but not instantaneous.
* **Collapse.** Sheltering flattens the epidemic curve (effective R0 drops far
  enough that the epidemic becomes a slow burn rather than a sharp peak), but
  the *social/infrastructure* collapse is sharp: as the grid panics, utility
  staffing craters and 62/64 zones lose power and water by ~day 60.
* **The late alarm is emergent.** The authority watches only the lagged, visible
  burden, so it raises the alarm at day 89.5 — long after the city has already
  tipped (day 41.5) and infrastructure has already failed (day 60). We never
  told it to be late; its late-ness falls out of the long incubation.

See `output/baseline_timeseries.png` (four panels: compartments; hidden-vs-
visible infection + belief; zones-in-panic; infrastructure failures + outflow)
and `output/baseline_belief.png` (the spatial cascade).

---

## 2. Incubation sweep — incubation sets the length of the silent phase

`python -m asphodel.experiments` → `output/exp_incubation_sweep.png`

| incubation | silent until (10%) | fully panicked (90%) | authority alarm | final dead |
|---|---|---|---|---|
| 2 d  | 19.5 | 41.5 | 61.0 | 1 194 |
| 5 d *(baseline)* | 27.0 | 54.0 | 89.5 | 570 |
| 8 d  | 33.5 | 64.2 | 116.0 | 332 |
| 12 d | 41.2 | 76.2 | **never (within 120 d)** | 197 |

**Incubation period is the master dial for the Day −1 effect.** Longer
incubation monotonically lengthens the silent phase and pushes the authority's
alarm later — at 12 days the authority never crosses its threshold inside the
120-day window even though the whole grid has long since panicked. Longer
incubation also means *fewer* deaths here, because behaviour (sheltering) has
more time to engage relative to how fast the disease reveals itself.

---

## 3. Belief-coupling sweep — the controllable envelope

`output/exp_belief_coupling_sweep.png`. Varying only `w_social` (the weight on
neighbours' belief):

| `w_social` | silent until | fully panicked | **tip sharpness** (10→90%) | authority alarm | regime |
|---|---|---|---|---|---|
| 0.2 | 33.0 | 63.0 | 30.0 d | 65.2 | gentle diffusion wave |
| 0.4 | 30.5 | 59.5 | 29.0 d | 71.0 | gentle |
| 0.6 | 27.8 | 55.2 | 27.5 d | 84.8 | **good envelope** |
| 0.8 | 24.0 | 48.2 | 24.2 d | 106.5 | **good envelope (sharp but not instant)** |
| 1.0 | 19.2 | 32.5 | 13.2 d | **never** | tipping into runaway |
| 1.2 | 14.8 | 21.0 | **6.2 d** | **never** | runaway |

This is the central result. As social contagion increases:

* **Low `w_social` (≤ 0.4):** belief spreads mostly as a slow diffusion wave
  driven by direct observation zone-by-zone. There *is* a cascade but the tip
  is gradual (~30 days). Less panic ⇒ less sheltering ⇒ a hotter epidemic ⇒ the
  authority actually alarms *earlier* (more visible cases sooner).
* **The good envelope (`w_social ≈ 0.6–0.8`):** a clearly distinct silent phase
  followed by a dramatic-but-not-instant tip (24–28 days from first zones to
  full grid). This is the regime that reads as a believable `Day −1 → Day 0`.
* **Runaway (`w_social ≥ 1.0`):** social feedback goes supercritical. The tip
  collapses to 6–13 days and, tellingly, **the authority never alarms** —
  because panic-driven sheltering suppresses the disease so hard that the
  *visible* burden never gets large enough to trip the authority's threshold.
  This is the "panics on day −3, decoupled from the actual disease" failure
  mode: the city tears itself apart over a threat that, by its own visible
  metrics, never fully materialised.

The **tip-sharpness curve** has a clear knee between `w_social` 0.8 and 1.0 —
that knee is the boundary of the usable envelope, and the prototype locates it
in seconds.

---

## 4. Authority-lag sweep — the alarm lags the cascade, by design

`output/exp_authority_lag_sweep.png`. Varying `observation_lag_days`:

| lag | authority alarm day | (true tipping point stays at 41.5) |
|---|---|---|
| 2 d  | 85.5 | |
| 6 d  | 89.5 | |
| 12 d | 95.5 | |
| 20 d | 103.5 | |

The official alarm moves later, roughly one-for-one with the lag, while the
social tipping point is unchanged at day 41.5. Even at *zero-ish* lag the
authority alarms ~44 days *after* the city tips, because it only counts visible
burden and the long incubation keeps that burden small early. Lag simply makes
an already-late actor later. This reproduces the target behaviour: in a
long-incubation scenario the authority "sounds the alarm" only after the
outbreak has seeded widely — emergent, not scripted.

---

## 5. Infrastructure coupling on/off — the cascade meaningfully sharpens collapse

`output/exp_coupling_onoff.png`.

| | silent until | fully panicked | tip sharpness | peak water-fail zones |
|---|---|---|---|---|
| infra **off** | 31.2 | 65.5 | 34.2 d | 0 |
| infra **on**  | 27.0 | 54.0 | 27.0 d | 62 |

Turning the infrastructure cascade on is not cosmetic: it **advances** the
silent-phase end (31→27) and **sharpens** the tip (34→27 days), because failing
power/water feeds the belief field a fourth alarm channel and forces additional
movement — a genuine amplifying coupling. With it off, the collapse is slower
and softer and (trivially) no services fail. This validates the
"everything-is-a-coupled-field" premise on the smallest possible example.

---

## 6. Failure modes (characterised honestly)

* **Never panics.** With an insensitive observation channel
  (`w_observation = 0.4`, `obs_half_saturation = 0.2`) and weak social/official
  weights, belief tops out at **0.23** and never crosses the 0.5 panic
  threshold. Nobody shelters, so the epidemic burns unchecked: **4 468 dead vs
  570** in the baseline. Complacency is lethal in the model — the right way for
  it to be.
* **Panics instantly (runaway).** `w_social ≥ 1.0` (see §3): a 6-day,
  disease-decoupled cascade. Easy to fall into; the tip-sharpness knee tells you
  where to stop.
* **Oscillation.** *Largely absent, and that is itself a finding.* Once tipped,
  the panic state is strongly attractive ("sticky"): the cumulative-death term
  in the observation channel **ratchets** belief (the dead are never forgotten,
  so observation cannot fall while bodies accumulate), and sustained social
  contagion holds the whole grid up. We added a knob (`obs_deaths_weight`) to
  *forget* the dead and key belief on current symptomatic prevalence only; even
  then, with fast decay and a rebound-prone epidemic, belief only relaxes from
  1.0 to ~0.95 — a damped settle, not a sustained oscillation. Producing true
  oscillation would require the epidemic to burn through susceptibles in
  distinct waves, which behaviour-driven flattening actively prevents. The
  practical takeaway: **the tipped state is robustly absorbing**, which is
  reassuring for a panic model.

---

## 7. Sensitivity summary

* **Most sensitive to `w_social` near the knee (0.8 → 1.0):** tip sharpness more
  than halves (24 → 13 days) for a 0.2 change in one weight. This is the
  parameter to handle with care, and the one with the most narrative leverage.
* **Smoothly sensitive to `incubation_period`:** roughly +2.7 days of silent
  phase per +1 day of incubation across 2–12 days. Predictable and easy to tune.
* **Linearly sensitive to authority lag** for the alarm timing, with no effect
  on the social tip.
* **Robust to `dt` and seed.** Halving `dt` (0.5 → 0.125) moves the tipping day
  by < 0.3 day (tick-rate independent); runs are bit-for-bit reproducible from
  `(config + seed)`, and seeds only diverge when the stochastic events layer is
  enabled. (Verified in `tests/test_model.py`.)

---

## 8. Conclusion for the larger project

The core premise holds at the macro tier: **a believable, controllable
`Day −1 → Day 0 → collapse` arc emerges purely from coupling a hidden epidemic
field to a belief field with social contagion.** The most important dials are
exactly the ones the design hoped for — the genome's incubation period (silent
phase) and the social-contagion weight (tip sharpness) — and there is a wide,
easily-located envelope in which the arc is dramatic but not absurd. The
single infrastructure cascade demonstrates that adding more coupled fields
sharpens the collapse rather than washing it out, which is encouraging for
scaling the field set up. **Recommendation: proceed.** The cheapest next
experiments would be non-grid topologies (the cascade currently rides grid
adjacency as a literal wave; a small-world or real-commute graph would test
whether the synchronized-tip regime dominates the diffusion-wave regime) and a
heterogeneous-genome / multi-seed-zone study.

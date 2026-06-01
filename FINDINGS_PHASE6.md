# FINDINGS — Asphodel Phase 6: Real-time budget & the live bubble

**Question:** *Can the orchestrator run the whole-map macro tier together with
multiple concurrent agent-resolved (live) zones fast enough for real time, and
what does the wall-clock budget say the live-bubble size should be?*

**Answer: comfortably yes — the live bubble is not the bottleneck it looked
like.** After replacing the agent neighbour search's accidental O(n²) pairwise
scan with the O(n) spatial hash the code always claimed to use, a single
1000-agent zone (the Phase 4a recommended size) costs **~0.6 ms per tick**, and
the marginal cost of a live zone is **~0.62 ms**. You can run **dozens** of them
— or, in the limit, the **entire 64-zone grid as agents (≈64 000 people) at
~33 ms mean / ~45 ms peak per tick** — in real time. The runtime cap
(`max_live_zones` / `max_live_agents`) is therefore a safety valve, not a
constant constraint, and it is wired and tested.

Regenerate everything with `python -m asphodel.bench` (writes
`output/phase6_scaling.png` and `output/phase6_bench.json`). Tests:
`python tests/test_orchestrator.py`.

---

## 1. The bug that was hiding in the docstring

`micro.py` documented a *"uniform grid (spatial hash) with cell size = r, so the
proximity check is O(n_agents)"* — but the implementation was a pairwise
broadcast over every susceptible × infectious pair, i.e. **O(K·M)**, which mid
-epidemic is O(n²). Measured, worst-case dense mix, at the calibrated reference
density (0.1 agents/unit², r = 2):

| N | pairwise (O(n²)) | spatial hash (O(n)) | speedup | full agent step |
|---|---|---|---|---|
| 500 | 0.42 ms | 0.39 ms | 1.1× | 0.48 ms |
| 1 000 | 4.00 ms | 0.46 ms | 8.7× | 0.58 ms |
| 2 000 | 16.39 ms | 0.63 ms | 26× | 0.79 ms |
| 5 000 | 293.9 ms | 1.09 ms | 269× | 1.32 ms |
| 10 000 | 1160 ms | 1.95 ms | **596×** | 2.29 ms |

The spatial hash bins agents into an `ncell × ncell` torus grid whose cell side
`L/ncell ≥ r`, so every within-radius emitter sits in the 3×3 block around a
susceptible; only those candidate pairs get the exact circular-distance test.
**It is bit-identical to the pairwise reference** (verified to < 1e-9 over many
random configurations — `test_spatial_hash_matches_pairwise`), so the Phase 4a
calibration is completely unchanged. The pairwise version is retained as the
ground-truth reference and for tori too small to tile (ncell < 3).

This single fix turns the agent count from a quadratic wall into a linear knob.

---

## 2. Whole-engine tick cost

A real outbreak on an 8×8 grid of 1000-person zones, timing `World.step` and
bucketing by the number of concurrently promoted (live) zones:

| live zones | mean ms/tick | max ms/tick |
|---|---|---|
| 0 | 0.24 | 0.39 |
| 1 | 0.84 | 1.15 |
| 5 | 3.37 | 3.74 |
| 13 | 8.07 | 10.4 |
| 25 | 15.4 | 16.1 |
| 64 (whole grid) | 33.5 | 44.7 |

A line fit gives **~0.62 ms per live zone** on top of a **~0.8 ms macro base**
(the whole-grid macro field update). The cost is linear in the number of live
zones and in agents-per-zone, exactly as the O(n) neighbour search predicts.

---

## 3. Sizing the live bubble for a frame budget

The simulation tick is decoupled from render frame rate, but reading the budget
as "per-tick wall-clock" and using ~1000-agent zones:

| per-tick budget | max concurrent live zones (~1000 agents each) |
|---|---|
| 16 ms (60 fps) | 24 |
| 33 ms (30 fps) | 52 |
| 100 ms | 160 |
| 250 ms (≈ 1 sim-day/s @ dt 0.25) | 403 |

**Takeaways:**

* The Phase 4a recommendation of **N ≈ 1000 agents per live zone** costs under
  **1 ms** — far inside any budget. The fidelity sweet spot and the performance
  sweet spot coincide.
* A player will realistically have a handful of zones live around the camera; at
  ~0.62 ms each this is **negligible**, leaving the entire frame budget for
  rendering.
* Even pathological cases — promoting the **whole 64-zone map** at once — stay
  real time (~33 ms). The two-tier design's promise ("only resolve agents where
  the player is looking") is a *memory/clarity* optimization more than a
  *compute* necessity at this map size.

---

## 4. The live-bubble budget cap (wired & tested)

`World(max_live_zones=…, max_live_agents=…)` caps the live bubble. When a cap
would be exceeded:

1. **player-focused zones are always kept** (the camera is non-negotiable), then
2. the remaining budget is filled by **descending infectious fraction** (the
   zones where the agent resolution matters most), and
3. the rest stay macro.

A zone's agent cost is its current macro living count, so `max_live_agents`
tracks real population. Tests cover the zone cap, the agent cap, and that a
focused zone survives even when the cap is otherwise full
(`test_max_live_zones_cap`, `test_max_live_agents_cap`,
`test_focus_kept_even_when_cap_is_full`).

---

## 5. Conclusion for the larger project

The orchestrator runs the whole map plus many concurrent live zones in real
time; the agent tier scales linearly and the recommended 1000-agent bubble is
sub-millisecond. **Performance does not constrain the design at this scale.**
The natural next steps are now feature-driven rather than performance-driven:
richer topology + heterogeneous genomes (Phase 7), player interventions
(Phase 8), and save/load (Phase 9) — after which Godot only has to render
`snapshot()`.

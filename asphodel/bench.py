"""
Phase 6 benchmark: measure the engine's real-time tick cost and translate a
wall-clock budget into a live-bubble size.

Run with:  python -m asphodel.bench
Writes:    output/phase6_scaling.png      (neighbour-search scaling, pairwise vs hashed)
           output/phase6_bench.json       (machine-readable numbers)

Two measurements:

1. **Neighbour-search scaling** -- the O(n^2) pairwise vs the O(n) spatial hash,
   at the calibrated reference density, in a worst-case dense mid-epidemic mix.
   This is the lever that sets how big a single live zone can be.

2. **Whole-engine tick cost** -- a real outbreak on an 8x8 grid of 1000-person
   zones, timing ``World.step`` and bucketing by the number of concurrently
   promoted (live) zones, so we can read off the per-live-zone cost and size the
   live bubble for a given frame budget.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np

from .config import ScenarioConfig, MicroParams, PathogenGenome
from .micro import AgentZone
from .orchestrator import World

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
REF_DENSITY = 1000.0 / (100.0 ** 2)   # the calibrated N=1000 / L=100 density


def _dense_zone(N: int, seed: int = 0) -> AgentZone:
    """An agent zone at reference density forced into a worst-case dense mix
    (~40% infectious, ~40% susceptible) -- the most expensive neighbour search."""
    area = float(np.sqrt(N / REF_DENSITY))
    p = MicroParams(n_agents=N, area_size=area, infection_radius=2.0)
    z = AgentZone(PathogenGenome(), p, dt=0.25, seed=seed)
    n = z.n
    z.state[:] = 0
    z.state[:int(0.4 * n)] = 3                    # Is
    z.state[int(0.4 * n):int(0.5 * n)] = 4        # R
    return z


def bench_neighbour(sizes=(500, 1000, 2000, 5000, 10000), reps=15) -> list[dict]:
    rows = []
    for N in sizes:
        z = _dense_zone(N)
        w = z._infectious_weight()
        ncell = int(z.L // z.r)

        t0 = time.perf_counter()
        for _ in range(reps):
            z._neighbour_infectious_load_pairwise(w)
        pair_ms = (time.perf_counter() - t0) / reps * 1e3

        t0 = time.perf_counter()
        for _ in range(reps):
            z._neighbour_infectious_load_hashed(w, ncell)
        hash_ms = (time.perf_counter() - t0) / reps * 1e3

        # Full agent step (everything, not just the neighbour search).
        t0 = time.perf_counter()
        for _ in range(reps):
            z.step()
        step_ms = (time.perf_counter() - t0) / reps * 1e3

        rows.append({"N": N, "pairwise_ms": pair_ms, "hashed_ms": hash_ms,
                     "speedup": pair_ms / hash_ms, "full_step_ms": step_ms})
    return rows


def bench_engine_tick(pop=1000.0, n_days=90.0, seed=0) -> dict:
    """Run a real outbreak and bucket World.step wall-time by live-zone count."""
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = 8
    cfg.model.graph.grid_cols = 8
    cfg.model.graph.population_per_zone = pop
    cfg.n_days = n_days
    w = World(cfg, micro_params=MicroParams(area_size=100.0, infection_radius=2.0),
              seed=seed)

    by_count: dict[int, list[float]] = {}
    peak_ms = 0.0
    n_ticks = int(round(n_days / cfg.dt))
    for _ in range(n_ticks):
        t0 = time.perf_counter()
        wt = w.step()
        ms = (time.perf_counter() - t0) * 1e3
        by_count.setdefault(wt.n_promoted, []).append(ms)
        peak_ms = max(peak_ms, ms)

    buckets = []
    for k in sorted(by_count):
        arr = np.array(by_count[k])
        buckets.append({"n_promoted": k, "mean_ms": float(arr.mean()),
                        "max_ms": float(arr.max()), "ticks": int(arr.size)})

    # Per-live-zone marginal cost via a line fit over buckets with >=1 promoted.
    pts = [(b["n_promoted"], b["mean_ms"]) for b in buckets if b["n_promoted"] > 0]
    per_zone_ms = base_ms = None
    if len(pts) >= 2:
        xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
        slope, intercept = np.polyfit(xs, ys, 1)
        per_zone_ms, base_ms = float(slope), float(intercept)

    return {"buckets": buckets, "peak_ms": peak_ms,
            "per_live_zone_ms": per_zone_ms, "macro_base_ms": base_ms,
            "pop_per_zone": pop}


def budget_table(per_zone_ms: float, base_ms: float,
                 budgets_ms=(16.0, 33.0, 100.0, 250.0)) -> list[dict]:
    """How many ~pop-sized live zones fit inside each per-tick wall budget."""
    rows = []
    for b in budgets_ms:
        if per_zone_ms and per_zone_ms > 0:
            n = max(0, int((b - (base_ms or 0.0)) // per_zone_ms))
        else:
            n = None
        rows.append({"budget_ms": b, "max_live_zones": n})
    return rows


def _plot_scaling(neighbour_rows, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    N = [r["N"] for r in neighbour_rows]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.loglog(N, [r["pairwise_ms"] for r in neighbour_rows], "o-", label="pairwise O(n²)")
    ax.loglog(N, [r["hashed_ms"] for r in neighbour_rows], "s-", label="spatial hash O(n)")
    ax.loglog(N, [r["full_step_ms"] for r in neighbour_rows], "^--", label="full agent step (hashed)")
    ax.set_xlabel("agents in zone (N)")
    ax.set_ylabel("ms per tick")
    ax.set_title("Phase 6: neighbour-search scaling at reference density")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def main():
    os.makedirs(OUT, exist_ok=True)
    print("== neighbour-search scaling (worst-case dense mix) ==")
    nb = bench_neighbour()
    print(f"{'N':>7} {'pairwise':>11} {'hashed':>10} {'speedup':>8} {'full step':>11}")
    for r in nb:
        print(f"{r['N']:7d} {r['pairwise_ms']:9.2f}ms {r['hashed_ms']:8.2f}ms "
              f"{r['speedup']:7.1f}x {r['full_step_ms']:9.2f}ms")

    print("\n== whole-engine tick cost (8x8 grid, 1000/zone outbreak) ==")
    eng = bench_engine_tick()
    print(f"{'live zones':>11} {'mean ms':>9} {'max ms':>8} {'ticks':>7}")
    for b in eng["buckets"]:
        print(f"{b['n_promoted']:11d} {b['mean_ms']:7.2f}ms {b['max_ms']:6.2f}ms {b['ticks']:7d}")
    if eng["per_live_zone_ms"]:
        print(f"\nmarginal cost ~ {eng['per_live_zone_ms']:.3f} ms / live zone "
              f"(+ {eng['macro_base_ms']:.3f} ms macro base); peak tick {eng['peak_ms']:.2f} ms")

    bud = budget_table(eng["per_live_zone_ms"] or 0.0, eng["macro_base_ms"] or 0.0)
    print("\n== live-bubble budget (zones of ~1000 agents) ==")
    for r in bud:
        print(f"  {r['budget_ms']:6.0f} ms/tick  ->  up to {r['max_live_zones']} live zones")

    plot = _plot_scaling(nb, os.path.join(OUT, "phase6_scaling.png"))
    summary = {"neighbour": nb, "engine": eng, "budget": bud}
    with open(os.path.join(OUT, "phase6_bench.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nwrote {os.path.join(OUT, 'phase6_bench.json')}"
          + (f" and {plot}" if plot else " (matplotlib unavailable; no plot)"))
    return summary


if __name__ == "__main__":
    main()

"""Live-bubble performance benchmark (M6): separate the simulation, snapshot and
IPC-serialization budgets so a rendering bottleneck is never mistaken for a
simulation one.

Measures, at several promoted-zone populations:

* **sim tick cost** — `World.step()` wall time with a zone of N agents promoted;
* **snapshot cost** — `World.snapshot()` wall time (the renderer contract build);
* **serialize cost** — `json.dumps(snapshot)` wall time (the IPC wire cost).

Rendering (Godot frame time, per-citizen draw) is measured on the Godot side and
kept separate by construction — this module never renders.

Run::

    python -m asphodel.bench_live
    python -m asphodel.bench_live --sizes 100,500,1000,2000 --steps 20
"""

from __future__ import annotations

import argparse
import json
import time

from .config import ScenarioConfig, MicroParams
from .citizen import CitizenProfile, ScheduleEntry
from .orchestrator import World


_DAY = [ScheduleEntry(0.0, 7.0, "sleep", "h"), ScheduleEntry(7.0, 9.0, "commute", "r"),
        ScheduleEntry(9.0, 17.0, "work", "o"), ScheduleEntry(17.0, 24.0, "leisure", "h")]


def _world_with_zone_pop(n_agents: int, seed: int = 1) -> World:
    """A 2x2 world whose focused zone 0 holds ~n_agents living people, with every
    resident an identified, reacting citizen (worst case for the NPC layer)."""
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = 2
    cfg.model.graph.grid_cols = 2
    cfg.model.graph.population_per_zone = float(n_agents)
    cfg.n_days = 60.0
    w = World(cfg, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                            mixing_step_frac=0.12),
              start_hour=8.0, seed=seed)
    citizens = [CitizenProfile(
        citizen_id=c, city="x", age=30, age_band="a", occupation="w", shift="d",
        home_district="d", work_district="d", home_zone=0, work_zone=0,
        schedule=_DAY, inventory={}, spawn_hour=8.0, current_location="o",
        current_activity="work", current_task="") for c in range(n_agents)]
    w.set_citizens(citizens)
    w.set_focus([0])
    w.intervene("broadcast", level=1.0)     # drive belief so reactions are active
    w.step()                                # promote + first identity/reaction pass
    return w


def _time(fn, repeat: int) -> float:
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best * 1000.0                     # ms


def benchmark(sizes, steps: int = 10) -> list[dict]:
    rows = []
    for n in sizes:
        w = _world_with_zone_pop(n)
        live = sum(z.n for z in w.promoted.values())
        sim_ms = _time(w.step, repeat=steps)
        snap_ms = _time(w.snapshot, repeat=steps)
        snap = w.snapshot()
        ser_ms = _time(lambda: json.dumps(snap), repeat=steps)
        payload_kb = len(json.dumps(snap)) / 1024.0
        rows.append({
            "requested": n, "live_agents": live,
            "sim_step_ms": round(sim_ms, 3),
            "snapshot_ms": round(snap_ms, 3),
            "serialize_ms": round(ser_ms, 3),
            "payload_kb": round(payload_kb, 1),
        })
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="100,500,1000,2000")
    ap.add_argument("--steps", type=int, default=10)
    args = ap.parse_args(argv)
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    rows = benchmark(sizes, steps=args.steps)

    print(f"{'req':>6} {'live':>7} {'sim(ms)':>9} {'snap(ms)':>9} "
          f"{'ser(ms)':>9} {'wire(KB)':>9}")
    for r in rows:
        print(f"{r['requested']:>6} {r['live_agents']:>7} {r['sim_step_ms']:>9} "
              f"{r['snapshot_ms']:>9} {r['serialize_ms']:>9} {r['payload_kb']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

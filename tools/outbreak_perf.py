#!/usr/bin/env python3
"""Wall-clock performance of the outbreak runtime on one city bundle.

Everything the outbreak adds on top of the embodied mobility runtime, in
milliseconds (median of 3 repeats where a repeat is cheap):

    advance       OutbreakRuntime.advance per game-minute — off-peak with one
                  infected, at the 07:00-08:00 commute peak, and in an
                  infection-heavy world (20 seeded index cases, measured over
                  12:00-13:00 once they are symptomatic / dead / undead)
    focus         the same advance with the mobility focus far from the city
                  (citizens spill into the ABSTRACT overflow band) vs near it
                  (the NEAR/PHYSICAL band). The Python cost is the same work
                  either way — a NEAR undead costs no extra Python; the Godot
                  body cost is measured in-engine, separately.
    contacts      _contacts (the co-occupancy scan) with 1 / 5 / 20 infectious
                  sources — this is the term that grows with the outbreak
    progression   _progress (the scheduled-transition scan) over all records
    snapshot      snapshot() and to_state() / from_state()
    baseline      the same world advanced with mobility only (no outbreak)

and states the implied real-time budget: at the default 24x clock one game
minute takes 2.5 s of real time.

    PYTHONPATH=. python3 tools/outbreak_perf.py [--city houston]

Writes artifacts/outbreak_v1/performance.json.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import statistics
import sys
import time
from typing import Callable, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel import MicroParams                                       # noqa: E402
from asphodel.bridge.worldfactory import (resolve_bundle_dir,          # noqa: E402
                                          world_from_bundle)
from asphodel.bundle_population import load_bundle_population          # noqa: E402
from asphodel.embodiment import CitySpatialContext                     # noqa: E402
from asphodel.outbreak import OutbreakRuntime                          # noqa: E402
from asphodel.outbreak.health import HealthState                       # noqa: E402

ARTIFACT = os.path.join(REPO, "artifacts", "outbreak_v1", "performance.json")
REPEATS = 3
BLOCK = 20                            # game-minutes per timed block
HEAVY_BLOCK = 5                       # ... in the infection-heavy world, where a
                                      # single game-minute already costs seconds
PATHOGEN = "classic_zombie"
MICRO = dict(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
CLOCK_X = 24.0                        # default game clock: 24x real time
GAME_MINUTE_REAL_S = 60.0 / CLOCK_X   # => 2.5 s of real time per game minute
FAR_XY = (1.0e6, 1.0e6)               # a focus nowhere near the city


def median_ms(fn: Callable[[], None], repeats: int = REPEATS) -> float:
    out: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(out)


def build(city: str, bundle_dir: str, start_hour: float, outbreak: bool = True,
          n_seeds: int = 1):
    """A world at ``start_hour`` with mobility and (optionally) the outbreak.

    ``n_seeds`` > 1 seeds the citizens with the most registered coworkers as
    extra index cases, which is how the infection-heavy scenario is built.
    """
    w = world_from_bundle(city, micro_params=MicroParams(**MICRO))
    w.start_hour = start_hour
    w.set_citizens(load_bundle_population(bundle_dir))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(bundle_dir))
    w.enable_mobility(bundle_dir=bundle_dir)
    if not outbreak:
        return w, None
    ob = w.enable_outbreak(PATHOGEN)
    if n_seeds > 1:
        for cid in most_connected(ob, n_seeds):
            if cid not in ob.records:
                ob.seed_index_case(cid, context="index_case:perf_seed")
    return w, ob


def most_connected(ob, n: int) -> List[int]:
    """Citizens with the most registered coworkers (ties: lowest citizen id)."""
    size = {}
    for bid, workers in ob.workers_by_building.items():
        for c in workers:
            size[c] = max(size.get(c, 0), len(workers) - 1)
    return [c for _, c in sorted(((-v, c) for c, v in size.items()))[:n]]


def advance_block(w, minutes: int = BLOCK, focus_xy=None) -> None:
    for _ in range(minutes):
        w.advance_seconds(60.0, focus_xy=focus_xy)


def timed_outbreak_block(w, ob, minutes: int = BLOCK, focus_xy=None) -> dict:
    """Advance ``minutes`` game-minutes, splitting mobility from outbreak cost."""
    cost = {"mobility_s": 0.0, "outbreak_s": 0.0}
    mob_advance, ob_advance = w.mobility.advance, (ob.advance if ob else None)

    def mob(dt, hour, _f=mob_advance):
        t0 = time.perf_counter()
        _f(dt, hour)
        cost["mobility_s"] += time.perf_counter() - t0

    w.mobility.advance = mob
    if ob is not None:
        def obr(dt, _f=ob_advance):
            t0 = time.perf_counter()
            _f(dt)
            cost["outbreak_s"] += time.perf_counter() - t0
        ob.advance = obr
    t0 = time.perf_counter()
    advance_block(w, minutes, focus_xy=focus_xy)
    total_s = time.perf_counter() - t0
    w.mobility.advance = mob_advance
    if ob is not None:
        ob.advance = ob_advance
    return {"total_ms_per_game_minute": round(total_s * 1000.0 / minutes, 3),
            "mobility_ms_per_game_minute": round(cost["mobility_s"] * 1000.0 / minutes, 3),
            "outbreak_ms_per_game_minute": round(cost["outbreak_s"] * 1000.0 / minutes, 3),
            "game_minutes": minutes}


def repeat_blocks(w, ob, repeats: int = REPEATS, minutes: int = BLOCK, focus_xy=None) -> dict:
    """Median over ``repeats`` timed blocks (each block advances the world)."""
    rows = [timed_outbreak_block(w, ob, minutes, focus_xy) for _ in range(repeats)]
    out = {k: round(statistics.median(r[k] for r in rows), 3)
           for k in ("total_ms_per_game_minute", "mobility_ms_per_game_minute",
                     "outbreak_ms_per_game_minute")}
    out.update({"repeats": repeats, "game_minutes_per_block": minutes,
                "blocks": rows, "hour_after": round(w.current_hour(), 3)})
    return out


def health_mix(ob) -> dict:
    c = {}
    for r in ob.records.values():
        c[r.state.value] = c.get(r.state.value, 0) + 1
    return dict(sorted(c.items()))


def infectious_sources(ob) -> int:
    return sum(1 for r in ob.records.values()
               if r.infectious_weight(ob.pathogen, ob.now_s) > 0.0)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="houston")
    ap.add_argument("--out", default=ARTIFACT)
    ap.add_argument("--seeds", type=int, default=20, help="index cases for the heavy scenario")
    ap.add_argument("--heavy-hour", type=float, default=12.0,
                    help="hour at which the infection-heavy scenario is measured")
    args = ap.parse_args(argv)

    wall0 = time.perf_counter()
    bundle_dir = resolve_bundle_dir(args.city)
    res: dict = {}

    # -- (a) off-peak, one infected ---------------------------------------
    t0 = time.perf_counter()
    w, ob = build(args.city, bundle_dir, 5.0)
    build_ms = (time.perf_counter() - t0) * 1000.0
    n_cits = len(w.mobility.execs)
    print(f"[{args.city}] world built in {build_ms / 1000:.1f} s, {n_cits} citizens, "
          f"index case {sorted(ob.records)}")
    res["world"] = {"n_citizens": n_cits, "n_vehicles": len(w.mobility.vehicles),
                    "build_ms": round(build_ms, 1),
                    "n_workplaces": len(ob.workers_by_building)}
    off = repeat_blocks(w, ob)
    off.update({"scenario": "off-peak 05:00, 1 infected (incubating index case)",
                "n_records": len(ob.records), "health": health_mix(ob),
                "infectious_sources": infectious_sources(ob)})
    res["advance_offpeak_1_infected"] = off
    print(f"  off-peak 05:00: outbreak {off['outbreak_ms_per_game_minute']} ms/game-min")

    # -- (b) commute peak 07:00-08:00 -------------------------------------
    w_pk, ob_pk = build(args.city, bundle_dir, 7.0)
    peak = repeat_blocks(w_pk, ob_pk)
    peak.update({"scenario": "commute peak 07:00-08:00, 1 infected",
                 "n_records": len(ob_pk.records), "health": health_mix(ob_pk),
                 "infectious_sources": infectious_sources(ob_pk)})
    res["advance_commute_peak"] = peak
    print(f"  peak 07:00:     outbreak {peak['outbreak_ms_per_game_minute']} ms/game-min")

    # -- (c) infection-heavy at 12:00-13:00 -------------------------------
    w_h, ob_h = build(args.city, bundle_dir, 5.0, n_seeds=args.seeds)
    seeded = sorted(ob_h.records)
    # 05:00 -> 12:00, one game hour at a time: the warm-up curve is itself a
    # measurement (how the world gets more expensive as the outbreak spreads).
    curve = []
    t0 = time.perf_counter()
    for h in range(int(args.heavy_hour - 5.0)):
        row = timed_outbreak_block(w_h, ob_h, 60)
        row.update({"hour_after": round(w_h.current_hour(), 2),
                    "n_records": len(ob_h.records),
                    "n_undead": sum(1 for r in ob_h.records.values()
                                    if r.state == HealthState.UNDEAD),
                    "n_events": len(ob_h.events)})
        curve.append(row)
        print(f"    warm {row['hour_after']:5.2f}h: total "
              f"{row['total_ms_per_game_minute']:8.1f} ms/game-min "
              f"(mobility {row['mobility_ms_per_game_minute']:.1f}, outbreak "
              f"{row['outbreak_ms_per_game_minute']:.1f}), "
              f"{row['n_undead']} undead, {row['n_records']} records")
    warm_s = time.perf_counter() - t0
    heavy = repeat_blocks(w_h, ob_h, minutes=HEAVY_BLOCK)
    heavy.update({"scenario": f"infection-heavy {args.heavy_hour:.0f}:00, "
                              f"{len(seeded)} seeded index cases",
                  "seeded_index_cases": seeded, "warmup_to_1200_s": round(warm_s, 1),
                  "warmup_curve_per_game_hour": curve,
                  "n_records": len(ob_h.records), "health": health_mix(ob_h),
                  "infectious_sources": infectious_sources(ob_h),
                  "n_undead": sum(1 for r in ob_h.records.values()
                                  if r.state == HealthState.UNDEAD),
                  "n_events": len(ob_h.events),
                  "n_disrupted_buildings": len(ob_h.disrupted_buildings),
                  "n_obstructions": len(ob_h.obstructions)})
    res["advance_infection_heavy"] = heavy
    print(f"  heavy 12:00:    outbreak {heavy['outbreak_ms_per_game_minute']} ms/game-min "
          f"({heavy['n_undead']} undead, {heavy['n_records']} records)")

    # -- focus FAR vs NEAR (same heavy world, back to back) ---------------
    near_xy = w_h.mobility.execs[seeded[0]].pos
    far = repeat_blocks(w_h, ob_h, minutes=HEAVY_BLOCK, focus_xy=FAR_XY)
    bands_far = {}
    for b in w_h.mobility.bands.values():
        bands_far[b.name.lower()] = bands_far.get(b.name.lower(), 0) + 1
    near = repeat_blocks(w_h, ob_h, minutes=HEAVY_BLOCK, focus_xy=near_xy)
    bands_near = {}
    for b in w_h.mobility.bands.values():
        bands_near[b.name.lower()] = bands_near.get(b.name.lower(), 0) + 1
    res["focus"] = {
        "far": {**far, "focus_xy": list(FAR_XY), "bands": bands_far},
        "near": {**near, "focus_xy": [round(near_xy[0], 1), round(near_xy[1], 1)],
                 "bands": bands_near, "n_undead": sum(
                     1 for r in ob_h.records.values() if r.state == HealthState.UNDEAD)},
        "max_active": w_h.mobility.max_active,
        "note": ("the outbreak scans every registered citizen regardless of the mobility "
                 "LOD band, so a NEAR undead costs exactly the same Python as a FAR one "
                 f"(the Godot body cost of a NEAR undead is measured in-engine, "
                 f"separately). Mobility only freezes citizens into ABSTRACT beyond its "
                 f"max_active={w_h.mobility.max_active} budget, and this city registers "
                 f"{len(w_h.mobility.execs)}, so nothing froze and the far focus changed "
                 "nothing on the mobility side either: "
                 f"far bands {bands_far}, near bands {bands_near}."),
    }
    print(f"  focus far:      outbreak {far['outbreak_ms_per_game_minute']} ms/game-min, "
          f"mobility {far['mobility_ms_per_game_minute']}")
    print(f"  focus near:     outbreak {near['outbreak_ms_per_game_minute']} ms/game-min, "
          f"mobility {near['mobility_ms_per_game_minute']}")

    # -- contact scan vs number of infectious sources ---------------------
    # A fresh world, with N seeded cases forced infectious now. _contacts is
    # side-effecting (it infects), so the records are restored after each call.
    contacts = {"note": ("sources are seeded index cases with infectious_from_t forced to 0 "
                         "so the scan really has N infectious sources; records are restored "
                         "after every timed call, so the scans are comparable"),
                "by_sources": {}}
    w_c, ob_c = build(args.city, bundle_dir, 8.0, n_seeds=args.seeds)
    ranked = sorted(ob_c.records)
    for n_src in (1, 5, 20):
        for cid in ranked:
            r = ob_c.records[cid]
            r.infectious_from_t = 0.0 if cid in ranked[:n_src] else None
            r.state = HealthState.SYMPTOMATIC if cid in ranked[:n_src] else HealthState.INCUBATING
        got = infectious_sources(ob_c)
        saved_records = copy.deepcopy(ob_c.records)
        saved_events = len(ob_c.events)

        def scan():
            ob_c._contacts(60.0)

        def restore():
            ob_c.records = copy.deepcopy(saved_records)
            del ob_c.events[saved_events:]

        samples = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            scan()
            samples.append((time.perf_counter() - t0) * 1000.0)
            restore()
        ms = statistics.median(samples)
        contacts["by_sources"][str(n_src)] = {
            "infectious_sources": got, "ms": round(ms, 3),
            "ms_per_source": round(ms / max(1, got), 4),
            "n_registered": len(ob_c.mobility.execs),
            "per_source_per_citizen_us": round(
                1000.0 * ms / max(1, got) / max(1, len(ob_c.mobility.execs)), 3)}
        print(f"  contacts {n_src:>2} sources: {ms:.2f} ms per scan (once a game-minute)")
    res["contacts"] = contacts

    # -- progression scan ---------------------------------------------------
    res["progression"] = {
        "heavy_ms": round(median_ms(lambda: ob_h._progress()), 4),
        "heavy_n_records": len(ob_h.records),
        "light_ms": round(median_ms(lambda: ob._progress()), 4),
        "light_n_records": len(ob.records),
        "note": "_progress runs on every 1 s substep, i.e. 60x per game-minute",
    }
    res["progression"]["heavy_ms_per_game_minute"] = round(
        res["progression"]["heavy_ms"] * 60.0, 3)

    # -- snapshot / persistence --------------------------------------------
    snap = ob_h.snapshot()
    res["snapshot"] = {"ms": round(median_ms(lambda: ob_h.snapshot()), 3),
                       "json_bytes": len(json.dumps(snap)),
                       "n_records": len(ob_h.records), "counts": snap["counts"]}
    blob = json.dumps(ob_h.to_state())
    res["persistence"] = {
        "to_state_plus_dumps_ms": round(median_ms(lambda: json.dumps(ob_h.to_state())), 3),
        "from_state_ms": round(median_ms(
            lambda: OutbreakRuntime.from_state(json.loads(blob), w_h.mobility)), 3),
        "state_bytes": len(blob), "n_events_in_state": len(ob_h.events)}

    # -- mobility-only baseline --------------------------------------------
    w_b, _ = build(args.city, bundle_dir, 5.0, outbreak=False)
    base_off = repeat_blocks(w_b, None)
    w_bp, _ = build(args.city, bundle_dir, 7.0, outbreak=False)
    base_peak = repeat_blocks(w_bp, None)
    res["mobility_only_baseline"] = {"offpeak_0500": base_off, "commute_peak_0700": base_peak}
    print(f"  baseline 05:00: mobility-only {base_off['total_ms_per_game_minute']} ms/game-min; "
          f"07:00 {base_peak['total_ms_per_game_minute']}")

    # -- budget --------------------------------------------------------------
    budget_ms = GAME_MINUTE_REAL_S * 1000.0
    worst = max(off["total_ms_per_game_minute"], peak["total_ms_per_game_minute"],
                heavy["total_ms_per_game_minute"])
    res["budget"] = {
        "clock_multiplier": CLOCK_X,
        "real_seconds_per_game_minute": GAME_MINUTE_REAL_S,
        "budget_ms": budget_ms,
        "worst_total_ms_per_game_minute": worst,
        "worst_scenario": max((off, peak, heavy),
                              key=lambda d: d["total_ms_per_game_minute"])["scenario"],
        "budget_used_fraction_worst": round(worst / budget_ms, 4),
        "outbreak_share_offpeak": round(
            off["outbreak_ms_per_game_minute"] / max(1e-9, off["total_ms_per_game_minute"]), 3),
        "outbreak_share_heavy": round(
            heavy["outbreak_ms_per_game_minute"] / max(1e-9, heavy["total_ms_per_game_minute"]), 3),
        "headroom_x": round(budget_ms / worst, 1) if worst else None,
        "note": (f"at {CLOCK_X:.0f}x one game minute is {GAME_MINUTE_REAL_S} s of real time "
                 f"({budget_ms:.0f} ms). The heaviest measured game-minute "
                 f"({worst} ms, {n_cits} citizens) uses "
                 f"{100.0 * worst / budget_ms:.2f}% of it; the outbreak itself is "
                 f"{heavy['outbreak_ms_per_game_minute']} ms of that."),
    }

    doc = {"version": 1, "city": args.city, "bundle_dir": bundle_dir,
           "pathogen": PATHOGEN, "repeats": REPEATS, "unit": "milliseconds",
           "machine": {"python": sys.version.split()[0],
                       "implementation": platform.python_implementation(),
                       "platform": platform.platform(),
                       "machine": platform.machine(),
                       "processor": platform.processor(),
                       "cpu_count": os.cpu_count()},
           "wall_s": round(time.perf_counter() - wall0, 1),
           **res}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    print_table(doc)
    print(f"  artifact: {args.out}")
    return 0


def print_table(doc: dict) -> None:
    rows = []
    for key, lab in (("advance_offpeak_1_infected", "advance off-peak 05:00 (1 infected)"),
                     ("advance_commute_peak", "advance commute peak 07:00"),
                     ("advance_infection_heavy", "advance infection-heavy 12:00")):
        a = doc[key]
        rows.append((f"outbreak {lab}", a["outbreak_ms_per_game_minute"],
                     f"total {a['total_ms_per_game_minute']} ms/game-min "
                     f"(mobility {a['mobility_ms_per_game_minute']}), "
                     f"{a['n_records']} records, {a['infectious_sources']} infectious"))
    f = doc["focus"]
    rows.append(("outbreak advance, focus FAR", f["far"]["outbreak_ms_per_game_minute"],
                 f"mobility {f['far']['mobility_ms_per_game_minute']} ms, bands {f['far']['bands']}"))
    rows.append(("outbreak advance, focus NEAR", f["near"]["outbreak_ms_per_game_minute"],
                 f"mobility {f['near']['mobility_ms_per_game_minute']} ms, "
                 f"bands {f['near']['bands']}, {f['near']['n_undead']} undead"))
    for k in ("1", "5", "20"):
        c = doc["contacts"]["by_sources"][k]
        rows.append((f"contact scan ({k} infectious sources)", c["ms"],
                     f"{c['n_registered']} citizens scanned, "
                     f"{c['per_source_per_citizen_us']} us per source-citizen, once/game-min"))
    p = doc["progression"]
    rows.append(("progression scan (heavy)", p["heavy_ms"],
                 f"{p['heavy_n_records']} records, x60 substeps = "
                 f"{p['heavy_ms_per_game_minute']} ms/game-min"))
    rows.append(("progression scan (1 record)", p["light_ms"], f"{p['light_n_records']} record(s)"))
    s = doc["snapshot"]
    rows.append(("snapshot()", s["ms"], f"{s['json_bytes']} json bytes, {s['n_records']} records"))
    pe = doc["persistence"]
    rows.append(("to_state + json.dumps", pe["to_state_plus_dumps_ms"], f"{pe['state_bytes']} bytes"))
    rows.append(("from_state", pe["from_state_ms"], f"{pe['n_events_in_state']} events carried"))
    b = doc["mobility_only_baseline"]
    rows.append(("baseline mobility-only 05:00", b["offpeak_0500"]["total_ms_per_game_minute"],
                 "World without outbreak"))
    rows.append(("baseline mobility-only 07:00", b["commute_peak_0700"]["total_ms_per_game_minute"],
                 "World without outbreak, commute peak"))

    print("")
    print(f"{'measurement':46s} {'ms':>10s}  detail")
    print("-" * 46 + " " + "-" * 10 + "  " + "-" * 46)
    for name, ms, detail in rows:
        val = "-" if ms is None else f"{ms:.4f}".rstrip("0").rstrip(".")
        print(f"{name:46s} {val:>10s}  {detail}")
    bu = doc["budget"]
    print("")
    print(f"  budget: {bu['note']}")
    print(f"          headroom {bu['headroom_x']}x on the heaviest measured game-minute")


if __name__ == "__main__":
    raise SystemExit(main())

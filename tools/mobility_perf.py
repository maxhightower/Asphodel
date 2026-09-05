#!/usr/bin/env python3
"""Wall-clock performance of the embodied mobility runtime on one city bundle.

Measures (median of 3 repeats, all numbers in milliseconds):

    routing          graph.route FOOT/CAR for a real commuter, and 20 random
                     node pairs (seeded, deterministic)
    pedestrian       PedestrianController.advance, per substep
    vehicle          VehicleController.advance, per substep, with 0 / 10 / 50
                     other vehicles in the neighbourhood
    runtime          MobilityRuntime.advance, per game-minute, with 1 / 10 /
                     all registered citizens
    lod              activate() after a 1 h freeze; set_focus_xy + _update_bands
    snapshot         MobilityRuntime.snapshot()
    persistence      to_state + json.dumps, and from_state

and states the implied real-time budget: at the default 24x clock a game
minute takes 2.5 s of real time.

    PYTHONPATH=. python3 tools/mobility_perf.py [--city houston]

Writes artifacts/mobility/performance.json.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
from typing import Callable, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge.worldfactory import resolve_bundle_dir              # noqa: E402
from asphodel.bundle_population import load_bundle_population            # noqa: E402
from asphodel.citizens.planning import Mode                              # noqa: E402
from asphodel.embodied import (MobilityRuntime, PedestrianController,    # noqa: E402
                               VehicleController, load_entrances)
from asphodel.embodied.pathing import PhysicalPath                       # noqa: E402
from asphodel.embodied.vehicle_control import (OtherVehicle,             # noqa: E402
                                               junctions_on_path)
from asphodel.embodiment import CitySpatialContext                       # noqa: E402

ARTIFACT = os.path.join(REPO, "artifacts", "mobility", "performance.json")
REPEATS = 3
SEED = 0
CLOCK_X = 24.0                       # default game clock: 24x real time
GAME_MINUTE_REAL_S = 60.0 / CLOCK_X  # => 2.5 s of real time per game minute


def median_ms(fn: Callable[[], None], repeats: int = REPEATS) -> float:
    """Median wall-clock ms of ``repeats`` runs of ``fn``."""
    out: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(out)


def build_runtime(bundle_dir, ctx, entrances, anchors, pop, limit=None, start_hour=5.0):
    rt = MobilityRuntime(ctx.street_graph, entrances, anchors, ctx=ctx, bundle_dir=bundle_dir)
    n = 0
    for prof in sorted(pop, key=lambda p: int(p.citizen_id)):
        if limit is not None and n >= limit:
            break
        if getattr(prof, "home_building_id", None) is None:
            continue
        if rt.register(prof, start_hour):
            n += 1
    return rt, n


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="houston")
    ap.add_argument("--out", default=ARTIFACT)
    ap.add_argument("--citizen", type=int, default=4, help="commuter used for the route probes")
    args = ap.parse_args(argv)

    bundle_dir = resolve_bundle_dir(args.city)
    t0 = time.perf_counter()
    pop = load_bundle_population(bundle_dir)
    ctx = CitySpatialContext.from_bundle_dir(bundle_dir)
    entrances, anchors = load_entrances(bundle_dir)
    graph = ctx.street_graph
    load_ms = (time.perf_counter() - t0) * 1000.0
    print(f"[{args.city}] bundle loaded in {load_ms / 1000:.1f} s "
          f"({len(graph.nodes)} nodes, {len(graph.segments)} segments)")

    res: dict = {}

    # -- full runtime (all citizens) --------------------------------------
    t0 = time.perf_counter()
    rt_all, n_all = build_runtime(bundle_dir, ctx, entrances, anchors, pop)
    res["register_all_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    res["n_citizens_all"] = n_all
    res["n_vehicles_all"] = len(rt_all.vehicles)

    # -- routing -----------------------------------------------------------
    cid = args.citizen if args.citizen in rt_all.records else sorted(rt_all.records)[0]
    rec = rt_all.records[cid]
    home_node = rt_all.node_for_building(rec.home_building_id)
    work_node = rt_all.node_for_building(rec.work_building_id) if rec.work_building_id else None
    routing = {"citizen_id": cid, "home_building_id": rec.home_building_id,
               "work_building_id": rec.work_building_id}
    r_foot = graph.route(home_node, work_node, Mode.FOOT)
    routing["home_work_foot_ms"] = round(median_ms(
        lambda: graph.route(home_node, work_node, Mode.FOOT)), 3)
    routing["home_work_foot_m"] = None if r_foot is None else round(r_foot.distance, 1)
    park_home = rt_all.citizens[cid].vehicle_node
    park_work = rt_all._resolve_parking(cid, work_node) if work_node else None
    if park_home is not None and park_work is not None:
        pw = park_work[0]
        r_car = graph.route(park_home, pw, Mode.CAR)
        routing["home_work_car_ms"] = round(median_ms(
            lambda: graph.route(park_home, pw, Mode.CAR)), 3)
        routing["home_work_car_m"] = None if r_car is None else round(r_car.distance, 1)
    else:
        routing["home_work_car_ms"] = None
        routing["home_work_car_m"] = None
        routing["car_note"] = "citizen has no usable car/parking"

    rng = random.Random(SEED)
    node_ids = sorted(graph.nodes)
    pairs = [(rng.choice(node_ids), rng.choice(node_ids)) for _ in range(20)]

    def _run_pairs(mode):
        def go():
            for a, b in pairs:
                graph.route(a, b, mode)
        return go

    routing["random20_foot_total_ms"] = round(median_ms(_run_pairs(Mode.FOOT)), 2)
    routing["random20_car_total_ms"] = round(median_ms(_run_pairs(Mode.CAR)), 2)
    routing["random20_foot_per_route_ms"] = round(routing["random20_foot_total_ms"] / 20.0, 3)
    routing["random20_car_per_route_ms"] = round(routing["random20_car_total_ms"] / 20.0, 3)
    routing["random20_seed"] = SEED
    routing["random20_solved_foot"] = sum(
        1 for a, b in pairs if graph.route(a, b, Mode.FOOT) is not None)
    routing["random20_solved_car"] = sum(
        1 for a, b in pairs if graph.route(a, b, Mode.CAR) is not None)
    res["routing"] = routing

    # -- pedestrian controller --------------------------------------------
    foot_path = PhysicalPath.from_route(graph, r_foot)
    N = 1000

    def ped_run():
        c = PedestrianController(foot_path)
        for _ in range(N):
            if c.arrived:
                c.dist = 0.0
            c.advance(1.0, [])

    res["pedestrian"] = {
        "substeps": N,
        "path_length_m": round(foot_path.length, 1),
        "path_points": len(foot_path.points),
        "total_ms": round(median_ms(ped_run), 2),
    }
    res["pedestrian"]["per_substep_ms"] = round(res["pedestrian"]["total_ms"] / N, 5)

    # -- vehicle controller ------------------------------------------------
    car_route = graph.route(park_home, park_work[0], Mode.CAR) if park_work else None
    car_path = PhysicalPath.from_route(graph, car_route) if car_route else foot_path
    juncs = junctions_on_path(graph, car_path) if car_route else []
    veh = {"substeps": N, "path_length_m": round(car_path.length, 1),
           "path_points": len(car_path.points), "junctions": len(juncs), "by_others": {},
           "note": ("others are a deterministic 7 m queue ahead on the path; "
                    "VehicleController._lead_gap only projects the ones within "
                    "lookahead+10 m, so the cost saturates once the queue fills that window")}
    for n_others in (0, 10, 50):
        others = []
        for k in range(n_others):
            xy = car_path.point_at(min(car_path.length, 20.0 + 7.0 * k))
            others.append(OtherVehicle(f"veh:other:{k}", xy, 6.0 + 0.1 * k,
                                       car_path.heading_at(20.0 + 7.0 * k)))
        near = sum(1 for o in others
                   if ((o.xy[0] - car_path.point_at(0.0)[0]) ** 2
                       + (o.xy[1] - car_path.point_at(0.0)[1]) ** 2) ** 0.5 <= 70.0)

        def car_run(others=others):
            c = VehicleController(car_path)
            c.junctions = list(juncs)
            for _ in range(N):
                if c.dist >= c.path.length - 1e-6:
                    c.dist = 0.0
                c.advance(1.0, graph, Mode.CAR, others, "veh:probe", 0.0)

        total = median_ms(car_run)
        veh["by_others"][str(n_others)] = {"total_ms": round(total, 2),
                                           "per_substep_ms": round(total / N, 5),
                                           "n_within_lookahead_at_start": near}
    res["vehicle"] = veh

    # -- MobilityRuntime.advance per game-minute ---------------------------
    advance = {}
    BLOCK = 20          # game-minutes per repeat: a single replan must not dominate
    # 05:00 is a quiet hour; 07:00 is the commute peak (everyone plans and drives).
    for label, limit, start in (("1", 1, 5.0), ("10", 10, 5.0), ("all", None, 5.0),
                                ("all_commute_0700", None, 7.0)):
        rt, n = (rt_all, n_all) if (limit is None and start == 5.0) else \
            build_runtime(bundle_dir, ctx, entrances, anchors, pop, limit=limit,
                          start_hour=start)
        hour = [start]

        def block(rt=rt, hour=hour):
            for _ in range(BLOCK):
                rt.advance(60.0, hour[0])
                hour[0] = (hour[0] + 1.0 / 60.0) % 24.0

        ms = median_ms(block) / BLOCK
        advance[label] = {"n_citizens": n, "n_vehicles": len(rt.vehicles),
                          "start_hour": start, "game_minutes_per_repeat": BLOCK,
                          "ms_per_game_minute": round(ms, 2),
                          "ms_per_citizen_game_minute": round(ms / max(1, n), 3)}
        print(f"  advance {label:>3} citizens: {ms:.1f} ms / game-minute")
    res["runtime_advance"] = advance

    # -- LOD promotion / demotion ------------------------------------------
    hour = 5.0
    for _ in range(30):                       # warm the runtime into motion
        rt_all.advance(60.0, hour)
        hour = (hour + 1.0 / 60.0) % 24.0
    lod = {}
    promo = []
    for cid_i in sorted(rt_all.execs)[:REPEATS]:
        rt_all.deactivate(cid_i)
        frozen_from = rt_all.now_s
        rt_all.now_s = frozen_from + 3600.0   # a 1 h freeze
        t0 = time.perf_counter()
        rt_all.activate(cid_i)
        promo.append((time.perf_counter() - t0) * 1000.0)
        rt_all.now_s = frozen_from
    lod["activate_after_1h_freeze_ms"] = round(statistics.median(promo), 2)

    focus = rt_all.execs[sorted(rt_all.execs)[0]].pos
    flip = [0]

    def bands():
        flip[0] ^= 1
        rt_all.set_focus_xy((focus[0] + 500.0 * flip[0], focus[1]))
        rt_all._update_bands()

    lod["set_focus_and_update_bands_ms"] = round(median_ms(bands), 3)
    lod["n_transitions"] = len(rt_all.transitions)
    res["lod"] = lod

    # -- snapshot -----------------------------------------------------------
    snap = rt_all.snapshot()
    res["snapshot"] = {
        "ms": round(median_ms(lambda: rt_all.snapshot()), 2),
        "n_citizens": snap["n_citizens"], "n_vehicles": snap["n_vehicles"],
        "json_bytes": len(json.dumps(snap)),
    }

    # -- persistence --------------------------------------------------------
    state = rt_all.to_state()
    blob = json.dumps(state)
    profiles = {int(p.citizen_id): p for p in pop}

    def save():
        json.dumps(rt_all.to_state())

    def restore():
        MobilityRuntime.from_state(json.loads(blob), graph, entrances, anchors,
                                   profiles, ctx=ctx, bundle_dir=bundle_dir)

    res["persistence"] = {
        "save_ms": round(median_ms(save), 2),
        "restore_ms": round(median_ms(restore), 2),
        "state_bytes": len(blob),
    }

    # -- budget -------------------------------------------------------------
    per_min = advance["all"]["ms_per_game_minute"]
    peak_min = advance["all_commute_0700"]["ms_per_game_minute"]
    res["budget"] = {
        "clock_multiplier": CLOCK_X,
        "real_seconds_per_game_minute": GAME_MINUTE_REAL_S,
        "advance_ms_per_game_minute_all_citizens": per_min,
        "n_citizens": advance["all"]["n_citizens"],
        "budget_ms": GAME_MINUTE_REAL_S * 1000.0,
        "budget_used_fraction": round(per_min / (GAME_MINUTE_REAL_S * 1000.0), 4),
        "advance_ms_per_game_minute_commute_peak": peak_min,
        "budget_used_fraction_commute_peak": round(peak_min / (GAME_MINUTE_REAL_S * 1000.0), 4),
        "headroom_x": round((GAME_MINUTE_REAL_S * 1000.0) / per_min, 1) if per_min else None,
        "implied_max_citizens_at_24x": int(
            advance["all"]["n_citizens"] * (GAME_MINUTE_REAL_S * 1000.0) / per_min)
        if per_min else None,
        "note": (f"at {CLOCK_X:.0f}x one game minute is {GAME_MINUTE_REAL_S} s of real time; "
                 f"advancing {advance['all']['n_citizens']} citizens costs {per_min} ms, i.e. "
                 f"{100.0 * per_min / (GAME_MINUTE_REAL_S * 1000.0):.2f}% of that budget "
                 f"(commute peak at 07:00: {peak_min} ms, "
                 f"{100.0 * peak_min / (GAME_MINUTE_REAL_S * 1000.0):.2f}%)"),
    }

    doc = {"version": 1, "city": args.city, "bundle_dir": bundle_dir,
           "repeats": REPEATS, "unit": "milliseconds",
           "machine": {"python": sys.version.split()[0],
                       "implementation": platform.python_implementation(),
                       "platform": platform.platform(),
                       "machine": platform.machine(),
                       "processor": platform.processor()},
           "bundle_load_ms": round(load_ms, 1),
           "graph": {"nodes": len(graph.nodes), "segments": len(graph.segments),
                     "entrances": len(entrances)},
           **res}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    print_table(doc)
    print(f"  artifact: {args.out}")
    return 0


def print_table(doc: dict) -> None:
    rows = []
    r = doc["routing"]
    rows.append(("route  home->work FOOT", r["home_work_foot_ms"],
                 f"{r['home_work_foot_m']} m, citizen {r['citizen_id']}"))
    rows.append(("route  home->work CAR", r["home_work_car_ms"],
                 f"{r['home_work_car_m']} m (parking node to parking node)"))
    rows.append(("route  random pair FOOT", r["random20_foot_per_route_ms"],
                 f"20 pairs seed 0, {r['random20_solved_foot']}/20 solved"))
    rows.append(("route  random pair CAR", r["random20_car_per_route_ms"],
                 f"20 pairs seed 0, {r['random20_solved_car']}/20 solved"))
    p = doc["pedestrian"]
    rows.append(("ped    advance / substep", p["per_substep_ms"],
                 f"{p['substeps']} substeps, {p['path_length_m']} m path"))
    v = doc["vehicle"]
    for k in ("0", "10", "50"):
        rows.append((f"car    advance / substep ({k} others)", v["by_others"][k]["per_substep_ms"],
                     f"{v['substeps']} substeps, {v['junctions']} junctions"))
    for k, lab in (("1", "1 citizen @05:00"), ("10", "10 citizens @05:00"),
                   ("all", "all citizens @05:00"),
                   ("all_commute_0700", "all citizens @07:00 peak")):
        a = doc["runtime_advance"][k]
        rows.append((f"runtime advance / game-min ({lab})", a["ms_per_game_minute"],
                     f"n={a['n_citizens']}, {a['n_vehicles']} vehicles, "
                     f"{a['ms_per_citizen_game_minute']} ms/citizen"))
    l = doc["lod"]
    rows.append(("lod    activate after 1 h freeze", l["activate_after_1h_freeze_ms"],
                 "catch-up at 5 s substeps"))
    rows.append(("lod    set_focus + _update_bands", l["set_focus_and_update_bands_ms"],
                 f"{l['n_transitions']} transitions recorded"))
    s = doc["snapshot"]
    rows.append(("snapshot()", s["ms"], f"{s['json_bytes']} json bytes"))
    pe = doc["persistence"]
    rows.append(("save   to_state + json.dumps", pe["save_ms"], f"{pe['state_bytes']} bytes"))
    rows.append(("restore from_state", pe["restore_ms"], ""))

    print("")
    print(f"{'measurement':48s} {'ms':>10s}  detail")
    print("-" * 48 + " " + "-" * 10 + "  " + "-" * 44)
    for name, ms, detail in rows:
        val = "-" if ms is None else f"{ms:.4f}".rstrip("0").rstrip(".")
        print(f"{name:48s} {val:>10s}  {detail}")
    b = doc["budget"]
    print("")
    print(f"  budget: {b['note']}")
    print(f"          headroom {b['headroom_x']}x -> ~{b['implied_max_citizens_at_24x']} "
          f"citizens fit the 24x real-time budget")


if __name__ == "__main__":
    raise SystemExit(main())

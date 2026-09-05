#!/usr/bin/env python3
"""Per-city smoke test for the embodied mobility runtime (ASPHODEL_EMBODIED_MOBILITY_V1).

For each requested city bundle: load the bundle, build a MobilityRuntime,
register every citizen that has a home building, check a deterministic sample
of commuters (entrances exist, a foot route resolves, parking resolves, a car
route resolves), then run the runtime for a few game hours and count completed
trips, failures and blocked events.

    PYTHONPATH=. python3 tools/mobility_city_smoke.py [city ...]

Status per city:
    PASS   compiled world, sample checks fine, citizens completed trips
    INFO   no compiled world in the bundle (nothing to embody) — skipped
    FAIL   a sample check failed, or no citizen completed a trip

Exit code is non-zero when any compiled city FAILs.
Writes artifacts/mobility/city_smoke.json.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from typing import Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge.worldfactory import resolve_bundle_dir           # noqa: E402
from asphodel.bundle_population import load_bundle_population         # noqa: E402
from asphodel.citizens.planning import Mode                           # noqa: E402
from asphodel.embodied import MobilityRuntime, load_entrances         # noqa: E402
from asphodel.embodiment import CitySpatialContext                    # noqa: E402

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio", "boulder"]
ARTIFACT = os.path.join(REPO, "artifacts", "mobility", "city_smoke.json")

START_HOUR = 5.0
RUN_HOURS = 4.0
STEP_S = 60.0
SAMPLE_N = 5


def has_compiled_world(bundle_dir: str) -> bool:
    """A bundle is embodiable only if its compiled world carries spawn anchors."""
    return os.path.exists(os.path.join(bundle_dir, "world", "spawn_anchors.json.gz"))


def check_sample(rt: MobilityRuntime, cids, entrances) -> dict:
    """Deterministic per-citizen checks: entrances, foot route, parking, car route."""
    graph = rt.graph
    rows = []
    car_route_checked = False
    for cid in cids:
        rec = rt.records[cid]
        row = {"citizen_id": cid, "home_building_id": rec.home_building_id,
               "work_building_id": rec.work_building_id, "has_vehicle": rec.has_vehicle,
               "home_entrance": rec.home_building_id in entrances,
               "work_entrance": rec.work_building_id in entrances,
               "foot_route": False, "foot_route_m": None,
               "parking_resolved": None, "car_route": None, "car_route_m": None,
               "errors": []}
        home_node = rt.node_for_building(rec.home_building_id)
        work_node = rt.node_for_building(rec.work_building_id)
        if home_node is None:
            row["errors"].append("home building has no street access node")
        if work_node is None:
            row["errors"].append("work building has no street access node")
        if home_node and work_node:
            r = graph.route(home_node, work_node, Mode.FOOT)
            row["foot_route"] = r is not None
            if r is None:
                row["errors"].append("no FOOT route home->work")
            else:
                row["foot_route_m"] = round(r.distance, 1)
        # parking + car route, for a citizen that actually owns a car
        if rec.has_vehicle and cid in rt.vehicle_of and work_node is not None:
            park_home = rt.citizens[cid].vehicle_node
            got = rt._resolve_parking(cid, work_node)
            row["parking_resolved"] = got is not None
            if got is None:
                row["errors"].append("no parking candidate near work")
            elif park_home is None:
                row["errors"].append("owner has no home parking node")
            else:
                r = graph.route(park_home, got[0], Mode.CAR)
                row["car_route"] = r is not None
                if r is None:
                    row["errors"].append(f"no CAR route {park_home}->{got[0]}")
                else:
                    row["car_route_m"] = round(r.distance, 1)
                    car_route_checked = True
        rows.append(row)
    return {"citizens": rows, "car_route_checked": car_route_checked,
            "errors": [f"cit {r['citizen_id']}: {e}" for r in rows for e in r["errors"]]}


def smoke_city(city: str, run_hours: float = RUN_HOURS, sample_n: int = SAMPLE_N,
               start_hour: float = START_HOUR, verbose: bool = True) -> dict:
    out = {"city": city, "status": "FAIL", "reason": ""}
    try:
        bundle_dir = resolve_bundle_dir(city)
    except FileNotFoundError as exc:
        out["status"] = "INFO"
        out["reason"] = str(exc)
        return out
    out["bundle_dir"] = bundle_dir
    if not has_compiled_world(bundle_dir):
        out["status"] = "INFO"
        out["reason"] = "no compiled world (world/spawn_anchors.json.gz absent) — nothing to embody"
        return out

    t0 = time.perf_counter()
    pop = load_bundle_population(bundle_dir)
    ctx = CitySpatialContext.from_bundle_dir(bundle_dir)
    entrances, anchors = load_entrances(bundle_dir)
    rt = MobilityRuntime(ctx.street_graph, entrances, anchors, ctx=ctx, bundle_dir=bundle_dir)
    registered = []
    unregistered = []
    for prof in sorted(pop, key=lambda p: int(p.citizen_id)):
        cid = int(prof.citizen_id)
        hb = getattr(prof, "home_building_id", None)
        if hb is None:
            unregistered.append({"citizen_id": cid, "home_building_id": None,
                                 "reason": "no home_building_id"})
            continue
        if rt.register(prof, start_hour):
            registered.append(cid)
        else:
            unregistered.append({
                "citizen_id": cid, "home_building_id": int(hb),
                "has_entrance_anchor": int(hb) in entrances,
                "reason": "home building has no street access node "
                          "(no street within MAX_CONNECTOR_M usable on foot)"})
    load_ms = (time.perf_counter() - t0) * 1000.0

    lost_car = [e["citizen_id"] for e in rt.events if e["event"] == "no_parking_for_vehicle"]
    out.update({
        "n_population": len(pop),
        "n_citizens": len(registered),
        "n_not_registered": len(unregistered),
        "unregistered": unregistered,
        "n_entrances": len(entrances),
        "n_graph_nodes": len(ctx.street_graph.nodes),
        "n_graph_segments": len(ctx.street_graph.segments),
        "n_vehicles": len(rt.vehicles),
        "n_lost_car_no_parking": len(lost_car),
        "lost_car_citizens": sorted(lost_car),
        "load_ms": round(load_ms, 1),
    })

    sample = [c for c in registered if rt.records[c].work_building_id is not None][:sample_n]
    out["sample_citizens"] = sample
    checks = check_sample(rt, sample, entrances)
    out["sample"] = checks

    # -- run ---------------------------------------------------------------
    n_routes_before = len(rt.route_ms)
    hour = start_hour
    t0 = time.perf_counter()
    for _ in range(int(run_hours * 3600.0 / STEP_S)):
        rt.advance(STEP_S, hour)
        hour = (hour + STEP_S / 3600.0) % 24.0
    run_ms = (time.perf_counter() - t0) * 1000.0

    completed = [c for c in registered if rt.execs[c].trips_completed >= 1]
    trips = sum(rt.execs[c].trips_completed for c in registered)
    blocked = sum(rt.execs[c].blocked_events for c in registered)
    fail_events = [e for e in rt.events if e["event"] in ("failure", "trip_failed")]
    blocked_reasons: dict = {}
    for e in rt.events:
        if e["event"] == "blocked":
            r = str(e.get("reason", ""))
            blocked_reasons[r] = blocked_reasons.get(r, 0) + 1
    route_ms = rt.route_ms[n_routes_before:]
    out.update({
        "start_hour": start_hour,
        "run_hours": run_hours,
        "run_ms": round(run_ms, 1),
        "run_ms_per_game_minute": round(run_ms / (run_hours * 60.0), 3),
        "n_completed_trip": len(completed),
        "n_trips": trips,
        "n_blocked_events": blocked,
        "n_blocked_runtime_events": sum(blocked_reasons.values()),
        "blocked_reasons": dict(sorted(blocked_reasons.items(), key=lambda kv: -kv[1])),
        "n_failure_events": sum(1 for e in fail_events if e["event"] == "failure"),
        "n_trip_failed_events": sum(1 for e in fail_events if e["event"] == "trip_failed"),
        "failure_reasons": sorted({str(e.get("reason", "")) for e in fail_events}),
        "n_routes": len(route_ms),
        "route_ms_median": round(statistics.median(route_ms), 3) if route_ms else None,
        "route_ms_max": round(max(route_ms), 3) if route_ms else None,
        "n_transitions": len(rt.transitions),
    })

    reasons = list(checks["errors"])
    if not completed:
        reasons.append(f"no citizen completed a trip in {run_hours} h")
    out["status"] = "FAIL" if reasons else "PASS"
    out["reason"] = "; ".join(reasons)
    if verbose:
        print(f"  {city}: {out['status']} "
              f"({out['n_citizens']} citizens, {out['n_vehicles']} vehicles, "
              f"{len(completed)} moved, {out['run_ms']:.0f} ms run)")
    return out


def print_table(results: dict) -> None:
    cols = [("city", 16), ("status", 6), ("cits", 5), ("veh", 4), ("nopark", 6),
            ("moved", 5), ("trips", 5), ("fail", 4), ("blocked", 7),
            ("load_s", 7), ("run_s", 6), ("rt_med_ms", 9), ("rt_max_ms", 9)]
    print("")
    print("  ".join(n.ljust(w) for n, w in cols))
    print("  ".join("-" * w for _, w in cols))
    for city, r in results.items():
        if r["status"] == "INFO":
            vals = [city, "INFO", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"]
        else:
            vals = [city, r["status"], r["n_citizens"], r["n_vehicles"],
                    r["n_lost_car_no_parking"], r["n_completed_trip"], r["n_trips"],
                    r["n_failure_events"], r["n_blocked_events"],
                    f"{r['load_ms'] / 1000.0:.1f}", f"{r['run_ms'] / 1000.0:.1f}",
                    r["route_ms_median"], r["route_ms_max"]]
        print("  ".join(str(v).ljust(w) for v, (_, w) in zip(vals, cols)))
    print("")
    for city, r in results.items():
        if r.get("reason"):
            print(f"  {city} [{r['status']}]: {r['reason']}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", default=None)
    ap.add_argument("--hours", type=float, default=RUN_HOURS)
    ap.add_argument("--start-hour", type=float, default=START_HOUR)
    ap.add_argument("--sample", type=int, default=SAMPLE_N)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)
    cities = args.cities or DEFAULT_CITIES

    results = {}
    for city in cities:
        print(f"[{city}] ...")
        try:
            results[city] = smoke_city(city, run_hours=args.hours, sample_n=args.sample,
                                       start_hour=args.start_hour)
        except Exception as exc:                                  # a crash is a FAIL, not a stack trace
            traceback.print_exc()
            results[city] = {"city": city, "status": "FAIL",
                             "reason": f"exception: {type(exc).__name__}: {exc}"}

    doc = {"version": 1,
           "start_hour": args.start_hour, "run_hours": args.hours, "step_s": STEP_S,
           "cities": results}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=False)
    print_table(results)
    print(f"  artifact: {args.out}")
    failed = [c for c, r in results.items() if r["status"] == "FAIL"]
    if failed:
        print(f"  FAIL: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

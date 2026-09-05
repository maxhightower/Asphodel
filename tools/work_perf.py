#!/usr/bin/env python3
"""Wall-clock performance of the smart-object / work runtime on one city bundle.

Everything ASPHODEL_SMART_OBJECTS_WORK_V1 adds on top of the embodied mobility
runtime, in milliseconds (median of 3 repeats where a repeat is cheap):

    registration  building the SmartObjectRegistry + RoomGraph of a building —
                  all workplaces, then all homes — split into the interior
                  descriptor cost (``World.interior_descriptor``, which the
                  registry calls) and the object/graph construction on top
    selection     WorkRuntime._select_work_task, the job-grammar scan, timed on
                  the instance over a live 10 game-minute window at 10:00
                  (per call and calls per game-minute, largest workplace named)
    reservations  ReservationLedger.hold / release / is_free / holders_of over
                  1e5 operations each
    advance       WorkRuntime.advance per game-minute at 06:00 (residents
                  asleep), 09:00 (shift start, walking to stations), 11:00
                  (customers in shops) and 17:00 (shift end), each split
                  mobility / work / other inside World.advance_seconds
    navigation    RoomGraph.route over the two largest buildings, and the share
                  of work.advance spent in _walk
    focus         the same advance with the mobility focus far from the city vs
                  at a building entrance. The Python cost is identical either
                  way; the NEAR *embodiment* cost is Godot-side and is measured
                  by the in-engine gate, not here.
    commute       the 07:00-08:00 peak with workers active
    outbreak      outbreak + work in the same world, measured 11:00-11:20
    heavy         a worker-heavy variant (every registered citizen employed at
                  the five largest workplaces)
    profile       a cProfile top-15 (cumulative and tottime) of a 20 game-minute
                  window at 10:00, plus a hotspot list with scaling

and states the implied real-time budget: at the default 24x clock one game
minute takes 2.5 s of real time.

    PYTHONPATH=. python3 tools/work_perf.py [--city houston]

Writes artifacts/smart_objects_work_v1/performance.json.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import platform
import pstats
import statistics
import sys
import time
import types
from typing import Callable, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.smart import WorkRuntime                                # noqa: E402

ARTIFACT = os.path.join(REPO, "artifacts", "smart_objects_work_v1", "performance.json")
REPEATS = 3
BLOCK = 10                            # game-minutes per timed block
WARM = 3                              # game-minutes of warm-up before a block
CLOCK_X = 24.0                        # default game clock: 24x real time
GAME_MINUTE_REAL_S = 60.0 / CLOCK_X   # => 2.5 s of real time per game minute
BUDGET_MS = GAME_MINUTE_REAL_S * 1000.0
FAR_XY = (9000.0, 9000.0)             # a focus away from the city
NEAR_BUILDING = 12013                 # focus building for the NEAR case
BIG_BUILDINGS = (2318, 6059)          # the two largest interiors in Houston
PATHOGEN = "classic_zombie"


# --------------------------------------------------------------------------- #
# world construction (exactly how the game boots one: bridge START_WORLD)
# --------------------------------------------------------------------------- #
def start_world(city: str, start_hour: float, work: bool = True,
                outbreak: bool = False, seed: int = 0):
    """A world from the bundle through the bridge, as START_WORLD builds it."""
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
           "start_hour": float(start_hour), "work": bool(work)}
    r = s.handle(msg)
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    w = s.world
    if outbreak:
        w.enable_outbreak(PATHOGEN, index_case=None)
    return w


def median_ms(fn: Callable[[], None], repeats: int = REPEATS) -> float:
    out: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(out)


# --------------------------------------------------------------------------- #
# timed advance (instance wrappers, so the split is exact)
# --------------------------------------------------------------------------- #
def timed_block(w, minutes: int = BLOCK, focus_xy=None) -> dict:
    """Advance ``minutes`` game-minutes, splitting mobility / outbreak / work."""
    cost = {"mobility_s": 0.0, "outbreak_s": 0.0, "work_s": 0.0}
    mob, ob, wk = w.mobility, w.outbreak, w.work
    mob_advance = mob.advance
    ob_advance = ob.advance if ob is not None else None
    wk_advance = wk.advance if wk is not None else None

    def mobw(dt, hour, _f=mob_advance):
        t0 = time.perf_counter()
        _f(dt, hour)
        cost["mobility_s"] += time.perf_counter() - t0

    mob.advance = mobw
    if ob is not None:
        def obw(dt, _f=ob_advance):
            t0 = time.perf_counter()
            _f(dt)
            cost["outbreak_s"] += time.perf_counter() - t0
        ob.advance = obw
    if wk is not None:
        def wkw(dt, _f=wk_advance):
            t0 = time.perf_counter()
            _f(dt)
            cost["work_s"] += time.perf_counter() - t0
        wk.advance = wkw

    t0 = time.perf_counter()
    for _ in range(minutes):
        w.advance_seconds(60.0, focus_xy=focus_xy)
    total_s = time.perf_counter() - t0

    mob.advance = mob_advance
    if ob is not None:
        ob.advance = ob_advance
    if wk is not None:
        wk.advance = wk_advance
    other_s = total_s - cost["mobility_s"] - cost["outbreak_s"] - cost["work_s"]
    return {"total_ms_per_game_minute": round(total_s * 1000.0 / minutes, 3),
            "mobility_ms_per_game_minute": round(cost["mobility_s"] * 1000.0 / minutes, 3),
            "outbreak_ms_per_game_minute": round(cost["outbreak_s"] * 1000.0 / minutes, 3),
            "work_ms_per_game_minute": round(cost["work_s"] * 1000.0 / minutes, 3),
            "other_ms_per_game_minute": round(other_s * 1000.0 / minutes, 3),
            "game_minutes": minutes}


def repeat_blocks(w, repeats: int = REPEATS, minutes: int = BLOCK, focus_xy=None) -> dict:
    rows = [timed_block(w, minutes, focus_xy) for _ in range(repeats)]
    keys = ("total_ms_per_game_minute", "mobility_ms_per_game_minute",
            "outbreak_ms_per_game_minute", "work_ms_per_game_minute",
            "other_ms_per_game_minute")
    out = {k: round(statistics.median(r[k] for r in rows), 3) for k in keys}
    out.update({"repeats": repeats, "game_minutes_per_block": minutes, "blocks": rows,
                "hour_after": round(w.current_hour(), 3)})
    return out


def warm(w, minutes: int = WARM, focus_xy=None) -> None:
    for _ in range(minutes):
        w.advance_seconds(60.0, focus_xy=focus_xy)


def work_state(w) -> dict:
    """What the work runtime is actually doing right now (context for a row)."""
    wk = w.work
    if wk is None:
        return {}
    kinds: Dict[str, int] = {}
    phases: Dict[str, int] = {}
    for a in wk.activities.values():
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
        phases[a.phase] = phases.get(a.phase, 0) + 1
    return {"n_sessions": len(wk.activities), "sessions_by_kind": dict(sorted(kinds.items())),
            "sessions_by_phase": dict(sorted(phases.items())),
            "n_employed": len(wk.employment), "n_registries": len(wk.registries),
            "n_holds": sum(len(v) for v in wk.ledger.holders.values()),
            "n_queued": sum(len(q) for q in wk.queues.values()),
            "counts": dict(sorted(wk.counts.items()))}


# --------------------------------------------------------------------------- #
# 1. registration cost
# --------------------------------------------------------------------------- #
def measure_registration(city: str, seed: int = 0) -> dict:
    """Registry + RoomGraph construction for every workplace and every home.

    Measured on a world booted with ``work: false`` and a fresh WorkRuntime, so
    no registry is warm. ``registry(bid)`` calls ``World.interior_descriptor``
    itself, so the descriptor cost is measured separately (on the same
    buildings, uncached — ``interiors.build_interior`` has no cache) and the
    remainder is the objects + doorway graph on top.
    """
    w = start_world(city, 5.0, work=False, seed=seed)
    recs = w.mobility.records
    profiles = w.citizens
    workplaces = sorted({int(r.work_building_id) for r in recs.values()
                         if r.work_building_id is not None})
    homes = sorted({int(r.home_building_id) for r in recs.values()
                    if r.home_building_id is not None}
                   | {int(getattr(p, "home_building_id"))
                      for p in profiles.values()
                      if getattr(p, "home_building_id", None) is not None})
    out = {"note": ("a fresh WorkRuntime on a work:false world, so every registry is "
                    "cold; registry(bid) builds the SmartObjectRegistry and the RoomGraph "
                    "and internally calls World.interior_descriptor(bid), whose cost is "
                    "measured separately on the same buildings")}

    for label, bids in (("workplaces", workplaces), ("homes", homes)):
        wr = WorkRuntime(w.mobility, seed, w.interior_descriptor)
        per: List[Tuple[float, int, int]] = []       # (ms, n_objects, bid)
        t_all = time.perf_counter()
        for bid in bids:
            t0 = time.perf_counter()
            reg = wr.registry(bid)
            per.append(((time.perf_counter() - t0) * 1000.0, len(reg), bid))
        total_ms = (time.perf_counter() - t_all) * 1000.0
        # the descriptor alone, same buildings, uncached
        t_all = time.perf_counter()
        n_rooms = 0
        n_decor = 0
        for bid in bids:
            d = w.interior_descriptor(bid)
            n_rooms += len(d.rooms)
            n_decor += len(d.decor) + len(d.fixtures)
        desc_ms = (time.perf_counter() - t_all) * 1000.0
        ms = [p[0] for p in per]
        worst = max(per) if per else (0.0, 0, -1)
        out[label] = {
            "n_buildings": len(bids),
            "total_ms": round(total_ms, 1),
            "descriptor_total_ms": round(desc_ms, 1),
            "objects_and_graph_total_ms": round(total_ms - desc_ms, 1),
            "descriptor_share": round(desc_ms / max(1e-9, total_ms), 3),
            "mean_ms_per_building": round(statistics.mean(ms), 3) if ms else 0.0,
            "median_ms_per_building": round(statistics.median(ms), 3) if ms else 0.0,
            "max_ms_per_building": round(worst[0], 3),
            "max_building_id": worst[2],
            "max_building_objects": worst[1],
            "n_objects": sum(p[1] for p in per),
            "mean_objects_per_building": round(
                statistics.mean([p[1] for p in per]), 1) if per else 0.0,
            "n_rooms": n_rooms,
            "n_descriptor_items": n_decor,
            "slowest": [{"building_id": b, "ms": round(m, 2), "objects": n}
                        for m, n, b in sorted(per, reverse=True)[:5]],
        }
        # a second, warm call must be free (the registry is cached)
        wbid = bids[0] if bids else None
        if wbid is not None:
            out[label]["warm_repeat_ms"] = round(
                median_ms(lambda b=wbid, r=wr: r.registry(b)), 5)
    out["all_buildings_ms"] = round(out["workplaces"]["total_ms"] + out["homes"]["total_ms"], 1)
    return out


# --------------------------------------------------------------------------- #
# 2. task selection
# --------------------------------------------------------------------------- #
def measure_selection(city: str, hour: float = 10.0, minutes: int = 10, seed: int = 0) -> dict:
    """Time every _select_work_task call in a live window (instance wrapper).

    The call is side-effecting (it reserves objects and emits events), so it is
    measured in place rather than replayed: each call is timed with its
    workplace and that workplace's object count, and the per-building rows show
    how the job-grammar scan scales with objects.
    """
    w = start_world(city, hour, seed=seed)
    warm(w)
    wk = w.work
    orig = wk._select_work_task
    rows: List[Tuple[float, int, int, str]] = []      # (ms, n_objects, bid, role)

    def wrapped(cid, ex, a, reg, g, _f=orig):
        t0 = time.perf_counter()
        r = _f(cid, ex, a, reg, g)
        rows.append(((time.perf_counter() - t0) * 1000.0, len(reg), a.building_id, a.role))
        return r

    wk._select_work_task = wrapped
    block = timed_block(w, minutes)
    wk._select_work_task = orig

    by_building: Dict[int, List[float]] = {}
    sizes: Dict[int, int] = {}
    for ms, n, bid, _role in rows:
        by_building.setdefault(bid, []).append(ms)
        sizes[bid] = n
    ms_all = [r[0] for r in rows]
    biggest = max(sizes, key=lambda b: (sizes[b], b)) if sizes else None
    out = {"hour": hour, "game_minutes": minutes, "n_calls": len(rows),
           "calls_per_game_minute": round(len(rows) / minutes, 2),
           "total_ms_per_game_minute": round(sum(ms_all) / minutes, 4),
           "mean_ms_per_call": round(statistics.mean(ms_all), 5) if ms_all else 0.0,
           "median_ms_per_call": round(statistics.median(ms_all), 5) if ms_all else 0.0,
           "max_ms_per_call": round(max(ms_all), 5) if ms_all else 0.0,
           "share_of_work_advance": round(
               (sum(ms_all) / minutes) / max(1e-9, block["work_ms_per_game_minute"]), 3),
           "block": block, "work_state": work_state(w),
           "note": ("_select_work_task is side-effecting (reservations, events), so it is "
                    "timed in place on a live world rather than replayed on a copy")}
    if biggest is not None:
        b = by_building[biggest]
        out["largest_workplace"] = {
            "building_id": biggest, "n_objects": sizes[biggest], "n_calls": len(b),
            "mean_ms_per_call": round(statistics.mean(b), 5),
            "max_ms_per_call": round(max(b), 5)}
    out["by_workplace_top5"] = [
        {"building_id": bid, "n_objects": sizes[bid], "n_calls": len(v),
         "mean_ms_per_call": round(statistics.mean(v), 5),
         "us_per_object_per_call": round(1000.0 * statistics.mean(v) / max(1, sizes[bid]), 4)}
        for bid, v in sorted(by_building.items(), key=lambda kv: -sizes[kv[0]])[:5]]
    return out


# --------------------------------------------------------------------------- #
# 3. reservation queries
# --------------------------------------------------------------------------- #
def measure_reservations(w, n_ops: int = 100_000) -> dict:
    """ReservationLedger microbench over a real registry's objects."""
    wk = w.work
    bid = max(wk.registries, key=lambda b: len(wk.registries[b]))
    reg = wk.registries[bid]
    excl = next((o for o in reg.objects.values() if o.exclusive), None)
    shared = next((o for o in reg.objects.values() if not o.exclusive), None)
    led = type(wk.ledger)()
    out = {"n_ops": n_ops, "building_id": bid, "n_objects": len(reg),
           "note": "a standalone ledger over one real building's objects, cid 0..999"}

    def bench(name: str, fn: Callable[[int], None]) -> None:
        t0 = time.perf_counter()
        for i in range(n_ops):
            fn(i)
        ms = (time.perf_counter() - t0) * 1000.0
        out[name] = {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                     "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0))}

    if excl is not None:
        bench("hold_release_exclusive",
              lambda i: (led.hold(excl, i % 1000, float(i)), led.release(i % 1000, excl.object_id)))
        bench("is_free_exclusive", lambda i: led.is_free(excl, True))
        bench("holders_of", lambda i: led.holders_of(excl.object_id))
    if shared is not None:
        bench("hold_release_shared",
              lambda i: (led.hold(shared, i % 1000, float(i), exclusive=False),
                         led.release(i % 1000, shared.object_id)))
        bench("is_free_shared", lambda i: led.is_free(shared, False))
    # release(cid) with no object id scans every held object: the O(holders) path
    for i in range(200):
        led.hold(reg.objects[sorted(reg.objects)[i % len(reg)]], 5000 + i, 0.0, exclusive=False)
    t0 = time.perf_counter()
    for i in range(10_000):
        led.held_by(1)
    out["held_by_scan"] = {"n_ops": 10_000, "n_held_objects": len(led.holders),
                           "us_per_op": round((time.perf_counter() - t0) * 1e6 / 10_000, 3),
                           "note": "held_by(cid) scans every held object; release(cid) uses it"}
    return out


# --------------------------------------------------------------------------- #
# 4/5. work execution and internal navigation
# --------------------------------------------------------------------------- #
def measure_hour(city: str, hour: float, label: str, seed: int = 0,
                 walk_share: bool = False) -> dict:
    w = start_world(city, hour, seed=seed)
    warm(w)
    wk = w.work
    walk = {"s": 0.0, "n": 0}
    if walk_share:
        orig = wk._walk

        def wrapped(ex, a, g, dt, _f=orig):
            t0 = time.perf_counter()
            r = _f(ex, a, g, dt)
            walk["s"] += time.perf_counter() - t0
            walk["n"] += 1
            return r
        wk._walk = wrapped
    row = repeat_blocks(w)
    if walk_share:
        wk._walk = orig
        row["walk"] = {
            "n_calls": walk["n"],
            "ms_per_game_minute": round(walk["s"] * 1000.0 / (REPEATS * BLOCK), 3),
            "share_of_work_advance": round(
                (walk["s"] * 1000.0 / (REPEATS * BLOCK))
                / max(1e-9, row["work_ms_per_game_minute"]), 3)}
    row["scenario"] = label
    row["hour"] = hour
    row["work_state"] = work_state(w)
    return row


def measure_routing(w, buildings=BIG_BUILDINGS) -> dict:
    """RoomGraph.route microbench across the largest interiors."""
    wk = w.work
    out = {"note": ("route() is BFS over the doorway graph; the pairs are the centres of "
                    "every room pair (capped), which is the worst case a walk can ask for")}
    rows = []
    for bid in buildings:
        try:
            g = wk.graph(int(bid))
        except Exception as exc:                                  # pragma: no cover
            rows.append({"building_id": int(bid), "error": f"{type(exc).__name__}: {exc}"})
            continue
        rids = sorted(g.rooms)
        pairs = [(g.rooms[a].center(), g.rooms[b].center())
                 for a in rids for b in rids if a != b][:2000]
        if not pairs:
            pairs = [(g.inside_xy, g.entrance_xy)]
        t0 = time.perf_counter()
        hops = 0
        for a, b in pairs:
            hops += len(g.route(a, b))
        ms = (time.perf_counter() - t0) * 1000.0
        rows.append({"building_id": int(bid), "n_rooms": len(g.rooms),
                     "n_objects": len(wk.registry(int(bid))),
                     "n_pairs": len(pairs), "total_ms": round(ms, 2),
                     "us_per_route": round(1000.0 * ms / len(pairs), 3),
                     "mean_waypoints": round(hops / len(pairs), 2)})
    out["by_building"] = rows
    return out


def commute_hour(city: str, hour: float = 7.0, seed: int = 0, minutes: int = 60) -> dict:
    """The whole 07:00-08:00 hour, one game minute at a time.

    A 10-minute block at 07:00 misses the mass departure: the cost of this hour
    is not flat, and a single game minute of it is what the real-time budget has
    to survive.
    """
    w = start_world_warm(city, hour, seed)
    rows = []
    for i in range(minutes):
        h = w.current_hour()
        r = timed_block(w, 1)
        rows.append({"minute": i, "hour": round(h, 4),
                     "total_ms": r["total_ms_per_game_minute"],
                     "mobility_ms": r["mobility_ms_per_game_minute"],
                     "work_ms": r["work_ms_per_game_minute"],
                     "n_sessions": len(w.work.activities),
                     "n_registries": len(w.work.registries)})
    worst = max(rows, key=lambda r: r["total_ms"])
    worst_work = max(rows, key=lambda r: r["work_ms"])
    return {"hour_from": hour, "hour_to": hour + minutes / 60.0, "minutes": minutes,
            "mean_total_ms_per_game_minute": round(
                statistics.mean(r["total_ms"] for r in rows), 2),
            "median_total_ms_per_game_minute": round(
                statistics.median(r["total_ms"] for r in rows), 2),
            "mean_work_ms_per_game_minute": round(
                statistics.mean(r["work_ms"] for r in rows), 2),
            "worst_minute": worst, "worst_work_minute": worst_work,
            "n_minutes_over_budget": sum(1 for r in rows if r["total_ms"] > BUDGET_MS),
            "per_minute": rows,
            "note": ("one timed game minute at a time; the departure peak is a mobility "
                     "route-planning spike, not a work-runtime cost")}


# --------------------------------------------------------------------------- #
# 10. worker-heavy variant
# --------------------------------------------------------------------------- #
def measure_worker_heavy(city: str, hour: float = 11.0, n_workplaces: int = 5,
                         seed: int = 0) -> dict:
    """Every registered citizen employed at one of the five largest workplaces.

    Built without touching ``asphodel/``: a second world with ``work: false``,
    a fresh WorkRuntime and ``employ_all`` fed synthetic profiles.
    """
    w = start_world(city, hour, work=False, seed=seed)
    probe = WorkRuntime(w.mobility, seed, w.interior_descriptor)
    recs = w.mobility.records
    workplaces = sorted({int(r.work_building_id) for r in recs.values()
                         if r.work_building_id is not None})
    sized = sorted(((len(probe.registry(b)), b) for b in workplaces), reverse=True)
    top = [b for _, b in sized[:n_workplaces]]
    profiles: Dict[int, object] = {}
    for i, cid in enumerate(sorted(w.mobility.execs)):
        occ = getattr(w.citizens.get(cid), "occupation", "") if w.citizens else ""
        profiles[cid] = types.SimpleNamespace(work_building_id=top[i % len(top)],
                                              occupation=occ)
    wk = WorkRuntime(w.mobility, seed, w.interior_descriptor)
    w.work = wk
    t0 = time.perf_counter()
    n = wk.employ_all(profiles)
    employ_ms = (time.perf_counter() - t0) * 1000.0
    warm(w)
    row = repeat_blocks(w)
    roles: Dict[str, int] = {}
    for e in wk.employment.values():
        roles[e.role] = roles.get(e.role, 0) + 1
    row.update({
        "scenario": f"worker-heavy {hour:.0f}:00 — every citizen employed at the "
                    f"{n_workplaces} largest workplaces",
        "hour": hour, "workplaces": top,
        "workplace_objects": {str(b): len(wk.registry(b)) for b in top},
        "n_employed": n, "roles": dict(sorted(roles.items())),
        "employ_all_ms": round(employ_ms, 1),
        "work_state": work_state(w),
        "caveat": ("employment alone does not create work sessions: WorkRuntime only opens a "
                   "worker session when the TripExecutor has actually delivered the citizen "
                   "into emp.workplace_id with activity 'work' (smart/runtime.py:234), and "
                   "the mobility runtime still routes everyone to the workplace in their own "
                   "bundle profile. This scenario therefore measures a maximal employment "
                   "table and a maximal per-workplace object/registry load, not 297 "
                   "simultaneous worker sessions."),
    })
    return row


# --------------------------------------------------------------------------- #
# 11. profile
# --------------------------------------------------------------------------- #
def _fname(fn: str) -> str:
    """``.../asphodel/smart/runtime.py`` -> ``smart/runtime.py`` (runtime.py alone
    is ambiguous: the mobility and the work runtime share the basename)."""
    parts = os.path.normpath(fn).split(os.sep)
    return "/".join(parts[-2:]) if len(parts) >= 2 else fn


# what each hot function costs *per what* — the scaling that matters when the
# city, the population or a building's furniture grows
SCALING: Dict[Tuple[str, str], str] = {
    ("smart/runtime.py", "_session_kind"): (
        "per registered citizen per 1 s substep (60 per game minute), whether or not that "
        "citizen is anywhere near a building — WorkRuntime._substep classifies every "
        "executor every substep (smart/runtime.py:202-223)"),
    ("smart/runtime.py", "_substep"): (
        "per registered citizen per 1 s substep — the `for cid in sorted(execs)` loop has no "
        "skip list, so it is O(citizens) x 60 per game minute even when nobody is working; "
        "the sorted() itself is O(n log n) per substep"),
    ("smart/runtime.py", "advance"): (
        "per game minute: 60 substeps x O(citizens)"),
    ("smart/runtime.py", "_advance_session"): (
        "per citizen with an open session per substep, gated by a.next_s wake scheduling"),
    ("smart/runtime.py", "_walk"): (
        "per citizen currently walking to an object, per 1 s substep"),
    ("smart/runtime.py", "_select_work_task"): (
        "per task selection x objects in the workplace"),
    ("smart/runtime.py", "_candidates"): (
        "per task selection x objects in the workplace (calls registry.with_affordance, "
        "which sorts every object id in the building on every call)"),
    ("smart/runtime.py", "_nearest_free"): (
        "per task selection x candidate objects (a hypot per candidate)"),
    ("smart/runtime.py", "_use"): "per using citizen per substep",
    ("smart/objects.py", "with_affordance"): (
        "per call: sorts every object of the building (O(objects log objects))"),
    ("smart/objects.py", "with_caps"): (
        "per call: sorts every object of the building (O(objects log objects))"),
    ("smart/objects.py", "use_xy"): "per candidate object per selection (two trig calls)",
    ("smart/rooms.py", "room_of"): (
        "per walking citizen per substep x rooms in the building (linear scan over every "
        "room rectangle)"),
    ("smart/rooms.py", "route"): "per interior walk x rooms (BFS over the doorway graph)",
    ("embodied/runtime.py", "_substep"): (
        "per registered citizen per 1 s substep — the mobility baseline this milestone adds "
        "to; citizens settled inside a building are skipped (embodied/runtime.py:464-471)"),
    ("embodied/executor.py", "inside"): (
        "per citizen per substep per caller — mobility and work each ask independently"),
    ("embodied/executor.py", "current_step"): "per citizen per substep per caller",
    ("embodied/traffic.py", "update_congestion"): "per game minute x road edges",
    ("asphodel/interiors.py", "build_interior"): (
        "per building, once per registry — but re-runs uncached on every "
        "World.interior_descriptor call"),
}


def measure_profile(city: str, hour: float = 10.0, minutes: int = 20, seed: int = 0):
    """cProfile a live window; returns (json-able doc, per-function lookup)."""
    w = start_world(city, hour, seed=seed)
    warm(w, 5)
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(minutes):
        w.advance_seconds(60.0)
    pr.disable()
    st = pstats.Stats(pr, stream=io.StringIO())
    total_s = st.total_tt

    rows = []
    for func, (_cc, nc, tt, ct, _callers) in st.stats.items():
        fn, ln, name = func
        rows.append({"function": f"{_fname(fn)}:{ln}({name})", "file": _fname(fn), "name": name,
                     "ncalls": nc, "tottime_s": round(tt, 4), "cumtime_s": round(ct, 4),
                     "tottime_pct": round(100.0 * tt / max(1e-9, total_s), 2),
                     "cumtime_pct": round(100.0 * ct / max(1e-9, total_s), 2),
                     "calls_per_game_minute": round(nc / minutes, 1)})
    by_tot = sorted(rows, key=lambda r: -r["tottime_s"])
    by_cum = sorted(rows, key=lambda r: -r["cumtime_s"])
    lookup = {(r["file"], r["name"]): r for r in rows}
    doc = {"hour": hour, "game_minutes": minutes, "profiled_total_s": round(total_s, 3),
           "ms_per_game_minute_under_profiler": round(total_s * 1000.0 / minutes, 1),
           "by_cumtime": by_cum[:15], "by_tottime": by_tot[:15],
           "work_state": work_state(w),
           "note": ("cProfile inflates absolute cost; read the shares, not the milliseconds. "
                    "The unprofiled cost of the same window is the 'advance' rows above.")}
    return doc, lookup


def hotspots(prof: dict, lookup: dict, sel: dict, reg: dict) -> List[dict]:
    """The hot functions of the profiled window, each with its scaling."""
    out = []
    for row in prof["by_tottime"][:12]:
        key = (row["file"], row["name"])
        out.append({"function": f"{row['file']}:{row['name']}",
                    "where": row["function"],
                    "tottime_pct": row["tottime_pct"],
                    "cumtime_pct": row["cumtime_pct"],
                    "calls_per_game_minute": row["calls_per_game_minute"],
                    "scaling": SCALING.get(key, "not annotated (see the profile rows)")})
    # the two subsystems the milestone owns, as cumulative shares
    for key, label, extra in (
            (("smart/runtime.py", "advance"), "WorkRuntime.advance (whole work runtime)", None),
            (("smart/runtime.py", "_select_work_task"), "WorkRuntime._select_work_task",
             {"calls_per_game_minute": sel.get("calls_per_game_minute"),
              "mean_ms_per_call": sel.get("mean_ms_per_call"),
              "largest_workplace": sel.get("largest_workplace")}),
            (("asphodel/interiors.py", "build_interior"), "interiors.build_interior "
             "(registration, one-off per building)",
             {"workplaces_total_ms": reg["workplaces"]["total_ms"],
              "homes_total_ms": reg["homes"]["total_ms"],
              "descriptor_share_of_registration": reg["workplaces"]["descriptor_share"]})):
        row = lookup.get(key)
        if row is None:
            continue
        item = {"function": label, "where": row["function"],
                "tottime_pct": row["tottime_pct"], "cumtime_pct": row["cumtime_pct"],
                "calls_per_game_minute": row["calls_per_game_minute"],
                "scaling": SCALING.get(key, "")}
        if extra:
            item["measured"] = extra
        out.append(item)
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="houston")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)
    city, seed = args.city, args.seed

    wall0 = time.perf_counter()
    res: dict = {}

    # -- world shape --------------------------------------------------------
    t0 = time.perf_counter()
    w0 = start_world(city, 5.0, seed=seed)
    build_ms = (time.perf_counter() - t0) * 1000.0
    n_cits = len(w0.mobility.execs)
    wk0 = w0.work
    res["world"] = {
        "n_citizens": n_cits, "n_vehicles": len(w0.mobility.vehicles),
        "start_world_ms": round(build_ms, 1),
        "n_employed": len(wk0.employment), "n_workplaces": len(wk0.registries),
        "n_objects_at_workplaces": sum(len(r) for r in wk0.registries.values()),
        "note": "START_WORLD enables work by default and employs every citizen with a workplace",
    }
    print(f"[{city}] START_WORLD in {build_ms / 1000:.1f} s, {n_cits} citizens, "
          f"{len(wk0.employment)} employed at {len(wk0.registries)} workplaces")

    # -- 1. registration ----------------------------------------------------
    res["registration"] = measure_registration(city, seed)
    r = res["registration"]
    print(f"  registration: workplaces {r['workplaces']['total_ms']:.0f} ms "
          f"({r['workplaces']['n_buildings']} buildings, {r['workplaces']['n_objects']} objects), "
          f"homes {r['homes']['total_ms']:.0f} ms ({r['homes']['n_buildings']} buildings)")

    # -- 2. task selection --------------------------------------------------
    res["task_selection"] = measure_selection(city, 10.0, BLOCK, seed)
    s = res["task_selection"]
    print(f"  selection:    {s['mean_ms_per_call']:.4f} ms/call, "
          f"{s['calls_per_game_minute']} calls/game-min")

    # -- 3. reservations ----------------------------------------------------
    res["reservations"] = measure_reservations(w0)
    print(f"  ledger:       hold+release {res['reservations']['hold_release_exclusive']['us_per_op']} "
          f"us/op exclusive")

    # -- 4. work execution by hour -----------------------------------------
    hours = [(6.0, "06:00 residents asleep at home"),
             (9.0, "09:00 shift start, workers walking to stations"),
             (11.0, "11:00 customers in shops"),
             (17.0, "17:00 shift end, commute home")]
    res["advance_by_hour"] = {}
    for hour, label in hours:
        row = measure_hour(city, hour, label, seed, walk_share=(hour == 9.0))
        res["advance_by_hour"][f"{int(hour):02d}00"] = row
        print(f"  advance {int(hour):02d}:00:  total {row['total_ms_per_game_minute']:8.2f} "
              f"ms/game-min (mobility {row['mobility_ms_per_game_minute']:.2f}, work "
              f"{row['work_ms_per_game_minute']:.2f}), {row['work_state']['n_sessions']} sessions")

    # -- 5. internal navigation --------------------------------------------
    res["navigation"] = measure_routing(w0)
    res["navigation"]["walk_share_0900"] = res["advance_by_hour"]["0900"].get("walk")
    for row in res["navigation"]["by_building"]:
        if "us_per_route" in row:
            print(f"  route b{row['building_id']}: {row['us_per_route']} us/route "
                  f"({row['n_rooms']} rooms, {row['n_objects']} objects)")

    # -- 6. focus FAR vs NEAR ----------------------------------------------
    wf = start_world(city, 9.0, seed=seed)
    warm(wf)
    far = repeat_blocks(wf, focus_xy=FAR_XY)
    bands_far: Dict[str, int] = {}
    for b in wf.mobility.bands.values():
        bands_far[b.name.lower()] = bands_far.get(b.name.lower(), 0) + 1
    near_xy = wf.mobility.entrances.get(NEAR_BUILDING)
    near = repeat_blocks(wf, focus_xy=near_xy)
    bands_near: Dict[str, int] = {}
    for b in wf.mobility.bands.values():
        bands_near[b.name.lower()] = bands_near.get(b.name.lower(), 0) + 1
    res["focus"] = {
        "far": {**far, "focus_xy": list(FAR_XY), "bands": bands_far},
        "near": {**near, "focus_xy": None if near_xy is None else [round(near_xy[0], 2),
                                                                   round(near_xy[1], 2)],
                 "near_building_id": NEAR_BUILDING, "bands": bands_near},
        "work_ms_delta": round(near["work_ms_per_game_minute"] - far["work_ms_per_game_minute"], 3),
        "max_active": wf.mobility.max_active,
        "note": ("the work runtime never reads focus_xy or the LOD band — there is no "
                 "reference to either anywhere in asphodel/smart — so a NEAR workplace runs "
                 "exactly the same Python as a FAR one. The measured work delta of "
                 f"{round(near['work_ms_per_game_minute'] - far['work_ms_per_game_minute'], 3)} "
                 f"ms/game-minute is machine noise plus the mobility band change (far bands "
                 f"{bands_far}, near bands {bands_near}); mobility freezes citizens into "
                 f"ABSTRACT only beyond max_active={wf.mobility.max_active} and this city "
                 f"registers {len(wf.mobility.execs)}, so nothing froze either way. The "
                 "Godot-side cost of embodying a NEAR worker is measured by the in-engine "
                 "gate, not here."),
    }
    print(f"  focus far:    work {far['work_ms_per_game_minute']} ms/game-min; "
          f"near work {near['work_ms_per_game_minute']}")

    # -- 7. NEAR embodiment -------------------------------------------------
    res["near_embodiment"] = {
        "measured": False,
        "status": "not measured here",
        "reason": ("materialising interior worker bodies, their station animations and the "
                   "MOBILITY_REPORT rows they add is Godot-side cost; this tool measures the "
                   "Python authority only"),
        "gate": {"scene": "godot/tests/WorkGate.tscn", "script": "godot/tests/work_gate.gd",
                 "runner": "tools/run_work_gate.sh",
                 "artifacts": "artifacts/smart_objects_work_v1/godot_probe_trace.json"},
    }

    # -- 8. commute peak ----------------------------------------------------
    peak = measure_hour(city, 7.0, "07:00-08:00 commute peak with workers active", seed)
    peak_long = commute_hour(city, 7.0, seed)
    peak["full_hour_0700_0800"] = peak_long
    res["commute_peak"] = peak
    print(f"  commute 07:00: total {peak['total_ms_per_game_minute']:.2f} ms/game-min "
          f"(mobility {peak['mobility_ms_per_game_minute']:.2f}, work "
          f"{peak['work_ms_per_game_minute']:.2f}); full hour "
          f"mean {peak_long['mean_total_ms_per_game_minute']:.1f}, worst minute "
          f"{peak_long['worst_minute']['total_ms']:.0f} ms at "
          f"{peak_long['worst_minute']['hour']:.2f}h)")

    # -- 9. outbreak + work -------------------------------------------------
    wo = start_world(city, 5.0, outbreak=True, seed=seed)
    t0 = time.perf_counter()
    for _ in range(int((11.0 - 5.0) * 60)):
        wo.advance_seconds(60.0)
    warm_s = time.perf_counter() - t0
    comb = repeat_blocks(wo, minutes=BLOCK)
    counts = wo.outbreak.snapshot()["counts"]
    comb.update({"scenario": "outbreak (classic_zombie, data-driven index case) + work, "
                             "seeded 05:00, measured 11:00-11:20",
                 "pathogen": PATHOGEN, "warmup_0500_to_1100_s": round(warm_s, 1),
                 "health": dict(sorted(counts.items())),
                 "n_records": len(wo.outbreak.records),
                 "work_state": work_state(wo)})
    res["outbreak_plus_work"] = comb
    print(f"  outbreak+work 11:00: total {comb['total_ms_per_game_minute']:.2f} "
          f"(mobility {comb['mobility_ms_per_game_minute']:.2f}, outbreak "
          f"{comb['outbreak_ms_per_game_minute']:.2f}, work {comb['work_ms_per_game_minute']:.2f})")

    # -- 10. worker-heavy ---------------------------------------------------
    res["worker_heavy"] = measure_worker_heavy(city, 11.0, 5, seed)
    hv = res["worker_heavy"]
    print(f"  worker-heavy 11:00: {hv['n_employed']} employed, total "
          f"{hv['total_ms_per_game_minute']:.2f} ms/game-min (work "
          f"{hv['work_ms_per_game_minute']:.2f})")

    # -- 11. profile --------------------------------------------------------
    res["profile"], prof_lookup = measure_profile(city, 10.0, 20, seed)
    res["hotspots"] = hotspots(res["profile"], prof_lookup, res["task_selection"],
                               res["registration"])

    # -- budget -------------------------------------------------------------
    cands = [res["advance_by_hour"][k] for k in sorted(res["advance_by_hour"])]
    cands += [peak, comb, hv]
    worst = max(cands, key=lambda d: d["total_ms_per_game_minute"])
    wm = worst["total_ms_per_game_minute"]
    ch = peak["full_hour_0700_0800"]
    worst_minute = ch["worst_minute"]
    res["budget"] = {
        "clock_multiplier": CLOCK_X,
        "real_seconds_per_game_minute": GAME_MINUTE_REAL_S,
        "budget_ms": BUDGET_MS,
        "worst_total_ms_per_game_minute": wm,
        "worst_scenario": worst["scenario"],
        "worst_work_ms_per_game_minute": worst["work_ms_per_game_minute"],
        "budget_used_fraction_worst": round(wm / BUDGET_MS, 4),
        "headroom_x": round(BUDGET_MS / wm, 1) if wm else None,
        "headroom_x_worst_single_minute": round(
            BUDGET_MS / worst_minute["total_ms"], 2) if worst_minute["total_ms"] else None,
        "work_share_worst": round(worst["work_ms_per_game_minute"] / max(1e-9, wm), 3),
        "registration_one_off_ms": res["registration"]["all_buildings_ms"],
        "worst_single_game_minute": {
            "scenario": "07:00-08:00 measured minute by minute",
            "hour": worst_minute["hour"], "total_ms": worst_minute["total_ms"],
            "mobility_ms": worst_minute["mobility_ms"], "work_ms": worst_minute["work_ms"],
            "budget_used_fraction": round(worst_minute["total_ms"] / BUDGET_MS, 3),
            "n_minutes_over_budget_in_that_hour": ch["n_minutes_over_budget"],
            "mean_over_that_hour_ms": ch["mean_total_ms_per_game_minute"]},
        "note": (f"at {CLOCK_X:.0f}x one game minute is {GAME_MINUTE_REAL_S} s of real time "
                 f"({BUDGET_MS:.0f} ms). The heaviest measured game-minute ({wm} ms, "
                 f"{n_cits} citizens) uses {100.0 * wm / BUDGET_MS:.2f}% of it; the work "
                 f"runtime is {worst['work_ms_per_game_minute']} ms of that. "
                 f"The 07:00-08:00 hour, measured minute by minute, averages "
                 f"{ch['mean_total_ms_per_game_minute']} ms and peaks at "
                 f"{worst_minute['total_ms']} ms in one game minute "
                 f"({worst_minute['mobility_ms']} ms of it mobility route planning), "
                 f"{ch['n_minutes_over_budget']} minute(s) of that hour over budget. "
                 f"Registration is a one-off "
                 f"{res['registration']['all_buildings_ms']:.0f} ms for every workplace and "
                 f"home in the city, paid lazily per building on first entry."),
    }

    doc = {"version": 1, "milestone": "ASPHODEL_SMART_OBJECTS_WORK_V1",
           "city": city, "seed": seed, "repeats": REPEATS, "unit": "milliseconds",
           "machine": {"python": sys.version.split()[0],
                       "implementation": platform.python_implementation(),
                       "platform": platform.platform(),
                       "machine": platform.machine(),
                       "processor": platform.processor(),
                       "cpu_count": os.cpu_count(),
                       "loadavg_1_5_15": [round(v, 2) for v in os.getloadavg()],
                       "loadavg_note": ("this repository's CI machine is shared; a load average "
                                        "above the cpu count means the milliseconds below are "
                                        "inflated by other work on the box")},
           "wall_s": round(time.perf_counter() - wall0, 1),
           **res}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    print_table(doc)
    print(f"  artifact: {args.out}")
    return 0


def start_world_warm(city: str, hour: float, seed: int):
    w = start_world(city, hour, seed=seed)
    warm(w)
    return w


def print_table(doc: dict) -> None:
    rows: List[Tuple[str, Optional[float], str]] = []
    r = doc["registration"]
    for k in ("workplaces", "homes"):
        b = r[k]
        rows.append((f"registration: all {k}", b["total_ms"],
                     f"{b['n_buildings']} buildings, {b['n_objects']} objects, "
                     f"mean {b['mean_ms_per_building']} ms, max {b['max_ms_per_building']} ms "
                     f"(b{b['max_building_id']}), descriptor {b['descriptor_share'] * 100:.0f}%"))
    s = doc["task_selection"]
    rows.append(("_select_work_task (per call)", s["mean_ms_per_call"],
                 f"{s['calls_per_game_minute']} calls/game-min = "
                 f"{s['total_ms_per_game_minute']} ms/game-min, "
                 f"{s['share_of_work_advance'] * 100:.0f}% of work.advance"))
    res = doc["reservations"]
    for k in ("hold_release_exclusive", "hold_release_shared", "is_free_exclusive", "holders_of"):
        if k in res:
            rows.append((f"ledger {k}", res[k]["us_per_op"] / 1000.0,
                         f"{res[k]['us_per_op']} us/op, {res[k]['ops_per_s']:,} ops/s"))
    for key in sorted(doc["advance_by_hour"]):
        a = doc["advance_by_hour"][key]
        rows.append((f"advance {a['scenario'][:34]}", a["total_ms_per_game_minute"],
                     f"mobility {a['mobility_ms_per_game_minute']}, work "
                     f"{a['work_ms_per_game_minute']}, other {a['other_ms_per_game_minute']}, "
                     f"{a['work_state']['n_sessions']} sessions "
                     f"{a['work_state']['sessions_by_kind']}"))
    for row in doc["navigation"]["by_building"]:
        if "us_per_route" in row:
            rows.append((f"RoomGraph.route b{row['building_id']}", row["us_per_route"] / 1000.0,
                         f"{row['us_per_route']} us/route over {row['n_pairs']} room pairs, "
                         f"{row['n_rooms']} rooms, mean {row['mean_waypoints']} waypoints"))
    walk = doc["navigation"].get("walk_share_0900")
    if walk:
        rows.append(("_walk inside work.advance (09:00)", walk["ms_per_game_minute"],
                     f"{walk['n_calls']} calls, "
                     f"{walk['share_of_work_advance'] * 100:.0f}% of work.advance"))
    f = doc["focus"]
    rows.append(("advance 09:00, focus FAR", f["far"]["total_ms_per_game_minute"],
                 f"work {f['far']['work_ms_per_game_minute']}, bands {f['far']['bands']}"))
    rows.append(("advance 09:00, focus NEAR", f["near"]["total_ms_per_game_minute"],
                 f"work {f['near']['work_ms_per_game_minute']}, bands {f['near']['bands']}, "
                 f"delta {f['work_ms_delta']} ms"))
    p = doc["commute_peak"]
    rows.append(("advance commute peak 07:00", p["total_ms_per_game_minute"],
                 f"mobility {p['mobility_ms_per_game_minute']}, work "
                 f"{p['work_ms_per_game_minute']}; full hour "
                 f"mean {p['full_hour_0700_0800']['mean_total_ms_per_game_minute']} ms/game-min, "
                 f"worst minute {p['full_hour_0700_0800']['worst_minute']['total_ms']} ms "
                 f"(mobility {p['full_hour_0700_0800']['worst_minute']['mobility_ms']})"))
    c = doc["outbreak_plus_work"]
    rows.append(("advance outbreak+work 11:00", c["total_ms_per_game_minute"],
                 f"mobility {c['mobility_ms_per_game_minute']}, outbreak "
                 f"{c['outbreak_ms_per_game_minute']}, work {c['work_ms_per_game_minute']}, "
                 f"health {c['health']}"))
    h = doc["worker_heavy"]
    rows.append(("advance worker-heavy 11:00", h["total_ms_per_game_minute"],
                 f"{h['n_employed']} employed at {len(h['workplaces'])} workplaces, work "
                 f"{h['work_ms_per_game_minute']}, roles {h['roles']}"))

    print("")
    print(f"{'measurement':46s} {'ms':>10s}  detail")
    print("-" * 46 + " " + "-" * 10 + "  " + "-" * 60)
    for name, ms, detail in rows:
        val = "-" if ms is None else f"{ms:.4f}".rstrip("0").rstrip(".")
        print(f"{name:46s} {val:>10s}  {detail}")

    print("")
    print(f"  profile (cProfile, {doc['profile']['game_minutes']} game-minutes at "
          f"{doc['profile']['hour']:.0f}:00) — top 8 by tottime:")
    for row in doc["profile"]["by_tottime"][:8]:
        print(f"    {row['tottime_pct']:5.2f}%  {row['function']:58s} "
              f"{row['ncalls']:>10,} calls")
    print("")
    print("  hotspots:")
    for hs in doc["hotspots"]:
        print(f"    tot {hs['tottime_pct']:5.2f}%  cum {hs['cumtime_pct']:6.2f}%  "
              f"{hs['function']}  ({hs['calls_per_game_minute']:,.0f} calls/game-min)")
        print(f"            scaling: {hs['scaling']}")
    print("")
    print(f"  near embodiment: {doc['near_embodiment']['status']} — "
          f"{doc['near_embodiment']['reason']}")
    print(f"                   gate: {doc['near_embodiment']['gate']['runner']} "
          f"({doc['near_embodiment']['gate']['scene']})")
    b = doc["budget"]
    print("")
    print(f"  budget: {b['note']}")
    print(f"          headroom {b['headroom_x']}x on the heaviest measured block "
          f"({b['worst_scenario']}); {b['headroom_x_worst_single_minute']}x on the worst "
          f"single game minute ({b['worst_single_game_minute']['total_ms']} ms at "
          f"{b['worst_single_game_minute']['hour']:.2f}h, "
          f"{b['worst_single_game_minute']['mobility_ms']} ms mobility)")


if __name__ == "__main__":
    raise SystemExit(main())

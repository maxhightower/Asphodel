#!/usr/bin/env python3
"""Wall-clock performance of the survivor-group runtime on one city bundle
(ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1).

Everything the survivor-group layer adds on top of the mobility / outbreak /
work / cognition / dialogue runtimes, in milliseconds, measured by wrapping
``GroupRuntime.advance`` at the instance level and comparing its cost against
the whole ``World.advance_seconds`` step it runs inside:

    world_step        ms per game minute of the whole world step (all runtimes)
                      with the group layer ON, in a normal Houston window
    groups_advance    ms per game minute spent inside GroupRuntime.advance, and
                      that as a SHARE of the world step — the headline cost
    formation_scan    ms of a single _scan_formation() over the whole live
                      population (the edge-indexed, O(sum of degrees) scan the
                      1 s advance runs at most once every two game minutes)
    outbreak_window   the same groups_advance cost measured inside a seeded
                      outbreak window (threats drive formation/warnings, the
                      group layer's busiest moment)
    two_groups        groups_advance with >=2 simultaneous groups formed (the
                      per-group tick cost is linear in the number of groups)

The group layer should be a small fraction of the world step: formation is
edge-indexed and timer-gated (a scan at most every two game minutes), objective
processing touches only members, and knowledge reuses the single dialogue
transmission path — there is no O(N^2) matching.

    PYTHONPATH=. python3 tools/groups_perf.py [--city houston]

Writes artifacts/survivor_groups_v1/performance.json.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import platform
import statistics
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.cognition import memory as M                            # noqa: E402
from asphodel.groups import model as GM                               # noqa: E402
from asphodel.groups import runtime as GR                             # noqa: E402

ARTIFACT = os.path.join(REPO, "artifacts", "survivor_groups_v1", "performance.json")
CLOCK_X = 24.0                        # default game clock: 24x real time
GAME_MINUTE_REAL_S = 60.0 / CLOCK_X   # => 2.5 s of real time per game minute
BUDGET_MS = GAME_MINUTE_REAL_S * 1000.0
START_HOUR = 8.0
WARM_MINUTES = 120
FAR = (9000.0, 9000.0)
SEED = 0
PLAYER_CITIZEN = 0
NORMAL_BLOCK = 15                     # game minutes timed in a normal window
OUTBREAK_BLOCK = 15
SCAN_REPEATS = 25
SEED_HOUR = 10.5833
PATHOGEN = "classic_zombie_fast"


class GroupTimer:
    """Wrap GroupRuntime.advance at the instance level to accumulate its
    wall-clock cost without touching the frozen runtime source."""

    def __init__(self, groups):
        self.groups = groups
        self._orig = groups.advance
        self.total_s = 0.0
        self.calls = 0
        groups.advance = self._timed

    def _timed(self, dt_s):
        t0 = time.perf_counter()
        r = self._orig(dt_s)
        self.total_s += time.perf_counter() - t0
        self.calls += 1
        return r

    def reset(self):
        self.total_s = 0.0
        self.calls = 0

    def restore(self):
        self.groups.advance = self._orig


def build_world(city: str, start_hour: float = START_HOUR, seed: int = SEED):
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
           "start_hour": float(start_hour), "player_citizen": PLAYER_CITIZEN}
    r = s.handle(msg)
    if not r.get("ok"):
        msg.pop("player_citizen")
        r = s.handle(msg)
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    if not r.get("groups_enabled"):
        raise RuntimeError(f"groups not enabled for {city}: {r}")
    return s, s.world


def run(w, minutes):
    for _ in range(int(minutes)):
        w.advance_seconds(60.0, focus_xy=FAR)


def clusters(w, want=2):
    """Up to `want` DISJOINT co-present trios discovered from authoritative
    co-presence — the seeds for forming multiple groups, never named."""
    c = w.cognition
    rooms = collections.defaultdict(list)
    for cid in sorted(w.mobility.execs):
        ex = w.mobility.execs[cid]
        if ex.inside and c._can_perceive(cid):
            rooms[(int(ex.building_id), c._ctx(cid).get("room_id"))].append(cid)
    out = []
    used = set()
    for k, v in sorted(rooms.items()):
        avail = [x for x in sorted(v) if x not in used]
        if len(avail) >= 3:
            trio = avail[:3]
            out.append((trio, k[0]))
            used |= set(trio)
        if len(out) >= want:
            break
    return out


def cooperate(c, trio, rounds=3):
    a, b, cc = trio
    for _ in range(rounds):
        for x, y in [(a, b), (b, a), (a, cc), (cc, a), (b, cc), (cc, b)]:
            c.relate(x, y, "fled_with")
            c.relate(y, x, "helped_by")


def timed_block(w, timer: GroupTimer, minutes: int) -> Tuple[float, float]:
    """Advance `minutes` game minutes; return (ms per game minute of the whole
    world step, ms per game minute inside GroupRuntime.advance)."""
    timer.reset()
    t0 = time.perf_counter()
    run(w, minutes)
    world_s = time.perf_counter() - t0
    world_ms = world_s / minutes * 1000.0
    grp_ms = timer.total_s / minutes * 1000.0
    return world_ms, grp_ms


def measure(city: str) -> dict:
    out: dict = {"city": city, "protocol_version": PROTOCOL_VERSION,
                 "clock_x": CLOCK_X, "budget_ms_per_game_minute": round(BUDGET_MS, 2)}

    # -- normal window -----------------------------------------------------
    s, w = build_world(city)
    run(w, WARM_MINUTES)                     # 08:00 -> 10:00
    timer = GroupTimer(w.groups)
    n_pop = len(w.mobility.execs)
    world_ms, grp_ms = timed_block(w, timer, NORMAL_BLOCK)
    out["population"] = n_pop
    out["normal_window"] = {
        "hour": round(w.current_hour(), 3), "minutes_timed": NORMAL_BLOCK,
        "world_step_ms_per_game_minute": round(world_ms, 4),
        "groups_advance_ms_per_game_minute": round(grp_ms, 4),
        "groups_share_of_world_step": round(grp_ms / world_ms, 5) if world_ms else None,
        "n_groups": len(w.groups.groups),
        "note": "groups on, no group formed yet in a fresh window — the pure advance overhead"}

    # -- formation-scan cost (a single full scan over the live population) --
    scan_ms = []
    for _ in range(SCAN_REPEATS):
        w.groups._last_form_scan = -1e9
        t0 = time.perf_counter()
        w.groups._scan_formation()
        scan_ms.append((time.perf_counter() - t0) * 1000.0)
    out["formation_scan"] = {
        "median_ms": round(statistics.median(scan_ms), 4),
        "max_ms": round(max(scan_ms), 4), "repeats": SCAN_REPEATS,
        "population": n_pop, "scan_interval_s": GR.FORM_SCAN_S,
        "note": ("edge-indexed O(sum of member degrees) scan; the 1 s advance runs it at most "
                 f"once every {GR.FORM_SCAN_S:.0f} game seconds, so its amortised per-second cost "
                 "is this divided by that interval")}
    out["formation_scan"]["amortised_ms_per_game_minute"] = round(
        statistics.median(scan_ms) * (60.0 / GR.FORM_SCAN_S), 5)

    # -- form >=2 groups and measure the per-group tick --------------------
    cs = clusters(w, want=2)
    formed = []
    for trio, _bid in cs:
        cooperate(w.cognition, trio, rounds=3)
    w.groups._last_form_scan = -1e9
    w.groups._scan_formation()
    formed = list(w.groups.groups.keys())
    # give each formed group a shelter so the tick exercises objective progress too
    for g in w.groups.groups.values():
        w.groups.select_shelter(g)
    world_ms2, grp_ms2 = timed_block(w, timer, NORMAL_BLOCK)
    out["two_groups"] = {
        "n_groups": len(w.groups.groups), "group_ids": formed,
        "members": {gid: g.active_members() for gid, g in w.groups.groups.items()},
        "world_step_ms_per_game_minute": round(world_ms2, 4),
        "groups_advance_ms_per_game_minute": round(grp_ms2, 4),
        "groups_share_of_world_step": round(grp_ms2 / world_ms2, 5) if world_ms2 else None,
        "note": "per-group objective/influence/departure tick is linear in the number of groups"}

    # -- outbreak window ---------------------------------------------------
    s2, w2 = build_world(city)
    run(w2, WARM_MINUTES)
    # seed the busiest shop, as the certification does
    by_b = collections.defaultdict(list)
    for cid, a in sorted(w2.work.activities.items()):
        if a.kind == "customer":
            by_b[int(a.building_id)].append(int(cid))
    seed_info = {"seeded": False}
    if by_b:
        bid = sorted(by_b.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
        cid = min(by_b[bid])
        r = s2.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": PATHOGEN, "citizen_id": int(cid)})
        seed_info = {"seeded": bool(r.get("ok")), "building_id": bid, "index_case": r.get("index_case")}
    else:
        r = s2.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": "classic_zombie"})
        seed_info = {"seeded": bool(r.get("ok")), "fallback": True, "index_case": r.get("index_case")}
    timer2 = GroupTimer(w2.groups)
    world_ms3, grp_ms3 = timed_block(w2, timer2, OUTBREAK_BLOCK)
    out["outbreak_window"] = {
        "hour": round(w2.current_hour(), 3), "minutes_timed": OUTBREAK_BLOCK,
        "seed": seed_info,
        "world_step_ms_per_game_minute": round(world_ms3, 4),
        "groups_advance_ms_per_game_minute": round(grp_ms3, 4),
        "groups_share_of_world_step": round(grp_ms3 / world_ms3, 5) if world_ms3 else None,
        "n_groups": len(w2.groups.groups),
        "note": "threats drive formation scans and warnings — the group layer's busiest window"}
    timer.restore()
    timer2.restore()

    # -- headline ----------------------------------------------------------
    # Two denominators, both reported: the bridge world step (Python runtimes
    # only — no Godot rendering/physics, so a cheap FAR-focus step makes even a
    # tiny absolute group cost look like a big *share*), and the real-time
    # budget (2.5 s per game minute at the 24x clock), which is the denominator
    # that actually matters for whether the game keeps up. The verdict is judged
    # against the budget; the world-step shares are reported as context.
    grp_ms_all = [out["normal_window"]["groups_advance_ms_per_game_minute"],
                  out["two_groups"]["groups_advance_ms_per_game_minute"],
                  out["outbreak_window"]["groups_advance_ms_per_game_minute"]]
    shares = [x for x in [out["normal_window"]["groups_share_of_world_step"],
                          out["two_groups"]["groups_share_of_world_step"],
                          out["outbreak_window"]["groups_share_of_world_step"]] if x is not None]
    max_grp_ms = max(grp_ms_all)
    budget_frac = max_grp_ms / BUDGET_MS
    out["headline"] = {
        "max_groups_advance_ms_per_game_minute": round(max_grp_ms, 4),
        "max_groups_share_of_world_step": round(max(shares), 5) if shares else None,
        "max_groups_share_of_realtime_budget": round(budget_frac, 6),
        "groups_advance_ms_per_game_minute_normal": out["normal_window"]["groups_advance_ms_per_game_minute"],
        "groups_advance_ms_per_game_minute_outbreak": out["outbreak_window"]["groups_advance_ms_per_game_minute"],
        "formation_scan_median_ms": out["formation_scan"]["median_ms"],
        "budget_ms_per_game_minute": round(BUDGET_MS, 2),
        "verdict": ("the survivor-group layer is a small fraction of the real-time budget "
                    f"(worst case {max_grp_ms:.2f} ms per game minute = {budget_frac*100:.2f}% of the "
                    f"{BUDGET_MS:.0f} ms budget); its share of the bridge world step ranges "
                    f"{min(shares)*100:.1f}%-{max(shares)*100:.1f}% because that step excludes Godot "
                    "rendering/physics, so a cheap FAR-focus step inflates the ratio"
                    if budget_frac < 0.05 else
                    "the survivor-group layer is a NOTABLE fraction of the real-time budget — inspect")}
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="houston")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    doc = {"milestone": "ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1",
           "python": platform.python_version(), "platform": platform.platform(),
           "measured": measure(args.city)}
    doc["wall_s"] = round(time.perf_counter() - t0, 1)
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w") as f:
        json.dump(doc, f, indent=2)
    h = doc["measured"]["headline"]
    print(f"wrote {ARTIFACT}")
    print(f"  population {doc['measured']['population']}, "
          f"groups.advance normal {h['groups_advance_ms_per_game_minute_normal']} ms/game-min, "
          f"outbreak {h['groups_advance_ms_per_game_minute_outbreak']} ms/game-min")
    print(f"  formation scan median {h['formation_scan_median_ms']} ms; "
          f"max groups.advance {h['max_groups_advance_ms_per_game_minute']} ms/game-min = "
          f"{h['max_groups_share_of_realtime_budget']*100:.2f}% of the {h['budget_ms_per_game_minute']} ms budget; "
          f"world-step share up to {h['max_groups_share_of_world_step']}")
    print(f"  {h['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

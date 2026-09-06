#!/usr/bin/env python3
"""Wall-clock performance of the NPC cognition runtime on one city bundle.

Everything ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 adds on top of the
mobility / outbreak / work runtimes, in milliseconds (median of 3 repeats
where a repeat is cheap):

    perception    CognitionRuntime._perceive_work + _perceive_outbreak per
                  game minute at 08:00, in the threat window, and at 16:00,
                  with the number of backend event rows drained per minute
    memory        MemoryStore.remember over 1e5 operations (new keys vs
                  reinforcement of an existing key) and consolidate()
    lookup        store.find / about / salient over a 64-fact store, 1e5 ops
    beliefs       beliefs.derive over stores of 5, 20 and 64 facts
    relationships RelationshipGraph.apply and CognitionRuntime.help_score,
                  1e5 operations each
    decisions     _decide_help + _decide_avoid + _observe_safety, timed in
                  place over a live 10 game-minute window at 08:00 and 11:00
    social        _copresence per call (with the number of pairs it meets)
                  and _alarmed_encounters per second while alarmed citizens
                  exist (the 11:00 threat window)
    rumor         WARNING_SHARED per game minute across the threat window,
                  the size of the told-set, and the boundedness proof
                  (tellings per sender, hops)
    focus         the same advance with the mobility focus far from the city
                  vs at a building entrance, with cognition.advance timed
                  separately by an instance wrapper
    day           the whole Houston day 05:00 -> 20:00 with cognition on vs
                  the same day booted with START_WORLD ``cognition: false``,
                  split mobility / outbreak / work / cognition per game minute
    combined      work + outbreak + cognition in the same world across the
                  threat window, milliseconds per game minute
    profile       a cProfile top-15 of cognition.advance alone over 20 game
                  minutes in the threat window
    memory growth total facts and the maximum facts held by one citizen over
                  the day (must stay <= memory.CAPACITY) and the number of
                  relationships

and states the implied real-time budget: at the default 24x clock one game
minute takes 2.5 s of real time.

The threat stressor is seeded the way the certification seeds it: the world
is booted at 05:00 and advanced to the first game minute at or after
``--seed-hour`` in which any customer work session exists; the busiest shop
(the building with the most ``customer`` sessions, ties by lowest building
id) is chosen and its lowest customer id is the index case of a
``classic_zombie_fast`` outbreak seeded through the bridge. If no customer
session exists by the cutoff, a ``classic_zombie`` with the data-driven
index case is seeded instead and the artifact says so.

    PYTHONPATH=. python3 tools/cognition_perf.py [--city houston]

Writes artifacts/npc_cognition_v1/performance.json.
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
from typing import Callable, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.cognition import memory as M                            # noqa: E402
from asphodel.cognition.beliefs import derive                         # noqa: E402
from asphodel.cognition.relationships import RelationshipGraph        # noqa: E402

ARTIFACT = os.path.join(REPO, "artifacts", "npc_cognition_v1", "performance.json")
REPEATS = 3
BLOCK = 10                            # game-minutes per timed block
WARM = 3                              # game-minutes of warm-up before a block
CLOCK_X = 24.0                        # default game clock: 24x real time
GAME_MINUTE_REAL_S = 60.0 / CLOCK_X   # => 2.5 s of real time per game minute
BUDGET_MS = GAME_MINUTE_REAL_S * 1000.0
FAR_XY = (9000.0, 9000.0)             # a focus away from the city
NEAR_BUILDING = 8470                  # focus building for the NEAR case
DAY_FROM = 5.0
DAY_TO = 20.0
SEED_HOUR = 10.5833                   # 10:35 — the earliest the stressor is seeded
SEED_CUTOFF_HOUR = 12.0               # give up looking for a customer session here
PATHOGEN = "classic_zombie_fast"
FALLBACK_PATHOGEN = "classic_zombie"
MICRO_OPS = 100_000
DERIVE_OPS = 20_000


# --------------------------------------------------------------------------- #
# world construction (exactly how the game boots one: bridge START_WORLD)
# --------------------------------------------------------------------------- #
def start_world(city: str, start_hour: float, cognition: bool = True, work: bool = True,
                seed: int = 0):
    """A world from the bundle through the bridge, as START_WORLD builds it.

    Returns ``(session, world)``: the session is kept so the stressor can be
    seeded later through the same command the game uses (SEED_OUTBREAK).
    """
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
           "start_hour": float(start_hour), "work": bool(work), "cognition": bool(cognition)}
    r = s.handle(msg)
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    if bool(r.get("cognition_enabled")) != bool(cognition):
        raise RuntimeError(f"START_WORLD cognition_enabled={r.get('cognition_enabled')} "
                           f"but cognition={cognition} was asked for")
    return s, s.world


def median_ms(fn: Callable[[], None], repeats: int = REPEATS) -> float:
    out: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(out)


def warm(w, minutes: int = WARM, focus_xy=None) -> None:
    for _ in range(minutes):
        w.advance_seconds(60.0, focus_xy=focus_xy)


def run_to(w, hour: float, focus_xy=None) -> int:
    """Advance in whole game minutes until ``hour``; returns the minutes spent."""
    n = 0
    while w.current_hour() < hour - 1e-9:
        w.advance_seconds(60.0, focus_xy=focus_xy)
        n += 1
    return n


def customer_sessions(w) -> Dict[int, List[int]]:
    """Open ``customer`` work sessions grouped by building (never by name)."""
    out: Dict[int, List[int]] = {}
    wk = w.work
    if wk is None:
        return out
    for cid, a in sorted(wk.activities.items()):
        if a.kind == "customer":
            out.setdefault(int(a.building_id), []).append(int(cid))
    return out


def seed_threat(session, w, seed_hour: float = SEED_HOUR,
                cutoff_hour: float = SEED_CUTOFF_HOUR) -> dict:
    """Seed the fast stressor inside the busiest shop, through the bridge.

    Advances the world to ``seed_hour`` and then one game minute at a time
    until some building has an open ``customer`` session. The busiest such
    building (ties by lowest id) is the shop; its lowest customer id is the
    index case of a ``classic_zombie_fast``. With no customer anywhere by
    ``cutoff_hour``, a ``classic_zombie`` with the data-driven index case is
    seeded instead and the row records the fallback.
    """
    run_to(w, seed_hour)
    info: dict = {"seed_hour_requested": seed_hour, "fallback": False}
    while w.current_hour() < cutoff_hour:
        by_b = customer_sessions(w)
        if by_b:
            bid = sorted(by_b.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
            cid = min(by_b[bid])
            r = session.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": PATHOGEN,
                                "citizen_id": int(cid)})
            if not r.get("ok"):
                raise RuntimeError(f"SEED_OUTBREAK failed: {r}")
            info.update({"pathogen": PATHOGEN, "building_id": int(bid), "citizen_id": int(cid),
                         "index_case": r.get("index_case"),
                         "seeded_at_hour": round(w.current_hour(), 4),
                         "n_customer_sessions_there": len(by_b[bid]),
                         "customer_sessions_by_building": {str(b): len(v)
                                                           for b, v in sorted(by_b.items())},
                         "note": ("the busiest shop is the building with the most open customer "
                                  "work sessions at the first game minute at or after "
                                  f"{seed_hour:.4f}h in which any customer session exists; ties "
                                  "by lowest building id, index case = lowest customer id there")})
            return info
        w.advance_seconds(60.0)
    r = session.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": FALLBACK_PATHOGEN})
    if not r.get("ok"):
        raise RuntimeError(f"SEED_OUTBREAK (fallback) failed: {r}")
    info.update({"pathogen": FALLBACK_PATHOGEN, "building_id": None, "citizen_id": None,
                 "index_case": r.get("index_case"), "fallback": True,
                 "seeded_at_hour": round(w.current_hour(), 4),
                 "note": (f"no customer work session existed anywhere between {seed_hour:.2f}h and "
                          f"{cutoff_hour:.2f}h, so the fallback was seeded: {FALLBACK_PATHOGEN} "
                          "with the data-driven index case")})
    return info


def threat_world(city: str, seed: int = 0, seed_hour: float = SEED_HOUR):
    """A world booted at 05:00 with the stressor seeded in the busiest shop."""
    session, w = start_world(city, DAY_FROM, seed=seed)
    info = seed_threat(session, w, seed_hour)
    return session, w, info


# --------------------------------------------------------------------------- #
# timed advance (instance wrappers, so the split is exact)
# --------------------------------------------------------------------------- #
def timed_block(w, minutes: int = BLOCK, focus_xy=None) -> dict:
    """Advance ``minutes`` game-minutes, splitting mobility/outbreak/work/cognition."""
    cost = {"mobility_s": 0.0, "outbreak_s": 0.0, "work_s": 0.0, "cognition_s": 0.0}
    mob, ob, wk, cg = w.mobility, w.outbreak, w.work, w.cognition
    mob_advance = mob.advance
    ob_advance = ob.advance if ob is not None else None
    wk_advance = wk.advance if wk is not None else None
    cg_advance = cg.advance if cg is not None else None

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
    if cg is not None:
        def cgw(dt, _f=cg_advance):
            t0 = time.perf_counter()
            _f(dt)
            cost["cognition_s"] += time.perf_counter() - t0
        cg.advance = cgw

    t0 = time.perf_counter()
    for _ in range(minutes):
        w.advance_seconds(60.0, focus_xy=focus_xy)
    total_s = time.perf_counter() - t0

    mob.advance = mob_advance
    if ob is not None:
        ob.advance = ob_advance
    if wk is not None:
        wk.advance = wk_advance
    if cg is not None:
        cg.advance = cg_advance
    other_s = total_s - sum(cost.values())
    return {"total_ms_per_game_minute": round(total_s * 1000.0 / minutes, 3),
            "mobility_ms_per_game_minute": round(cost["mobility_s"] * 1000.0 / minutes, 3),
            "outbreak_ms_per_game_minute": round(cost["outbreak_s"] * 1000.0 / minutes, 3),
            "work_ms_per_game_minute": round(cost["work_s"] * 1000.0 / minutes, 3),
            "cognition_ms_per_game_minute": round(cost["cognition_s"] * 1000.0 / minutes, 3),
            "other_ms_per_game_minute": round(other_s * 1000.0 / minutes, 3),
            "game_minutes": minutes}


def repeat_blocks(w, repeats: int = REPEATS, minutes: int = BLOCK, focus_xy=None) -> dict:
    rows = [timed_block(w, minutes, focus_xy) for _ in range(repeats)]
    keys = ("total_ms_per_game_minute", "mobility_ms_per_game_minute",
            "outbreak_ms_per_game_minute", "work_ms_per_game_minute",
            "cognition_ms_per_game_minute", "other_ms_per_game_minute")
    out = {k: round(statistics.median(r[k] for r in rows), 3) for k in keys}
    out.update({"repeats": repeats, "game_minutes_per_block": minutes, "blocks": rows,
                "hour_after": round(w.current_hour(), 3)})
    return out


def cognition_state(w) -> dict:
    """What the cognition runtime is holding right now (context for a row)."""
    c = w.cognition
    if c is None:
        return {}
    sizes = [len(s) for s in c.memories.values()]
    return {"n_citizens_with_memory": len(c.memories),
            "n_facts": sum(sizes), "max_facts_per_citizen": max(sizes) if sizes else 0,
            "n_relationships": len(c.rels.rels), "n_told": len(c.told),
            "n_alarmed": len(c._alarmed), "n_avoiding": len(c.avoid_goals),
            "hour": round(w.current_hour(), 3),
            "counts": dict(sorted(c.counts.items()))}


# --------------------------------------------------------------------------- #
# 1. perception scan cost
# --------------------------------------------------------------------------- #
def measure_perception(w, minutes: int = BLOCK, label: str = "") -> dict:
    """Time _perceive_work and _perceive_outbreak in place, with the rows drained.

    Both are called once per 1 s substep (60 per game minute) and both return
    immediately when the backend runtime has emitted nothing new; the drained
    row counts show how much of the cost is real work.
    """
    c = w.cognition
    acc = {"work_s": 0.0, "work_calls": 0, "work_rows": 0, "work_returns_early": 0,
           "ob_s": 0.0, "ob_calls": 0, "ob_rows": 0, "ob_returns_early": 0}
    pw, po = c._perceive_work, c._perceive_outbreak

    def wrap_work(_f=pw):
        pending = (w.work.event_seq - c._work_seq) if w.work is not None else 0
        t0 = time.perf_counter()
        _f()
        acc["work_s"] += time.perf_counter() - t0
        acc["work_calls"] += 1
        acc["work_rows"] += max(0, pending)
        acc["work_returns_early"] += 1 if pending <= 0 else 0

    def wrap_ob(ob, _f=po):
        pending = ob.event_seq - c._ob_seq
        t0 = time.perf_counter()
        _f(ob)
        acc["ob_s"] += time.perf_counter() - t0
        acc["ob_calls"] += 1
        acc["ob_rows"] += max(0, pending)
        acc["ob_returns_early"] += 1 if pending <= 0 else 0

    c._perceive_work = wrap_work
    c._perceive_outbreak = wrap_ob
    block = timed_block(w, minutes)
    c._perceive_work = pw
    c._perceive_outbreak = po

    def per(prefix: str, key: str) -> dict:
        s, n, rows = acc[key + "_s"], acc[key + "_calls"], acc[key + "_rows"]
        return {"calls": n, "calls_per_game_minute": round(n / minutes, 1),
                "ms_per_game_minute": round(s * 1000.0 / minutes, 4),
                "us_per_call": round(s * 1e6 / max(1, n), 3),
                "rows_drained": rows, "rows_per_game_minute": round(rows / minutes, 2),
                "us_per_row": round(s * 1e6 / rows, 2) if rows else None,
                "calls_with_nothing_to_drain": acc[key + "_returns_early"],
                "name": prefix}

    work = per("CognitionRuntime._perceive_work", "work")
    ob = per("CognitionRuntime._perceive_outbreak", "ob")
    total_ms = work["ms_per_game_minute"] + ob["ms_per_game_minute"]
    return {"label": label, "hour": round(w.current_hour(), 3), "game_minutes": minutes,
            "perceive_work": work, "perceive_outbreak": ob,
            "perception_ms_per_game_minute": round(total_ms, 4),
            "share_of_cognition_advance": round(
                total_ms / max(1e-9, block["cognition_ms_per_game_minute"]), 3),
            "block": block, "cognition_state": cognition_state(w)}


# --------------------------------------------------------------------------- #
# 2/3. memory microbenchmarks
# --------------------------------------------------------------------------- #
def _store(n_facts: int, owner: int = 1, now_s: float = 0.0) -> M.MemoryStore:
    """A store with ``n_facts`` distinct facts (a realistic mix of kinds)."""
    st = M.MemoryStore(owner, capacity=max(M.CAPACITY, n_facts))
    # threat kinds early, so even the 5-fact store derives real danger beliefs,
    # and a PLACE_SAFE among them so the contradiction path is exercised
    kinds = [M.THREAT_PERSON, M.WORKED_BESIDE, M.ATTACK_SEEN, M.MET, M.CORPSE_SEEN,
             M.PLACE_SAFE, M.SERVED, M.HELPED_BY, M.SAW_HELP, M.DEATH_SEEN]
    for i in range(n_facts):
        st.remember(kinds[i % len(kinds)], now_s + i, actor=1000 + i, building_id=100 + (i % 7),
                    room_id=i % 5)
    return st


def measure_memory_write(n_ops: int = MICRO_OPS) -> dict:
    """MemoryStore.remember: a brand new key every call vs reinforcing one key."""
    out = {"n_ops": n_ops,
           "note": ("both benchmarks run on a store seeded with 60 facts; the new-key case "
                    "grows the store without consolidating (the runtime consolidates every "
                    "10 game minutes), the reinforcement case hits the _by_key index")}

    grown = _store(60)
    t0 = time.perf_counter()
    for i in range(n_ops):
        grown.remember(M.MET, 1000.0, actor=100000 + i, building_id=i % 900, room_id=i % 11)
    ms = (time.perf_counter() - t0) * 1000.0
    out["remember_new_key"] = {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                               "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                               "store_size_after": len(grown)}

    st = _store(60)
    t0 = time.perf_counter()
    for i in range(n_ops):
        st.remember(M.WORKED_BESIDE, 1000.0 + i, actor=1000, building_id=100, room_id=0)
    ms = (time.perf_counter() - t0) * 1000.0
    out["remember_reinforce"] = {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                                 "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                                 "store_size_after": len(st)}

    # consolidate() on a store at capacity, and on the grown one (the O(n log n) path)
    reps = []
    for _ in range(REPEATS):
        s2 = _store(M.CAPACITY)
        t0 = time.perf_counter()
        s2.consolidate(3600.0 * 6)
        reps.append((time.perf_counter() - t0) * 1000.0)
    out["consolidate_64_facts"] = {"median_ms": round(statistics.median(reps), 4),
                                   "remaining": len(s2), "repeats": REPEATS}
    t0 = time.perf_counter()
    dropped = grown.consolidate(3600.0 * 6)
    out["consolidate_grown_store"] = {
        "facts_before": len(grown) + len(dropped), "dropped": len(dropped),
        "remaining": len(grown), "total_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "note": "one consolidate over the store grown by the new-key benchmark; O(n log n) in facts"}
    return out


def measure_memory_read(n_ops: int = MICRO_OPS) -> dict:
    """find / about / salient over a store at CAPACITY (64 facts)."""
    st = _store(M.CAPACITY)
    out = {"n_ops": n_ops, "n_facts": len(st),
           "note": "every one of the three is a full linear scan of the store (find/about) or a "
                   "full sort of it (salient); none uses an index"}

    def bench(name: str, fn: Callable[[int], None]) -> None:
        t0 = time.perf_counter()
        for i in range(n_ops):
            fn(i)
        ms = (time.perf_counter() - t0) * 1000.0
        out[name] = {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                     "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0))}

    bench("find_by_kind", lambda i: st.find(M.MET))
    bench("find_by_actor", lambda i: st.find(actor=1000 + (i % M.CAPACITY)))
    bench("about", lambda i: st.about(1000 + (i % M.CAPACITY)))
    bench("salient_8", lambda i: st.salient(10_000.0, 8))
    return out


def measure_beliefs(sizes=(5, 20, M.CAPACITY), n_ops: int = DERIVE_OPS) -> dict:
    """beliefs.derive over stores of increasing size (uncached, as on a store change)."""
    out = {"n_ops": n_ops,
           "note": ("derive() is called by CognitionRuntime.beliefs() whenever the citizen's "
                    "store changed or the cached derivation is a game minute old")}
    rows = []
    for n in sizes:
        st = _store(n)
        ops = max(1000, n_ops // max(1, n // 8 or 1))
        t0 = time.perf_counter()
        for _ in range(ops):
            b = derive(st, 10_000.0)
        ms = (time.perf_counter() - t0) * 1000.0
        rows.append({"n_facts": n, "n_ops": ops, "n_beliefs": len(b),
                     "us_per_derive": round(1000.0 * ms / ops, 3),
                     "us_per_fact": round(1000.0 * ms / ops / max(1, n), 4),
                     "derives_per_s": int(ops / max(1e-9, ms / 1000.0))})
    out["by_store_size"] = rows
    return out


def measure_relationships(w, n_ops: int = MICRO_OPS) -> dict:
    """RelationshipGraph.apply and CognitionRuntime.help_score."""
    g = RelationshipGraph()
    t0 = time.perf_counter()
    for i in range(n_ops):
        g.apply(i % 300, (i * 7) % 300 + 1000, "met", float(i))
    ms = (time.perf_counter() - t0) * 1000.0
    out = {"n_ops": n_ops,
           "apply": {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                     "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                     "n_pairs_after": len(g.rels),
                     "note": "rule 'met' (one dimension); a multi-dimension rule such as "
                             "'helped_by' touches four"},
           "note": "help_score is the per-candidate cost inside _decide_help"}
    t0 = time.perf_counter()
    for i in range(n_ops):
        g.apply(i % 300, (i * 7) % 300 + 1000, "helped_by", float(i))
    ms = (time.perf_counter() - t0) * 1000.0
    out["apply_helped_by"] = {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                              "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                              "dimensions": 4}
    c = w.cognition
    pairs = sorted(c.rels.rels)[:1] or [(0, 1)]
    a, b = pairs[0]
    problem = {"kind": "unstaffed_queue", "citizen_id": b}
    t0 = time.perf_counter()
    for i in range(n_ops):
        c.help_score(a, b, problem)
    ms = (time.perf_counter() - t0) * 1000.0
    out["help_score"] = {"total_ms": round(ms, 2), "us_per_op": round(1000.0 * ms / n_ops, 4),
                         "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                         "helper": a, "beneficiary": b,
                         "score": c.help_score(a, b, problem)[0],
                         "threshold": 0.40}
    return out


# --------------------------------------------------------------------------- #
# 4/5. decisions and social interaction processing (timed in place)
# --------------------------------------------------------------------------- #
def measure_decisions_social(w, minutes: int = BLOCK, label: str = "") -> dict:
    """_decide_help / _decide_avoid / _observe_safety per call, _copresence per
    call (with the pairs it meets) and _alarmed_encounters per second."""
    c = w.cognition
    acc: Dict[str, List[float]] = {k: [] for k in
                                   ("help", "avoid", "safety", "copresence", "alarmed")}
    pairs = {"n": 0}
    alarmed_seen: List[int] = []
    orig = {"help": c._decide_help, "avoid": c._decide_avoid, "safety": c._observe_safety,
            "copresence": c._copresence, "alarmed": c._alarmed_encounters, "meet": c._meet}

    def timer(key: str, fn):
        def wrapped(*a, **kw):
            t0 = time.perf_counter()
            r = fn(*a, **kw)
            acc[key].append((time.perf_counter() - t0) * 1000.0)
            return r
        return wrapped

    def meet_counter(a, b, bid, rid, _f=orig["meet"]):
        pairs["n"] += 1
        return _f(a, b, bid, rid)

    def alarmed_wrapped(_f=orig["alarmed"]):
        alarmed_seen.append(len(c._alarmed))
        t0 = time.perf_counter()
        r = _f()
        acc["alarmed"].append((time.perf_counter() - t0) * 1000.0)
        return r

    c._decide_help = timer("help", orig["help"])
    c._decide_avoid = timer("avoid", orig["avoid"])
    c._observe_safety = timer("safety", orig["safety"])
    c._copresence = timer("copresence", orig["copresence"])
    c._alarmed_encounters = alarmed_wrapped
    c._meet = meet_counter
    block = timed_block(w, minutes)
    for k, v in orig.items():
        setattr(c, "_decide_help" if k == "help" else
                "_decide_avoid" if k == "avoid" else
                "_observe_safety" if k == "safety" else
                "_copresence" if k == "copresence" else
                "_alarmed_encounters" if k == "alarmed" else "_meet", v)

    def row(key: str, per: str) -> dict:
        v = acc[key]
        return {"n_calls": len(v), "calls_per_game_minute": round(len(v) / minutes, 2),
                "ms_per_game_minute": round(sum(v) / minutes, 4),
                "mean_ms_per_call": round(statistics.mean(v), 5) if v else 0.0,
                "median_ms_per_call": round(statistics.median(v), 5) if v else 0.0,
                "max_ms_per_call": round(max(v), 5) if v else 0.0,
                "cadence": per}

    dec_ms = sum(sum(acc[k]) for k in ("help", "avoid", "safety")) / minutes
    soc_ms = sum(sum(acc[k]) for k in ("copresence", "alarmed")) / minutes
    return {"label": label, "hour": round(w.current_hour(), 3), "game_minutes": minutes,
            "decide_help": row("help", "once per game minute"),
            "decide_avoid": row("avoid", "once per game minute"),
            "observe_safety": row("safety", "once per game minute"),
            "decision_ms_per_game_minute": round(dec_ms, 4),
            "copresence": {**row("copresence", "once per 300 s of game time"),
                           "n_pairs_met": pairs["n"],
                           "pairs_per_call": round(pairs["n"] / max(1, len(acc["copresence"])), 1)},
            "alarmed_encounters": {**row("alarmed", "every 1 s substep while alarmed citizens exist"),
                                   "max_alarmed_citizens": max(alarmed_seen) if alarmed_seen else 0,
                                   "mean_alarmed_citizens": round(statistics.mean(alarmed_seen), 2)
                                   if alarmed_seen else 0.0,
                                   "ms_per_second_of_game_time": round(
                                       sum(acc["alarmed"]) / (minutes * 60.0), 5)},
            "social_ms_per_game_minute": round(soc_ms, 4),
            "block": block, "cognition_state": cognition_state(w)}


# --------------------------------------------------------------------------- #
# 6. rumor propagation + the combined window, minute by minute
# --------------------------------------------------------------------------- #
def measure_window(session, w, to_hour: float, label: str) -> dict:
    """Advance minute by minute to ``to_hour``, timing each game minute and
    draining GET_COGNITION for the rumor trace."""
    rows: List[dict] = []
    events: List[dict] = []
    since = 0
    while w.current_hour() < to_hour - 1e-9:
        hour = w.current_hour()
        r = timed_block(w, 1)
        snap = session.handle({"cmd": Command.GET_COGNITION, "since_seq": since})["cognition"]
        new = snap["events"]
        if new:
            since = new[-1]["seq"]
            events.extend(new)
        rows.append({"hour": round(hour, 4),
                     "total_ms": r["total_ms_per_game_minute"],
                     "mobility_ms": r["mobility_ms_per_game_minute"],
                     "outbreak_ms": r["outbreak_ms_per_game_minute"],
                     "work_ms": r["work_ms_per_game_minute"],
                     "cognition_ms": r["cognition_ms_per_game_minute"],
                     "warning_shared": sum(1 for e in new if e["event"] == "WARNING_SHARED"),
                     "warning_received": sum(1 for e in new if e["event"] == "WARNING_RECEIVED"),
                     "perceived": sum(1 for e in new if e["event"] == "PERCEIVED"),
                     "memory_created": sum(1 for e in new if e["event"] == "MEMORY_CREATED"),
                     "n_events": len(new)})
    worst = max(rows, key=lambda r: r["total_ms"]) if rows else {}
    worst_cog = max(rows, key=lambda r: r["cognition_ms"]) if rows else {}
    out = {"label": label, "hour_from": rows[0]["hour"] if rows else None,
           "hour_to": round(w.current_hour(), 4), "game_minutes": len(rows),
           "mean_total_ms_per_game_minute": round(statistics.mean(r["total_ms"] for r in rows), 3),
           "median_total_ms_per_game_minute": round(statistics.median(r["total_ms"] for r in rows), 3),
           "mean_cognition_ms_per_game_minute": round(
               statistics.mean(r["cognition_ms"] for r in rows), 3),
           "mean_mobility_ms_per_game_minute": round(
               statistics.mean(r["mobility_ms"] for r in rows), 3),
           "mean_outbreak_ms_per_game_minute": round(
               statistics.mean(r["outbreak_ms"] for r in rows), 3),
           "mean_work_ms_per_game_minute": round(statistics.mean(r["work_ms"] for r in rows), 3),
           "worst_minute": worst, "worst_cognition_minute": worst_cog,
           "n_minutes_over_budget": sum(1 for r in rows if r["total_ms"] > BUDGET_MS),
           "per_minute": rows, "cognition_state": cognition_state(w)}
    out["rumor"] = rumor_stats(w, events, rows)
    return out


def rumor_stats(w, events: List[dict], rows: List[dict]) -> dict:
    """WARNING_SHARED per game minute and the boundedness proof."""
    shared = [e for e in events if e["event"] == "WARNING_SHARED"]
    per_sender: Dict[int, int] = {}
    per_pair: Dict[Tuple[int, int], int] = {}
    per_origin: Dict[str, int] = {}
    hops: List[int] = []
    for e in shared:
        s = int(e["citizen_id"])
        r = int(e["recipient"])
        per_sender[s] = per_sender.get(s, 0) + 1
        per_pair[(s, r)] = per_pair.get((s, r), 0) + 1
        per_origin[str(e.get("origin_id"))] = per_origin.get(str(e.get("origin_id")), 0) + 1
        hops.append(int(e.get("hops", 0)))
    c = w.cognition
    minutes = max(1, len(rows))
    return {
        "n_warning_shared": len(shared),
        "n_warning_received": sum(1 for e in events if e["event"] == "WARNING_RECEIVED"),
        "per_game_minute": round(len(shared) / minutes, 3),
        "max_in_one_game_minute": max((r["warning_shared"] for r in rows), default=0),
        "n_senders": len(per_sender),
        "max_tellings_per_sender": max(per_sender.values()) if per_sender else 0,
        "max_tellings_per_pair": max(per_pair.values()) if per_pair else 0,
        "max_hops": max(hops) if hops else 0,
        "hop_histogram": {str(h): hops.count(h) for h in sorted(set(hops))},
        "n_origin_facts_in_circulation": len(per_origin),
        "max_tellings_per_origin_fact": max(per_origin.values()) if per_origin else 0,
        "told_set_size": len(c.told),
        "n_calls_tracked": len(c.calls),
        "max_calls_per_fact": max(c.calls.values()) if c.calls else 0,
        "bounds": {"MAX_HOPS": 2, "PAIR_COOLDOWN_S": 1800.0, "MAX_CALLS_PER_FACT": 3,
                   "note": ("boundedness: one telling of one origin fact per (sender, recipient) "
                            "pair ever (the told-set), one telling per pair per 30 min "
                            "(pair_last_s), at most 2 hops, at most 3 calls per origin fact; "
                            "max_tellings_per_pair above is the same origin fact never told "
                            "twice — a pair may exchange different facts")},
    }


# --------------------------------------------------------------------------- #
# 7. focus FAR vs NEAR
# --------------------------------------------------------------------------- #
def measure_focus(city: str, hour: float = 9.0, seed: int = 0) -> dict:
    _s, w = start_world(city, hour, seed=seed)
    warm(w)
    far = repeat_blocks(w, focus_xy=FAR_XY)
    bands_far: Dict[str, int] = {}
    for b in w.mobility.bands.values():
        bands_far[b.name.lower()] = bands_far.get(b.name.lower(), 0) + 1
    near_xy = w.mobility.entrances.get(NEAR_BUILDING)
    near = repeat_blocks(w, focus_xy=near_xy)
    bands_near: Dict[str, int] = {}
    for b in w.mobility.bands.values():
        bands_near[b.name.lower()] = bands_near.get(b.name.lower(), 0) + 1
    delta = round(near["cognition_ms_per_game_minute"] - far["cognition_ms_per_game_minute"], 3)
    return {
        "hour": hour,
        "far": {**far, "focus_xy": list(FAR_XY), "bands": bands_far},
        "near": {**near, "near_building_id": NEAR_BUILDING,
                 "focus_xy": None if near_xy is None else [round(near_xy[0], 2), round(near_xy[1], 2)],
                 "bands": bands_near},
        "cognition_ms_delta": delta,
        "note": ("the cognition runtime never reads focus_xy or the LOD band (no reference to "
                 "either anywhere in asphodel/cognition), so a NEAR building runs exactly the "
                 f"same Python as a FAR one; the measured delta of {delta} ms/game-minute is "
                 f"machine noise plus the mobility band change (far {bands_far}, near "
                 f"{bands_near}). cognition.advance is timed by its own instance wrapper inside "
                 "World.advance_seconds, so the split is exact rather than profiled."),
    }


# --------------------------------------------------------------------------- #
# 8. the whole day
# --------------------------------------------------------------------------- #
def measure_day(city: str, cognition: bool, seed: int = 0,
                from_hour: float = DAY_FROM, to_hour: float = DAY_TO) -> dict:
    """05:00 -> 20:00 one timed game minute at a time, split per runtime."""
    _s, w = start_world(city, from_hour, cognition=cognition, seed=seed)
    rows: List[dict] = []
    growth: List[dict] = []
    next_sample = from_hour
    t0 = time.perf_counter()
    while w.current_hour() < to_hour - 1e-9:
        hour = w.current_hour()
        r = timed_block(w, 1)
        rows.append({"hour": round(hour, 4), "total_ms": r["total_ms_per_game_minute"],
                     "mobility_ms": r["mobility_ms_per_game_minute"],
                     "outbreak_ms": r["outbreak_ms_per_game_minute"],
                     "work_ms": r["work_ms_per_game_minute"],
                     "cognition_ms": r["cognition_ms_per_game_minute"],
                     "other_ms": r["other_ms_per_game_minute"]})
        if cognition and w.current_hour() >= next_sample:
            next_sample += 1.0
            growth.append(memory_growth_row(w))
    wall_s = time.perf_counter() - t0
    n = len(rows)
    out = {"cognition": cognition, "hour_from": from_hour, "hour_to": to_hour, "game_minutes": n,
           "wall_s": round(wall_s, 1),
           "mean_total_ms_per_game_minute": round(statistics.mean(r["total_ms"] for r in rows), 3),
           "median_total_ms_per_game_minute": round(statistics.median(r["total_ms"] for r in rows), 3),
           "mean_mobility_ms_per_game_minute": round(statistics.mean(r["mobility_ms"] for r in rows), 3),
           "mean_outbreak_ms_per_game_minute": round(statistics.mean(r["outbreak_ms"] for r in rows), 3),
           "mean_work_ms_per_game_minute": round(statistics.mean(r["work_ms"] for r in rows), 3),
           "mean_cognition_ms_per_game_minute": round(statistics.mean(r["cognition_ms"] for r in rows), 3),
           "mean_other_ms_per_game_minute": round(statistics.mean(r["other_ms"] for r in rows), 3),
           "worst_minute": max(rows, key=lambda r: r["total_ms"]),
           "n_minutes_over_budget": sum(1 for r in rows if r["total_ms"] > BUDGET_MS),
           "per_minute": rows}
    if cognition:
        out["memory_growth"] = growth
        out["final"] = memory_growth_row(w)
        out["cognition_state"] = cognition_state(w)
    return out


def memory_growth_row(w) -> dict:
    c = w.cognition
    sizes = sorted(((len(s), cid) for cid, s in c.memories.items()), reverse=True)
    n_facts = sum(n for n, _ in sizes)
    return {"hour": round(w.current_hour(), 3), "n_citizens_with_memory": len(sizes),
            "n_facts": n_facts, "max_facts_per_citizen": sizes[0][0] if sizes else 0,
            "max_facts_citizen_id": sizes[0][1] if sizes else None,
            "mean_facts_per_citizen": round(n_facts / max(1, len(sizes)), 2),
            "capacity": M.CAPACITY, "within_capacity": bool(not sizes or sizes[0][0] <= M.CAPACITY),
            "n_relationships": len(c.rels.rels), "n_told": len(c.told),
            "n_help_pairs": len(c.help_pairs), "n_avoid_goals": len(c.avoid_goals),
            "n_facts_forgotten": sum(s.forgotten for s in c.memories.values())}


# --------------------------------------------------------------------------- #
# 9. profile of cognition.advance alone
# --------------------------------------------------------------------------- #
def _fname(fn: str) -> str:
    """``.../asphodel/cognition/runtime.py`` -> ``cognition/runtime.py`` (the
    mobility, work and cognition runtimes share the basename)."""
    parts = os.path.normpath(fn).split(os.sep)
    return "/".join(parts[-2:]) if len(parts) >= 2 else fn


SCALING: Dict[Tuple[str, str], str] = {
    ("cognition/runtime.py", "_substep"): (
        "per 1 s substep (60 per game minute): two backend drains, the alarmed scan when any "
        "citizen is alarmed, and the scheduled co-presence / decision / consolidation passes "
        "(cognition/runtime.py:177-195)"),
    ("cognition/runtime.py", "advance"): "per game minute: 60 substeps",
    ("cognition/runtime.py", "_perceive_work"): (
        "per substep; O(1) when the WorkRuntime emitted nothing, else O(new rows) — but the "
        "row scan is `[e for e in w.events if e['seq'] > self._work_seq]` over the whole 5000-row "
        "ring (cognition/runtime.py:289)"),
    ("cognition/runtime.py", "_perceive_outbreak"): (
        "per substep; same whole-ring scan plus an unconditional slice of the last 200 outbreak "
        "rows for ATTACK lookups (cognition/runtime.py:360-362)"),
    ("cognition/runtime.py", "_copresence"): (
        "per 300 s of game time: O(citizens) grouping, then per room O(occupants x PAIR_CAP) "
        "meetings and an outdoor grid hash over canonical positions"),
    ("cognition/runtime.py", "_meet"): "per co-present pair per scan: two remembers, two relates, "
                                       "two share attempts",
    ("cognition/runtime.py", "_alarmed_encounters"): (
        "per 1 s substep while any citizen is alarmed: O(alarmed x outdoor citizens) distance "
        "checks — the outdoor list is rebuilt every substep (cognition/runtime.py:676-690)"),
    ("cognition/runtime.py", "_decide_help"): (
        "per game minute: O(open work sessions) + per building with >= 2 workers, "
        "O(problems x eligible helpers) help_score evaluations"),
    ("cognition/runtime.py", "_decide_avoid"): (
        "per game minute: O(citizens with memory) x O(facts) to find the threat holders, then a "
        "belief derivation per holder (cognition/runtime.py:792-798)"),
    ("cognition/runtime.py", "_observe_safety"): (
        "per game minute: O(citizens with memory) x O(facts), and for each holder indoors a scan "
        "of every outbreak record for a threat in the room (cognition/runtime.py:866-895)"),
    ("cognition/runtime.py", "_refresh_alarmed"): (
        "per game minute: O(citizens with memory) x O(facts per store)"),
    ("cognition/runtime.py", "_consolidate"): (
        "per 600 s of game time: O(citizens with memory) x O(facts log facts)"),
    ("cognition/runtime.py", "_share"): (
        "per telling attempt: O(recipient facts) duplicate scan"),
    ("cognition/runtime.py", "_shareable"): "per share attempt: O(sender facts) + a sort",
    ("cognition/runtime.py", "_room_mates"): (
        "indoors O(room occupants); outdoors O(all citizens) — a linear scan over every executor "
        "per call (cognition/runtime.py:216-232)"),
    ("cognition/memory.py", "remember"): "per fact write: dict lookup on the merge key",
    ("cognition/memory.py", "consolidate"): "per store: O(facts log facts)",
    ("cognition/memory.py", "effective"): "per fact per belief derivation / salience sort",
    ("cognition/beliefs.py", "derive"): "per citizen per changed store: O(facts) x O(safe facts)",
    ("cognition/relationships.py", "apply"): "per relationship update: O(dims of the rule)",
}


def measure_profile(session, w, minutes: int = 20) -> Tuple[dict, dict]:
    """cProfile cognition.advance alone across a live window."""
    c = w.cognition
    pr = cProfile.Profile()
    orig = c.advance

    def wrapped(dt, _f=orig):
        return pr.runcall(_f, dt)

    c.advance = wrapped
    t0 = time.perf_counter()
    for _ in range(minutes):
        w.advance_seconds(60.0)
    wall_s = time.perf_counter() - t0
    c.advance = orig
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
    doc = {"hour_after": round(w.current_hour(), 3), "game_minutes": minutes,
           "profiled_cognition_s": round(total_s, 3),
           "cognition_ms_per_game_minute_under_profiler": round(total_s * 1000.0 / minutes, 1),
           "whole_advance_ms_per_game_minute_under_profiler": round(wall_s * 1000.0 / minutes, 1),
           "by_cumtime": by_cum[:15], "by_tottime": by_tot[:15],
           "cognition_state": cognition_state(w),
           "note": ("only CognitionRuntime.advance is profiled (cProfile.runcall around the "
                    "instance method), so the shares below are shares of cognition, not of the "
                    "whole world step. cProfile inflates absolute cost; read the shares.")}
    return doc, lookup


def hotspots(prof: dict, lookup: dict) -> List[dict]:
    out = []
    for row in prof["by_tottime"][:12]:
        key = (row["file"], row["name"])
        out.append({"function": f"{row['file']}:{row['name']}", "where": row["function"],
                    "tottime_pct": row["tottime_pct"], "cumtime_pct": row["cumtime_pct"],
                    "calls_per_game_minute": row["calls_per_game_minute"],
                    "scaling": SCALING.get(key, "not annotated (see the profile rows)")})
    for key in (("cognition/runtime.py", "_perceive_work"),
                ("cognition/runtime.py", "_perceive_outbreak"),
                ("cognition/runtime.py", "_copresence"),
                ("cognition/runtime.py", "_decide_help"),
                ("cognition/runtime.py", "_decide_avoid"),
                ("cognition/runtime.py", "_observe_safety"),
                ("cognition/runtime.py", "_alarmed_encounters")):
        row = lookup.get(key)
        if row is None or any(h["where"] == row["function"] for h in out):
            continue
        out.append({"function": f"{row['file']}:{row['name']}", "where": row["function"],
                    "tottime_pct": row["tottime_pct"], "cumtime_pct": row["cumtime_pct"],
                    "calls_per_game_minute": row["calls_per_game_minute"],
                    "scaling": SCALING.get(key, "")})
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--city", default="houston")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seed-hour", type=float, default=SEED_HOUR,
                    help="earliest hour at which the threat stressor may be seeded")
    ap.add_argument("--day-from", type=float, default=DAY_FROM)
    ap.add_argument("--day-to", type=float, default=DAY_TO)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)
    city, seed = args.city, args.seed

    wall0 = time.perf_counter()
    res: dict = {}

    # -- world shape --------------------------------------------------------
    t0 = time.perf_counter()
    _s0, w0 = start_world(city, 8.0, seed=seed)
    build_ms = (time.perf_counter() - t0) * 1000.0
    c0 = w0.cognition
    res["world"] = {
        "n_citizens": len(w0.mobility.execs), "n_vehicles": len(w0.mobility.vehicles),
        "start_world_ms": round(build_ms, 1),
        "cognition_enabled": w0.cognition is not None,
        "n_prior_relationships": len(c0.rels.rels),
        "n_employed": len(w0.work.employment) if w0.work else 0,
        "memory_capacity": M.CAPACITY,
        "note": ("START_WORLD enables cognition by default whenever mobility is on; the "
                 "relationships present at boot are the household / workplace priors"),
    }
    print(f"[{city}] START_WORLD in {build_ms / 1000:.1f} s, {len(w0.mobility.execs)} citizens, "
          f"{len(c0.rels.rels)} prior relationships")

    # -- 1. perception, 08:00 ----------------------------------------------
    warm(w0)
    res["perception"] = {}
    res["perception"]["0800"] = measure_perception(w0, BLOCK, "08:00 morning, no threat")
    p = res["perception"]["0800"]
    print(f"  perception 08:00: {p['perception_ms_per_game_minute']:.3f} ms/game-min "
          f"({p['perceive_work']['rows_per_game_minute']} work rows/min)")

    # -- 2/3. microbenchmarks ----------------------------------------------
    res["memory_write"] = measure_memory_write()
    res["memory_read"] = measure_memory_read()
    res["beliefs"] = measure_beliefs()
    res["relationships"] = measure_relationships(w0)
    print(f"  memory:       remember new {res['memory_write']['remember_new_key']['us_per_op']} "
          f"us/op, reinforce {res['memory_write']['remember_reinforce']['us_per_op']} us/op; "
          f"salient {res['memory_read']['salient_8']['us_per_op']} us/op")
    print(f"  beliefs:      " + ", ".join(
        f"{r['n_facts']} facts {r['us_per_derive']} us" for r in res["beliefs"]["by_store_size"]))
    print(f"  rels:         apply {res['relationships']['apply']['us_per_op']} us/op, "
          f"help_score {res['relationships']['help_score']['us_per_op']} us/op")

    # -- 4. decisions + social at 08:00 (no threat) -------------------------
    res["decisions_social"] = {}
    res["decisions_social"]["0800"] = measure_decisions_social(w0, BLOCK, "08:00, no threat")
    d = res["decisions_social"]["0800"]
    print(f"  decisions 08:00: {d['decision_ms_per_game_minute']:.3f} ms/game-min "
          f"(help {d['decide_help']['mean_ms_per_call']:.4f}, avoid "
          f"{d['decide_avoid']['mean_ms_per_call']:.4f}, safety "
          f"{d['observe_safety']['mean_ms_per_call']:.4f} ms/call)")

    # -- 5. the threat world: perception in the threat window ---------------
    s1, w1, info1 = threat_world(city, seed, args.seed_hour)
    res["threat_seed"] = info1
    print(f"  threat seeded: {info1.get('pathogen')} citizen {info1.get('citizen_id')} in "
          f"building {info1.get('building_id')} at {info1.get('seeded_at_hour')}h"
          + (" (FALLBACK)" if info1.get("fallback") else ""))
    run_to(w1, info1["seeded_at_hour"] + 8.0 / 60.0)     # let the case rise
    res["perception"]["threat"] = measure_perception(
        w1, BLOCK, f"threat window from {round(w1.current_hour(), 3)}h "
                   f"({info1.get('pathogen')} seeded at {info1.get('seeded_at_hour')}h)")
    p = res["perception"]["threat"]
    print(f"  perception threat ({p['hour']}h): {p['perception_ms_per_game_minute']:.3f} "
          f"ms/game-min ({p['perceive_outbreak']['rows_per_game_minute']} outbreak rows/min)")

    # -- 6. decisions + social at 11:00 in the threat world ------------------
    run_to(w1, 11.0)
    res["decisions_social"]["1100"] = measure_decisions_social(
        w1, BLOCK, "11:00, threat in the city")
    d = res["decisions_social"]["1100"]
    print(f"  decisions 11:00: {d['decision_ms_per_game_minute']:.3f} ms/game-min; social "
          f"{d['social_ms_per_game_minute']:.3f} ms/game-min "
          f"(copresence {d['copresence']['mean_ms_per_call']:.3f} ms/call, "
          f"{d['copresence']['pairs_per_call']} pairs/call; alarmed "
          f"{d['alarmed_encounters']['n_calls']} calls, max "
          f"{d['alarmed_encounters']['max_alarmed_citizens']} alarmed)")

    # -- 7. perception at 16:00 (no threat) ---------------------------------
    _s2, w2 = start_world(city, 16.0, seed=seed)
    warm(w2)
    res["perception"]["1600"] = measure_perception(w2, BLOCK, "16:00 afternoon, no threat")
    p = res["perception"]["1600"]
    print(f"  perception 16:00: {p['perception_ms_per_game_minute']:.3f} ms/game-min "
          f"({p['perceive_work']['rows_per_game_minute']} work rows/min)")

    # -- 8. the combined window (work + outbreak + cognition) + rumor -------
    s3, w3, info3 = threat_world(city, seed, args.seed_hour)
    res["threat_seed_window_run"] = info3
    window = measure_window(s3, w3, info3["seeded_at_hour"] + 1.0,
                            f"work + outbreak + cognition, {info3['seeded_at_hour']}h -> "
                            f"{round(info3['seeded_at_hour'] + 1.0, 3)}h "
                            f"({info3.get('pathogen')})")
    res["combined_window"] = window
    res["rumor"] = {**window["rumor"], "window": window["label"],
                    "hour_from": window["hour_from"], "hour_to": window["hour_to"],
                    "per_minute": [{"hour": r["hour"], "warning_shared": r["warning_shared"],
                                    "warning_received": r["warning_received"],
                                    "perceived": r["perceived"]} for r in window["per_minute"]]}
    print(f"  combined window {window['hour_from']}-{window['hour_to']}h: "
          f"{window['mean_total_ms_per_game_minute']:.1f} ms/game-min "
          f"(cognition {window['mean_cognition_ms_per_game_minute']:.1f}); "
          f"{window['rumor']['n_warning_shared']} warnings shared, max hops "
          f"{window['rumor']['max_hops']}, max per sender "
          f"{window['rumor']['max_tellings_per_sender']}")

    # -- 9. profile of cognition.advance ------------------------------------
    s4, w4, info4 = threat_world(city, seed, args.seed_hour)
    run_to(w4, info4["seeded_at_hour"] + 10.0 / 60.0)
    res["profile"], lookup = measure_profile(s4, w4, 20)
    res["hotspots"] = hotspots(res["profile"], lookup)
    print(f"  profile: cognition {res['profile']['cognition_ms_per_game_minute_under_profiler']} "
          f"ms/game-min under cProfile over 20 game-minutes")

    # -- 10. focus FAR vs NEAR ----------------------------------------------
    res["focus"] = measure_focus(city, 9.0, seed)
    f = res["focus"]
    print(f"  focus far:    cognition {f['far']['cognition_ms_per_game_minute']} ms/game-min; "
          f"near {f['near']['cognition_ms_per_game_minute']} (delta {f['cognition_ms_delta']})")

    # -- 11. the whole day, cognition on vs off ------------------------------
    day_on = measure_day(city, True, seed, args.day_from, args.day_to)
    print(f"  day {args.day_from:.0f}:00-{args.day_to:.0f}:00 cognition ON:  "
          f"{day_on['wall_s']:.0f} s wall, {day_on['mean_total_ms_per_game_minute']:.1f} "
          f"ms/game-min (cognition {day_on['mean_cognition_ms_per_game_minute']:.1f})")
    day_off = measure_day(city, False, seed, args.day_from, args.day_to)
    print(f"  day {args.day_from:.0f}:00-{args.day_to:.0f}:00 cognition OFF: "
          f"{day_off['wall_s']:.0f} s wall, {day_off['mean_total_ms_per_game_minute']:.1f} "
          f"ms/game-min")
    res["day"] = {
        "cognition_on": day_on, "cognition_off": day_off,
        "wall_s_delta": round(day_on["wall_s"] - day_off["wall_s"], 1),
        "wall_s_ratio": round(day_on["wall_s"] / max(1e-9, day_off["wall_s"]), 3),
        "ms_per_game_minute_delta": round(day_on["mean_total_ms_per_game_minute"]
                                          - day_off["mean_total_ms_per_game_minute"], 3),
        "cognition_share_of_day": round(day_on["mean_cognition_ms_per_game_minute"]
                                        / max(1e-9, day_on["mean_total_ms_per_game_minute"]), 3),
        "note": ("the same bundle, seed and hours, booted once with START_WORLD cognition:true "
                 "and once with cognition:false; each game minute is timed on its own and split "
                 "by instance wrappers on every runtime's advance"),
    }
    res["memory_growth"] = {
        "hourly": day_on["memory_growth"], "final": day_on["final"],
        "capacity": M.CAPACITY,
        "within_capacity_all_day": all(r["within_capacity"] for r in day_on["memory_growth"])
        and day_on["final"]["within_capacity"],
        "note": ("MemoryStore.consolidate runs every 600 s of game time and trims to "
                 f"capacity {M.CAPACITY}; the maximum any citizen holds is the bound "
                 "that must never be exceeded"),
    }
    g = day_on["final"]
    print(f"  memory:       {g['n_facts']} facts over {g['n_citizens_with_memory']} citizens, "
          f"max {g['max_facts_per_citizen']}/citizen (capacity {M.CAPACITY}), "
          f"{g['n_relationships']} relationships")

    # -- budget -------------------------------------------------------------
    cands = [(res["perception"]["0800"]["block"], "08:00 block"),
             (res["perception"]["threat"]["block"], "threat-window block"),
             (res["perception"]["1600"]["block"], "16:00 block"),
             (res["decisions_social"]["1100"]["block"], "11:00 threat block")]
    worst_block, worst_label = max(cands, key=lambda kv: kv[0]["total_ms_per_game_minute"])
    day_worst = day_on["worst_minute"]
    win_worst = window["worst_minute"]
    worst_single = max([day_worst, win_worst], key=lambda r: r["total_ms"])
    wm = max(worst_block["total_ms_per_game_minute"], window["mean_total_ms_per_game_minute"],
             day_on["mean_total_ms_per_game_minute"])
    res["budget"] = {
        "clock_multiplier": CLOCK_X,
        "real_seconds_per_game_minute": GAME_MINUTE_REAL_S,
        "budget_ms": BUDGET_MS,
        "worst_mean_total_ms_per_game_minute": round(wm, 3),
        "worst_block": {"label": worst_label, **worst_block},
        "worst_single_game_minute": worst_single,
        "budget_used_fraction_worst_mean": round(wm / BUDGET_MS, 4),
        "budget_used_fraction_worst_minute": round(worst_single["total_ms"] / BUDGET_MS, 4),
        "headroom_x": round(BUDGET_MS / wm, 1) if wm else None,
        "headroom_x_worst_single_minute": round(BUDGET_MS / worst_single["total_ms"], 2)
        if worst_single["total_ms"] else None,
        "cognition_ms_per_game_minute_day_mean": day_on["mean_cognition_ms_per_game_minute"],
        "cognition_share_worst_block": round(
            worst_block["cognition_ms_per_game_minute"]
            / max(1e-9, worst_block["total_ms_per_game_minute"]), 3),
        "n_minutes_over_budget_day": day_on["n_minutes_over_budget"],
        "n_minutes_over_budget_window": window["n_minutes_over_budget"],
        "note": (f"at {CLOCK_X:.0f}x one game minute is {GAME_MINUTE_REAL_S} s of real time "
                 f"({BUDGET_MS:.0f} ms). The heaviest measured mean game-minute ({round(wm, 1)} ms) "
                 f"uses {100.0 * wm / BUDGET_MS:.2f}% of it; the cognition runtime is "
                 f"{day_on['mean_cognition_ms_per_game_minute']} ms of the day mean "
                 f"({100.0 * day_on['mean_cognition_ms_per_game_minute'] / max(1e-9, day_on['mean_total_ms_per_game_minute']):.0f}% "
                 f"of the whole world step). The worst single measured game minute is "
                 f"{worst_single['total_ms']} ms at {worst_single['hour']}h."),
    }

    doc = {"version": 1, "milestone": "ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1",
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


def print_table(doc: dict) -> None:
    rows: List[Tuple[str, Optional[float], str]] = []
    for key in ("0800", "threat", "1600"):
        p = doc["perception"][key]
        rows.append((f"perception {key} (per game-min)", p["perception_ms_per_game_minute"],
                     f"work {p['perceive_work']['us_per_call']} us/call x "
                     f"{p['perceive_work']['calls_per_game_minute']:.0f}, outbreak "
                     f"{p['perceive_outbreak']['us_per_call']} us/call; drained "
                     f"{p['perceive_work']['rows_per_game_minute']} work + "
                     f"{p['perceive_outbreak']['rows_per_game_minute']} outbreak rows/min"))
    mw = doc["memory_write"]
    rows.append(("memory remember (new key)", mw["remember_new_key"]["us_per_op"] / 1000.0,
                 f"{mw['remember_new_key']['us_per_op']} us/op, "
                 f"{mw['remember_new_key']['ops_per_s']:,} ops/s, store "
                 f"{mw['remember_new_key']['store_size_after']:,} facts after"))
    rows.append(("memory remember (reinforce)", mw["remember_reinforce"]["us_per_op"] / 1000.0,
                 f"{mw['remember_reinforce']['us_per_op']} us/op, "
                 f"{mw['remember_reinforce']['ops_per_s']:,} ops/s"))
    rows.append(("memory consolidate (64 facts)", mw["consolidate_64_facts"]["median_ms"],
                 f"remaining {mw['consolidate_64_facts']['remaining']}; grown store "
                 f"{mw['consolidate_grown_store']['facts_before']:,} facts in "
                 f"{mw['consolidate_grown_store']['total_ms']} ms"))
    mr = doc["memory_read"]
    for k in ("find_by_kind", "find_by_actor", "about", "salient_8"):
        rows.append((f"memory {k} (64 facts)", mr[k]["us_per_op"] / 1000.0,
                     f"{mr[k]['us_per_op']} us/op, {mr[k]['ops_per_s']:,} ops/s"))
    for r in doc["beliefs"]["by_store_size"]:
        rows.append((f"beliefs.derive ({r['n_facts']} facts)", r["us_per_derive"] / 1000.0,
                     f"{r['us_per_derive']} us/derive, {r['us_per_fact']} us/fact, "
                     f"{r['n_beliefs']} beliefs"))
    rl = doc["relationships"]
    rows.append(("RelationshipGraph.apply ('met')", rl["apply"]["us_per_op"] / 1000.0,
                 f"{rl['apply']['us_per_op']} us/op, {rl['apply']['ops_per_s']:,} ops/s"))
    rows.append(("RelationshipGraph.apply ('helped_by')",
                 rl["apply_helped_by"]["us_per_op"] / 1000.0,
                 f"{rl['apply_helped_by']['us_per_op']} us/op, 4 dimensions"))
    rows.append(("CognitionRuntime.help_score", rl["help_score"]["us_per_op"] / 1000.0,
                 f"{rl['help_score']['us_per_op']} us/op, "
                 f"{rl['help_score']['ops_per_s']:,} ops/s"))
    for key in ("0800", "1100"):
        d = doc["decisions_social"][key]
        rows.append((f"decisions {key} (per game-min)", d["decision_ms_per_game_minute"],
                     f"help {d['decide_help']['mean_ms_per_call']} ms/call, avoid "
                     f"{d['decide_avoid']['mean_ms_per_call']}, safety "
                     f"{d['observe_safety']['mean_ms_per_call']}"))
        rows.append((f"social {key} (per game-min)", d["social_ms_per_game_minute"],
                     f"copresence {d['copresence']['mean_ms_per_call']} ms/call "
                     f"({d['copresence']['pairs_per_call']} pairs/call), alarmed "
                     f"{d['alarmed_encounters']['n_calls']} calls, "
                     f"{d['alarmed_encounters']['ms_per_second_of_game_time']} ms/game-second, "
                     f"max {d['alarmed_encounters']['max_alarmed_citizens']} alarmed"))
    ru = doc["rumor"]
    rows.append(("rumor WARNING_SHARED per game-min", None,
                 f"{ru['per_game_minute']} shared/min ({ru['n_warning_shared']} total, "
                 f"{ru['n_warning_received']} received), max {ru['max_in_one_game_minute']} in "
                 f"one minute; told-set {ru['told_set_size']}, max hops {ru['max_hops']}, "
                 f"max per sender {ru['max_tellings_per_sender']}, max per origin fact "
                 f"{ru['max_tellings_per_origin_fact']}"))
    f = doc["focus"]
    rows.append(("advance 09:00, focus FAR", f["far"]["total_ms_per_game_minute"],
                 f"cognition {f['far']['cognition_ms_per_game_minute']}, bands {f['far']['bands']}"))
    rows.append(("advance 09:00, focus NEAR", f["near"]["total_ms_per_game_minute"],
                 f"cognition {f['near']['cognition_ms_per_game_minute']} (delta "
                 f"{f['cognition_ms_delta']}), building {f['near']['near_building_id']}"))
    win = doc["combined_window"]
    rows.append(("work+outbreak+cognition window", win["mean_total_ms_per_game_minute"],
                 f"mobility {win['mean_mobility_ms_per_game_minute']}, outbreak "
                 f"{win['mean_outbreak_ms_per_game_minute']}, work "
                 f"{win['mean_work_ms_per_game_minute']}, cognition "
                 f"{win['mean_cognition_ms_per_game_minute']}; worst minute "
                 f"{win['worst_minute']['total_ms']} ms at {win['worst_minute']['hour']}h"))
    d_on = doc["day"]["cognition_on"]
    d_off = doc["day"]["cognition_off"]
    rows.append(("whole day, cognition ON", d_on["mean_total_ms_per_game_minute"],
                 f"{d_on['wall_s']} s wall for {d_on['game_minutes']} game-min; mobility "
                 f"{d_on['mean_mobility_ms_per_game_minute']}, work "
                 f"{d_on['mean_work_ms_per_game_minute']}, cognition "
                 f"{d_on['mean_cognition_ms_per_game_minute']}; worst minute "
                 f"{d_on['worst_minute']['total_ms']} ms"))
    rows.append(("whole day, cognition OFF", d_off["mean_total_ms_per_game_minute"],
                 f"{d_off['wall_s']} s wall; delta {doc['day']['ms_per_game_minute_delta']} "
                 f"ms/game-min, wall ratio {doc['day']['wall_s_ratio']}x"))
    g = doc["memory_growth"]["final"]
    rows.append(("memory at 20:00", None,
                 f"{g['n_facts']} facts over {g['n_citizens_with_memory']} citizens, max "
                 f"{g['max_facts_per_citizen']}/citizen (capacity "
                 f"{doc['memory_growth']['capacity']}, within capacity all day "
                 f"{doc['memory_growth']['within_capacity_all_day']}), "
                 f"{g['n_relationships']} relationships, {g['n_facts_forgotten']} forgotten"))

    print("")
    print(f"{'measurement':46s} {'ms':>10s}  detail")
    print("-" * 46 + " " + "-" * 10 + "  " + "-" * 60)
    for name, ms, detail in rows:
        val = "-" if ms is None else f"{ms:.4f}".rstrip("0").rstrip(".")
        print(f"{name:46s} {val:>10s}  {detail}")

    print("")
    print(f"  profile (cProfile of cognition.advance alone, "
          f"{doc['profile']['game_minutes']} game-minutes in the threat window) — top 8 by tottime:")
    for row in doc["profile"]["by_tottime"][:8]:
        print(f"    {row['tottime_pct']:5.2f}%  {row['function']:58s} {row['ncalls']:>10,} calls")
    print("")
    print("  hotspots:")
    for hs in doc["hotspots"]:
        print(f"    tot {hs['tottime_pct']:5.2f}%  cum {hs['cumtime_pct']:6.2f}%  "
              f"{hs['function']}  ({hs['calls_per_game_minute']:,.0f} calls/game-min)")
        print(f"            scaling: {hs['scaling']}")
    b = doc["budget"]
    print("")
    print(f"  budget: {b['note']}")
    print(f"          headroom {b['headroom_x']}x on the heaviest measured mean game-minute; "
          f"{b['headroom_x_worst_single_minute']}x on the worst single game minute")


if __name__ == "__main__":
    raise SystemExit(main())

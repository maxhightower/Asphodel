#!/usr/bin/env python3
"""Wall-clock performance of the NPC dialogue runtime on one city bundle.

Everything ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 adds on top of the
mobility / outbreak / work / cognition runtimes, in milliseconds (median of 3
repeats where a repeat is cheap):

    sessions      DialogueRuntime.advance / _substep per game minute at 08:00,
                  in the 10:45 threat window and at 16:00, with the number of
                  active conversation sessions it walks every second
    retrieval     grounding.retrieve over stores of 5, 20 and 64 facts, 1e5 ops
                  (subject / place / kind queries)
    grounding     grounding.ground, 1e5 ops on an accepted proposition and 1e5
                  on a rejected one (the validator's two exits)
    rendering     render.render over the proposition kinds and the bare acts,
                  1e5 ops
    transfer      CognitionRuntime.receive_fact over scratch stores, 1e4 ops
                  (threat fact, which also triggers the avoidance decision, and
                  a non-threat fact), plus the same call timed in place inside
                  the threat window (milliseconds per FACT_RECEIVED)
    help          CognitionRuntime._decide_help (which now asks through a
                  conversation) per game minute, and DialogueRuntime.request_help
                  per call, with the accept / refuse split
    player        the bridge TALK round trip for GREET / ASK_FACT / ASK_SAFETY /
                  ASK_PERSON / END_CONVERSATION against a co-present NPC,
                  median milliseconds per TALK
    day           the whole Houston day 05:00 -> 20:00 with dialogue on vs the
                  same day booted with START_WORLD ``dialogue: false``, split
                  mobility / outbreak / work / cognition / dialogue per game
                  minute by instance wrappers on every runtime's advance
    threat        the threat window seeded in the busiest shop at ~10:35
    combined      work + outbreak + cognition + dialogue, 10:35 -> 11:35, one
                  timed game minute at a time with GET_DIALOGUE drained
    chatter       the bounds that keep a city from turning into a chat room:
                  SPEECH_ACT per game minute (max and mean), distinct speakers
                  per minute, conversations per citizen per day, identical
                  (speaker, listener, act, line) repeats inside 10 minutes
                  (must be ~0), and the ring sizes (events 5000, conversations
                  kept <= 400, rendered <= 200)
    profile       a cProfile top-15 of DialogueRuntime.advance plus the player
                  TALK path

and states the implied real-time budget: at the default 24x clock one game
minute takes 2.5 s of real time.

The threat stressor is seeded the way the certification seeds it: the world is
booted at 05:00 and advanced to the first game minute at or after
``--seed-hour`` in which any customer work session exists; the busiest shop
(the building with the most ``customer`` sessions, ties by lowest building id)
is chosen and its lowest customer id is the index case of a
``classic_zombie_fast`` outbreak seeded through the bridge. If no customer
session exists by the cutoff, a ``classic_zombie`` with the data-driven index
case is seeded instead and the artifact says so.

    PYTHONPATH=. python3 tools/dialogue_perf.py [--city houston]

Writes artifacts/npc_dialogue_v1/performance.json.
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
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.cognition import memory as M                            # noqa: E402
from asphodel.dialogue import acts as A                               # noqa: E402
from asphodel.dialogue import grounding as G                          # noqa: E402
from asphodel.dialogue.render import render                           # noqa: E402
from asphodel.dialogue import runtime as DR                           # noqa: E402
from asphodel.dialogue import session as DS                           # noqa: E402

ARTIFACT = os.path.join(REPO, "artifacts", "npc_dialogue_v1", "performance.json")
REPEATS = 3
BLOCK = 10                            # game-minutes per timed block
WARM = 3                              # game-minutes of warm-up before a block
CLOCK_X = 24.0                        # default game clock: 24x real time
GAME_MINUTE_REAL_S = 60.0 / CLOCK_X   # => 2.5 s of real time per game minute
BUDGET_MS = GAME_MINUTE_REAL_S * 1000.0
DAY_FROM = 5.0
DAY_TO = 20.0
SEED_HOUR = 10.5833                   # 10:35 — the earliest the stressor is seeded
SEED_CUTOFF_HOUR = 12.0               # give up looking for a customer session here
THREAT_BLOCK_HOUR = 10.75             # 10:45 — the threat window block
PATHOGEN = "classic_zombie_fast"
FALLBACK_PATHOGEN = "classic_zombie"
MICRO_OPS = 100_000
TRANSFER_OPS = 10_000
REPEAT_WINDOW_S = 600.0               # "identical line again" window: 10 game minutes
PLAYER_CITIZEN = 0                    # any registered citizen: TALK needs a player at START_WORLD


# --------------------------------------------------------------------------- #
# world construction (exactly how the game boots one: bridge START_WORLD)
# --------------------------------------------------------------------------- #
def start_world(city: str, start_hour: float, dialogue: bool = True, cognition: bool = True,
                work: bool = True, seed: int = 0, player_citizen: Optional[int] = PLAYER_CITIZEN):
    """A world from the bundle through the bridge, as START_WORLD builds it.

    Returns ``(session, world)``: the session is kept so the stressor can be
    seeded and TALK / GET_DIALOGUE issued through the same commands the game
    uses. ``player_citizen`` is required by TALK; START_WORLD refuses an id
    that is not in the bundle population, so it is dropped on refusal.
    """
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
           "start_hour": float(start_hour), "work": bool(work), "cognition": bool(cognition),
           "dialogue": bool(dialogue)}
    if player_citizen is not None:
        msg["player_citizen"] = int(player_citizen)
    r = s.handle(msg)
    if not r.get("ok") and player_citizen is not None:
        msg.pop("player_citizen")
        r = s.handle(msg)
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    if bool(r.get("dialogue_enabled")) != bool(dialogue):
        raise RuntimeError(f"START_WORLD dialogue_enabled={r.get('dialogue_enabled')} "
                           f"but dialogue={dialogue} was asked for")
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
KEYS = ("mobility", "outbreak", "work", "cognition", "dialogue")


def timed_block(w, minutes: int = BLOCK, focus_xy=None) -> dict:
    """Advance ``minutes`` game-minutes, splitting the cost per runtime."""
    cost = {k + "_s": 0.0 for k in KEYS}
    runtimes = {k: getattr(w, k, None) for k in KEYS}
    orig = {k: (None if r is None else r.advance) for k, r in runtimes.items()}

    def wrap(key: str, fn, mobility: bool = False):
        if mobility:
            def mobw(dt, hour, _f=fn):
                t0 = time.perf_counter()
                _f(dt, hour)
                cost[key + "_s"] += time.perf_counter() - t0
            return mobw

        def w2(dt, _f=fn):
            t0 = time.perf_counter()
            _f(dt)
            cost[key + "_s"] += time.perf_counter() - t0
        return w2

    for k, r in runtimes.items():
        if r is not None:
            r.advance = wrap(k, orig[k], mobility=(k == "mobility"))

    t0 = time.perf_counter()
    for _ in range(minutes):
        w.advance_seconds(60.0, focus_xy=focus_xy)
    total_s = time.perf_counter() - t0

    for k, r in runtimes.items():
        if r is not None:
            r.advance = orig[k]
    other_s = total_s - sum(cost.values())
    out = {"total_ms_per_game_minute": round(total_s * 1000.0 / minutes, 3),
           "other_ms_per_game_minute": round(other_s * 1000.0 / minutes, 3),
           "game_minutes": minutes}
    for k in KEYS:
        out[k + "_ms_per_game_minute"] = round(cost[k + "_s"] * 1000.0 / minutes, 3)
    return out


def repeat_blocks(w, repeats: int = REPEATS, minutes: int = BLOCK, focus_xy=None) -> dict:
    rows = [timed_block(w, minutes, focus_xy) for _ in range(repeats)]
    keys = ["total_ms_per_game_minute", "other_ms_per_game_minute"] + \
           [k + "_ms_per_game_minute" for k in KEYS]
    out = {k: round(statistics.median(r[k] for r in rows), 3) for k in keys}
    out.update({"repeats": repeats, "game_minutes_per_block": minutes, "blocks": rows,
                "hour_after": round(w.current_hour(), 3)})
    return out


def dialogue_state(w) -> dict:
    """What the dialogue runtime is holding right now (context for a row)."""
    d = w.dialogue
    if d is None:
        return {}
    active = [c for c in d.conversations.values() if c.state == DS.ACTIVE]
    by_state: Counter = Counter(c.state for c in d.conversations.values())
    by_channel: Counter = Counter(c.channel for c in d.conversations.values())
    reqs: Counter = Counter(r.state for r in d.requests.values())
    return {"hour": round(w.current_hour(), 3),
            "n_conversations_kept": len(d.conversations), "n_active": len(active),
            "conversations_by_state": dict(sorted(by_state.items())),
            "conversations_by_channel": dict(sorted(by_channel.items())),
            "n_requests": len(d.requests), "requests_by_state": dict(sorted(reqs.items())),
            "n_events_in_ring": len(d.events), "event_seq": d.event_seq,
            "n_rendered_lines": len(d.rendered),
            "n_ask_cooldowns": len(d.ask_last), "n_request_cooldowns": len(d.request_last),
            "counts": dict(sorted(d.counts.items()))}


# --------------------------------------------------------------------------- #
# 1. conversation-session processing
# --------------------------------------------------------------------------- #
def measure_sessions(w, minutes: int = BLOCK, label: str = "") -> dict:
    """Time DialogueRuntime._substep in place, with the sessions it walks.

    ``_substep`` runs once per 1 s substep (60 per game minute): it steps every
    active conversation's queued plan, ages the player session and times out
    accepted requests, so its cost is O(conversations kept) + O(requests).
    """
    d = w.dialogue
    clean = timed_block(w, minutes)          # the honest cost: no instrumentation attached
    acc = {"s": 0.0, "calls": 0, "active": [], "kept": [], "requests": []}
    orig = d._substep

    def wrapped(_f=orig):
        acc["active"].append(sum(1 for c in d.conversations.values() if c.state == DS.ACTIVE))
        acc["kept"].append(len(d.conversations))
        acc["requests"].append(len(d.requests))
        t0 = time.perf_counter()
        r = _f()
        acc["s"] += time.perf_counter() - t0
        acc["calls"] += 1
        return r

    d._substep = wrapped
    before = dict(d.counts)
    block = timed_block(w, minutes)
    d._substep = orig
    after = d.counts
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in set(after) | set(before)}
    delta = {k: v for k, v in sorted(delta.items()) if v}
    n = max(1, acc["calls"])
    return {"label": label, "hour": round(w.current_hour(), 3), "game_minutes": minutes,
            "substep": {"calls": acc["calls"], "calls_per_game_minute": round(acc["calls"] / minutes, 1),
                        "ms_per_game_minute": round(acc["s"] * 1000.0 / minutes, 4),
                        "us_per_call": round(acc["s"] * 1e6 / n, 3),
                        "cadence": "every 1 s substep (60 per game minute)"},
            "active_sessions": {"max": max(acc["active"]) if acc["active"] else 0,
                                "mean": round(statistics.mean(acc["active"]), 3) if acc["active"] else 0.0,
                                "max_conversations_kept": max(acc["kept"]) if acc["kept"] else 0,
                                "max_requests_tracked": max(acc["requests"]) if acc["requests"] else 0},
            "dialogue_ms_per_game_minute": clean["dialogue_ms_per_game_minute"],
            "dialogue_ms_per_game_minute_instrumented": block["dialogue_ms_per_game_minute"],
            "share_of_dialogue_advance": round(
                (acc["s"] * 1000.0 / minutes) / max(1e-9, block["dialogue_ms_per_game_minute"]), 3),
            "events_in_block": delta,
            "speech_acts_per_game_minute": round(delta.get("SPEECH_ACT", 0) / minutes, 3),
            "block": clean, "instrumented_block": block, "dialogue_state": dialogue_state(w),
            "note": ("``dialogue_ms_per_game_minute`` is the clean block, timed before the "
                     "_substep wrapper is attached; the instrumented figure beside it carries the "
                     "wrapper's own per-substep bookkeeping and is only there to make the "
                     "_substep share meaningful")}


# --------------------------------------------------------------------------- #
# 2/3/4. grounding microbenchmarks (one store, no world)
# --------------------------------------------------------------------------- #
def _store(n_facts: int, owner: int = 1, now_s: float = 0.0) -> M.MemoryStore:
    """A store with ``n_facts`` distinct facts (a realistic mix of kinds), all
    of them recent enough to be retrievable."""
    st = M.MemoryStore(owner, capacity=max(M.CAPACITY, n_facts))
    kinds = [M.THREAT_PERSON, M.WORKED_BESIDE, M.ATTACK_SEEN, M.MET, M.CORPSE_SEEN,
             M.PLACE_SAFE, M.SERVED, M.HELPED_BY, M.SAW_HELP, M.DEATH_SEEN]
    for i in range(n_facts):
        st.remember(kinds[i % len(kinds)], now_s + i, actor=1000 + i, building_id=100 + (i % 7),
                    room_id=i % 5)
    return st


def measure_retrieval(sizes=(5, 20, M.CAPACITY), n_ops: int = MICRO_OPS) -> dict:
    """grounding.retrieve over stores of increasing size.

    retrieve() is a full linear scan of the store with a score per fact and a
    sort of the survivors; it is the first step of every answer.
    """
    rows = []
    now = 10_000.0
    for n in sizes:
        st = _store(n)
        subjects = [1000 + i for i in range(n)]
        r: dict = {"n_facts": n, "n_ops": n_ops}

        def bench(name: str, fn: Callable[[int], None]) -> None:
            t0 = time.perf_counter()
            for i in range(n_ops):
                fn(i)
            ms = (time.perf_counter() - t0) * 1000.0
            r[name] = {"us_per_op": round(1000.0 * ms / n_ops, 4),
                       "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                       "us_per_fact": round(1000.0 * ms / n_ops / max(1, n), 5)}

        bench("by_subject", lambda i: G.retrieve(st, now, subject=subjects[i % n]))
        bench("by_building", lambda i: G.retrieve(st, now, building_id=100 + (i % 7)))
        bench("by_kinds", lambda i: G.retrieve(st, now, kinds=G.EVENT_KINDS))
        rows.append({**r, "n_returned_by_kinds": len(G.retrieve(st, now, kinds=G.EVENT_KINDS))})
    return {"n_ops": n_ops, "top_k": G.TOP_K, "retrieval_floor": G.RETRIEVAL_FLOOR,
            "by_store_size": rows,
            "note": ("retrieve() scans every fact in the store, scores it (topic + subject + "
                     "place + recency + salience + confidence) and sorts the survivors; nothing "
                     "is indexed, so the cost is linear in the store and the store is capped at "
                     f"memory.CAPACITY = {M.CAPACITY}")}


def measure_grounding(n_ops: int = MICRO_OPS) -> dict:
    """grounding.ground on a supported proposition and on an unsupported one."""
    st = _store(M.CAPACITY)
    now = 10_000.0
    facts = sorted(st.facts.values(), key=lambda f: f.fact_id)
    threat = next(f for f in facts if f.kind == M.THREAT_PERSON)
    ok_prop = A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=threat.actor,
                            building_id=threat.building_id)
    bad_prop = A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=999_999)
    out: dict = {"n_ops": n_ops, "n_facts": len(st)}

    def bench(name: str, prop: A.Proposition) -> None:
        t0 = time.perf_counter()
        for _ in range(n_ops):
            g, verdict = G.ground(st, prop, now)
        ms = (time.perf_counter() - t0) * 1000.0
        out[name] = {"us_per_op": round(1000.0 * ms / n_ops, 4),
                     "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                     "verdict": verdict, "grounded": g is not None,
                     "epistemic": (g.epistemic if g is not None else None)}

    bench("accept", ok_prop)
    bench("reject", bad_prop)
    # the UNKNOWN short-circuit: the validator's cheapest exit
    t0 = time.perf_counter()
    for _ in range(n_ops):
        G.ground(st, A.Proposition(kind=A.UNKNOWN), now)
    ms = (time.perf_counter() - t0) * 1000.0
    out["unknown_short_circuit"] = {"us_per_op": round(1000.0 * ms / n_ops, 4),
                                    "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0))}
    out["note"] = ("ground() walks every fact of the speaker's store looking for one that "
                   "supports every field of the candidate; a rejection is the full scan, an "
                   "acceptance is the same scan (it keeps the best supporting fact), so the two "
                   "cost the same — the validator has no fast path for a lie")
    return out


def measure_render(n_ops: int = MICRO_OPS) -> dict:
    """render.render: templates over acts, with an epistemic frame per kind."""
    st = _store(M.CAPACITY)
    now = 10_000.0
    facts = sorted(st.facts.values(), key=lambda f: f.fact_id)
    props = [G.proposition_from_fact(f, now) for f in facts[:8]]
    out: dict = {"n_ops": n_ops}

    def bench(name: str, fn: Callable[[int], str]) -> None:
        t0 = time.perf_counter()
        for i in range(n_ops):
            line = fn(i)
        ms = (time.perf_counter() - t0) * 1000.0
        out[name] = {"us_per_op": round(1000.0 * ms / n_ops, 4),
                     "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                     "example": line}

    bench("with_proposition", lambda i: render(A.WARN, props[i % len(props)], speaker=1, listener=2,
                                               now_s=now, warmth=0.6))
    bench("bare_act", lambda i: render(A.GREET, None, speaker=1, listener=2, now_s=now, warmth=0.6))
    bench("refuse_with_reason", lambda i: render(A.REFUSE, None, speaker=1, listener=2, now_s=now,
                                                 warmth=0.1, reason=A.R_TOO_DANGEROUS))
    out["n_proposition_kinds_rendered"] = len({p.kind for p in props})
    out["note"] = ("the renderer is pure string formatting over the semantic act: no model, no "
                   "network, no state (render.py), so its cost never depends on the world")
    return out


# --------------------------------------------------------------------------- #
# 5. memory transfer (cognition.receive_fact — the ONE transmission path)
# --------------------------------------------------------------------------- #
def measure_transfer(city: str, seed: int = 0, n_ops: int = TRANSFER_OPS) -> dict:
    """receive_fact over scratch stores, per call.

    Every told fact — a warning, an answer that carries a fact, a shout — goes
    through ``CognitionRuntime.receive_fact``: it writes the told copy with its
    provenance and told confidence, invalidates beliefs, emits three cognition
    events and, for a threat, runs the avoidance decision at once.
    """
    _s, w = start_world(city, 9.0, seed=seed)
    warm(w, 2)
    c = w.cognition
    pair = [cid for cid in sorted(w.mobility.execs) if c._can_perceive(cid)][:2]
    if len(pair) < 2:
        return {"n_ops": 0, "note": "fewer than two perceiving citizens in this bundle"}
    sender, recipient = pair
    out: dict = {"n_ops": n_ops, "sender": sender, "recipient": recipient}

    def bench(name: str, kind: str) -> None:
        src = M.MemoryStore(sender)
        c.memories[sender] = src
        c.memories[recipient] = M.MemoryStore(recipient)
        f, _ = src.remember(kind, c.now_s, actor=4242, building_id=777, room_id=1,
                            source=M.DIRECT)
        t0 = time.perf_counter()
        for i in range(n_ops):
            if i % M.CAPACITY == 0:                    # a scratch recipient store, never a fossil
                c.memories[recipient] = M.MemoryStore(recipient)
            f.actor = 4242 + i                         # a new fact each call, as a real telling is
            c.receive_fact(recipient, sender, f, DS.FACE_TO_FACE, 777, 1)
        ms = (time.perf_counter() - t0) * 1000.0
        out[name] = {"kind": kind, "us_per_op": round(1000.0 * ms / n_ops, 3),
                     "ops_per_s": int(n_ops / max(1e-9, ms / 1000.0)),
                     "total_ms": round(ms, 2)}

    bench("threat_fact", M.THREAT_PERSON)
    bench("non_threat_fact", M.WORKED_BESIDE)
    out["note"] = ("the threat case additionally invalidates the recipient's beliefs and runs "
                   "_decide_avoid_one immediately (cognition/runtime.py: a warning is acted on at "
                   "once, not next minute); the difference between the two rows is that decision")
    return out


def measure_transfer_in_place(session, w, minutes: int = BLOCK) -> dict:
    """The same call timed where it really happens: inside the threat window,
    once per FACT_RECEIVED."""
    c = w.cognition
    acc: List[float] = []
    orig = c.receive_fact

    def wrapped(*a, **kw):
        t0 = time.perf_counter()
        r = orig(*a, **kw)
        acc.append((time.perf_counter() - t0) * 1000.0)
        return r

    c.receive_fact = wrapped
    block = timed_block(w, minutes)
    c.receive_fact = orig
    return {"hour": round(w.current_hour(), 3), "game_minutes": minutes,
            "n_calls": len(acc), "calls_per_game_minute": round(len(acc) / minutes, 3),
            "ms_per_game_minute": round(sum(acc) / minutes, 4),
            "mean_ms_per_call": round(statistics.mean(acc), 5) if acc else 0.0,
            "median_ms_per_call": round(statistics.median(acc), 5) if acc else 0.0,
            "max_ms_per_call": round(max(acc), 5) if acc else 0.0,
            "block": block,
            "note": "every call here is one FACT_RECEIVED: the transmission of a told fact"}


# --------------------------------------------------------------------------- #
# 6. social conversation selection (_decide_help now asks through dialogue)
# --------------------------------------------------------------------------- #
def measure_help(w, minutes: int = BLOCK, label: str = "") -> dict:
    """_decide_help per game minute and request_help per call.

    With conversations on, ``_decide_help`` no longer assigns a helper: the
    coworker with the problem asks the coworker it knows best and that one
    decides inside ``DialogueRuntime.request_help`` (cognition/runtime.py:800-813).
    """
    c, d = w.cognition, w.dialogue
    dec: List[float] = []
    req: List[float] = []
    outcomes: Counter = Counter()
    o_help, o_req, o_eval = c._decide_help, d.request_help, d.evaluate_request
    ev: List[float] = []

    def help_wrapped(_f=o_help):
        t0 = time.perf_counter()
        r = _f()
        dec.append((time.perf_counter() - t0) * 1000.0)
        return r

    def req_wrapped(*a, _f=o_req, **kw):
        t0 = time.perf_counter()
        r = _f(*a, **kw)
        req.append((time.perf_counter() - t0) * 1000.0)
        outcomes[r.state if r is not None else "no_request"] += 1
        return r

    def eval_wrapped(*a, _f=o_eval, **kw):
        t0 = time.perf_counter()
        r = _f(*a, **kw)
        ev.append((time.perf_counter() - t0) * 1000.0)
        return r

    c._decide_help, d.request_help, d.evaluate_request = help_wrapped, req_wrapped, eval_wrapped
    block = timed_block(w, minutes)
    c._decide_help, d.request_help, d.evaluate_request = o_help, o_req, o_eval

    def row(v: List[float], cadence: str) -> dict:
        return {"n_calls": len(v), "calls_per_game_minute": round(len(v) / minutes, 3),
                "ms_per_game_minute": round(sum(v) / minutes, 4),
                "mean_ms_per_call": round(statistics.mean(v), 5) if v else 0.0,
                "median_ms_per_call": round(statistics.median(v), 5) if v else 0.0,
                "max_ms_per_call": round(max(v), 5) if v else 0.0, "cadence": cadence}

    return {"label": label, "hour": round(w.current_hour(), 3), "game_minutes": minutes,
            "decide_help": row(dec, "once per game minute"),
            "request_help": row(req, "per asked coworker"),
            "evaluate_request": row(ev, "per request, inside request_help"),
            "request_outcomes": dict(sorted(outcomes.items())),
            "block": block, "dialogue_state": dialogue_state(w)}


# --------------------------------------------------------------------------- #
# 7. player dialogue query latency (the bridge TALK round trip)
# --------------------------------------------------------------------------- #
def co_present_pair(w) -> Optional[dict]:
    """Two citizens the dialogue runtime agrees are co-present and available.

    Read from ``work.occupants_by_room`` (never by building name) and confirmed
    through ``DialogueRuntime.co_present`` / ``available``.
    """
    d, wk = w.dialogue, w.work
    if d is None or wk is None:
        return None
    bids = sorted({int(ex.building_id) for ex in w.mobility.execs.values()
                   if ex.inside and ex.building_id is not None})
    best = None
    for bid in bids:
        for rid, occ in sorted(wk.occupants_by_room(bid).items(), key=lambda kv: str(kv[0])):
            occ = sorted(int(c) for c in occ if d.available(int(c), DS.PLAYER)[0])
            if len(occ) < 2:
                continue
            for i, a in enumerate(occ):
                for b in occ[i + 1:]:
                    if d.co_present(a, b)[0]:
                        cand = {"player": a, "npc": b, "building_id": bid, "room_id": rid,
                                "n_in_room": len(occ), "others": [c for c in occ if c not in (a, b)]}
                        if best is None or cand["n_in_room"] > best["n_in_room"]:
                            best = cand
                        break
                if best is not None and best["n_in_room"] >= 3:
                    return best
    return best


def measure_player_talk(session, w, repeats: int = REPEATS) -> dict:
    """The bridge TALK round trip for each player act against a co-present NPC.

    ``player_citizen`` is passed explicitly on the command (the bridge accepts
    it per TALK, and START_WORLD's player is rarely in a room with anyone) so
    the probe is always a real co-present pair rather than a lucky one.
    """
    pair = co_present_pair(w)
    if pair is None:
        return {"ok": False, "reason": "no co-present available pair in any room at this hour",
                "hour": round(w.current_hour(), 3)}
    player, npc = pair["player"], pair["npc"]
    subject = pair["others"][0] if pair["others"] else npc
    plan = [("GREET", {}), ("ASK_FACT", {"building_id": pair["building_id"]}),
            ("ASK_SAFETY", {}), ("ASK_PERSON", {"citizen_id": subject}),
            ("END_CONVERSATION", {})]
    per_act: Dict[str, List[float]] = {a: [] for a, _ in plan}
    lines: List[dict] = []
    refusals: Counter = Counter()
    for rep in range(repeats):
        for act, args in plan:
            msg = {"cmd": Command.TALK, "citizen_id": int(npc), "player_citizen": int(player),
                   "act": act, "args": args}
            t0 = time.perf_counter()
            r = session.handle(msg)
            per_act[act].append((time.perf_counter() - t0) * 1000.0)
            if not r.get("ok") or r.get("ok") is False:
                refusals[str(r.get("reason") or r.get("error"))] += 1
            if rep == 0:
                lines.append({"act": act, "ok": bool(r.get("ok")),
                              "reason": r.get("reason"), "lines": r.get("lines"),
                              "npc_state": r.get("state")})
    allms = [v for vs in per_act.values() for v in vs]
    return {"ok": True, "hour": round(w.current_hour(), 3), "pair": pair, "repeats": repeats,
            "median_ms_per_talk": round(statistics.median(allms), 4),
            "mean_ms_per_talk": round(statistics.mean(allms), 4),
            "max_ms_per_talk": round(max(allms), 4),
            "per_act_median_ms": {a: round(statistics.median(v), 4) for a, v in per_act.items()},
            "per_act_max_ms": {a: round(max(v), 4) for a, v in per_act.items()},
            "refusals": dict(refusals), "first_pass": lines,
            "note": ("one TALK is one bridge command: the whole player round trip (availability, "
                     "co-presence, the NPC's grounded answer, the renderer and the world summary "
                     "the bridge attaches to every response)")}


# --------------------------------------------------------------------------- #
# 8. windows and the whole day
# --------------------------------------------------------------------------- #
def drain(session, since: int) -> Tuple[List[dict], int]:
    snap = session.handle({"cmd": Command.GET_DIALOGUE, "since_seq": since})["dialogue"]
    rows = snap["events"]
    return rows, (rows[-1]["seq"] if rows else since)


def measure_window(session, w, to_hour: float, label: str) -> dict:
    """Advance minute by minute to ``to_hour``, timing each game minute and
    draining GET_DIALOGUE for the conversation trace."""
    rows: List[dict] = []
    events: List[dict] = []
    since = 0
    while w.current_hour() < to_hour - 1e-9:
        hour = w.current_hour()
        r = timed_block(w, 1)
        new, since = drain(session, since)
        events.extend(new)
        kinds = Counter(e["event"] for e in new)
        rows.append({"hour": round(hour, 4),
                     "total_ms": r["total_ms_per_game_minute"],
                     **{k + "_ms": r[k + "_ms_per_game_minute"] for k in KEYS},
                     "speech_acts": kinds.get("SPEECH_ACT", 0),
                     "conversations_started": kinds.get("CONVERSATION_STARTED", 0),
                     "facts_received": kinds.get("FACT_RECEIVED", 0),
                     "questions_asked": kinds.get("QUESTION_ASKED", 0),
                     "requests_made": kinds.get("REQUEST_MADE", 0),
                     "n_events": len(new)})
    worst = max(rows, key=lambda r: r["total_ms"]) if rows else {}
    worst_d = max(rows, key=lambda r: r["dialogue_ms"]) if rows else {}
    out = {"label": label, "hour_from": rows[0]["hour"] if rows else None,
           "hour_to": round(w.current_hour(), 4), "game_minutes": len(rows),
           "mean_total_ms_per_game_minute": round(statistics.mean(r["total_ms"] for r in rows), 3),
           "median_total_ms_per_game_minute": round(statistics.median(r["total_ms"] for r in rows), 3),
           **{"mean_" + k + "_ms_per_game_minute":
              round(statistics.mean(r[k + "_ms"] for r in rows), 3) for k in KEYS},
           "worst_minute": worst, "worst_dialogue_minute": worst_d,
           "n_minutes_over_budget": sum(1 for r in rows if r["total_ms"] > BUDGET_MS),
           "per_minute": rows, "dialogue_state": dialogue_state(w)}
    out["chatter"] = chatter_stats(w, events, rows)
    return out


def measure_day(city: str, dialogue: bool, seed: int = 0, from_hour: float = DAY_FROM,
                to_hour: float = DAY_TO) -> Tuple[dict, List[dict], object]:
    """05:00 -> 20:00 one timed game minute at a time, split per runtime.

    With dialogue on, GET_DIALOGUE is drained every game minute so the whole
    day's conversation trace survives the 5000-row ring.
    """
    session, w = start_world(city, from_hour, dialogue=dialogue, seed=seed)
    rows: List[dict] = []
    events: List[dict] = []
    since = 0
    t0 = time.perf_counter()
    while w.current_hour() < to_hour - 1e-9:
        hour = w.current_hour()
        r = timed_block(w, 1)
        if dialogue:
            new, since = drain(session, since)
            events.extend(new)
            kinds = Counter(e["event"] for e in new)
        else:
            kinds = Counter()
        rows.append({"hour": round(hour, 4), "total_ms": r["total_ms_per_game_minute"],
                     **{k + "_ms": r[k + "_ms_per_game_minute"] for k in KEYS},
                     "other_ms": r["other_ms_per_game_minute"],
                     "speech_acts": kinds.get("SPEECH_ACT", 0),
                     "conversations_started": kinds.get("CONVERSATION_STARTED", 0)})
    wall_s = time.perf_counter() - t0
    out = {"dialogue": dialogue, "hour_from": from_hour, "hour_to": to_hour,
           "game_minutes": len(rows), "wall_s": round(wall_s, 1),
           "mean_total_ms_per_game_minute": round(statistics.mean(r["total_ms"] for r in rows), 3),
           "median_total_ms_per_game_minute": round(statistics.median(r["total_ms"] for r in rows), 3),
           **{"mean_" + k + "_ms_per_game_minute":
              round(statistics.mean(r[k + "_ms"] for r in rows), 3) for k in KEYS},
           "mean_other_ms_per_game_minute": round(statistics.mean(r["other_ms"] for r in rows), 3),
           "worst_minute": max(rows, key=lambda r: r["total_ms"]),
           "n_minutes_over_budget": sum(1 for r in rows if r["total_ms"] > BUDGET_MS),
           "per_minute": rows}
    if dialogue:
        out["dialogue_state"] = dialogue_state(w)
        out["n_dialogue_events"] = len(events)
    return out, events, w


# --------------------------------------------------------------------------- #
# 9. chatter bounds
# --------------------------------------------------------------------------- #
def chatter_stats(w, events: List[dict], rows: List[dict]) -> dict:
    """Is the city a place where people occasionally speak, or a chat room?"""
    speech = [e for e in events if e["event"] == "SPEECH_ACT"]
    per_minute = [r["speech_acts"] for r in rows] if rows else [0]
    minutes = max(1, len(rows))
    # distinct speakers inside each game minute (the event t is world seconds)
    by_minute: Dict[int, set] = {}
    for e in speech:
        by_minute.setdefault(int(e["t"] // 60.0), set()).add(int(e["speaker"]))
    speakers_per_minute = [len(v) for v in by_minute.values()] or [0]
    # conversations per citizen over the run
    per_citizen: Counter = Counter()
    for e in events:
        if e["event"] == "CONVERSATION_STARTED":
            per_citizen[int(e["speaker"])] += 1
            per_citizen[int(e["listener"])] += 1
    # identical (speaker, listener, act, line) inside REPEAT_WINDOW_S
    last_seen: Dict[Tuple, float] = {}
    repeats = 0
    repeat_examples: List[dict] = []
    for e in speech:
        key = (int(e["speaker"]), e.get("listener"), e.get("act"), e.get("line"))
        t = float(e["t"])
        prev = last_seen.get(key)
        if prev is not None and t - prev <= REPEAT_WINDOW_S:
            repeats += 1
            if len(repeat_examples) < 10:
                repeat_examples.append({"t": t, "gap_s": round(t - prev, 1), "speaker": key[0],
                                        "listener": key[1], "act": key[2], "line": key[3]})
        last_seen[key] = t
    d = w.dialogue
    acts: Counter = Counter(e.get("act") for e in speech)
    channels: Counter = Counter(e.get("channel") for e in speech)
    ends: Counter = Counter(e.get("reason") for e in events
                            if e["event"] in ("CONVERSATION_ENDED", "CONVERSATION_INTERRUPTED"))
    return {
        "n_speech_acts": len(speech), "game_minutes": minutes,
        "speech_acts_per_game_minute_mean": round(len(speech) / minutes, 3),
        "speech_acts_per_game_minute_max": max(per_minute),
        "distinct_speakers_per_game_minute_max": max(speakers_per_minute),
        "distinct_speakers_per_game_minute_mean": round(statistics.mean(speakers_per_minute), 3),
        "n_citizens_who_spoke": len({int(e["speaker"]) for e in speech}),
        "conversations_per_citizen_max": max(per_citizen.values()) if per_citizen else 0,
        "conversations_per_citizen_mean": round(statistics.mean(per_citizen.values()), 3)
        if per_citizen else 0.0,
        "n_citizens_in_a_conversation": len(per_citizen),
        "identical_line_repeats_within_10_min": repeats,
        "identical_line_repeat_examples": repeat_examples,
        "acts": dict(acts.most_common()), "channels": dict(sorted(channels.items())),
        "end_reasons": dict(ends.most_common()),
        "rings": {"events_in_ring": len(d.events), "events_ring_cap": DR.MAX_EVENTS,
                  "conversations_kept": len(d.conversations),
                  "conversations_kept_cap": DR.MAX_CONVERSATIONS_KEPT,
                  "ended_conversations_kept": sum(1 for c in d.conversations.values()
                                                  if c.state != DS.ACTIVE),
                  "rendered_lines": len(d.rendered), "rendered_cap": 200,
                  "max_acts_per_conversation": max((c.n_acts for c in d.conversations.values()),
                                                   default=0),
                  "acts_kept_per_conversation_cap": DS.MAX_ACTS,
                  "within_bounds": bool(len(d.events) <= DR.MAX_EVENTS
                                        and sum(1 for c in d.conversations.values()
                                                if c.state != DS.ACTIVE) <= DR.MAX_CONVERSATIONS_KEPT
                                        and len(d.rendered) <= 200)},
        "note": ("an identical (speaker, listener, act, line) inside 10 game minutes is the "
                 "signature of a stuck loop; the cooldowns (ASK_COOLDOWN_S 1800 s, "
                 "REQUEST_COOLDOWN_S 3600 s) and cognition's told-set are what should keep it at "
                 "zero. The drain is once per game minute, so the 5000-row event ring never "
                 "loses a row"),
    }


# --------------------------------------------------------------------------- #
# 10. profile of dialogue.advance + the player TALK path
# --------------------------------------------------------------------------- #
def _fname(fn: str) -> str:
    """``.../asphodel/dialogue/runtime.py`` -> ``dialogue/runtime.py`` (the
    runtimes share the basename)."""
    parts = os.path.normpath(fn).split(os.sep)
    return "/".join(parts[-2:]) if len(parts) >= 2 else fn


SCALING: Dict[Tuple[str, str], str] = {
    ("dialogue/runtime.py", "advance"): "per game minute: 60 substeps",
    ("dialogue/runtime.py", "_substep"): (
        "per 1 s substep (60 per game minute): a sorted walk of EVERY conversation kept — active "
        "or not, up to MAX_CONVERSATIONS_KEPT = 400 — plus a walk of every request ever made "
        "(dialogue/runtime.py:640-680); the sort of the keys is redone every second"),
    ("dialogue/runtime.py", "_step_plan"): (
        "per active conversation per second: availability of both, co-presence when face to "
        "face, the fresh-threat interrupt check, then one queued act"),
    ("dialogue/runtime.py", "say"): (
        "per speech act: one ground() over the speaker's store, one render(), two event rows"),
    ("dialogue/runtime.py", "transmit"): (
        "per told fact: say() plus cognition.receive_fact plus two event rows"),
    ("dialogue/runtime.py", "warn"): (
        "per telling cognition decided on: starts a conversation and queues a six-act plan"),
    ("dialogue/runtime.py", "co_present"): (
        "per availability check: two executor lookups and two cognition._ctx calls"),
    ("dialogue/runtime.py", "_fresh_threat"): (
        "per conversation per second: a full scan of one citizen's store (up to "
        f"{M.CAPACITY} facts) for a fresh first-hand threat"),
    ("dialogue/runtime.py", "available"): "per participant per second while a conversation is open",
    ("dialogue/runtime.py", "request_help"): (
        "per asked coworker: cooldowns, availability, help_score twice (the decision and its "
        "counterfactual), a WorkRuntime.assist and up to five acts"),
    ("dialogue/runtime.py", "evaluate_request"): "per request: one help_score plus the work checks",
    ("dialogue/runtime.py", "player_talk"): "per bridge TALK command",
    ("dialogue/runtime.py", "_answer"): (
        "per question: one grounding.event_answer / person_answer / safety_answer, each a "
        "bounded retrieve over the answerer's store"),
    ("dialogue/grounding.py", "retrieve"): (
        f"per query: a full scan of the store (<= memory.CAPACITY = {M.CAPACITY} facts), a score "
        "per fact and a sort of the survivors"),
    ("dialogue/grounding.py", "ground"): (
        "per asserted proposition: a full scan of the speaker's store for a supporting fact"),
    ("dialogue/grounding.py", "proposition_from_fact"): "per assertion: a dataclass build",
    ("dialogue/grounding.py", "event_answer"): "per ASK_FACT: retrieve + a max over the survivors",
    ("dialogue/grounding.py", "safety_answer"): (
        "per ASK_SAFETY: the answerer's belief derivation plus a retrieve over the place"),
    ("dialogue/render.py", "render"): "per speech act: pure string formatting",
    ("cognition/runtime.py", "receive_fact"): (
        "per told fact: the told copy, belief invalidation, three cognition events and — for a "
        "threat — the avoidance decision immediately"),
    ("cognition/runtime.py", "_decide_help"): (
        "per game minute: O(open work sessions) + per building with >= 2 workers, one "
        "request_help conversation per problem"),
}


def measure_profile(session, w, minutes: int = 20, talks: int = 20) -> Tuple[dict, dict]:
    """cProfile DialogueRuntime.advance across a live window, plus the player
    TALK path under the same profiler."""
    d = w.dialogue
    pr = cProfile.Profile()
    orig = d.advance

    def wrapped(dt, _f=orig):
        return pr.runcall(_f, dt)

    d.advance = wrapped
    t0 = time.perf_counter()
    for _ in range(minutes):
        w.advance_seconds(60.0)
    wall_s = time.perf_counter() - t0
    d.advance = orig

    pair = co_present_pair(w)
    n_talks = 0
    if pair is not None:
        plan = [("GREET", {}), ("ASK_FACT", {"building_id": pair["building_id"]}),
                ("ASK_SAFETY", {}), ("ASK_PERSON", {"citizen_id": pair["npc"]}),
                ("END_CONVERSATION", {})]
        for i in range(talks):
            act, args = plan[i % len(plan)]
            pr.runcall(w.talk, int(pair["player"]), int(pair["npc"]), act, args)
            n_talks += 1

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
           "n_talks_profiled": n_talks, "talk_pair": pair,
           "profiled_s": round(total_s, 3),
           "dialogue_ms_per_game_minute_under_profiler": round(total_s * 1000.0 / minutes, 1),
           "whole_advance_ms_per_game_minute_under_profiler": round(wall_s * 1000.0 / minutes, 1),
           "by_cumtime": by_cum[:15], "by_tottime": by_tot[:15],
           "dialogue_state": dialogue_state(w),
           "note": ("only DialogueRuntime.advance and the player TALK path are profiled "
                    "(cProfile.runcall around each), so the shares below are shares of dialogue, "
                    "not of the whole world step. cProfile inflates absolute cost; read the "
                    "shares.")}
    return doc, lookup


def hotspots(prof: dict, lookup: dict) -> List[dict]:
    out = []
    for row in prof["by_tottime"][:12]:
        key = (row["file"], row["name"])
        out.append({"function": f"{row['file']}:{row['name']}", "where": row["function"],
                    "tottime_pct": row["tottime_pct"], "cumtime_pct": row["cumtime_pct"],
                    "calls_per_game_minute": row["calls_per_game_minute"],
                    "scaling": SCALING.get(key, "not annotated (see the profile rows)")})
    for key in (("dialogue/runtime.py", "_substep"), ("dialogue/runtime.py", "_step_plan"),
                ("dialogue/runtime.py", "say"), ("dialogue/runtime.py", "transmit"),
                ("dialogue/runtime.py", "_fresh_threat"), ("dialogue/grounding.py", "ground"),
                ("dialogue/grounding.py", "retrieve"), ("dialogue/render.py", "render"),
                ("cognition/runtime.py", "receive_fact")):
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
    s0, w0 = start_world(city, 8.0, seed=seed)
    build_ms = (time.perf_counter() - t0) * 1000.0
    res["world"] = {
        "n_citizens": len(w0.mobility.execs), "n_vehicles": len(w0.mobility.vehicles),
        "start_world_ms": round(build_ms, 1),
        "dialogue_enabled": w0.dialogue is not None,
        "cognition_enabled": w0.cognition is not None,
        "n_employed": len(w0.work.employment) if w0.work else 0,
        "n_prior_relationships": len(w0.cognition.rels.rels),
        "player_citizen": s0.player_citizen,
        "channels": list(DS.CHANNELS), "acts": list(A.ACTS),
        "note": ("START_WORLD enables dialogue by default whenever cognition is on "
                 "(bridge/session.py:184-186); the player citizen is what TALK needs"),
    }
    print(f"[{city}] START_WORLD in {build_ms / 1000:.1f} s, {len(w0.mobility.execs)} citizens, "
          f"dialogue {'on' if w0.dialogue is not None else 'OFF'}")

    # -- 1. sessions at 08:00 ----------------------------------------------
    warm(w0)
    res["sessions"] = {}
    res["sessions"]["0800"] = measure_sessions(w0, BLOCK, "08:00 morning, no threat")
    s = res["sessions"]["0800"]
    print(f"  sessions 08:00: dialogue {s['dialogue_ms_per_game_minute']:.3f} ms/game-min, "
          f"_substep {s['substep']['us_per_call']} us/call, "
          f"max {s['active_sessions']['max']} active")

    # -- 2/3/4. grounding microbenchmarks -----------------------------------
    res["retrieval"] = measure_retrieval()
    res["grounding"] = measure_grounding()
    res["rendering"] = measure_render()
    print("  retrieval:    " + ", ".join(
        f"{r['n_facts']} facts {r['by_subject']['us_per_op']} us" for r in res["retrieval"]["by_store_size"]))
    print(f"  grounding:    accept {res['grounding']['accept']['us_per_op']} us/op, "
          f"reject {res['grounding']['reject']['us_per_op']} us/op; render "
          f"{res['rendering']['with_proposition']['us_per_op']} us/op")

    # -- 5. transfer over scratch stores ------------------------------------
    res["transfer"] = measure_transfer(city, seed)
    if res["transfer"].get("threat_fact"):
        print(f"  transfer:     receive_fact threat {res['transfer']['threat_fact']['us_per_op']} "
              f"us/op, non-threat {res['transfer']['non_threat_fact']['us_per_op']} us/op")

    # -- 6. help selection at 08:00 -----------------------------------------
    res["help"] = {}
    res["help"]["0800"] = measure_help(w0, BLOCK, "08:00, no threat")
    h = res["help"]["0800"]
    print(f"  help 08:00:   _decide_help {h['decide_help']['mean_ms_per_call']:.4f} ms/call, "
          f"{h['request_help']['n_calls']} requests {h['request_outcomes']}")

    # -- 7. player TALK latency at 08:00 ------------------------------------
    res["player_talk"] = {"0800": measure_player_talk(s0, w0)}
    p = res["player_talk"]["0800"]
    print("  player TALK 08:00: " + (f"{p['median_ms_per_talk']} ms median "
                                     f"({p['pair']['player']} -> {p['pair']['npc']} in room "
                                     f"{p['pair']['room_id']} of {p['pair']['building_id']})"
                                     if p["ok"] else f"none — {p['reason']}"))

    # -- 8. the threat world: sessions in the 10:45 window ------------------
    s1, w1, info1 = threat_world(city, seed, args.seed_hour)
    res["threat_seed"] = info1
    print(f"  threat seeded: {info1.get('pathogen')} citizen {info1.get('citizen_id')} in "
          f"building {info1.get('building_id')} at {info1.get('seeded_at_hour')}h"
          + (" (FALLBACK)" if info1.get("fallback") else ""))
    run_to(w1, THREAT_BLOCK_HOUR)
    res["sessions"]["threat"] = measure_sessions(
        w1, BLOCK, f"10:45 threat window ({info1.get('pathogen')} seeded at "
                   f"{info1.get('seeded_at_hour')}h)")
    s = res["sessions"]["threat"]
    print(f"  sessions 10:45: dialogue {s['dialogue_ms_per_game_minute']:.3f} ms/game-min, "
          f"max {s['active_sessions']['max']} active, "
          f"{s['speech_acts_per_game_minute']} speech acts/game-min")
    res["help"]["threat"] = measure_help(w1, BLOCK, "10:45 threat window")
    res["player_talk"]["threat"] = measure_player_talk(s1, w1)

    # receive_fact timed where the tellings actually are: the minutes right after
    # the case rises, on its own world so no earlier block has drained the news
    s1b, w1b, info1b = threat_world(city, seed, args.seed_hour)
    run_to(w1b, info1b["seeded_at_hour"] + 8.0 / 60.0)
    res["transfer_in_place"] = measure_transfer_in_place(s1b, w1b, BLOCK * 3)
    t = res["transfer_in_place"]
    print(f"  transfer in place: {t['n_calls']} FACT_RECEIVED in {t['game_minutes']} game-min "
          f"from {t['hour']}h, {t['mean_ms_per_call']} ms/call")

    # -- 9. sessions at 16:00 (no threat) -----------------------------------
    _s2, w2 = start_world(city, 16.0, seed=seed)
    warm(w2)
    res["sessions"]["1600"] = measure_sessions(w2, BLOCK, "16:00 afternoon, no threat")
    s = res["sessions"]["1600"]
    print(f"  sessions 16:00: dialogue {s['dialogue_ms_per_game_minute']:.3f} ms/game-min, "
          f"max {s['active_sessions']['max']} active")

    # -- 10. the combined window 10:35 -> 11:35 -----------------------------
    s3, w3, info3 = threat_world(city, seed, args.seed_hour)
    res["threat_seed_window_run"] = info3
    window = measure_window(s3, w3, info3["seeded_at_hour"] + 1.0,
                            f"work + outbreak + cognition + dialogue, {info3['seeded_at_hour']}h "
                            f"-> {round(info3['seeded_at_hour'] + 1.0, 3)}h "
                            f"({info3.get('pathogen')})")
    res["combined_window"] = window
    print(f"  combined window {window['hour_from']}-{window['hour_to']}h: "
          f"{window['mean_total_ms_per_game_minute']:.1f} ms/game-min "
          f"(dialogue {window['mean_dialogue_ms_per_game_minute']:.2f}); "
          f"{window['chatter']['n_speech_acts']} speech acts, max "
          f"{window['chatter']['speech_acts_per_game_minute_max']}/min, "
          f"{window['chatter']['identical_line_repeats_within_10_min']} repeated lines")

    # -- 11. profile of dialogue.advance + TALK -----------------------------
    s4, w4, info4 = threat_world(city, seed, args.seed_hour)
    run_to(w4, info4["seeded_at_hour"] + 10.0 / 60.0)
    res["profile"], lookup = measure_profile(s4, w4, 20)
    res["hotspots"] = hotspots(res["profile"], lookup)
    print(f"  profile: dialogue {res['profile']['dialogue_ms_per_game_minute_under_profiler']} "
          f"ms/game-min under cProfile over 20 game-minutes + "
          f"{res['profile']['n_talks_profiled']} TALKs")

    # -- 12. the whole day, dialogue on vs off -------------------------------
    day_on, day_events, w_day = measure_day(city, True, seed, args.day_from, args.day_to)
    print(f"  day {args.day_from:.0f}:00-{args.day_to:.0f}:00 dialogue ON:  "
          f"{day_on['wall_s']:.0f} s wall, {day_on['mean_total_ms_per_game_minute']:.1f} "
          f"ms/game-min (dialogue {day_on['mean_dialogue_ms_per_game_minute']:.2f})")
    day_off, _e, _w = measure_day(city, False, seed, args.day_from, args.day_to)
    print(f"  day {args.day_from:.0f}:00-{args.day_to:.0f}:00 dialogue OFF: "
          f"{day_off['wall_s']:.0f} s wall, {day_off['mean_total_ms_per_game_minute']:.1f} "
          f"ms/game-min")
    res["day"] = {
        "dialogue_on": day_on, "dialogue_off": day_off,
        "wall_s_delta": round(day_on["wall_s"] - day_off["wall_s"], 1),
        "wall_s_ratio": round(day_on["wall_s"] / max(1e-9, day_off["wall_s"]), 3),
        "ms_per_game_minute_delta": round(day_on["mean_total_ms_per_game_minute"]
                                          - day_off["mean_total_ms_per_game_minute"], 3),
        "dialogue_share_of_day": round(day_on["mean_dialogue_ms_per_game_minute"]
                                       / max(1e-9, day_on["mean_total_ms_per_game_minute"]), 4),
        "cognition_ms_delta": round(day_on["mean_cognition_ms_per_game_minute"]
                                    - day_off["mean_cognition_ms_per_game_minute"], 3),
        "note": ("the same bundle, seed and hours, booted once with START_WORLD dialogue:true and "
                 "once with dialogue:false; each game minute is timed on its own and split by "
                 "instance wrappers on every runtime's advance. The cognition delta is what "
                 "routing warnings and help requests through conversations costs the cognition "
                 "runtime itself"),
    }
    res["chatter_day"] = chatter_stats(w_day, day_events, day_on["per_minute"])
    ch = res["chatter_day"]
    print(f"  chatter (day): {ch['n_speech_acts']} speech acts, "
          f"{ch['speech_acts_per_game_minute_mean']}/min mean, "
          f"{ch['speech_acts_per_game_minute_max']} max, max "
          f"{ch['distinct_speakers_per_game_minute_max']} distinct speakers/min, max "
          f"{ch['conversations_per_citizen_max']} conversations per citizen, "
          f"{ch['identical_line_repeats_within_10_min']} identical lines within 10 min")

    # -- budget -------------------------------------------------------------
    cands = [(res["sessions"]["0800"]["block"], "08:00 block"),
             (res["sessions"]["threat"]["block"], "10:45 threat block"),
             (res["sessions"]["1600"]["block"], "16:00 block"),
             (res["help"]["threat"]["block"], "10:45 help block")]
    worst_block, worst_label = max(cands, key=lambda kv: kv[0]["total_ms_per_game_minute"])
    worst_single = max([day_on["worst_minute"], window["worst_minute"]],
                       key=lambda r: r["total_ms"])
    wm = max(worst_block["total_ms_per_game_minute"], window["mean_total_ms_per_game_minute"],
             day_on["mean_total_ms_per_game_minute"])
    talk_ms = max((v["median_ms_per_talk"] for v in res["player_talk"].values() if v.get("ok")),
                  default=None)
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
        "dialogue_ms_per_game_minute_day_mean": day_on["mean_dialogue_ms_per_game_minute"],
        "dialogue_share_worst_block": round(
            worst_block["dialogue_ms_per_game_minute"]
            / max(1e-9, worst_block["total_ms_per_game_minute"]), 4),
        "median_ms_per_player_talk": talk_ms,
        "n_minutes_over_budget_day": day_on["n_minutes_over_budget"],
        "n_minutes_over_budget_window": window["n_minutes_over_budget"],
        "note": (f"at {CLOCK_X:.0f}x one game minute is {GAME_MINUTE_REAL_S} s of real time "
                 f"({BUDGET_MS:.0f} ms). The heaviest measured mean game-minute ({round(wm, 1)} ms) "
                 f"uses {100.0 * wm / BUDGET_MS:.2f}% of it; the dialogue runtime is "
                 f"{day_on['mean_dialogue_ms_per_game_minute']} ms of the day mean "
                 f"({100.0 * day_on['mean_dialogue_ms_per_game_minute'] / max(1e-9, day_on['mean_total_ms_per_game_minute']):.1f}% "
                 f"of the whole world step). The worst single measured game minute is "
                 f"{worst_single['total_ms']} ms at {worst_single['hour']}h, of which dialogue is "
                 f"{worst_single.get('dialogue_ms')} ms — the spike is the rest of the world, not "
                 f"the conversations"
                 + (f", and one player TALK answers in {talk_ms} ms — a keystroke, not a frame."
                    if talk_ms is not None else ".")),
    }

    doc = {"version": 1, "milestone": "ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1",
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
        s = doc["sessions"][key]
        rows.append((f"dialogue.advance {key} (per game-min)", s["dialogue_ms_per_game_minute"],
                     f"_substep {s['substep']['us_per_call']} us/call x "
                     f"{s['substep']['calls_per_game_minute']:.0f}; max "
                     f"{s['active_sessions']['max']} active sessions, "
                     f"{s['active_sessions']['max_conversations_kept']} kept; "
                     f"{s['speech_acts_per_game_minute']} speech acts/game-min"))
    for r in doc["retrieval"]["by_store_size"]:
        rows.append((f"grounding.retrieve ({r['n_facts']} facts)",
                     r["by_subject"]["us_per_op"] / 1000.0,
                     f"subject {r['by_subject']['us_per_op']} us, place "
                     f"{r['by_building']['us_per_op']} us, kinds {r['by_kinds']['us_per_op']} us "
                     f"({r['by_subject']['us_per_fact']} us/fact)"))
    g = doc["grounding"]
    rows.append(("grounding.ground (accepted)", g["accept"]["us_per_op"] / 1000.0,
                 f"{g['accept']['us_per_op']} us/op, {g['accept']['ops_per_s']:,} ops/s, verdict "
                 f"{g['accept']['verdict']} ({g['accept']['epistemic']})"))
    rows.append(("grounding.ground (rejected)", g["reject"]["us_per_op"] / 1000.0,
                 f"{g['reject']['us_per_op']} us/op, verdict {g['reject']['verdict']}; UNKNOWN "
                 f"short circuit {g['unknown_short_circuit']['us_per_op']} us/op"))
    rn = doc["rendering"]
    rows.append(("render.render (proposition)", rn["with_proposition"]["us_per_op"] / 1000.0,
                 f"{rn['with_proposition']['us_per_op']} us/op, "
                 f"{rn['with_proposition']['ops_per_s']:,} ops/s; bare act "
                 f"{rn['bare_act']['us_per_op']} us/op"))
    tr = doc["transfer"]
    if tr.get("threat_fact"):
        rows.append(("cognition.receive_fact (threat)", tr["threat_fact"]["us_per_op"] / 1000.0,
                     f"{tr['threat_fact']['us_per_op']} us/op over {tr['n_ops']:,} ops "
                     f"(includes the immediate avoidance decision)"))
        rows.append(("cognition.receive_fact (non-threat)",
                     tr["non_threat_fact"]["us_per_op"] / 1000.0,
                     f"{tr['non_threat_fact']['us_per_op']} us/op"))
    tp = doc["transfer_in_place"]
    rows.append(("receive_fact in the threat window", tp["mean_ms_per_call"],
                 f"{tp['n_calls']} FACT_RECEIVED over {tp['game_minutes']} game-min "
                 f"({tp['calls_per_game_minute']}/min), max {tp['max_ms_per_call']} ms/call"))
    for key in ("0800", "threat"):
        h = doc["help"][key]
        rows.append((f"_decide_help {key} (per call)", h["decide_help"]["mean_ms_per_call"],
                     f"{h['decide_help']['ms_per_game_minute']} ms/game-min; request_help "
                     f"{h['request_help']['n_calls']} calls at "
                     f"{h['request_help']['mean_ms_per_call']} ms, outcomes "
                     f"{h['request_outcomes']}"))
    for key in ("0800", "threat"):
        p = doc["player_talk"].get(key) or {}
        if p.get("ok"):
            rows.append((f"bridge TALK {key} (per command)", p["median_ms_per_talk"],
                         "per act " + ", ".join(f"{a} {ms}" for a, ms in
                                                p["per_act_median_ms"].items())
                         + f"; pair {p['pair']['player']} -> {p['pair']['npc']}"))
        else:
            rows.append((f"bridge TALK {key} (per command)", None,
                         f"no probe: {p.get('reason')}"))
    win = doc["combined_window"]
    rows.append(("work+outbreak+cognition+dialogue window", win["mean_total_ms_per_game_minute"],
                 f"mobility {win['mean_mobility_ms_per_game_minute']}, outbreak "
                 f"{win['mean_outbreak_ms_per_game_minute']}, work "
                 f"{win['mean_work_ms_per_game_minute']}, cognition "
                 f"{win['mean_cognition_ms_per_game_minute']}, dialogue "
                 f"{win['mean_dialogue_ms_per_game_minute']}; worst minute "
                 f"{win['worst_minute']['total_ms']} ms at {win['worst_minute']['hour']}h"))
    d_on, d_off = doc["day"]["dialogue_on"], doc["day"]["dialogue_off"]
    rows.append(("whole day, dialogue ON", d_on["mean_total_ms_per_game_minute"],
                 f"{d_on['wall_s']} s wall for {d_on['game_minutes']} game-min; cognition "
                 f"{d_on['mean_cognition_ms_per_game_minute']}, dialogue "
                 f"{d_on['mean_dialogue_ms_per_game_minute']}; worst minute "
                 f"{d_on['worst_minute']['total_ms']} ms"))
    rows.append(("whole day, dialogue OFF", d_off["mean_total_ms_per_game_minute"],
                 f"{d_off['wall_s']} s wall; delta {doc['day']['ms_per_game_minute_delta']} "
                 f"ms/game-min, wall ratio {doc['day']['wall_s_ratio']}x, cognition delta "
                 f"{doc['day']['cognition_ms_delta']} ms/game-min"))
    ch = doc["chatter_day"]
    rows.append(("chatter over the day", None,
                 f"{ch['n_speech_acts']} speech acts, {ch['speech_acts_per_game_minute_mean']}/min "
                 f"mean and {ch['speech_acts_per_game_minute_max']} max; max "
                 f"{ch['distinct_speakers_per_game_minute_max']} distinct speakers/min; "
                 f"{ch['n_citizens_in_a_conversation']} citizens ever in a conversation, max "
                 f"{ch['conversations_per_citizen_max']} each; "
                 f"{ch['identical_line_repeats_within_10_min']} identical lines within 10 min"))
    r = ch["rings"]
    rows.append(("ring sizes at 20:00", None,
                 f"events {r['events_in_ring']}/{r['events_ring_cap']}, ended conversations kept "
                 f"{r['ended_conversations_kept']}/{r['conversations_kept_cap']}, rendered "
                 f"{r['rendered_lines']}/{r['rendered_cap']}, longest conversation "
                 f"{r['max_acts_per_conversation']} acts (kept "
                 f"{r['acts_kept_per_conversation_cap']}); within bounds {r['within_bounds']}"))

    print("")
    print(f"{'measurement':46s} {'ms':>10s}  detail")
    print("-" * 46 + " " + "-" * 10 + "  " + "-" * 60)
    for name, ms, detail in rows:
        val = "-" if ms is None else f"{ms:.4f}".rstrip("0").rstrip(".")
        print(f"{name:46s} {val:>10s}  {detail}")

    print("")
    print(f"  profile (cProfile of dialogue.advance over {doc['profile']['game_minutes']} "
          f"game-minutes in the threat window plus {doc['profile']['n_talks_profiled']} TALKs) — "
          f"top 8 by tottime:")
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

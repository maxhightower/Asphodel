#!/usr/bin/env python3
"""Per-city smoke test for the NPC cognition runtime
(ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1).

For each requested city bundle: boot the world exactly as the game does
(bridge ``START_WORLD``, which enables mobility, the work runtime and the
cognition runtime and seeds the household / workplace relationship priors),
run one day (05:00 -> 17:00 in 60 s steps) with the certification threat
stressor seeded inside the busiest shop, drain ``GET_COGNITION`` every game
minute and report what the citizens actually learned and did:

    * the day: MEMORY_CREATED, RELATIONSHIP_CHANGED, HELP_DECIDED /
      HELP_COMPLETED, WARNING_SHARED / WARNING_RECEIVED, AVOID_DECIDED,
      AVOID_ROOM_DECIDED, PERCEIVED, TRUST_CHANGED — both as emitted events
      and as the runtime's persistent counts (low-salience rows are counted
      without emitting an event);
    * memory: how many citizens hold memories, how many facts in total, and
      the most any single citizen holds (which must stay within
      ``memory.CAPACITY``);
    * relationships: how many pairs exist and how many moved on at least one
      of familiarity / trust / affinity / obligation away from the value the
      household / workplace prior gave them at boot — a relationship changed
      by something that happened, not by a prior;
    * rumor boundedness: the most tellings any one sender made and the
      maximum hop depth reached;
    * determinism: the city is built and run twice — booted at 05:00, seeded
      by the same rule at the same game minute and advanced three further
      game hours — and the two cognition event lists plus a memory /
      relationship digest must be identical;
    * cost: wall time and milliseconds per game minute.

The stressor is seeded the way the certification seeds it: the first game
minute at or after ``--seed-hour`` in which any ``customer`` work session
exists anywhere, in the building with the most such sessions (ties by lowest
building id), on the lowest customer id inside it, with pathogen
``classic_zombie_fast``. When no customer session exists by the cutoff the
fallback is ``classic_zombie`` with the data-driven index case, and the row
says so.

    PYTHONPATH=. python3 tools/cognition_city_smoke.py [city ...]

Status per city:
    PASS   memories accumulated, at least one relationship moved because of
           an event rather than a prior, at least one social action happened
           (HELP_DECIDED or WARNING_SHARED or AVOID_DECIDED), no citizen
           exceeded the memory capacity and the run was deterministic
    INFO   no compiled world in the bundle (nothing to embody), or no citizen
           in the bundle is employable (nobody is ever delivered to work, so
           there is nothing to perceive)
    FAIL   anything else

Exit code is non-zero when any city FAILs.
Writes artifacts/npc_cognition_v1/city_smoke.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from collections import Counter
from typing import Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.bridge.worldfactory import resolve_bundle_dir           # noqa: E402
from asphodel.cognition import memory as M                            # noqa: E402
from asphodel.cognition.relationships import DIMS                     # noqa: E402

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio", "boulder"]
ARTIFACT = os.path.join(REPO, "artifacts", "npc_cognition_v1", "city_smoke.json")

START_HOUR = 5.0
END_HOUR = 17.0
STEP_S = 60.0
SEED_HOUR = 10.5833                  # 10:35 — the earliest the stressor may be seeded
SEED_CUTOFF_HOUR = 12.0
PATHOGEN = "classic_zombie_fast"
FALLBACK_PATHOGEN = "classic_zombie"
DETERMINISM_HOURS = 3.0              # game hours run past the seeding in each replay
SEED = 0

# the events that tell the story of a cognitive day, in reading order
STORY_EVENTS = ("PERCEIVED", "MEMORY_CREATED", "MEMORY_REINFORCED", "MEMORY_DECAYED",
                "RELATIONSHIP_CHANGED", "TRUST_CHANGED", "HELP_DECIDED", "HELP_COMPLETED",
                "WARNING_SHARED", "WARNING_RECEIVED", "AVOID_DECIDED", "AVOID_ROOM_DECIDED",
                "SOCIAL_ACTION", "BELIEF_UPDATED")
# the dimensions a prior sets; a move on any of them is experience, not a prior
PRIOR_DIMS = ("familiarity", "trust", "affinity", "obligation")
# what PASS requires: a social action is any one of these
SOCIAL_ACTIONS = ("HELP_DECIDED", "WARNING_SHARED", "AVOID_DECIDED")


def has_compiled_world(bundle_dir: str) -> bool:
    """A bundle is embodiable only if its compiled world carries spawn anchors."""
    return os.path.exists(os.path.join(bundle_dir, "world", "spawn_anchors.json.gz"))


def build_world(city: str, start_hour: float, seed: int = SEED):
    """World + mobility + work + cognition, exactly as the game boots one
    (START_WORLD enables cognition by default whenever mobility is on).
    Returns ``(session, world)`` — the session issues SEED_OUTBREAK and
    GET_COGNITION the way the client does."""
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = s.handle({"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
                  "start_hour": float(start_hour)})
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    if not r.get("cognition_enabled"):
        raise RuntimeError(f"START_WORLD did not enable cognition for {city}: {r}")
    return s, s.world


class EventTape:
    """The complete cognition event trace.

    ``CognitionRuntime.events`` is a ring buffer capped at ``MAX_EVENTS``
    (5000) and a threatened city turns it over quickly, so the tape drains the
    runtime once per game minute through ``GET_COGNITION(since_seq)`` and keeps
    everything. ``dropped`` records whether the ring lost rows between two
    drains (it never should at a one-minute drain interval).
    """

    def __init__(self, session):
        self.session = session
        self.events: List[dict] = []
        self.last_seq = 0
        self.dropped = 0
        self.drain()

    def drain(self) -> None:
        snap = self.session.handle({"cmd": Command.GET_COGNITION,
                                    "since_seq": self.last_seq})["cognition"]
        rows = snap["events"]
        if rows and rows[0]["seq"] > self.last_seq + 1:
            self.dropped += rows[0]["seq"] - self.last_seq - 1
        if rows:
            self.events.extend(rows)
            self.last_seq = rows[-1]["seq"]


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


def try_seed(session, w, seed_hour: float, cutoff_hour: float) -> Optional[dict]:
    """Seed the stressor if this game minute is the moment to do it.

    Returns the seeding row once seeded, else None. The moment is the first
    game minute at or after ``seed_hour`` in which any building has an open
    customer session; the busiest such building (ties by lowest id) is the
    shop and its lowest customer id is the index case. Past ``cutoff_hour``
    with no customer anywhere, the fallback pathogen is seeded with the
    data-driven index case.
    """
    hour = w.current_hour()
    if hour < seed_hour - 1e-9:
        return None
    by_b = customer_sessions(w)
    if by_b:
        bid = sorted(by_b.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
        cid = min(by_b[bid])
        r = session.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": PATHOGEN,
                            "citizen_id": int(cid)})
        if not r.get("ok"):
            raise RuntimeError(f"SEED_OUTBREAK failed: {r}")
        return {"pathogen": PATHOGEN, "building_id": int(bid), "citizen_id": int(cid),
                "index_case": r.get("index_case"), "hour": round(hour, 4), "fallback": False,
                "n_customer_sessions_there": len(by_b[bid]),
                "n_buildings_with_customers": len(by_b),
                "note": ("the busiest shop is the building with the most open customer work "
                         f"sessions at the first game minute at or after {seed_hour:.4f}h in "
                         "which any customer session exists; ties by lowest building id, index "
                         "case = lowest customer id there")}
    if hour >= cutoff_hour - 1e-9:
        r = session.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": FALLBACK_PATHOGEN})
        if not r.get("ok"):
            raise RuntimeError(f"SEED_OUTBREAK (fallback) failed: {r}")
        return {"pathogen": FALLBACK_PATHOGEN, "building_id": None, "citizen_id": None,
                "index_case": r.get("index_case"), "hour": round(hour, 4), "fallback": True,
                "note": (f"no customer work session existed anywhere between {seed_hour:.2f}h and "
                         f"{cutoff_hour:.2f}h, so the fallback was seeded: {FALLBACK_PATHOGEN} "
                         "with the data-driven index case")}
    return None


def run_day(session, w, end_hour: float, tape: Optional[EventTape] = None,
            seed_hour: float = SEED_HOUR, cutoff_hour: float = SEED_CUTOFF_HOUR,
            stop_hours_after_seed: Optional[float] = None) -> Tuple[float, Optional[dict], int]:
    """Advance in 60 s steps, seeding the stressor at its moment and draining
    the tape every game minute. Returns (advance seconds, seeding row, minutes).

    ``stop_hours_after_seed`` ends the run that many game hours after the
    seeding instead of at ``end_hour`` (the determinism replay).
    """
    spent = 0.0
    minutes = 0
    seeding: Optional[dict] = None
    stop_at = end_hour
    while w.current_hour() < stop_at - 1e-9:
        if seeding is None:
            seeding = try_seed(session, w, seed_hour, cutoff_hour)
            if seeding is not None and stop_hours_after_seed is not None:
                stop_at = min(end_hour, w.current_hour() + stop_hours_after_seed)
        t0 = time.perf_counter()
        w.advance_seconds(STEP_S)
        spent += time.perf_counter() - t0
        minutes += 1
        if tape is not None:
            tape.drain()
    return spent, seeding, minutes


# --------------------------------------------------------------------------- #
# what the citizens ended up holding
# --------------------------------------------------------------------------- #
def prior_relationships(w) -> Dict[Tuple[int, int], Tuple[float, ...]]:
    """The relationship state at boot: the household / workplace priors."""
    return {k: tuple(round(getattr(r, d), 6) for d in PRIOR_DIMS)
            for k, r in w.cognition.rels.rels.items()}


def memory_report(w) -> dict:
    c = w.cognition
    sizes = sorted(((len(s), cid) for cid, s in c.memories.items()), reverse=True)
    n_facts = sum(n for n, _ in sizes)
    kinds: Counter = Counter()
    sources: Counter = Counter()
    hops: Counter = Counter()
    for st in c.memories.values():
        for f in st.facts.values():
            kinds[f.kind] += 1
            sources[f.source] += 1
            hops[int(f.hops)] += 1
    return {"n_citizens_with_memory": len(sizes), "n_facts": n_facts,
            "max_facts_per_citizen": sizes[0][0] if sizes else 0,
            "max_facts_citizen_id": sizes[0][1] if sizes else None,
            "mean_facts_per_citizen": round(n_facts / max(1, len(sizes)), 2),
            "capacity": M.CAPACITY,
            "within_capacity": bool(not sizes or sizes[0][0] <= M.CAPACITY),
            "n_facts_forgotten": sum(s.forgotten for s in c.memories.values()),
            "fact_kinds": dict(kinds.most_common()),
            "fact_sources": dict(sorted(sources.items())),
            "fact_hops": {str(k): v for k, v in sorted(hops.items())}}


def relationship_report(w, priors: Dict[Tuple[int, int], Tuple[float, ...]]) -> dict:
    """How many pairs moved away from what the prior (or nothing) gave them."""
    c = w.cognition
    moved: List[Tuple[int, int]] = []
    moved_dims: Counter = Counter()
    new_pairs = 0
    for k, r in sorted(c.rels.rels.items()):
        now = tuple(round(getattr(r, d), 6) for d in PRIOR_DIMS)
        before = priors.get(k)
        if before is None:
            new_pairs += 1
            before = tuple(0.0 for _ in PRIOR_DIMS)
            if r.origin:
                continue          # a prior created after boot is still a prior, not experience
        if now != before:
            moved.append(k)
            for d, a, b in zip(PRIOR_DIMS, before, now):
                if a != b:
                    moved_dims[d] += 1
    origins = Counter(r.origin or "experience" for r in c.rels.rels.values())
    return {"n_relationships": len(c.rels.rels), "n_prior_relationships_at_boot": len(priors),
            "n_relationships_created_after_boot": new_pairs,
            "n_pairs_changed_from_prior": len(moved),
            "changed_dimensions": dict(sorted(moved_dims.items())),
            "pairs_changed_sample": [{"owner": a, "other": b} for a, b in moved[:10]],
            "origins": dict(sorted(origins.items())),
            "dimensions_tracked": list(PRIOR_DIMS), "all_dimensions": list(DIMS),
            "note": ("a pair counts as changed when familiarity / trust / affinity / obligation "
                     "differs from the value it held at boot (the household / workplace prior), "
                     "i.e. an event moved it; pairs that only ever received a prior do not count")}


def rumor_report(events: List[dict]) -> dict:
    shared = [e for e in events if e["event"] == "WARNING_SHARED"]
    per_sender: Counter = Counter()
    per_pair: Counter = Counter()
    per_origin: Counter = Counter()
    hops: List[int] = []
    for e in shared:
        per_sender[int(e["citizen_id"])] += 1
        per_pair[(int(e["citizen_id"]), int(e["recipient"]))] += 1
        per_origin[str(e.get("origin_id"))] += 1
        hops.append(int(e.get("hops", 0)))
    return {"n_warning_shared": len(shared),
            "n_warning_received": sum(1 for e in events if e["event"] == "WARNING_RECEIVED"),
            "n_senders": len(per_sender),
            "max_warning_shared_per_sender": max(per_sender.values()) if per_sender else 0,
            "max_warning_shared_per_pair": max(per_pair.values()) if per_pair else 0,
            "max_hops": max(hops) if hops else 0,
            "hop_histogram": {str(h): hops.count(h) for h in sorted(set(hops))},
            "n_origin_facts_in_circulation": len(per_origin),
            "max_tellings_per_origin_fact": max(per_origin.values()) if per_origin else 0,
            "note": ("hops is the depth stamped on the telling; the runtime refuses a third hop "
                     "(social.MAX_HOPS = 2), one telling of one origin fact per (sender, "
                     "recipient) pair ever, and one telling per pair per 30 minutes")}


def digest(w) -> dict:
    """A stable digest of every citizen's memory and every relationship."""
    c = w.cognition
    mem = [(cid, [(f.fact_id, f.kind, f.actor, f.target, f.building_id, f.room_id,
                   round(f.t, 3), f.source, f.source_citizen, f.origin_id, f.hops,
                   round(f.confidence, 6), f.count)
                  for _fid, f in sorted(c.memories[cid].facts.items())])
           for cid in sorted(c.memories)]
    rels = [(a, b, *[round(getattr(r, d), 6) for d in DIMS], r.interactions, r.origin)
            for (a, b), r in sorted(c.rels.rels.items())]
    avoid = [(cid, v.get("building_id")) for cid, v in sorted(c.avoid_goals.items())]

    def sha(obj) -> str:
        return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]

    return {"memories": sha(mem), "relationships": sha(rels), "avoid_goals": sha(avoid),
            "n_citizens_with_memory": len(mem), "n_facts": sum(len(v) for _, v in mem),
            "n_relationships": len(rels), "n_avoiding": len(avoid)}


def determinism_check(city: str, hours: float, seed: int = SEED,
                      seed_hour: float = SEED_HOUR) -> dict:
    """Two fresh worlds, each booted at 05:00, seeded by the same rule at the
    same game minute and advanced ``hours`` game hours past the seeding: the
    cognition event lists and the memory / relationship digests must match."""
    runs = []
    for _ in range(2):
        session, w = build_world(city, START_HOUR, seed)
        tape = EventTape(session)
        _spent, seeding, minutes = run_day(session, w, END_HOUR, tape, seed_hour,
                                           SEED_CUTOFF_HOUR, stop_hours_after_seed=hours)
        runs.append((tape.events, digest(w), seeding, minutes, round(w.current_hour(), 4)))
    a_ev, a_dig, a_seed, a_min, a_hour = runs[0]
    b_ev, b_dig, b_seed, b_min, b_hour = runs[1]
    identical = json.dumps(a_ev, sort_keys=True) == json.dumps(b_ev, sort_keys=True)
    first_diff = None
    if not identical:
        for i in range(max(len(a_ev), len(b_ev))):
            x = a_ev[i] if i < len(a_ev) else None
            y = b_ev[i] if i < len(b_ev) else None
            if json.dumps(x, sort_keys=True) != json.dumps(y, sort_keys=True):
                first_diff = {"i": i, "run1": x, "run2": y}
                break
    same_seeding = json.dumps(a_seed, sort_keys=True) == json.dumps(b_seed, sort_keys=True)
    return {"hours_after_seeding": hours, "n_events_run1": len(a_ev), "n_events_run2": len(b_ev),
            "events_identical": identical, "first_difference": first_diff,
            "digest_run1": a_dig, "digest_run2": b_dig, "digests_identical": a_dig == b_dig,
            "seeding_run1": a_seed, "seeding_run2": b_seed, "seeding_identical": same_seeding,
            "game_minutes_run1": a_min, "game_minutes_run2": b_min,
            "hour_after_run1": a_hour, "hour_after_run2": b_hour,
            "deterministic": bool(identical and a_dig == b_dig and same_seeding),
            "note": (f"two freshly built worlds booted at {START_HOUR:.0f}:00, each seeding the "
                     "stressor by the same rule at the same game minute and advancing "
                     f"{hours:.0f} further game hours; the full cognition event lists are "
                     "compared verbatim plus a digest of every fact of every citizen and every "
                     "relationship dimension")}


# --------------------------------------------------------------------------- #
# one city
# --------------------------------------------------------------------------- #
def smoke_city(city: str, start_hour: float = START_HOUR, end_hour: float = END_HOUR,
               det_hours: float = DETERMINISM_HOURS, seed: int = SEED,
               seed_hour: float = SEED_HOUR, verbose: bool = True) -> dict:
    out = {"city": city, "status": "FAIL", "reason": ""}
    try:
        bundle_dir = resolve_bundle_dir(city)
    except FileNotFoundError as exc:
        return {**out, "status": "INFO", "reason": str(exc)}
    out["bundle_dir"] = bundle_dir
    if not has_compiled_world(bundle_dir):
        return {**out, "status": "INFO",
                "reason": "no compiled world (world/spawn_anchors.json.gz absent) — "
                          "nothing to embody"}

    t0 = time.perf_counter()
    session, w = build_world(city, start_hour, seed)
    out["setup_s"] = round(time.perf_counter() - t0, 2)
    if w.mobility is None:
        return {**out, "status": "INFO",
                "reason": "no street graph in the bundle: mobility never started, so no "
                          "citizen is ever delivered into a building"}
    if w.cognition is None:
        return {**out, "status": "FAIL", "reason": "START_WORLD did not enable the cognition runtime"}

    out["n_citizens"] = len(w.mobility.execs)
    out["n_employed"] = len(w.work.employment) if w.work is not None else 0
    priors = prior_relationships(w)
    out["priors"] = {"n_pairs": len(priors),
                     "note": "household / workplace relationship priors, the only non-experience "
                             "source; everything else must be earned by an event"}
    if not out["n_employed"]:
        n_wp = len({int(r.work_building_id) for r in w.mobility.records.values()
                    if r.work_building_id is not None})
        out["status"] = "INFO"
        out["reason"] = (f"nobody is employed: none of the {out['n_citizens']} registered citizens "
                         f"has a workplace whose smart objects support a job role ({n_wp} "
                         "workplace(s) in the bundle), so no citizen is ever delivered to work "
                         "and there is nothing to perceive")
        if verbose:
            print(f"  {city}: INFO — {out['reason']}")
        return out

    # -- the day -----------------------------------------------------------
    tape = EventTape(session)
    t0 = time.perf_counter()
    advance_s, seeding, minutes = run_day(session, w, end_hour, tape, seed_hour, SEED_CUTOFF_HOUR)
    run_s = time.perf_counter() - t0
    events = tape.events
    c = w.cognition

    by_event = Counter(e["event"] for e in events)
    counts = dict(sorted(c.counts.items()))
    headline = ("MEMORY_CREATED", "RELATIONSHIP_CHANGED", "HELP_DECIDED", "HELP_COMPLETED",
                "WARNING_SHARED", "WARNING_RECEIVED", "AVOID_DECIDED", "AVOID_ROOM_DECIDED",
                "PERCEIVED", "TRUST_CHANGED")
    mem = memory_report(w)
    rels = relationship_report(w, priors)
    rumor = rumor_report(events)

    out.update({
        "start_hour": start_hour, "end_hour": end_hour, "step_s": STEP_S,
        "game_minutes": minutes, "run_s": round(run_s, 2),
        "ms_per_game_minute": round(advance_s * 1000.0 / minutes, 3),
        "ms_per_game_minute_with_instrumentation": round(run_s * 1000.0 / minutes, 3),
        "threat_seed": seeding,
        "n_events": len(events),
        "n_events_in_runtime_ring": len(c.events),
        "n_events_dropped_between_drains": tape.dropped,
        "counts": {k: int(counts.get(k, 0)) for k in headline},
        "counts_all": counts,
        "events_by_kind": dict(sorted(by_event.items())),
        "story_counts": {k: int(by_event.get(k, 0)) for k in STORY_EVENTS},
        "memory": mem, "relationships": rels, "rumor": rumor,
        "outbreak": (None if w.outbreak is None
                     else {"pathogen": w.outbreak.pathogen.name,
                           "counts": dict(sorted(w.outbreak.snapshot()["counts"].items()))}),
        "counts_note": ("`counts` are the runtime's persistent counters (every occurrence, "
                        "including the low-salience rows that are counted without emitting an "
                        "event); `story_counts` are the events actually emitted and drained"),
        "story": story_sample(events, start_hour),
    })

    # -- determinism -------------------------------------------------------
    t0 = time.perf_counter()
    det = determinism_check(city, det_hours, seed, seed_hour)
    det["repeat_s"] = round(time.perf_counter() - t0, 2)
    out["determinism"] = det

    reasons = []
    if not mem["n_facts"]:
        reasons.append("no citizen remembered anything all day")
    if not mem["within_capacity"]:
        reasons.append(f"citizen {mem['max_facts_citizen_id']} holds "
                       f"{mem['max_facts_per_citizen']} facts, over the capacity of {M.CAPACITY}")
    if not rels["n_pairs_changed_from_prior"]:
        reasons.append("no relationship moved away from its prior: nothing was earned by an event")
    n_social = sum(int(counts.get(k, 0)) for k in SOCIAL_ACTIONS)
    if not n_social:
        reasons.append("no social action all day (no HELP_DECIDED, WARNING_SHARED or "
                       "AVOID_DECIDED)")
    if not det["deterministic"]:
        reasons.append("the two replays diverged"
                       + ("" if det["events_identical"] else " (event lists differ)")
                       + ("" if det["seeding_identical"] else " (the stressor was seeded "
                                                              "differently)"))
    out["n_social_actions"] = n_social
    out["status"] = "FAIL" if reasons else "PASS"
    out["reason"] = "; ".join(reasons)
    if verbose:
        s = out["counts"]
        print(f"  {city}: {out['status']} ({out['n_citizens']} citizens, "
              f"{mem['n_citizens_with_memory']} with memory, {mem['n_facts']} facts, max "
              f"{mem['max_facts_per_citizen']}/citizen, {rels['n_relationships']} relationships "
              f"({rels['n_pairs_changed_from_prior']} moved), {s['WARNING_SHARED']} warnings, "
              f"{s['HELP_DECIDED']} help decisions, {s['AVOID_DECIDED']} avoidances, "
              f"{run_s:.0f} s run)")
        if out["reason"]:
            print(f"      reason: {out['reason']}")
    return out


def story_sample(events: List[dict], start_hour: float, per_kind: int = 30) -> List[dict]:
    """The first ``per_kind`` rows of each story event kind, in time order.

    A flat head of the trace would be all MEMORY_CREATED in a busy city; the
    per-kind cap keeps the rarer, more interesting kinds visible.
    """
    seen: Counter = Counter()
    out = []
    for e in events:
        kind = e["event"]
        if kind not in STORY_EVENTS or seen[kind] >= per_kind:
            continue
        seen[kind] += 1
        out.append({"hour": round(start_hour + e["t"] / 3600.0, 3),
                    **{k: v for k, v in e.items() if k not in ("seq", "t")}})
    return out


def print_table(results: dict) -> None:
    cols = [("city", 16), ("status", 6), ("cits", 5), ("empl", 5), ("mem", 5), ("facts", 6),
            ("max", 4), ("rels", 6), ("moved", 6), ("perc", 6), ("mcre", 6), ("rel+", 6),
            ("trust", 6), ("help", 5), ("done", 5), ("warn", 5), ("recv", 5), ("avoid", 5),
            ("avrm", 5), ("hops", 4), ("snd", 4), ("det", 4), ("ms/gm", 7)]
    print("")
    print("  ".join(n.ljust(w) for n, w in cols))
    print("  ".join("-" * w for _, w in cols))
    for city, r in results.items():
        if r["status"] == "INFO":
            vals = [city, "INFO"] + ["-"] * (len(cols) - 2)
        else:
            m, rl, ru, s, d = (r["memory"], r["relationships"], r["rumor"], r["counts"],
                               r["determinism"])
            vals = [city, r["status"], r["n_citizens"], r["n_employed"],
                    m["n_citizens_with_memory"], m["n_facts"], m["max_facts_per_citizen"],
                    rl["n_relationships"], rl["n_pairs_changed_from_prior"], s["PERCEIVED"],
                    s["MEMORY_CREATED"], s["RELATIONSHIP_CHANGED"], s["TRUST_CHANGED"],
                    s["HELP_DECIDED"], s["HELP_COMPLETED"], s["WARNING_SHARED"],
                    s["WARNING_RECEIVED"], s["AVOID_DECIDED"], s["AVOID_ROOM_DECIDED"],
                    ru["max_hops"], ru["max_warning_shared_per_sender"],
                    "ok" if d["deterministic"] else "DIFF", r["ms_per_game_minute"]]
        print("  ".join(str(v).ljust(w) for v, (_, w) in zip(vals, cols)))
    print("")
    for city, r in results.items():
        if r["status"] == "INFO":
            print(f"  {city} [INFO]: {r['reason']}")
            continue
        m, rl, ru = r["memory"], r["relationships"], r["rumor"]
        ts = r["threat_seed"] or {}
        print(f"  {city}: threat {ts.get('pathogen')} seeded on citizen {ts.get('citizen_id')} in "
              f"building {ts.get('building_id')} at {ts.get('hour')}h"
              + (" [FALLBACK]" if ts.get("fallback") else "")
              + f"; {m['n_facts']} facts over {m['n_citizens_with_memory']} citizens, max "
              f"{m['max_facts_per_citizen']} <= {m['capacity']} "
              f"({m['n_facts_forgotten']} forgotten); {rl['n_pairs_changed_from_prior']}/"
              f"{rl['n_relationships']} relationships moved {rl['changed_dimensions']}; "
              f"{r['n_social_actions']} social actions; rumor max hops {ru['max_hops']}, max "
              f"{ru['max_warning_shared_per_sender']} tellings per sender; determinism "
              f"{'ok' if r['determinism']['deterministic'] else 'DIVERGED'} "
              f"({r['determinism']['n_events_run1']} events)")
        if r["reason"]:
            print(f"  {city} [{r['status']}]: {r['reason']}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", default=None)
    ap.add_argument("--start-hour", type=float, default=START_HOUR)
    ap.add_argument("--end-hour", type=float, default=END_HOUR)
    ap.add_argument("--seed-hour", type=float, default=SEED_HOUR,
                    help="earliest hour at which the threat stressor may be seeded")
    ap.add_argument("--determinism-hours", type=float, default=DETERMINISM_HOURS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)
    cities = args.cities or DEFAULT_CITIES

    t_all = time.perf_counter()
    results: Dict[str, dict] = {}
    for city in cities:
        print(f"[{city}] ...")
        try:
            results[city] = smoke_city(city, start_hour=args.start_hour, end_hour=args.end_hour,
                                       det_hours=args.determinism_hours, seed=args.seed,
                                       seed_hour=args.seed_hour)
        except Exception as exc:                     # a crash is a FAIL, not a stack trace
            traceback.print_exc()
            results[city] = {"city": city, "status": "FAIL",
                             "reason": f"exception: {type(exc).__name__}: {exc}"}
    wall_s = time.perf_counter() - t_all

    doc = {"version": 1, "milestone": "ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1",
           "start_hour": args.start_hour, "end_hour": args.end_hour, "step_s": STEP_S,
           "seed_hour": args.seed_hour, "pathogen": PATHOGEN,
           "fallback_pathogen": FALLBACK_PATHOGEN,
           "determinism_hours_after_seeding": args.determinism_hours, "seed": args.seed,
           "memory_capacity": M.CAPACITY,
           "wall_s": round(wall_s, 1), "python": sys.version.split()[0],
           "pass_requires": ["memories accumulate (at least one fact held)",
                             "at least one relationship moved away from its prior "
                             "(changed by an event, not by a prior)",
                             "at least one social action (HELP_DECIDED or WARNING_SHARED or "
                             "AVOID_DECIDED)",
                             f"no citizen over the memory capacity of {M.CAPACITY} facts",
                             "identical cognition events and memory/relationship digests over "
                             "the determinism replay, including the same seeding minute"],
           "cities": results}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    print_table(results)
    print(f"  wall: {wall_s:.1f} s")
    print(f"  artifact: {args.out}")
    failed = [c for c, r in results.items() if r["status"] == "FAIL"]
    if failed:
        print(f"  FAIL: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Per-city smoke test for the smart-object / work runtime
(ASPHODEL_SMART_OBJECTS_WORK_V1).

For each requested city bundle: boot the world exactly as the game does
(bridge ``START_WORLD``, which enables mobility and the work runtime and
employs every citizen with a workplace), run one working day (05:00 -> 17:00
in 60 s steps) and report what the work runtime actually did:

    * employment: how many citizens got a job, the role histogram, how many
      workplaces have smart objects and how many registers / desks / shelves
      those workplaces offer (by capability, never by object name);
    * the day: CLOCK_IN, USE_START, STATE_CHANGE, SERVED, CUSTOMER_QUEUED,
      CUSTOMER_UNSERVED, RESERVATION_DENIED, WORK_INTERRUPTED, CLOCK_OUT, and
      how many distinct workers actually used at least one object;
    * the reservation invariants, checked every game minute: no exclusive
      object with two holders, no citizen holding two exclusive objects;
    * determinism: the city is built and run twice for the first 3 game hours
      and the two event lists (plus an executor-position and ledger digest)
      must be identical;
    * cost: wall time and milliseconds per game minute.

    PYTHONPATH=. python3 tools/work_city_smoke.py [city ...]

Status per city:
    PASS   somebody clocked in, used an object and changed its state, the
           reservation invariants held every game minute and the run was
           deterministic
    INFO   no compiled world in the bundle (nothing to embody), or no citizen
           in the bundle is employable (no workplace with usable objects)
    FAIL   nothing was used, an invariant broke, or the two runs diverged

Exit code is non-zero when any city FAILs.
Writes artifacts/smart_objects_work_v1/city_smoke.json.
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
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.bridge.worldfactory import resolve_bundle_dir           # noqa: E402

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio", "boulder"]
ARTIFACT = os.path.join(REPO, "artifacts", "smart_objects_work_v1", "city_smoke.json")

START_HOUR = 5.0
END_HOUR = 17.0
STEP_S = 60.0
DETERMINISM_HOURS = 3.0
SEED = 0

# the events that tell the story of a working day, in reading order
STORY_EVENTS = ("CLOCK_IN", "USE_START", "STATE_CHANGE", "SERVED", "CUSTOMER_QUEUED",
                "CUSTOMER_UNSERVED", "RESERVATION_DENIED", "WORK_INTERRUPTED", "CLOCK_OUT")
# what PASS requires to have happened at least once
REQUIRED_EVENTS = ("CLOCK_IN", "USE_START", "STATE_CHANGE")


def has_compiled_world(bundle_dir: str) -> bool:
    """A bundle is embodiable only if its compiled world carries spawn anchors."""
    return os.path.exists(os.path.join(bundle_dir, "world", "spawn_anchors.json.gz"))


def build_world(city: str, start_hour: float, seed: int = SEED):
    """World + mobility + work, exactly as the game boots one (START_WORLD
    enables the work runtime by default whenever mobility is on)."""
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = s.handle({"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
                  "start_hour": float(start_hour)})
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    return s.world


class EventTape:
    """The complete event trace.

    ``WorkRuntime.events`` is a ring buffer capped at ``MAX_EVENTS`` (5000) and
    a busy city turns it over in well under a game hour, so the tape drains the
    runtime once per game minute through ``World.work_snapshot(since_seq)`` and
    keeps everything. ``dropped`` records whether the ring lost rows between
    two drains (it never should at a one-minute drain interval).
    """

    def __init__(self, world):
        self.world = world
        self.events: List[dict] = []
        self.last_seq = 0
        self.dropped = 0
        self.drain()

    def drain(self) -> None:
        rows = self.world.work_snapshot(self.last_seq)["events"]
        if rows and rows[0]["seq"] > self.last_seq + 1:
            self.dropped += rows[0]["seq"] - self.last_seq - 1
        if rows:
            self.events.extend(rows)
            self.last_seq = rows[-1]["seq"]


class InvariantWatch:
    """The reservation ledger invariants, checked every game minute.

    * an exclusive object never has two holders;
    * a citizen never holds two exclusive objects;
    * a shared object never exceeds its capacity.
    """

    def __init__(self, world):
        self.world = world
        self.checks = 0
        self.violations: List[dict] = []

    def check(self, hour: float) -> None:
        wk = self.world.work
        self.checks += 1
        excl_by_citizen: Dict[int, List[str]] = {}
        for oid, holders in wk.ledger.holders.items():
            obj = self._object(oid)
            if obj is None:
                if len(self.violations) < 50:
                    self.violations.append({"hour": round(hour, 3), "object_id": oid,
                                            "kind": "unknown_object", "holders": list(holders)})
                continue
            if obj.exclusive and len(holders) > 1:
                self._add(hour, "exclusive_object_two_holders", oid, holders, obj)
            if not obj.exclusive and len(holders) > int(obj.capacity):
                self._add(hour, "shared_object_over_capacity", oid, holders, obj)
            if obj.exclusive:
                for cid in holders:
                    excl_by_citizen.setdefault(int(cid), []).append(oid)
        for cid, oids in excl_by_citizen.items():
            if len(oids) > 1:
                if len(self.violations) < 50:
                    self.violations.append({"hour": round(hour, 3), "kind": "citizen_two_exclusive",
                                            "citizen_id": cid, "objects": sorted(oids)})

    def _object(self, oid: str):
        try:
            bid = int(oid.split(":")[1])
        except (IndexError, ValueError):
            return None
        reg = self.world.work.registries.get(bid)
        return None if reg is None else reg.get(oid)

    def _add(self, hour: float, kind: str, oid: str, holders, obj) -> None:
        if len(self.violations) < 50:
            self.violations.append({"hour": round(hour, 3), "kind": kind, "object_id": oid,
                                    "object_kind": obj.kind, "capacity": obj.capacity,
                                    "exclusive": obj.exclusive, "holders": list(holders)})


def run_minutes(w, minutes: int, tape: Optional[EventTape] = None,
                watch: Optional[InvariantWatch] = None) -> float:
    """Advance ``minutes`` game minutes; returns the advance seconds only (the
    tape drain and the invariant check are instrumentation, not game cost)."""
    spent = 0.0
    for _ in range(minutes):
        t0 = time.perf_counter()
        w.advance_seconds(STEP_S)
        spent += time.perf_counter() - t0
        if tape is not None:
            tape.drain()
        if watch is not None:
            watch.check(w.current_hour())
    return spent


def employment_report(w) -> dict:
    wk = w.work
    roles = Counter(e.role for e in wk.employment.values())
    workplaces = sorted({int(e.workplace_id) for e in wk.employment.values()})
    return {"n_employed": len(wk.employment), "roles": dict(sorted(roles.items())),
            "n_workplaces_employing": len(workplaces),
            "n_registries_built": len(wk.registries)}


def object_census(w) -> dict:
    """Registers / desks / shelves across every workplace, by capability.

    Capability, never name: a register is anything with ``{station, transact}``,
    a desk anything with ``{station, desk_work}``, a shelf anything with
    ``{shelf}`` — whatever object kind composes those capabilities counts.
    """
    wk = w.work
    workplaces = sorted({int(e.workplace_id) for e in wk.employment.values()})
    registers = desks = shelves = objects = 0
    with_objects = 0
    kinds: Counter = Counter()
    for bid in workplaces:
        reg = wk.registry(bid)
        if len(reg):
            with_objects += 1
        objects += len(reg)
        registers += len(reg.with_caps("station", "transact"))
        desks += len(reg.with_caps("station", "desk_work"))
        shelves += len(reg.with_caps("shelf"))
        kinds.update(reg.counts())
    return {"n_workplaces": len(workplaces), "n_workplaces_with_objects": with_objects,
            "n_objects": objects, "registers": registers, "desks": desks, "shelves": shelves,
            "top_object_kinds": dict(kinds.most_common(10))}


def digest(w) -> dict:
    """A stable digest of executor positions and the whole ledger state."""
    pos = [(cid, round(ex.pos[0], 3), round(ex.pos[1], 3), ex.state.value, int(ex.building_id),
            str(ex.activity or "")) for cid, ex in sorted(w.mobility.execs.items())]
    led = w.work.ledger.to_state()
    sessions = [(cid, a.kind, a.role, a.phase, a.task_id, a.object_id, a.room_id)
                for cid, a in sorted(w.work.activities.items())]

    def sha(obj) -> str:
        return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]

    return {"executors": sha(pos), "ledger": sha(led), "sessions": sha(sessions),
            "n_execs": len(pos), "n_held_objects": len(led["holders"]),
            "n_sessions": len(sessions)}


def determinism_check(city: str, hours: float, seed: int = SEED) -> dict:
    """Two fresh worlds, run the same first ``hours`` game hours: the event
    lists and the position/ledger digests must be identical."""
    minutes = int(hours * 60.0)
    runs = []
    for _ in range(2):
        w = build_world(city, START_HOUR, seed)
        tape = EventTape(w)
        run_minutes(w, minutes, tape)
        runs.append((tape.events, digest(w)))
    a_ev, a_dig = runs[0]
    b_ev, b_dig = runs[1]
    identical = json.dumps(a_ev, sort_keys=True) == json.dumps(b_ev, sort_keys=True)
    first_diff = None
    if not identical:
        for i in range(max(len(a_ev), len(b_ev))):
            x = a_ev[i] if i < len(a_ev) else None
            y = b_ev[i] if i < len(b_ev) else None
            if json.dumps(x, sort_keys=True) != json.dumps(y, sort_keys=True):
                first_diff = {"i": i, "run1": x, "run2": y}
                break
    return {"hours": hours, "n_events_run1": len(a_ev), "n_events_run2": len(b_ev),
            "events_identical": identical, "first_difference": first_diff,
            "digest_run1": a_dig, "digest_run2": b_dig,
            "digests_identical": a_dig == b_dig,
            "deterministic": identical and a_dig == b_dig,
            "note": (f"two freshly built worlds advanced over {START_HOUR:.0f}:00-"
                     f"{START_HOUR + hours:.0f}:00; full event lists compared verbatim plus a "
                     "digest of every executor position/state and the whole reservation ledger")}


def smoke_city(city: str, start_hour: float = START_HOUR, end_hour: float = END_HOUR,
               det_hours: float = DETERMINISM_HOURS, seed: int = SEED,
               verbose: bool = True) -> dict:
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
    w = build_world(city, start_hour, seed)
    out["setup_s"] = round(time.perf_counter() - t0, 2)
    if w.mobility is None:
        return {**out, "status": "INFO",
                "reason": "no street graph in the bundle: mobility never started, so no "
                          "citizen is ever delivered into a building"}
    if w.work is None:
        return {**out, "status": "FAIL", "reason": "START_WORLD did not enable the work runtime"}

    out["n_citizens"] = len(w.mobility.execs)
    out["employment"] = employment_report(w)
    out["objects"] = object_census(w)
    if not out["employment"]["n_employed"]:
        n_wp = len({int(r.work_building_id) for r in w.mobility.records.values()
                    if r.work_building_id is not None})
        out["status"] = "INFO"
        out["reason"] = (f"nobody is employed: none of the {out['n_citizens']} registered "
                         f"citizens has a workplace whose smart objects support a job role "
                         f"({n_wp} workplace(s) in the bundle)")
        if verbose:
            print(f"  {city}: INFO — {out['reason']}")
        return out

    # -- the working day ---------------------------------------------------
    minutes = int((end_hour - start_hour) * 60.0)
    tape = EventTape(w)
    watch = InvariantWatch(w)
    watch.check(w.current_hour())
    t0 = time.perf_counter()
    advance_s = run_minutes(w, minutes, tape, watch)
    run_s = time.perf_counter() - t0
    events = tape.events

    by_kind = dict(sorted(w.work.counts.items()))
    clocked_in = {e["citizen_id"] for e in events
                  if e["event"] == "CLOCK_IN" and e.get("citizen_id") is not None}
    used = {e["citizen_id"] for e in events
            if e["event"] == "USE_START" and e.get("citizen_id") is not None}
    # a worker who was given a customer session at their own workplace: the
    # executor reports activity 'arrived' rather than 'work' in that window
    customer_at_own_workplace = sorted({
        e["citizen_id"] for e in events
        if e["event"] == "SESSION_START" and e.get("session") == "customer"
        and w.work.employment.get(e.get("citizen_id")) is not None
        and w.work.employment[e["citizen_id"]].workplace_id == e.get("building_id")})

    out.update({
        "start_hour": start_hour, "end_hour": end_hour, "step_s": STEP_S,
        "game_minutes": minutes,
        "run_s": round(run_s, 2),
        "ms_per_game_minute": round(advance_s * 1000.0 / minutes, 3),
        "ms_per_game_minute_with_instrumentation": round(run_s * 1000.0 / minutes, 3),
        "n_events": len(events),
        "n_events_in_runtime_ring": len(w.work.events),
        "n_events_dropped_between_drains": tape.dropped,
        "events_by_kind": by_kind,
        "story_counts": {k: int(by_kind.get(k, 0)) for k in STORY_EVENTS},
        "n_workers_clocked_in": len(clocked_in),
        "n_workers_used_an_object": len(clocked_in & used),
        "n_citizens_used_an_object": len(used),
        "invariants": {"checks": watch.checks, "n_violations": len(watch.violations),
                       "violations": watch.violations[:20],
                       "held_objects_now": len(w.work.ledger.holders),
                       "note": "checked once per game minute over the whole run"},
        "workplace_function": {
            "n_reduced_now": sum(1 for v in w.work.reduced.values() if v),
            "n_shift_log_rows": len(w.work.shift_log)},
        "worker_given_customer_session_at_own_workplace": {
            "n_citizens": len(customer_at_own_workplace),
            "citizen_ids": customer_at_own_workplace[:20],
            "note": ("informational, not a pass condition: WorkRuntime._session_kind "
                     "(smart/runtime.py:234-245) only opens a worker session while the "
                     "executor's activity is exactly 'work', so the 'arrived' window at the "
                     "workplace door opens a *customer* session instead")},
        "story": story_sample(events, start_hour),
    })

    # -- determinism -------------------------------------------------------
    t0 = time.perf_counter()
    det = determinism_check(city, det_hours, seed)
    det["repeat_s"] = round(time.perf_counter() - t0, 2)
    out["determinism"] = det

    reasons = []
    for k in REQUIRED_EVENTS:
        if not by_kind.get(k):
            reasons.append(f"no {k} event in the whole day")
    if watch.violations:
        v = watch.violations[0]
        reasons.append(f"reservation invariant broken ({len(watch.violations)} times), first: "
                       f"{v['kind']} at {v['hour']}h")
    if not det["deterministic"]:
        reasons.append(f"two runs of the first {det_hours:.0f} game hours diverged"
                       + ("" if det["events_identical"] else " (event lists differ)"))
    out["status"] = "FAIL" if reasons else "PASS"
    out["reason"] = "; ".join(reasons)
    if verbose:
        s = out["story_counts"]
        print(f"  {city}: {out['status']} ({out['n_citizens']} citizens, "
              f"{out['employment']['n_employed']} employed, {s['CLOCK_IN']} clock-ins, "
              f"{s['USE_START']} uses, {s['STATE_CHANGE']} state changes, "
              f"{len(events)} events, {run_s:.0f} s run)")
        if out["reason"]:
            print(f"      reason: {out['reason']}")
    return out


def story_sample(events: List[dict], start_hour: float, per_kind: int = 40) -> List[dict]:
    """The first ``per_kind`` rows of each story event kind, in time order.

    A flat head of the trace would be all RESERVATION_DENIED in a contended
    city; the per-kind cap keeps the rarer, more interesting kinds visible.
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
    cols = [("city", 16), ("status", 6), ("cits", 5), ("empl", 5), ("wp", 4), ("obj", 6),
            ("regs", 5), ("desks", 5), ("shelf", 5), ("clock", 5), ("uses", 6), ("state", 6),
            ("served", 6), ("queued", 6), ("unsrv", 6), ("denied", 6), ("intr", 5), ("out", 5),
            ("wrkrs", 5), ("inv", 4), ("det", 4), ("ms/gm", 7)]
    print("")
    print("  ".join(n.ljust(w) for n, w in cols))
    print("  ".join("-" * w for _, w in cols))
    for city, r in results.items():
        if r["status"] == "INFO":
            vals = [city, "INFO"] + ["-"] * (len(cols) - 2)
        else:
            e, o, s, d = r["employment"], r["objects"], r["story_counts"], r["determinism"]
            vals = [city, r["status"], r["n_citizens"], e["n_employed"],
                    o["n_workplaces_with_objects"], o["n_objects"], o["registers"], o["desks"],
                    o["shelves"], s["CLOCK_IN"], s["USE_START"], s["STATE_CHANGE"], s["SERVED"],
                    s["CUSTOMER_QUEUED"], s["CUSTOMER_UNSERVED"], s["RESERVATION_DENIED"],
                    s["WORK_INTERRUPTED"], s["CLOCK_OUT"], r["n_workers_used_an_object"],
                    "ok" if not r["invariants"]["n_violations"] else "BAD",
                    "ok" if d["deterministic"] else "DIFF", r["ms_per_game_minute"]]
        print("  ".join(str(v).ljust(w) for v, (_, w) in zip(vals, cols)))
    print("")
    for city, r in results.items():
        if r["status"] == "INFO":
            print(f"  {city} [INFO]: {r['reason']}")
            continue
        e = r["employment"]
        print(f"  {city}: {e['n_employed']} employed {e['roles']} across "
              f"{e['n_workplaces_employing']} workplaces; "
              f"{r['n_workers_used_an_object']}/{r['n_workers_clocked_in']} clocked-in workers "
              f"used an object; invariants checked {r['invariants']['checks']}x, "
              f"{r['invariants']['n_violations']} violations; determinism "
              f"{'ok' if r['determinism']['deterministic'] else 'DIVERGED'} over "
              f"{r['determinism']['hours']:.0f} h "
              f"({r['determinism']['n_events_run1']} events)")
        cw = r.get("worker_given_customer_session_at_own_workplace") or {}
        if cw.get("n_citizens"):
            print(f"      note: {cw['n_citizens']} employed citizens got a *customer* session "
                  f"at their own workplace (smart/runtime.py:234-245)")
        if r["reason"]:
            print(f"  {city} [{r['status']}]: {r['reason']}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", default=None)
    ap.add_argument("--start-hour", type=float, default=START_HOUR)
    ap.add_argument("--end-hour", type=float, default=END_HOUR)
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
                                       det_hours=args.determinism_hours, seed=args.seed)
        except Exception as exc:                     # a crash is a FAIL, not a stack trace
            traceback.print_exc()
            results[city] = {"city": city, "status": "FAIL",
                             "reason": f"exception: {type(exc).__name__}: {exc}"}
    wall_s = time.perf_counter() - t_all

    doc = {"version": 1, "milestone": "ASPHODEL_SMART_OBJECTS_WORK_V1",
           "start_hour": args.start_hour, "end_hour": args.end_hour, "step_s": STEP_S,
           "determinism_hours": args.determinism_hours, "seed": args.seed,
           "wall_s": round(wall_s, 1), "python": sys.version.split()[0],
           "pass_requires": ["at least one CLOCK_IN", "at least one USE_START",
                             "at least one STATE_CHANGE",
                             "no reservation invariant violation in any game minute",
                             "identical events and digests over the determinism replay"],
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

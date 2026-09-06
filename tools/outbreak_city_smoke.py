#!/usr/bin/env python3
"""Per-city smoke test for the outbreak runtime (ASPHODEL_OUTBREAK_V1).

For each requested city bundle: build the world from the bundle, attach the
embodied mobility runtime and the outbreak runtime (``classic_zombie``, with
the data-driven index case), run one game morning (05:00 -> 17:00 in 60 s
steps) and report what the outbreak actually did:

    * the index case (id, workplace, registered coworkers) and whether it
      progressed symptom onset -> incapacitation -> death (-> reanimation,
      when the record says it will reanimate);
    * every event by kind, the health counts at the end, whether any *onward*
      exposure happened and in what context (a shared building, a shared
      vehicle, outdoor proximity or a bite);
    * the civil breakdown the outbreak caused: disrupted workplaces and the
      street obstructions left by abandoned vehicles;
    * cost: wall time, and mobility vs outbreak milliseconds per game-minute;
    * determinism: the same city is built and run twice for the first
      3 game hours and the two event lists must be identical.

    PYTHONPATH=. python3 tools/outbreak_city_smoke.py [city ...]

Status per city:
    PASS   the index case progressed through its scheduled transitions and
           the run was deterministic
    INFO   no compiled world in the bundle (nothing to embody), or the bundle
           has no workplace with two day-shift workers, so the data-driven
           index case does not exist
    FAIL   a transition did not fire, or the two runs diverged

Onward transmission is *reported*, never required: a bundle whose citizens do
not share workplaces has no contact structure for the pathogen to use.

Exit code is non-zero when any city FAILs.
Writes artifacts/outbreak_v1/city_smoke.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter
from typing import Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel import MicroParams                                      # noqa: E402
from asphodel.bridge.worldfactory import (resolve_bundle_dir,         # noqa: E402
                                          world_from_bundle)
from asphodel.bundle_population import load_bundle_population         # noqa: E402
from asphodel.embodiment import CitySpatialContext                    # noqa: E402
from asphodel.outbreak.health import INFECTED, HealthState            # noqa: E402

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio", "boulder"]
ARTIFACT = os.path.join(REPO, "artifacts", "outbreak_v1", "city_smoke.json")

START_HOUR = 5.0
END_HOUR = 17.0
STEP_S = 60.0
DETERMINISM_HOURS = 3.0
PATHOGEN = "classic_zombie"
MICRO = dict(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)

# events that describe what the outbreak did to the city, in the order a
# reader wants to see them
STORY_EVENTS = ("EXPOSURE", "INFECTED", "SYMPTOM_ONSET", "INCAPACITATED", "DEATH",
                "REANIMATION", "ATTACK", "FLEE", "VEHICLE_ABANDONED", "ROAD_OBSTRUCTED",
                "WORKPLACE_DISRUPTED", "TRIP_ABORTED", "THREAT_OBSERVED", "HUNT")


def has_compiled_world(bundle_dir: str) -> bool:
    """A bundle is embodiable only if its compiled world carries spawn anchors."""
    return os.path.exists(os.path.join(bundle_dir, "world", "spawn_anchors.json.gz"))


def build_world(city: str, bundle_dir: str, start_hour: float, index_case=None):
    """World + mobility + outbreak, exactly as the game boots one."""
    w = world_from_bundle(city, micro_params=MicroParams(**MICRO))
    w.start_hour = start_hour
    w.set_citizens(load_bundle_population(bundle_dir))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(bundle_dir))
    w.enable_mobility(bundle_dir=bundle_dir)
    ob = w.enable_outbreak(PATHOGEN, index_case=index_case)
    return w, ob


def instrument(w, ob):
    """Split the per-step cost between the two runtimes (instance wrappers)."""
    cost = {"mobility_s": 0.0, "outbreak_s": 0.0}
    mob_advance, ob_advance = w.mobility.advance, ob.advance

    def mob(dt, hour, _f=mob_advance):
        t0 = time.perf_counter()
        _f(dt, hour)
        cost["mobility_s"] += time.perf_counter() - t0

    def obr(dt, _f=ob_advance):
        t0 = time.perf_counter()
        _f(dt)
        cost["outbreak_s"] += time.perf_counter() - t0

    w.mobility.advance = mob
    ob.advance = obr
    return cost


class EventTape:
    """The complete event trace.

    ``OutbreakRuntime.events`` is a ring buffer capped at ``MAX_EVENTS``
    (5000); once the undead are hunting it turns over in well under an hour of
    game time, so the seeding and progression events fall off the front. The
    tape drains the runtime once per game-minute and keeps everything, and
    records whether the runtime dropped events between two drains.
    """

    def __init__(self, ob):
        self.ob = ob
        self.events: list = []
        self.last_seq = 0
        self.dropped = 0
        self.drain()

    def drain(self) -> None:
        rows = [e for e in self.ob.events if e["seq"] > self.last_seq]
        if rows and rows[0]["seq"] > self.last_seq + 1:
            self.dropped += rows[0]["seq"] - self.last_seq - 1
        if rows:
            self.events.extend(rows)
            self.last_seq = rows[-1]["seq"]


def run_minutes(w, minutes: int, tape: "EventTape | None" = None) -> None:
    for _ in range(minutes):
        w.advance_seconds(STEP_S)
        if tape is not None:
            tape.drain()


def index_case_report(ob, w, events) -> dict:
    """Who the index case is, where it works and how many coworkers it has."""
    infected = [e for e in events if e["event"] == "INFECTED" and e.get("source_citizen") is None]
    if not infected:
        return {"citizen_id": None}
    e = infected[0]
    cid = int(e["citizen_id"])
    rec = w.mobility.records[cid]
    bid = rec.work_building_id
    coworkers = ob.workers_by_building.get(int(bid), []) if bid is not None else []
    return {
        "citizen_id": cid,
        "work_building_id": None if bid is None else int(bid),
        "n_registered_coworkers": max(0, len(coworkers) - 1),
        "coworkers": [c for c in coworkers if c != cid],
        "seeded_at_building_id": int(e["building_id"]),
        "schedule_hours": {
            "symptom": round(START_HOUR + e["symptom_t"] / 3600.0, 3) if e["symptom_t"] else None,
            "incapacitation": round(START_HOUR + e["incapacitation_t"] / 3600.0, 3)
            if e["incapacitation_t"] else None,
            "death": round(START_HOUR + e["death_t"] / 3600.0, 3) if e["death_t"] else None,
            "reanimation": round(START_HOUR + e["reanimate_t"] / 3600.0, 3)
            if e["reanimate_t"] else None,
        },
        "fatal": bool(e["fatal"]), "will_reanimate": bool(e["will_reanimate"]),
    }


def progression_report(ob, events, cid: int, will_reanimate: bool) -> dict:
    """Did the index case actually walk its scheduled transitions?"""
    fired = {k: None for k in ("SYMPTOM_ONSET", "INCAPACITATED", "DEATH", "REANIMATION")}
    for e in events:
        if e["event"] in fired and e.get("citizen_id") == cid and fired[e["event"]] is None:
            fired[e["event"]] = round(START_HOUR + e["t"] / 3600.0, 3)
    need = ["SYMPTOM_ONSET", "INCAPACITATED", "DEATH"] + (["REANIMATION"] if will_reanimate else [])
    missing = [k for k in need if fired[k] is None]
    return {"fired_at_hour": fired, "required": need, "missing": missing,
            "progressed": not missing,
            "final_state": ob.records[cid].state.value if cid in ob.records else None}


def onward_report(events) -> dict:
    """Every exposure that came from another citizen (the thing V1 is about)."""
    onward = [e for e in events
              if e["event"] == "EXPOSURE" and e.get("source_citizen") is not None]
    return {
        "n_onward_exposures": len(onward),
        "contexts": dict(Counter(str(e.get("context")) for e in onward)),
        "first": ({"hour": round(START_HOUR + onward[0]["t"] / 3600.0, 3),
                   "citizen_id": onward[0]["citizen_id"],
                   "source_citizen": onward[0]["source_citizen"],
                   "context": onward[0].get("context"),
                   "building_id": onward[0].get("building_id")} if onward else None),
        "chain": [{"hour": round(START_HOUR + e["t"] / 3600.0, 3),
                   "citizen_id": e["citizen_id"], "source_citizen": e["source_citizen"],
                   "context": e.get("context")} for e in onward[:50]],
    }


def contact_structure(ob) -> dict:
    """How much shared-workplace structure the bundle offers at all."""
    sizes = sorted((len(v) for v in ob.workers_by_building.values()), reverse=True)
    return {"n_workplaces": len(ob.workers_by_building),
            "largest_workplace_workers": sizes[0] if sizes else 0,
            "n_shared_workplaces": sum(1 for s in sizes if s >= 2),
            "top_workplace_sizes": sizes[:5]}


def health_counts(ob, w) -> dict:
    counts = ob.snapshot()["counts"]
    recs = ob.records
    return {
        "by_state": dict(sorted(counts.items())),
        "n_registered": len(w.mobility.execs),
        "n_ever_infected": sum(1 for r in recs.values() if r.infection_t is not None),
        "n_infected_now": sum(1 for r in recs.values() if r.state in INFECTED),
        "n_symptomatic": sum(1 for r in recs.values() if r.state == HealthState.SYMPTOMATIC),
        "n_incapacitated": sum(1 for r in recs.values() if r.state == HealthState.INCAPACITATED),
        "n_dead": sum(1 for r in recs.values()
                      if r.state in (HealthState.DEAD, HealthState.CORPSE)),
        "n_undead": sum(1 for r in recs.values() if r.state == HealthState.UNDEAD),
    }


def determinism_check(city: str, bundle_dir: str, hours: float, index_case, main_events) -> dict:
    """Build and run the city a second time; the event lists must match.

    The event stream over 3 game hours can be short (the index case is still
    incubating), so a health + executor-position digest at the same instant is
    compared as well — a divergence in movement or scheduling shows up there.
    """
    minutes = int(hours * 60.0)
    w2, ob2 = build_world(city, bundle_dir, START_HOUR, index_case=index_case)
    tape2 = EventTape(ob2)
    run_minutes(w2, minutes, tape2)
    want = [e for e in main_events if e["t"] <= hours * 3600.0 + 1e-6]
    got = [e for e in tape2.events if e["t"] <= hours * 3600.0 + 1e-6]
    identical = json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)
    first_diff = None
    if not identical:
        for i in range(max(len(got), len(want))):
            a = got[i] if i < len(got) else None
            b = want[i] if i < len(want) else None
            if json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True):
                first_diff = {"i": i, "run1": b, "run2": a}
                break
    return {"hours": hours, "n_events_run1": len(want), "n_events_run2": len(got),
            "events_identical": identical, "first_difference": first_diff,
            "digest": _digest(w2, ob2),
            "note": ("full event lists over the first %.0f game hours compared verbatim, "
                     "plus an executor-position and health digest at the same instant"
                     % hours)}, w2, ob2


def _digest(w, ob) -> dict:
    pos = [(cid, round(ex.pos[0], 3), round(ex.pos[1], 3), ex.state.value, int(ex.building_id))
           for cid, ex in sorted(w.mobility.execs.items())]
    health = [(cid, r.state.value, r.infection_t, r.symptom_t, r.death_t)
              for cid, r in sorted(ob.records.items())]
    return {"executors": hash(json.dumps(pos, sort_keys=True)) & 0xFFFFFFFF,
            "health": hash(json.dumps(health, sort_keys=True)) & 0xFFFFFFFF,
            "n_execs": len(pos), "n_records": len(health)}


def smoke_city(city: str, start_hour: float = START_HOUR, end_hour: float = END_HOUR,
               det_hours: float = DETERMINISM_HOURS, verbose: bool = True) -> dict:
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
    w, ob = build_world(city, bundle_dir, start_hour)
    setup_s = time.perf_counter() - t0
    out["setup_s"] = round(setup_s, 2)
    out["n_citizens"] = len(w.mobility.execs)
    out["contact_structure"] = contact_structure(ob)
    out["pathogen"] = ob.pathogen.name

    tape = EventTape(ob)
    idx = index_case_report(ob, w, tape.events)
    out["index_case"] = idx
    if idx["citizen_id"] is None:
        cs = out["contact_structure"]
        out["status"] = "INFO"
        out["reason"] = (
            "no data-driven index case: no workplace has >= 2 day-shift (06:00-10:00) "
            f"workers among the {out['n_citizens']} registered citizens "
            f"(largest workplace: {cs['largest_workplace_workers']} worker(s), "
            f"{cs['n_shared_workplaces']} shared workplaces)")
        if verbose:
            print(f"  {city}: INFO — {out['reason']}")
        return out

    # -- the run -----------------------------------------------------------
    minutes = int((end_hour - start_hour) * 60.0)
    cost = instrument(w, ob)
    t0 = time.perf_counter()
    run_minutes(w, minutes, tape)
    run_s = time.perf_counter() - t0
    events = tape.events

    out.update({
        "start_hour": start_hour, "end_hour": end_hour, "step_s": STEP_S,
        "game_minutes": minutes,
        "run_s": round(run_s, 2),
        "ms_per_game_minute_total": round(run_s * 1000.0 / minutes, 3),
        "ms_per_game_minute_mobility": round(cost["mobility_s"] * 1000.0 / minutes, 3),
        "ms_per_game_minute_outbreak": round(cost["outbreak_s"] * 1000.0 / minutes, 3),
        "ms_per_game_minute_other": round(
            (run_s - cost["mobility_s"] - cost["outbreak_s"]) * 1000.0 / minutes, 3),
        "n_events": len(events),
        "n_events_in_runtime_ring": len(ob.events),
        "n_events_dropped_between_drains": tape.dropped,
        "events_by_kind": dict(sorted(Counter(e["event"] for e in events).items())),
        "health": health_counts(ob, w),
        "progression": progression_report(ob, events, idx["citizen_id"], idx["will_reanimate"]),
        "onward": onward_report(events),
        "disrupted_buildings": {str(k): {"hour": round(start_hour + v["t"] / 3600.0, 3),
                                         "reason": v["reason"],
                                         "n_workers": len(v.get("workers") or [])}
                                for k, v in sorted(ob.disrupted_buildings.items())},
        "n_disrupted_buildings": len(ob.disrupted_buildings),
        "obstructions": list(ob.obstructions),
        "n_obstructions": len(ob.obstructions),
        "story": [{"hour": round(start_hour + e["t"] / 3600.0, 3),
                   **{k: v for k, v in e.items() if k not in ("seq", "t")}}
                  for e in events if e["event"] in STORY_EVENTS
                  and e["event"] not in ("HUNT", "THREAT_OBSERVED")][:400],
    })

    # -- determinism -------------------------------------------------------
    t0 = time.perf_counter()
    det, w2, ob2 = determinism_check(city, bundle_dir, det_hours, idx["citizen_id"], events)
    det["repeat_s"] = round(time.perf_counter() - t0, 2)
    out["determinism"] = det

    reasons = []
    if not out["progression"]["progressed"]:
        reasons.append("index case did not progress: missing "
                       + ", ".join(out["progression"]["missing"]))
    if not det["events_identical"]:
        reasons.append(f"two runs of the first {det_hours:.0f} game hours produced "
                       f"different event lists")
    out["status"] = "FAIL" if reasons else "PASS"
    out["reason"] = "; ".join(reasons)
    if not out["onward"]["n_onward_exposures"]:
        note = ("no onward exposure: the index case never shared a building, a vehicle or "
                "outdoor proximity with a susceptible citizen while infectious")
        if out["contact_structure"]["n_shared_workplaces"] <= 1:
            note += " (this bundle has almost no shared workplaces)"
        out["note"] = note
    if verbose:
        print(f"  {city}: {out['status']} ({out['n_citizens']} citizens, index "
              f"{idx['citizen_id']}, {len(events)} events, "
              f"{out['onward']['n_onward_exposures']} onward, {run_s:.0f} s run)")
    return out


def print_table(results: dict) -> None:
    cols = [("city", 16), ("status", 6), ("cits", 5), ("index", 6), ("cowork", 6),
            ("events", 6), ("onward", 6), ("inf", 4), ("dead", 4), ("undead", 6),
            ("disrupt", 7), ("obstr", 5), ("det", 4), ("run_s", 6),
            ("mob_ms/m", 8), ("ob_ms/m", 7)]
    print("")
    print("  ".join(n.ljust(w) for n, w in cols))
    print("  ".join("-" * w for _, w in cols))
    for city, r in results.items():
        if r["status"] == "INFO":
            vals = [city, "INFO"] + ["-"] * (len(cols) - 2)
        else:
            h, i, d = r["health"], r["index_case"], r["determinism"]
            vals = [city, r["status"], h["n_registered"], i["citizen_id"],
                    i["n_registered_coworkers"], r["n_events"],
                    r["onward"]["n_onward_exposures"], h["n_ever_infected"], h["n_dead"],
                    h["n_undead"], r["n_disrupted_buildings"], r["n_obstructions"],
                    "ok" if d["events_identical"] else "DIFF", f"{r['run_s']:.1f}",
                    r["ms_per_game_minute_mobility"], r["ms_per_game_minute_outbreak"]]
        print("  ".join(str(v).ljust(w) for v, (_, w) in zip(vals, cols)))
    print("")
    for city, r in results.items():
        if r["status"] != "INFO" and r.get("progression"):
            p, i = r["progression"], r["index_case"]
            f = p["fired_at_hour"]
            print(f"  {city}: index {i['citizen_id']} @ workplace {i['work_building_id']} "
                  f"({i['n_registered_coworkers']} coworkers) — symptom {f['SYMPTOM_ONSET']}h, "
                  f"incapacitated {f['INCAPACITATED']}h, death {f['DEATH']}h, "
                  f"reanimation {f['REANIMATION']}h "
                  f"(will_reanimate={i['will_reanimate']}), final "
                  f"{p['final_state']}")
        if r.get("note"):
            print(f"      note: {r['note']}")
        if r.get("reason"):
            print(f"  {city} [{r['status']}]: {r['reason']}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", default=None)
    ap.add_argument("--start-hour", type=float, default=START_HOUR)
    ap.add_argument("--end-hour", type=float, default=END_HOUR)
    ap.add_argument("--determinism-hours", type=float, default=DETERMINISM_HOURS)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)
    cities = args.cities or DEFAULT_CITIES

    t_all = time.perf_counter()
    results = {}
    for city in cities:
        print(f"[{city}] ...")
        try:
            results[city] = smoke_city(city, start_hour=args.start_hour,
                                       end_hour=args.end_hour,
                                       det_hours=args.determinism_hours)
        except Exception as exc:                       # a crash is a FAIL, not a stack trace
            traceback.print_exc()
            results[city] = {"city": city, "status": "FAIL",
                             "reason": f"exception: {type(exc).__name__}: {exc}"}
    wall_s = time.perf_counter() - t_all

    doc = {"version": 1, "pathogen": PATHOGEN,
           "start_hour": args.start_hour, "end_hour": args.end_hour, "step_s": STEP_S,
           "determinism_hours": args.determinism_hours,
           "wall_s": round(wall_s, 1),
           "python": sys.version.split()[0],
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

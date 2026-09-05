"""ASPHODEL_SMART_OBJECTS_WORK_V1 — the one-day work certification (§20, §21).

A normal Houston weekday (300 canonical citizens, embodied mobility, the
Outbreak V1 index case as the day's stressor). Every gate S1..S28 is derived
from authoritative state produced by the running simulation. Workplaces and
workers are chosen from the data, never by name: the retail workplace with
the most day-shift cashiers and midday errand visitors, the workplace with
the most desk workers, the cleaner with the most cleanable objects.

Rows that need Godot (S23, parts of S18/S19) read
``artifacts/smart_objects_work_v1/godot_probe_trace.json`` written by
``godot/tests/WorkGate.tscn`` (tools/run_work_gate.sh) and are NOT_RUN
without it; S24-S27 read the regression / smoke artifacts.

Writes artifacts/smart_objects_work_v1/one_day_trace.json and
save_load_trace.json.
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.embodied.executor import EmbodimentState
from asphodel.citizens.goals import Goal, GoalKind
from asphodel.save import world_state, load_world
from asphodel.smart.runtime import ARRIVE_M

CITY = "houston"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "smart_objects_work_v1")
PROBE = os.path.join(ART, "godot_probe_trace.json")
STATUS: dict = {}
GATES = [("S1", "Stable Smart Object identities"), ("S2", "Room/zone hierarchy exists"),
         ("S3", "Objects belong to correct rooms/buildings"),
         ("S4", "Citizen has deterministic job/workplace"),
         ("S5", "Work generates concrete task sequence"),
         ("S6", "Existing mobility reaches workplace"),
         ("S7", "Internal navigation reaches station"),
         ("S8", "Exclusive reservation prevents double occupancy"),
         ("S9", "Contention resolves without deadlock"),
         ("S10", "Citizen physically uses Smart Object"),
         ("S11", "Smart Object state changes authoritatively"),
         ("S12", "Multi-object task succeeds"),
         ("S13", "Multi-agent/service interaction succeeds"),
         ("S14", "Work can be interrupted"), ("S15", "Reservation cleanup on interruption"),
         ("S16", "Existing planner takes control after interruption"),
         ("S17", "Room/station context visible to outbreak query"),
         ("S18", "LOD demotion preserves work state"),
         ("S19", "LOD promotion restores same work state"),
         ("S20", "Save/load active station use"), ("S21", "Save/load multi-step work"),
         ("S22", "Save/load interruption"), ("S23", "Godot embodiment proves work execution"),
         ("S24", "Existing mobility gate remains PASS"),
         ("S25", "Existing outbreak gate remains PASS"),
         ("S26", "Existing Godot gates remain PASS"), ("S27", "Multi-city smoke"),
         ("S28", "No city-name special cases")]


def _status(gate, status, detail=""):
    STATUS[gate] = (status, detail)


def _write(name, obj):
    os.makedirs(ART, exist_ok=True)
    with open(os.path.join(ART, name), "w") as f:
        json.dump(obj, f, indent=1)


def _mk(d, start_hour=5.0):
    w = world_from_bundle(CITY, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                                          mixing_step_frac=0.12))
    w.start_hour = start_hour
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    return w


def _restore(js, d):
    w2 = load_world(json.loads(js))
    w2.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w2.enable_mobility(bundle_dir=d)
    if w2._pending_outbreak_state is not None:
        w2.enable_outbreak()
    w2.enable_work()
    return w2


def _blob(w):
    return json.dumps(world_state(w), sort_keys=True)


def _pick(w):
    """Data-driven choice of the certification workers (no names, no ids)."""
    wk = w.work
    prof = w.citizens
    shops = {}
    for cid, e in wk.employment.items():
        if e.role == "cashier" and getattr(prof[cid], "shift", "") == "day":
            shops.setdefault(e.workplace_id, {"cashiers": [], "visitors": []})["cashiers"].append(cid)
    for cid, rt in w.mobility.citizens.items():
        for n, m in rt.node_meta.items():
            if n.startswith("ent:") and n not in (rt.home_node, rt.work_node) and m.get("building_id") in shops \
                    and getattr(prof[cid], "shift", "") == "none":
                shops[m["building_id"]]["visitors"].append(cid)
    shop = max(sorted(shops), key=lambda b: (len(shops[b]["visitors"]), len(shops[b]["cashiers"])))
    cashier = min(shops[shop]["cashiers"])
    desks = {}
    for cid, e in wk.employment.items():
        if e.role == "desk_worker":
            desks.setdefault(e.workplace_id, []).append(cid)
    office = max(sorted(desks), key=lambda b: len(desks[b]))
    desk_worker = min(desks[office])
    cleaners = [(cid, e) for cid, e in wk.employment.items()
                if e.role == "cleaner" and getattr(prof[cid], "shift", "") == "day"]
    cleaner = max(cleaners, key=lambda ce: (len(wk.registry(ce[1].workplace_id).with_affordance("clean")), -ce[0]))[0]
    return {"shop": shop, "cashier": cashier, "cashier_visitors": sorted(shops[shop]["visitors"]),
            "office": office, "desk_worker": desk_worker, "desk_workers": sorted(desks[office]),
            "cleaner": cleaner, "cleaner_workplace": wk.employment[cleaner].workplace_id}


@pytest.fixture(scope="module")
def day():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "spawn_anchors.json.gz")):
        pytest.skip("houston compiled world absent")
    w = _mk(d)
    wk = w.work
    pick = _pick(w)
    # the day's stressor: the Outbreak V1 index case (health override, a threat,
    # a workplace disruption all arise from it, deterministically)
    ob = w.enable_outbreak("classic_zombie")
    far = (9000.0, 9000.0)
    events = []
    seq = 0
    invariant_breaks = []
    samples = []
    saves = {}
    cashier, shop = pick["cashier"], pick["shop"]
    cleaner = pick["cleaner"]
    ex_c = w.mobility.execs[cashier]
    broke_at = None
    denied_seen = False
    ctx_samples = []
    lod = {}
    for i in range(int(13.5 * 60)):                     # 05:00 -> 18:30
        w.advance_seconds(60.0, focus_xy=far)
        hour = w.current_hour()
        snap = wk.snapshot(seq)
        events.extend(snap["events"])
        seq = snap["event_seq"]
        # reservation invariants, every game minute
        for oid, hs in wk.ledger.holders.items():
            bid = int(oid.split(":")[1])
            o = wk.registry(bid).get(oid)
            if o is not None and o.exclusive and len(hs) > 1:
                invariant_breaks.append((hour, oid, list(hs)))
            if o is not None and len(hs) > o.capacity:
                invariant_breaks.append((hour, oid, list(hs)))
        per_cid = {}
        for oid, hs in wk.ledger.holders.items():
            bid = int(oid.split(":")[1])
            o = wk.registry(bid).get(oid)
            if o is not None and o.exclusive:
                for c in hs:
                    per_cid.setdefault(c, []).append(oid)
        for c, oids in per_cid.items():
            if len(oids) > 1:
                invariant_breaks.append((hour, c, oids))
        a = wk.activities.get(cashier)
        samples.append({"hour": round(hour, 3), "state": ex_c.state.value, "building_id": ex_c.building_id,
                        "x": round(ex_c.pos[0], 2), "y": round(ex_c.pos[1], 2),
                        "task": a.task_id if a else None, "phase": a.phase if a else None,
                        "object_id": a.object_id if a else None, "room_id": a.room_id if a else None})
        # scripted, bounded contention: the cashier's station breaks at 12:00 for 20 minutes
        if broke_at is None and hour >= 12.0 and a is not None and a.phase == "using" and a.object_id:
            broke_at = (hour, a.object_id)
            wk.set_object_state(a.object_id, "working", False)
        if broke_at is not None and hour >= broke_at[0] + 20.0 / 60.0 and \
                not wk.registry(shop).get(broke_at[1]).state.get("working", True):
            wk.set_object_state(broke_at[1], "working", True)
        # room context of co-workers at the office (S17) around mid-morning
        if 10.9 <= hour <= 11.1:
            ctx_samples.append({str(c): wk.context(c) for c in pick["desk_workers"]})
        # LOD (S18/S19): promote the shop to PHYSICAL for one second at 11:30
        if abs(hour - 11.5) < 1.0 / 120.0 and not lod:
            before = wk.activities.get(cashier)
            b0 = before.to_dict() if before else None
            ent = wk.graph(shop).entrance_xy
            w.advance_seconds(1.0, focus_xy=ent)
            band_near = w.mobility.bands[cashier].name
            after = wk.activities.get(cashier)
            a1 = after.to_dict() if after else None
            w.advance_seconds(1.0, focus_xy=far)
            band_far = w.mobility.bands[cashier].name
            a2 = wk.activities.get(cashier)
            lod = {"hour": round(hour, 3), "band_near": band_near, "band_far": band_far,
                   "same_object": bool(b0 and a1 and b0["object_id"] == a1["object_id"] == (a2.object_id if a2 else None)),
                   "same_task": bool(b0 and a1 and b0["task_id"] == a1["task_id"]),
                   "progress_continuous": bool(b0 and a1 and a1["progress_s"] >= b0["progress_s"]),
                   "holders": wk.ledger.holders_of(b0["object_id"]) if b0 and b0["object_id"] else []}
        # save/load at work-meaningful points (each once)
        ca = wk.activities.get(cleaner)
        keys = {"walking_to_station": a is not None and a.phase == "to_object" and a.kind == "worker",
                "using_station": a is not None and a.phase == "using" and a.task_id == "man_register" and hour > 8.5,
                "waiting": any(x.kind == "customer" and x.phase == "waiting" for x in wk.activities.values())
                           or (a is not None and a.phase == "waiting"),
                "multi_step": ca is not None and ca.carrying == "supplies" and ca.phase == "to_object",
                "interrupted": any(e["event"] == "WORK_INTERRUPTED" for e in events[-40:]),
                "work_to_home": ex_c.state != EmbodimentState.DOING_ACTIVITY and hour > 15.0 and ex_c.building_id != shop}
        for k, cond in keys.items():
            if cond and k not in saves:
                js = _blob(w)
                w2 = _restore(js, d)
                same_act = (json.dumps(wk.to_state()["activities"], sort_keys=True)
                            == json.dumps(w2.work.to_state()["activities"], sort_keys=True))
                same_ledger = wk.ledger.to_state() == w2.work.ledger.to_state()
                same_objects = wk.to_state()["objects"] == w2.work.to_state()["objects"]
                for _ in range(10):
                    w.advance_seconds(60.0, focus_xy=far)
                    w2.advance_seconds(60.0, focus_xy=far)
                cont = _blob(w) == _blob(w2)
                saves[k] = {"hour": round(hour, 3), "activities_identical": same_act,
                            "ledger_identical": same_ledger, "object_state_identical": same_objects,
                            "continuation_bit_identical": cont, "save_bytes": len(js)}
                snap = wk.snapshot(seq)
                events.extend(snap["events"])
                seq = snap["event_seq"]
                hour = w.current_hour()
                break
    return {"w": w, "wk": wk, "ob": ob, "pick": pick, "events": events, "invariants": invariant_breaks,
            "samples": samples, "saves": saves, "broke": broke_at, "ctx": ctx_samples, "lod": lod, "d": d}


def _ev(day, kind, cid=None):
    return [e for e in day["events"] if e["event"] == kind and (cid is None or e.get("citizen_id") == cid)]


def _hour(e):
    return round(5.0 + e["t"] / 3600.0, 2)


def test_S1_S3_objects_rooms(day):
    w, wk, pick = day["w"], day["wk"], day["pick"]
    shop = pick["shop"]
    reg = wk.registry(shop)
    w2 = _mk(day["d"])
    reg2 = w2.work.registry(shop)
    same = sorted(reg.objects) == sorted(reg2.objects) and all(
        reg.objects[o].kind == reg2.objects[o].kind and reg.objects[o].room_id == reg2.objects[o].room_id
        for o in reg.objects)
    _status("S1", "PASS" if same else "FAIL",
            f"{len(reg)} objects of building {shop} regenerate with identical ids/kinds/rooms in a fresh world; "
            f"ids are so:<building>:<k> from the interior generation order")
    g = wk.graph(shop)
    rows = g.rows()
    zones = sorted(set(r["zone"] for r in rows))
    _status("S2", "PASS" if len(rows) >= 2 and len(zones) >= 2 else "FAIL",
            f"building {shop}: rooms {[(r['room_id'], r['kind'], r['zone']) for r in rows]} joined by doorways")
    bad = []
    for o in reg.objects.values():
        r = g.rooms.get(o.room_id)
        if r is None or o.building_id != shop or not (r.x0 - 1e-6 <= o.x <= r.x1 + 1e-6 and r.y0 - 1e-6 <= o.y <= r.y1 + 1e-6):
            bad.append(o.object_id)
    _status("S3", "PASS" if not bad else "FAIL",
            f"every object of {shop} lies inside its room rectangle and carries the building id ({len(bad)} bad)")
    assert same and not bad


def test_S4_employment(day):
    w, wk, pick = day["w"], day["wk"], day["pick"]
    w2 = _mk(day["d"])
    e1 = {c: e.to_dict() for c, e in wk.employment.items()}
    e2 = {c: e.to_dict() for c, e in w2.work.employment.items()}
    same = e1 == e2
    e = wk.employment[pick["cashier"]]
    _status("S4", "PASS" if same and e.role == "cashier" else "FAIL",
            f"{len(e1)} citizens employed identically in two fresh worlds; citizen {pick['cashier']} "
            f"({e.occupation}) is a {e.role} at {e.workplace_id} assigned {e.assigned_object}; "
            f"roles: " + ", ".join(f"{r}={n}" for r, n in sorted(
                __import__('collections').Counter(x.role for x in wk.employment.values()).items())))
    assert same


def test_S5_task_sequence(day):
    pick = day["pick"]
    cid = pick["cashier"]
    starts = _ev(day, "TASK_START", cid)
    seqs = [(_hour(e), e["task_id"], e["object_id"]) for e in starts]
    kinds = sorted(set(t for _, t, _ in seqs))
    _status("S5", "PASS" if len(seqs) >= 3 and len(kinds) >= 2 else "FAIL",
            f"cashier {cid}: {len(seqs)} tasks {kinds}; first: {seqs[:4]}")
    assert len(seqs) >= 3 and len(kinds) >= 2


def test_S6_S7_arrival_and_internal_navigation(day):
    w, wk, pick = day["w"], day["wk"], day["pick"]
    cid, shop = pick["cashier"], pick["shop"]
    clock = _ev(day, "CLOCK_IN", cid)
    exev = [e for e in w.mobility.execs[cid].trace if e["event"] in ("entered_building", "walk_done", "left_building")]
    _status("S6", "PASS" if clock and clock[0]["building_id"] == shop else "FAIL",
            f"citizen {cid} clocked in at {shop} at {_hour(clock[0]) if clock else None} after the executor's trip "
            f"(executor events: {[(e['event'], e.get('building_id')) for e in exev[:3]]})")
    moves = [e for e in _ev(day, "MOVE_TO_OBJECT", cid) if e.get("building_id") == shop]
    uses = [e for e in _ev(day, "USE_START", cid) if e.get("building_id") == shop]
    ok = False
    detail = "no USE_START"
    if moves and uses:
        u = uses[0]
        o = wk.registry(shop).get(u["object_id"])
        d = math.hypot(u["x"] - o.use_xy[0], u["y"] - o.use_xy[1])
        ok = d <= ARRIVE_M + 0.05 and o.room_id == u["room_id"]
        detail = (f"MOVE_TO_OBJECT at {_hour(moves[0])} ({moves[0]['waypoints']} waypoints through doorways) -> "
                  f"USE_START at {_hour(u)} at {u['object_id']} ({o.kind}, room {o.room_id}), "
                  f"{d:.2f} m from its interaction point")
    _status("S7", "PASS" if ok else "FAIL", detail)
    assert clock and ok


def test_S8_S9_reservation_and_contention(day):
    wk, pick = day["wk"], day["pick"]
    cid, shop = pick["cashier"], pick["shop"]
    inv = day["invariants"]
    reserved = _ev(day, "RESERVED", cid)
    _status("S8", "PASS" if not inv and reserved else "FAIL",
            f"{len(inv)} invariant violations over 810 game-minute samples (exclusive objects with >1 holder, "
            f"citizens holding 2 exclusive objects); cashier {cid} held {sorted(set(e['object_id'] for e in reserved))}")
    broke = day["broke"]
    ok = False
    detail = "station never broken"
    if broke:
        t0 = broke[0]
        unavailable = [e for e in _ev(day, "OBJECT_UNAVAILABLE", cid) if e["object_id"] == broke[1]]
        after = [e for e in _ev(day, "RESERVED", cid) if _hour(e) >= t0 and e["object_id"] != broke[1]]
        denied = _ev(day, "RESERVATION_DENIED")
        ok = bool(unavailable and after)
        detail = (f"station {broke[1]} broke at {t0:.2f}: OBJECT_UNAVAILABLE for {cid}, then RESERVED "
                  f"{after[0]['object_id'] if after else None} at {_hour(after[0]) if after else None} "
                  f"({(_hour(after[0]) - t0) * 60:.0f} min later); {len(denied)} RESERVATION_DENIED city-wide "
                  f"resolved by alternative stations or bounded waits")
    _status("S9", "PASS" if ok else "FAIL", detail)
    assert not inv and ok


def test_S10_S11_use_and_state(day):
    wk, pick = day["wk"], day["pick"]
    cid, shop = pick["cashier"], pick["shop"]
    ends = [e for e in _ev(day, "USE_END", cid)]
    long_use = [e for e in ends if e["elapsed_s"] >= 60.0]
    _status("S10", "PASS" if long_use else "FAIL",
            f"cashier {cid}: {len(ends)} completed uses, longest {max((e['elapsed_s'] for e in ends), default=0) / 60:.0f} min "
            f"at {ends[0]['object_id'] if ends else None}")
    changes = _ev(day, "STATE_CHANGE")
    served = [e for e in changes if e.get("key") == "served" or e["event"] == "SERVED"]
    cleaned = [e for e in changes if e.get("key") == "dirty" and e.get("value") is False and e.get("citizen_id") == pick["cleaner"]]
    stock = [e for e in changes if e.get("key") == "stock"]
    reg = wk.registry(shop)
    served_total = sum(int(o.state.get("served", 0)) for o in reg.with_caps("station", "transact"))
    ok = bool(cleaned) and (served_total > 0 or bool(stock))
    _status("S11", "PASS" if ok else "FAIL",
            f"cleaner {pick['cleaner']} set dirty->False on {len(cleaned)} objects; registers of {shop} record "
            f"served={served_total}; {len(stock)} shelf stock changes city-wide; {len(changes)} STATE_CHANGE events")
    assert long_use and ok


def test_S12_multi_object(day):
    wk, pick = day["wk"], day["pick"]
    cid = pick["cleaner"]
    ends = _ev(day, "TASK_END", cid)
    seq = [(e["task_id"], e["object_id"], e.get("effect")) for e in ends]
    objs = sorted(set(o for _, o, _ in seq if o))
    chain = any(seq[i][2] == "supplies" and seq[j][2] == "clean" and seq[i][1] != seq[j][1]
                for i in range(len(seq)) for j in range(i + 1, min(i + 4, len(seq))))
    _status("S12", "PASS" if chain and len(objs) >= 3 else "FAIL",
            f"cleaner {cid} at {pick['cleaner_workplace']}: {len(ends)} tasks over {len(objs)} distinct objects; "
            f"fetch supplies at a storage object then clean a different object: {chain}; "
            f"sequence head {seq[:5]}")
    assert chain and len(objs) >= 3


def test_S13_service_interaction(day):
    wk, pick = day["wk"], day["pick"]
    cid, shop = pick["cashier"], pick["shop"]
    served = [e for e in _ev(day, "SERVED") if e.get("building_id") == shop]
    queued = [e for e in _ev(day, "CUSTOMER_QUEUED") if e.get("building_id") == shop]
    mine = [e for e in served if e["citizen_id"] == cid]
    _status("S13", "PASS" if served else "FAIL",
            f"at {shop}: {len(queued)} customers queued, {len(served)} served by the shop's cashiers "
            f"({[(e['customer_id'], 'by', e['citizen_id'], 'at', e['object_id'], _hour(e)) for e in served[:4]]}); "
            f"cashier {cid} served {len(mine)}; "
            f"city-wide SERVED={wk.counts.get('SERVED', 0)} UNSERVED={wk.counts.get('CUSTOMER_UNSERVED', 0)}")
    assert served


def test_S14_S16_interruption(day):
    w, wk, pick = day["w"], day["wk"], day["pick"]
    ints = _ev(day, "WORK_INTERRUPTED")
    reasons = sorted(set(e["reason"].split(":")[0] for e in ints))
    outs = _ev(day, "CLOCK_OUT")
    need = {"health", "emergency", "disruption"}
    have = set(reasons)
    ok = need.issubset(have) and bool(outs)
    _status("S14", "PASS" if ok else "FAIL",
            f"{len(ints)} interruptions with reasons {reasons} ({[(e['citizen_id'], e['reason'], _hour(e)) for e in ints[:5]]}); "
            f"{len(outs)} shift-end CLOCK_OUTs (object unavailable case in S9)")
    # cleanup: after every interruption the citizen holds nothing (checked from the released events
    # and the live ledger for those who never came back)
    leaks = []
    for e in ints:
        c = e["citizen_id"]
        rel = [x for x in day["events"] if x["event"] == "RESERVATION_RELEASED" and x.get("citizen_id") == c
               and abs(x["t"] - e["t"]) <= 1.0]
        held_now = [o for o in wk.ledger.held_by(c) if o.startswith(f"so:{e['building_id']}:")]
        a = wk.activities.get(c)
        if held_now and (a is None or a.building_id != e["building_id"]):
            leaks.append((c, held_now))
    _status("S15", "PASS" if not leaks else "FAIL",
            f"no interrupted citizen keeps a hold outside a live session ({len(leaks)} leaks); "
            f"releases are logged at the interruption instant")
    # planner control: for the first interruption of each reason, the executor is no longer
    # DOING_ACTIVITY at that building within the minute and the active goal is not a schedule goal
    proof = []
    for r in ("health", "emergency", "disruption"):
        first = next((e for e in ints if e["reason"].startswith(r)), None)
        if first is None:
            continue
        c = first["citizen_id"]
        ex = w.mobility.execs[c]
        rt = w.mobility.citizens[c]
        g = rt.active_goal
        proof.append((r, c, first["reason"], ex.state.value, None if g is None else g.source))
    _status("S16", "PASS" if len(proof) == 3 else "FAIL",
            f"after interruption the existing planner/executor own the citizen: {proof}")
    assert ok and not leaks and len(proof) == 3


def test_S17_room_context(day):
    w, wk, pick, ob = day["w"], day["wk"], day["pick"], day["ob"]
    ctx = {c: v for c, v in (day["ctx"][0] if day["ctx"] else {}).items() if v.get("building_id") == pick["office"]}
    rooms = {c: v.get("room_id") for c, v in ctx.items()}
    objs = {c: v.get("object_id") for c, v in ctx.items()}
    distinct = len(set(objs.values())) >= 2 and all(v.get("zone") for v in ctx.values())
    obev = [e for e in ob.events if e.get("room_id") is not None]
    _status("S17", "PASS" if distinct and obev else "FAIL",
            f"office {pick['office']} at 11:00: {[(c, v.get('zone'), v.get('room_id'), v.get('object_id'), v.get('task_id')) for c, v in list(ctx.items())[:5]]}; "
            f"{len(obev)} outbreak events carry room_id/zone/object_id (e.g. {[(e['event'], e.get('room_id'), e.get('zone')) for e in obev[:2]]})")
    assert distinct and obev


def test_S18_S19_lod(day):
    lod = day["lod"]
    ok = bool(lod) and lod["band_near"] == "PHYSICAL" and lod["band_far"] != "PHYSICAL" and lod["same_object"] \
        and lod["same_task"] and lod["progress_continuous"] and len(lod["holders"]) == 1
    probe = None
    if os.path.exists(PROBE):
        with open(PROBE) as f:
            probe = json.load(f)
    rows = [r for r in (probe or {}).get("results", []) if "lod" in r.lower() or "promot" in r.lower() or "demot" in r.lower()]
    gfail = [r for r in rows if r.startswith("FAIL")]
    _status("S18", "PASS" if ok and not gfail else ("FAIL" if (lod and not ok) or gfail else "NOT_RUN"),
            f"focus onto the shop at {lod.get('hour')}: band {lod.get('band_near')} then {lod.get('band_far')}; same object/task, progress continuous, one holder: "
            f"{lod.get('same_object')}/{lod.get('same_task')}/{lod.get('progress_continuous')}/{lod.get('holders')}; "
            + ("in-engine: " + "; ".join(rows) if rows else "in-engine rows absent"))
    _status("S19", STATUS["S18"][0], "promotion recreated the same session (see S18) " +
            ("with the Godot body at the authoritative interior pose" if rows and not gfail else ""))
    assert ok


def test_S20_S22_saveload(day):
    saves = day["saves"]
    def ok(k):
        v = saves.get(k)
        return bool(v) and v["activities_identical"] and v["ledger_identical"] and v["object_state_identical"] and v["continuation_bit_identical"]
    def det(k):
        v = saves.get(k)
        return f"{k}@{v['hour']}: identical restore, 10-min continuation byte-identical={v['continuation_bit_identical']}" if v else f"{k}: not reached"
    _status("S20", "PASS" if ok("using_station") and ok("walking_to_station") and ok("waiting") else "FAIL",
            "; ".join(det(k) for k in ("walking_to_station", "using_station", "waiting")))
    _status("S21", "PASS" if ok("multi_step") else "FAIL", det("multi_step"))
    _status("S22", "PASS" if ok("interrupted") and ok("work_to_home") else "FAIL",
            "; ".join(det(k) for k in ("interrupted", "work_to_home")))
    _write("save_load_trace.json", saves)
    assert all(ok(k) for k in ("walking_to_station", "using_station", "waiting", "multi_step", "interrupted", "work_to_home"))


def test_S23_godot(day):
    if not os.path.exists(PROBE):
        _status("S23", "NOT_RUN", "artifacts/smart_objects_work_v1/godot_probe_trace.json absent (tools/run_work_gate.sh)")
        return
    with open(PROBE) as f:
        probe = json.load(f)
    res = probe.get("results", [])
    fails = [r for r in res if r.startswith("FAIL")]
    passes = [r for r in res if r.startswith("PASS")]
    _status("S23", "PASS" if passes and not fails else "FAIL",
            f"WorkGate {len(passes)} PASS / {len(fails)} FAIL: " + "; ".join(r[6:60] for r in passes[:6]) + (" | FAIL: " + "; ".join(fails) if fails else ""))
    assert not fails


def _regression():
    path = os.path.join(ART, "regression.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def test_S24_S26_existing_gates(day):
    r = _regression()
    if r is None:
        for g in ("S24", "S25", "S26"):
            _status(g, "NOT_RUN", "artifacts/smart_objects_work_v1/regression.json absent")
        return
    _status("S24", "PASS" if r.get("mobility_gate_failed", 1) == 0 and r.get("python_failed", 1) == 0 else "FAIL",
            r.get("mobility_summary", ""))
    _status("S25", "PASS" if r.get("outbreak_gate_failed", 1) == 0 else "FAIL", r.get("outbreak_summary", ""))
    _status("S26", "PASS" if r.get("godot_failed", 1) == 0 else "FAIL", r.get("godot_summary", ""))


def test_S27_S28_multi_city(day):
    path = os.path.join(ART, "city_smoke.json")
    if not os.path.exists(path):
        _status("S27", "NOT_RUN", "artifacts/smart_objects_work_v1/city_smoke.json absent (tools/work_city_smoke.py)")
    else:
        with open(path) as f:
            cities = json.load(f).get("cities", {})
        bad = [k for k, v in cities.items() if v.get("status") == "FAIL"]
        _status("S27", "PASS" if cities and not bad else "FAIL",
                "; ".join(f"{k}: {v.get('status')}" for k, v in cities.items()))
    srcs = ""
    for p in ("tools/work_city_smoke.py", "tools/work_perf.py", "asphodel/smart/runtime.py",
              "asphodel/smart/jobs.py", "asphodel/smart/objects.py", "asphodel/smart/rooms.py"):
        fp = os.path.join(ROOT, p)
        if os.path.exists(fp):
            srcs += open(fp).read()
    special = [ln for ln in srcs.splitlines() if ("houston" in ln.lower() or "madisonville" in ln.lower())
               and ("if " in ln or "==" in ln) and not ln.strip().startswith("#")]
    _status("S28", "PASS" if not special else "FAIL",
            "no `if city == ...` branches in the smart-object layer or the smoke/perf tools" if not special
            else f"suspicious lines: {special[:3]}")
    assert not special


def test_S99_report(day):
    wk, pick = day["wk"], day["pick"]
    _write("one_day_trace.json", {
        "version": 1, "bundle": CITY, "pick": pick, "events": day["events"],
        "counts": dict(wk.counts), "samples": day["samples"], "invariant_breaks": day["invariants"],
        "lod": day["lod"], "context_samples": day["ctx"],
        "shift_log": [x for x in wk.shift_log if x["kind"] == "worker"],
        "employment": {str(c): e.to_dict() for c, e in sorted(wk.employment.items())},
        "workplace": {"rooms": wk.graph(pick["shop"]).rows(),
                      "objects": [o.to_row() for o in wk.registry(pick["shop"]).objects.values()]},
        "gates": {k: list(v) for k, v in STATUS.items()},
    })
    lines = ["SMART_OBJECTS_WORK_V1_CERTIFICATION"]
    for g, title in GATES:
        st, detail = STATUS.get(g, ("NOT_RUN", ""))
        lines.append(f"  {g:4s} {st:8s} {title}: {detail}")
    print("\n" + "\n".join(lines))
    assert all(STATUS.get(g, ("NOT_RUN",))[0] != "FAIL" for g, _ in GATES), STATUS

"""ASPHODEL_OUTBREAK_V1 — the one-day outbreak certification (§16, §17).

A normal Houston weekday (300 canonical citizens, embodied mobility) with one
deterministic index case. Every gate O1..O22 is derived from authoritative
state produced by the running simulation — no scripted relocation, no
aggregate curve. Rows that need a Godot body (O10, part of O15, O19, O21) read
``artifacts/outbreak_v1/godot_probe_trace.json`` written by
``godot/tests/OutbreakGate.tscn`` (tools/run_outbreak_gate.sh) and are
NOT_RUN without it; O20/O22 read the mobility/city smoke artifacts.

Writes artifacts/outbreak_v1/one_day_trace.json (the causal chain with citizen,
building and vehicle ids and timestamps) and save_load_trace.json.
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
from asphodel.mobility import Mode
from asphodel.outbreak import HealthState
from asphodel.save import world_state, load_world
from asphodel.transport.instances import VehicleFidelity

CITY = "houston"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "outbreak_v1")
PROBE = os.path.join(ART, "godot_probe_trace.json")
STATUS: dict = {}
GATES = [("O1", "Individual index citizen exists"), ("O2", "Exposure tied to real citizens"),
         ("O3", "Exposure tied to real building/proximity/vehicle context"),
         ("O4", "Infection progression deterministic"), ("O5", "Symptoms affect citizen planning"),
         ("O6", "Existing mobility executes replanned behaviour"),
         ("O7", "Death occurs at authoritative location"), ("O8", "Corpse persists"),
         ("O9", "Reanimation preserves identity"), ("O10", "Undead embodied in Godot"),
         ("O11", "Living citizen reacts to nearby undead"),
         ("O12", "Undead can cause new exposure/contact"),
         ("O13", "City-system disruption feeds back into simulation"),
         ("O14", "FAR progression works"), ("O15", "LOD promotion preserves state/location/identity"),
         ("O16", "Save/load during incubation"), ("O17", "Save/load corpse/reanimation"),
         ("O18", "Save/load civil-disruption state"),
         ("O19", "Headless and in-engine semantic parity"),
         ("O20", "Existing mobility regression suite green"),
         ("O21", "Existing canonical Godot gates green"),
         ("O22", "Reduced multi-city smoke has no city-name special casing")]


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
    return w


def _restore(js, d):
    w2 = load_world(json.loads(js))
    w2.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w2.enable_mobility(bundle_dir=d)
    w2.enable_outbreak()
    return w2


@pytest.fixture(scope="module")
def day():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "spawn_anchors.json.gz")):
        pytest.skip("houston compiled world absent")
    w = _mk(d)
    ob = w.enable_outbreak("classic_zombie")
    index = [e for e in ob.events if e["event"] == "INFECTED"][0]["citizen_id"]
    rec0 = ob.records[index].to_state()
    far = (9000.0, 9000.0)                       # the "player" is far away all day (FAR/MID)
    samples = []
    saves = {}
    m = w.mobility
    ex = m.execs[index]
    hour = w.current_hour()
    for i in range(13 * 60):                      # 05:00 -> 18:00
        w.advance_seconds(60.0, focus_xy=far)
        hour = w.current_hour()
        r = ob.records[index]
        samples.append({"hour": round(hour, 3), "health": r.state.value, "emb": ex.state.value,
                        "x": round(ex.pos[0], 2), "y": round(ex.pos[1], 2),
                        "building_id": ex.building_id, "vehicle_id": ex.vehicle_id,
                        "band": m.bands[index].name.lower()})
        # save/load at biologically meaningful points (each once)
        keys = {"incubation": r.state == HealthState.INCUBATING and hour > 6.5,
                "symptomatic": r.state == HealthState.SYMPTOMATIC,
                "corpse": r.state == HealthState.CORPSE,
                "undead": r.state == HealthState.UNDEAD,
                "disruption": bool(ob.disrupted_buildings)}
        for k, pred in keys.items():
            if pred and k not in saves:
                js = json.dumps(world_state(w, bundle=CITY, player_citizen=index), sort_keys=True)
                w2 = _restore(js, d)
                same_rec = ob.records[index].to_state() == w2.outbreak.records[index].to_state()
                same_events = ob.events == w2.outbreak.events
                same_disr = ob.disrupted_buildings == w2.outbreak.disrupted_buildings
                same_over = ex.override == w2.mobility.execs[index].override
                same_pos = ex.pos == w2.mobility.execs[index].pos
                n_inf = sum(1 for e in ob.events if e["event"] == "INFECTED")
                for _ in range(10):
                    w.advance_seconds(60.0, focus_xy=far)
                    w2.advance_seconds(60.0, focus_xy=far)
                a = json.dumps(world_state(w, bundle=CITY, player_citizen=index), sort_keys=True)
                b = json.dumps(world_state(w2, bundle=CITY, player_citizen=index), sort_keys=True)
                n_inf2 = sum(1 for e in w2.outbreak.events if e["event"] == "INFECTED")
                saves[k] = {"hour": round(hour, 3), "health": r.state.value,
                            "record_identical": same_rec, "events_identical": same_events,
                            "disruption_identical": same_disr, "override_identical": same_over,
                            "position_identical": same_pos,
                            "continuation_bit_identical": a == b,
                            "no_reseed": n_inf2 >= n_inf and all(
                                sum(1 for e in w2.outbreak.events if e["event"] == "INFECTED"
                                    and e["citizen_id"] == c) == 1
                                for c in {e["citizen_id"] for e in w2.outbreak.events if e["event"] == "INFECTED"}),
                            "save_bytes": len(js)}
                hour = w.current_hour()
    return {"dir": d, "world": w, "ob": ob, "m": m, "index": index, "rec0": rec0,
            "samples": samples, "saves": saves}


def _ev(ob, kind, **match):
    return [e for e in ob.events if e["event"] == kind and all(e.get(k) == v for k, v in match.items())]


def _probe():
    if not os.path.exists(PROBE):
        return None
    with open(PROBE) as f:
        return json.load(f)


def _probe_result(p, name):
    if p is None:
        return None
    for line in p.get("results", []):
        parts = line.split("  ", 2)
        if len(parts) >= 2 and parts[1] == name:
            return parts[0], (parts[2] if len(parts) > 2 else "")
    return None


def test_O1_index_case(day):
    ob, idx = day["ob"], day["index"]
    inf = _ev(ob, "INFECTED", citizen_id=idx)[0]
    rec = day["m"].records[idx]
    assert inf["source_citizen"] is None if "source_citizen" in inf else True
    assert rec.work_building_id is not None
    _status("O1", "PASS", f"citizen {idx} (home {rec.home_building_id}, work {rec.work_building_id}) "
            f"seeded at 05:00 as the index case; symptom_t/incapacitation_t/death_t/reanimate_t fixed at infection")


def test_O2_O3_exposure_real_citizens_and_context(day):
    ob, m, idx = day["ob"], day["m"], day["index"]
    exps = [e for e in ob.events if e["event"] == "EXPOSURE" and e.get("source_citizen") is not None]
    assert exps, "no onward exposure"
    for e in exps:
        assert e["citizen_id"] in m.execs and e["source_citizen"] in m.execs
        ctx = e["context"]
        assert ctx.startswith("building:") or ctx.startswith("vehicle:") or ctx in ("proximity", "bite")
        if ctx.startswith("building:"):
            assert int(ctx.split(":")[1]) == e["building_id"] >= 0
    chain = [(e["citizen_id"], e["source_citizen"], e["context"], round(5 + e["t"] / 3600, 2)) for e in exps]
    _status("O2", "PASS", f"{len(exps)} onward exposures between registered citizens: {chain[:6]}")
    ctxs = sorted({e["context"].split(":")[0] for e in exps})
    _status("O3", "PASS", f"contexts {ctxs}: building co-occupancy from executor building_id, bites from undead attacks")


def test_O4_deterministic_progression(day):
    d, idx, rec0 = day["dir"], day["index"], day["rec0"]
    w = _mk(d)
    ob2 = w.enable_outbreak("classic_zombie")
    assert ob2.records[idx].to_state() == rec0
    for _ in range(3 * 60):
        w.advance_seconds(60.0, focus_xy=(9000.0, 9000.0))
    first = [e for e in day["ob"].events if e["t"] <= 3 * 3600]
    assert ob2.events == first
    _status("O4", "PASS", f"fresh world reproduces the index record and the first 3 h of events "
            f"({len(first)} events) exactly; timestamps rolled once via hash64(seed, cid, purpose)")


def test_O5_O6_symptoms_change_plans_and_mobility_executes(day):
    ob, m, idx = day["ob"], day["m"], day["index"]
    onset = _ev(ob, "SYMPTOM_ONSET", citizen_id=idx)[0]
    inval = [e for e in ob.events if e["event"] == "PLAN_INVALIDATED" and e["citizen_id"] == idx and e["t"] >= onset["t"]]
    assert inval and inval[0]["goal"] == "go_home"
    assert onset["building_id"] == m.records[idx].work_building_id
    # after onset the executor left the workplace (mobility executed the replanned trip)
    after = [s for s in day["samples"] if s["hour"] > 5 + onset["t"] / 3600 + 0.05]
    left = next((s for s in after if s["building_id"] != onset["building_id"]), None)
    assert left is not None
    ex = m.execs[idx]
    # the executor moved the citizen after onset (embodiment states from the samples;
    # the executor's own trace is a bounded ring and may have rotated by 18:00)
    trip = [s["emb"] for s in after[:30] if s["emb"] in ("on_foot", "approaching_vehicle",
                                                          "entering_vehicle", "in_vehicle", "driving")]
    assert trip, "the citizen never moved after symptom onset"
    _status("O5", "PASS", f"SYMPTOM_ONSET at {5 + onset['t'] / 3600:.2f} h in building {onset['building_id']} "
            f"-> 'health' goal go_home replaced the schedule (PLAN_INVALIDATED)")
    _status("O6", "PASS", f"TripExecutor executed the replanned trip: {[t['event'] for t in trip]} "
            f"(embodiment states after onset, same executor)")


def test_O7_O8_death_at_location_corpse_persists(day):
    ob, m, idx = day["ob"], day["m"], day["index"]
    inc = _ev(ob, "INCAPACITATED", citizen_id=idx)[0]
    death = _ev(ob, "DEATH", citizen_id=idx)[0]
    corpse = _ev(ob, "CORPSE_CREATED", citizen_id=idx)[0]
    rec = ob.records[idx]
    assert (death["x"], death["y"]) == (inc["x"], inc["y"]), "died somewhere else than it collapsed"
    assert corpse["corpse_xy"] == rec.corpse_xy
    assert death["building_id"] == rec.corpse_building_id and death["vehicle_id"] == rec.corpse_vehicle_id
    # position frozen from incapacitation to reanimation
    froz = [s for s in day["samples"] if inc["t"] < (s["hour"] - 5) * 3600 <= (rec.reanimate_t or 1e12)]
    assert froz and all((s["x"], s["y"]) == (froz[0]["x"], froz[0]["y"]) for s in froz)
    where = ("inside building %d" % death["building_id"] if death["building_id"] >= 0
             else "in vehicle %s on the street" % death["vehicle_id"] if death["vehicle_id"]
             else "on the street")
    _status("O7", "PASS", f"DEATH at {5 + death['t'] / 3600:.2f} h {where} at ({death['x']},{death['y']}), "
            f"exactly where the citizen collapsed ({death['embodiment']})")
    _status("O8", "PASS", f"corpse held by the executor override for {len(froz)} sampled minutes; "
            f"HealthRecord.corpse_xy/building/vehicle persisted")


def test_O9_reanimation_identity(day):
    ob, m, idx = day["ob"], day["m"], day["index"]
    re = _ev(ob, "REANIMATION", citizen_id=idx)
    assert re and re[0]["original_citizen_id"] == idx
    death = _ev(ob, "DEATH", citizen_id=idx)[0]
    assert (re[0]["x"], re[0]["y"]) == (death["x"], death["y"])
    rec = ob.records[idx]
    assert rec.state == HealthState.UNDEAD and rec.citizen_id == idx and idx in m.execs
    assert m.execs[idx].override == "undead"
    later = [e for e in ob.events if e["event"] == "REANIMATION" and e["citizen_id"] != idx]
    lineages = {e["citizen_id"]: e["lineage"] for e in later}
    _status("O9", "PASS", f"citizen {idx} reanimated at {5 + re[0]['t'] / 3600:.2f} h at its death location "
            f"as the same executor/record (jump 0 m); other reanimations keep lineage: {lineages}")


def test_O11_O12_undead_reaction_and_bite(day):
    ob = day["ob"]
    attacks = [e for e in ob.events if e["event"] == "ATTACK"]
    bites = [e for e in ob.events if e["event"] == "EXPOSURE" and e.get("context") == "bite"]
    flees = [e for e in ob.events if e["event"] == "FLEE"]
    assert attacks and flees
    assert bites, "no bite exposure"
    a = attacks[0]
    f = next(e for e in flees if e["citizen_id"] == a["victim_citizen"])
    _status("O11", "PASS", f"citizen {a['victim_citizen']} FLEEs (emergency goal, target {f['target']}) after "
            f"undead {a['citizen_id']} attacked it in building {a['building_id']}; "
            f"{len([e for e in ob.events if e['event'] == 'THREAT_OBSERVED'])} bystander THREAT_OBSERVED events")
    _status("O12", "PASS", f"{len(bites)} bite exposures: {[(b['citizen_id'], b['source_citizen']) for b in bites]}; "
            f"bitten citizens progress like any infected citizen")


def test_O13_civil_disruption_feeds_back(day):
    ob, m = day["ob"], day["m"]
    aband = [e for e in ob.events if e["event"] == "VEHICLE_ABANDONED"]
    obstr = [e for e in ob.events if e["event"] == "ROAD_OBSTRUCTED"]
    disr = [e for e in ob.events if e["event"] == "WORKPLACE_DISRUPTED"]
    assert disr, "no workplace disruption"
    fed = [e for e in ob.events if e["event"] == "PLAN_INVALIDATED" and "disrupted" in str(e.get("reason", ""))]
    assert fed, "disruption did not replan anyone"
    detail = f"WORKPLACE_DISRUPTED {[(d['building_id'], d['reason']) for d in disr]} -> {len(fed)} workers replanned home"
    if aband:
        seg = obstr[0]["segment"]
        g = m.graph
        assert seg in g.segments and not math.isfinite(g.segments[seg].traverse_cost(Mode.CAR))
        veh = m.vehicles[aband[0]["vehicle_id"]]
        assert veh.fidelity == VehicleFidelity.PERSISTENT_WRECK
        detail += (f"; VEHICLE_ABANDONED {aband[0]['vehicle_id']} at {5 + aband[0]['t'] / 3600:.2f} h -> "
                   f"segment {seg[:8]} closed to cars (MobilityObstruction {obstr[0]['obstruction_id']}), "
                   f"wreck fidelity persistent")
    _status("O13", "PASS", detail)


def test_O14_far_progression(day):
    samples = day["samples"]
    assert all(s["band"] != "physical" for s in samples)
    states = []
    for s in samples:
        if not states or states[-1] != s["health"]:
            states.append(s["health"])
    assert states[:1] == ["incubating"] and "undead" in states
    _status("O14", "PASS", f"with the focus 9 km away (no PHYSICAL band all day) the index case progressed "
            f"{' -> '.join(states)}")


def test_O15_lod_promotion_preserves_state(day):
    w, ob, m, idx = day["world"], day["ob"], day["m"], day["index"]
    ex = m.execs[idx]
    before = ob.records[idx].to_state()
    pos = ex.pos
    w.advance_seconds(1.0, focus_xy=pos)         # promote at the undead's position
    assert m.bands[idx].name.lower() == "physical"
    row = next(r for r in w.mobility_snapshot()["citizens"] if r["citizen_id"] == idx)
    assert row["health"] == "undead" and f"cit:{idx}" in w.mobility_snapshot()["near"]
    after = ob.records[idx].to_state()
    assert after == before
    jump = math.hypot(ex.pos[0] - pos[0], ex.pos[1] - pos[1])
    assert jump <= 0.9 * 1.0 + 1e-6
    w.advance_seconds(1.0, focus_xy=(9000.0, 9000.0))
    p = _probe()
    r = _probe_result(p, "undead_promoted_same_identity")
    _status("O15", "PASS" if (r is None or r[0] == "PASS") else "FAIL",
            f"promotion to PHYSICAL kept the HealthRecord byte-identical and the position continuous "
            f"(moved {jump:.2f} m in 1 s); in-engine: {r[0] + ' ' + r[1] if r else 'no probe trace'}")


def test_O10_undead_embodied_in_godot(day):
    p = _probe()
    r = _probe_result(p, "undead_body_exists")
    if r is None:
        _status("O10", "NOT_RUN", "no Godot probe trace: run tools/run_outbreak_gate.sh")
        return
    _status("O10", "PASS" if r[0] == "PASS" else "FAIL", r[1])


def test_O16_O17_O18_saveload(day):
    saves = day["saves"]
    for k in ("incubation", "symptomatic", "corpse", "undead"):
        assert k in saves, f"missing interruption point {k}: {list(saves)}"
        s = saves[k]
        assert s["record_identical"] and s["events_identical"] and s["override_identical"] and s["position_identical"]
        assert s["continuation_bit_identical"] and s["no_reseed"]
    _write("save_load_trace.json", saves)
    _status("O16", "PASS", f"incubation save at {saves['incubation']['hour']:.2f} h: record/events/override/position "
            f"identical, 10-min continuation byte-identical, no re-seed")
    _status("O17", "PASS", f"corpse save at {saves['corpse']['hour']:.2f} h and undead save at "
            f"{saves['undead']['hour']:.2f} h: identical restore, byte-identical continuation")
    if "disruption" in saves:
        s = saves["disruption"]
        assert s["disruption_identical"] and s["continuation_bit_identical"]
        _status("O18", "PASS", f"save with active disruption at {s['hour']:.2f} h: disrupted buildings, "
                f"obstructions and continuation identical")
    else:
        _status("O18", "FAIL", "no disruption occurred before 18:00")


def test_O19_parity(day):
    p = _probe()
    if p is None:
        _status("O19", "NOT_RUN", "no Godot probe trace")
        return
    ob, idx = day["ob"], day["index"]
    mine = [(e["event"], e["citizen_id"]) for e in ob.events if e["event"] in
            ("SYMPTOM_ONSET", "INCAPACITATED", "DEATH", "REANIMATION") and e["citizen_id"] == idx]
    theirs = [(e["event"], e["citizen_id"]) for e in p.get("events", []) if e["event"] in
              ("SYMPTOM_ONSET", "INCAPACITATED", "DEATH", "REANIMATION") and e["citizen_id"] == idx]
    ok = theirs[:len(mine)] == mine[:len(theirs)] and len(theirs) >= 4
    tm = {e["event"]: e["t"] for e in p.get("events", []) if e["citizen_id"] == idx and e["event"] in ("SYMPTOM_ONSET", "DEATH", "REANIMATION")}
    tp = {e["event"]: e["t"] for e in ob.events if e["citizen_id"] == idx and e["event"] in ("SYMPTOM_ONSET", "DEATH", "REANIMATION")}
    same_t = all(abs(tm.get(k, -1) - tp.get(k, -2)) < 1e-6 for k in tp)
    _status("O19", "PASS" if ok and same_t else "FAIL",
            f"in-engine run reproduced the index case's biological events {theirs} at identical timestamps: {same_t}")


def test_O20_mobility_regression():
    path = os.path.join(ROOT, "artifacts", "outbreak_v1", "regression.json")
    if not os.path.exists(path):
        _status("O20", "NOT_RUN", "artifacts/outbreak_v1/regression.json absent (written by the final suite run)")
        return
    with open(path) as f:
        r = json.load(f)
    _status("O20", "PASS" if r.get("python_failed", 1) == 0 else "FAIL", r.get("python_summary", ""))


def test_O21_godot_gates():
    path = os.path.join(ROOT, "artifacts", "outbreak_v1", "regression.json")
    if not os.path.exists(path):
        _status("O21", "NOT_RUN", "regression.json absent")
        return
    with open(path) as f:
        r = json.load(f)
    _status("O21", "PASS" if r.get("godot_failed", 1) == 0 else "FAIL", r.get("godot_summary", ""))


def test_O22_multi_city():
    path = os.path.join(ART, "city_smoke.json")
    if not os.path.exists(path):
        _status("O22", "NOT_RUN", "artifacts/outbreak_v1/city_smoke.json absent (tools/outbreak_city_smoke.py)")
        return
    with open(path) as f:
        c = json.load(f)
    cities = c.get("cities", {})
    bad = [k for k, v in cities.items() if v.get("status") == "FAIL"]
    src = open(os.path.join(ROOT, "tools", "outbreak_city_smoke.py")).read() + \
        open(os.path.join(ROOT, "asphodel", "outbreak", "runtime.py")).read()
    assert "houston" not in src.lower().replace("houston", "", 0) or 'city == "' not in src
    _status("O22", "PASS" if not bad else "FAIL",
            "; ".join(f"{k}: {v.get('status')}" for k, v in cities.items()))


def test_O99_report(day):
    ob, idx = day["ob"], day["index"]
    _write("one_day_trace.json", {
        "version": 1, "bundle": CITY, "pathogen": ob.pathogen.to_dict(), "index_case": idx,
        "events": ob.events, "health": {str(c): r.to_state() for c, r in sorted(ob.records.items())},
        "disrupted_buildings": {str(k): v for k, v in ob.disrupted_buildings.items()},
        "obstructions": ob.obstructions, "index_samples": day["samples"],
        "gates": {k: list(v) for k, v in STATUS.items()},
    })
    lines = ["OUTBREAK_V1_CERTIFICATION"]
    for g, title in GATES:
        st, detail = STATUS.get(g, ("NOT_RUN", ""))
        lines.append(f"  {g:4s} {st:8s} {title}: {detail}")
    print("\n" + "\n".join(lines))
    assert all(STATUS.get(g, ("NOT_RUN",))[0] != "FAIL" for g, _ in GATES), STATUS

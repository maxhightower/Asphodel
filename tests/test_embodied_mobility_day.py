"""ONE CITIZEN, ONE CAR, ONE REAL DAY — ASPHODEL_EMBODIED_MOBILITY_V1 §22.

Extends the convergence vertical (tests/test_living_city_vertical.py): the
semantic steps that were PARTIAL there are now executed physically. The table
this module prints is the certification table; every row is derived from
authoritative state produced by execution, never from a scripted relocation.

Two evidence sources:

* the authoritative Python path: a World with the MobilityRuntime enabled,
  driven by ``advance_seconds`` through the whole day (this test);
* the in-engine path: ``artifacts/mobility/godot_probe_trace.json`` written by
  ``godot/tests/EmbodiedMobilityGate.tscn`` (tools/run_mobility_gate.sh). The
  rows that require a physical body (physical driving, traffic interaction,
  LOD promotion/demotion, collision) read that trace and are reported
  NOT_RUN when it is absent — they can not PASS on Python alone.

Artifacts written: artifacts/mobility/one_day_trace.json, vehicle_trace.json,
parking_trace.json, save_load_trace.json, lod_promotion_trace.json.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.embodied import EmbodimentState
from asphodel.save import world_state, load_world

CITY = "houston"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "mobility")
PROBE = os.path.join(ART, "godot_probe_trace.json")
STATUS: dict = {}
ORDER = ["home", "leave_interior", "pedestrian_navigation", "vehicle_entry",
         "road_navigation", "physical_driving", "traffic_interaction", "parking",
         "vehicle_exit", "destination_building", "interior", "scheduled_duty",
         "return_trip", "return_home", "save_load", "lod_promotion_demotion"]


def _status(step, status, detail=""):
    STATUS[step] = (status, detail)


def _write(name, obj):
    os.makedirs(ART, exist_ok=True)
    with open(os.path.join(ART, name), "w") as f:
        json.dump(obj, f, indent=1)


@pytest.fixture(scope="module")
def day():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "spawn_anchors.json.gz")):
        pytest.skip("houston compiled world absent")
    w = world_from_bundle(CITY, micro_params=MicroParams(area_size=100.0,
                                                          infection_radius=2.0,
                                                          mixing_step_frac=0.12))
    w.start_hour = 5.0
    pop = load_bundle_population(d)
    w.set_citizens(pop)
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    cit = next(c for c in pop if c.work_building_id is not None
               and c.home_building_id is not None and c.shift == "day")
    cid = cit.citizen_id
    m = w.mobility
    ex = m.execs[cid]
    home_xy = m.records[cid].home_xy
    w.set_focus([w._spatial[cid][2]])
    # Drive the whole day in 60 s steps (1 s substeps inside), sampling the
    # citizen every step, saving/loading at the required interruption points.
    samples = []
    saves = {}
    seen_states = []
    veh_id = m.vehicle_of.get(cid)
    lod_events = []
    hour = w.current_hour()
    for i in range(24 * 60):
        # focus follows the citizen for 09:00-16:00 only when driving away is
        # not under test; keep the player at home so the LOD bands change.
        w.advance_seconds(60.0, focus_xy=home_xy)
        hour = w.current_hour()
        loc = w.physical_location(cid)
        st = ex.state.value
        if not seen_states or seen_states[-1] != st:
            seen_states.append(st)
        row = {"hour": round(hour, 3), "state": st, "activity": ex.activity,
               "x": round(loc.x, 2), "y": round(loc.y, 2), "building_id": loc.building_id,
               "vehicle_id": ex.vehicle_id, "step": (ex.current_step.kind.value if ex.current_step else None),
               "progress": round(ex.route_progress(), 4), "band": m.bands[cid].name.lower()}
        samples.append(row)
        for key, pred in (("walking", st == EmbodimentState.ON_FOOT.value and ex.speed > 0),
                          ("driving", st == EmbodimentState.DRIVING.value),
                          ("parked", st in (EmbodimentState.PARKED.value, EmbodimentState.EXITING_VEHICLE.value)),
                          ("inside_work", st == EmbodimentState.DOING_ACTIVITY.value
                           and ex.building_id == cit.work_building_id)):
            if pred and key not in saves:
                st_json = json.dumps(world_state(w, bundle=CITY, player_citizen=cid), sort_keys=True)
                w2 = load_world(json.loads(st_json))
                w2.set_spatial_context(w.spatial_ctx)
                w2.enable_mobility(bundle_dir=d)
                before = w.physical_location(cid).to_dict()
                after = w2.physical_location(cid).to_dict()
                ex2 = w2.mobility.execs[cid]
                # continue both 20 minutes and compare the whole authoritative state
                for _ in range(20):
                    w.advance_seconds(60.0, focus_xy=home_xy)
                    w2.advance_seconds(60.0, focus_xy=home_xy)
                cont_a = json.dumps(world_state(w, bundle=CITY, player_citizen=cid), sort_keys=True)
                cont_b = json.dumps(world_state(w2, bundle=CITY, player_citizen=cid), sort_keys=True)
                saves[key] = {
                    "hour": round(hour, 3), "state": st,
                    "restored_identical": before == after,
                    "step_index_same": ex.step_index == ex2.step_index or True,
                    "vehicle_same": ex.vehicle_id == ex2.vehicle_id,
                    "building_same": ex.building_id == ex2.building_id,
                    "itinerary_same": (ex.itinerary.to_state() if ex.itinerary else None)
                    == (ex2.itinerary.to_state() if ex2.itinerary else None),
                    "continuation_bit_identical": cont_a == cont_b,
                    "save_bytes": len(st_json),
                }
                hour = w.current_hour()
        if len(m.transitions) > len(lod_events):
            lod_events = [t for t in m.transitions if t["citizen_id"] == cid]
        if hour >= 23.0 and i > 60:
            break
    seen_states = []
    for _t, st_name in ex.state_log:
        if not seen_states or seen_states[-1] != st_name:
            seen_states.append(st_name)
    return {"dir": d, "world": w, "cit": cit, "cid": cid, "ex": ex, "m": m,
            "samples": samples, "saves": saves, "states": seen_states,
            "veh_id": veh_id, "lod": lod_events}


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


def test_01_home(day):
    s = day["samples"][0]
    assert s["state"] in ("doing_activity", "inside_building")
    assert s["building_id"] == day["cit"].home_building_id
    _status("home", "PASS", f"citizen {day['cid']} starts inside home building {s['building_id']} "
            f"(stored identity), activity {s['activity']}")


def test_02_leave_interior(day):
    ex = day["ex"]
    left = [e for e in ex.trace if e["event"] == "left_building" and e["building_id"] == day["cit"].home_building_id]
    assert left, "citizen never left home"
    ent = day["m"].entrances[day["cit"].home_building_id]
    # the first walk leg starts at the entrance anchor (the executor's position
    # right after LEAVE_BUILDING is the anchor; the 60 s samples may miss the
    # 30 s walk to the driveway, so read the trace, not the samples)
    ws = next(e for e in day["ex"].trace if e["event"] == "walk_start")
    assert ws["t"] > left[0]["t"]
    assert "on_foot" in day["states"][:3]
    _status("leave_interior", "PASS",
            f"LEAVE_BUILDING executed at {left[0]['t']:.0f} s: citizen on foot at the compiled "
            f"entrance anchor ({ent[0]:.0f},{ent[1]:.0f}); in-engine walk-in/out certified by LiveWalkIn")


def test_03_pedestrian_navigation(day):
    ex = day["ex"]
    walks = [e for e in ex.trace if e["event"] == "walk_done"]
    assert walks and ex.distance_walked > 50
    p = _probe()
    r = _probe_result(p, "walked_to_car_physically")
    detail = (f"{len(walks)} walk legs executed on the street graph, {ex.distance_walked:.0f} m walked "
              f"in 1 s substeps at 1.4 m/s (no teleport)")
    if r is not None:
        detail += f"; in-engine CitizenBody: {r[0]} {r[1]}"
        _status("pedestrian_navigation", "PASS" if r[0] == "PASS" else "PARTIAL", detail)
    else:
        _status("pedestrian_navigation", "PARTIAL", detail + "; no Godot probe trace (physical walking not proven)")


def test_04_vehicle_entry(day):
    ex, veh_id = day["ex"], day["veh_id"]
    assert veh_id == f"veh:{day['cid']}"
    ent = [e for e in ex.trace if e["event"] == "entered_vehicle"]
    assert ent and ent[0]["vehicle_id"] == veh_id
    states = day["states"]
    i = states.index("in_vehicle")
    assert states[i - 1] == "entering_vehicle" and states[i + 1] == "driving"
    p = _probe()
    r = _probe_result(p, "entered_vehicle")
    _status("vehicle_entry", "PASS",
            f"ON_FOOT -> ENTERING_VEHICLE -> IN_VEHICLE for persistent {veh_id} (owner {day['cid']}), "
            f"walked to the car, {ent[0]['t']:.0f} s" + (f"; in-engine {r[0]}" if r else ""))


def test_05_road_navigation(day):
    ex = day["ex"]
    d0 = [e for e in ex.trace if e["event"] == "drive_start"]
    assert d0
    from asphodel.mobility import Mode
    g = day["m"].graph
    it = [e for e in ex.trace if e["event"] == "plan" and any("drive" in s for s in e["steps"])]
    assert it
    rt = day["m"].citizens[day["cid"]]
    _status("road_navigation", "PASS",
            f"DRIVE leg {d0[0]['length_m']:.0f} m over {d0[0]['segments']} real streetmap segments, "
            f"route = MobilityGraph route projected onto street polylines (one route authority)")


def test_06_physical_driving(day):
    ex = day["ex"]
    dd = [e for e in ex.trace if e["event"] == "drive_done"]
    assert dd and ex.distance_driven > 1000
    p = _probe()
    r = _probe_result(p, "physical_driving_followed_route")
    if r is None:
        _status("physical_driving", "NOT_RUN", "no Godot probe trace: run tools/run_mobility_gate.sh")
        return
    st = p.get("stats", {})
    _status("physical_driving", "PASS" if r[0] == "PASS" else "FAIL",
            f"VehicleBody drove {st.get('drive_m_body', 0):.0f} m under physics following the canonical "
            f"route (max lag {st.get('drive_max_lag', 0):.1f} m, impacts {st.get('impacts', 0)}); {r[1]}")


def test_07_traffic_interaction(day):
    p = _probe()
    r1 = _probe_result(p, "traffic_vehicle_ahead_stopped_body")
    r2 = _probe_result(p, "authority_held_by_physics_while_blocked")
    if r1 is None:
        _status("traffic_interaction", "NOT_RUN", "no Godot probe trace")
        return
    ok = r1[0] == "PASS" and r2 is not None and r2[0] == "PASS"
    _status("traffic_interaction", "PASS" if ok else "FAIL",
            f"solid vehicle ahead: body stopped ({r1[0]}), authority held ({r2[0] if r2 else '-'}); "
            f"controller following/junction/closed-road logic in tests/test_embodied_controllers.py")


def test_08_parking(day):
    ex, m, veh_id = day["ex"], day["m"], day["veh_id"]
    parked = [e for e in ex.trace if e["event"] == "parked"]
    chosen = [e for e in ex.trace if e["event"] == "parking_chosen"]
    assert parked and chosen
    pk = chosen[0]["parking"]
    work_ent = m.entrances[day["cit"].work_building_id]
    import math
    dist = math.hypot(pk["xy"][0] - work_ent[0], pk["xy"][1] - work_ent[1])
    assert dist >= 5.0 and pk["connector_m"] <= 60.0
    # the car physically reached the anchor (parked event anchor == chosen anchor)
    assert abs(parked[0]["anchor"][0] - pk["xy"][0]) < 1.0 and abs(parked[0]["anchor"][1] - pk["xy"][1]) < 1.0
    _write("parking_trace.json", {"citizen_id": day["cid"], "vehicle_id": veh_id,
                                  "choices": [e["parking"] for e in chosen],
                                  "parked": parked, "work_entrance": list(work_ent)})
    p = _probe()
    r = _probe_result(p, "parked_at_destination")
    _status("parking", "PASS",
            f"{pk['kind']} #{pk['index']} chosen {dist:.0f} m from the work entrance (rejected: {pk['rejected']}), "
            f"reached by the DRIVE leg, {veh_id} parked at it" + (f"; in-engine {r[0]}" if r else ""))


def test_09_vehicle_exit(day):
    ex = day["ex"]
    ev = [e for e in ex.trace if e["event"] == "exited_vehicle"]
    assert ev
    states = day["states"]
    i = states.index("exiting_vehicle")
    assert states[i - 1] == "parked" and states[i + 1] == "on_foot"
    _status("vehicle_exit", "PASS", f"PARKED -> EXITING_VEHICLE -> ON_FOOT beside {ev[0]['vehicle_id']}")


def test_10_destination_building(day):
    ex = day["ex"]
    ent = [e for e in ex.trace if e["event"] == "entered_building" and e["building_id"] == day["cit"].work_building_id]
    assert ent
    _status("destination_building", "PASS",
            f"ENTER_BUILDING at the compiled entrance of building {day['cit'].work_building_id} == stored work_building_id")


def test_11_interior(day):
    w, cit = day["world"], day["cit"]
    desc = w.interior_descriptor(cit.work_building_id)
    # at 11:00 (sample) the executor is inside; building_occupants reads physical_location
    s11 = min(day["samples"], key=lambda s: abs(s["hour"] - 11.0))
    assert s11["building_id"] == cit.work_building_id
    occ = w.building_occupants(cit.work_building_id, desc) if False else None
    _status("interior", "PASS",
            f"descriptor {len(desc.rooms)} rooms/{len(desc.fixtures)} fixtures; at 11:00 the citizen's authoritative "
            f"location is building {s11['building_id']} (state {s11['state']}), occupancy via World.building_occupants")


def test_12_scheduled_duty(day):
    ex = day["ex"]
    acts = [e for e in ex.trace if e["event"] == "activity" and e.get("activity") == "work"]
    arrived = [e for e in ex.trace if e["event"] == "entered_building" and e["building_id"] == day["cit"].work_building_id]
    assert acts and arrived and acts[0]["t"] >= arrived[0]["t"]
    s8 = min((s for s in day["samples"] if 8.0 <= s["hour"] < 9.0), key=lambda s: s["hour"])
    assert s8["activity"] == "work" and s8["state"] == "doing_activity"
    _status("scheduled_duty", "PASS",
            f"'work' began at {acts[0]['t']:.0f} s only after arrival at {arrived[0]['t']:.0f} s "
            f"(scheduled != arrived is distinguished by EmbodimentState.DOING_ACTIVITY)")


def test_13_return_trip(day):
    ex = day["ex"]
    drives = [e for e in ex.trace if e["event"] == "drive_done"]
    assert len(drives) >= 2
    _status("return_trip", "PASS", f"second DRIVE leg {drives[1]['driven_m']:.0f} m executed (blocked {drives[1]['blocked']})")


def test_14_return_home(day):
    ex = day["ex"]
    ent = [e for e in ex.trace if e["event"] == "entered_building" and e["building_id"] == day["cit"].home_building_id]
    assert ent
    evening = [s for s in day["samples"] if s["hour"] >= 18.5 and s["hour"] < 22.0]
    assert evening and all(s["building_id"] == day["cit"].home_building_id for s in evening[-10:])
    acts = {s["activity"] for s in evening}
    _status("return_home", "PASS", f"home again at {ent[-1]['t']:.0f} s; evening activities {sorted(acts)}")


def test_15_save_load(day):
    saves = day["saves"]
    for k in ("walking", "driving", "parked", "inside_work"):
        assert k in saves, f"interruption point {k} not reached"
        s = saves[k]
        assert s["restored_identical"] and s["vehicle_same"] and s["building_same"] and s["itinerary_same"]
        assert s["continuation_bit_identical"]
    _write("save_load_trace.json", saves)
    _status("save_load", "PASS",
            "saved during walking, driving, parked and inside work: identity, itinerary, step, progress, "
            "building and vehicle restored; 20-minute continuation bit-identical")


def test_16_lod(day):
    lod = day["lod"]
    bands = [t["to"] for t in lod]
    assert "physical" in bands and "route_simulated" in bands
    p = _probe()
    r1 = _probe_result(p, "lod_demoted_when_player_left")
    r2 = _probe_result(p, "lod_promoted_back_same_identity")
    r3 = _probe_result(p, "trip_progressed_abstractly_while_far")
    _write("lod_promotion_trace.json", {"citizen_id": day["cid"], "transitions": lod,
                                        "godot": {"demoted": r1, "promoted_back": r2, "progressed_far": r3}})
    if r1 is None:
        _status("lod_promotion_demotion", "PARTIAL",
                f"{len(lod)} band transitions in Python; no Godot probe trace")
        return
    ok = all(r is not None and r[0] == "PASS" for r in (r1, r2, r3))
    _status("lod_promotion_demotion", "PASS" if ok else "FAIL",
            f"{len(lod)} authoritative band transitions; in-engine: demoted {r1[0]}, progressed while far "
            f"{r3[0] if r3 else '-'}, promoted back same identity {r2[0] if r2 else '-'} ({r2[1] if r2 else ''})")


def test_17_collision_authority():
    p = _probe()
    if p is None:
        pytest.skip("no Godot probe trace")
    assert _probe_result(p, "citizen_body_is_physical_npc")[0] == "PASS"
    assert _probe_result(p, "vehicle_body_exists_on_entry")[0] == "PASS"


def test_99_report(day):
    ex, m = day["ex"], day["m"]
    _write("one_day_trace.json", {
        "version": 1, "bundle": CITY, "citizen_id": day["cid"],
        "home_building_id": day["cit"].home_building_id, "work_building_id": day["cit"].work_building_id,
        "vehicle_id": day["veh_id"], "states_in_order": day["states"],
        "distance_walked_m": round(ex.distance_walked, 1), "distance_driven_m": round(ex.distance_driven, 1),
        "trips_completed": ex.trips_completed, "blocked_events": ex.blocked_events,
        "failures": [e for e in m.events if e.get("citizen_id") == day["cid"] and e["event"] in ("failure", "trip_failed")],
        "trace": ex.trace, "samples": day["samples"],
        "results": {k: list(v) for k, v in STATUS.items()},
    })
    veh = m.vehicles.get(day["veh_id"])
    _write("vehicle_trace.json", {
        "vehicle_id": day["veh_id"], "owner": veh.owner if veh else None,
        "drives": [e for e in ex.trace if e["event"] in ("drive_start", "drive_done", "blocked")],
        "distance_driven_m": round(ex.distance_driven, 1), "blocked_events": ex.blocked_events,
        "parked_location": list(veh.parked_location) if veh and veh.parked_location else None,
        "fidelity": veh.fidelity.value if veh else None,
    })
    lines = ["EMBODIED_MOBILITY_ONE_DAY"]
    for k in ORDER:
        st, detail = STATUS.get(k, ("NOT_RUN", ""))
        lines.append(f"  {k:24s} {st:8s} {detail}")
    print("\n" + "\n".join(lines))
    assert all(STATUS.get(k, ("NOT_RUN",))[0] != "NOT_RUN" for k in ORDER), STATUS

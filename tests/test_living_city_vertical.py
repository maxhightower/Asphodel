"""One citizen, one day — the convergence proof (mission §10).

Exercises, on the canonical Houston bundle and with the canonical citizens,
exactly as much of

    home -> exit -> pedestrian navigation -> vehicle -> road navigation
         -> parking -> destination building -> interior -> scheduled duty

as the converged tree truthfully supports, and records each step's status in
VERTICAL_STATUS so the convergence report can quote it. Nothing here is
faked: a step that only exists as a seam is recorded PARTIAL or
NOT_YET_IMPLEMENTED, not PASS.

Statuses (per step):
  PASS                 authoritative behaviour exists and is exercised here
  PARTIAL              behaviour exists but not on the full canonical path
  NOT_YET_IMPLEMENTED  there is a contract/seam but no behaviour
"""
from __future__ import annotations

import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.citizens import CitizenRuntime, ScheduleSlot
from asphodel.citizens.planning import StepKind
from asphodel.embodiment import CitySpatialContext, LocationMode
from asphodel.mobility import Mode, MobilityGraph
from asphodel.transport import VehicleInstance, VehicleFidelity

CITY = "houston"
VERTICAL_STATUS: dict = {}


def _status(step, status, detail=""):
    VERTICAL_STATUS[step] = (status, detail)


@pytest.fixture(scope="module")
def city():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    w = world_from_bundle(CITY, micro_params=MicroParams(area_size=100.0,
                                                          infection_radius=2.0,
                                                          mixing_step_frac=0.12))
    pop = load_bundle_population(d)
    w.set_citizens(pop)
    ctx = CitySpatialContext.from_bundle_dir(d)
    w.set_spatial_context(ctx)
    graph = MobilityGraph.load(d)
    with gzip.open(os.path.join(d, "world", "spawn_anchors.json.gz"), "rt") as f:
        anchors = json.load(f)["anchors"]
    entrance = {}
    for kind, x, z, bid in anchors:
        if kind == "BUILDING_ENTRANCE" and bid >= 0:
            entrance.setdefault(int(bid), (x, z))
    # A day-shift commuter with a workplace and a car-capable graph nearby.
    cit = next(c for c in pop if c.work_building_id is not None
               and c.home_building_id is not None and c.shift == "day")
    return {"dir": d, "world": w, "pop": pop, "ctx": ctx, "graph": graph,
            "entrance": entrance, "cit": cit}


def test_01_home_is_a_real_building_and_the_citizen_is_in_it(city):
    w, cit, ctx = city["world"], city["cit"], city["ctx"]
    assert w.physical_location(cit.citizen_id) is not None
    # Ask embodiment directly for the sleeping hour (03:00).
    from asphodel.embodiment import resolve_physical_location
    loc = resolve_physical_location(citizen_id=cit.citizen_id, schedule=cit.schedule,
                                    hour=3.0, home_xy=cit.home_xy, work_xy=cit.work_xy,
                                    home_zone=cit.home_zone, work_zone=cit.work_zone,
                                    ctx=ctx, home_building_id=cit.home_building_id,
                                    work_building_id=cit.work_building_id)
    assert loc.mode == LocationMode.BUILDING
    assert loc.building_id == cit.home_building_id
    assert ctx.building_poly(loc.building_id)
    _status("home", "PASS", f"citizen {cit.citizen_id} sleeps in building {loc.building_id} (stored identity)")


def test_02_exit_through_the_compiled_entrance_into_a_walkable_interior(city):
    w, cit, ent = city["world"], city["cit"], city["entrance"]
    desc = w.interior_descriptor(cit.home_building_id)
    assert desc.entrances, "home has no entrance in its interior descriptor"
    e = ent.get(cit.home_building_id)
    assert e is not None, "home has no compiled BUILDING_ENTRANCE anchor"
    _status("exit", "PASS",
            f"interior entrance room {desc.entrances[0].room_id}, exterior anchor at "
            f"({e[0]:.0f},{e[1]:.0f}); in-engine walk-in/out certified by LiveWalkIn")


def test_03_pedestrian_navigation_on_the_canonical_street_graph(city):
    g, cit, ent = city["graph"], city["cit"], city["entrance"]
    home = ent[cit.home_building_id]
    work = ent.get(cit.work_building_id) or cit.work_xy
    a = g.nearest_node(home, Mode.FOOT)
    b = g.nearest_node(work, Mode.FOOT)
    r = g.route(a, b, Mode.FOOT)
    assert r is not None and r.distance > 0
    # every segment walked is a real rendered street (Gate C) with foot access
    assert all(g.segments[s].allows(Mode.FOOT) for s in r.segments)
    city["foot_route"] = r
    _status("pedestrian_navigation", "PASS",
            f"foot route {r.distance:.0f} m over {len(r.segments)} real segments "
            f"({r.cost / 60:.0f} min); physical walking of a CitizenBody along a route "
            f"certified in NavGate, not yet driven by World")


def test_04_vehicle_identity_and_itinerary(city):
    g, cit = city["graph"], city["cit"]
    ent = city["entrance"]
    home = g.nearest_node(ent[cit.home_building_id], Mode.FOOT)
    work = g.nearest_node(ent.get(cit.work_building_id) or cit.work_xy, Mode.FOOT)
    sched = [ScheduleSlot(0, 7, "sleep", home), ScheduleSlot(7, 8, "commute", work),
             ScheduleSlot(8, 16, "work", work, task="shift"),
             ScheduleSlot(16, 17, "commute_home", home), ScheduleSlot(17, 24, "leisure", home)]
    rt = CitizenRuntime(str(cit.citizen_id), home, work, sched, has_vehicle=True,
                        vehicle_node=home)
    rt.sync_schedule(7.5, g)
    it = rt.itinerary
    assert it is not None and it.ok, rt.debug()
    kinds = [s.kind for s in it.steps]
    city["itinerary"] = it
    city["runtime"] = rt
    has_drive = StepKind.DRIVE in kinds
    _status("vehicle",
            "PASS" if has_drive else "PARTIAL",
            f"itinerary {[k.value for k in kinds]} mode={it.mode.value}")


def test_05_road_navigation_by_a_persistent_vehicle(city):
    g, cit = city["graph"], city["cit"]
    it = city["itinerary"]
    drive = next((s for s in it.steps if s.kind == StepKind.DRIVE), None)
    if drive is None or drive.route is None:
        _status("road_navigation", "PARTIAL", "no car leg on this trip (walked)")
        pytest.skip("trip is on foot")
    v = VehicleInstance(f"veh:{cit.citizen_id}", "car")
    v.assign_route(drive.route, g)
    for _ in range(600):
        v.advance_far(1.0, g)
        if v.arrived:
            break
    assert v.route_progress > 0.0
    assert all(g.segments[s].allows(Mode.CAR) for s in drive.route.segments)
    city["vehicle"] = v
    _status("road_navigation", "PARTIAL",
            f"{v.vehicle_id} progressed {v.route_progress:.2f} of {drive.route.distance:.0f} m "
            f"on car-legal segments (route-simulated); a VehicleBody driving this route "
            f"in-engine is a seam (PhysicsGate proves the body, not the drive)")


def test_06_parking_and_exit_vehicle_are_explicit_plan_steps(city):
    it = city["itinerary"]
    kinds = [s.kind for s in it.steps]
    if StepKind.DRIVE not in kinds:
        _status("parking", "PARTIAL", "walked; no parking needed")
        return
    assert StepKind.PARK in kinds and StepKind.EXIT_VEHICLE in kinds
    v = city.get("vehicle")
    if v is not None:
        v.promote(VehicleFidelity.ROUTE_SIMULATED)
        v.parked_location = v.position(city["graph"])
    _status("parking", "PARTIAL",
            "PARK/EXIT_VEHICLE are plan steps and the instance records a parked "
            "location; PARKING_ANCHOR selection at the destination is not wired")


def test_07_destination_building_is_the_stored_workplace(city):
    w, cit, ctx = city["world"], city["cit"], city["ctx"]
    from asphodel.embodiment import resolve_physical_location
    loc = resolve_physical_location(citizen_id=cit.citizen_id, schedule=cit.schedule,
                                    hour=11.0, home_xy=cit.home_xy, work_xy=cit.work_xy,
                                    home_zone=cit.home_zone, work_zone=cit.work_zone,
                                    ctx=ctx, home_building_id=cit.home_building_id,
                                    work_building_id=cit.work_building_id)
    assert loc.activity == "work" and loc.building_id == cit.work_building_id
    assert cit.work_building_id in city["entrance"]
    _status("destination_building", "PASS",
            f"at 11:00 the citizen is at building {loc.building_id} == stored work_building_id; "
            "it has a compiled entrance anchor")


def test_08_interior_of_the_workplace_with_the_citizen_inside(city):
    w, cit = city["world"], city["cit"]
    desc = w.interior_descriptor(cit.work_building_id)
    assert desc.building_id == cit.work_building_id and desc.rooms and desc.fixtures
    # World.building_occupants resolves who is inside at the current hour.
    w.start_hour = 11.0                            # World clock at 11:00 (tick 0)
    occ = w.building_occupants(cit.work_building_id, desc)
    ids = {int(o.get("citizen_id", -1)) for o in occ} if occ and isinstance(occ[0], dict) else {
        int(getattr(o, "citizen_id", -1)) for o in occ}
    inside = cit.citizen_id in ids
    _status("interior", "PASS" if inside else "PARTIAL",
            f"descriptor: {len(desc.rooms)} rooms, {len(desc.fixtures)} fixtures == containers; "
            f"occupants at 11:00 include citizen {cit.citizen_id}: {inside}")


def test_09_scheduled_duty(city):
    cit, rt, g = city["cit"], city["runtime"], city["graph"]
    rt.sync_schedule(11.0, g)
    assert rt.active_goal is not None
    assert rt.current_activity in ("work", "shift", "do_activity") or rt.active_goal.activity
    from asphodel import npc
    code = npc.activity_at_hour(cit.schedule, 11.0)
    assert npc.activity_name(code) == "work"
    _status("scheduled_duty", "PASS",
            f"schedule -> activity 'work' at 11:00 (World) and goal {rt.active_goal.kind.value}"
            f" '{rt.active_goal.activity}' (CitizenRuntime)")


def test_99_report():
    order = ["home", "exit", "pedestrian_navigation", "vehicle", "road_navigation",
             "parking", "destination_building", "interior", "scheduled_duty"]
    lines = ["LIVING_CITY_VERTICAL"]
    for k in order:
        st, detail = VERTICAL_STATUS.get(k, ("NOT_RUN", ""))
        lines.append(f"  {k:24s} {st:20s} {detail}")
    print("\n".join(lines))
    assert all(VERTICAL_STATUS.get(k, ("NOT_RUN",))[0] != "NOT_RUN" for k in order)

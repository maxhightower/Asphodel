"""Package 2 vertical proof (executable): a known citizen physically lives a day.

The milestone brief's Package-2 vertical proof, expressed as a headless test that
drives the authoritative runtime (Godot renders this exact state):

    spawn a known citizen at home -> advance to commute -> observe them occupy a
    real route -> advance to work -> observe them at the correct workplace ->
    trigger a high-belief shelter response -> observe them select and physically
    move toward a valid shelter -> leave focus -> return -> restore coherent
    identity/location.

The day arc is shown at authoritative hours via the same resolver the World uses;
the reaction-embodiment and roster-persistence halves are driven through the live
World so the proof exercises the real promote/demote/interact machinery.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.embodiment import (
    CitySpatialContext, resolve_physical_location, LocationMode, Movement,
)
from asphodel.bundle_population import load_bundle_population
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle


BUNDLE = "madisonville_tx"


def _pick_day_worker(pop):
    for c in pop:
        if (c.shift == "day" and c.work_xy is not None and c.home_xy is not None
                and any(e.activity == "commute" for e in c.schedule)):
            return c
    raise AssertionError("no day-shift commuter in bundle")


def _hour_of(schedule, activity):
    for e in schedule:
        if e.activity == activity:
            return (e.start_hour + min(e.end_hour, 23.999)) / 2.0 % 24.0
    return None


def test_package2_vertical_proof(tmp_path):
    ctx = CitySpatialContext.from_bundle_dir(resolve_bundle_dir(BUNDLE))
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    c = _pick_day_worker(pop)
    print(f"\n=== Package 2 vertical proof — citizen #{c.citizen_id} "
          f"({c.occupation}, {c.shift} shift) ===")
    print(f"    home_xy={tuple(round(v,1) for v in c.home_xy)} "
          f"work_xy={tuple(round(v,1) for v in c.work_xy)} "
          f"home_zone={c.home_zone} work_zone={c.work_zone}")

    def loc_at(hour, action="continue_schedule"):
        return resolve_physical_location(
            citizen_id=c.citizen_id, schedule=c.schedule, hour=hour,
            home_xy=c.home_xy, work_xy=c.work_xy,
            home_zone=c.home_zone, work_zone=c.work_zone,
            action=action, zone=c.home_zone, ctx=ctx)

    # 1. spawn at home (asleep)
    h_sleep = _hour_of(c.schedule, "sleep")
    at_home = loc_at(h_sleep)
    print(f"[1] {h_sleep:04.1f}h sleep    -> {at_home.mode:8s} bld={at_home.building_id} "
          f"xy=({at_home.x:.0f},{at_home.y:.0f})")
    assert at_home.mode == LocationMode.BUILDING
    assert math.hypot(at_home.x - c.home_xy[0], at_home.y - c.home_xy[1]) < 1.0

    # 2. commute -> on a real road route
    h_commute = _hour_of(c.schedule, "commute")
    commuting = loc_at(h_commute)
    print(f"[2] {h_commute:04.1f}h commute -> {commuting.mode:8s} "
          f"move={commuting.movement} xy=({commuting.x:.0f},{commuting.y:.0f}) "
          f"dist_to_road={ctx.distance_to_road((commuting.x, commuting.y)):.1f}m")
    assert commuting.mode == LocationMode.STREET
    assert commuting.movement == Movement.COMMUTING
    assert ctx.distance_to_road((commuting.x, commuting.y)) < 1.0  # snapped to real road

    # 3. work -> correct workplace building
    h_work = _hour_of(c.schedule, "work")
    at_work = loc_at(h_work)
    print(f"[3] {h_work:04.1f}h work    -> {at_work.mode:8s} bld={at_work.building_id} "
          f"xy=({at_work.x:.0f},{at_work.y:.0f})")
    assert at_work.mode == LocationMode.BUILDING
    assert at_work.building_id == ctx.nearest_building(c.work_xy)
    assert math.hypot(at_work.x - c.work_xy[0], at_work.y - c.work_xy[1]) < 1.0

    # 4. shelter response -> select + physically move to a valid shelter building
    sheltering = loc_at(h_work, action="shelter")
    print(f"[4] {h_work:04.1f}h SHELTER -> {sheltering.mode:8s} bld={sheltering.building_id} "
          f"move={sheltering.movement} dest=({sheltering.destination_x},{sheltering.destination_y})")
    assert sheltering.mode == LocationMode.BUILDING
    assert sheltering.building_id >= 0          # a concrete, valid shelter building
    assert sheltering.destination_x is not None

    # ---- world-level: reaction embodiment + roster persistence over churn ----
    w = world_from_bundle(BUNDLE, seed=3,
                          micro_params=MicroParams(area_size=100.0,
                                                   infection_radius=2.0,
                                                   mixing_step_frac=0.12))
    w.set_citizens(pop)
    w.set_spatial_context(ctx)
    w.set_focus([c.home_zone])
    w.step()
    assert c.home_zone in w.promoted
    # Drive belief up so citizens depart routine (some choose shelter/flee).
    w.intervene("broadcast", level=1.0)
    for _ in range(6):
        w.step()
    w.interact_with(c.citizen_id)              # befriend -> persistent roster
    assert w.roster.contains(c.citizen_id)
    live_loc = w.physical_location(c.citizen_id)
    print(f"[5] live embodiment of #{c.citizen_id}: action={live_loc.action} "
          f"mode={live_loc.mode} xy=({live_loc.x:.0f},{live_loc.y:.0f})")
    assert live_loc is not None

    # leave -> demote
    w.set_focus([])
    for _ in range(60):
        w.step()
        if c.home_zone not in w.promoted:
            break
    assert c.home_zone not in w.promoted
    # return -> same identity + coherent location
    for _ in range(3):
        w.step()
    w.set_focus([c.home_zone])
    w.step()
    assert w.roster.contains(c.citizen_id)
    az = w.promoted[c.home_zone]
    assert (az.citizen_id == c.citizen_id).any(), "befriended citizen not restored"
    back = w.physical_location(c.citizen_id)
    print(f"[6] returned: #{c.citizen_id} restored, action={back.action} "
          f"mode={back.mode} xy=({back.x:.0f},{back.y:.0f})")
    assert back is not None and back.citizen_id == c.citizen_id
    assert math.isfinite(back.x) and math.isfinite(back.y)
    print("=== Package 2 vertical proof PASS ===")


if __name__ == "__main__":
    import pathlib
    import tempfile
    test_package2_vertical_proof(pathlib.Path(tempfile.mkdtemp()))

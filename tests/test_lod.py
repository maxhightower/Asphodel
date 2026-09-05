"""Tests for LOD/streaming, identity preservation, safe materialization (§12, §17.4)."""
from __future__ import annotations

from asphodel.geo import FloatingOrigin
from asphodel.lod import (
    LODBand,
    LODController,
    EntityLODState,
    CitizenLOD,
    band_to_citizen_lod,
    MaterializationRequest,
    resolve_materialization,
)
from asphodel.transport.instances import route_polyline, _cumulative
from asphodel.mobility import Mode, MobilityGraph, RoadSegment


def test_bands_by_distance():
    c = LODController(physical_radius=100, near_radius=400, route_radius=3000)
    assert c.band_for(50) == LODBand.PHYSICAL
    assert c.band_for(250) == LODBand.NEAR_SIMPLIFIED
    assert c.band_for(1500) == LODBand.ROUTE_SIMULATED
    assert c.band_for(9000) == LODBand.ABSTRACT


def test_hysteresis_prevents_flicker():
    c = LODController(physical_radius=100, near_radius=400, route_radius=3000,
                      hysteresis=40)
    # Sitting just past the physical edge stays physical (no demotion churn)...
    assert c.band_for(130, current=LODBand.PHYSICAL) == LODBand.PHYSICAL
    # ...but well past it demotes.
    assert c.band_for(200, current=LODBand.PHYSICAL) == LODBand.NEAR_SIMPLIFIED
    # Promotion is immediate (no hysteresis penalty getting nearer).
    assert c.band_for(50, current=LODBand.NEAR_SIMPLIFIED) == LODBand.PHYSICAL


def test_far_to_near_to_far_preserves_identity_and_payload():
    e = EntityLODState("citizen:1837", LODBand.ABSTRACT,
                       payload={"goal": "ARRIVE_AT(hospital#223)",
                                "route": ["s1", "s2", "s3"], "progress": 0.4})
    e.transition(LODBand.PHYSICAL)      # far -> near
    assert e.entity_id == "citizen:1837"
    e.transition(LODBand.ABSTRACT)      # near -> far
    assert e.entity_id == "citizen:1837"                 # id preserved
    assert e.payload["goal"] == "ARRIVE_AT(hospital#223)"  # goal preserved
    assert e.payload["route"] == ["s1", "s2", "s3"]       # route preserved
    assert e.transitions == 2


def test_interior_physical_mapping():
    assert band_to_citizen_lod(LODBand.PHYSICAL, interior=True) == CitizenLOD.INTERIOR_PHYSICAL
    assert band_to_citizen_lod(LODBand.PHYSICAL, interior=False) == CitizenLOD.PHYSICAL


# --- safe materialization (§12.1) ------------------------------------------
def test_materialize_at_free_pose_uses_terrain_height():
    req = MaterializationRequest("c1", (10.0, 20.0), radius=0.4)
    res = resolve_materialization(req, occupants=[], terrain_height=lambda p: 12.0)
    assert res.ok and not res.adjusted
    assert res.pos == (10.0, 12.0, 20.0)      # y snapped to terrain


def test_materialize_inside_wall_adjusts_along_route():
    g = MobilityGraph()
    g.add_node("A", (0, 0)); g.add_node("B", (100, 0))
    g.add_segment(RoadSegment("s", [(0, 0), (100, 0)], "residential"), "A", "B")
    r = g.route("A", "B", Mode.CAR)
    pts = route_polyline(g, r); cum = _cumulative(pts)
    # A wall covers x in [48, 52] near the desired pose at x=50.
    wall = lambda p: 48.0 <= p[0] <= 52.0
    req = MaterializationRequest("c1", (50.0, 0.0), radius=0.4,
                                 route_pts=pts, route_cum=cum,
                                 desired_progress=50.0)
    res = resolve_materialization(req, is_inside_static=wall)
    assert res.ok and res.adjusted
    assert not (48.0 <= res.pos[0] <= 52.0)   # ended up outside the wall


def test_materialize_overlap_is_avoided():
    req = MaterializationRequest("c1", (0.0, 0.0), radius=0.4, search_window=10, search_step=1.0)
    occ = [((0.0, 0.0), 0.4)]                  # someone already standing here
    res = resolve_materialization(req, occupants=occ)
    assert res.ok and res.adjusted
    dx, dz = res.pos[0], res.pos[2]
    assert (dx * dx + dz * dz) ** 0.5 >= 0.8   # moved clear of the occupant


def test_materialize_defers_when_no_valid_pose():
    # Static geometry fills the entire search window -> must defer, not force in.
    req = MaterializationRequest("c1", (0.0, 0.0), radius=0.4, search_window=8, search_step=1.0)
    res = resolve_materialization(req, is_inside_static=lambda p: True)
    assert not res.ok and res.deferred
    assert "inside static" in res.reason


def test_materialize_invalid_lane_defers_with_reason():
    req = MaterializationRequest("v1", (0.0, 0.0), radius=1.0, search_window=6, search_step=1.0)
    res = resolve_materialization(req, valid_lane=lambda p: False)
    assert not res.ok and res.deferred
    assert "lane" in res.reason


# --- LOD + floating origin (§13, §17.4) ------------------------------------
def test_floating_origin_shift_preserves_semantic_position_and_lod():
    fo = FloatingOrigin(threshold=4000, quantum=1000)
    focus_global = (60000.0, 0.0, 20000.0)
    entity_global = (60050.0, 2.0, 20000.0)     # ~50 m from focus -> physical
    ctrl = LODController(physical_radius=120)

    def dist_xz(a, b):
        return ((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

    band_before = ctrl.band_for(dist_xz(entity_global, focus_global))
    fo.maybe_rebase(focus_global)               # rebase to shrink render coords
    # Semantic (global) position is unchanged; only render coords moved.
    assert fo.to_global(fo.to_render(entity_global)) == entity_global
    band_after = ctrl.band_for(dist_xz(entity_global, focus_global))
    assert band_before == band_after == LODBand.PHYSICAL

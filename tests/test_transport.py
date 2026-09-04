"""Tests for vehicle identity, far-sim, and traffic reconciliation (AS-NAV-3/4)."""
from __future__ import annotations

import math

from asphodel.mobility import Mode, MobilityGraph, RoadSegment
from asphodel.transport import (
    VehicleInstance,
    VehicleFidelity,
    TrafficReconciler,
    point_at_distance,
)
from asphodel.transport.instances import route_polyline, _cumulative


def _corridor(n=4, seg_len=1000.0):
    g = MobilityGraph()
    for i in range(n):
        g.add_node(f"N{i}", (i * seg_len, 0))
    for i in range(n - 1):
        g.add_segment(RoadSegment(f"s{i}", [(i * seg_len, 0), ((i + 1) * seg_len, 0)],
                                  "secondary"), f"N{i}", f"N{i+1}")
    return g


def test_far_sim_advances_route_progress_to_arrival():
    g = _corridor()
    v = VehicleInstance("v1", "car")
    r = g.route("N0", "N3", Mode.CAR)
    v.assign_route(r, g)
    assert v.fidelity == VehicleFidelity.ROUTE_SIMULATED
    assert v.route_progress == 0.0
    for _ in range(2000):
        v.advance_far(1.0, g)
        if v.arrived:
            break
    assert v.arrived and v.route_progress >= 1.0 - 1e-9


def test_identity_and_progress_preserved_across_fidelity_promotion():
    g = _corridor()
    v = VehicleInstance("v42", "car")
    v.assign_route(g.route("N0", "N3", Mode.CAR), g)
    for _ in range(600):
        v.advance_far(1.0, g)
        if v.route_progress > 0.4:
            break
    progress_before = v.route_progress
    v.promote(VehicleFidelity.PHYSICAL_CONTROLLED)
    assert v.vehicle_id == "v42"                      # identity unchanged (§12)
    assert v.route_progress == progress_before        # progress preserved
    v.demote(VehicleFidelity.ROUTE_SIMULATED)
    assert v.vehicle_id == "v42" and v.route_progress == progress_before


def test_reconcile_from_physical_position_round_trips():
    g = _corridor()
    v = VehicleInstance("v1", "car")
    v.assign_route(g.route("N0", "N3", Mode.CAR), g)
    target = point_at_distance(v._pts, v._cum, 1500.0)  # a point on the route
    v.promote(VehicleFidelity.PHYSICAL_CONTROLLED)
    v.reconcile_from_physical(target)
    assert abs(v.distance_along - 1500.0) < 1.0


def test_wreck_becomes_persistent_obstruction_graph_reacts_and_restores():
    g = _corridor()
    # Two ways N0->N3? corridor is a single chain; add a parallel bypass.
    g.add_node("B", (1000, 400))
    g.add_segment(RoadSegment("byp1", [(0, 0), (1000, 400)], "secondary"), "N0", "B")
    g.add_segment(RoadSegment("byp2", [(1000, 400), (3000, 0)], "secondary"), "B", "N3")

    v = VehicleInstance("v1", "car")
    v.assign_route(g.route("N0", "N3", Mode.CAR), g)
    for _ in range(200):
        v.advance_far(1.0, g)
        if v.route_progress > 0.3:
            break
    obs = v.to_wreck(g)
    assert v.fidelity == VehicleFidelity.PERSISTENT_WRECK
    assert obs.affected_segment is not None
    before = g.route("N0", "N3", Mode.CAR)
    g.apply_obstruction(obs)
    after = g.route("N0", "N3", Mode.CAR)
    assert after.cost >= before.cost                  # wreck raises cost / reroutes
    g.clear_obstruction(obs.id)
    restored = g.route("N0", "N3", Mode.CAR)
    assert restored.cost <= after.cost                # towing restores capacity


def test_morning_commute_congestion_emerges_on_shared_segment():
    g = _corridor(n=3)                                 # s0 (N0-N1), s1 (N1-N2)
    tr = TrafficReconciler(g, ref_capacity=4.0)
    for i in range(12):                                # everyone drives N0->N1
        v = VehicleInstance(f"c{i}", "car")
        tr.add_vehicle(v)
        tr.route_vehicle(f"c{i}", g.route("N0", "N1", Mode.CAR))
    factors = tr.update_congestion()
    assert factors["s0"] > 1.3                         # jammed shared segment
    assert factors["s1"] == 1.0                        # nobody there, free flow


def test_congestion_feeds_back_and_slows_far_sim():
    g = _corridor(n=2)
    tr = TrafficReconciler(g, ref_capacity=2.0)
    speeds = []
    for load in (1, 20):
        v = VehicleInstance("probe", "car")
        # add congestion-producing peers
        tr.vehicles.clear()
        tr.add_vehicle(v)
        tr.route_vehicle("probe", g.route("N0", "N1", Mode.CAR))
        for j in range(load):
            p = VehicleInstance(f"p{j}", "car")
            tr.add_vehicle(p)
            tr.route_vehicle(f"p{j}", g.route("N0", "N1", Mode.CAR))
        tr.update_congestion()
        v.advance_far(1.0, g)
        speeds.append(v.speed)
    assert speeds[1] < speeds[0]                        # heavier load => slower

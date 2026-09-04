"""Physics proving-ground acceptance, at the authority level (§18, 14 items).

The scene itself is realized in Godot (unrunnable here), but each of the 14
acceptance criteria reduces to a contract the authorities enforce, which is
tested here. Where an item is a pure in-engine physics behaviour, the test
asserts the contract the Godot body is built from (collision matrix / anti-tunnel
sweep); where it is semantic (obstruction, wreck, materialization) it is exercised
directly on the Python authority.
"""
from __future__ import annotations

import math

from asphodel.physics import BODY_PROFILES, classify_object, physically_blocks
from asphodel.physics.anti_tunneling import swept_segment_hits_aabb
from asphodel.mobility import (
    Mode, MobilityGraph, MobilityObstruction, ObstructionKind, RoadSegment,
)
from asphodel.transport import VehicleInstance, VehicleFidelity
from asphodel.lod import MaterializationRequest, resolve_materialization

P = BODY_PROFILES


def _blocks(a, b):
    return physically_blocks(P[a], P[b])


# 1-3, 6-9: the collision matrix (what Godot bodies are built from).
def test_item01_player_cannot_walk_through_house():
    assert _blocks("player", "world_static")


def test_item02_npc_cannot_walk_through_house():
    assert _blocks("npc", "world_static")


def test_item03_npc_cannot_walk_through_player():
    assert _blocks("npc", "player")


def test_item04_npcs_cannot_overlap_indefinitely():
    assert _blocks("npc", "npc")
    # and a promoted NPC never materializes on top of another
    req = MaterializationRequest("npc2", (0.0, 0.0), radius=0.4,
                                 search_window=6, search_step=0.6)
    res = resolve_materialization(req, occupants=[((0.0, 0.0), 0.4)])
    assert res.ok and res.adjusted and not (
        math.hypot(res.pos[0], res.pos[2]) < 0.8)


def test_item05_npc_can_pass_through_valid_doorway():
    door = classify_object("doorway")
    assert door.navigation and not door.collision


def test_item06_vehicle_cannot_pass_through_building():
    assert _blocks("vehicle", "world_static")


def test_item07_vehicle_cannot_pass_through_vehicle():
    assert _blocks("vehicle", "vehicle")


def test_item08_player_cannot_walk_through_parked_car():
    assert classify_object("parked_vehicle").collision
    assert _blocks("player", "vehicle")


def test_item09_vehicle_physically_contacts_pedestrian():
    assert _blocks("vehicle", "npc") and _blocks("vehicle", "player")


def test_item10_vehicle_cannot_tunnel_thin_barrier():
    barrier = (0.0, -3.0, 0.15, 3.0)      # 15 cm wall
    p0 = (-0.1, 0.0)
    p1 = (0.6, 0.0)                        # a fast frame straight through
    assert swept_segment_hits_aabb(p0, p1, barrier, radius=0.05)


def _graph():
    g = MobilityGraph()
    for nid, xy in [("A", (0, 0)), ("B", (100, 0)), ("C", (50, 80))]:
        g.add_node(nid, xy)
    g.add_segment(RoadSegment("main", [(0, 0), (100, 0)], "secondary"), "A", "B")
    g.add_segment(RoadSegment("byp1", [(0, 0), (50, 80)], "secondary"), "A", "C")
    g.add_segment(RoadSegment("byp2", [(50, 80), (100, 0)], "secondary"), "C", "B")
    return g


def test_item11_wreck_becomes_persistent_obstacle():
    g = _graph()
    v = VehicleInstance("v1", "car")
    v.assign_route(g.route("A", "B", Mode.CAR), g)
    obs = v.to_wreck(g)
    assert v.fidelity == VehicleFidelity.PERSISTENT_WRECK
    assert classify_object("wreck").collision
    assert obs.kind == ObstructionKind.WRECK


def test_item12_mobility_graph_reacts_to_persistent_obstacle():
    g = _graph()
    before = g.route("A", "B", Mode.CAR)
    g.apply_obstruction(MobilityObstruction("o", ObstructionKind.CLOSURE, "main"))
    after = g.route("A", "B", Mode.CAR)
    assert after is not None and "main" not in after.segments  # rerouted


def test_item13_removing_obstruction_restores_path():
    g = _graph()
    g.apply_obstruction(MobilityObstruction("o", ObstructionKind.CLOSURE, "main"))
    g.clear_obstruction("o")
    assert "main" in g.route("A", "B", Mode.CAR).segments


def test_item14_far_to_near_materialization_never_overlaps():
    # A cluster of already-physical agents; a promoted one must not spawn inside.
    occ = [((0.0, 0.0), 0.4), ((0.6, 0.0), 0.4), ((-0.6, 0.0), 0.4)]
    req = MaterializationRequest("late", (0.0, 0.0), radius=0.4,
                                 search_window=8, search_step=0.5)
    res = resolve_materialization(req, occupants=occ)
    assert res.ok
    for (op, orad) in occ:
        assert math.hypot(res.pos[0] - op[0], res.pos[2] - op[1]) >= (0.4 + orad) - 1e-9

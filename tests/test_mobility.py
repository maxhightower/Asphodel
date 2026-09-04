"""Tests for StreetMap V2 / MobilityGraph (AS-NAV-0, §17.2)."""
from __future__ import annotations

import json
import math
import os

import pytest

from asphodel.mobility import (
    Direction,
    Mode,
    MobilityGraph,
    MobilityObstruction,
    ObstructionKind,
    RoadSegment,
)


def _diamond():
    """A --s1-- B --s3-- D  and  A --s2-- C --s4-- D (all bidirectional)."""
    g = MobilityGraph()
    for nid, xy in [("A", (0, 0)), ("B", (100, 50)), ("C", (100, -50)), ("D", (200, 0))]:
        g.add_node(nid, xy)
    g.add_segment(RoadSegment("s1", [(0, 0), (100, 50)], "residential"), "A", "B")
    g.add_segment(RoadSegment("s3", [(100, 50), (200, 0)], "residential"), "B", "D")
    g.add_segment(RoadSegment("s2", [(0, 0), (100, -50)], "residential"), "A", "C")
    g.add_segment(RoadSegment("s4", [(100, -50), (200, 0)], "residential"), "C", "D")
    return g


def test_basic_route_found():
    g = _diamond()
    r = g.route("A", "D", Mode.CAR)
    assert r is not None and r.nodes[0] == "A" and r.nodes[-1] == "D"
    assert r.distance > 0 and r.cost > 0


def test_directed_one_way_blocks_reverse_travel():
    g = MobilityGraph()
    g.add_node("A", (0, 0))
    g.add_node("B", (100, 0))
    g.add_segment(RoadSegment("s", [(0, 0), (100, 0)], "residential",
                              directionality=Direction.FORWARD), "A", "B")
    assert g.route("A", "B", Mode.CAR) is not None      # with the arrow
    assert g.route("B", "A", Mode.CAR) is None           # against it: no path


def test_one_way_forces_detour():
    # Top branch one-way A->B->D only; a D->A trip must use the bottom branch.
    g = MobilityGraph()
    for nid, xy in [("A", (0, 0)), ("B", (100, 50)), ("C", (100, -50)), ("D", (200, 0))]:
        g.add_node(nid, xy)
    g.add_segment(RoadSegment("s1", [(0, 0), (100, 50)], "residential",
                              directionality=Direction.FORWARD), "A", "B")
    g.add_segment(RoadSegment("s3", [(100, 50), (200, 0)], "residential",
                              directionality=Direction.FORWARD), "B", "D")
    g.add_segment(RoadSegment("s2", [(0, 0), (100, -50)], "residential"), "A", "C")
    g.add_segment(RoadSegment("s4", [(100, -50), (200, 0)], "residential"), "C", "D")
    r = g.route("D", "A", Mode.CAR)
    assert r is not None
    assert "s2" in r.segments and "s4" in r.segments  # forced onto the bottom
    assert "s1" not in r.segments


def test_pedestrian_and_vehicle_networks_differ():
    g = MobilityGraph()
    for nid, xy in [("A", (0, 0)), ("B", (100, 0)), ("C", (200, 0))]:
        g.add_node(nid, xy)
    # A->B is a footway (no cars); A->C..? give cars a longer road A->B2->C.
    g.add_node("B2", (100, 80))
    g.add_segment(RoadSegment("foot", [(0, 0), (100, 0)], "footway"), "A", "B")
    g.add_segment(RoadSegment("foot2", [(100, 0), (200, 0)], "footway"), "B", "C")
    g.add_segment(RoadSegment("road1", [(0, 0), (100, 80)], "secondary"), "A", "B2")
    g.add_segment(RoadSegment("road2", [(100, 80), (200, 0)], "secondary"), "B2", "C")

    foot = g.route("A", "C", Mode.FOOT)
    car = g.route("A", "C", Mode.CAR)
    assert foot is not None and car is not None
    assert "foot" in foot.segments               # pedestrians take the footway
    assert "foot" not in car.segments            # cars cannot
    assert "road1" in car.segments


def test_car_only_footway_leaves_car_unrouted():
    g = MobilityGraph()
    g.add_node("A", (0, 0))
    g.add_node("B", (50, 0))
    g.add_segment(RoadSegment("f", [(0, 0), (50, 0)], "footway"), "A", "B")
    assert g.route("A", "B", Mode.FOOT) is not None
    assert g.route("A", "B", Mode.CAR) is None   # no car-legal edge


def test_obstruction_reroutes_and_removal_restores(_kind=ObstructionKind.CLOSURE):
    g = _diamond()
    base = g.route("A", "D", Mode.CAR)
    used = base.segments[0]                       # whichever branch it took first
    obs = MobilityObstruction("o1", ObstructionKind.CLOSURE, affected_segment=used)
    g.apply_obstruction(obs)
    after = g.route("A", "D", Mode.CAR)
    assert after is not None
    assert used not in after.segments             # rerouted around the closure
    g.clear_obstruction("o1")
    restored = g.route("A", "D", Mode.CAR)
    assert used in restored.segments              # capacity restored


def test_partial_obstruction_raises_cost_without_removing_edge():
    g = _diamond()
    seg = "s1"
    before = g.segments[seg].traverse_cost(Mode.CAR)
    g.apply_obstruction(MobilityObstruction("w", ObstructionKind.WRECK, seg, severity=1.0))
    after = g.segments[seg].traverse_cost(Mode.CAR)
    assert after > before and math.isfinite(after)  # slower but still passable


def test_full_closure_makes_segment_impassable():
    g = _diamond()
    g.apply_obstruction(MobilityObstruction("c", ObstructionKind.CLOSURE, "s1"))
    assert not math.isfinite(g.segments["s1"].traverse_cost(Mode.CAR))


def test_congestion_increases_travel_time():
    g = _diamond()
    r0 = g.route("A", "D", Mode.CAR)
    for s in g.segments:                # congest the whole network, no cheap detour
        g.set_congestion(s, 3.0)
    r1 = g.route("A", "D", Mode.CAR)
    assert r1.cost > r0.cost
    assert abs(r1.distance - r0.distance) < 1e-6  # same road, just slower


def test_building_to_road_connectivity():
    g = MobilityGraph()
    g.add_node("R1", (0, 0))
    g.add_node("R2", (300, 0))
    g.add_segment(RoadSegment("road", [(0, 0), (300, 0)], "residential"), "R1", "R2")
    home = g.attach_building("home", (5, 20))
    work = g.attach_building("work", (295, -20))
    assert home == "bldg:home" and work == "bldg:work"
    r = g.route(home, work, Mode.FOOT)
    assert r is not None
    assert r.nodes[0] == "bldg:home" and r.nodes[-1] == "bldg:work"
    assert "road" in r.segments                   # trip uses the road between them


def test_from_polylines_upgrades_legacy_roads_to_routable_graph():
    path = os.path.join(os.path.dirname(__file__), os.pardir,
                        "godot", "bundles", "houston", "roads.json")
    with open(path) as f:
        roads = json.load(f)
    g = MobilityGraph.from_polylines(roads["polylines"], snap=3.0)
    st = g.stats()
    assert st["nodes"] > 0 and st["segments"] > 0 and st["directed_edges"] > 0
    # A route between two real nodes on the same connected polyline chain exists.
    seg = next(iter(g.segments.values()))
    u = g.nearest_node(seg.start)
    v = g.nearest_node(seg.end)
    r = g.route(u, v, Mode.CAR)
    assert r is not None

"""Graph route -> physical path projection (ASPHODEL_EMBODIED_MOBILITY_V1 §11).

The load-bearing claim of `asphodel.embodied.pathing` is that there is **no
invisible road model**: a leg's executable geometry is the rendered street
polyline plus a bounded anchor hop, one-way rules included. These tests prove
that on a synthetic graph small enough to reason about exactly, and then on the
canonical Houston bundle for citizen 4's real DRIVE leg (Gate C spirit: every
driven metre is on a car-legal street the renderer draws).
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodied import MobilityRuntime, load_entrances
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodied.pathing import (MAX_CONNECTOR_M, PhysicalPath, access_point,
                                       attach_anchor, detach_anchor)
from asphodel.embodiment import CitySpatialContext
from asphodel.mobility import Direction, Mode, MobilityGraph, RoadSegment
from asphodel.transport.instances import route_polyline

CITY = "houston"
CITIZEN = 4


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _dist_point_polyline(p, pts) -> float:
    best = math.inf
    for a, b in zip(pts, pts[1:]):
        abx, abz = b[0] - a[0], b[1] - a[1]
        l2 = abx * abx + abz * abz
        if l2 < 1e-12:
            best = min(best, math.hypot(p[0] - a[0], p[1] - a[1]))
            continue
        t = max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * abz) / l2))
        q = (a[0] + abx * t, a[1] + abz * t)
        best = min(best, math.hypot(p[0] - q[0], p[1] - q[1]))
    if len(pts) == 1:
        best = math.hypot(p[0] - pts[0][0], p[1] - pts[0][1])
    return best


def _synthetic() -> MobilityGraph:
    """A four-node city:  A --s_AB-- B ==s_BC=> C   and   B --s_BD-- D.

    ``s_BC`` is one-way in polyline order (B -> C).
    """
    g = MobilityGraph()
    for nid, xy in (("A", (0.0, 0.0)), ("B", (100.0, 0.0)),
                    ("C", (200.0, 0.0)), ("D", (100.0, 100.0))):
        g.add_node(nid, xy)
    g.add_segment(RoadSegment("s_AB", [(0.0, 0.0), (100.0, 0.0)], "residential"), "A", "B")
    g.add_segment(RoadSegment("s_BC", [(100.0, 0.0), (200.0, 0.0)], "residential",
                              Direction.FORWARD), "B", "C")
    g.add_segment(RoadSegment("s_BD", [(100.0, 0.0), (100.0, 100.0)], "residential"), "B", "D")
    return g


# --------------------------------------------------------------------------- #
# 1. projection
# --------------------------------------------------------------------------- #
def test_access_point_projects_onto_the_polyline():
    g = _synthetic()
    ap = access_point(g, (150.0, 8.0), Mode.CAR)
    assert ap is not None
    assert ap.segment_id == "s_BC"
    # the projection is ON the street polyline, not near it
    assert _dist_point_polyline(ap.on_street_xy, g.segments["s_BC"].polyline) < 1e-9
    assert ap.on_street_xy == pytest.approx((150.0, 0.0))
    assert ap.along == pytest.approx(50.0)
    assert ap.connector_m == pytest.approx(8.0)
    assert ap.mode is Mode.CAR
    # an anchor beyond the connector budget is not "at" a street
    assert access_point(g, (400.0, 400.0), Mode.CAR) is None
    # a car cannot project onto a foot-only street
    g2 = MobilityGraph()
    g2.add_node("X", (0.0, 0.0))
    g2.add_node("Y", (50.0, 0.0))
    g2.add_segment(RoadSegment("foot", [(0.0, 0.0), (50.0, 0.0)], "footway"), "X", "Y")
    assert access_point(g2, (25.0, 2.0), Mode.FOOT) is not None
    assert access_point(g2, (25.0, 2.0), Mode.CAR) is None


def test_attach_anchor_makes_real_partial_polylines():
    g = _synthetic()
    got = attach_anchor(g, "park:1", (150.0, 8.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    assert got is not None
    node, ap = got
    assert node == "park:1" and g.nodes["park:1"] == (150.0, 8.0)
    up = g.segments["conn:park:1:1"]      # toward polyline end (node C)
    down = g.segments["conn:park:1:0"]    # toward polyline start (node B)
    # anchor -> kerb hop, then the REAL street polyline to the junction
    assert list(up.polyline) == [(150.0, 8.0), (150.0, 0.0), (200.0, 0.0)]
    assert list(down.polyline) == [(150.0, 8.0), (150.0, 0.0), (100.0, 0.0)]
    assert up.length == pytest.approx(8.0 + 50.0)
    assert down.length == pytest.approx(8.0 + 50.0)
    # class/speed inherited from the street it hangs off
    assert up.road_class == g.segments["s_BC"].road_class
    assert up.speed_limit == g.segments["s_BC"].speed_limit
    # idempotent
    again = attach_anchor(g, "park:1", (150.0, 8.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    assert again == (node, ap)
    detach_anchor(g, "park:1")
    assert "park:1" not in g.nodes and not [s for s in g.segments if s.startswith("conn:")]


def test_one_way_street_yields_one_way_connectors():
    g = _synthetic()
    attach_anchor(g, "park:1", (150.0, 8.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    assert g.segments["conn:park:1:1"].directionality is Direction.FORWARD    # out only
    assert g.segments["conn:park:1:0"].directionality is Direction.BACKWARD   # in only
    # a car may leave with the traffic ...
    car_out = g.route("park:1", "C", Mode.CAR)
    assert car_out is not None and car_out.segments == ["conn:park:1:1"]
    # ... and may NOT route out against it (there is no legal way back to B)
    assert g.route("park:1", "B", Mode.CAR) is None
    assert g.route("park:1", "D", Mode.CAR) is None
    # a pedestrian uses the bidirectional foot twin
    walk = g.route("park:1", "B", Mode.FOOT)
    assert walk is not None
    assert all(s.startswith("conn:park:1:") for s in walk.segments)
    twin = g.segments[walk.segments[0]]
    assert twin.directionality is Direction.BIDIRECTIONAL
    assert twin.allowed_modes == {Mode.FOOT}
    assert g.route("park:1", "D", Mode.FOOT) is not None


# --------------------------------------------------------------------------- #
# 2. the physical path is the street geometry
# --------------------------------------------------------------------------- #
def test_physical_path_points_lie_on_real_geometry():
    g = _synthetic()
    attach_anchor(g, "ent:9", (10.0, -4.0), [Mode.FOOT], Mode.FOOT)
    route = g.route("ent:9", "D", Mode.FOOT)
    assert route is not None
    path = PhysicalPath.from_route(g, route)
    assert path.length > 0
    for p in path.points:
        best = min(_dist_point_polyline(p, s.polyline) for s in g.segments.values())
        assert best < 1e-6, f"point {p} is not on any rendered polyline ({best:.4f} m)"
    # cumulative geometry is consistent with the reported length
    assert path.cum[-1] == pytest.approx(path.length)
    assert path.point_at(0.0) == pytest.approx(path.points[0])
    assert path.point_at(path.length) == pytest.approx(path.points[-1])


def test_route_polyline_equals_path_points_without_shortcut():
    g = _synthetic()
    route = g.route("A", "C", Mode.FOOT)
    assert route is not None and route.segments == ["s_AB", "s_BC"]
    path = PhysicalPath.from_route(g, route)
    assert [tuple(p) for p in path.points] == [tuple(p) for p in route_polyline(g, route)]
    assert path.street_segments() == ["s_AB", "s_BC"]
    assert path.length == pytest.approx(200.0)


def test_same_street_shortcut_is_the_direct_distance():
    g = _synthetic()
    attach_anchor(g, "p:P", (30.0, -5.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    attach_anchor(g, "p:Q", (70.0, -5.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    for mode in (Mode.FOOT, Mode.CAR):
        route = g.route("p:P", "p:Q", mode)
        assert route is not None
        # the graph route detours via a junction ...
        assert route.distance == pytest.approx(110.0)
        assert route.nodes[1] in ("A", "B")
        path = PhysicalPath.from_route(g, route)
        # ... the executed path does not: 5 m out + 40 m along the street + 5 m in
        assert path.length == pytest.approx(50.0)
        assert [tuple(p) for p in path.points] == [(30.0, -5.0), (30.0, 0.0),
                                                   (70.0, 0.0), (70.0, -5.0)]
        assert path.street_segments() == ["s_AB"]
        for p in path.points:
            assert min(_dist_point_polyline(p, s.polyline)
                       for s in g.segments.values()) < 1e-6


def test_one_way_shortcut_is_not_taken_against_traffic():
    """Two anchors on a one-way street: the shortcut only applies with traffic."""
    g = _synthetic()
    attach_anchor(g, "p:X", (120.0, 6.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    attach_anchor(g, "p:Y", (180.0, 6.0), [Mode.CAR, Mode.FOOT], Mode.CAR)
    # walking backwards down the one-way street is legal for a pedestrian and
    # the shortcut is the direct 60 m + two 6 m hops.
    back = g.route("p:Y", "p:X", Mode.FOOT)
    assert back is not None
    path = PhysicalPath.from_route(g, back)
    assert path.length == pytest.approx(72.0)
    # for a car the same geometry is illegal, and the route itself does not exist.
    assert g.route("p:Y", "p:X", Mode.CAR) is None


def test_add_segment_index_flag_preserves_the_grid():
    g = _synthetic()
    assert g._grid is None
    g.nearest_segment_point((10.0, 10.0), Mode.FOOT)
    assert g._grid is not None
    g.add_node("E", (0.0, 100.0))
    g.add_segment(RoadSegment("conn:x", [(0.0, 0.0), (0.0, 100.0)], "residential"),
                  "A", "E", index=False)
    assert g._grid is not None, "index=False must not force a city-wide reindex"
    # the un-indexed connector is routable but is never a 'where am I' answer
    assert g.route("A", "E", Mode.FOOT) is not None
    hit = g.nearest_segment_point((0.0, 50.0), Mode.FOOT)
    assert hit is not None and hit[0] != "conn:x"
    # ... and a real geometry change still drops the index
    g.add_segment(RoadSegment("s_DE", [(100.0, 100.0), (0.0, 100.0)], "residential"),
                  "D", "E")
    assert g._grid is None


# --------------------------------------------------------------------------- #
# 3. Houston: citizen 4's real DRIVE leg (Gate C spirit)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def houston():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    ctx = CitySpatialContext.from_bundle_dir(d)
    ent, anchors = load_entrances(d)
    pop = load_bundle_population(d)
    return d, ctx, ent, anchors, pop


@pytest.fixture(scope="module")
def drive_path(houston):
    """The PhysicalPath citizen 4 is actually driving on the morning commute."""
    d, ctx, ent, anchors, pop = houston
    rt = MobilityRuntime(ctx.street_graph, ent, anchors, ctx=ctx, bundle_dir=d)
    prof = next(c for c in pop if int(c.citizen_id) == CITIZEN)
    assert rt.register(prof, 7.45)
    hour = 7.45
    ex = rt.execs[CITIZEN]
    for _ in range(200):
        rt.advance(10.0, hour)
        hour = (hour + 10.0 / 3600.0) % 24.0
        if ex.state is EmbodimentState.DRIVING and ex.car is not None:
            break
    assert ex.state is EmbodimentState.DRIVING, f"citizen {CITIZEN} never drove"
    return rt, ex.car.path


def test_houston_drive_path_is_car_legal_street_geometry(drive_path):
    rt, path = drive_path
    graph = rt.graph
    streets = path.street_segments()
    assert len(streets) > 10, "the commute should use real streets"
    for sid in streets:
        seg = graph.segments[sid]
        assert seg.allows(Mode.CAR), f"{sid} is not car-legal"
    # every executed point sits on the polyline of the segment it belongs to
    worst = 0.0
    for sid, s0, s1 in path.segments:
        poly = graph.segments[sid].polyline
        for p, c in zip(path.points, path.cum):
            if s0 - 1e-6 <= c <= s1 + 1e-6:
                worst = max(worst, _dist_point_polyline(p, poly))
    assert worst <= 0.5, f"driven point {worst:.3f} m off its own street polyline"


def test_houston_drive_path_connectors_are_bounded(drive_path):
    rt, path = drive_path
    conns = [s for s, _, _ in path.segments if s.startswith("conn:")]
    assert len(conns) <= 2, "only the two anchor hops may be connectors"
    for sid in conns:
        ap = rt.graph.__dict__["_access_points"].get(sid.split(":", 1)[1].rsplit(":", 1)[0])
        if ap is not None:
            assert ap.connector_m <= MAX_CONNECTOR_M
    assert path.mode is Mode.CAR
    assert path.length > 100.0

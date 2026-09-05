"""Tests for the canonical street-graph bake (AS-NAV-0 §5, §17).

These pin the contract that makes the rendered city and the routable city the
same city: roads split at their shared connectors, one-ways that really are
one-way, and a version-2 artifact whose geometry survives the round trip so
Python and the client measure the same street.
"""
from __future__ import annotations

import math

import pytest

from asphodel.mobility import Direction, Mode, MobilityGraph
from asphodel.mobility.bake import (
    streetmap_from_polylines,
    streetmap_from_world_source,
)
from asphodel.world_source.schema import Feature, WorldSourceV1


# -- synthetic world source ---------------------------------------------------
def _feature(key, pts, connectors, cls="residential", oneway=None):
    return Feature(
        stable_key=key, geometry=[(float(x), float(z)) for x, z in pts],
        geom_type="line",
        properties={"class": cls, "subtype": "road", "width_m": None,
                    "lanes_total": None, "connectors": connectors,
                    "oneway": oneway},
        source="test/segment", source_id=key,
    )


def _connector(key, xy):
    return Feature(stable_key=key, geometry=[xy], geom_type="point",
                   properties={}, source="test/connector", source_id=key)


def _crossing_ws(oneway_ns=None):
    """Two roads crossing at a shared mid connector X.

    EW runs (-100, 0) -> (100, 0); NS runs (0, -100) -> (0, 100). Both list the
    same connector X at at=0.5, plus their own endpoint connectors.
    """
    ws = WorldSourceV1()
    ws.meta = {"city": "synthetic", "release": "test"}
    ws.connectors = [
        _connector("W", (-100.0, 0.0)),
        _connector("E", (100.0, 0.0)),
        _connector("S", (0.0, -100.0)),
        _connector("N", (0.0, 100.0)),
        _connector("X", (0.0, 0.0)),
    ]
    ws.roads = [
        _feature("EW", [(-100, 0), (0, 0), (100, 0)],
                 [["W", 0.0], ["X", 0.5], ["E", 1.0]]),
        _feature("NS", [(0, -100), (0, 0), (0, 100)],
                 [["S", 0.0], ["X", 0.5], ["N", 1.0]], oneway=oneway_ns),
    ]
    return ws


def test_crossing_roads_split_into_four_segments_over_five_nodes():
    art = streetmap_from_world_source(_crossing_ws(), "test")
    assert art["version"] == 2
    assert art["frame"] == "bundle_metres"
    assert art["source"] == "test"
    assert len(art["segments"]) == 4
    assert len(art["nodes"]) == 5
    assert set(art["nodes"]) == {"W", "E", "S", "N", "X"}
    assert art["nodes"]["X"] == [0.0, 0.0]

    by_id = {s["id"]: s for s in art["segments"]}
    assert set(by_id) == {"EW#0", "EW#1", "NS#0", "NS#1"}
    assert by_id["EW#0"]["u"] == "W" and by_id["EW#0"]["v"] == "X"
    assert by_id["EW#0"]["pts"] == [[-100.0, 0.0], [0.0, 0.0]]
    assert by_id["EW#1"]["pts"] == [[0.0, 0.0], [100.0, 0.0]]
    assert by_id["NS#0"]["pts"] == [[0.0, -100.0], [0.0, 0.0]]
    for s in art["segments"]:
        assert s["length"] == pytest.approx(100.0, abs=0.01)


def test_segments_and_nodes_are_sorted_for_determinism():
    art = streetmap_from_world_source(_crossing_ws(), "test")
    ids = [s["id"] for s in art["segments"]]
    assert ids == sorted(ids)
    assert list(art["nodes"]) == sorted(art["nodes"])
    again = streetmap_from_world_source(_crossing_ws(), "test")
    assert art == again


def test_crossing_graph_routes_through_the_shared_connector():
    g = MobilityGraph.from_artifact(streetmap_from_world_source(_crossing_ws(), "t"))
    r = g.route("W", "N", Mode.CAR)
    assert r is not None
    assert r.nodes == ["W", "X", "N"]
    assert r.distance == pytest.approx(200.0, abs=0.02)


def test_one_way_road_is_routable_forward_only():
    art = streetmap_from_world_source(_crossing_ws(oneway_ns="forward"), "t")
    by_id = {s["id"]: s for s in art["segments"]}
    assert by_id["NS#0"]["directionality"] == "forward"
    assert by_id["EW#0"]["directionality"] == "bidirectional"
    assert art["stats"]["oneway_segments"] == 2

    g = MobilityGraph.from_artifact(art)
    assert g.route("S", "N", Mode.CAR) is not None       # with the arrow
    assert g.route("N", "S", Mode.CAR) is None           # against it


def test_backward_one_way_reverses_the_legal_direction():
    art = streetmap_from_world_source(_crossing_ws(oneway_ns="backward"), "t")
    g = MobilityGraph.from_artifact(art)
    assert g.route("N", "S", Mode.CAR) is not None
    assert g.route("S", "N", Mode.CAR) is None


def test_missing_endpoint_connector_still_gets_a_node():
    ws = WorldSourceV1()
    ws.connectors = [_connector("M", (50.0, 0.0))]
    # Only a mid connector: both ends must still become nodes, keyed off the road.
    ws.roads = [_feature("R", [(0, 0), (100, 0)], [["M", 0.5]])]
    art = streetmap_from_world_source(ws, "t")
    assert set(art["nodes"]) == {"R@0", "M", "R@2"}
    assert art["nodes"]["R@0"] == [0.0, 0.0]
    assert art["nodes"]["R@2"] == [100.0, 0.0]
    assert [s["id"] for s in art["segments"]] == ["R#0", "R#1"]


def test_connector_absent_from_the_connector_table_falls_back_to_interpolation():
    ws = WorldSourceV1()
    ws.connectors = []              # the packet clipped the connector rows away
    ws.roads = [_feature("R", [(0, 0), (100, 0)], [["A", 0.0], ["B", 0.25],
                                                   ["C", 1.0]])]
    art = streetmap_from_world_source(ws, "t")
    assert art["nodes"]["B"] == [25.0, 0.0]


def test_class_defaults_cover_the_overture_classes():
    ws = WorldSourceV1()
    ws.connectors = []
    ws.roads = [
        _feature(c, [(0, 0), (10, 0)], [["a" + c, 0.0], ["b" + c, 1.0]], cls=c)
        for c in ("unclassified", "living_street", "track", "steps",
                  "cycleway", "bridleway", "unknown", "footway", "path")
    ]
    art = streetmap_from_world_source(ws, "t")
    modes = {s["class"]: set(s["modes"]) for s in art["segments"]}
    for c in ("steps", "footway", "path", "cycleway", "bridleway"):
        assert "car" not in modes[c], c
        assert "foot" in modes[c], c
    for c in ("unclassified", "living_street", "track", "unknown"):
        assert "car" in modes[c], c
    by_id = {s["class"]: s for s in art["segments"]}
    assert by_id["unknown"]["speed_limit"] == 8.0      # behaves like residential
    assert by_id["unknown"]["lanes"] == 1


# -- artifact round trip ------------------------------------------------------
def test_v2_round_trip_preserves_pts_and_length():
    ws = WorldSourceV1()
    ws.connectors = [_connector("A", (0.0, 0.0)), _connector("B", (0.0, 60.0))]
    # A dog-legged road: a 2-point rebuild would understate its length badly.
    ws.roads = [_feature("R", [(0, 0), (40, 0), (40, 60), (0, 60)],
                         [["A", 0.0], ["B", 1.0]])]
    art = streetmap_from_world_source(ws, "t")
    seg = art["segments"][0]
    assert seg["pts"] == [[0.0, 0.0], [40.0, 0.0], [40.0, 60.0], [0.0, 60.0]]
    assert seg["length"] == pytest.approx(140.0, abs=0.01)

    g = MobilityGraph.from_artifact(art)
    rebuilt = g.segments["R#0"]
    assert [list(p) for p in rebuilt.polyline] == seg["pts"]
    assert rebuilt.length == pytest.approx(seg["length"], abs=1e-2)

    route = g.route("A", "B", Mode.CAR)
    assert route.distance == pytest.approx(seg["length"], abs=1e-2)
    assert route.distance > 100.0                    # not the 60 m straight line


def test_route_length_equals_the_sum_of_baked_lengths():
    art = streetmap_from_world_source(_crossing_ws(), "t")
    g = MobilityGraph.from_artifact(art)
    baked = {s["id"]: s["length"] for s in art["segments"]}
    r = g.route("W", "E", Mode.CAR)
    assert r.distance == pytest.approx(sum(baked[s] for s in r.segments), abs=1e-2)


def test_unknown_version_raises():
    art = streetmap_from_world_source(_crossing_ws(), "t")
    art["version"] = 99
    with pytest.raises(ValueError, match="unsupported streetmap version"):
        MobilityGraph.from_artifact(art)


def test_missing_version_raises():
    art = streetmap_from_world_source(_crossing_ws(), "t")
    del art["version"]
    with pytest.raises(ValueError, match="no 'version' field"):
        MobilityGraph.from_artifact(art)


def test_legacy_version_1_artifact_still_loads():
    art = {
        "version": "1",
        "nodes": {"A": [0.0, 0.0], "B": [100.0, 0.0]},
        "segments": [{"id": "s0", "u": "A", "v": "B", "class": "residential",
                      "length": 100.0, "directionality": "bidirectional",
                      "modes": ["car", "foot"], "speed_limit": 8.0, "lanes": 1}],
        "stats": {},
    }
    g = MobilityGraph.from_artifact(art)
    assert g.version == 1
    assert g.segments["s0"].length == pytest.approx(100.0)
    assert g.route("A", "B", Mode.CAR) is not None


# -- the legacy polyline bake -------------------------------------------------
def _legacy_roads():
    return {"polylines": [
        {"points": [[0, 0], [50, 20], [100, 0]], "class": "secondary"},
        {"points": [[100, 0], [100, 100]], "class": "residential",
         "oneway": True},
    ]}


def test_from_polylines_keeps_intermediate_points():
    art = streetmap_from_polylines(_legacy_roads(), "legacy")
    assert art["version"] == 2
    assert art["source"] == "legacy"
    seg = next(s for s in art["segments"] if s["id"] == "seg0")
    assert seg["pts"] == [[0.0, 0.0], [50.0, 20.0], [100.0, 0.0]]
    # The bend is real length, not the 100 m chord.
    assert seg["length"] == pytest.approx(2 * math.hypot(50, 20), abs=0.01)


def test_from_polylines_snaps_shared_endpoints_into_one_node():
    art = streetmap_from_polylines(_legacy_roads(), "legacy")
    by_id = {s["id"]: s for s in art["segments"]}
    assert by_id["seg0"]["v"] == by_id["seg1"]["u"]
    assert by_id["seg1"]["directionality"] == "forward"
    g = MobilityGraph.from_artifact(art)
    assert g.route(by_id["seg0"]["u"], by_id["seg1"]["v"], Mode.CAR) is not None


def test_from_polylines_is_deterministic():
    a = streetmap_from_polylines(_legacy_roads(), "legacy")
    b = streetmap_from_polylines(_legacy_roads(), "legacy")
    assert a == b


# -- nearest_segment_point ----------------------------------------------------
def test_nearest_segment_point_projects_onto_the_polyline_not_a_node():
    g = MobilityGraph.from_artifact(
        streetmap_from_world_source(_crossing_ws(), "t"))
    hit = g.nearest_segment_point((50.0, 7.0))
    assert hit is not None
    sid, pt, dist = hit
    assert sid == "EW#1"
    assert pt == pytest.approx((50.0, 0.0), abs=1e-6)
    assert dist == pytest.approx(7.0, abs=1e-6)


def test_nearest_segment_point_honours_mode_access():
    ws = WorldSourceV1()
    ws.connectors = [_connector("A", (0.0, 0.0)), _connector("B", (100.0, 0.0)),
                     _connector("C", (0.0, 40.0)), _connector("D", (100.0, 40.0))]
    ws.roads = [
        _feature("F", [(0, 0), (100, 0)], [["A", 0.0], ["B", 1.0]], cls="footway"),
        _feature("R", [(0, 40), (100, 40)], [["C", 0.0], ["D", 1.0]], cls="residential"),
    ]
    g = MobilityGraph.from_artifact(streetmap_from_world_source(ws, "t"))
    assert g.nearest_segment_point((50.0, 5.0))[0] == "F#0"
    assert g.nearest_segment_point((50.0, 5.0), Mode.CAR)[0] == "R#0"


def test_nearest_segment_point_matches_a_brute_force_scan():
    ws = _crossing_ws()
    g = MobilityGraph.from_artifact(streetmap_from_world_source(ws, "t"))
    for q in [(-300.0, -300.0), (0.0, 0.0), (99.0, 1.0), (5.0, -70.0),
              (1000.0, 1000.0)]:
        sid, pt, dist = g.nearest_segment_point(q)
        brute = min(
            (MobilityGraph._project_on_polyline(s.polyline, q)[1]
             for s in g.segments.values()))
        assert dist == pytest.approx(math.sqrt(brute), abs=1e-6)


def test_nearest_segment_point_on_an_empty_graph_is_none():
    assert MobilityGraph().nearest_segment_point((0.0, 0.0)) is None

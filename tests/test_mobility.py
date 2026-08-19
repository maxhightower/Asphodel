"""
Real-road zone-mobility tests.

Covers the road->zone derivation (crossings only, class capacity, aggregation,
determinism, disconnection), the engine consuming an explicit sparse mobility
graph (backward-compatible grid fallback), that real-road topology materially
changes epidemic propagation, and that population is still conserved exactly.

Run with:  python -m pytest tests/test_mobility.py -q
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.osm_city.mobility import (
    GridIndex, derive_road_edges, build_mobility_edges, derive_zone_mobility,
    mobility_stats, road_capacity,
)
from asphodel.config import ScenarioConfig, ModelParams, GraphParams
from asphodel.graph import ZoneGraph
from asphodel.runner import run_scenario
from asphodel import World, MicroParams


def _grid_1xN(n):
    # A 1 x n metre grid of 100 m cells starting at the origin.
    return GridIndex(rows=1, cols=n, x_min=0.0, z_min=0.0, cell_w=100.0, cell_h=100.0)


def _road(cls, pts):
    return {"class": cls, "points": pts}


# --------------------------------------------------------------------------- #
# 1. straight road A-B-C -> A<->B and B<->C, never A<->C
# --------------------------------------------------------------------------- #
def test_straight_road_links_only_adjacent_transitions():
    grid = _grid_1xN(3)                                  # zones 0,1,2
    edges = derive_road_edges(grid, [_road("primary", [[50, 50], [250, 50]])])
    assert set(edges.keys()) == {(0, 1), (1, 2)}
    assert (0, 2) not in edges


# --------------------------------------------------------------------------- #
# 2. no connecting road -> adjacent cells get NO road edge
# --------------------------------------------------------------------------- #
def test_no_road_no_edge():
    grid = _grid_1xN(3)
    # A road wholly inside zone 0 (never crosses a boundary).
    edges = derive_road_edges(grid, [_road("primary", [[10, 50], [40, 50]])])
    assert edges == {}


# --------------------------------------------------------------------------- #
# 3. multiple / stronger roads -> higher weight
# --------------------------------------------------------------------------- #
def test_multiple_roads_aggregate_weight():
    grid = _grid_1xN(2)
    one = derive_road_edges(grid, [_road("secondary", [[50, 50], [150, 50]])])
    two = derive_road_edges(grid, [
        _road("secondary", [[50, 50], [150, 50]]),
        _road("secondary", [[50, 70], [150, 70]]),
    ])
    assert two[(0, 1)] > one[(0, 1)]
    assert abs(two[(0, 1)] - 2 * one[(0, 1)]) < 1e-9


def test_road_class_capacity_ordering():
    grid = _grid_1xN(2)
    mo = derive_road_edges(grid, [_road("motorway", [[50, 50], [150, 50]])])[(0, 1)]
    re = derive_road_edges(grid, [_road("residential", [[50, 50], [150, 50]])])[(0, 1)]
    assert mo > re
    assert road_capacity("motorway") > road_capacity("primary") > road_capacity("residential")


# --------------------------------------------------------------------------- #
# 4. determinism
# --------------------------------------------------------------------------- #
def test_derivation_is_deterministic():
    grid = _grid_1xN(4)
    roads = [_road("primary", [[50, 50], [350, 50]]),
             _road("trunk", [[350, 60], [50, 60]])]
    a = build_mobility_edges(grid, derive_road_edges(grid, roads), local_floor=0.1,
                             populated=[True] * 4)
    b = build_mobility_edges(grid, derive_road_edges(grid, roads), local_floor=0.1,
                             populated=[True] * 4)
    assert a == b


# --------------------------------------------------------------------------- #
# 5. floor gates on population; empty cells are not conduits
# --------------------------------------------------------------------------- #
def test_local_floor_skips_empty_cells():
    grid = _grid_1xN(3)
    # No roads; only the floor. Middle cell empty -> it must not gain floor edges.
    edges = build_mobility_edges(grid, {}, local_floor=0.2,
                                 populated=[True, False, True])
    pairs = {(a, b) for a, b, w in edges}
    assert (0, 1) not in pairs and (1, 2) not in pairs   # empty middle is inert


# --------------------------------------------------------------------------- #
# 6. disconnected regions -> stats sane, no crash
# --------------------------------------------------------------------------- #
def test_disconnected_stats():
    # zones 0-1 linked, 2-3 linked, 4 isolated.
    edges = [[0, 1, 1.0], [2, 3, 1.0]]
    st = mobility_stats(edges, 5)
    assert st["connected_components"] == 3        # {0,1},{2,3},{4}
    assert st["isolated_zones"] == 1
    assert st["n_edges"] == 2


# --------------------------------------------------------------------------- #
# 7. the engine consumes explicit edges; grid fallback is unchanged
# --------------------------------------------------------------------------- #
def test_explicit_edges_build_symmetric_weights():
    gp = GraphParams(grid_rows=1, grid_cols=3, mobility_edges=[[0, 1, 3.0], [1, 2, 5.0]])
    g = ZoneGraph(gp)
    assert g.topology_kind == "explicit"
    assert g.weights[0, 1] == 3.0 and g.weights[1, 0] == 3.0
    assert g.weights[1, 2] == 5.0 and g.weights[2, 1] == 5.0
    assert g.weights[0, 2] == 0.0                 # no edge -> no coupling


def test_grid_fallback_unchanged_without_edges():
    gp = GraphParams(grid_rows=4, grid_cols=4)     # no mobility_edges
    g = ZoneGraph(gp)
    assert g.topology_kind == "grid"
    # 4-neighbour grid weights, exactly as before this feature existed.
    assert g.weights[0, 1] == 1.0 and g.weights[0, 4] == 1.0
    assert g.weights[0, 5] == 0.0                  # diagonal not connected


def test_negative_weight_rejected():
    import pytest
    with pytest.raises(ValueError):
        ZoneGraph(GraphParams(grid_rows=1, grid_cols=2, mobility_edges=[[0, 1, -1.0]]))


# --------------------------------------------------------------------------- #
# 8. road topology MATERIALLY changes propagation
# --------------------------------------------------------------------------- #
def _two_zone_config(edges):
    return ScenarioConfig(
        model=ModelParams(graph=GraphParams(
            grid_rows=1, grid_cols=2, population=[1000.0, 1000.0],
            mobility_edges=edges)),
        n_days=30.0, seed_zone=0,
    )


def test_road_connection_changes_who_gets_infected():
    # Map 1: A === B (strong road). Map 2: A | B (no road edge at all).
    linked = run_scenario(_two_zone_config([[0, 1, 8.0]]))
    isolated = run_scenario(_two_zone_config([]))       # [] -> all-zero coupling

    def infected_in_B(res):
        return res.sim.N0[1] - res.sim.S[1]              # people who left S in zone B

    assert infected_in_B(linked) > 50.0, infected_in_B(linked)
    assert infected_in_B(isolated) < 1e-6, infected_in_B(isolated)
    # And zone A (the seed) burns in both cases regardless of the link.
    assert linked.sim.N0[0] - linked.sim.S[0] > 50.0


# --------------------------------------------------------------------------- #
# 9. conservation with road mobility (macro-only and macro+micro)
# --------------------------------------------------------------------------- #
def _total(sim):
    return float(sim.S.sum() + sim.E.sum() + sim.Ia.sum()
                 + sim.Is.sum() + sim.R.sum() + sim.D.sum())


def test_macro_conservation_with_mobility():
    res = run_scenario(_two_zone_config([[0, 1, 4.0]]), record_belief=False)
    assert abs(_total(res.sim) - 2000.0) < 1e-6


def test_macro_micro_conservation_with_mobility():
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(
            grid_rows=2, grid_cols=2, population=[1000.0, 1000.0, 1000.0, 1000.0],
            mobility_edges=[[0, 1, 5.0], [1, 3, 5.0], [0, 2, 2.0], [2, 3, 2.0]])),
        n_days=40.0, seed_zone=0,
    )
    w = World(cfg, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                            mixing_step_frac=0.12), seed=1)
    N0 = 4000.0
    last = None
    for _ in range(int(40.0 / cfg.dt)):
        last = w.step()
        assert abs(last.total_pop - N0) < 1e-6, last.total_pop
    assert last.D > 0                                    # something actually happened


# --------------------------------------------------------------------------- #
# 10. real committed cities produce distinct road-derived graphs
# --------------------------------------------------------------------------- #
def _bundle_graph(city):
    import json
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "godot", "bundles", city)
    zones = json.load(open(os.path.join(d, "zones.json")))
    roads = json.load(open(os.path.join(d, "roads.json")))
    meta = json.load(open(os.path.join(d, "meta.json")))
    rows, cols = meta["grid"]["rows"], meta["grid"]["cols"]
    zones = sorted(zones, key=lambda z: z["id"])
    edges = derive_zone_mobility(zones, roads.get("polylines", []), rows, cols,
                                 local_floor=0.1)
    return mobility_stats(edges, rows * cols), edges


def test_houston_and_madisonville_graphs_differ_materially():
    hou, _ = _bundle_graph("houston")
    mad, _ = _bundle_graph("madisonville_tx")
    # The metropolis has far more mobility edges and a denser, connected graph;
    # the small town is sparser and fragments into components.
    assert hou["n_edges"] > 2 * mad["n_edges"], (hou["n_edges"], mad["n_edges"])
    assert hou["connected_components"] < mad["connected_components"]
    assert hou["max_weight"] > 0 and mad["max_weight"] > 0


def test_derivation_deterministic_on_real_bundle():
    a, ea = _bundle_graph("houston")
    b, eb = _bundle_graph("houston")
    assert ea == eb and a == b


# --------------------------------------------------------------------------- #
# 11. the bundle persists the exact mobility graph used for the sim
# --------------------------------------------------------------------------- #
def test_build_bundle_persists_mobility(tmp_path):
    import json
    from asphodel.osm_city import overpass as ov
    from asphodel.osm_city import pipeline as pipe

    fixture = {"elements": [
        {"type": "way", "tags": {"building": "yes", "building:levels": "3"},
         "geometry": [{"lat": 40.0, "lon": -73.0}, {"lat": 40.0, "lon": -73.004},
                      {"lat": 40.004, "lon": -73.004}, {"lat": 40.004, "lon": -73.0}]},
        {"type": "way", "tags": {"highway": "primary"},
         "geometry": [{"lat": 40.0, "lon": -73.0}, {"lat": 40.01, "lon": -73.01}]},
    ]}
    buildings, roads = ov.parse_osm(fixture)
    out = tmp_path / "city"
    pipe.build_bundle(query="Toy", bbox=(40.0, -73.01, 40.01, -73.0),
                      buildings=buildings, roads=roads, out_dir=str(out),
                      grid=4, total_pop=20000.0, seed=0, n_days=8.0,
                      bake_citizens=False)
    m = json.loads((out / "mobility.json").read_text())
    assert m["version"] == 1
    assert isinstance(m["edges"], list)
    for e in m["edges"]:
        assert len(e) == 3 and e[2] >= 0.0
    meta = json.loads((out / "meta.json").read_text())
    assert meta["mobility"]["n_edges"] == len(m["edges"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

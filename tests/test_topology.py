"""
Phase 7 tests: swappable topology, heterogeneous population, and multi-seed
outbreaks.

Run with:  python -m pytest tests/test_topology.py -q
       or:  python tests/test_topology.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import ScenarioConfig, ZoneGraph, GraphParams, Simulation, run_scenario


def _mix_is_valid(graph):
    rs = graph.mix.sum(axis=1)
    # Rows sum to 1 (every zone has neighbours here) and the diagonal is zero.
    assert np.allclose(rs, 1.0), rs
    assert np.allclose(np.diag(graph.mix), 0.0)


# --------------------------------------------------------------------------- #
# topology construction
# --------------------------------------------------------------------------- #
def test_grid_topology_unchanged():
    g = ZoneGraph(GraphParams(grid_rows=8, grid_cols=8, topology="grid"))
    _mix_is_valid(g)
    # 4-neighbour grid: corners have 2 neighbours, interior 4.
    assert len(g.neighbors(0)) == 2
    assert len(g.neighbors(g.index(4, 4))) == 4


def test_small_world_adds_long_range_edges():
    gp = GraphParams(grid_rows=8, grid_cols=8, topology="small_world",
                     rewire_prob=0.3, topology_seed=1)
    g = ZoneGraph(gp)
    _mix_is_valid(g)
    # At least one edge must connect non-grid-adjacent zones (|dr|+|dc| > 1).
    long_range = 0
    for i in range(g.n_zones):
        for j in g.neighbors(i):
            ir, ic = g.coords(i)
            jr, jc = g.coords(j)
            if abs(ir - jr) + abs(ic - jc) > 1:
                long_range += 1
    assert long_range > 0, "rewiring produced no long-range shortcuts"


def test_small_world_is_deterministic():
    a = ZoneGraph(GraphParams(topology="small_world", rewire_prob=0.3, topology_seed=7))
    b = ZoneGraph(GraphParams(topology="small_world", rewire_prob=0.3, topology_seed=7))
    assert np.array_equal(a.weights, b.weights)


def test_commute_topology_has_population_hubs():
    gp = GraphParams(grid_rows=6, grid_cols=6, population_per_zone=1000.0,
                     topology="commute", n_hubs=3, hub_pop_multiplier=5.0,
                     topology_seed=2)
    g = ZoneGraph(gp)
    _mix_is_valid(g)
    # Exactly 3 zones carry the hub population.
    assert int(np.sum(g.populations > 1000.0)) == 3
    assert np.isclose(g.populations.max(), 5000.0)


# --------------------------------------------------------------------------- #
# heterogeneous population flows into the model
# --------------------------------------------------------------------------- #
def test_heterogeneous_population_in_model():
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = 6
    cfg.model.graph.grid_cols = 6
    cfg.model.graph.population_per_zone = 1000.0
    cfg.model.graph.topology = "commute"
    cfg.model.graph.n_hubs = 2
    cfg.model.graph.hub_pop_multiplier = 4.0
    sim = Simulation(cfg)
    assert np.isclose(sim.N0.sum(), sim.living().sum())   # nobody lost at init
    assert sim.N0.max() > sim.N0.min()                    # genuinely heterogeneous
    assert int(np.sum(sim.N0 > 1000.0)) == 2


# --------------------------------------------------------------------------- #
# multi-seed outbreak
# --------------------------------------------------------------------------- #
def test_multi_seed_zones():
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = 6
    cfg.model.graph.grid_cols = 6
    cfg.seed_zones = [0, 35]
    cfg.seed_exposed = 60.0
    sim = Simulation(cfg)
    # The exposed are split evenly across both seed zones.
    assert np.isclose(sim.E[0], 30.0)
    assert np.isclose(sim.E[35], 30.0)
    assert np.isclose(sim.E.sum(), 60.0)


def test_total_population_conserved_on_small_world():
    cfg = ScenarioConfig()
    cfg.model.graph.topology = "small_world"
    cfg.model.graph.rewire_prob = 0.2
    cfg.n_days = 40.0
    res = run_scenario(cfg, record_belief=False)
    total = (res.frame[["S", "E", "I_asymp", "I_symp", "R", "D"]].sum(axis=1))
    N0 = cfg.model.graph.population_per_zone * 64
    assert np.allclose(total, N0, rtol=1e-9), (total.min(), total.max())


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

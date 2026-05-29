"""
Phase 4b tests: inter-zone agent flux at the micro tier.

Covers the hard requirements from the brief:

* with flux off (or a single zone) a block is bit-identical to independent
  Phase 4a zones -- the validated dynamics are untouched;
* **exact population conservation** across a promoted block (promoted agents +
  non-promoted macro counts) -- nothing created or lost;
* the *live handoff* (promoted -> promoted) preserves each agent's full epidemic
  state -- per-compartment totals are conserved when the epidemic is frozen;
* micro inter-zone movement **matches the macro mobility in expectation**
  (realized vs expected flux), the same calibration discipline as 4a.

Run with:  python -m pytest tests/test_flux.py -q
       or:  python tests/test_flux.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import PathogenGenome, MicroParams, GraphParams, ZoneGraph
from asphodel.micro import AgentZone, STATE_NAMES
from asphodel.flux import MicroFluxBlock


GENOME = PathogenGenome()


def _micro(n=400):
    return MicroParams(n_agents=n, area_size=100.0, infection_radius=2.0,
                       mixing_step_frac=0.12)


def _grid(rows=2, cols=2):
    return ZoneGraph(GraphParams(grid_rows=rows, grid_cols=cols))


def _counts(s, e=0, ia=0, is_=0, r=0, d=0):
    return {"S": s, "E": e, "Ia": ia, "Is": is_, "R": r, "D": d}


# --------------------------------------------------------------------------- #
# flux off == independent Phase 4a zones (frozen dynamics untouched)
# --------------------------------------------------------------------------- #
def test_flux_zero_reduces_to_independent_zones():
    graph = _grid(2, 2)
    mp = _micro(300)
    counts = _counts(280, e=20)

    # Two standalone zones (the Phase 4a path).
    standalone = {}
    for zi, sd in ((0, 11), (3, 22)):
        z = AgentZone.from_counts(counts, GENOME, mp, dt=0.25, seed=sd)
        for _ in range(60):
            z.step()
        standalone[zi] = z.counts()

    # The same two zones inside a block with flux_rate = 0.
    zones = {0: AgentZone.from_counts(counts, GENOME, mp, dt=0.25, seed=11),
             3: AgentZone.from_counts(counts, GENOME, mp, dt=0.25, seed=22)}
    block = MicroFluxBlock(graph, zones, dt=0.25, flux_rate=0.0, seed=5)
    for _ in range(60):
        block.step(step_dynamics=True)

    for zi in (0, 3):
        assert block.zones[zi].counts() == standalone[zi], zi


# --------------------------------------------------------------------------- #
# exact conservation across a promoted block + non-promoted macro sinks
# --------------------------------------------------------------------------- #
def test_flux_conserves_total_population():
    # 4x4 macro grid; promote the central 2x2 block, so each promoted zone has
    # both promoted and non-promoted (macro-sink) neighbours.
    graph = ZoneGraph(GraphParams(grid_rows=4, grid_cols=4))
    mp = _micro(500)
    block_idx = [graph.index(1, 1), graph.index(1, 2),
                 graph.index(2, 1), graph.index(2, 2)]
    zones = {zi: AgentZone.from_counts(_counts(480, e=20), GENOME, mp,
                                       dt=0.25, seed=zi) for zi in block_idx}
    # Non-promoted neighbours start with some macro population (fractional ok).
    macro_counts = {}
    for zi in block_idx:
        for j in graph.neighbors(zi):
            if j not in zones:
                macro_counts[j] = _counts(1000.4, e=3.6, ia=2.0)
    block = MicroFluxBlock(graph, zones, dt=0.25, flux_rate=0.15,
                           macro_counts=macro_counts, seed=7)

    total0 = block.total_population()
    for _ in range(250):
        block.step(step_dynamics=True)
        assert abs(block.total_population() - total0) < 1e-6, block.total_population()
    # Some flux actually crossed into the macro sinks (the demote-side path).
    assert sum(sum(c.values()) for c in block.ledger.to_macro.values()) > 0


# --------------------------------------------------------------------------- #
# live handoff (promoted -> promoted) preserves full epidemic state
# --------------------------------------------------------------------------- #
def test_flux_live_handoff_preserves_compartments():
    # 2x2 grid, ALL zones promoted => every migration is promoted->promoted, so
    # with the epidemic frozen each compartment total must be exactly conserved.
    graph = _grid(2, 2)
    mp = _micro(400)
    zones = {zi: AgentZone.from_counts(_counts(300, e=40, ia=30, is_=15, r=14, d=1),
                                       GENOME, mp, dt=0.25, seed=zi)
             for zi in range(4)}
    block = MicroFluxBlock(graph, zones, dt=0.25, flux_rate=0.25, seed=3)

    start = block.compartment_totals()
    for _ in range(120):
        block.step(step_dynamics=False)   # freeze the epidemic
    end = block.compartment_totals()
    for name in STATE_NAMES:
        assert abs(start[name] - end[name]) < 1e-9, (name, start[name], end[name])
    # No macro sinks exist (all neighbours promoted) -> nothing left the block.
    assert block.macro_population() == 0.0
    # And migration did happen.
    assert block.flux_consistency()["realized_total"] > 0


# --------------------------------------------------------------------------- #
# micro inter-zone movement matches macro mobility in expectation
# --------------------------------------------------------------------------- #
def test_flux_matches_mobility_in_expectation():
    graph = _grid(2, 2)
    mp = _micro(1000)
    flux_rate = 0.15
    zones = {zi: AgentZone.from_counts(_counts(1000), GENOME, mp, dt=0.25, seed=zi)
             for zi in range(4)}
    block = MicroFluxBlock(graph, zones, dt=0.25, flux_rate=flux_rate, seed=42)

    for _ in range(150):
        block.step(step_dynamics=False)   # isolate migration from the epidemic

    c = block.flux_consistency()
    # Aggregate realized total flux is within a few percent of the expectation.
    assert abs(c["ratio"] - 1.0) < 0.03, c["ratio"]
    # Every edge with a meaningful expectation also matches in expectation.
    for edge, ratio in c["per_edge_ratio"].items():
        assert abs(ratio - 1.0) < 0.06, (edge, ratio)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

"""
Inter-zone agent flux at the micro tier (Phase 4b).

Phase 4a promoted a *single* zone to agents and stubbed inter-zone flux to zero.
This module implements it for a small block of simultaneously-promoted adjacent
zones, with agents migrating between them, while leaving the validated
single-zone ``AgentZone`` dynamics **completely untouched**.

Design (the conservation discipline)
------------------------------------
* Each promoted zone is an independent :class:`~asphodel.micro.AgentZone` (its
  own torus).  Their internal step -- proximity transmission + genome
  transitions -- is the frozen Phase 4a code, called verbatim.  Migration is a
  **separate process layered on top**, so with ``flux_rate == 0`` (or a single
  promoted zone) a block is bit-identical to running independent 4a zones.

* **Direction** of each migration follows the macro mobility weights
  (:attr:`ZoneGraph.mix`): a migrating agent picks its destination neighbour
  with exactly the macro's relative mixing probabilities.

* **Magnitude**: each tick every agent in a promoted zone emigrates with the
  dt-correct probability ``1 - exp(-flux_rate * dt)`` (``flux_rate`` per-day,
  default = the macro ``mobility``).  So the expected per-day flux from zone i
  to neighbour j is ``flux_rate * mix[i, j] * N_i`` -- micro inter-zone movement
  reproduces the macro mobility in expectation (verified the same way 4a
  verified transmission).

The conservation ledger -- nothing is created or lost:

* **promoted -> promoted** (the *live handoff*): the agent is removed from the
  source zone's agent set and appended to the destination zone's agent set with
  its **full epidemic state preserved** (a fresh uniform torus position).
* **promoted -> non-promoted** (the *demote-side*): the departure is recorded as
  cross-zone flux and added to that neighbour's **macro compartment counts**.

So every agent leaving a promoted zone arrives somewhere -- a promoted
neighbour's agents or a non-promoted neighbour's macro counts -- and the block
total (promoted agents + non-promoted macro counts) is invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .config import PathogenGenome, MicroParams
from .graph import ZoneGraph
from .micro import AgentZone, STATE_NAMES, N_STATES
from .handoff import promote, macro_zone_counts


# --------------------------------------------------------------------------- #
# low-level agent add/remove (operate on AgentZone arrays without touching the
# frozen micro.py dynamics -- pure array surgery, no behaviour change)
# --------------------------------------------------------------------------- #
def _remove_agents(zone: AgentZone, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Remove agents at ``idx`` from ``zone``; return their (states, positions)."""
    if idx.size == 0:
        return (np.empty(0, dtype=zone.state.dtype),
                np.empty((0, 2), dtype=zone.pos.dtype))
    states = zone.state[idx].copy()
    positions = zone.pos[idx].copy()
    keep = np.ones(zone.n, dtype=bool)
    keep[idx] = False
    zone.state = zone.state[keep]
    zone.pos = zone.pos[keep]
    zone.sheltered = zone.sheltered[keep]
    zone.n = int(zone.state.size)
    return states, positions


def _add_agents(zone: AgentZone, states: np.ndarray) -> None:
    """Append agents with the given ``states`` to ``zone`` (fresh torus
    positions, unsheltered).  Preserves each agent's full epidemic state."""
    k = int(states.size)
    if k == 0:
        return
    new_pos = zone.rng.uniform(0.0, zone.L, size=(k, 2))
    zone.pos = np.vstack([zone.pos, new_pos])
    zone.state = np.concatenate([zone.state, states.astype(zone.state.dtype)])
    zone.sheltered = np.concatenate([zone.sheltered, np.zeros(k, dtype=bool)])
    zone.n = int(zone.state.size)


def _zero_counts() -> dict[str, float]:
    return {name: 0.0 for name in STATE_NAMES}


# --------------------------------------------------------------------------- #
# the multi-zone promoted block
# --------------------------------------------------------------------------- #
@dataclass
class FluxLedger:
    """Cumulative bookkeeping for the conservation + mobility-consistency checks."""

    # realized agent moves i -> j (counts), and the matching expected counts.
    realized: dict = field(default_factory=dict)   # {(i, j): count}
    expected: dict = field(default_factory=dict)    # {(i, j): float}
    # per-state flux deposited into each non-promoted zone's macro counts.
    to_macro: dict = field(default_factory=dict)    # {j: {state: count}}

    def add_realized(self, i: int, j: int, n: int) -> None:
        self.realized[(i, j)] = self.realized.get((i, j), 0) + int(n)

    def add_expected(self, i: int, j: int, x: float) -> None:
        self.expected[(i, j)] = self.expected.get((i, j), 0.0) + float(x)

    def add_to_macro(self, j: int, state_code: int, n: int) -> None:
        d = self.to_macro.setdefault(j, _zero_counts())
        d[STATE_NAMES[state_code]] += int(n)


class MicroFluxBlock:
    """A block of simultaneously-promoted adjacent zones with inter-zone flux.

    Parameters
    ----------
    graph : ZoneGraph
        The macro zone graph (supplies neighbour topology + mobility weights).
    zones : dict[int, AgentZone]
        Promoted zones keyed by their macro zone index.
    dt : float
        Tick length in days (shared with the macro schedule).
    flux_rate : float
        Per-day per-agent emigration rate.  Direction is by ``graph.mix``.
    macro_counts : dict[int, dict[str, float]], optional
        Initial macro compartment counts for the non-promoted neighbour zones
        that the demote-side flux drains into.  Missing zones start at zero.
    seed : int
        Seed for the migration RNG (independent of each zone's own RNG).
    """

    def __init__(self, graph: ZoneGraph, zones: dict[int, AgentZone],
                 dt: float, flux_rate: float,
                 macro_counts: Optional[dict[int, dict[str, float]]] = None,
                 seed: int = 0):
        self.graph = graph
        self.zones = dict(zones)
        self.promoted = set(self.zones.keys())
        self.dt = dt
        self.flux_rate = float(flux_rate)
        self.rng = np.random.default_rng(seed)
        self.macro_counts: dict[int, dict[str, float]] = {
            j: dict(c) for j, c in (macro_counts or {}).items()
        }
        self.ledger = FluxLedger()
        self.tick = 0

        # Pre-compute, for each promoted zone, its neighbour list and the
        # destination probabilities (the macro mobility weights, renormalised
        # over the neighbours that exist).
        self._neighbours: dict[int, np.ndarray] = {}
        self._dest_p: dict[int, np.ndarray] = {}
        for i in self.promoted:
            nbrs = np.array(graph.neighbors(i), dtype=int)
            w = graph.mix[i, nbrs]
            s = w.sum()
            p = w / s if s > 0 else np.full(nbrs.size, 1.0 / max(nbrs.size, 1))
            self._neighbours[i] = nbrs
            self._dest_p[i] = p

    # --------------------------------------------------------------- counts
    def promoted_population(self) -> int:
        return int(sum(z.n for z in self.zones.values()))

    def macro_population(self) -> float:
        return float(sum(sum(c.values()) for c in self.macro_counts.values()))

    def total_population(self) -> float:
        """The conserved invariant: promoted agents + non-promoted macro counts."""
        return self.promoted_population() + self.macro_population()

    def compartment_totals(self) -> dict[str, float]:
        """Per-compartment totals across the whole block (agents + macro)."""
        totals = _zero_counts()
        for z in self.zones.values():
            bc = np.bincount(z.state, minlength=N_STATES)
            for code, name in enumerate(STATE_NAMES):
                totals[name] += float(bc[code])
        for c in self.macro_counts.values():
            for name in STATE_NAMES:
                totals[name] += float(c[name])
        return totals

    # ----------------------------------------------------------------- step
    def step(self, step_dynamics: bool = True) -> None:
        """Advance one tick: (optionally) the per-zone epidemic dynamics, then
        inter-zone migration.

        ``step_dynamics=False`` freezes the epidemic (no transmission/transitions)
        so a test can measure migration counts against their expectation cleanly.
        """
        if step_dynamics:
            for z in self.zones.values():
                z.step()

        self._migrate()
        self.tick += 1

    def _migrate(self) -> None:
        p_move = 1.0 - np.exp(-self.flux_rate * self.dt)

        # --- Phase 1: collect departures (remove from source zones first, so an
        #     agent that just arrived this tick cannot re-emigrate immediately).
        arrivals_promoted: dict[int, list[np.ndarray]] = {i: [] for i in self.promoted}
        for i in self.promoted:
            zone = self.zones[i]
            n_i = zone.n
            # Accumulate the expected flux for the consistency check (uses the
            # pre-migration count, matching flux_rate * mix[i,j] * N_i per day).
            nbrs, dest_p = self._neighbours[i], self._dest_p[i]
            for k, j in enumerate(nbrs):
                self.ledger.add_expected(i, int(j), n_i * p_move * dest_p[k])
            if n_i == 0 or p_move <= 0:
                continue
            leaves = self.rng.random(n_i) < p_move
            move_idx = np.where(leaves)[0]
            if move_idx.size == 0:
                continue
            # Assign each migrant a destination neighbour by the mobility weights.
            choice = self.rng.choice(nbrs.size, size=move_idx.size, p=dest_p)
            states, _ = _remove_agents(zone, move_idx)
            for k, j in enumerate(nbrs):
                sel = choice == k
                cnt = int(sel.sum())
                if cnt == 0:
                    continue
                self.ledger.add_realized(i, int(j), cnt)
                if j in self.promoted:
                    arrivals_promoted[int(j)].append(states[sel])
                else:
                    # demote-side: add to the neighbour's macro compartments.
                    dest = self.macro_counts.setdefault(int(j), _zero_counts())
                    sel_states = states[sel]
                    bc = np.bincount(sel_states, minlength=N_STATES)
                    for code, name in enumerate(STATE_NAMES):
                        if bc[code]:
                            dest[name] += float(bc[code])
                            self.ledger.add_to_macro(int(j), code, int(bc[code]))

        # --- Phase 2: deposit arrivals into promoted destination zones.
        for j, batches in arrivals_promoted.items():
            if batches:
                _add_agents(self.zones[j], np.concatenate(batches))

    # ------------------------------------------------------ consistency report
    def flux_consistency(self) -> dict:
        """Realized vs expected inter-zone flux, aggregated over the run.

        Returns the total realized & expected agent moves and their ratio -- the
        mobility-in-expectation check (analogous to Phase 4a's transmission
        calibration check).  Per-edge detail is in ``self.ledger``."""
        realized_total = sum(self.ledger.realized.values())
        expected_total = sum(self.ledger.expected.values())
        ratio = (realized_total / expected_total) if expected_total > 0 else float("nan")
        # Per-edge ratios for edges with a meaningful expectation.
        per_edge = {}
        for edge, exp in self.ledger.expected.items():
            if exp >= 1.0:
                per_edge[edge] = self.ledger.realized.get(edge, 0) / exp
        return {
            "realized_total": int(realized_total),
            "expected_total": float(expected_total),
            "ratio": float(ratio),
            "per_edge_ratio": per_edge,
        }


# --------------------------------------------------------------------------- #
# construction helper: promote a block of zones from a macro Simulation
# --------------------------------------------------------------------------- #
def promote_block(sim, promoted_zones, genome: PathogenGenome,
                  micro_params: MicroParams, dt: float, flux_rate: float,
                  seed: int = 0) -> MicroFluxBlock:
    """Promote ``promoted_zones`` of a macro ``Simulation`` into an agent block.

    Each promoted zone is spawned from its macro compartment counts (reusing the
    Phase 4a spawn manifest, which conserves the total).  Non-promoted
    neighbours of the block are seeded as macro-count sinks for the demote-side
    flux.  ``flux_rate`` defaults are chosen by the caller (typically the macro
    ``mobility``)."""
    zones: dict[int, AgentZone] = {}
    for idx, zi in enumerate(promoted_zones):
        counts = macro_zone_counts(sim, zi)
        zones[zi] = promote(counts, genome, micro_params, dt, seed=seed + idx)

    promoted_set = set(promoted_zones)
    macro_counts: dict[int, dict[str, float]] = {}
    for zi in promoted_zones:
        for j in sim.graph.neighbors(zi):
            if j not in promoted_set and j not in macro_counts:
                macro_counts[j] = macro_zone_counts(sim, j)

    return MicroFluxBlock(sim.graph, zones, dt, flux_rate,
                          macro_counts=macro_counts, seed=seed + 999)

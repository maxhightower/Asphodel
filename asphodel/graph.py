"""
The zone graph: an abstract grid of zones with weighted mobility edges.

The whole model is "a coupled field over a zone graph", so this module owns the
topology and the mobility-weighted mixing matrices that both infection pressure
and belief contagion read from.  Topology is deliberately swappable: anything
that produces an adjacency/weight matrix can stand in for the grid.
"""

from __future__ import annotations

import numpy as np

from .config import GraphParams


class ZoneGraph:
    """An N x N grid of zones connected to their 4-neighbours.

    Attributes
    ----------
    n_zones : int
    rows, cols : int
    mix : (Z, Z) ndarray
        Row-normalised neighbour weights.  ``mix[i, j]`` is the share of zone
        i's "elsewhere" interaction that happens with zone j (rows sum to 1,
        zero diagonal).  Used for both infection mixing and belief contagion.
    """

    def __init__(self, params: GraphParams):
        self.params = params
        self.rows = params.grid_rows
        self.cols = params.grid_cols
        self.n_zones = self.rows * self.cols
        self._rng = np.random.default_rng(params.topology_seed)

        # Per-zone population (uniform unless a topology makes it heterogeneous).
        self.populations = np.full(self.n_zones, params.population_per_zone, dtype=float)

        topo = getattr(params, "topology", "grid")
        if topo == "grid":
            W = self._grid_weights()
        elif topo == "small_world":
            W = self._small_world_weights(params.rewire_prob)
        elif topo == "commute":
            W = self._commute_weights(params.n_hubs, params.hub_pop_multiplier)
        else:
            raise ValueError(f"unknown topology {topo!r}")
        self.weights = W

        # Row-normalised mixing matrix (rows with no neighbours stay all-zero).
        row_sums = W.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.mix = np.where(row_sums > 0, W / row_sums, 0.0)

    # ------------------------------------------------------------ topologies
    def _grid_weights(self) -> np.ndarray:
        """Uniform weights between 4-connected grid neighbours."""
        W = np.zeros((self.n_zones, self.n_zones), dtype=float)
        for r in range(self.rows):
            for c in range(self.cols):
                i = self.index(r, c)
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols:
                        W[i, self.index(nr, nc)] = 1.0
        return W

    def _small_world_weights(self, rewire_prob: float) -> np.ndarray:
        """Watts-Strogatz-style: start from the grid, then rewire each edge to a
        random distant zone with probability ``rewire_prob`` (kept symmetric).

        This injects long-range shortcuts so belief contagion can jump across
        the map instead of only diffusing to adjacent zones -- the mechanism
        that turns a slow diffusion wave into a synchronized tip.
        """
        W = self._grid_weights()
        Z = self.n_zones
        # Iterate the upper-triangular existing edges; rewire one endpoint.
        edges = [(i, j) for i in range(Z) for j in range(i + 1, Z) if W[i, j] > 0]
        for i, j in edges:
            if self._rng.random() < rewire_prob:
                # Move the j endpoint to a random non-self, non-duplicate zone.
                candidates = np.where((W[i] == 0))[0]
                candidates = candidates[candidates != i]
                if candidates.size == 0:
                    continue
                k = int(self._rng.choice(candidates))
                W[i, j] = W[j, i] = 0.0
                W[i, k] = W[k, i] = 1.0
        return W

    def _commute_weights(self, n_hubs: int, hub_mult: float) -> np.ndarray:
        """Hub-and-spoke commute graph: grid base + every zone connected to a
        few high-population hubs by a gravity weight (~ hub_pop / distance).

        Hubs carry ``hub_mult`` x the base population, so they are both
        population centres and mobility centres -- a crude city/suburb commute.
        """
        W = self._grid_weights()
        Z = self.n_zones
        if n_hubs > 0:
            hubs = self._rng.choice(Z, size=min(n_hubs, Z), replace=False)
            self.populations[hubs] *= hub_mult
            for h in hubs:
                hr, hc = self.coords(int(h))
                for i in range(Z):
                    if i == h:
                        continue
                    ir, ic = self.coords(i)
                    dist = abs(ir - hr) + abs(ic - hc)
                    w = hub_mult / (1.0 + dist)        # gravity-ish spoke weight
                    W[i, h] = max(W[i, h], w)
                    W[h, i] = max(W[h, i], w)
        return W

    def index(self, r: int, c: int) -> int:
        return r * self.cols + c

    def coords(self, i: int) -> tuple[int, int]:
        return divmod(i, self.cols)

    def center_zone(self) -> int:
        return self.index(self.rows // 2, self.cols // 2)

    def neighbors(self, i: int) -> list[int]:
        return [j for j in range(self.n_zones) if self.weights[i, j] > 0]

    def to_grid(self, values: np.ndarray) -> np.ndarray:
        """Reshape a per-zone vector into a (rows, cols) array for plotting."""
        return np.asarray(values).reshape(self.rows, self.cols)

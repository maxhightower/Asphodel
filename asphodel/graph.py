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

        # Per-zone population: an explicit vector (e.g. real OSM building density,
        # ordered row*cols+col) overrides the uniform default; otherwise every
        # zone starts equal and a topology may then make it heterogeneous (e.g.
        # commute hubs).
        if params.population is not None:
            if len(params.population) != self.n_zones:
                raise ValueError(
                    f"graph.population has {len(params.population)} entries "
                    f"but grid has {self.n_zones} zones"
                )
            self.populations = np.asarray(params.population, dtype=float)
        else:
            self.populations = np.full(self.n_zones, params.population_per_zone, dtype=float)

        edges = getattr(params, "mobility_edges", None)
        if edges is not None:
            # Explicit weighted mobility graph (e.g. road-derived) replaces the
            # topology. Grid geometry (rows/cols) is still kept for reporting.
            W = self._explicit_weights(edges)
            self.topology_kind = "explicit"
        else:
            topo = getattr(params, "topology", "grid")
            if topo == "grid":
                W = self._grid_weights()
            elif topo == "small_world":
                W = self._small_world_weights(params.rewire_prob)
            elif topo == "commute":
                W = self._commute_weights(params.n_hubs, params.hub_pop_multiplier)
            else:
                raise ValueError(f"unknown topology {topo!r}")
            self.topology_kind = topo
        self.weights = W

        # Row-normalised mixing matrix (rows with no neighbours stay all-zero).
        row_sums = W.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.mix = np.where(row_sums > 0, W / row_sums, 0.0)

        # Population-weighted mixing for *social belief contagion*. Belief is a
        # human phenomenon: an empty cell (water, a park, a rural edge -- common
        # when zones come from real OSM geography) holds no people to believe or
        # relay panic, so it must not launder belief between its populated
        # neighbours as though it were a crowd. Weighting each neighbour j by its
        # population zeroes an empty cell's contribution (weight ~ pop[j] = 0)
        # and, symmetrically, makes an empty cell's own belief inert (no
        # populated neighbour ever reads it). For a uniform-population grid this
        # is identical to ``mix``, so abstract scenarios are unchanged; only
        # heterogeneous/empty OSM grids differ. See test_empty_cell_belief.
        Wp = W * self.populations[None, :]
        pop_row_sums = Wp.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.belief_mix = np.where(pop_row_sums > 0, Wp / pop_row_sums, 0.0)

    # ------------------------------------------------------------ topologies
    def _explicit_weights(self, edges) -> np.ndarray:
        """Build a symmetric weight matrix from a sparse [[a, b, w], ...] list.

        Undirected: each edge sets W[a,b] = W[b,a] = max(existing, w) so repeated
        or reciprocal entries aggregate to the stronger weight (the derivation
        already sums parallel roads into one weight per pair). Self-edges and
        out-of-range indices are ignored; negative weights are rejected.
        """
        Z = self.n_zones
        W = np.zeros((Z, Z), dtype=float)
        for e in edges:
            a, b, w = int(e[0]), int(e[1]), float(e[2])
            if a == b or not (0 <= a < Z and 0 <= b < Z):
                continue
            if w < 0.0:
                raise ValueError(f"mobility edge weight must be >= 0, got {w}")
            W[a, b] = max(W[a, b], w)
            W[b, a] = max(W[b, a], w)
        return W

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

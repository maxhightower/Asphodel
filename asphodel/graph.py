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

        # Build symmetric mobility weights between 4-connected neighbours.
        W = np.zeros((self.n_zones, self.n_zones), dtype=float)
        for r in range(self.rows):
            for c in range(self.cols):
                i = self.index(r, c)
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols:
                        j = self.index(nr, nc)
                        W[i, j] = 1.0  # uniform mobility weight to start
        self.weights = W

        # Row-normalised mixing matrix (rows with no neighbours stay all-zero).
        row_sums = W.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.mix = np.where(row_sums > 0, W / row_sums, 0.0)

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

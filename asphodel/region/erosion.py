"""Bake-time erosion + hydrology for realistic terrain (all cities).

Raw fractal terrain has no drainage structure — real landscapes are organised by
water. This module post-processes a baked heightmap with a deterministic,
vectorised pipeline:

  1. a light smoothing pass to remove fractal blockiness;
  2. D8 flow accumulation → drainage area per cell (the river network);
  3. valley carving proportional to drainage area → dendritic valleys and ridges;
  4. thermal relaxation so slopes settle to a natural angle of repose;
  5. a water mask: rivers/lakes where drainage is large, plus anything at/under
     sea level.

No droplet loop (which is fragile and slow); the flow-accumulation carve gives
the characteristic branching valleys that read as "real" terrain, and it is
O(n log n) and fully reproducible from the input heightmap.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

# 8 neighbours (dr, dc) and their distances in cell units.
_NEIGH = [(-1, -1, 1.41421356), (-1, 0, 1.0), (-1, 1, 1.41421356),
          (0, -1, 1.0), (0, 1, 1.0),
          (1, -1, 1.41421356), (1, 0, 1.0), (1, 1, 1.41421356)]


def _smooth(h: np.ndarray, passes: int = 1) -> np.ndarray:
    """Separable 1-2-1 blur, edge-clamped. Removes fractal stair-stepping."""
    out = h
    for _ in range(passes):
        p = np.pad(out, 1, mode="edge")
        out = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
               + 4.0 * p[1:-1, 1:-1]) / 8.0
    return out


def flow_accumulation(h: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """D8 drainage area per cell. Returns (accumulation, downstream_flat_index)."""
    rows, cols = h.shape
    downstream = np.full(rows * cols, -1, dtype=np.int64)
    hr = h  # local
    for r in range(rows):
        for c in range(cols):
            hc = hr[r, c]
            best = -1
            best_slope = 0.0
            for dr, dc, dd in _NEIGH:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    s = (hc - hr[nr, nc]) / dd
                    if s > best_slope:
                        best_slope = s
                        best = nr * cols + nc
            downstream[r * cols + c] = best
    acc = np.ones(rows * cols, dtype=np.float64)
    order = np.argsort(h.ravel())[::-1]  # process high cells first
    for idx in order:
        d = downstream[idx]
        if d >= 0:
            acc[d] += acc[idx]
    return acc.reshape(rows, cols), downstream


def thermal_relax(h: np.ndarray, iters: int, talus: float,
                  rate: float = 0.5) -> np.ndarray:
    """Mass-conserving thermal erosion: material above the talus slope slides to
    the lower of two opposite neighbours (settling steep spikes into slopes)."""
    out = h.astype(np.float64).copy()
    for _ in range(iters):
        for (dr, dc) in [(1, 0), (0, 1)]:
            a = out
            b = np.roll(out, (-dr, -dc), axis=(0, 1))
            diff = a - b
            # interior-only (ignore the wrapped edge row/col)
            move = np.where(diff > talus, (diff - talus) * rate * 0.5, 0.0)
            if dr:
                move[-1, :] = 0.0
            if dc:
                move[:, -1] = 0.0
            out = out - move                                   # higher cell loses
            out = out + np.roll(move, (dr, dc), axis=(0, 1))    # lower cell gains
    return out


def extract_water(h: np.ndarray, acc: np.ndarray, cell_m: float,
                  sea_level: Optional[float], river_fraction: float = 0.985
                  ) -> np.ndarray:
    """Boolean water mask: big-drainage cells (rivers/lakes) plus sub-sea land."""
    mask = np.zeros(h.shape, dtype=bool)
    if sea_level is not None:
        mask |= h <= sea_level
    if river_fraction < 1.0:
        thresh = np.quantile(acc, river_fraction)
        # A cell is river where it carries a lot of flow and is not on a steep face.
        gy, gx = np.gradient(h, cell_m)
        slope = np.hypot(gx, gy)
        mask |= (acc >= thresh) & (slope < 0.08)
    return mask


def erode_and_hydrology(h: np.ndarray, cell_m: float, seed: int = 0,
                        mountainous: bool = False) -> dict:
    """Full pipeline. Returns eroded heights, water mask, and river stats."""
    h0 = h.astype(np.float64)
    relief = float(h0.max() - h0.min())

    smoothed = _smooth(h0, passes=2)
    acc, _ = flow_accumulation(smoothed)

    # Carve valleys proportional to log-drainage; deeper where the land is higher.
    la = np.log1p(acc)
    la = (la - la.min()) / (la.max() - la.min() + 1e-9)
    carve_depth = (0.10 if mountainous else 0.04) * max(relief, 40.0)
    carved = smoothed - carve_depth * la

    # Settle slopes; a steeper talus in the mountains keeps ridges sharp.
    talus = (0.9 if mountainous else 0.4) * cell_m
    eroded = thermal_relax(carved, iters=6, talus=talus)

    # Rebuild drainage on the eroded surface for the final water mask.
    acc2, _ = flow_accumulation(_smooth(eroded, 1))
    water = extract_water(eroded, acc2, cell_m, None, river_fraction=0.988)

    return {
        "heights": eroded,
        "water_mask": water,
        "accumulation": acc2,
        "river_cells": int(water.sum()),
        "carve_depth": carve_depth,
    }

"""Offline P0-D3/D5: turn the big raster parking fields into intentional lots in a
single coordinated pass — landscaped grass islands, stall striping, parked cars,
light standards.

The huge visible parking lots are Overture S_PARKING land cover, not the compiler's
open-area `_parking_lot`, so they arrive as bare striped polygons. This lays a
PCA-oriented stall grid over each parking region and, in one pass so everything
stays consistent:

  * carves small GRASS islands into the surface raster and stands a tree (+ shrub)
    on each — so island trees grow out of a green median, never straight out of the
    asphalt;
  * paints stall-divider stripes (ground_markings), skipping island cells;
  * parks cars in ~42% of the remaining stalls (full vehicle mix, aligned to the
    stall depth);
  * drops light standards down the aisles.

Idempotent via a per-chunk sentinel; re-encodes the (island-carved) surface. This
supersedes the standalone parking-markings pass. The compiler-side raster-parking
furniture step is the follow-up for a from-source rebuild.

    python -m tools.repatch_parking_ensemble godot/bundles/houston
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import sys

import numpy as np

S_PARKING = 2
S_MAINTAINED_GRASS = 4
CELLS = 128
CELL_M = 2.0

STALL_PITCH = 2.7
STALL_DEPTH = 5.0
AISLE = 6.0
MIN_REGION_CELLS = 24
ISLAND_EVERY = 8          # every Nth stall column in a band becomes a grass island
ISLAND_R = 2.3            # island grass radius (m)
CAR_FILL = 0.42
CAR_MIX = [("sedan", 5), ("suv", 3), ("pickup", 2), ("van", 1), ("jeep", 1),
           ("sports_car", 1)]
ISLAND_TREES = ["tree_round", "tree_crape_myrtle", "tree_round", "tree_magnolia"]
ISLAND_SHRUBS = ["bush_round", "bush_low", "flowering_shrub"]
MAX_CARS = 160
MAX_POLES = 40
MAX_ISLANDS = 40


def _decode_rle(runs, n):
    out = np.zeros(n, dtype=np.uint8)
    idx = 0
    for i in range(0, len(runs) - 1, 2):
        t = int(runs[i]); c = int(runs[i + 1])
        end = min(idx + c, n)
        out[idx:end] = t
        idx = end
        if idx >= n:
            break
    return out.reshape(CELLS, CELLS)


def _encode_rle(grid):
    flat = grid.reshape(-1)
    runs = []
    i = 0
    n = len(flat)
    while i < n:
        j = i
        val = flat[i]
        while j < n and flat[j] == val:
            j += 1
        runs.append(int(val)); runs.append(int(j - i))
        i = j
    return runs


def _components(mask):
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for r in range(CELLS):
        for c in range(CELLS):
            if not mask[r, c] or seen[r, c]:
                continue
            stack = [(r, c)]; seen[r, c] = True; cells = []
            while stack:
                rr, cc = stack.pop(); cells.append((rr, cc))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = rr + dr, cc + dc
                    if 0 <= nr < CELLS and 0 <= nc < CELLS and mask[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True; stack.append((nr, nc))
            if len(cells) >= MIN_REGION_CELLS:
                comps.append(cells)
    return comps


def _rng(x, z, salt):
    a = (int(round(x * 4.0)) ^ (salt * 2654435761)) & 0xFFFFFFFF
    b = int(round(z * 4.0)) & 0xFFFFFFFF
    h = ((a * 0x9E3779B1) ^ (b * 0x85EBCA6B)) & 0x7FFFFFFF
    h ^= (h >> 13)
    h = (h * 0x2545F491) & 0x7FFFFFFF
    return (h % 1000000) / 1000000.0


def _pick(mix, r):
    tot = sum(w for _, w in mix)
    acc = 0.0
    for v, w in mix:
        acc += w
        if r * tot < acc:
            return v
    return mix[-1][0]


def _carve_island(grid, origin, px, pz):
    """Set the parking cells within ISLAND_R of (px,pz) to grass (an island median).
    Returns True if any cell was carved."""
    ox, oz = origin
    cc = int((px - ox) / CELL_M)
    cr = int((pz - oz) / CELL_M)
    rad = int(math.ceil(ISLAND_R / CELL_M))
    carved = False
    for dr in range(-rad, rad + 1):
        for dc in range(-rad, rad + 1):
            r, c = cr + dr, cc + dc
            if 0 <= r < CELLS and 0 <= c < CELLS and grid[r, c] == S_PARKING:
                wx = ox + (c + 0.5) * CELL_M
                wz = oz + (r + 0.5) * CELL_M
                if math.hypot(wx - px, wz - pz) <= ISLAND_R:
                    grid[r, c] = S_MAINTAINED_GRASS
                    carved = True
    return carved


def _region(cells, origin, grid, out):
    ox, oz = origin
    pts = np.array([[ox + (c + 0.5) * CELL_M, oz + (r + 0.5) * CELL_M] for r, c in cells])
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T)
    if not np.all(np.isfinite(cov)):
        return
    evals, evecs = np.linalg.eigh(cov)
    u = evecs[:, int(np.argmax(evals))]
    v = np.array([-u[1], u[0]])
    pu = (pts - mean) @ u
    pv = (pts - mean) @ v
    umin, umax, vmin, vmax = pu.min(), pu.max(), pv.min(), pv.max()
    if umax - umin < 8.0:
        return
    v_head = round(math.degrees(math.atan2(v[0], v[1])), 1)
    u_head = round(math.degrees(math.atan2(u[0], u[1])), 1)

    def wp(uu, vv):
        p = mean + u * uu + v * vv
        return float(p[0]), float(p[1])

    def cell_is(wx, wz, val):
        col = int((wx - ox) / CELL_M); row = int((wz - oz) / CELL_M)
        return 0 <= row < CELLS and 0 <= col < CELLS and grid[row, col] == val

    # Pass 1: carve grass islands (every Nth stall column per band) + plant them.
    band_v = vmin + STALL_DEPTH * 0.5
    band_i = 0
    while band_v <= vmax:
        col_i = 0
        uu = umin + STALL_PITCH * 0.5
        while uu <= umax:
            if col_i % ISLAND_EVERY == (band_i % ISLAND_EVERY) and len(out["tree"]) < MAX_ISLANDS:
                px, pz = wp(uu, band_v)
                if cell_is(px, pz, S_PARKING) and _carve_island(grid, origin, px, pz):
                    t = ISLAND_TREES[int(_rng(px, pz, 29) * len(ISLAND_TREES)) % len(ISLAND_TREES)]
                    out["tree"].append([t, round(px, 2), round(pz, 2),
                                        round(_rng(px, pz, 31) * 360.0, 1),
                                        int(_rng(px, pz, 37) * 5) % 5])
                    if _rng(px, pz, 41) < 0.6:
                        s = ISLAND_SHRUBS[int(_rng(px, pz, 43) * len(ISLAND_SHRUBS)) % len(ISLAND_SHRUBS)]
                        sx, sz = wp(uu + 0.9, band_v)
                        out["tree"].append([s, round(sx, 2), round(sz, 2),
                                            round(_rng(sx, sz, 47) * 360.0, 1),
                                            int(_rng(sx, sz, 53) * 5) % 5])
            uu += STALL_PITCH
            col_i += 1
        band_v += STALL_DEPTH + AISLE
        band_i += 1

    # Pass 2: stripes + parked cars on the stalls that are still asphalt.
    band_v = vmin + STALL_DEPTH * 0.5
    while band_v <= vmax:
        uu = umin + STALL_PITCH * 0.5
        while uu <= umax:
            px, pz = wp(uu, band_v)
            if cell_is(px, pz, S_PARKING):
                out["mark"].append([round(px, 2), round(pz, 2), v_head, STALL_DEPTH, "parking_stall"])
                if len(out["veh"]) < MAX_CARS and _rng(px, pz, 7) < CAR_FILL:
                    kind = _pick(CAR_MIX, _rng(px, pz, 11))
                    face = v_head if _rng(px, pz, 13) < 0.5 else (v_head + 180.0)
                    out["veh"].append([kind, round(px, 2), round(pz, 2),
                                       round(face, 1), int(_rng(px, pz, 17) * 5) % 5])
            uu += STALL_PITCH
        band_v += STALL_DEPTH + AISLE

    # Pass 3: light standards down the aisles.
    band_v = vmin + STALL_DEPTH * 0.5
    while band_v <= vmax:
        pole_v = band_v + STALL_DEPTH * 0.5 + AISLE * 0.5
        upos = umin + 6.0
        while upos <= umax - 6.0 and len(out["prop"]) < MAX_POLES:
            px, pz = wp(upos, pole_v)
            if cell_is(px, pz, S_PARKING):
                out["prop"].append(["streetlight", round(px, 2), round(pz, 2), u_head, 0])
            upos += 16.0
        band_v += STALL_DEPTH + AISLE


def repatch_bundle(bundle_dir: str) -> dict:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    tot = {"veh": 0, "prop": 0, "tree": 0, "mark": 0, "chunks": 0}
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        if chunk.get("_pk_ens"):
            continue
        runs = chunk.get("surface", [])
        if not runs:
            continue
        grid = _decode_rle(runs, CELLS * CELLS)
        if not (grid == S_PARKING).any():
            continue
        origin = chunk["origin"]
        out = {"veh": [], "prop": [], "tree": [], "mark": []}
        for comp in _components(grid == S_PARKING):
            _region(comp, origin, grid, out)
        if not (out["veh"] or out["prop"] or out["tree"] or out["mark"]):
            continue
        chunk["surface"] = _encode_rle(grid)
        chunk["ground_markings"] = out["mark"]
        chunk.setdefault("vehicles", []).extend(out["veh"])
        chunk.setdefault("props", []).extend(out["prop"])
        chunk.setdefault("trees", []).extend(out["tree"])
        chunk["_pk_ens"] = 1
        for k in ("veh", "prop", "tree", "mark"):
            tot[k] += len(out[k])
        tot["chunks"] += 1
        payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
        with open(fn, "wb") as f:
            f.write(gzip.compress(payload, mtime=0))
    return tot


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle")
    args = ap.parse_args(argv)
    t = repatch_bundle(args.bundle)
    print("parking ensemble: %d islands+shrubs, %d cars, %d poles, %d stripes over %d chunks"
          % (t["tree"], t["veh"], t["prop"], t["mark"], t["chunks"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

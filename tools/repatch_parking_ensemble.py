"""Offline P0-D3: dress the big raster parking fields as real commercial lots —
parked cars in the stalls, light standards, and landscaped-island trees — so a lot
reads as an intentional site instead of a striped grey polygon.

The huge visible parking lots are Overture S_PARKING land cover, not the compiler's
open-area `_parking_lot`, so they never received its stalls/poles/cars. This adds
that furniture from the same raster + stall grid the stripe markings use, so cars
and poles land on the stall rows. Idempotent via a per-chunk sentinel. The
compiler-side pass (a raster-parking-furniture step alongside the markings) is the
follow-up for a from-source rebuild.

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
CELLS = 128
CELL_M = 2.0

STALL_PITCH = 2.7
STALL_DEPTH = 5.0
AISLE = 6.0
MIN_REGION_CELLS = 24
CAR_FILL = 0.42                      # fraction of stalls with a parked car
CAR_MIX = [("sedan", 5), ("suv", 3), ("pickup", 2), ("van", 1), ("jeep", 1),
           ("sports_car", 1)]
ISLAND_TREES = ["tree_round", "tree_crape_myrtle", "tree_round", "tree_magnolia"]
MAX_CARS = 160
MAX_POLES = 40
MAX_TREES = 40


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


def _region_furniture(cells, origin, mask, out):
    ox, oz = origin
    pts = np.array([[ox + (c + 0.5) * CELL_M, oz + (r + 0.5) * CELL_M] for r, c in cells])
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T)
    if not np.all(np.isfinite(cov)):
        return
    evals, evecs = np.linalg.eigh(cov)
    u = evecs[:, int(np.argmax(evals))]       # aisle direction
    v = np.array([-u[1], u[0]])               # stall depth direction
    pu = (pts - mean) @ u
    pv = (pts - mean) @ v
    umin, umax, vmin, vmax = pu.min(), pu.max(), pv.min(), pv.max()
    if umax - umin < 8.0:
        return
    v_head = round(math.degrees(math.atan2(v[0], v[1])), 1)   # car heading along depth
    u_head = round(math.degrees(math.atan2(u[0], u[1])), 1)

    def on_park(wx, wz):
        col = int((wx - ox) / CELL_M); row = int((wz - oz) / CELL_M)
        return 0 <= row < CELLS and 0 <= col < CELLS and mask[row, col]

    band_v = vmin + STALL_DEPTH * 0.5
    band_i = 0
    while band_v <= vmax:
        uu = umin + STALL_PITCH * 0.5
        col_i = 0
        while uu <= umax:
            p = mean + u * uu + v * band_v
            px, pz = float(p[0]), float(p[1])
            if on_park(px, pz):
                # a parked car in some stalls
                if len(out["veh"]) < MAX_CARS and _rng(px, pz, 7) < CAR_FILL:
                    kind = _pick(CAR_MIX, _rng(px, pz, 11))
                    face = v_head if _rng(px, pz, 13) < 0.5 else (v_head + 180.0)
                    out["veh"].append([kind, round(px, 2), round(pz, 2),
                                       round(face, 1), int(_rng(px, pz, 17) * 5) % 5])
                # a landscaped-island tree at the end of a run, now and then
                elif len(out["tree"]) < MAX_TREES and col_i % 6 == 0 and _rng(px, pz, 23) < 0.5:
                    t = ISLAND_TREES[int(_rng(px, pz, 29) * len(ISLAND_TREES)) % len(ISLAND_TREES)]
                    out["tree"].append([t, round(px, 2), round(pz, 2),
                                        round(_rng(px, pz, 31) * 360.0, 1),
                                        int(_rng(px, pz, 37) * 5) % 5])
            uu += STALL_PITCH
            col_i += 1
        # light poles down the middle of the aisle behind this band
        pole_v = band_v + STALL_DEPTH * 0.5 + AISLE * 0.5
        upos = umin + 6.0
        while upos <= umax - 6.0 and len(out["prop"]) < MAX_POLES:
            p = mean + u * upos + v * pole_v
            px, pz = float(p[0]), float(p[1])
            if on_park(px, pz):
                out["prop"].append(["streetlight", round(px, 2), round(pz, 2), u_head, 0])
            upos += 16.0
        band_v += STALL_DEPTH + AISLE
        band_i += 1


def repatch_bundle(bundle_dir: str) -> tuple[int, int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    cars = poles = trees = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        if chunk.get("_pk_ens"):
            continue
        runs = chunk.get("surface", [])
        if not runs:
            continue
        grid = _decode_rle(runs, CELLS * CELLS)
        mask = grid == S_PARKING
        if not mask.any():
            continue
        origin = chunk["origin"]
        out = {"veh": [], "prop": [], "tree": []}
        for comp in _components(mask):
            _region_furniture(comp, origin, mask, out)
        if not (out["veh"] or out["prop"] or out["tree"]):
            continue
        chunk.setdefault("vehicles", []).extend(out["veh"])
        chunk.setdefault("props", []).extend(out["prop"])
        chunk.setdefault("trees", []).extend(out["tree"])
        chunk["_pk_ens"] = 1
        cars += len(out["veh"]); poles += len(out["prop"]); trees += len(out["tree"])
        payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
        with open(fn, "wb") as f:
            f.write(gzip.compress(payload, mtime=0))
    return cars, poles, trees


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle")
    args = ap.parse_args(argv)
    cars, poles, trees = repatch_bundle(args.bundle)
    print("added %d parked cars, %d light poles, %d island trees in %s"
          % (cars, poles, trees, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Offline: put 18-wheelers and oil tankers into an already-compiled bundle by
promoting some box trucks to big rigs — without a full recompile.

A semi is ~17 m long, so it only belongs on a road or a loading apron, never in a
parking stall. This decodes each chunk's surface raster and only promotes box
trucks whose cell is a road or other-impervious (loading/industrial) surface,
leaving any parked in a stall alone. Position, heading and colour variant are
kept; the choice is a stable hash of the rounded position. The compiler-side
vehicle grammar placing these directly is the follow-up.

    python -m tools.repatch_big_rigs godot/bundles/houston
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys

import numpy as np

S_ROAD = 0
S_OTHER_IMPERVIOUS = 3
CELLS = 128
CELL_M = 2.0

P_PROMOTE = 0.7     # of eligible box trucks, this fraction become big rigs
P_TANKER = 0.35     # of those promoted, this fraction are tankers (rest semis)


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


def _h01(x: float, z: float, salt: int) -> float:
    a = (int(round(x * 4.0)) ^ (salt * 2654435761)) & 0xFFFFFFFF
    b = int(round(z * 4.0)) & 0xFFFFFFFF
    h = (a * 0x9E3779B1) ^ (b * 0x85EBCA6B)
    h &= 0x7FFFFFFF
    h ^= (h >> 13)
    h = (h * 0x2545F491) & 0x7FFFFFFF
    return (h % 1000000) / 1000000.0


def repatch_bundle(bundle_dir: str) -> tuple[int, int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    semis = tankers = boxes = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        veh = chunk.get("vehicles", [])
        if not veh:
            continue
        runs = chunk.get("surface", [])
        grid = _decode_rle(runs, CELLS * CELLS) if runs else None
        ox, oz = chunk.get("origin", [0.0, 0.0])
        dirty = False
        for v in veh:
            if not isinstance(v, list) or len(v) < 3 or v[0] != "box_truck":
                continue
            boxes += 1
            x = float(v[1]); z = float(v[2])
            on_road = True
            if grid is not None:
                col = int((x - ox) / CELL_M)
                row = int((z - oz) / CELL_M)
                if 0 <= row < CELLS and 0 <= col < CELLS:
                    cls = int(grid[row, col])
                    on_road = cls in (S_ROAD, S_OTHER_IMPERVIOUS)
                else:
                    on_road = False
            if not on_road:
                continue
            if _h01(x, z, 1) >= P_PROMOTE:
                continue
            if _h01(x, z, 2) < P_TANKER:
                v[0] = "oil_tanker"; tankers += 1
            else:
                v[0] = "semi_truck"; semis += 1
            dirty = True
        if dirty:
            payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
            with open(fn, "wb") as f:
                f.write(gzip.compress(payload, mtime=0))
    return semis, tankers, boxes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="bundle dir, e.g. godot/bundles/houston")
    args = ap.parse_args(argv)
    semis, tankers, boxes = repatch_bundle(args.bundle)
    print("promoted %d semis + %d tankers (of %d box trucks) in %s"
          % (semis, tankers, boxes, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

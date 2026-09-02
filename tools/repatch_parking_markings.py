"""Offline P0-D5: generate a `ground_markings` stream (parking-stall striping) for
an already-compiled world bundle, so parking fields read as laid-out lots instead
of blank grey polygons.

The renderer batches a chunk's whole `ground_markings` list into one thin mesh
(exterior_world._build_ground_markings), so this adds real parking structure for
almost no node cost. Records are [x, z, heading_deg, length, kind]; here every
record is a parking-stall divider stripe.

Layout is derived from the chunk's own S_PARKING raster: each contiguous parking
region is oriented by PCA (major axis = the aisle direction), then tiled with rows
of stall dividers (depth 5 m, pitch 2.7 m) separated by 6 m drive aisles. Each
stripe is kept only if its centre actually falls on a parking cell, so irregular
lots don't spill stripes onto grass or buildings.

This is a presentation-layer marking pass (like the existing road-lane markings),
run offline because a from-source recompile needs the Overture data. It never
touches building/appearance truth.

    python -m tools.repatch_parking_markings godot/bundles/houston
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

STALL_PITCH = 2.7      # spacing between stall divider lines along the aisle
STALL_DEPTH = 5.0      # stall depth (stripe length)
AISLE = 6.0            # drive aisle between back-to-back stall rows
MIN_REGION_CELLS = 16  # ignore parking blobs under ~64 m²
MAX_MARKS_PER_CHUNK = 400


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
    return out.reshape(CELLS, CELLS)   # [row, col]


def _components(mask):
    """Connected components (4-neighbour) of a boolean grid, via iterative BFS."""
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for r in range(CELLS):
        for c in range(CELLS):
            if not mask[r, c] or seen[r, c]:
                continue
            stack = [(r, c)]
            seen[r, c] = True
            cells = []
            while stack:
                rr, cc = stack.pop()
                cells.append((rr, cc))
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr, nc = rr + dr, cc + dc
                    if 0 <= nr < CELLS and 0 <= nc < CELLS and mask[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        stack.append((nr, nc))
            if len(cells) >= MIN_REGION_CELLS:
                comps.append(cells)
    return comps


def _region_marks(cells, origin, mask):
    ox, oz = origin
    pts = np.array([[ox + (c + 0.5) * CELL_M, oz + (r + 0.5) * CELL_M] for r, c in cells])
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T)
    if not np.all(np.isfinite(cov)):
        return []
    evals, evecs = np.linalg.eigh(cov)
    u = evecs[:, int(np.argmax(evals))]        # major axis (aisle direction)
    v = np.array([-u[1], u[0]])                # minor axis (stall depth direction)
    pu = (pts - mean) @ u
    pv = (pts - mean) @ v
    umin, umax = pu.min(), pu.max()
    vmin, vmax = pv.min(), pv.max()
    if umax - umin < 6.0:
        return []
    heading = math.degrees(math.atan2(v[1], v[0]))

    def on_parking(wx, wz):
        col = int((wx - ox) / CELL_M)
        row = int((wz - oz) / CELL_M)
        return 0 <= row < CELLS and 0 <= col < CELLS and mask[row, col]

    marks = []
    band_v = vmin + STALL_DEPTH * 0.5
    while band_v <= vmax:
        uu = umin + STALL_PITCH * 0.5
        while uu <= umax:
            p = mean + u * uu + v * band_v
            if on_parking(p[0], p[1]):
                marks.append([round(float(p[0]), 2), round(float(p[1]), 2),
                              round(heading, 1), STALL_DEPTH, "parking_stall"])
            uu += STALL_PITCH
        band_v += STALL_DEPTH + AISLE
    return marks


def repatch_bundle(bundle_dir: str) -> tuple[int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    total_marks = lots = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        runs = chunk.get("surface", [])
        if not runs:
            continue
        grid = _decode_rle(runs, CELLS * CELLS)
        mask = grid == S_PARKING
        if not mask.any():
            # clear any stale stream, keep file unchanged otherwise
            if "ground_markings" in chunk:
                del chunk["ground_markings"]
            else:
                continue
            marks = []
        else:
            ox, oz = chunk["origin"]
            marks = []
            for cells in _components(mask):
                marks.extend(_region_marks(cells, (ox, oz), mask))
                if len(marks) >= MAX_MARKS_PER_CHUNK:
                    break
            marks = marks[:MAX_MARKS_PER_CHUNK]
            if marks:
                lots += 1
            chunk["ground_markings"] = marks
        total_marks += len(marks)
        payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
        with open(fn, "wb") as f:
            f.write(gzip.compress(payload, mtime=0))
    return total_marks, lots


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="bundle dir, e.g. godot/bundles/houston")
    args = ap.parse_args(argv)
    marks, lots = repatch_bundle(args.bundle)
    print("wrote %d stall markings across %d parking chunks in %s" % (marks, lots, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

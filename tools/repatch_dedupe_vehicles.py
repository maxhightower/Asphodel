"""Offline: remove overlapping vehicles from a compiled bundle.

Promoting box trucks to 17 m big rigs (and adding parked cars) can leave vehicles
whose footprints intersect — most visibly two 18-wheeler trailers clipping through
each other at an industrial dock. This greedily de-overlaps each chunk's vehicles:
process largest-first (so a big rig is kept over a car it overlaps) and drop any
vehicle whose oriented bounding box overlaps one already kept.

Run last, after every other vehicle pass. The correctness guard is
tests/test_vehicle_overlap.py.

    python -m tools.repatch_dedupe_vehicles godot/bundles/houston
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys

from tools.vehicle_geometry import dims, obb_overlap

# Footprints shrunk to 0.9 when testing, so tightly-packed parking that merely
# touches is kept and only real overlaps are removed.
DEDUP_SCALE = 0.9


def _dedupe(vehicles: list) -> list:
    rows = [v for v in vehicles if isinstance(v, list) and len(v) >= 4]
    other = [v for v in vehicles if not (isinstance(v, list) and len(v) >= 4)]
    # largest footprint first so big rigs win over cars
    rows.sort(key=lambda v: dims(v[0])[0] * dims(v[0])[1], reverse=True)
    kept = []
    for v in rows:
        a = (float(v[1]), float(v[2]), float(v[3]), v[0])
        if any(obb_overlap(a, k, DEDUP_SCALE) for k in kept):
            continue
        kept.append(a)
    keep_keys = {(round(a[0], 2), round(a[1], 2), a[3]) for a in kept}
    out = other + [v for v in rows if (round(float(v[1]), 2), round(float(v[2]), 2), v[0]) in keep_keys]
    return out


def repatch_bundle(bundle_dir: str) -> tuple[int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    removed = total = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        veh = chunk.get("vehicles", [])
        if not veh:
            continue
        total += len(veh)
        deduped = _dedupe(veh)
        if len(deduped) != len(veh):
            removed += len(veh) - len(deduped)
            chunk["vehicles"] = deduped
            payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
            with open(fn, "wb") as f:
                f.write(gzip.compress(payload, mtime=0))
    return removed, total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle")
    args = ap.parse_args(argv)
    removed, total = repatch_bundle(args.bundle)
    print("removed %d overlapping vehicles of %d in %s" % (removed, total, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

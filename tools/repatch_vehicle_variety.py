"""Offline: introduce the new vehicle body styles (jeep, sports_car) into an
already-compiled bundle's baked `vehicles` stream, so the fleet shows more variety
without a full recompile.

A deterministic fraction of existing vehicles is remapped by body category:
some SUVs become jeeps, some sedans become sports cars. Position/heading/colour
variant are untouched, and the choice is a stable hash of the vehicle's rounded
position, so reloads reproduce the same fleet. The compiler-side equivalent (the
vehicle grammar in detail.py placing these kinds directly) is the follow-up.

    python -m tools.repatch_vehicle_variety godot/bundles/houston
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys

# (source kind, target kind, probability)
REMAP = [
    ("suv", "jeep", 0.38),
    ("sedan", "sports_car", 0.28),
]


def _h01(x: float, z: float) -> float:
    # small stable hash of a quantised position -> [0,1)
    a = int(round(x * 4.0)) & 0xFFFFFFFF
    b = int(round(z * 4.0)) & 0xFFFFFFFF
    h = (a * 0x9E3779B1) ^ (b * 0x85EBCA6B)
    h &= 0x7FFFFFFF
    h ^= (h >> 13)
    h = (h * 0x2545F491) & 0x7FFFFFFF
    return (h % 1000000) / 1000000.0


def repatch_bundle(bundle_dir: str) -> tuple[int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    changed = total = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        veh = chunk.get("vehicles", [])
        if not veh:
            continue
        dirty = False
        for v in veh:
            if not isinstance(v, list) or len(v) < 3:
                continue
            total += 1
            kind = v[0]
            r = _h01(float(v[1]), float(v[2]))
            for src, dst, p in REMAP:
                if kind == src and r < p:
                    v[0] = dst
                    changed += 1
                    dirty = True
                    break
        if dirty:
            payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
            with open(fn, "wb") as f:
                f.write(gzip.compress(payload, mtime=0))
    return changed, total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="bundle dir, e.g. godot/bundles/houston")
    args = ap.parse_args(argv)
    changed, total = repatch_bundle(args.bundle)
    print("remapped %d / %d vehicles to new body styles in %s" % (changed, total, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

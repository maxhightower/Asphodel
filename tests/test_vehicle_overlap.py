"""Correctness guard: no two vehicles in a compiled chunk overlap.

Vehicles are placed by several passes (compiler, parking fill, big-rig promotion),
so footprints can collide — most visibly two 18-wheelers clipping through each
other. This scans the shipped Houston bundle and asserts every chunk is overlap-
free at a 0.85 footprint scale (so bumper-to-bumper parking is allowed, real
intersections are not). tools/repatch_dedupe_vehicles enforces it."""
from __future__ import annotations

import glob
import gzip
import json
import os

from tools.vehicle_geometry import obb_overlap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(REPO, "godot", "bundles", "houston", "world", "chunks")
TEST_SCALE = 0.85


def _overlaps_in_chunk(vehicles):
    rows = [(float(v[1]), float(v[2]), float(v[3]), v[0])
            for v in vehicles if isinstance(v, list) and len(v) >= 4]
    hits = []
    # sort by x so we can prune pairs that are far apart on the x axis (semis are
    # <=17 m, so once xj - xi exceeds that they cannot touch)
    rows.sort(key=lambda r: r[0])
    for i in range(len(rows)):
        xi = rows[i][0]
        for j in range(i + 1, len(rows)):
            if rows[j][0] - xi > 18.0:
                break
            if obb_overlap(rows[i], rows[j], TEST_SCALE):
                hits.append((rows[i], rows[j]))
    return hits


def test_no_overlapping_vehicles_in_houston():
    files = sorted(glob.glob(os.path.join(BUNDLE, "c_*.json.gz")))
    assert files, "houston chunks not found"
    offenders = []
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        veh = chunk.get("vehicles", [])
        if len(veh) < 2:
            continue
        hits = _overlaps_in_chunk(veh)
        if hits:
            a, b = hits[0]
            offenders.append("%s: %s@(%.1f,%.1f) overlaps %s@(%.1f,%.1f) (+%d more)"
                             % (os.path.basename(fn), a[3], a[0], a[1],
                                b[3], b[0], b[1], len(hits) - 1))
    assert not offenders, "overlapping vehicles:\n" + "\n".join(offenders[:20])

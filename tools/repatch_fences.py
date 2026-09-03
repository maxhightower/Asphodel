"""Offline: regenerate yard fences on an already-compiled bundle using the fixed
per-building routing (detail.py `_fences`), without a full recompile.

The old baked fences traced block-level parcel polygons and spiked diagonally
across yards. This drops every existing wood/chainlink fence prop and rebuilds one
tidy rectangular yard fence per building — aligned to the building's own footprint
(oriented bounding box + small margin), fenced on the three non-street sides
(street side found from the baked entrance) and open to the street. Residential
yards get a consistent style baked into the panel variant (0 picket, 1 privacy,
2 split rail, 3 iron); industrial yards get chain-link; civic gets iron.

    python -m tools.repatch_fences godot/bundles/houston
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import sys

from shapely.geometry import Polygon, Point

FENCE_SPACING = 2.0
MAX_PANELS_PER_EDGE = 24


def _h01(bid: int, salt: int) -> float:
    h = ((bid * 0x9E3779B1) ^ (salt * 0x85EBCA6B)) & 0x7FFFFFFF
    h ^= (h >> 13)
    h = (h * 0x2545F491) & 0x7FFFFFFF
    return (h % 1000000) / 1000000.0


def _heading_deg(dx: float, dz: float) -> float:
    return math.degrees(math.atan2(dx, dz))


def _fences_for_building(b: dict) -> list:
    arch = b.get("arch", "")
    if arch in ("DETACHED_RESIDENTIAL", "MULTIFAMILY"):
        kind, residential = "wood_fence", True
    elif arch == "INDUSTRIAL":
        kind, residential = "chainlink_fence", False
    elif arch == "CIVIC_SPECIAL":
        kind, residential = "wood_fence", True
    else:
        return []
    poly_pts = b.get("poly", [])
    if len(poly_pts) < 3:
        return []
    bid = int(b.get("bid", 0))
    if _h01(bid, 1) >= (0.6 if arch == "INDUSTRIAL" else 0.4):
        return []
    try:
        poly = Polygon(poly_pts)
        if not poly.is_valid or poly.area < 4.0:
            return []
        coords = list(poly.minimum_rotated_rectangle.exterior.coords)[:-1]
    except Exception:
        return []
    if len(coords) != 4:
        return []
    cx, cz = poly.centroid.x, poly.centroid.y
    margin = 1.5 + _h01(bid, 2) * 1.5
    exp = []
    for (x, z) in coords:
        dx, dz = x - cx, z - cz
        d = math.hypot(dx, dz) or 1.0
        exp.append((x + dx / d * margin, z + dz / d * margin))
    edges = [(exp[i], exp[(i + 1) % 4]) for i in range(4)]
    # entrance point (faces the street) → skip the nearest expanded-rect edge
    ent = b.get("entrance", {}) or {}
    ei = int(ent.get("edge", 0)) % len(poly_pts)
    t = float(ent.get("t", 0.5))
    ea = poly_pts[ei]
    eb = poly_pts[(ei + 1) % len(poly_pts)]
    entx = ea[0] + (eb[0] - ea[0]) * t
    entz = ea[1] + (eb[1] - ea[1]) * t

    def emid(e):
        return ((e[0][0] + e[1][0]) * 0.5, (e[0][1] + e[1][1]) * 0.5)

    skip_i = min(range(4), key=lambda i: math.dist(emid(edges[i]), (entx, entz)))
    if residential and kind == "wood_fence":
        style = 3 if arch == "CIVIC_SPECIAL" else int(_h01(bid, 3) * 4) % 4
    else:
        style = 0

    out = []
    for i, (a, c) in enumerate(edges):
        if i == skip_i:
            continue
        dx, dz = c[0] - a[0], c[1] - a[1]
        ln = math.hypot(dx, dz)
        if ln < 1.0:
            continue
        ux, uz = dx / ln, dz / ln
        heading = round(_heading_deg(dx, dz), 1)
        n = min(MAX_PANELS_PER_EDGE, max(1, int(ln // FENCE_SPACING)))
        for k in range(n):
            d = (k + 0.5) * FENCE_SPACING
            if d >= ln:
                continue
            px = round(a[0] + ux * d, 2)
            pz = round(a[1] + uz * d, 2)
            out.append([kind, px, pz, heading, style])
    return out


def repatch_bundle(bundle_dir: str) -> tuple[int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    removed = added = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        props = chunk.get("props", [])
        kept = [p for p in props if not (isinstance(p, list) and p and
                p[0] in ("wood_fence", "chainlink_fence"))]
        removed += len(props) - len(kept)
        new_fences = []
        for b in chunk.get("buildings", []):
            new_fences.extend(_fences_for_building(b))
        added += len(new_fences)
        chunk["props"] = kept + new_fences
        payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
        with open(fn, "wb") as f:
            f.write(gzip.compress(payload, mtime=0))
    return removed, added


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="bundle dir, e.g. godot/bundles/houston")
    args = ap.parse_args(argv)
    removed, added = repatch_bundle(args.bundle)
    print("replaced %d old fence panels with %d per-building yard panels in %s"
          % (removed, added, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

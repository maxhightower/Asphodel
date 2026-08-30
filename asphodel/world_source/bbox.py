"""City bounding boxes, read from the committed Godot bundle metadata.

Bundle authority boundary: this module never invents or hardcodes city
geometry -- it reads the (S, W, N, E) bbox already committed at
``godot/bundles/<city>/meta.json`` (the same bbox the Godot frontend and the
OSM city pipeline use) and re-expresses it as (W, S, E, N), the ordering
Overture's tooling and most GIS conventions expect.
"""
from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_BUNDLES_DIR = os.path.join(_REPO_ROOT, "godot", "bundles")


class BundleNotFound(Exception):
    """No committed bundle meta.json for the requested city."""


def bundle_meta_path(city: str) -> str:
    return os.path.join(_BUNDLES_DIR, city, "meta.json")


def load_bundle_meta(city: str) -> dict:
    path = bundle_meta_path(city)
    if not os.path.exists(path):
        raise BundleNotFound(f"No bundle meta.json for city {city!r} at {path}")
    with open(path) as f:
        return json.load(f)


def city_bbox(city: str) -> tuple[float, float, float, float]:
    """Return (W, S, E, N) for `city`, read from its committed bundle meta.json.

    The bundle's own `bbox` field is stored as [S, W, N, E] (lat/lon min/max);
    this function re-orders it to (W, S, E, N) longitude/latitude order.
    """
    meta = load_bundle_meta(city)
    s, w, n, e = meta["bbox"]
    return (w, s, e, n)


def _cli(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m asphodel.world_source bbox <city>", file=sys.stderr)
        return 2
    city = argv[0]
    try:
        w, s, e, n = city_bbox(city)
    except BundleNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{w} {s} {e} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))

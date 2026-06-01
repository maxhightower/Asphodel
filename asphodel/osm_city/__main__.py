"""CLI: python -m asphodel.osm_city "<city>" --out <dir>

Geocodes the city, fetches OSM (cached), and writes a bundle Godot can load.
"""
from __future__ import annotations

import argparse
import sys

from . import OSMError
from .geocode import geocode
from .overpass import fetch_osm, parse_osm
from .pipeline import build_bundle


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="asphodel.osm_city")
    p.add_argument("city", help="City name to geocode, e.g. \"Chicago\"")
    p.add_argument("--out", required=True, help="Output bundle directory")
    p.add_argument("--grid", type=int, default=16, help="Cells along the longer axis")
    p.add_argument("--total-pop", type=float, default=500000.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--days", type=float, default=120.0)
    p.add_argument("--cache", default=None, help="OSM response cache directory")
    p.add_argument("--max-span-deg", type=float, default=0.5)
    args = p.parse_args(argv)

    try:
        bbox = geocode(args.city, max_span_deg=args.max_span_deg)
        data = fetch_osm(bbox, cache_dir=args.cache)
        buildings, roads = parse_osm(data)
        build_bundle(
            query=args.city, bbox=bbox, buildings=buildings, roads=roads,
            out_dir=args.out, grid=args.grid, total_pop=args.total_pop,
            seed=args.seed, n_days=args.days,
        )
    except OSMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote bundle to {args.out} "
          f"({len(buildings)} buildings, {len(roads)} roads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

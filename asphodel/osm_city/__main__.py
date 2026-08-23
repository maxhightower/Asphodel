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
    p.add_argument("--max-buildings", type=int, default=30000,
                   help="Cap on baked footprints (nearest to center kept)")
    p.add_argument("--cities-dir", default="cities", help="Dir of city-profile YAMLs")
    p.add_argument("--citizens-per-profile", type=int, default=15)
    p.add_argument("--no-citizens", action="store_true", help="Skip citizen baking")
    args = p.parse_args(argv)

    try:
        bbox = geocode(args.city, max_span_deg=args.max_span_deg)
        data = fetch_osm(bbox, cache_dir=args.cache)
        buildings, roads = parse_osm(data)
        build_bundle(
            query=args.city, bbox=bbox, buildings=buildings, roads=roads,
            out_dir=args.out, grid=args.grid, total_pop=args.total_pop,
            seed=args.seed, n_days=args.days, max_buildings=args.max_buildings,
        )
    except OSMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote bundle to {args.out} "
          f"({len(buildings)} buildings, {len(roads)} roads)")

    if not args.no_citizens:
        from .citizens import write_citizens
        n = write_citizens(args.out, cities_dir=args.cities_dir,
                           n_per_profile=args.citizens_per_profile, seed=args.seed)
        print(f"Baked {n} citizens into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

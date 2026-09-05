#!/usr/bin/env python3
"""Bake a bundle's canonical street graph — and nothing else.

    python tools/bake_streetmap.py <city> [--release 2026-08-19.0]

Writes ONLY ``godot/bundles/<city>/streetmap.json``. Every other bundle file
(region/physics/roads/mobility/zones/timeline/buildings and all of ``world/``)
is left untouched, so a re-bake of the graph can never perturb the compiled
presentation artifacts or their byte-determinism guarantees.

The graph is split at Overture connectors when the raw packet is on disk
(``data/raw/overture/<release>/<city>/{segment,connector}.parquet``) and falls
back to the legacy ``roads.json`` polylines otherwise; the source used is
printed and recorded in the artifact's ``source`` field.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.region_bundle import build_mobility_artifact, street_source_for  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLES = os.path.join(REPO, "godot", "bundles")


def bake(city: str, release: str, data_root: str = "data/raw") -> dict:
    bundle_dir = os.path.join(BUNDLES, city)
    if not os.path.isdir(bundle_dir):
        raise SystemExit(f"no bundle at {bundle_dir}")

    ws = street_source_for(bundle_dir, release, data_root=data_root)
    if ws is not None:
        label = f"world_source/overture@{release}"
        print(f"[{city}] source: {label} "
              f"({len(ws.roads)} roads, {len(ws.connectors)} connectors)")
        roads = {}
    else:
        label = "roads.json/polylines"
        print(f"[{city}] source: {label} (no Overture packet for {release})")
        with open(os.path.join(bundle_dir, "roads.json")) as f:
            roads = json.load(f)

    art = build_mobility_artifact(roads, ws=ws, source_label=label)
    out = os.path.join(bundle_dir, "streetmap.json")
    with open(out, "w") as f:
        json.dump(art, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
    st = art["stats"]
    print(f"[{city}] wrote {out}")
    print(f"[{city}] nodes={st['nodes']} segments={st['segments']} "
          f"directed_edges={st['directed_edges']} "
          f"oneway={st['oneway_segments']} km={st['length_km']}")
    return art


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("city")
    ap.add_argument("--release", default="2026-08-19.0")
    ap.add_argument("--data-root", default="data/raw")
    args = ap.parse_args(argv)
    bake(args.city, args.release, args.data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

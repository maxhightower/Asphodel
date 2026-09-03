#!/usr/bin/env python3
"""Residential architecture census.

Two modes:

  1. On a compiled bundle report JSON (from asphodel.world_source.compile_city),
     print the `residential_census` / `residential_architecture` blocks:

         python tools/residential_census.py --report path/to/report.json

  2. Synthetic city (default; no compiled Houston bundle needed in CI): generate
     a grid of residential blocks with realistic footprints, run the real
     compile stages (buildings_grammar + residential_grammar), and report the
     citywide architecture distribution, cohort structure, style entropy and the
     median distinct-styles-per-block. This exercises exactly the authority path
     the mission specifies and demonstrates the system does NOT collapse to a
     single style, while keeping each block internally coherent.

         python tools/residential_census.py [--blocks 240] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter

from shapely.geometry import Polygon

from asphodel.world_source import buildings_grammar, residential_grammar as rg
from asphodel.world_source.records import Parcel
from asphodel.world_source.schema import Feature
from asphodel.city_visual.residential_architecture import FACADE_SUBTYPE_TO_FAMILY


def _rect(cx, cz, w, d):
    return [[(cx - w / 2, cz - d / 2), (cx + w / 2, cz - d / 2),
             (cx + w / 2, cz + d / 2), (cx - w / 2, cz + d / 2)]]


def _lshape(cx, cz, w, d):
    return [[(cx, cz), (cx + w, cz), (cx + w, cz + d * 0.5),
             (cx + w * 0.5, cz + d * 0.5), (cx + w * 0.5, cz + d), (cx, cz + d)]]


def _house_geom(rng, cx, cz):
    """A footprint whose shape varies (compact, elongated, square, L) so forms
    are morphology-driven, not uniform."""
    r = rng.random()
    if r < 0.30:
        return _rect(cx, cz, rng.uniform(9, 13), rng.uniform(8, 11))     # compact
    if r < 0.55:
        return _rect(cx, cz, rng.uniform(18, 26), rng.uniform(7, 9))     # elongated
    if r < 0.75:
        return _rect(cx, cz, rng.uniform(11, 14), rng.uniform(11, 14))   # square
    if r < 0.90:
        return _lshape(cx, cz, rng.uniform(14, 20), rng.uniform(11, 15)) # L
    return _rect(cx, cz, rng.uniform(14, 20), rng.uniform(10, 13))       # mid


def synth_city(n_blocks: int, seed: int, lat=29.76, lon=-95.36):
    import random
    all_recs = []
    block_styles = []          # list of Counter per block
    grid = int(math.ceil(math.sqrt(n_blocks)))
    bid = 0
    for bi in range(n_blocks):
        bx = (bi % grid) * 220.0
        bz = (bi // grid) * 220.0
        rng = random.Random((seed << 8) ^ bi)
        n_houses = rng.randint(6, 14)
        feats = []
        bids = []
        for h in range(n_houses):
            cx = bx + 30 + (h % 4) * 40 + rng.uniform(-4, 4)
            cz = bz + 30 + (h // 4) * 40 + rng.uniform(-4, 4)
            g = _house_geom(rng, cx, cz)
            props = {"subtype": "residential", "_area": Polygon(g[0]).area}
            feats.append(Feature(stable_key=f"b{bi}h{h}", geometry=g,
                                 geom_type="polygon", properties=props,
                                 source="synthetic", source_id=f"b{bi}h{h}"))
            bids.append(bid)
            bid += 1
        blockpoly = Polygon([(bx, bz), (bx + 200, bz), (bx + 200, bz + 200),
                             (bx, bz + 200)])
        parcel = Parcel(pid=f"p:{bi}", poly=blockpoly, arch="RESIDENTIAL",
                        obs="DERIVED", block_id=bi, building_bids=bids)
        recs = buildings_grammar.compile_buildings(feats, [parcel], [], seed)
        rg.assign_architecture(recs, [parcel], [blockpoly], seed, lat=lat, lon=lon,
                               props_by_bid={r.bid: f.properties
                                             for r, f in zip(recs, feats)})
        all_recs.extend(recs)
        block_styles.append(Counter(r.architecture["style"]["value"] for r in recs))
    return all_recs, block_styles


def _entropy(counter: Counter) -> float:
    total = sum(counter.values())
    if total == 0:
        return 0.0
    h = 0.0
    for v in counter.values():
        p = v / total
        h -= p * math.log2(p)
    return h


def report_synth(n_blocks: int, seed: int):
    recs, block_styles = synth_city(n_blocks, seed)
    cen = rg.census(recs)
    dist = cen["distributions"]
    n = cen["houses"]
    print(f"=== RESIDENTIAL ARCHITECTURE CENSUS (synthetic, {n_blocks} blocks) ===")
    print(f"detached_house_count: {n}")
    print(f"number_of_residential_blocks: {n_blocks}")
    print(f"number_of_cohorts: {n_blocks}   (one per block; spatially correlated era)")
    for key in ("era", "form", "style", "foundation", "roof_family",
                "roof_material", "facade_front_family", "parking", "porch"):
        rows = sorted(dist[key].items(), key=lambda kv: -kv[1])
        pretty = ", ".join(f"{k} {v} ({100*v/n:.0f}%)" for k, v in rows)
        print(f"  by {key}: {pretty}")
    print(f"era_provenance: {cen['era_provenance']}")
    style_counter = Counter(dist["style"])
    print(f"style_entropy_citywide: {_entropy(style_counter):.2f} bits "
          f"(max {math.log2(len(rg.STYLES_PROD)):.2f} for {len(rg.STYLES_PROD)} styles)")
    per_block = sorted(len(bs) for bs in block_styles)
    med = per_block[len(per_block) // 2]
    print(f"median_distinct_styles_per_block: {med} "
          f"(min {per_block[0]}, max {per_block[-1]})")
    # coherence check: dominant style share within a block (should be high)
    dom_shares = []
    for bs in block_styles:
        if sum(bs.values()):
            dom_shares.append(max(bs.values()) / sum(bs.values()))
    print(f"mean_block_dominant_style_share: {sum(dom_shares)/len(dom_shares):.2f} "
          f"(high => blocks are internally coherent, not random soup)")
    print("source-data coverage (synthetic): observed height/floors/roof/facade/"
          "year = 0% (all inferred, provenance honest)")


def report_bundle(path: str):
    with open(path) as f:
        rep = json.load(f)
    for key in ("residential_architecture", "residential_census"):
        if key in rep:
            print(f"=== {key} ===")
            print(json.dumps(rep[key], indent=2, sort_keys=True))
        else:
            print(f"(report has no '{key}' block)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", help="compiled bundle report JSON to summarise")
    ap.add_argument("--blocks", type=int, default=240)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    if args.report:
        report_bundle(args.report)
    else:
        report_synth(args.blocks, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

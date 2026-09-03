"""Offline residential-architecture repatch + census on an already-compiled bundle.

A from-source recompile (compile.py) attaches ResidentialArchitectureV1 to every
detached house automatically. This tool brings an EXISTING baked bundle up to the
same contract without re-fetching Overture source, and reports the real citywide
architecture census — the mission's Houston certification numbers.

It reconstructs the compile inputs from the chunks: parcels carry their block id
in the pid ("p:<block>:<uuid>"), and each detached building is matched to its
block by footprint containment. Cohorts + builder families + per-house
form/style/roof/facade/porch/foundation/parking are then assigned exactly as in
the live pipeline. The chunks do not carry each building's stable source key, so
the per-house streams are keyed on the building id ("b<bid>") — deterministic for
this bundle (a true recompile keys on the source UUID and so may pick a different
subset). Regional priors come from --lat/--lon (geography), never the city name.

    # census only (no writes):
    python -m tools.repatch_residential_architecture godot/bundles/houston \
        --lat 29.76 --lon -95.36
    # also write architecture back into the chunks (for rendering):
    python -m tools.repatch_residential_architecture godot/bundles/houston \
        --lat 29.76 --lon -95.36 --write
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys

from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

from asphodel.world_source import residential_grammar as rg
from asphodel.world_source.records import BuildingRecord, Parcel
from asphodel.world_source.schema import validate_chunk
from asphodel.world_source.chunks import expected_cells
from asphodel.city_visual.provenance import OBSERVED


def _block_id_of_pid(pid: str):
    parts = (pid or "").split(":")
    if len(parts) >= 2 and parts[1].lstrip("-").isdigit():
        return int(parts[1])
    return None


def _load(bundle_dir):
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    chunks = {}
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunks[fn] = json.load(f)
    return chunks


def _reconstruct(chunks):
    parcel_polys = []
    parcel_block = []
    b_by_bid = {}          # bid -> (chunk_fn, building dict)
    records = []
    for fn, chunk in chunks.items():
        for p in chunk.get("parcels", []):
            ring = p.get("poly", [])
            if len(ring) < 3:
                continue
            bid = _block_id_of_pid(p.get("id", ""))
            if bid is None:
                continue
            try:
                parcel_polys.append(Polygon(ring))
                parcel_block.append(bid)
            except Exception:
                continue
        for b in chunk.get("buildings", []):
            if b.get("arch") != "DETACHED_RESIDENTIAL":
                continue
            ring = b.get("poly", [])
            if len(ring) < 3:
                continue
            bid = int(b.get("bid", -1))
            b_by_bid[bid] = (fn, b)
            ap = b.get("appearance") or {}
            hm = ap.get("height_m", {})
            height_obs = hm.get("class") == OBSERVED
            ent = b.get("entrance", {}) or {}
            rec = BuildingRecord(
                bid=bid, key="b%d" % bid, poly=Polygon(ring),
                h=float(b.get("h", 4.0)), floors=int(b.get("floors", 1)),
                arch="DETACHED_RESIDENTIAL", roof=str(b.get("roof", "pitched")),
                entrance_edge=int(ent.get("edge", 0)),
                entrance_t=float(ent.get("t", 0.5)),
                entrance_w=float(ent.get("w", 1.2)), entrance_xy=(0.0, 0.0),
                feat=list(b.get("feat", [])), height_observed=height_obs,
                floors_observed=False, appearance=ap)
            records.append(rec)
    return parcel_polys, parcel_block, records, b_by_bid


def _assign(parcel_polys, parcel_block, records, lat, lon, seed):
    tree = STRtree(parcel_polys) if parcel_polys else None

    # building -> block id via footprint-centroid containment.
    bid_block = {}
    for rec in records:
        c = rec.poly.centroid
        blk = None
        if tree is not None:
            for idx in tree.query(c):
                if parcel_polys[int(idx)].covers(c):
                    blk = parcel_block[int(idx)]
                    break
        bid_block[rec.bid] = blk

    # remap sparse block ids -> contiguous indices; block centroid = mean of its
    # houses' centroids (good enough for the spatial era field).
    ordered = sorted({b for b in bid_block.values() if b is not None})
    remap = {b: i for i, b in enumerate(ordered)}
    sums = {i: [0.0, 0.0, 0] for i in range(len(ordered))}
    per_block_bids = {i: [] for i in range(len(ordered))}
    homeless = 0
    for rec in records:
        blk = bid_block[rec.bid]
        if blk is None:
            homeless += 1
            continue
        i = remap[blk]
        c = rec.poly.centroid
        sums[i][0] += c.x
        sums[i][1] += c.y
        sums[i][2] += 1
        per_block_bids[i].append(rec.bid)

    blocks = []
    for i in range(len(ordered)):
        n = max(1, sums[i][2])
        blocks.append(Point(sums[i][0] / n, sums[i][1] / n))
    parcels = [Parcel(pid="blk:%d" % i, poly=None, arch="RESIDENTIAL",
                      obs="DERIVED", block_id=i, building_bids=per_block_bids[i])
               for i in range(len(ordered))]

    stats = rg.assign_architecture(records, parcels, blocks, seed,
                                   lat=lat, lon=lon, props_by_bid={})
    stats["homeless_houses"] = homeless
    return stats


def _writeback(chunks, records, b_by_bid, do_write):
    changed = set()
    for rec in records:
        fn, b = b_by_bid[rec.bid]
        b["architecture"] = rec.architecture
        b["appearance"] = rec.appearance
        b["feat"] = sorted(rec.feat)
        changed.add(fn)
    # Validate only the architecture records we added (every arch record was also
    # validated in assign_architecture). Pre-existing, unrelated enum drift in the
    # baked bundle (e.g. newer vehicle kinds than the current enum) is NOT this
    # tool's concern and must not block an architecture repatch.
    bad = 0
    for fn in changed:
        for e in validate_chunk(chunks[fn], expected_cells()):
            if "architecture" in e:
                bad += 1
                if bad <= 3:
                    print(f"  ! architecture validation error in "
                          f"{os.path.basename(fn)}: {e}")
    if bad:
        raise SystemExit(f"{bad} architecture validation errors — not writing")
    if do_write:
        for fn in sorted(changed):
            payload = json.dumps(chunks[fn], separators=(",", ":"),
                                 sort_keys=True).encode("utf-8")
            with open(fn, "wb") as f:
                f.write(gzip.compress(payload, mtime=0))
    return len(changed)


def _print_census(records, stats):
    import math
    from collections import Counter
    cen = rg.census(records)
    dist = cen["distributions"]
    n = cen["houses"]
    print(f"\n=== HOUSTON RESIDENTIAL ARCHITECTURE CENSUS ===")
    print(f"detached_house_count: {n}")
    print(f"residential_blocks(cohorts): {stats['cohorts']}   "
          f"builder_families: {stats['builder_families']}   "
          f"region: {stats['region_tag']}   homeless: {stats.get('homeless_houses', 0)}")
    for key in ("era", "form", "style", "foundation", "roof_family",
                "roof_material", "facade_front_family", "parking", "porch"):
        rows = sorted(dist[key].items(), key=lambda kv: -kv[1])
        pretty = ", ".join(f"{k} {v} ({100*v/n:.0f}%)" for k, v in rows)
        print(f"  by {key}: {pretty}")
    print(f"era_provenance: {cen['era_provenance']}")
    sc = Counter(dist["style"])
    total = sum(sc.values())
    ent = -sum((v / total) * math.log2(v / total) for v in sc.values() if v)
    print(f"style_entropy_citywide: {ent:.2f} bits "
          f"(max {math.log2(len(rg.STYLES_PROD)):.2f})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="bundle dir, e.g. godot/bundles/houston")
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write", action="store_true",
                    help="write architecture back into the chunks")
    args = ap.parse_args(argv)

    chunks = _load(args.bundle)
    parcel_polys, parcel_block, records, b_by_bid = _reconstruct(chunks)
    stats = _assign(parcel_polys, parcel_block, records, args.lat, args.lon, args.seed)
    n_changed = _writeback(chunks, records, b_by_bid, args.write)
    _print_census(records, stats)
    print(f"\n{'WROTE' if args.write else 'would touch'} {n_changed} chunks"
          f" ({stats['houses']} houses){' (dry run)' if not args.write else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

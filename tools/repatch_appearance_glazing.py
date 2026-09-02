"""Offline appearance repatch: apply the height-driven glass-curtain rule to an
already-compiled world bundle, without a full recompile (which needs the Overture
source).

`appearance_infer.py` now biases tall buildings toward a full glass_curtain facade
(see glass_probability). A from-source recompile picks this up automatically; this
tool brings an existing baked bundle up to the same rule so it can be rendered
without re-fetching source data. It only *adds* glazing to tall, non-observed,
non-glass facades — every other building's baked appearance is left byte-identical.

The chunks do not carry each building's stable source key, so the per-building
decision here is keyed on the building id (deterministic, same distribution as the
source rule; a true recompile keys on the UUID and so may glaze a different subset).

    python -m tools.repatch_appearance_glazing godot/bundles/houston [--seed 0]
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import sys

from asphodel.world_source.appearance_infer import (
    glass_probability, _GLASS_WAYS, _pick_way, _hex, _shash, _h01,
)
from asphodel.city_visual.provenance import OBSERVED, PROCEDURAL


def _centroid(poly):
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    return sum(xs) / len(xs), sum(zs) / len(zs)


def _fam_label(arch: str) -> str:
    if "RESIDENTIAL" in arch or arch == "MULTIFAMILY":
        return "residential"
    return {"CIVIC_SPECIAL": "civic", "INDUSTRIAL": "industrial",
            "OFFICE_HIGHRISE": "office"}.get(arch, "commercial")


def _repatch_building(b: dict, seed: int) -> bool:
    ap = b.get("appearance")
    if not ap:
        return False
    fmat = ap.get("facade", {}).get("material", {})
    if fmat.get("class") == OBSERVED or fmat.get("value") == "glass_curtain":
        return False
    h = float(b.get("h", 0.0) or 0.0)
    p = glass_probability(h)
    if p <= 0.0:
        return False
    bid = int(b.get("bid", 0))
    kh = _shash("b%d" % bid) & 0xFFFFFFFF
    if _h01(kh, seed, 71) >= p:
        return False
    # Flip to a full glass curtain wall with a cool curtain-wall colourway.
    cx, cz = _centroid(b["poly"])
    hh, ss, vv = _pick_way(_GLASS_WAYS, cx, cz, kh, seed, 140)
    fmat["value"] = "glass_curtain"
    fmat["class"] = PROCEDURAL
    ap["facade"]["color"] = {"value": _hex(hh, ss, vv), "class": PROCEDURAL}
    sf = ap.get("style_family", {})
    region = "regional"
    if isinstance(sf.get("value"), str) and "_" in sf["value"]:
        region = sf["value"].split("_", 1)[0]
    ap["style_family"] = {"value": "%s_%s_glass_curtain" % (region, _fam_label(b.get("arch", ""))),
                          "class": sf.get("class", "DERIVED")}
    return True


def repatch_bundle(bundle_dir: str, seed: int) -> tuple[int, int]:
    cdir = os.path.join(bundle_dir, "world", "chunks")
    files = sorted(glob.glob(os.path.join(cdir, "c_*.json.gz")))
    if not files:
        raise SystemExit(f"no chunks under {cdir}")
    flipped = total = 0
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            chunk = json.load(f)
        changed = False
        for b in chunk.get("buildings", []):
            total += 1
            if _repatch_building(b, seed):
                flipped += 1
                changed = True
        if changed:
            payload = json.dumps(chunk, separators=(",", ":"), sort_keys=True).encode("utf-8")
            with open(fn, "wb") as f:
                f.write(gzip.compress(payload, mtime=0))
    return flipped, total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", help="bundle dir, e.g. godot/bundles/houston")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    flipped, total = repatch_bundle(args.bundle, args.seed)
    print("glazed %d / %d buildings in %s" % (flipped, total, args.bundle))
    return 0


if __name__ == "__main__":
    sys.exit(main())

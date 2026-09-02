#!/usr/bin/env python3
"""VIS-0 appearance census: measure real Overture building-appearance coverage.

Reads the acquired raw building parquet for one or more cities
(data/raw/overture/<release>/<city>/building.parquet) and reports non-null
coverage of the appearance-bearing columns, plus value distributions and
coverage broken down by Overture building class. Numbers are OBSERVED source
coverage only -- no inference. Run acquisition first:

    python -m asphodel.world_source acquire --city <city> --types building
    python tools/appearance_census.py <city> [<city> ...]
"""
from __future__ import annotations

import collections
import json
import os
import sys

import pyarrow.parquet as pq

RELEASE = "2026-08-19.0"
APPEARANCE_FIELDS = [
    "height", "num_floors", "roof_shape", "roof_material", "roof_color",
    "roof_direction", "facade_material", "facade_color",
]


def _nonnull(col):
    return sum(1 for v in col if v is not None and v != "")


def census_city(city: str, data_root: str = "data/raw") -> dict:
    path = os.path.join(data_root, "overture", RELEASE, city, "building.parquet")
    if not os.path.exists(path):
        return {"city": city, "error": f"missing {path} (run acquire first)"}
    t = pq.read_table(path)
    n = t.num_rows
    cols = {name: t.column(name).to_pylist() if name in t.column_names
            else [None] * n for name in APPEARANCE_FIELDS}
    coverage = {f: {"n": _nonnull(cols[f]),
                    "pct": round(100.0 * _nonnull(cols[f]) / max(n, 1), 2)}
                for f in APPEARANCE_FIELDS}
    # value distributions for the categorical appearance fields
    dists = {}
    for f in ("roof_shape", "roof_material", "facade_material",
              "facade_color", "roof_color"):
        c = collections.Counter(v for v in cols[f] if v not in (None, ""))
        dists[f] = c.most_common(12)
    # "useful combination": has any of facade color/material or roof color/material
    useful = sum(1 for i in range(n) if any(
        cols[k][i] not in (None, "") for k in
        ("facade_color", "facade_material", "roof_color", "roof_material")))
    # coverage by Overture class
    classes = t.column("class").to_pylist() if "class" in t.column_names else [None] * n
    by_class = collections.defaultdict(lambda: collections.Counter())
    for i in range(n):
        cl = classes[i] or "(none)"
        by_class[cl]["total"] += 1
        for f in ("facade_color", "facade_material", "roof_color",
                  "roof_material", "roof_shape"):
            if cols[f][i] not in (None, ""):
                by_class[cl][f] += 1
    class_rows = sorted(by_class.items(), key=lambda kv: -kv[1]["total"])[:12]
    return {
        "city": city, "buildings": n, "coverage": coverage,
        "useful_appearance_rows": {"n": useful,
                                   "pct": round(100.0 * useful / max(n, 1), 2)},
        "distributions": dists,
        "by_class": [(cl, dict(cnt)) for cl, cnt in class_rows],
    }


def main(argv):
    cities = argv or ["madisonville_tx", "houston", "austin", "san_antonio"]
    out = {"release": RELEASE, "cities": [census_city(c) for c in cities]}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])

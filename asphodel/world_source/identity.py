"""OW2: stable geographic identity for buildings.

building_id is a load-bearing contract: interiors, container deltas,
occupancy and Godot AABB lookup all key on the integer index into
buildings.json.  This module founds those integers on stable geography:

- stable_key: the source's stable id (Overture GERS) when present, else a
  deterministic digest of quantized centroid + area ("d:<sha1-16>").
- building_id: index into the list sorted by
  (round(centroid_z*10), round(centroid_x*10), stable_key).

Same (city, source release, compiler version, seed) => same mapping.  The
mapping is persisted to world/identity.json so future source releases can
be diffed instead of silently reshuffling identity.
"""
from __future__ import annotations

import hashlib

from .schema import COMPILER_VERSION


def derived_key(layer: str, cx: float, cz: float, area: float) -> str:
    payload = f"{layer}|{round(cx, 2)}|{round(cz, 2)}|{round(area, 1)}"
    return "d:" + hashlib.sha1(payload.encode("ascii")).hexdigest()[:16]


def order_buildings(features: list) -> list:
    """Deterministically order building Features; returns the sorted list.

    Sort key quantizes centroids to 0.1 m so tiny float jitter between
    releases cannot flip adjacent buildings, with stable_key as the final
    tiebreak.
    """
    def key(f):
        cx, cz = f.properties["_centroid"]
        return (round(cz * 10), round(cx * 10), f.stable_key)

    return sorted(features, key=key)


def identity_table(city: str, release: str, seed: int, ordered) -> dict:
    rows = []
    for bid, f in enumerate(ordered):
        cx, cz = f.properties["_centroid"]
        rows.append({
            "id": bid,
            "key": f.stable_key,
            "source_id": f.source_id,
            "centroid": [round(cx, 2), round(cz, 2)],
            "area": round(f.properties.get("_area", 0.0), 1),
        })
    return {
        "version": 1,
        "city": city,
        "source_release": release,
        "compiler_version": COMPILER_VERSION,
        "seed": seed,
        "buildings": rows,
    }

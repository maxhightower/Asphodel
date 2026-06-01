"""Assemble and write the city bundle (meta / zones / roads / timeline JSON).

Writes are deterministic: keys sorted, floats rounded, so identical inputs
produce byte-identical files (the spec's reproducibility guarantee).
"""
from __future__ import annotations

import json
import os


def build_timeline(belief_history, field: str = "belief", ndigits: int = 5) -> dict:
    """Turn a (n_ticks+1, Z) belief array into the timeline payload."""
    rows, cols = belief_history.shape
    data = [[round(float(v), ndigits) for v in row] for row in belief_history]
    return {"field": field, "shape": [rows, cols], "data": data}


def _write_json(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def write_bundle(out_dir: str, meta: dict, zones: list, roads: dict, timeline: dict) -> None:
    """Write the four bundle files into `out_dir` (created if absent)."""
    os.makedirs(out_dir, exist_ok=True)
    _write_json(os.path.join(out_dir, "meta.json"), meta)
    _write_json(os.path.join(out_dir, "zones.json"), zones)
    _write_json(os.path.join(out_dir, "roads.json"), roads)
    _write_json(os.path.join(out_dir, "timeline.json"), timeline)

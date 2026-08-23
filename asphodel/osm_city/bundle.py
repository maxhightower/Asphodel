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
        # allow_nan=False turns any non-finite leak into a loud ValueError here
        # rather than emitting bare NaN/Infinity tokens that are invalid JSON and
        # would make Godot's parser reject the bundle silently.
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def write_bundle(out_dir: str, meta: dict, zones: list, roads: dict, timeline: dict,
                 buildings: list | None = None) -> None:
    """Write the bundle files into `out_dir` (created if absent).

    `buildings` (real OSM footprints in local meters) is optional so older
    callers/tests keep working; when given it becomes buildings.json.
    """
    os.makedirs(out_dir, exist_ok=True)
    _write_json(os.path.join(out_dir, "meta.json"), meta)
    _write_json(os.path.join(out_dir, "zones.json"), zones)
    _write_json(os.path.join(out_dir, "roads.json"), roads)
    _write_json(os.path.join(out_dir, "timeline.json"), timeline)
    if buildings is not None:
        _write_json(os.path.join(out_dir, "buildings.json"), buildings)

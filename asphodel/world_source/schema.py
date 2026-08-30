"""WorldSourceV1 normalized representation and the compiled chunk schema.

WorldSourceV1 is the versioned intermediate between raw public data and the
exterior compiler: five external schemas normalize into this, and only this
feeds compilation (mission §7).  It implements exactly the fields Asphodel
needs — it is not a universal GIS engine.

The compiled chunk JSON schema (CHUNK_SCHEMA_VERSION) is the contract with
the Godot streaming renderer; `validate_chunk` is the single source of
truth for its shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WORLD_SOURCE_VERSION = 1
CHUNK_SCHEMA_VERSION = 1
COMPILER_VERSION = 1

OBSERVATION_CLASSES = ("OBSERVED", "DERIVED", "PROCEDURAL")
LICENSE_FAMILIES = (
    "PUBLIC_DOMAIN", "CC0", "PERMISSIVE", "ODBL", "RESTRICTED", "UNKNOWN",
)

ANCHOR_KINDS = (
    "BUILDING_ENTRANCE",
    "PEDESTRIAN_APPROACH",
    "SIDEWALK_ANCHOR",
    "DRIVEWAY_ANCHOR",
    "PARKING_ANCHOR",
    "ROAD_ANCHOR",
    "INTERIOR_ANCHOR",
)

ROOF_KINDS = ("flat", "pitched")

# Building feature tags compiled per building (position-free flags; anything
# position-bearing is compiled as a prop/anchor instead).
BUILDING_FEATURES = (
    "garage", "porch", "storefront", "sign_band", "loading_dock",
    "rooftop_hvac", "balconies", "lobby", "parapet",
)


@dataclass
class Feature:
    """One normalized geographic feature in the bundle's metre frame.

    geometry: for polygons a list of rings (first exterior, rest holes),
    each ring a list of (x, z); for lines a single list of (x, z); for
    points a single (x, z) pair wrapped in a list-of-one.
    """

    stable_key: str
    geometry: list
    geom_type: str  # "polygon" | "line" | "point"
    properties: dict
    source: str  # e.g. "overture/buildings/building@2026-08-19.0"
    source_id: str | None
    observation_class: str = "OBSERVED"
    confidence: float = 1.0
    license_family: str = "ODBL"


@dataclass
class WorldSourceV1:
    meta: dict = field(default_factory=dict)
    roads: list = field(default_factory=list)
    connectors: list = field(default_factory=list)
    buildings: list = field(default_factory=list)
    building_parts: list = field(default_factory=list)
    water: list = field(default_factory=list)
    land: list = field(default_factory=list)
    land_use: list = field(default_factory=list)
    land_cover: list = field(default_factory=list)
    infrastructure: list = field(default_factory=list)
    places: list = field(default_factory=list)

    def layer(self, name: str) -> list:
        return getattr(self, name)


# --------------------------------------------------------------------------
# Compiled chunk JSON contract (consumed by godot/scripts/exterior_world.gd)
# --------------------------------------------------------------------------
#
# chunks/c_<cx>_<cz>.json:
# {
#   "v": 1, "cx": int, "cz": int, "origin": [x, z],
#   "surface": [type, count, ...],           # 128x128 row-major RLE, 2 m cells
#   "roads": [ {"pts": [[x,z],...], "class": str, "carriage_w": m,
#               "lanes": int, "sidewalk_w": m, "verge_w": m,
#               "curb": bool, "markings": str, "elevated": bool} ],
#   "parcels": [ {"id": str, "poly": [[x,z],...], "arch": str, "obs": str} ],
#   "buildings": [ {"bid": int, "poly": [[x,z],...], "h": m, "floors": int,
#                   "arch": str, "roof": str,
#                   "entrance": {"edge": int, "t": 0..1, "w": m},
#                   "feat": [str,...]} ],
#   "props":    [[kind, x, z, rot_deg, variant], ...],
#   "vehicles": [[kind, x, z, rot_deg, variant], ...],
#   "trees":    [[kind, x, z, rot_deg, variant], ...],   # bushes included
#   "anchors":  [[kind, x, z, bid_or_-1], ...]
# }

_PLACEMENT_LISTS = ("props", "vehicles", "trees")


def validate_chunk(chunk: dict, expect_cells: int) -> list[str]:
    """Return a list of problems (empty == valid)."""
    from .chunkgrid import rle_decode
    from .grammar_tables import (
        BUILDING_ARCHETYPES,
        BUSH_KINDS,
        PARCEL_ARCHETYPES,
        PROP_KINDS,
        SURFACE_TYPES,
        TREE_KINDS,
        VEHICLE_KINDS,
    )

    errs: list[str] = []
    if chunk.get("v") != CHUNK_SCHEMA_VERSION:
        errs.append("bad chunk schema version")
    for key in ("cx", "cz", "origin", "surface", "roads", "parcels",
                "buildings", "props", "vehicles", "trees", "anchors"):
        if key not in chunk:
            errs.append(f"missing key {key}")
    if errs:
        return errs

    try:
        cells = rle_decode(chunk["surface"], expect_cells)
    except ValueError as e:
        errs.append(str(e))
        cells = b""
    n_types = len(SURFACE_TYPES)
    for b in set(cells):
        if b >= n_types:
            errs.append(f"surface type byte {b} outside enum")

    for r in chunk["roads"]:
        if len(r.get("pts", [])) < 2:
            errs.append("road with <2 points")
        if r.get("carriage_w", 0) <= 0 and not r.get("path_only"):
            errs.append(f"road {r.get('class')} without carriageway width")
    for p in chunk["parcels"]:
        if p.get("arch") not in PARCEL_ARCHETYPES:
            errs.append(f"parcel archetype {p.get('arch')!r} invalid")
        if len(p.get("poly", [])) < 3:
            errs.append("parcel with <3 vertices")
    for b in chunk["buildings"]:
        if b.get("arch") not in BUILDING_ARCHETYPES:
            errs.append(f"building archetype {b.get('arch')!r} invalid")
        if b.get("roof") not in ROOF_KINDS:
            errs.append(f"roof kind {b.get('roof')!r} invalid")
        if not isinstance(b.get("bid"), int):
            errs.append("building without integer bid")
        ent = b.get("entrance") or {}
        if not (0.0 <= ent.get("t", -1) <= 1.0):
            errs.append("entrance t outside [0,1]")

    valid_kinds = {
        "props": set(PROP_KINDS),
        "vehicles": set(VEHICLE_KINDS),
        "trees": set(TREE_KINDS) | set(BUSH_KINDS),
    }
    for lst in _PLACEMENT_LISTS:
        for row in chunk[lst]:
            if len(row) != 5:
                errs.append(f"{lst} row wrong arity")
            elif row[0] not in valid_kinds[lst]:
                errs.append(f"{lst} kind {row[0]!r} invalid")
    for row in chunk["anchors"]:
        if len(row) != 4 or row[0] not in ANCHOR_KINDS:
            errs.append(f"bad anchor row {row!r}")
    return errs

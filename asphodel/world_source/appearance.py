"""Compile-time bridge: Overture building appearance -> BuildingAppearanceV1.

Package B (appearance truth). Reads the appearance-bearing source properties a
building feature carries and produces a BuildingAppearanceV1 whose values are
OBSERVED only where the source actually supplied them. Everything else is left
None with PROCEDURAL provenance for Package C (inference) to fill as DERIVED.

Never labels an inferred value OBSERVED. VIS-0 reality: for the cert cities
these observed fields are ~0% populated, so this mostly emits Nones today; it
exists to carry the rare real values (and generalize to richer future data)
correctly, and to normalize source material vocab onto our canonical families.
"""
from __future__ import annotations

import re

from ..city_visual.building_appearance import (
    BuildingAppearanceV1, FacadeAppearance, RoofAppearance, AppearanceValue,
    FACADE_MATERIALS, ROOF_MATERIALS, ROOF_SHAPES,
)
from ..city_visual.provenance import OBSERVED, DERIVED, PROCEDURAL

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Overture facade_material -> canonical facade family.
_FACADE_MAP = {
    "brick": "brick", "brick_block": "brick",
    "concrete": "concrete", "cement_block": "concrete", "cement": "concrete",
    "stone": "stone", "sandstone": "stone", "limestone": "stone", "granite": "stone",
    "stucco": "stucco", "plaster": "stucco",
    "metal": "metal_panel", "metal_panel": "metal_panel", "steel": "metal_panel",
    "wood": "wood", "timber": "wood",
    "glass": "glass_curtain", "glass_curtain": "glass_curtain",
    "vinyl": "siding", "vinyl_siding": "siding", "siding": "siding",
    "plastic": "siding",
}
# Overture roof_material -> canonical roof family.
_ROOF_MAP = {
    "shingle": "asphalt_shingle", "asphalt": "asphalt_shingle",
    "asphalt_shingle": "asphalt_shingle", "bitumen": "flat_membrane",
    "tar_paper": "flat_membrane", "tar": "flat_membrane", "gravel": "flat_membrane",
    "membrane": "flat_membrane", "eternit": "flat_membrane",
    "metal": "standing_seam_metal", "steel": "standing_seam_metal",
    "zinc": "standing_seam_metal", "copper": "standing_seam_metal",
    "tile": "tile", "roof_tiles": "tile", "clay": "tile", "slate": "tile",
    "concrete": "roof_generic",
}
# Overture roof_shape values that map onto our roof shapes (others -> None).
_ROOF_SHAPE_MAP = {
    "flat": "flat", "gabled": "gabled", "hipped": "hipped",
    "half_hipped": "hipped", "pyramidal": "pyramidal", "gambrel": "complex",
    "mansard": "complex", "saltbox": "gabled", "skillion": "flat",
    "round": "complex", "dome": "complex",
}


def _norm_hex(v):
    if isinstance(v, str) and _HEX_RE.match(v.strip()):
        return v.strip().lower()
    return None


def _norm_facade_material(v):
    if isinstance(v, str):
        return _FACADE_MAP.get(v.strip().lower())
    return None


def _norm_roof_material(v):
    if isinstance(v, str):
        return _ROOF_MAP.get(v.strip().lower())
    return None


def _norm_roof_shape(v):
    if isinstance(v, str):
        return _ROOF_SHAPE_MAP.get(v.strip().lower())
    return None


def build_appearance(bid: int, props: dict, derived_roof: str,
                     height_m, height_observed: bool) -> BuildingAppearanceV1:
    """Assemble a BuildingAppearanceV1 from a building's source properties.

    `derived_roof` is the flat/pitched value the grammar already computed, used
    as the DERIVED roof shape when the source gives no observed roof_shape.
    """
    props = props or {}

    fc = _norm_hex(props.get("facade_color"))
    fm = _norm_facade_material(props.get("facade_material"))
    rc = _norm_hex(props.get("roof_color"))
    rm = _norm_roof_material(props.get("roof_material"))
    obs_shape = _norm_roof_shape(props.get("roof_shape"))

    facade = FacadeAppearance(
        color=AppearanceValue(fc, OBSERVED if fc else PROCEDURAL),
        material=AppearanceValue(fm, OBSERVED if fm else PROCEDURAL),
    )
    # roof shape: observed source value wins; else the grammar's flat/pitched is
    # DERIVED (it came from archetype/height heuristics, not observation).
    if obs_shape:
        shape_val, shape_cls = obs_shape, OBSERVED
    else:
        shape_val, shape_cls = (derived_roof if derived_roof in ROOF_SHAPES
                                else "flat"), DERIVED
    roof = RoofAppearance(
        color=AppearanceValue(rc, OBSERVED if rc else PROCEDURAL),
        material=AppearanceValue(rm, OBSERVED if rm else PROCEDURAL),
        shape=AppearanceValue(shape_val, shape_cls),
    )
    hv = float(height_m) if isinstance(height_m, (int, float)) else None
    return BuildingAppearanceV1(
        bid=bid, facade=facade, roof=roof,
        height_m=AppearanceValue(hv, OBSERVED if height_observed else DERIVED),
        style_family=AppearanceValue(None, PROCEDURAL),
    )

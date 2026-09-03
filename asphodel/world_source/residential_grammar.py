"""Compile-time residential architecture grammar (the brain behind
ResidentialArchitectureV1).

This module is where *Python decides what a house is*. It runs after the
building footprints, parcels and blocks are compiled and BEFORE the generic
per-house presentation choices, so architecture is authoritative and the Godot
renderer only consumes it (never re-rolls porch/garage/style).

Pipeline for detached residential buildings (mission R14):

  footprint morphology  ->  neighbourhood cohort (per block, spatially
  correlated era wave)  ->  builder/plan families within the cohort  ->  each
  house selects a form (constrained by its observed footprint) and a style
  (drawn from its cohort/builder prior, constrained by era + form)  ->  roof,
  facade materials, porch, windows, foundation, parking, details  ->  a bounded
  renovation layer.

Determinism: every choice draws from a `DetRand` stream keyed on the world seed,
a stable feature/block key, and a purpose tag. No global RNG, no iteration-order
dependence, no reliance on Python's salted hash(). Cohorts are keyed on the
deterministic block id and the block centroid, so the same city always yields
the same architecture across fresh processes.

No city-name dispatch: regional priors come only from geographic position
(latitude/longitude) via `region_profile`, never from the bundle's city string.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..city_visual.provenance import OBSERVED, DERIVED, PROCEDURAL
from ..city_visual.residential_architecture import (
    ResidentialArchitectureV1, ArchValue, Foundation, Massing, RoofGrammar,
    FacadeComposition, PorchGrammar, WindowGrammar,
    FACADE_SUBTYPE_TO_FAMILY,
)
from .detrand import DetRand, hash64

# Production first-wave vocabulary (the reserved enum members are valid in the
# schema but this grammar does not emit them yet).
FORMS_PROD = (
    "FOLK_COTTAGE", "BUNGALOW", "FOURSQUARE", "VICTORIAN_IRREGULAR",
    "TUDOR_COTTAGE", "REVIVAL_TWO_STORY", "MINIMAL_TRADITIONAL",
    "LINEAR_RANCH", "L_RANCH", "U_RANCH", "SUBURBAN_TWO_STORY",
    "CONTEMPORARY_COMPACT",
)
STYLES_PROD = (
    "CRAFTSMAN", "FOLK_NATIONAL", "FOLK_VICTORIAN", "QUEEN_ANNE",
    "AMERICAN_FOURSQUARE", "COLONIAL_REVIVAL", "TUDOR_REVIVAL",
    "MINIMAL_TRADITIONAL", "TRADITIONAL_RANCH", "MID_CENTURY_MODERN",
    "TEXAS_NEO_TRADITIONAL", "SPANISH_ECLECTIC",
)

ERA_SEQUENCE = (
    "PRE_1900", "1900_1919", "1920_1939", "1940_1959",
    "1960_1979", "1980_1999", "2000_2014", "2015_PLUS",
)


# --------------------------------------------------------------------------
# R2 -- footprint morphology
# --------------------------------------------------------------------------
@dataclass
class Morphology:
    area: float
    perimeter: float
    aspect: float            # oriented bounding box long/short
    obb_long: float
    obb_short: float
    rectangularity: float    # area / obb.area  (1 == perfect rectangle)
    compactness: float       # Polsby-Popper 4*pi*A / P^2
    concavity: float         # 1 - area / convex_hull.area
    edge_count: int
    frontage: float          # street-facing width proxy (obb long)
    depth: float             # obb short
    winged: bool
    winged_strong: bool


def compute_morphology(poly) -> Morphology:
    """Pure geometric descriptors from a footprint polygon (shapely)."""
    area = float(poly.area)
    perimeter = float(poly.length)
    try:
        obb = poly.minimum_rotated_rectangle
        oc = list(obb.exterior.coords)
        e0 = math.hypot(oc[1][0] - oc[0][0], oc[1][1] - oc[0][1])
        e1 = math.hypot(oc[2][0] - oc[1][0], oc[2][1] - oc[1][1])
        obb_long = max(e0, e1)
        obb_short = max(1e-6, min(e0, e1))
        obb_area = max(1e-6, float(obb.area))
    except Exception:
        obb_long = obb_short = math.sqrt(max(area, 1.0))
        obb_area = area
    aspect = obb_long / obb_short
    rectangularity = min(1.0, area / obb_area)
    compactness = (4.0 * math.pi * area) / (perimeter * perimeter) if perimeter > 0 else 0.0
    try:
        hull_area = float(poly.convex_hull.area)
        concavity = max(0.0, 1.0 - area / max(hull_area, 1e-6))
    except Exception:
        concavity = 0.0
    try:
        edge_count = max(3, len(poly.exterior.coords) - 1)
    except Exception:
        edge_count = 4
    winged = rectangularity < 0.86 and concavity > 0.10
    winged_strong = rectangularity < 0.72 and concavity > 0.18
    return Morphology(
        area=area, perimeter=perimeter, aspect=aspect,
        obb_long=obb_long, obb_short=obb_short, rectangularity=rectangularity,
        compactness=compactness, concavity=concavity, edge_count=edge_count,
        frontage=obb_long, depth=obb_short, winged=winged,
        winged_strong=winged_strong,
    )


# form -> (floor_min, floor_max, predicate(morph)->bool). When observed floors
# are unknown the floor bounds do not constrain (only geometry does); when known
# they gate hard (a 1-storey footprint can never become a 2-storey Foursquare).
_FORM_RULES = {
    "FOLK_COTTAGE":         (1, 2, lambda m: m.aspect < 2.6 and m.area < 260),
    "BUNGALOW":             (1, 2, lambda m: m.aspect < 2.4 and m.area < 300),
    "FOURSQUARE":           (2, 3, lambda m: m.aspect < 1.5 and m.area >= 110),
    "VICTORIAN_IRREGULAR":  (1, 3, lambda m: (m.winged or m.aspect < 2.2) and m.area >= 110),
    "TUDOR_COTTAGE":        (1, 2, lambda m: m.aspect < 2.2 and m.area < 340),
    "REVIVAL_TWO_STORY":    (2, 3, lambda m: m.aspect < 2.2 and m.area >= 110),
    "MINIMAL_TRADITIONAL":  (1, 2, lambda m: m.aspect < 2.4 and m.area < 300),
    "LINEAR_RANCH":         (1, 1, lambda m: m.aspect >= 1.7 and m.area >= 120),
    "L_RANCH":              (1, 1, lambda m: (m.rectangularity < 0.86 or m.winged) and m.area >= 150),
    "U_RANCH":              (1, 1, lambda m: m.winged_strong and m.area >= 200),
    "SUBURBAN_TWO_STORY":   (2, 3, lambda m: m.area >= 150),
    "CONTEMPORARY_COMPACT": (1, 2, lambda m: m.aspect < 2.4 and m.area < 340),
}


def form_eligible(form: str, morph: Morphology, obs_floors) -> bool:
    fmin, fmax, pred = _FORM_RULES[form]
    if obs_floors is not None:
        if not (fmin <= int(obs_floors) <= fmax):
            return False
    return bool(pred(morph))


def eligible_forms(morph: Morphology, obs_floors) -> list:
    out = [f for f in FORMS_PROD if form_eligible(f, morph, obs_floors)]
    if out:
        return out
    # Guaranteed fallback: pick by story count so a house always has a form.
    if obs_floors is not None and int(obs_floors) >= 2:
        return ["SUBURBAN_TWO_STORY"]
    return ["MINIMAL_TRADITIONAL"]


# --------------------------------------------------------------------------
# R3 -- construction era
# --------------------------------------------------------------------------
def era_for_year(year) -> str | None:
    if not isinstance(year, (int, float)) or year <= 0:
        return None
    y = int(year)
    if y < 1900:
        return "PRE_1900"
    if y < 1920:
        return "1900_1919"
    if y < 1940:
        return "1920_1939"
    if y < 1960:
        return "1940_1959"
    if y < 1980:
        return "1960_1979"
    if y < 2000:
        return "1980_1999"
    if y < 2015:
        return "2000_2014"
    return "2015_PLUS"


# plausible styles per era, as (style, weight). Impossible combinations are
# simply absent (mission R3: no anachronistic soup).
ERA_STYLE_WEIGHTS = {
    "PRE_1900":  [("FOLK_NATIONAL", 3), ("FOLK_VICTORIAN", 3), ("QUEEN_ANNE", 2),
                  ("CRAFTSMAN", 1)],
    "1900_1919": [("CRAFTSMAN", 3), ("FOLK_NATIONAL", 3), ("FOLK_VICTORIAN", 2),
                  ("QUEEN_ANNE", 2), ("AMERICAN_FOURSQUARE", 2)],
    "1920_1939": [("CRAFTSMAN", 3), ("AMERICAN_FOURSQUARE", 3), ("COLONIAL_REVIVAL", 2),
                  ("TUDOR_REVIVAL", 2), ("SPANISH_ECLECTIC", 1), ("MINIMAL_TRADITIONAL", 1)],
    "1940_1959": [("MINIMAL_TRADITIONAL", 3), ("TRADITIONAL_RANCH", 2),
                  ("COLONIAL_REVIVAL", 1), ("TUDOR_REVIVAL", 1)],
    "1960_1979": [("TRADITIONAL_RANCH", 3), ("MID_CENTURY_MODERN", 3),
                  ("MINIMAL_TRADITIONAL", 1)],
    "1980_1999": [("TEXAS_NEO_TRADITIONAL", 3), ("TRADITIONAL_RANCH", 1),
                  ("COLONIAL_REVIVAL", 1)],
    "2000_2014": [("TEXAS_NEO_TRADITIONAL", 3), ("COLONIAL_REVIVAL", 1)],
    "2015_PLUS": [("TEXAS_NEO_TRADITIONAL", 3), ("MID_CENTURY_MODERN", 1)],
}
# broad fallback for UNKNOWN era.
_ALL_ERA_STYLES = [("TRADITIONAL_RANCH", 3), ("MINIMAL_TRADITIONAL", 2),
                   ("CRAFTSMAN", 2), ("TEXAS_NEO_TRADITIONAL", 2),
                   ("COLONIAL_REVIVAL", 1), ("FOLK_NATIONAL", 1)]


def styles_for_era(era: str) -> list:
    return ERA_STYLE_WEIGHTS.get(era, _ALL_ERA_STYLES)


# --------------------------------------------------------------------------
# R4b -- regional priors from geography (never city name)
# --------------------------------------------------------------------------
def region_profile(lat, lon) -> dict:
    """Geographic priors: multipliers on styles + a material lean, derived from
    latitude/longitude only. Returns a neutral profile when geography is
    unknown so the system works city-agnostically."""
    prof = {"style_mult": {}, "brick_bias": 1.0, "tag": "generic"}
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return prof
    # US Gulf Coast / Texas-ish band: heavy brick veneer, ranch + neo-traditional
    # + spanish influence. Bounds are climatic/geographic, not a city test.
    if 25.0 <= lat <= 33.5 and -106.0 <= lon <= -88.0:
        prof["tag"] = "gulf_south"
        prof["brick_bias"] = 1.6
        prof["style_mult"] = {
            "TRADITIONAL_RANCH": 1.5, "TEXAS_NEO_TRADITIONAL": 1.6,
            "SPANISH_ECLECTIC": 1.4, "CRAFTSMAN": 1.1, "MID_CENTURY_MODERN": 1.15,
            "TUDOR_REVIVAL": 0.8,
        }
    # US arid Southwest: stronger spanish/stucco.
    elif 31.0 <= lat <= 37.0 and -120.0 <= lon <= -106.0:
        prof["tag"] = "southwest"
        prof["brick_bias"] = 0.8
        prof["style_mult"] = {"SPANISH_ECLECTIC": 2.0, "MID_CENTURY_MODERN": 1.3,
                              "TRADITIONAL_RANCH": 1.2}
    # US Northeast / Midwest older band: more colonial/tudor/foursquare.
    elif lat >= 39.0 and -85.0 <= lon <= -70.0:
        prof["tag"] = "northeast_midwest"
        prof["style_mult"] = {"COLONIAL_REVIVAL": 1.5, "TUDOR_REVIVAL": 1.4,
                              "AMERICAN_FOURSQUARE": 1.4, "SPANISH_ECLECTIC": 0.4}
    return prof


# --------------------------------------------------------------------------
# R6 -- style grammar tables (the visual rules)
# --------------------------------------------------------------------------
# Each entry is data the selector reads. Weighted lists are (value, weight).
STYLE_GRAMMAR = {
    "CRAFTSMAN": dict(
        forms=("BUNGALOW", "FOURSQUARE"),
        story=("ONE", "ONE_HALF"), h_emph="MEDIUM", symmetry="ASYMMETRIC",
        roof=[("FRONT_GABLE", 3), ("SIDE_GABLE", 2), ("CROSS_GABLE", 2), ("HIP", 1)],
        pitch="LOW", eave="WIDE",
        foundation=[("RAISED_PIER_BEAM", 3), ("LOW_CRAWLSPACE", 2), ("SLAB_ON_GRADE", 1)],
        porch=[("FULL_WIDTH", 3), ("PARTIAL_FRONT", 2), ("PROJECTING_GABLE", 2), ("RECESSED", 1)],
        supports=[("TAPERED_POST_BRICK_PIER", 3), ("TAPERED_POST", 2), ("PAIRED_POST", 1)],
        windows=("CRAFTSMAN_GROUPED", False),
        parking=[("SIDE_DRIVE", 3), ("ATTACHED_SIDE", 1)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_shingle",
                 foundation="red_brick", accent="none", trim="CRAFTSMAN_WOOD"),
            dict(front="fiber_cement_lap", side_rear="fiber_cement_lap", gable="wood_shingle",
                 foundation="red_brick", accent="stone_veneer", trim="CRAFTSMAN_WOOD"),
            dict(front="red_brick", side_rear="wood_lap", gable="wood_shingle",
                 foundation="red_brick", accent="none", trim="CRAFTSMAN_WOOD"),
        ],
        roof_mat="asphalt_shingle",
        details=["exposed_rafter_tails", "knee_brackets", "gable_vent"],
        maybe_details=[("chimney_modest", 0.4)],
    ),
    "FOLK_NATIONAL": dict(
        forms=("FOLK_COTTAGE", "BUNGALOW"),
        story=("ONE", "ONE_HALF"), h_emph="MEDIUM", symmetry="NEAR_SYMMETRIC",
        roof=[("FRONT_GABLE", 2), ("SIDE_GABLE", 2)],
        pitch="MEDIUM", eave="NORMAL",
        foundation=[("LOW_CRAWLSPACE", 3), ("RAISED_PIER_BEAM", 2), ("SLAB_ON_GRADE", 1)],
        porch=[("PARTIAL_FRONT", 2), ("FULL_WIDTH", 2), ("STOOP", 1)],
        supports=[("SIMPLE_POST", 3)],
        windows=("SIMPLE_VERTICAL", False),
        parking=[("SIDE_DRIVE", 3)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_lap",
                 foundation="smooth_stucco", accent="none", trim="NONE"),
            dict(front="board_and_batten", side_rear="board_and_batten", gable="board_and_batten",
                 foundation="smooth_stucco", accent="none", trim="NONE"),
        ],
        roof_mat="asphalt_shingle",
        details=["gable_vent"], maybe_details=[],
    ),
    "FOLK_VICTORIAN": dict(
        forms=("FOLK_COTTAGE", "VICTORIAN_IRREGULAR"),
        story=("ONE", "ONE_HALF"), h_emph="MEDIUM", symmetry="ASYMMETRIC",
        roof=[("FRONT_GABLE", 2), ("CROSS_GABLE", 2)],
        pitch="MEDIUM", eave="NORMAL",
        foundation=[("RAISED_PIER_BEAM", 3), ("LOW_CRAWLSPACE", 2)],
        porch=[("FULL_WIDTH", 2), ("PARTIAL_FRONT", 2)],
        supports=[("SIMPLE_POST", 2), ("PAIRED_POST", 1)],
        windows=("VICTORIAN_ASYMMETRIC", False),
        parking=[("SIDE_DRIVE", 3)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="VICTORIAN_GINGERBREAD"),
        ],
        roof_mat="asphalt_shingle",
        details=["gable_decoration", "porch_rail"], maybe_details=[("chimney_modest", 0.3)],
    ),
    "QUEEN_ANNE": dict(
        forms=("VICTORIAN_IRREGULAR", "FOURSQUARE"),
        story=("TWO", "ONE_HALF"), h_emph="LOW", symmetry="ASYMMETRIC",
        roof=[("CROSS_GABLE", 3), ("COMPLEX_HIP_GABLE", 2), ("HIP", 1)],
        pitch="STEEP", eave="NORMAL",
        foundation=[("RAISED_PIER_BEAM", 3), ("LOW_CRAWLSPACE", 2)],
        porch=[("WRAP_PARTIAL", 2), ("FULL_WIDTH", 2), ("PARTIAL_FRONT", 1)],
        supports=[("SIMPLE_POST", 2), ("PAIRED_POST", 1)],
        windows=("VICTORIAN_ASYMMETRIC", False),
        parking=[("SIDE_DRIVE", 3)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_shingle",
                 foundation="red_brick", accent="none", trim="VICTORIAN_GINGERBREAD"),
            dict(front="painted_brick", side_rear="wood_lap", gable="wood_shingle",
                 foundation="red_brick", accent="none", trim="VICTORIAN_GINGERBREAD"),
        ],
        roof_mat="asphalt_shingle",
        details=["gable_decoration", "bay_projection"], maybe_details=[("chimney_prominent", 0.5)],
    ),
    "AMERICAN_FOURSQUARE": dict(
        forms=("FOURSQUARE",),
        story=("TWO",), h_emph="LOW", symmetry="NEAR_SYMMETRIC",
        roof=[("HIP", 3), ("LOW_HIP", 1)],
        pitch="MEDIUM", eave="WIDE",
        foundation=[("LOW_CRAWLSPACE", 2), ("RAISED_PIER_BEAM", 2), ("SLAB_ON_GRADE", 1)],
        porch=[("FULL_WIDTH", 3), ("PARTIAL_FRONT", 1)],
        supports=[("CLASSICAL_SIMPLE", 2), ("PAIRED_POST", 2), ("TAPERED_POST_BRICK_PIER", 1)],
        windows=("FOURSQUARE_REGULAR", True),
        parking=[("SIDE_DRIVE", 3), ("ATTACHED_SIDE", 1)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="CLASSICAL_WHITE"),
            dict(front="red_brick", side_rear="red_brick", gable="red_brick",
                 foundation="red_brick", accent="none", trim="CLASSICAL_WHITE"),
        ],
        roof_mat="asphalt_shingle",
        details=["dormer_front", "wide_overhang"], maybe_details=[("chimney_modest", 0.4)],
    ),
    "COLONIAL_REVIVAL": dict(
        forms=("REVIVAL_TWO_STORY", "FOURSQUARE"),
        story=("TWO",), h_emph="LOW", symmetry="SYMMETRIC",
        roof=[("SIDE_GABLE", 3), ("HIP", 2)],
        pitch="MEDIUM", eave="NORMAL",
        foundation=[("LOW_CRAWLSPACE", 2), ("SLAB_ON_GRADE", 2)],
        porch=[("STOOP", 2), ("PARTIAL_FRONT", 1), ("RECESSED", 1)],
        supports=[("CLASSICAL_SIMPLE", 3)],
        windows=("COLONIAL_SYMMETRIC", True),
        parking=[("SIDE_DRIVE", 2), ("ATTACHED_SIDE", 1), ("ATTACHED_FRONT_ONE", 1)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="CLASSICAL_WHITE"),
            dict(front="red_brick", side_rear="red_brick", gable="red_brick",
                 foundation="red_brick", accent="none", trim="CLASSICAL_WHITE"),
            dict(front="painted_brick", side_rear="painted_brick", gable="painted_brick",
                 foundation="painted_brick", accent="none", trim="CLASSICAL_WHITE"),
        ],
        roof_mat="asphalt_shingle",
        details=["columns", "shutters"], maybe_details=[("chimney_modest", 0.4)],
    ),
    "TUDOR_REVIVAL": dict(
        forms=("TUDOR_COTTAGE", "REVIVAL_TWO_STORY"),
        story=("ONE_HALF", "TWO"), h_emph="LOW", symmetry="ASYMMETRIC",
        roof=[("CROSS_GABLE", 3), ("FRONT_GABLE", 2)],
        pitch="STEEP", eave="TIGHT",
        foundation=[("LOW_CRAWLSPACE", 2), ("SLAB_ON_GRADE", 2)],
        porch=[("RECESSED", 2), ("STOOP", 2)],
        supports=[("NONE", 2), ("SIMPLE_POST", 1)],
        windows=("TUDOR_GROUPED_VERTICAL", False),
        parking=[("SIDE_DRIVE", 2), ("ATTACHED_SIDE", 1), ("ATTACHED_FRONT_ONE", 1)],
        packages=[
            dict(front="red_brick", side_rear="red_brick", gable="smooth_stucco",
                 foundation="stone_veneer", accent="stone_veneer", trim="TUDOR_HALF_TIMBER"),
            dict(front="dark_brick", side_rear="dark_brick", gable="smooth_stucco",
                 foundation="stone_veneer", accent="stone_veneer", trim="TUDOR_HALF_TIMBER"),
        ],
        roof_mat="asphalt_shingle",
        details=["half_timber_gable", "chimney_prominent", "arched_entry"], maybe_details=[],
    ),
    "MINIMAL_TRADITIONAL": dict(
        forms=("MINIMAL_TRADITIONAL", "FOLK_COTTAGE"),
        story=("ONE",), h_emph="MEDIUM", symmetry="NEAR_SYMMETRIC",
        roof=[("SIDE_GABLE", 2), ("CROSS_GABLE", 2)],
        pitch="MEDIUM", eave="TIGHT",
        foundation=[("SLAB_ON_GRADE", 2), ("LOW_CRAWLSPACE", 2)],
        porch=[("STOOP", 3), ("PARTIAL_FRONT", 1)],
        supports=[("SIMPLE_POST", 2)],
        windows=("SUBURBAN_REGULAR", False),
        parking=[("SIDE_DRIVE", 2), ("ATTACHED_SIDE", 1), ("ATTACHED_FRONT_ONE", 1)],
        packages=[
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="SUBURBAN_TRIM"),
            dict(front="red_brick", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="SUBURBAN_TRIM"),
            dict(front="buff_brick", side_rear="buff_brick", gable="buff_brick",
                 foundation="buff_brick", accent="none", trim="SUBURBAN_TRIM"),
        ],
        roof_mat="asphalt_shingle",
        details=["shutters"], maybe_details=[("chimney_modest", 0.3)],
    ),
    "TRADITIONAL_RANCH": dict(
        forms=("LINEAR_RANCH", "L_RANCH", "U_RANCH"),
        story=("ONE",), h_emph="HIGH", symmetry="ASYMMETRIC",
        roof=[("LOW_HIP", 3), ("HIP", 2), ("LOW_GABLE", 2), ("SIDE_GABLE", 2), ("CROSS_HIP", 1)],
        pitch="LOW", eave="WIDE",
        foundation=[("SLAB_ON_GRADE", 4), ("LOW_CRAWLSPACE", 1)],
        porch=[("PARTIAL_FRONT", 2), ("RECESSED", 2), ("STOOP", 1)],
        supports=[("SIMPLE_POST", 2), ("MCM_THIN", 1)],
        windows=("RANCH_PICTURE", False),
        parking=[("ATTACHED_FRONT_TWO", 2), ("ATTACHED_FRONT_ONE", 2), ("ATTACHED_SIDE", 2),
                 ("CARPORT", 1), ("SIDE_DRIVE", 1)],
        packages=[
            dict(front="red_brick", side_rear="red_brick", gable="red_brick",
                 foundation="red_brick", accent="none", trim="RANCH_MINIMAL"),
            dict(front="buff_brick", side_rear="buff_brick", gable="buff_brick",
                 foundation="buff_brick", accent="stone_veneer", trim="RANCH_MINIMAL"),
            dict(front="red_brick", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="RANCH_MINIMAL"),
            dict(front="wood_lap", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="none", trim="RANCH_MINIMAL"),
        ],
        roof_mat="asphalt_shingle",
        details=["picture_window", "wide_overhang"], maybe_details=[("chimney_modest", 0.4)],
    ),
    "MID_CENTURY_MODERN": dict(
        forms=("LINEAR_RANCH", "L_RANCH", "CONTEMPORARY_COMPACT"),
        story=("ONE",), h_emph="HIGH", symmetry="ASYMMETRIC",
        roof=[("LOW_GABLE", 3), ("LOW_HIP", 2), ("SHED_COMPOSITE", 2), ("FLAT", 1)],
        pitch="VERY_LOW", eave="WIDE",
        foundation=[("SLAB_ON_GRADE", 4)],
        porch=[("RECESSED", 3), ("STOOP", 1)],
        supports=[("MCM_THIN", 2), ("MCM_SLANTED", 2)],
        windows=("MCM_HORIZONTAL", False),
        parking=[("CARPORT", 3), ("ATTACHED_FRONT_TWO", 1), ("INTEGRATED_ONE", 1)],
        packages=[
            dict(front="red_brick", side_rear="wood_lap", gable="wood_lap",
                 foundation="red_brick", accent="stone_veneer", trim="MCM_PLANK"),
            dict(front="buff_brick", side_rear="wood_lap", gable="wood_lap",
                 foundation="buff_brick", accent="stone_veneer", trim="MCM_PLANK"),
            dict(front="wood_lap", side_rear="wood_lap", gable="smooth_stucco",
                 foundation="smooth_stucco", accent="stone_veneer", trim="MCM_PLANK"),
        ],
        roof_mat="standing_seam_metal",
        details=["clerestory_strip", "picture_window", "wide_overhang"], maybe_details=[],
    ),
    "TEXAS_NEO_TRADITIONAL": dict(
        forms=("SUBURBAN_TWO_STORY", "REVIVAL_TWO_STORY"),
        story=("TWO", "ONE_HALF"), h_emph="LOW", symmetry="NEAR_SYMMETRIC",
        roof=[("CROSS_GABLE", 3), ("COMPLEX_HIP_GABLE", 2), ("HIP", 2)],
        pitch="MEDIUM", eave="NORMAL",
        foundation=[("SLAB_ON_GRADE", 4)],
        porch=[("RECESSED", 2), ("STOOP", 2), ("PARTIAL_FRONT", 1)],
        supports=[("CLASSICAL_SIMPLE", 2), ("SIMPLE_POST", 1)],
        windows=("SUBURBAN_REGULAR", False),
        parking=[("ATTACHED_FRONT_TWO", 3), ("INTEGRATED_TWO", 1), ("ATTACHED_FRONT_ONE", 1)],
        packages=[
            dict(front="red_brick", side_rear="fiber_cement_lap", gable="fiber_cement_lap",
                 foundation="red_brick", accent="stone_veneer", trim="SUBURBAN_TRIM"),
            dict(front="buff_brick", side_rear="fiber_cement_lap", gable="buff_brick",
                 foundation="buff_brick", accent="stone_veneer", trim="SUBURBAN_TRIM"),
            dict(front="dark_brick", side_rear="fiber_cement_lap", gable="fiber_cement_lap",
                 foundation="dark_brick", accent="stone_veneer", trim="SUBURBAN_TRIM"),
        ],
        roof_mat="asphalt_shingle",
        details=["stone_accent_wall", "chimney_modest"], maybe_details=[("shutters", 0.4)],
    ),
    "SPANISH_ECLECTIC": dict(
        forms=("MINIMAL_TRADITIONAL", "REVIVAL_TWO_STORY", "LINEAR_RANCH"),
        story=("ONE", "TWO"), h_emph="MEDIUM", symmetry="ASYMMETRIC",
        roof=[("LOW_HIP", 3), ("LOW_GABLE", 2)],
        pitch="LOW", eave="TIGHT",
        foundation=[("SLAB_ON_GRADE", 3)],
        porch=[("RECESSED", 2), ("STOOP", 2)],
        supports=[("NONE", 2), ("SIMPLE_POST", 1)],
        windows=("SIMPLE_VERTICAL", False),
        parking=[("ATTACHED_SIDE", 2), ("SIDE_DRIVE", 1), ("ATTACHED_FRONT_ONE", 1)],
        packages=[
            dict(front="smooth_stucco", side_rear="smooth_stucco", gable="smooth_stucco",
                 foundation="smooth_stucco", accent="stone_veneer", trim="STUCCO_SIMPLE"),
        ],
        roof_mat="tile",
        details=["arched_entry", "tile_roof_ridge", "wrought_iron"], maybe_details=[],
    ),
}

# roof shape (observed/derived from appearance) -> architecture roof family, used
# when a source roof_shape overrides the style's roof grammar.
_OBSROOF_TO_FAMILY = {
    "flat": "FLAT", "gabled": "SIDE_GABLE", "hipped": "HIP",
    "pyramidal": "HIP", "complex": "COMPLEX_HIP_GABLE", "pitched": "SIDE_GABLE",
}
_FOUNDATION_HEIGHT = {
    "RAISED_PIER_BEAM": 0.80, "LOW_CRAWLSPACE": 0.42, "SLAB_ON_GRADE": 0.12,
}


def _det_choice(rng: DetRand, weighted):
    """Weighted pick with a fresh DetRand draw (keeps stream position stable)."""
    return rng.weighted_choice(weighted)


# --------------------------------------------------------------------------
# R4 -- neighbourhood cohort
# --------------------------------------------------------------------------
@dataclass
class Cohort:
    cohort_id: int
    dominant_era: str
    secondary_era: str
    primary_forms: tuple
    primary_styles: list          # [(style, weight)]
    secondary_styles: list
    builder_families: list        # [dict]
    infill_probability: float
    renovation_pressure: float


def _era_field(cx: float, cz: float, seed: int) -> str:
    """Spatially-coherent development-wave era. A coarse value-noise field over
    the block centroid maps to an era band, so adjacent blocks share an era and
    the city reads as neighbourhoods of different ages rather than per-block
    noise."""
    cell = 520.0
    gx, gz = cx / cell, cz / cell
    ix, iz = math.floor(gx), math.floor(gz)
    fx, fz = gx - ix, gz - iz
    fx = fx * fx * (3 - 2 * fx)
    fz = fz * fz * (3 - 2 * fz)

    def corner(a, b):
        return (hash64(seed, "era_wave", a, b) % 100000) / 100000.0

    c00 = corner(ix, iz); c10 = corner(ix + 1, iz)
    c01 = corner(ix, iz + 1); c11 = corner(ix + 1, iz + 1)
    v = (c00 * (1 - fx) + c10 * fx) * (1 - fz) + (c01 * (1 - fx) + c11 * fx) * fz
    idx = min(len(ERA_SEQUENCE) - 1, int(v * len(ERA_SEQUENCE)))
    return ERA_SEQUENCE[idx]


def _neighbor_era(era: str, rng: DetRand) -> str:
    i = ERA_SEQUENCE.index(era)
    step = rng.choice((-1, 1))
    return ERA_SEQUENCE[min(len(ERA_SEQUENCE) - 1, max(0, i + step))]


def _apply_region(styles, region: dict):
    mult = region.get("style_mult", {})
    return [(s, max(0.1, w * mult.get(s, 1.0))) for s, w in styles]


def build_cohort(seed: int, cohort_id: int, cx: float, cz: float,
                 region: dict) -> Cohort:
    rng = DetRand(seed, "res_cohort", cohort_id)
    dominant_era = _era_field(cx, cz, seed)
    secondary_era = _neighbor_era(dominant_era, DetRand(seed, "res_cohort2", cohort_id))

    prim = _apply_region(styles_for_era(dominant_era), region)
    sec = _apply_region(styles_for_era(secondary_era), region)
    primary_forms = tuple(sorted({f for s, _ in prim
                                  for f in STYLE_GRAMMAR[s]["forms"]}))

    # Historic cohorts: many loose families (weaker repetition). Postwar/new tract
    # cohorts: few tight families (strong builder repetition).
    era_i = ERA_SEQUENCE.index(dominant_era)
    if era_i <= 2:            # pre-1940 historic
        fam_count = rng.randint(4, 5)
        infill = 0.14
        reno = 0.55
    elif era_i <= 4:         # 1940-1979 postwar
        fam_count = rng.randint(2, 3)
        infill = 0.08
        reno = 0.40
    else:                    # 1980+ newer subdivisions
        fam_count = rng.randint(2, 3)
        infill = 0.05
        reno = 0.20

    families = []
    for j in range(fam_count):
        frng = DetRand(seed, "builder", cohort_id, j)
        style = _det_choice(frng, prim)
        g = STYLE_GRAMMAR[style]
        form = _det_choice(frng, [(f, 1) for f in g["forms"]])
        fam = dict(
            id=j, style=style, form=form,
            story=frng.choice(g["story"]),
            roof_family=_det_choice(frng, g["roof"]),
            porch_family=_det_choice(frng, g["porch"]),
            porch_support=_det_choice(frng, g["supports"]),
            parking=_det_choice(frng, g["parking"]),
            foundation=_det_choice(frng, g["foundation"]),
            package_idx=frng.randint(0, len(g["packages"]) - 1),
            # relative share of houses that follow this family
            share=frng.uniform(0.7, 1.3),
        )
        families.append(fam)

    return Cohort(
        cohort_id=cohort_id, dominant_era=dominant_era, secondary_era=secondary_era,
        primary_forms=primary_forms, primary_styles=prim, secondary_styles=sec,
        builder_families=families, infill_probability=infill,
        renovation_pressure=reno,
    )


# --------------------------------------------------------------------------
# R14 -- per-house architecture selection
# --------------------------------------------------------------------------
@dataclass
class HouseInputs:
    bid: int
    key: str
    morph: Morphology
    obs_floors: object = None       # int or None
    obs_year: object = None         # int or None
    obs_roof_shape: object = None   # value from appearance roof.shape
    obs_roof_shape_class: str = PROCEDURAL
    obs_roof_material: object = None
    obs_facade_material: object = None   # canonical FACADE_MATERIALS family


def _story_profile(obs_floors, style_story) -> str:
    if obs_floors is not None:
        n = int(obs_floors)
        if n >= 2:
            return "TWO"
        # 1 storey: keep the style's half-storey flavour if it has one
        return "ONE_HALF" if "ONE_HALF" in style_story and "ONE" not in style_story else "ONE"
    return style_story[0]


def _subtype_for_family(family: str, rng: DetRand) -> str:
    """Pick a residential subtype whose shared shader family matches an observed
    facade material family, so observed material is honoured in the composition."""
    opts = [s for s, fam in FACADE_SUBTYPE_TO_FAMILY.items()
            if fam == family and s != "none"]
    if not opts:
        return None
    return opts[rng.randint(0, len(opts) - 1)]


def _pick_style_and_form(house_rng, era, morph, obs_floors, cohort, family):
    """Resolve (style, form) honouring: builder-family preference, era-plausible
    styles, and morphology-eligible forms. Returns (style, form, from_family)."""
    elig = eligible_forms(morph, obs_floors)
    elig_set = set(elig)

    # 1. Try the builder family's style if any of its forms fits this footprint.
    if family is not None:
        fam_forms = [f for f in STYLE_GRAMMAR[family["style"]]["forms"] if f in elig_set]
        if fam_forms:
            form = family["form"] if family["form"] in fam_forms else \
                fam_forms[house_rng.randint(0, len(fam_forms) - 1)]
            return family["style"], form, True

    # 2. Bounded break: choose an era-plausible style that has an eligible form,
    #    weighted by the cohort prior. This is what makes infill / odd lots differ
    #    from their block in a controlled way rather than randomly.
    era_styles = dict(styles_for_era(era))
    weighted = []
    for s, w in cohort.primary_styles:
        if s not in era_styles:
            continue
        if any(f in elig_set for f in STYLE_GRAMMAR[s]["forms"]):
            weighted.append((s, w * era_styles[s]))
    if not weighted:
        # widen to any era-plausible style with an eligible form
        for s, w in styles_for_era(era):
            if any(f in elig_set for f in STYLE_GRAMMAR[s]["forms"]):
                weighted.append((s, w))
    if not weighted:
        # last resort: any style compatible with the eligible forms
        for s in STYLES_PROD:
            if any(f in elig_set for f in STYLE_GRAMMAR[s]["forms"]):
                weighted.append((s, 1))
    style = house_rng.weighted_choice(weighted)
    fam_forms = [f for f in STYLE_GRAMMAR[style]["forms"] if f in elig_set]
    form = fam_forms[house_rng.randint(0, len(fam_forms) - 1)]
    return style, form, False


def build_architecture(inp: HouseInputs, cohort: Cohort,
                       seed: int) -> ResidentialArchitectureV1:
    """Compile one house's ResidentialArchitectureV1 from its footprint and its
    neighbourhood cohort. Pure + deterministic in (seed, key, cohort)."""
    house_rng = DetRand(seed, inp.key, "res_arch")
    g_default = STYLE_GRAMMAR

    # ---- era ----
    year_era = era_for_year(inp.obs_year)
    is_infill = False
    if year_era is not None:
        era_val, era_cls = year_era, DERIVED
    else:
        # infill breaks the cohort era in a bounded way (a later build on an old block)
        if house_rng.chance(cohort.infill_probability):
            is_infill = True
            i = ERA_SEQUENCE.index(cohort.dominant_era)
            era_val = ERA_SEQUENCE[min(len(ERA_SEQUENCE) - 1, i + house_rng.randint(1, 3))]
        else:
            era_val = house_rng.weighted_choice(
                [(cohort.dominant_era, 3), (cohort.secondary_era, 1)])
        era_cls = PROCEDURAL

    # ---- builder family assignment ----
    family = None
    if cohort.builder_families and not is_infill:
        fam_weights = [(f, f["share"]) for f in cohort.builder_families]
        family = house_rng.weighted_choice(fam_weights)

    # ---- form + style ----
    style, form, from_family = _pick_style_and_form(
        house_rng, era_val, inp.morph, inp.obs_floors, cohort, family)
    g = g_default[style]

    # ---- massing ----
    story = _story_profile(inp.obs_floors, g["story"])
    massing = Massing(story_profile=story, horizontal_emphasis=g["h_emph"],
                      symmetry=g["symmetry"])

    # ---- roof ----
    if inp.obs_roof_shape and inp.obs_roof_shape_class == OBSERVED:
        roof_family = _OBSROOF_TO_FAMILY.get(str(inp.obs_roof_shape).lower(),
                                             _det_choice(house_rng, g["roof"]))
        pitch = "VERY_LOW" if roof_family == "FLAT" else g["pitch"]
    else:
        roof_family = (family["roof_family"] if (family and from_family)
                       else _det_choice(house_rng, g["roof"]))
        pitch = g["pitch"]
    roof_mat = inp.obs_roof_material or g["roof_mat"]
    dormer = ("dormer_front" in g["details"]) and house_rng.chance(0.6)
    roof = RoofGrammar(family=roof_family, pitch=pitch, eave=g["eave"],
                       material=roof_mat, material_subtype=_roof_subtype(roof_mat),
                       dormer=dormer)

    # ---- facade composition (multi-material) ----
    pkg_idx = family["package_idx"] if (family and from_family) else \
        house_rng.randint(0, len(g["packages"]) - 1)
    pkg = dict(g["packages"][pkg_idx])
    # honour observed facade material family on the front region
    if inp.obs_facade_material:
        sub = _subtype_for_family(inp.obs_facade_material, house_rng)
        if sub:
            pkg["front"] = sub
    facade = FacadeComposition(front=pkg["front"], side_rear=pkg["side_rear"],
                               gable=pkg["gable"], foundation=pkg["foundation"],
                               accent=pkg["accent"], trim=pkg["trim"])

    # ---- foundation ----
    fam_found = family["foundation"] if (family and from_family) else \
        _det_choice(house_rng, g["foundation"])
    # postwar+ era pressure toward slab regardless of style default
    if ERA_SEQUENCE.index(era_val) >= 4 and house_rng.chance(0.5):
        fam_found = "SLAB_ON_GRADE"
    foundation = Foundation(family=fam_found,
                            height_m=_FOUNDATION_HEIGHT[fam_found]
                            + house_rng.uniform(-0.03, 0.05))

    # ---- porch ----
    porch_family = family["porch_family"] if (family and from_family) else \
        _det_choice(house_rng, g["porch"])
    porch_support = family["porch_support"] if (family and from_family) else \
        _det_choice(house_rng, g["supports"])
    porch = _porch_geometry(porch_family, porch_support, house_rng)

    # ---- windows ----
    win_family, win_sym = g["windows"]
    windows = WindowGrammar(family=win_family, symmetric=win_sym)

    # ---- parking ----
    parking = family["parking"] if (family and from_family) else \
        _det_choice(house_rng, g["parking"])
    # never invent a detached rear garage without observed accessory evidence
    if parking == "DETACHED_REAR_OBSERVED":
        parking = "SIDE_DRIVE"

    # ---- details ----
    details = list(g["details"])
    for tag, p in g.get("maybe_details", []):
        if house_rng.chance(p):
            details.append(tag)

    # ---- R13 renovation layer ----
    mods = _renovations(era_val, cohort.renovation_pressure, style, facade, house_rng)

    return ResidentialArchitectureV1(
        bid=inp.bid,
        era=ArchValue(era_val, era_cls),
        form=ArchValue(form, DERIVED),        # constrained by observed footprint
        style=ArchValue(style, PROCEDURAL),   # a neighbourhood prior, never observed
        cohort_id=cohort.cohort_id,
        builder_family_id=(family["id"] if (family and from_family) else -1),
        plan_variant=house_rng.randint(0, 2),
        mirrored=house_rng.chance(0.5),
        foundation=foundation, massing=massing, roof=roof, facade=facade,
        porch=porch, windows=windows, parking=parking,
        details=details, modifications=mods,
    )


def _roof_subtype(roof_mat: str) -> str:
    return {"asphalt_shingle": "asphalt_3tab", "standing_seam_metal": "standing_seam",
            "tile": "barrel_tile", "flat_membrane": "membrane",
            "roof_generic": "generic"}.get(roof_mat, "asphalt_3tab")


def _porch_geometry(family: str, support: str, rng: DetRand) -> PorchGrammar:
    if family == "NONE":
        return PorchGrammar("NONE", 0.0, 0.0, "NONE")
    depth = {"STOOP": 1.2, "PARTIAL_FRONT": 2.2, "FULL_WIDTH": 2.4,
             "PROJECTING_GABLE": 2.6, "RECESSED": 1.6, "WRAP_PARTIAL": 2.3}.get(family, 2.0)
    depth += rng.uniform(-0.2, 0.3)
    width = {"STOOP": 0.22, "PARTIAL_FRONT": 0.5, "FULL_WIDTH": 0.92,
             "PROJECTING_GABLE": 0.42, "RECESSED": 0.4, "WRAP_PARTIAL": 0.7}.get(family, 0.5)
    width = min(1.0, max(0.1, width + rng.uniform(-0.05, 0.05)))
    return PorchGrammar(family=family, depth_m=max(0.6, depth),
                        width_fraction=width, support=support)


def _renovations(era: str, pressure: float, style, facade, rng: DetRand) -> list:
    """Bounded, style-compatible later alterations. Original style is preserved;
    this only touches the *current exterior treatment* so old neighbourhoods read
    as coherent-but-lived-in rather than frozen at construction."""
    mods = []
    era_i = ERA_SEQUENCE.index(era) if era in ERA_SEQUENCE else 3
    # older houses under more renovation pressure change more.
    p = pressure * (1.0 + max(0, 4 - era_i) * 0.12)
    if rng.chance(min(0.6, p)):
        mods.append("REPAINTED")
    front_fam = FACADE_SUBTYPE_TO_FAMILY.get(facade.front, "siding")
    if front_fam == "brick" and rng.chance(min(0.3, p * 0.5)):
        mods.append("PAINTED_BRICK")
    if front_fam == "siding" and era_i <= 3 and rng.chance(min(0.35, p * 0.6)):
        mods.append("REPLACEMENT_SIDING")
    if era_i <= 3 and rng.chance(min(0.2, p * 0.4)):
        mods.append("METAL_ROOF_RETROFIT")
    if rng.chance(min(0.3, p * 0.5)):
        mods.append("REPLACEMENT_WINDOWS")
    return mods


# --------------------------------------------------------------------------
# Batch entry point (called from compile.py). Builds cohorts per block, then
# assigns a ResidentialArchitectureV1 to every DETACHED_RESIDENTIAL record and
# reconciles its BuildingAppearanceV1 facade/roof material so the two contracts
# agree (and the legacy renderer still shows era-appropriate materials).
# --------------------------------------------------------------------------
_PSEUDO_BLOCK_BASE = 1_000_000    # keeps homeless-house cohort ids off real ones
_YEAR_KEYS = ("year_built", "built_year", "construction_year", "start_date",
              "building_date", "year", "construction_date")


def _extract_year(props: dict):
    for k in _YEAR_KEYS:
        v = props.get(k) if props else None
        if isinstance(v, (int, float)) and 1600 < v < 2100:
            return int(v)
        if isinstance(v, str):
            m = "".join(ch for ch in v[:4] if ch.isdigit())
            if len(m) == 4 and 1600 < int(m) < 2100:
                return int(m)
    return None


def _pseudo_block(cx: float, cz: float) -> int:
    cell = 180.0
    ix, iz = math.floor(cx / cell), math.floor(cz / cell)
    return _PSEUDO_BLOCK_BASE + (hash64("pseudo_block", ix, iz) % 900_000)


def _obs_inputs(rec, props):
    """Pull the observed constraints off a compiled BuildingRecord."""
    ap = rec.appearance or {}
    roof = ap.get("roof", {})
    shp = roof.get("shape", {})
    rmat = roof.get("material", {})
    fmat = ap.get("facade", {}).get("material", {})
    # observed floor count: use the record's floors when it derives from an
    # observed source (levels or height), so a short/1-storey observed house
    # cannot be promoted to a 2-storey form.
    floors_known = getattr(rec, "floors_observed", False) or rec.height_observed
    obs_floors = rec.floors if floors_known else None
    return HouseInputs(
        bid=rec.bid, key=rec.key, morph=compute_morphology(rec.poly),
        obs_floors=obs_floors,
        obs_year=_extract_year(props or {}),
        obs_roof_shape=shp.get("value"),
        obs_roof_shape_class=shp.get("class", PROCEDURAL),
        obs_roof_material=(rmat.get("value") if rmat.get("class") == OBSERVED else None),
        obs_facade_material=(fmat.get("value") if fmat.get("class") == OBSERVED else None),
    )


def assign_architecture(records, parcels, blocks, seed, lat=None, lon=None,
                        props_by_bid=None) -> dict:
    """Attach ResidentialArchitectureV1 to every detached-residential record.

    Runs BEFORE appearance colour inference so it can set the residential facade/
    roof material families that inference then colours. Returns a stats dict.
    """
    region = region_profile(lat, lon)
    props_by_bid = props_by_bid or {}

    bid_block = {}
    for p in parcels:
        for bid in getattr(p, "building_bids", []):
            bid_block[bid] = p.block_id

    block_centroid = {}
    for i, blk in enumerate(blocks):
        c = blk.centroid
        block_centroid[i] = (float(c.x), float(c.y))

    cohorts: dict[int, Cohort] = {}

    def cohort_for(block_id, cx, cz):
        if block_id not in cohorts:
            cohorts[block_id] = build_cohort(seed, block_id, cx, cz, region)
        return cohorts[block_id]

    count = 0
    for rec in records:
        if rec.arch != "DETACHED_RESIDENTIAL":
            continue
        c = rec.poly.centroid
        rcx, rcz = float(c.x), float(c.y)
        block_id = bid_block.get(rec.bid)
        if block_id is None:
            block_id = _pseudo_block(rcx, rcz)
            cx, cz = rcx, rcz
        else:
            cx, cz = block_centroid.get(block_id, (rcx, rcz))
        cohort = cohort_for(block_id, cx, cz)

        inp = _obs_inputs(rec, props_by_bid.get(rec.bid))
        arch = build_architecture(inp, cohort, seed)
        errs = arch.validate()
        if errs:
            raise ValueError(f"invalid architecture for bid {rec.bid}: {errs[:3]}")
        rec.architecture = arch.to_dict()
        _reconcile_appearance(rec, arch, region)
        _derive_feat_flags(rec, arch)
        count += 1

    return {
        "houses": count,
        "cohorts": len(cohorts),
        "builder_families": sum(len(c.builder_families) for c in cohorts.values()),
        "region_tag": region.get("tag", "generic"),
    }


_ATTACHED_PARKING = {
    "ATTACHED_FRONT_ONE", "ATTACHED_FRONT_TWO", "ATTACHED_SIDE",
    "INTEGRATED_ONE", "INTEGRATED_TWO", "CARPORT",
}


def _derive_feat_flags(rec, arch):
    """Derive the legacy `feat` garage/porch compatibility flags FROM the
    authoritative architecture record (single source of truth), so any consumer
    still reading `feat` agrees with the architecture instead of a second roll."""
    feat = [f for f in rec.feat if f not in ("garage", "porch")]
    if arch.parking in _ATTACHED_PARKING:
        feat.append("garage")
    if arch.porch.family != "NONE":
        feat.append("porch")
    rec.feat = feat


def _reconcile_appearance(rec, arch, region):
    """Keep BuildingAppearanceV1 consistent with the architecture: set the
    dominant facade/roof material family and a style_family label, but never
    overwrite OBSERVED values. Colours are still filled later by inference."""
    ap = rec.appearance
    if ap is None:
        return
    fmat = ap["facade"]["material"]
    if fmat.get("class") != OBSERVED:
        fmat["value"] = FACADE_SUBTYPE_TO_FAMILY.get(arch.facade.front, "siding")
        fmat["class"] = PROCEDURAL
    rmat = ap["roof"]["material"]
    if rmat.get("class") != OBSERVED and rmat.get("value") is None:
        rmat["value"] = arch.roof.material
        rmat["class"] = PROCEDURAL
    sf = ap.get("style_family")
    if sf is not None and sf.get("class") != OBSERVED:
        sf["value"] = f"{region.get('tag', 'regional')}_residential_{arch.style.value.lower()}"
        sf["class"] = DERIVED


def census(records) -> dict:
    """Distribution report over compiled residential architecture records."""
    from collections import Counter
    tallies = {k: Counter() for k in (
        "era", "form", "style", "foundation", "roof_family", "roof_material",
        "facade_front_family", "parking", "porch")}
    prov = Counter()
    n = 0
    for rec in records:
        a = getattr(rec, "architecture", None)
        if not a:
            continue
        n += 1
        tallies["era"][a["era"]["value"]] += 1
        tallies["form"][a["form"]["value"]] += 1
        tallies["style"][a["style"]["value"]] += 1
        tallies["foundation"][a["foundation"]["family"]] += 1
        tallies["roof_family"][a["roof"]["family"]] += 1
        tallies["roof_material"][a["roof"]["material"]] += 1
        tallies["facade_front_family"][
            FACADE_SUBTYPE_TO_FAMILY.get(a["facade"]["front"], "?")] += 1
        tallies["parking"][a["parking"]] += 1
        tallies["porch"][a["porch"]["family"]] += 1
        prov[a["era"]["class"]] += 1
    return {"houses": n,
            "distributions": {k: dict(v) for k, v in tallies.items()},
            "era_provenance": dict(prov)}


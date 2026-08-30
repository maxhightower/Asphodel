"""Classification and grammar tables for Asphodel's procedural exterior world.

This module is pure data plus tiny pure lookup functions: no I/O, no numpy,
no randomness. It defines the vocabulary and deterministic classification
rules that later procedural-generation passes (parcel detailing, road
building, prop scattering) consume as their single source of truth.

Everything here is meant to be imported and read, not executed as a script.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Parcel archetypes
# ---------------------------------------------------------------------------
# The land-use bucket assigned to a parcel (a lot / tax-parcel-like polygon)
# before any building has been placed on it.
PARCEL_ARCHETYPES = [
    "RESIDENTIAL",
    "MULTIFAMILY",
    "RETAIL",
    "OFFICE",
    "INDUSTRIAL",
    "CIVIC",
    "SCHOOL",
    "MEDICAL",
    "PARK",
    "VACANT_OPEN",
    "UNKNOWN",
]

# ---------------------------------------------------------------------------
# 2. Building archetypes
# ---------------------------------------------------------------------------
# The physical "kind of building" that gets placed on a footprint, distinct
# from the parcel's land-use archetype (a RETAIL parcel can host either a
# SMALL_COMMERCIAL or BIG_BOX_COMMERCIAL building, for example).
BUILDING_ARCHETYPES = [
    "DETACHED_RESIDENTIAL",
    "MULTIFAMILY",
    "SMALL_COMMERCIAL",
    "BIG_BOX_COMMERCIAL",
    "INDUSTRIAL",
    "OFFICE_HIGHRISE",
    "CIVIC_SPECIAL",
    "GENERIC_UNKNOWN",
]

# ---------------------------------------------------------------------------
# 3. Surface types
# ---------------------------------------------------------------------------
# The ground-cover classification used for rasterized/vector surface tiles
# across parcels, road right-of-way, and open space.
SURFACE_TYPES = [
    "ROAD",
    "SIDEWALK",
    "PARKING",
    "OTHER_IMPERVIOUS",
    "MAINTAINED_GRASS",
    "ROUGH_VEGETATION",
    "TREE_CANOPY",
    "BARE_GROUND",
    "WATER",
    "BUILDING",
]

_PARCEL_SET = set(PARCEL_ARCHETYPES)
_BUILDING_SET = set(BUILDING_ARCHETYPES)
_SURFACE_SET = set(SURFACE_TYPES)


# ---------------------------------------------------------------------------
# 4. land_use -> parcel archetype
# ---------------------------------------------------------------------------
# Keys are lower-cased Overture/OSM land_use class strings (or common
# synonyms across the two datasets). Values must be members of
# PARCEL_ARCHETYPES.
LANDUSE_TO_PARCEL = {
    # residential
    "residential": "RESIDENTIAL",
    "housing": "RESIDENTIAL",
    "residential_multifamily": "MULTIFAMILY",
    "apartments": "MULTIFAMILY",
    # commercial / retail
    "retail": "RETAIL",
    "commercial": "RETAIL",
    "shop": "RETAIL",
    # office
    "office": "OFFICE",
    # industrial
    "industrial": "INDUSTRIAL",
    "warehouse": "INDUSTRIAL",
    "construction": "INDUSTRIAL",
    "brownfield": "INDUSTRIAL",
    "quarry": "INDUSTRIAL",
    "railway": "INDUSTRIAL",
    # education
    "education": "SCHOOL",
    "school": "SCHOOL",
    "university": "SCHOOL",
    "college": "SCHOOL",
    "kindergarten": "SCHOOL",
    # medical
    "medical": "MEDICAL",
    "hospital": "MEDICAL",
    "healthcare": "MEDICAL",
    # park / open recreation
    "park": "PARK",
    "recreation": "PARK",
    "recreation_ground": "PARK",
    "grass": "PARK",
    "meadow": "PARK",
    "forest": "PARK",
    "nature_reserve": "PARK",
    "golf_course": "PARK",
    # vacant / low-structure open ground
    "farmland": "VACANT_OPEN",
    "farmyard": "VACANT_OPEN",
    "cemetery": "VACANT_OPEN",
    "landfill": "VACANT_OPEN",
    "greenfield": "VACANT_OPEN",
    "vacant": "VACANT_OPEN",
    "parking": "VACANT_OPEN",
    "garages": "VACANT_OPEN",
    # civic / institutional
    "civic": "CIVIC",
    "government": "CIVIC",
    "religious": "CIVIC",
    "place_of_worship": "CIVIC",
    "military": "CIVIC",
    "institutional": "CIVIC",
    "cemetery_civic": "CIVIC",
}


def parcel_archetype_for_landuse(cls: str) -> str:
    """Map a raw land_use class string to a PARCEL_ARCHETYPES value.

    Matching is case-insensitive and tolerant of surrounding whitespace.
    Falls back to "UNKNOWN" for anything not present in the table (including
    None/empty input), which is the deliberately conservative default so
    downstream generation degrades gracefully rather than guessing.
    """
    if not cls:
        return "UNKNOWN"
    key = cls.strip().lower()
    return LANDUSE_TO_PARCEL.get(key, "UNKNOWN")


# ---------------------------------------------------------------------------
# 5. place category -> parcel archetype hint
# ---------------------------------------------------------------------------
# Keys are lower-case substrings matched against an Overture "places"
# category string (e.g. "fast_food_restaurant" contains "restaurant" and
# "fast_food"). Values are PARCEL_ARCHETYPES hints -- these are *hints*
# layered on top of (and generally overriding, since a place is more
# specific than a land-use polygon) LANDUSE_TO_PARCEL results.
PLACE_CATEGORY_TO_PARCEL = {
    "school": "SCHOOL",
    "university": "SCHOOL",
    "college": "SCHOOL",
    "hospital": "MEDICAL",
    "clinic": "MEDICAL",
    "pharmacy": "MEDICAL",
    "dentist": "MEDICAL",
    "doctor": "MEDICAL",
    "grocery": "RETAIL",
    "supermarket": "RETAIL",
    "gas_station": "RETAIL",
    "fuel": "RETAIL",
    "restaurant": "RETAIL",
    "cafe": "RETAIL",
    "fast_food": "RETAIL",
    "hotel": "RETAIL",
    "bank": "RETAIL",
    "church": "CIVIC",
    "place_of_worship": "CIVIC",
    "office": "OFFICE",
    "factory": "INDUSTRIAL",
    "industrial": "INDUSTRIAL",
    "warehouse": "INDUSTRIAL",
    "park": "PARK",
}


def parcel_archetype_for_place(category: str) -> str | None:
    """Return a PARCEL_ARCHETYPES hint for an Overture place category string.

    Performs longest-keyword-first substring matching against
    PLACE_CATEGORY_TO_PARCEL so that a more specific keyword (e.g.
    "fast_food") wins over an accidental shorter overlap, and returns None
    when nothing matches (including for falsy input) so callers can tell
    "no opinion" apart from an explicit archetype.
    """
    if not category:
        return None
    key = category.strip().lower()
    for keyword in sorted(PLACE_CATEGORY_TO_PARCEL, key=len, reverse=True):
        if keyword in key:
            return PLACE_CATEGORY_TO_PARCEL[keyword]
    return None


# ---------------------------------------------------------------------------
# 6. building archetype selection
# ---------------------------------------------------------------------------
def building_archetype_for(
    parcel_archetype: str, footprint_area_m2: float, height_m: float
) -> str:
    """Deterministically choose a BUILDING_ARCHETYPES value.

    Rules (checked in this order):
      1. Any footprint with height_m >= 30 is treated as a highrise
         regardless of parcel use -- a tall structure reads as a highrise
         to an observer even if the underlying land use is unusual.
      2. RESIDENTIAL parcels: small footprints (< 350 m^2, i.e. roughly a
         single-family home footprint) become DETACHED_RESIDENTIAL; larger
         footprints on a nominally single-family parcel are treated as
         MULTIFAMILY (a duplex/small apartment building misclassified as
         residential land use).
      3. MULTIFAMILY parcels always produce MULTIFAMILY buildings.
      4. RETAIL parcels: footprints >= 2500 m^2 (big-box scale, e.g a
         supermarket or warehouse store) become BIG_BOX_COMMERCIAL,
         otherwise SMALL_COMMERCIAL (strip-mall / storefront scale).
      5. OFFICE parcels: height_m >= 25 (roughly 7+ stories) becomes
         OFFICE_HIGHRISE; lower buildings are treated as low-rise office,
         which shares its footprint/scattering grammar with
         SMALL_COMMERCIAL.
      6. INDUSTRIAL parcels always produce INDUSTRIAL buildings.
      7. CIVIC, SCHOOL, and MEDICAL parcels always produce CIVIC_SPECIAL
         buildings (these get bespoke/hand-authored-feeling treatment
         rather than the generic commercial grammar).
      8. PARK, VACANT_OPEN, UNKNOWN, and anything else fall through to
         GENERIC_UNKNOWN.
    """
    if height_m >= 30:
        return "OFFICE_HIGHRISE"

    if parcel_archetype == "RESIDENTIAL":
        return "DETACHED_RESIDENTIAL" if footprint_area_m2 < 350 else "MULTIFAMILY"

    if parcel_archetype == "MULTIFAMILY":
        return "MULTIFAMILY"

    if parcel_archetype == "RETAIL":
        return "BIG_BOX_COMMERCIAL" if footprint_area_m2 >= 2500 else "SMALL_COMMERCIAL"

    if parcel_archetype == "OFFICE":
        return "OFFICE_HIGHRISE" if height_m >= 25 else "SMALL_COMMERCIAL"

    if parcel_archetype == "INDUSTRIAL":
        return "INDUSTRIAL"

    if parcel_archetype in ("CIVIC", "SCHOOL", "MEDICAL"):
        return "CIVIC_SPECIAL"

    # PARK, VACANT_OPEN, UNKNOWN, and any unrecognized archetype: fall back
    # to what the massing itself implies, so an observed footprint on
    # unclassified land still reads as *something* coherent.  Small
    # footprints read as houses; mid-size low masses as small commercial;
    # large low masses as industrial/warehouse; taller mid-size masses as
    # multifamily.  GENERIC_UNKNOWN remains only for shapes that genuinely
    # carry no signal (mid-size, mid-height).
    if footprint_area_m2 < 300:
        return "DETACHED_RESIDENTIAL"
    if footprint_area_m2 >= 2000:
        return "BIG_BOX_COMMERCIAL" if height_m < 12 else "MULTIFAMILY"
    if height_m >= 10:
        return "MULTIFAMILY"
    if footprint_area_m2 >= 700:
        return "INDUSTRIAL" if height_m < 7 else "GENERIC_UNKNOWN"
    return "GENERIC_UNKNOWN"


# ---------------------------------------------------------------------------
# 7. Parcel-detail generation grammar
# ---------------------------------------------------------------------------
# Deterministic (probability-of-presence, not randomness itself) parameters
# consumed by the parcel-detail compiler. Every PARCEL_ARCHETYPES entry has
# a complete row. Reasoning per archetype is documented inline below.
PARCEL_DETAIL_GRAMMAR = {
    # A US-suburban single-family lot: near-universal driveway/walkway/
    # mailbox, modest greenery, an AC condenser tucked at the side, no
    # commercial parking demand.
    "RESIDENTIAL": {
        "driveway": 0.95,
        "front_walkway": 0.9,
        "mailbox": 0.85,
        "bins": 0.9,
        "ac_condenser": 0.85,
        "fence": 0.35,
        "parked_vehicle": 0.7,
        "tree_density_per_100m2": 0.06,
        "bush_density_per_100m2": 0.15,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.0,
        "dumpster": 0.0,
        "flagpole_or_sign": 0.05,
        "vehicle_mix": [("sedan", 5), ("suv", 4), ("pickup", 2)],
    },
    # Shared driveways/walkways are less universal per-unit; more units
    # share bin/AC infrastructure; some resident parking is expected but
    # not a full commercial lot.
    "MULTIFAMILY": {
        "driveway": 0.6,
        "front_walkway": 0.8,
        "mailbox": 0.5,  # often consolidated cluster boxes rather than per-unit
        "bins": 0.95,
        "ac_condenser": 0.7,
        "fence": 0.25,
        "parked_vehicle": 0.85,
        "tree_density_per_100m2": 0.04,
        "bush_density_per_100m2": 0.1,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.25,
        "dumpster": 0.6,
        "flagpole_or_sign": 0.15,
        "vehicle_mix": [("sedan", 5), ("suv", 4), ("pickup", 1), ("van", 1)],
    },
    # No residential yard furniture; a customer parking lot dominates open
    # area; dumpster and signage are near-universal.
    "RETAIL": {
        "driveway": 0.0,
        "front_walkway": 0.4,
        "mailbox": 0.0,
        "bins": 0.2,
        "ac_condenser": 0.3,  # small units, big rooftop HVAC is more typical
        "fence": 0.1,
        "parked_vehicle": 0.9,
        "tree_density_per_100m2": 0.015,
        "bush_density_per_100m2": 0.04,
        "lawn_surface": "PARKING",
        "parking_demand": 0.6,
        "dumpster": 0.85,
        "flagpole_or_sign": 0.7,
        "vehicle_mix": [("sedan", 5), ("suv", 5)],
    },
    # Office parks: moderate landscaping, dedicated employee parking, low
    # signage relative to retail.
    "OFFICE": {
        "driveway": 0.0,
        "front_walkway": 0.6,
        "mailbox": 0.1,
        "bins": 0.3,
        "ac_condenser": 0.2,
        "fence": 0.1,
        "parked_vehicle": 0.85,
        "tree_density_per_100m2": 0.03,
        "bush_density_per_100m2": 0.08,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.5,
        "dumpster": 0.4,
        "flagpole_or_sign": 0.3,
        "vehicle_mix": [("sedan", 6), ("suv", 4)],
    },
    # Industrial sites: mostly hardscape/gravel, chain-link security fencing
    # is the norm, heavier work-vehicle mix, lower parking-demand fraction
    # since much of the open area is loading/yard rather than car parking.
    "INDUSTRIAL": {
        "driveway": 0.0,
        "front_walkway": 0.15,
        "mailbox": 0.05,
        "bins": 0.3,
        "ac_condenser": 0.1,
        "fence": 0.75,
        "parked_vehicle": 0.7,
        "tree_density_per_100m2": 0.01,
        "bush_density_per_100m2": 0.01,
        "lawn_surface": "OTHER_IMPERVIOUS",
        "parking_demand": 0.35,
        "dumpster": 0.7,
        "flagpole_or_sign": 0.15,
        "vehicle_mix": [("pickup", 3), ("van", 3), ("box_truck", 3), ("sedan", 1)],
    },
    # Civic buildings (municipal, government, religious, military): tended
    # grounds, flagpoles are near-universal, moderate parking for visitors.
    "CIVIC": {
        "driveway": 0.2,
        "front_walkway": 0.85,
        "mailbox": 0.2,
        "bins": 0.5,
        "ac_condenser": 0.15,
        "fence": 0.2,
        "parked_vehicle": 0.6,
        "tree_density_per_100m2": 0.04,
        "bush_density_per_100m2": 0.1,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.4,
        "dumpster": 0.4,
        "flagpole_or_sign": 0.8,
        "vehicle_mix": [("sedan", 5), ("suv", 4), ("van", 1)],
    },
    # School grounds: large lawns/fields, drop-off driveways, bus/parent
    # parking demand, security fencing around play areas.
    "SCHOOL": {
        "driveway": 0.5,
        "front_walkway": 0.85,
        "mailbox": 0.1,
        "bins": 0.5,
        "ac_condenser": 0.15,
        "fence": 0.6,
        "parked_vehicle": 0.7,
        "tree_density_per_100m2": 0.035,
        "bush_density_per_100m2": 0.07,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.3,
        "dumpster": 0.5,
        "flagpole_or_sign": 0.6,
        "vehicle_mix": [("sedan", 5), ("suv", 4), ("van", 2)],
    },
    # Medical campuses: high parking demand for patients/staff, groomed
    # grounds, low residential-style furniture.
    "MEDICAL": {
        "driveway": 0.1,
        "front_walkway": 0.7,
        "mailbox": 0.1,
        "bins": 0.4,
        "ac_condenser": 0.2,
        "fence": 0.1,
        "parked_vehicle": 0.85,
        "tree_density_per_100m2": 0.03,
        "bush_density_per_100m2": 0.08,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.5,
        "dumpster": 0.55,
        "flagpole_or_sign": 0.3,
        "vehicle_mix": [("sedan", 6), ("suv", 4)],
    },
    # Open park land: no built infrastructure of the kind above; ground
    # cover leans toward maintained lawn but with essentially no
    # parking/hardscape carve-out at the parcel-detail level.
    "PARK": {
        "driveway": 0.0,
        "front_walkway": 0.2,
        "mailbox": 0.0,
        "bins": 0.3,
        "ac_condenser": 0.0,
        "fence": 0.05,
        "parked_vehicle": 0.05,
        "tree_density_per_100m2": 0.08,
        "bush_density_per_100m2": 0.1,
        "lawn_surface": "MAINTAINED_GRASS",
        "parking_demand": 0.05,
        "dumpster": 0.05,
        "flagpole_or_sign": 0.05,
        "vehicle_mix": [("sedan", 1)],
    },
    # Vacant/undeveloped: essentially nothing built; rough, untended
    # ground cover; negligible everything else.
    "VACANT_OPEN": {
        "driveway": 0.0,
        "front_walkway": 0.0,
        "mailbox": 0.0,
        "bins": 0.0,
        "ac_condenser": 0.0,
        "fence": 0.15,
        "parked_vehicle": 0.02,
        "tree_density_per_100m2": 0.02,
        "bush_density_per_100m2": 0.03,
        "lawn_surface": "ROUGH_VEGETATION",
        "parking_demand": 0.0,
        "dumpster": 0.0,
        "flagpole_or_sign": 0.0,
        "vehicle_mix": [("sedan", 1)],
    },
    # Unknown: conservative near-zero defaults so an unclassified parcel
    # doesn't get inappropriately elaborate detailing.
    "UNKNOWN": {
        "driveway": 0.1,
        "front_walkway": 0.1,
        "mailbox": 0.05,
        "bins": 0.1,
        "ac_condenser": 0.05,
        "fence": 0.1,
        "parked_vehicle": 0.2,
        "tree_density_per_100m2": 0.02,
        "bush_density_per_100m2": 0.03,
        "lawn_surface": "ROUGH_VEGETATION",
        "parking_demand": 0.05,
        "dumpster": 0.05,
        "flagpole_or_sign": 0.02,
        "vehicle_mix": [("sedan", 3), ("suv", 2)],
    },
}


# ---------------------------------------------------------------------------
# 8. Road class grammar
# ---------------------------------------------------------------------------
# Deterministic geometric/decoration parameters per Overture road-segment
# class. footway/cycleway/path are non-carriageway pedestrian/cycle ways,
# flagged via carriageway=False; their "lanes" describes travel-way count
# for the path itself, not vehicle lanes.
ROAD_CLASS_PARAMS = {
    "motorway": {
        "lanes": 6,
        "lane_width_m": 3.6,
        "sidewalk": False,
        "sidewalk_width_m": 0.0,
        "verge_width_m": 3.0,
        "median": True,
        "shoulder": True,
        "curb": False,
        "markings": "solid_lanes",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "trunk": {
        "lanes": 4,
        "lane_width_m": 3.6,
        "sidewalk": False,
        "sidewalk_width_m": 0.0,
        "verge_width_m": 2.5,
        "median": True,
        "shoulder": True,
        "curb": False,
        "markings": "solid_lanes",
        "signalize_junctions": True,
        "carriageway": True,
    },
    "primary": {
        "lanes": 4,
        "lane_width_m": 3.5,
        "sidewalk": True,
        "sidewalk_width_m": 1.8,
        "verge_width_m": 2.0,
        "median": True,
        "shoulder": False,
        "curb": True,
        "markings": "solid_lanes",
        "signalize_junctions": True,
        "carriageway": True,
    },
    "secondary": {
        "lanes": 4,
        "lane_width_m": 3.3,
        "sidewalk": True,
        "sidewalk_width_m": 1.6,
        "verge_width_m": 1.5,
        "median": False,
        "shoulder": False,
        "curb": True,
        "markings": "dashed_center",
        "signalize_junctions": True,
        "carriageway": True,
    },
    "tertiary": {
        "lanes": 2,
        "lane_width_m": 3.3,
        "sidewalk": True,
        "sidewalk_width_m": 1.5,
        "verge_width_m": 1.5,
        "median": False,
        "shoulder": False,
        "curb": True,
        "markings": "dashed_center",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "residential": {
        "lanes": 2,
        "lane_width_m": 3.0,
        "sidewalk": True,
        "sidewalk_width_m": 1.5,
        "verge_width_m": 1.8,
        "median": False,
        "shoulder": False,
        "curb": True,
        "markings": "dashed_center",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "unclassified": {
        "lanes": 2,
        "lane_width_m": 3.0,
        "sidewalk": True,
        "sidewalk_width_m": 1.4,
        "verge_width_m": 1.5,
        "median": False,
        "shoulder": False,
        "curb": True,
        "markings": "none",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "service": {
        "lanes": 1,
        "lane_width_m": 3.0,
        "sidewalk": False,
        "sidewalk_width_m": 0.0,
        "verge_width_m": 0.5,
        "median": False,
        "shoulder": False,
        "curb": True,
        "markings": "none",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "living_street": {
        "lanes": 2,
        "lane_width_m": 2.8,
        "sidewalk": True,
        "sidewalk_width_m": 1.2,
        "verge_width_m": 0.5,
        "median": False,
        "shoulder": False,
        "curb": False,
        "markings": "none",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "unknown": {
        "lanes": 2,
        "lane_width_m": 3.0,
        "sidewalk": True,
        "sidewalk_width_m": 1.4,
        "verge_width_m": 1.5,
        "median": False,
        "shoulder": False,
        "curb": True,
        "markings": "none",
        "signalize_junctions": False,
        "carriageway": True,
    },
    "footway": {
        "lanes": 1,
        "lane_width_m": 1.5,
        "sidewalk": False,
        "sidewalk_width_m": 0.0,
        "verge_width_m": 0.3,
        "median": False,
        "shoulder": False,
        "curb": False,
        "markings": "none",
        "signalize_junctions": False,
        "carriageway": False,
    },
    "cycleway": {
        "lanes": 1,
        "lane_width_m": 1.8,
        "sidewalk": False,
        "sidewalk_width_m": 0.0,
        "verge_width_m": 0.3,
        "median": False,
        "shoulder": False,
        "curb": False,
        "markings": "dashed_center",
        "signalize_junctions": False,
        "carriageway": False,
    },
    "path": {
        "lanes": 1,
        "lane_width_m": 1.2,
        "sidewalk": False,
        "sidewalk_width_m": 0.0,
        "verge_width_m": 0.3,
        "median": False,
        "shoulder": False,
        "curb": False,
        "markings": "none",
        "signalize_junctions": False,
        "carriageway": False,
    },
}

_ROAD_PARAM_KEYS = {
    "lanes",
    "lane_width_m",
    "sidewalk",
    "sidewalk_width_m",
    "verge_width_m",
    "median",
    "shoulder",
    "curb",
    "markings",
    "signalize_junctions",
    "carriageway",
}

_VALID_MARKINGS = {"dashed_center", "solid_lanes", "none"}


def road_params_for(road_class: str) -> dict:
    """Look up ROAD_CLASS_PARAMS for a road class, falling back to "unknown".

    Case-insensitive; None/empty/unrecognized classes fall back to the
    "unknown" entry rather than raising, since malformed source data should
    degrade to a sane generic road rather than crash generation.
    """
    if not road_class:
        return ROAD_CLASS_PARAMS["unknown"]
    key = road_class.strip().lower()
    return ROAD_CLASS_PARAMS.get(key, ROAD_CLASS_PARAMS["unknown"])


# ---------------------------------------------------------------------------
# 9. Canonical kind lists
# ---------------------------------------------------------------------------
PROP_KINDS = [
    "mailbox",
    "garbage_bin",
    "recycling_bin",
    "fire_hydrant",
    "utility_pole",
    "streetlight",
    "traffic_sign",
    "traffic_signal",
    "guardrail",
    "bollard",
    "transformer_box",
    "utility_cabinet",
    "ac_condenser",
    "rooftop_hvac",
    "dumpster",
    "parking_stop",
    "bench",
    "bus_shelter",
    "wood_fence",
    "chainlink_fence",
    "pallet",
    "road_barrier",
]

VEHICLE_KINDS = ["sedan", "suv", "pickup", "van", "box_truck"]

TREE_KINDS = ["tree_round", "tree_conical", "tree_columnar"]

BUSH_KINDS = ["bush_round", "bush_low"]

_PROP_SET = set(PROP_KINDS)
_VEHICLE_SET = set(VEHICLE_KINDS)
_TREE_SET = set(TREE_KINDS)
_BUSH_SET = set(BUSH_KINDS)


# ---------------------------------------------------------------------------
# 10. Surface color hints
# ---------------------------------------------------------------------------
# Muted RGB triples (floats in [0, 1]) used as flat-shaded placeholder
# colors per surface type ahead of any textured material pass.
SURFACE_COLOR_HINTS = {
    "ROAD": [0.16, 0.16, 0.17],
    "SIDEWALK": [0.55, 0.55, 0.55],
    "PARKING": [0.22, 0.22, 0.23],
    "OTHER_IMPERVIOUS": [0.35, 0.35, 0.35],
    "MAINTAINED_GRASS": [0.30, 0.42, 0.22],
    "ROUGH_VEGETATION": [0.33, 0.38, 0.24],
    "TREE_CANOPY": [0.20, 0.32, 0.18],
    "BARE_GROUND": [0.45, 0.38, 0.30],
    "WATER": [0.15, 0.25, 0.35],
    "BUILDING": [0.4, 0.4, 0.4],
}

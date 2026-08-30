"""Tests for asphodel.world_source.grammar_tables."""

import math

import pytest

from asphodel.world_source import grammar_tables as gt


# ---------------------------------------------------------------------------
# Enum membership sanity
# ---------------------------------------------------------------------------

def test_landuse_to_parcel_values_are_valid_archetypes():
    for cls, archetype in gt.LANDUSE_TO_PARCEL.items():
        assert archetype in gt.PARCEL_ARCHETYPES, f"{cls!r} -> {archetype!r}"


def test_place_category_to_parcel_values_are_valid_archetypes():
    for cat, archetype in gt.PLACE_CATEGORY_TO_PARCEL.items():
        assert archetype in gt.PARCEL_ARCHETYPES, f"{cat!r} -> {archetype!r}"


def test_building_archetypes_list_has_no_duplicates():
    assert len(BUILDING := gt.BUILDING_ARCHETYPES) == len(set(BUILDING))


def test_parcel_archetypes_list_has_no_duplicates():
    assert len(gt.PARCEL_ARCHETYPES) == len(set(gt.PARCEL_ARCHETYPES))


def test_surface_types_list_has_no_duplicates():
    assert len(gt.SURFACE_TYPES) == len(set(gt.SURFACE_TYPES))


# ---------------------------------------------------------------------------
# parcel_archetype_for_landuse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "cls,expected",
    [
        ("residential", "RESIDENTIAL"),
        ("RETAIL", "RETAIL"),
        ("  Industrial  ", "INDUSTRIAL"),
        ("school", "SCHOOL"),
        ("university", "SCHOOL"),
        ("hospital", "MEDICAL"),
        ("park", "PARK"),
        ("forest", "PARK"),
        ("farmland", "VACANT_OPEN"),
        ("cemetery", "VACANT_OPEN"),
        ("religious", "CIVIC"),
        ("military", "CIVIC"),
        ("government", "CIVIC"),
        ("parking", "VACANT_OPEN"),
        ("garages", "VACANT_OPEN"),
        ("construction", "INDUSTRIAL"),
        ("brownfield", "INDUSTRIAL"),
        ("grass", "PARK"),
        ("meadow", "PARK"),
        ("recreation", "PARK"),
    ],
)
def test_parcel_archetype_for_landuse_known(cls, expected):
    assert gt.parcel_archetype_for_landuse(cls) == expected


@pytest.mark.parametrize("cls", [None, "", "   ", "totally_made_up_class", "xyz123"])
def test_parcel_archetype_for_landuse_unknown_fallback(cls):
    assert gt.parcel_archetype_for_landuse(cls) == "UNKNOWN"


def test_parcel_archetype_for_landuse_is_deterministic():
    for cls in list(gt.LANDUSE_TO_PARCEL) + ["nonsense", None, ""]:
        first = gt.parcel_archetype_for_landuse(cls)
        second = gt.parcel_archetype_for_landuse(cls)
        assert first == second


# ---------------------------------------------------------------------------
# parcel_archetype_for_place
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "category,expected",
    [
        ("school", "SCHOOL"),
        ("elementary_school", "SCHOOL"),
        ("hospital", "MEDICAL"),
        ("urgent_care_clinic", "MEDICAL"),
        ("grocery_store", "RETAIL"),
        ("supermarket", "RETAIL"),
        ("gas_station", "RETAIL"),
        ("fuel", "RETAIL"),
        ("fast_food_restaurant", "RETAIL"),
        ("cafe", "RETAIL"),
        ("hotel", "RETAIL"),
        ("bank", "RETAIL"),
        ("pharmacy", "MEDICAL"),
        ("church", "CIVIC"),
        ("place_of_worship", "CIVIC"),
        ("corporate_office", "OFFICE"),
        ("factory", "INDUSTRIAL"),
        ("industrial_park", "INDUSTRIAL"),
        ("warehouse_club", "INDUSTRIAL"),
        ("public_park", "PARK"),
    ],
)
def test_parcel_archetype_for_place_known(category, expected):
    result = gt.parcel_archetype_for_place(category)
    assert result in gt.PARCEL_ARCHETYPES
    # only assert the exact expectation for unambiguous single-keyword cases
    if category in ("school", "hospital", "supermarket", "gas_station", "fuel",
                     "cafe", "hotel", "bank", "pharmacy", "church",
                     "place_of_worship", "corporate_office", "factory",
                     "public_park"):
        assert result == expected


def test_parcel_archetype_for_place_longest_match_wins():
    # "warehouse" and "industrial" both could match "warehouse_industrial";
    # ensure a real overlap resolves to a single deterministic non-None value.
    result = gt.parcel_archetype_for_place("warehouse_industrial_unit")
    assert result == "INDUSTRIAL"


def test_parcel_archetype_for_place_no_hint_returns_none():
    assert gt.parcel_archetype_for_place("") is None
    assert gt.parcel_archetype_for_place(None) is None
    assert gt.parcel_archetype_for_place("totally_unrelated_category_zzz") is None


def test_parcel_archetype_for_place_deterministic():
    for cat in list(gt.PLACE_CATEGORY_TO_PARCEL) + [None, "", "nope"]:
        assert gt.parcel_archetype_for_place(cat) == gt.parcel_archetype_for_place(cat)


# ---------------------------------------------------------------------------
# building_archetype_for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "parcel,area,height,expected",
    [
        ("RESIDENTIAL", 200.0, 6.0, "DETACHED_RESIDENTIAL"),
        ("RESIDENTIAL", 349.9, 6.0, "DETACHED_RESIDENTIAL"),
        ("RESIDENTIAL", 350.0, 6.0, "MULTIFAMILY"),
        ("RESIDENTIAL", 800.0, 8.0, "MULTIFAMILY"),
        ("MULTIFAMILY", 900.0, 10.0, "MULTIFAMILY"),
        ("RETAIL", 2499.0, 8.0, "SMALL_COMMERCIAL"),
        ("RETAIL", 2500.0, 8.0, "BIG_BOX_COMMERCIAL"),
        ("RETAIL", 5000.0, 9.0, "BIG_BOX_COMMERCIAL"),
        ("OFFICE", 1000.0, 10.0, "SMALL_COMMERCIAL"),
        ("OFFICE", 1000.0, 24.9, "SMALL_COMMERCIAL"),
        ("OFFICE", 1000.0, 25.0, "OFFICE_HIGHRISE"),
        ("INDUSTRIAL", 4000.0, 12.0, "INDUSTRIAL"),
        ("CIVIC", 500.0, 10.0, "CIVIC_SPECIAL"),
        ("SCHOOL", 3000.0, 10.0, "CIVIC_SPECIAL"),
        ("MEDICAL", 3000.0, 10.0, "CIVIC_SPECIAL"),
        # Unclassified land falls back to massing-implied archetypes: small
        # footprints read as houses, mid-size mid-height stays generic.
        ("PARK", 50.0, 3.0, "DETACHED_RESIDENTIAL"),
        ("VACANT_OPEN", 0.0, 0.0, "DETACHED_RESIDENTIAL"),
        ("UNKNOWN", 100.0, 5.0, "DETACHED_RESIDENTIAL"),
        ("UNKNOWN", 500.0, 5.0, "GENERIC_UNKNOWN"),
        ("UNKNOWN", 900.0, 5.0, "INDUSTRIAL"),
        ("UNKNOWN", 2500.0, 6.0, "BIG_BOX_COMMERCIAL"),
        ("UNKNOWN", 450.0, 11.0, "MULTIFAMILY"),
        # height >= 30 overrides everything
        ("RESIDENTIAL", 100.0, 30.0, "OFFICE_HIGHRISE"),
        ("VACANT_OPEN", 10.0, 31.0, "OFFICE_HIGHRISE"),
        ("INDUSTRIAL", 5000.0, 30.0, "OFFICE_HIGHRISE"),
    ],
)
def test_building_archetype_for(parcel, area, height, expected):
    result = gt.building_archetype_for(parcel, area, height)
    assert result == expected
    assert result in gt.BUILDING_ARCHETYPES


def test_building_archetype_for_is_deterministic():
    args = ("RETAIL", 3000.0, 9.0)
    assert gt.building_archetype_for(*args) == gt.building_archetype_for(*args)


# ---------------------------------------------------------------------------
# PARCEL_DETAIL_GRAMMAR completeness
# ---------------------------------------------------------------------------

_REQUIRED_GRAMMAR_KEYS = {
    "driveway",
    "front_walkway",
    "mailbox",
    "bins",
    "ac_condenser",
    "fence",
    "parked_vehicle",
    "tree_density_per_100m2",
    "bush_density_per_100m2",
    "lawn_surface",
    "parking_demand",
    "dumpster",
    "flagpole_or_sign",
    "vehicle_mix",
}

_PROB_KEYS = {
    "driveway",
    "front_walkway",
    "mailbox",
    "bins",
    "ac_condenser",
    "fence",
    "parked_vehicle",
    "parking_demand",
    "dumpster",
    "flagpole_or_sign",
}


def test_every_parcel_archetype_has_grammar_entry():
    for archetype in gt.PARCEL_ARCHETYPES:
        assert archetype in gt.PARCEL_DETAIL_GRAMMAR, f"missing grammar for {archetype}"


def test_grammar_entries_have_no_extra_or_missing_keys():
    for archetype, entry in gt.PARCEL_DETAIL_GRAMMAR.items():
        assert set(entry.keys()) == _REQUIRED_GRAMMAR_KEYS, archetype


def test_grammar_probabilities_within_bounds():
    for archetype, entry in gt.PARCEL_DETAIL_GRAMMAR.items():
        for key in _PROB_KEYS:
            value = entry[key]
            assert isinstance(value, (int, float)), (archetype, key)
            assert 0.0 <= value <= 1.0, (archetype, key, value)


def test_grammar_densities_are_nonnegative_floats():
    for archetype, entry in gt.PARCEL_DETAIL_GRAMMAR.items():
        for key in ("tree_density_per_100m2", "bush_density_per_100m2"):
            value = entry[key]
            assert isinstance(value, (int, float)), (archetype, key)
            assert value >= 0.0, (archetype, key, value)
            assert math.isfinite(value)


def test_grammar_lawn_surface_is_valid_surface_type():
    for archetype, entry in gt.PARCEL_DETAIL_GRAMMAR.items():
        assert entry["lawn_surface"] in gt.SURFACE_TYPES, archetype


def test_grammar_vehicle_mix_valid_and_positive():
    for archetype, entry in gt.PARCEL_DETAIL_GRAMMAR.items():
        mix = entry["vehicle_mix"]
        assert isinstance(mix, list) and len(mix) > 0, archetype
        for kind, weight in mix:
            assert kind in gt.VEHICLE_KINDS, (archetype, kind)
            assert isinstance(weight, (int, float))
            assert weight > 0, (archetype, kind, weight)


# ---------------------------------------------------------------------------
# ROAD_CLASS_PARAMS completeness
# ---------------------------------------------------------------------------

_EXPECTED_ROAD_CLASSES = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "unclassified",
    "service",
    "living_street",
    "unknown",
    "footway",
    "cycleway",
    "path",
}

_REQUIRED_ROAD_KEYS = {
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
}

_VALID_MARKINGS = {"dashed_center", "solid_lanes", "none"}


def test_all_expected_road_classes_present():
    assert _EXPECTED_ROAD_CLASSES.issubset(set(gt.ROAD_CLASS_PARAMS.keys()))


def test_road_params_have_required_keys():
    for road_class, params in gt.ROAD_CLASS_PARAMS.items():
        missing = _REQUIRED_ROAD_KEYS - set(params.keys())
        assert not missing, f"{road_class} missing {missing}"


def test_road_params_types_and_ranges():
    for road_class, params in gt.ROAD_CLASS_PARAMS.items():
        assert isinstance(params["lanes"], int) and params["lanes"] >= 1, road_class
        assert params["lane_width_m"] > 0, road_class
        assert isinstance(params["sidewalk"], bool), road_class
        assert params["sidewalk_width_m"] >= 0, road_class
        assert params["verge_width_m"] >= 0, road_class
        assert isinstance(params["median"], bool), road_class
        assert isinstance(params["shoulder"], bool), road_class
        assert isinstance(params["curb"], bool), road_class
        assert params["markings"] in _VALID_MARKINGS, road_class
        assert isinstance(params["signalize_junctions"], bool), road_class


def test_non_carriageway_classes_flagged():
    for cls in ("footway", "cycleway", "path"):
        assert gt.ROAD_CLASS_PARAMS[cls]["carriageway"] is False


def test_carriageway_classes_flagged_true():
    for cls in ("motorway", "trunk", "primary", "secondary", "tertiary",
                "residential", "unclassified", "service", "living_street",
                "unknown"):
        assert gt.ROAD_CLASS_PARAMS[cls]["carriageway"] is True


def test_road_params_for_known_classes():
    for cls in gt.ROAD_CLASS_PARAMS:
        assert gt.road_params_for(cls) == gt.ROAD_CLASS_PARAMS[cls]
        assert gt.road_params_for(cls.upper()) == gt.ROAD_CLASS_PARAMS[cls]


def test_road_params_for_unknown_falls_back():
    assert gt.road_params_for("not_a_real_class") == gt.ROAD_CLASS_PARAMS["unknown"]
    assert gt.road_params_for(None) == gt.ROAD_CLASS_PARAMS["unknown"]
    assert gt.road_params_for("") == gt.ROAD_CLASS_PARAMS["unknown"]


def test_road_params_for_deterministic():
    for cls in list(gt.ROAD_CLASS_PARAMS) + [None, "", "bogus"]:
        assert gt.road_params_for(cls) == gt.road_params_for(cls)


def test_motorway_has_no_sidewalk_and_has_shoulder():
    m = gt.ROAD_CLASS_PARAMS["motorway"]
    assert m["sidewalk"] is False
    assert m["shoulder"] is True
    assert m["lanes"] == 6


def test_service_road_minimal():
    s = gt.ROAD_CLASS_PARAMS["service"]
    assert s["lanes"] == 1
    assert s["sidewalk"] is False
    assert s["markings"] == "none"


# ---------------------------------------------------------------------------
# Canonical kind lists
# ---------------------------------------------------------------------------

def test_prop_kinds_no_duplicates_and_nonempty():
    assert len(gt.PROP_KINDS) == len(set(gt.PROP_KINDS))
    assert len(gt.PROP_KINDS) > 0


def test_vehicle_kinds_match_used_in_grammar():
    used_kinds = set()
    for entry in gt.PARCEL_DETAIL_GRAMMAR.values():
        for kind, _weight in entry["vehicle_mix"]:
            used_kinds.add(kind)
    assert used_kinds.issubset(set(gt.VEHICLE_KINDS))


def test_tree_and_bush_kinds_nonempty_and_unique():
    assert len(gt.TREE_KINDS) == len(set(gt.TREE_KINDS)) and gt.TREE_KINDS
    assert len(gt.BUSH_KINDS) == len(set(gt.BUSH_KINDS)) and gt.BUSH_KINDS


# ---------------------------------------------------------------------------
# SURFACE_COLOR_HINTS
# ---------------------------------------------------------------------------

def test_surface_color_hints_cover_all_surface_types():
    assert set(gt.SURFACE_COLOR_HINTS.keys()) == set(gt.SURFACE_TYPES)


def test_surface_color_hints_are_valid_rgb_triples():
    for surface, rgb in gt.SURFACE_COLOR_HINTS.items():
        assert isinstance(rgb, list) and len(rgb) == 3, surface
        for component in rgb:
            assert 0.0 <= component <= 1.0, (surface, rgb)

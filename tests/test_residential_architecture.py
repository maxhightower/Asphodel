"""ResidentialArchitectureV1 schema, provenance, and observed-data-wins gates."""
from __future__ import annotations

import pytest

from asphodel.city_visual.residential_architecture import (
    ResidentialArchitectureV1, ArchValue, FORMS, STYLES, FACADE_SUBTYPE_TO_FAMILY,
)
from asphodel.world_source import residential_grammar as rg

from tests._res_fixtures import (
    rect, feature, compile_block, make_cohort, house_inputs,
)


def _arch_of(recs, key):
    return next(r.architecture for r in recs if r.key == key)


# ---- schema / serialization -------------------------------------------------
def test_default_record_is_valid_and_roundtrips():
    a = ResidentialArchitectureV1(bid=3)
    assert a.is_valid(), a.validate()
    d = a.to_dict()
    b = ResidentialArchitectureV1.from_dict(d)
    assert b.to_dict() == d


def test_invalid_enum_members_are_rejected():
    a = ResidentialArchitectureV1(bid=0)
    a.form = ArchValue("NOT_A_FORM", "DERIVED")
    assert any("form" in e for e in a.validate())
    a2 = ResidentialArchitectureV1(bid=0)
    a2.parking = "TELEPORTER"
    assert any("parking" in e for e in a2.validate())


def test_form_and_style_are_independent_axes():
    # Form and style are separate FIELDS, not a fused taxonomy: one form is shared
    # by several styles (a BUNGALOW can be CRAFTSMAN or FOLK_NATIONAL; a FOURSQUARE
    # can be CRAFTSMAN, QUEEN_ANNE, AMERICAN_FOURSQUARE or COLONIAL_REVIVAL).
    fs_users = [s for s, g in rg.STYLE_GRAMMAR.items() if "FOURSQUARE" in g["forms"]]
    assert len(fs_users) >= 3
    bung_users = [s for s, g in rg.STYLE_GRAMMAR.items() if "BUNGALOW" in g["forms"]]
    assert len(bung_users) >= 2
    # every style lists only real FORM members as compatible forms.
    for s, g in rg.STYLE_GRAMMAR.items():
        for f in g["forms"]:
            assert f in FORMS, (s, f)
    # the record keeps them in distinct fields with independent provenance.
    a = ResidentialArchitectureV1(bid=0)
    assert hasattr(a, "form") and hasattr(a, "style") and a.form is not a.style


# ---- provenance honesty -----------------------------------------------------
def test_style_may_not_be_observed():
    a = ResidentialArchitectureV1(bid=0)
    a.style = ArchValue("CRAFTSMAN", "OBSERVED")
    assert any("style may not be OBSERVED" in e for e in a.validate())


def test_generated_style_is_never_observed_and_form_is_derived():
    feats = [feature(f"h{i}", rect(40 + i * 16, 40, 12, 10)) for i in range(12)]
    recs, _ = compile_block(feats)
    for r in recs:
        a = r.architecture
        assert a is not None
        assert a["style"]["class"] in ("DERIVED", "PROCEDURAL")
        assert a["style"]["class"] != "OBSERVED"
        assert a["form"]["class"] == "DERIVED"       # follows observed footprint
        assert a["era"]["class"] != "OBSERVED"


def test_era_from_real_year_is_derived_not_procedural():
    inp = house_inputs("y", rect(0, 0, 12, 10), obs_year=1925)
    a = rg.build_architecture(inp, make_cohort("TRADITIONAL_RANCH"), seed=1)
    assert a.era.value == "1920_1939"
    assert a.era.provenance == "DERIVED"


# ---- observed data wins -----------------------------------------------------
def test_observed_one_story_cannot_become_two_story_form():
    # levels==1 is observed; no 2-storey form (Foursquare/Revival/Suburban 2-story)
    # may be selected however the cohort leans.
    feats = [feature(f"h{i}", rect(40 + i * 16, 40, 12, 12), {"levels": 1})
             for i in range(16)]
    recs, _ = compile_block(feats)
    two_story = {"FOURSQUARE", "REVIVAL_TWO_STORY", "SUBURBAN_TWO_STORY"}
    for r in recs:
        assert r.architecture["form"]["value"] not in two_story
        assert r.architecture["massing"]["story_profile"] != "TWO"


def test_observed_flat_roof_shape_wins():
    feats = [feature("flat", rect(40, 40, 14, 10), {"roof_shape": "flat"})]
    recs, _ = compile_block(feats)
    a = _arch_of(recs, "flat")
    assert a["roof"]["family"] == "FLAT"
    assert a["roof"]["pitch"] == "VERY_LOW"


def test_observed_facade_material_is_honoured_on_front():
    feats = [feature("brk", rect(40, 40, 18, 8), {"facade_material": "brick"})]
    recs, _ = compile_block(feats)
    a = _arch_of(recs, "brk")
    assert FACADE_SUBTYPE_TO_FAMILY[a["facade"]["front"]] == "brick"


def test_facade_subtypes_all_map_to_a_shared_shader_family():
    from asphodel.city_visual.building_appearance import FACADE_MATERIALS
    for sub, fam in FACADE_SUBTYPE_TO_FAMILY.items():
        assert fam in FACADE_MATERIALS, (sub, fam)


# ---- multi-material facade --------------------------------------------------
def test_texas_neo_traditional_is_brick_front_siding_side():
    a = rg.build_architecture(
        house_inputs("t", rect(0, 0, 16, 12), obs_floors=2),
        make_cohort("TEXAS_NEO_TRADITIONAL", era="1980_1999"), seed=5)
    assert a.style.value == "TEXAS_NEO_TRADITIONAL"
    assert FACADE_SUBTYPE_TO_FAMILY[a.facade.front] == "brick"
    assert FACADE_SUBTYPE_TO_FAMILY[a.facade.side_rear] == "siding"


def test_non_residential_gets_no_architecture_record():
    # a big footprint on a retail parcel -> not detached residential -> no record.
    from asphodel.world_source.records import Parcel
    from asphodel.world_source import buildings_grammar
    f = feature("shop", rect(40, 40, 40, 30), {"subtype": "commercial"})
    par = Parcel(pid="p:0:s", poly=None, arch="RETAIL", obs="DERIVED",
                 block_id=0, building_bids=[0])
    from shapely.geometry import Polygon
    par.poly = Polygon([(0, 0), (200, 0), (200, 200), (0, 200)])
    recs = buildings_grammar.compile_buildings([f], [par], segments=[], seed=1)
    rg.assign_architecture(recs, [par], [par.poly], seed=1)
    assert recs[0].arch != "DETACHED_RESIDENTIAL"
    assert recs[0].architecture is None

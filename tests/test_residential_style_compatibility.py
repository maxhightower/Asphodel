"""Form/style/morphology compatibility gates + style-grammar visual rules."""
from __future__ import annotations

from shapely.geometry import Polygon

from asphodel.world_source import residential_grammar as rg
from tests._res_fixtures import rect, lshape, ushape, make_cohort, house_inputs


def morph(geom):
    return rg.compute_morphology(Polygon(geom[0]))


# ---- form eligibility from morphology ---------------------------------------
def test_one_story_footprint_is_not_foursquare_eligible():
    m = morph(rect(0, 0, 12, 12))          # near-square
    assert not rg.form_eligible("FOURSQUARE", m, obs_floors=1)
    assert rg.form_eligible("FOURSQUARE", m, obs_floors=2)     # 2-storey square ok


def test_elongated_footprint_is_ranch_not_foursquare():
    m = morph(rect(0, 0, 24, 8))           # aspect 3.0
    assert rg.form_eligible("LINEAR_RANCH", m, obs_floors=1)
    assert not rg.form_eligible("FOURSQUARE", m, obs_floors=None)
    forms = rg.eligible_forms(m, obs_floors=1)
    assert "LINEAR_RANCH" in forms and "FOURSQUARE" not in forms


def test_l_and_u_ranch_require_compatible_footprint():
    plain = morph(rect(0, 0, 18, 10))      # rectangle, no wings
    assert not rg.form_eligible("L_RANCH", plain, obs_floors=1)
    assert not rg.form_eligible("U_RANCH", plain, obs_floors=1)
    l = morph(lshape(0, 0, 18, 14))
    assert rg.form_eligible("L_RANCH", l, obs_floors=1)
    u = morph(ushape(0, 0, 24, 18))
    assert u.winged_strong
    assert rg.form_eligible("U_RANCH", u, obs_floors=1)


def test_eligible_forms_never_empty():
    for geom in (rect(0, 0, 6, 6), rect(0, 0, 40, 6), lshape(0, 0, 30, 20)):
        assert rg.eligible_forms(morph(geom), None)
        assert rg.eligible_forms(morph(geom), 1)
        assert rg.eligible_forms(morph(geom), 2)


def test_incompatible_style_form_pairs_never_produced():
    # whatever the cohort, the chosen form must be listed as compatible with the
    # chosen style (form<->style compatibility is enforced by the selector).
    feats_geoms = [rect(0, 0, 12, 10), rect(0, 0, 26, 8), rect(0, 0, 13, 13),
                   lshape(0, 0, 16, 12)]
    for era in rg.ERA_SEQUENCE:
        cohort = rg.Cohort(0, era, era,
                           tuple(), rg.styles_for_era(era), rg.styles_for_era(era),
                           [], 0.0, 0.0)
        for i, g in enumerate(feats_geoms):
            a = rg.build_architecture(house_inputs(f"k{era}{i}", g), cohort, seed=3)
            assert a.form.value in rg.STYLE_GRAMMAR[a.style.value]["forms"], \
                (a.style.value, a.form.value)


# ---- style grammar visual rules ---------------------------------------------
def test_colonial_uses_symmetric_window_grammar():
    a = rg.build_architecture(house_inputs("c", rect(0, 0, 14, 12), obs_floors=2),
                              make_cohort("COLONIAL_REVIVAL"), seed=2)
    assert a.style.value == "COLONIAL_REVIVAL"
    assert a.windows.family == "COLONIAL_SYMMETRIC"
    assert a.windows.symmetric is True
    assert a.massing.symmetry == "SYMMETRIC"


def test_tudor_chooses_steep_roof():
    a = rg.build_architecture(house_inputs("t", rect(0, 0, 13, 11), obs_floors=2),
                              make_cohort("TUDOR_REVIVAL"), seed=2)
    assert a.style.value == "TUDOR_REVIVAL"
    assert a.roof.pitch == "STEEP"
    assert a.roof.family in ("CROSS_GABLE", "FRONT_GABLE")


def test_mcm_chooses_very_low_roof_and_horizontal_windows():
    a = rg.build_architecture(house_inputs("m", rect(0, 0, 22, 9), obs_floors=1),
                              make_cohort("MID_CENTURY_MODERN"), seed=2)
    assert a.style.value == "MID_CENTURY_MODERN"
    assert a.roof.pitch == "VERY_LOW"
    assert a.windows.family == "MCM_HORIZONTAL"
    assert a.massing.horizontal_emphasis == "HIGH"


def test_ranch_usually_uses_slab_foundation():
    slab = 0
    for i in range(40):
        a = rg.build_architecture(
            house_inputs(f"r{i}", rect(0, 0, 22, 9), obs_floors=1),
            make_cohort("TRADITIONAL_RANCH"), seed=100 + i)
        if a.foundation.family == "SLAB_ON_GRADE":
            slab += 1
    assert slab >= 30    # strongly slab-dominant


def test_historic_forms_can_use_raised_foundation():
    raised = 0
    for i in range(40):
        a = rg.build_architecture(
            house_inputs(f"b{i}", rect(0, 0, 12, 10), obs_floors=1),
            make_cohort("CRAFTSMAN", form="BUNGALOW", era="1920_1939"),
            seed=200 + i)
        if a.foundation.family in ("RAISED_PIER_BEAM", "LOW_CRAWLSPACE"):
            raised += 1
    assert raised >= 25    # historic bungalows sit above grade often


def test_craftsman_forms_and_details():
    a = rg.build_architecture(house_inputs("cf", rect(0, 0, 12, 10), obs_floors=1),
                              make_cohort("CRAFTSMAN", form="BUNGALOW"), seed=2)
    assert a.form.value == "BUNGALOW"
    assert a.roof.eave in ("WIDE", "VERY_WIDE")
    assert "exposed_rafter_tails" in a.details


def test_spanish_uses_tile_roof():
    a = rg.build_architecture(house_inputs("sp", rect(0, 0, 16, 11), obs_floors=1),
                              make_cohort("SPANISH_ECLECTIC"), seed=2)
    assert a.roof.material == "tile"


def test_all_twelve_production_styles_are_realisable():
    # every first-wave style can produce a valid record on some compatible
    # footprint (i.e. the grammar tables are internally consistent).
    geoms = {
        1: rect(0, 0, 12, 10), 2: rect(0, 0, 14, 13),
    }
    for style in rg.STYLES_PROD:
        g = rg.STYLE_GRAMMAR[style]
        form = g["forms"][0]
        floors = 2 if form in ("FOURSQUARE", "REVIVAL_TWO_STORY",
                               "SUBURBAN_TWO_STORY") else 1
        geom = rect(0, 0, 20, 8) if "RANCH" in form else rect(0, 0, 13, 12)
        if form in ("L_RANCH",):
            geom = lshape(0, 0, 16, 12)
        if form in ("U_RANCH",):
            geom = ushape(0, 0, 20, 14)
        a = rg.build_architecture(house_inputs("x", geom, obs_floors=floors),
                                  make_cohort(style, form=form), seed=7)
        assert a.style.value == style
        assert not a.validate(), (style, a.validate())

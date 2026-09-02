"""Package A contract tests: AssetCatalogV1, BuildingAppearanceV1,
CityVisualProfileV1, and the no-city-name-special-case static gate (Section 24)."""
from __future__ import annotations

import os
import re

import pytest

from asphodel.city_visual import (
    AssetCatalogV1, AssetFamily, AssetVariant,
    BuildingAppearanceV1, FacadeAppearance, RoofAppearance, AppearanceValue,
    CityVisualProfileV1,
)
from asphodel.city_visual.city_profile import SourceRef
from asphodel.city_visual import provenance

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# --------------------------------------------------------------- asset catalog
def test_catalog_loads_and_validates():
    cat = AssetCatalogV1.load()
    assert cat.families, "catalog is empty"
    assert cat.validate() == []


def test_catalog_semantic_ids_unique():
    cat = AssetCatalogV1.load()
    ids = list(cat.families.keys())
    assert len(ids) == len(set(ids))


def test_every_variant_has_a_resource_or_fallback():
    cat = AssetCatalogV1.load()
    for fam in cat.families.values():
        assert fam.variants, f"{fam.semantic_id} has no variants"
        for v in fam.variants:
            assert v.resource or v.procedural, f"{fam.semantic_id}/{v.id} unbacked"


def test_dimensions_positive():
    cat = AssetCatalogV1.load()
    for fam in cat.families.values():
        for k in ("width_m", "depth_m", "height_m"):
            assert fam.dimensions.get(k, 0) > 0, f"{fam.semantic_id} bad {k}"


def test_deterministic_selection_is_stable_and_in_range():
    cat = AssetCatalogV1.load()
    fam = cat.get("vehicle_sedan")
    ids = {v.id for v in fam.variants}
    for seed in range(50):
        a = fam.select(seed).id
        b = fam.select(seed).id
        assert a == b, "selection not deterministic"
        assert a in ids


def test_unknown_semantic_id_fails_visibly():
    cat = AssetCatalogV1.load()
    with pytest.raises(KeyError):
        cat.get("chair_does_not_exist")


def test_catalog_validation_catches_bad_family():
    bad = AssetFamily(semantic_id="x", category="not_a_category",
                      dimensions={"width_m": 0, "depth_m": 1, "height_m": 1},
                      variants=[AssetVariant(id="x0")])  # no resource/procedural
    cat = AssetCatalogV1.from_list([bad])
    errs = cat.validate()
    assert any("category" in e for e in errs)
    assert any("dimension" in e for e in errs)
    assert any("resource" in e or "fallback" in e for e in errs)


# ----------------------------------------------------- building appearance V1
def _appearance(**kw):
    f = FacadeAppearance(AppearanceValue(kw.get("fc"), kw.get("fcc", "DERIVED")),
                         AppearanceValue(kw.get("fm"), kw.get("fmc", "DERIVED")))
    r = RoofAppearance(AppearanceValue(kw.get("rc"), kw.get("rcc", "DERIVED")),
                       AppearanceValue(kw.get("rm"), kw.get("rmc", "PROCEDURAL")),
                       AppearanceValue(kw.get("rs"), kw.get("rsc", "DERIVED")))
    return BuildingAppearanceV1(bid=kw.get("bid", 1), facade=f, roof=r,
                                style_family=AppearanceValue(kw.get("sf"), "DERIVED"))


def test_building_appearance_roundtrip():
    a = _appearance(fc="#c3a887", fm="brick", rc="#49443e", rm="asphalt_shingle",
                    rs="gabled", sf="gulf_residential_brick", fcc="OBSERVED",
                    fmc="OBSERVED")
    assert a.is_valid(), a.validate()
    b = BuildingAppearanceV1.from_dict(a.to_dict())
    assert b.to_dict() == a.to_dict()
    assert b.facade.color.provenance == "OBSERVED"


def test_building_appearance_rejects_bad_hex_and_enum():
    a = _appearance(fc="red", fm="marble", rm="thatch", rs="onion")
    errs = a.validate()
    assert any("colour" in e for e in errs)
    assert any("facade.material" in e for e in errs)
    assert any("roof.material" in e for e in errs)
    assert any("roof.shape" in e for e in errs)


def test_style_family_may_not_be_observed():
    a = _appearance(fc="#ffffff", fm="brick", rc="#000000", rm="tile", rs="flat")
    a.style_family = AppearanceValue("gulf_x", "OBSERVED")
    assert any("style_family" in e for e in a.validate())


def test_provenance_require():
    assert provenance.require("OBSERVED") == "OBSERVED"
    with pytest.raises(ValueError):
        provenance.require("GUESSED")


# ------------------------------------------------------- city visual profile
def _profile(**kw):
    return CityVisualProfileV1(
        city=kw.get("city", "testville"),
        location={"latitude": kw.get("lat", 29.76), "longitude": kw.get("lon", -95.36)},
        architecture={"facade_material_dist": kw.get("fmd", {"brick": 0.5, "siding": 0.5})},
        atmosphere={"humidity_factor": kw.get("hf", 0.8), "haze_factor": 0.5,
                    "cloudiness_prior": 0.4},
        vegetation={"regional_family": "gulf",
                    "landcover_distribution": {"grass": 0.6, "canopy": 0.4}},
        sources=[SourceRef(name="test", license="PUBLIC_DOMAIN")],
    )


def test_city_profile_roundtrip_and_valid():
    p = _profile()
    assert p.is_valid(), p.validate()
    q = CityVisualProfileV1.from_dict(p.to_dict())
    assert q.to_dict() == p.to_dict()


def test_city_profile_rejects_bad_lat_and_dist_and_observed():
    p = _profile(lat=200.0, fmd={"brick": 0.2, "siding": 0.2})  # lat bad, dist sums 0.4
    errs = p.validate()
    assert any("latitude" in e for e in errs)
    assert any("facade_material_dist" in e for e in errs)
    p2 = _profile()
    p2.appearance_class = "OBSERVED"
    assert any("OBSERVED" in e for e in p2.validate())


# --------------------------------------- Section 24: no city-name special cases
def test_no_city_name_rendering_special_cases():
    """Production generator/renderer code must not branch on a hardcoded city
    name. City identity may appear only in bundle selection / acquisition /
    provenance / tests / fixtures."""
    names = ("houston", "austin", "san_antonio", "san antonio", "madisonville")
    # equality/branch comparisons against a hardcoded city name
    pat = re.compile(r"(city[\w.]*\s*==\s*[\"'])|(==\s*[\"'](houston|austin|"
                     r"san_antonio|madisonville)[\"'])", re.IGNORECASE)
    scan_dirs = [os.path.join(REPO, "godot", "scripts"),
                 os.path.join(REPO, "asphodel", "city_visual")]
    offenders = []
    for base in scan_dirs:
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith((".gd", ".py")):
                    continue
                path = os.path.join(root, fn)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        low = line.lower()
                        if any(n in low for n in names) and pat.search(line):
                            offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, "city-name special cases found:\n" + "\n".join(offenders)

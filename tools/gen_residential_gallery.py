#!/usr/bin/env python3
"""Generate the residential architecture gallery fixture.

Emits godot/tests/residential_gallery.json: one deterministic, representative
compiled house per production style, each a building dict in the chunk contract
shape (poly / h / entrance / architecture) that ResidentialHouseRenderer consumes
verbatim. The Godot gallery scene renders these in two modes (neutral silhouette
+ full material) so style diversity can be certified from SHAPE alone.

    python tools/gen_residential_gallery.py
"""
from __future__ import annotations

import json
import os

from shapely.geometry import Polygon

from asphodel.world_source import residential_grammar as rg


def rect(w, d):
    return [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]]


def lshape(w, d):
    return [[0, 0], [w, 0], [w, d * 0.5], [w * 0.5, d * 0.5], [w * 0.5, d], [0, d]]


# style -> (form, footprint ring, floors). Footprints match each style's primary
# form so the morphology admits it.
STYLE_SPECS = {
    "CRAFTSMAN":            ("BUNGALOW", rect(12, 10), 1),
    "FOLK_NATIONAL":        ("FOLK_COTTAGE", rect(11, 9), 1),
    "FOLK_VICTORIAN":       ("FOLK_COTTAGE", rect(11, 10), 1),
    "QUEEN_ANNE":           ("VICTORIAN_IRREGULAR", lshape(14, 13), 2),
    "AMERICAN_FOURSQUARE":  ("FOURSQUARE", rect(12, 12), 2),
    "COLONIAL_REVIVAL":     ("REVIVAL_TWO_STORY", rect(15, 11), 2),
    "TUDOR_REVIVAL":        ("TUDOR_COTTAGE", rect(13, 11), 2),
    "MINIMAL_TRADITIONAL":  ("MINIMAL_TRADITIONAL", rect(12, 9), 1),
    "TRADITIONAL_RANCH":    ("LINEAR_RANCH", rect(22, 9), 1),
    "MID_CENTURY_MODERN":   ("LINEAR_RANCH", rect(22, 9), 1),
    "TEXAS_NEO_TRADITIONAL": ("SUBURBAN_TWO_STORY", rect(16, 12), 2),
    "SPANISH_ECLECTIC":     ("MINIMAL_TRADITIONAL", rect(15, 11), 1),
}


def _ring_at(ring, ox, oz):
    return [[x + ox, z + oz] for x, z in ring]


def build_gallery():
    houses = []
    for i, (style, (form, ring, floors)) in enumerate(STYLE_SPECS.items()):
        cohort = _forced_cohort(style, form)
        inp = rg.HouseInputs(bid=i, key=f"gallery:{style}",
                             morph=rg.compute_morphology(Polygon(ring)),
                             obs_floors=floors)
        arch = rg.build_architecture(inp, cohort, seed=17)
        assert arch.style.value == style, (style, arch.style.value)
        assert not arch.validate(), arch.validate()
        h = floors * 3.3 + 0.6
        houses.append({
            "bid": i,
            "label": style,
            "poly": ring,
            "h": round(h, 2),
            "floors": floors,
            "arch": "DETACHED_RESIDENTIAL",
            "roof": "pitched",
            "entrance": {"edge": 0, "t": 0.5, "w": 1.2},
            "architecture": arch.to_dict(),
        })
    return {"version": 1, "houses": houses}


def _forced_cohort(style, form):
    g = rg.STYLE_GRAMMAR[style]
    fam = dict(id=0, style=style, form=form, story=g["story"][0],
               roof_family=g["roof"][0][0], porch_family=g["porch"][0][0],
               porch_support=g["supports"][0][0], parking=g["parking"][0][0],
               foundation=g["foundation"][0][0], package_idx=0, share=1.0)
    return rg.Cohort(cohort_id=0, dominant_era="1960_1979", secondary_era="1960_1979",
                     primary_forms=(form,), primary_styles=[(style, 1)],
                     secondary_styles=[(style, 1)], builder_families=[fam],
                     infill_probability=0.0, renovation_pressure=0.0)


def main():
    out = os.path.join(os.path.dirname(__file__), "..", "godot", "tests",
                       "residential_gallery.json")
    out = os.path.abspath(out)
    doc = build_gallery()
    with open(out, "w") as f:
        json.dump(doc, f, separators=(",", ":"), sort_keys=True)
    print(f"wrote {out} ({len(doc['houses'])} styles)")


if __name__ == "__main__":
    main()

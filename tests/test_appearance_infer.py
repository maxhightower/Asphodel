"""Package C: deterministic, spatially-coherent, provenance-honest appearance
inference for buildings without observed appearance."""
from __future__ import annotations

from asphodel.world_source import appearance as appear
from asphodel.world_source import appearance_infer as inf


def _blank(bid=0):
    return appear.build_appearance(bid, {"height_m": None}, "flat", None, False).to_dict()


def _rgb(hexs):
    hexs = hexs.lstrip("#")
    return tuple(int(hexs[i:i + 2], 16) for i in (0, 2, 4))


def _cdist(a, b):
    ra, rb = _rgb(a), _rgb(b)
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def test_inference_is_deterministic():
    a = inf.infer_building(1, "k1", 100.0, 200.0, "DETACHED_RESIDENTIAL", _blank(1), seed=7)
    b = inf.infer_building(1, "k1", 100.0, 200.0, "DETACHED_RESIDENTIAL", _blank(1), seed=7)
    assert a == b


def test_never_overwrites_observed():
    ap = appear.build_appearance(
        3, {"facade_color": "#123456", "facade_material": "brick",
            "roof_color": "#abcdef", "roof_material": "tile", "roof_shape": "hipped",
            "height_m": 5.0}, "pitched", 5.0, True).to_dict()
    inf.infer_building(3, "k3", 10.0, 10.0, "DETACHED_RESIDENTIAL", ap, seed=1)
    assert ap["facade"]["color"] == {"value": "#123456", "class": "OBSERVED"}
    assert ap["roof"]["color"] == {"value": "#abcdef", "class": "OBSERVED"}
    assert ap["roof"]["shape"] == {"value": "hipped", "class": "OBSERVED"}


def test_inferred_colour_is_procedural_and_complete():
    ap = inf.infer_building(2, "k2", 50.0, 50.0, "OFFICE_HIGHRISE", _blank(2), seed=5)
    for sec, fld in (("facade", "color"), ("facade", "material"),
                     ("roof", "color"), ("roof", "material")):
        assert ap[sec][fld]["value"] is not None
        assert ap[sec][fld]["class"] == "PROCEDURAL"
    assert ap["style_family"]["value"].endswith(("glass_curtain", "concrete", "metal_panel"))
    assert ap["style_family"]["class"] == "DERIVED"


def test_spatial_continuity():
    """Neighbouring residential buildings are generally coherent (no dramatic
    per-parcel colour thrash); distant ones vary more. Measured statistically
    over many pairs, since a continuous field has occasional colourway
    boundaries."""
    import statistics

    def fac(x, z):
        return inf.infer_building(0, f"k{x:.1f}_{z:.1f}", x, z,
                                  "DETACHED_RESIDENTIAL", _blank(), seed=9
                                  )["facade"]["color"]["value"]
    near_deltas, far_deltas = [], []
    for i in range(60):
        x = 400.0 + 11.0 * i
        z = 400.0 + 7.0 * i
        near_deltas.append(_cdist(fac(x, z), fac(x + 9.0, z)))     # ~9 m apart
        far_deltas.append(_cdist(fac(x, z), fac(x + 900.0, z + 700.0)))
    mean_near = statistics.mean(near_deltas)
    mean_far = statistics.mean(far_deltas)
    assert mean_near < 25, f"neighbours not coherent (mean {mean_near:.1f})"
    assert mean_far > mean_near * 1.5, f"no distance variety ({mean_far:.1f} vs {mean_near:.1f})"


def test_unknown_archetype_is_fallback_procedural():
    ap = inf.infer_building(0, "kx", 0.0, 0.0, "NOT_A_REAL_ARCH", _blank(), seed=1)
    assert ap["facade"]["color"]["class"] == "PROCEDURAL"
    assert ap["style_family"]["class"] == "PROCEDURAL"

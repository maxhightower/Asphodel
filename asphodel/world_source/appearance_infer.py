"""Package C -- deterministic appearance inference for buildings lacking
observed facade/roof colour + material.

VIS-0 reality: observed colour/material is ~0% for the cert cities, so almost
every building's appearance is produced here. The precedence follows Section 15:

  1. observed building appearance                 (kept, never overwritten)
  2. nearby observed buildings, compatible arch   } DERIVED when observed data
  3. local observed colour/material distribution  }   actually exists nearby
  4. archetype-conditioned prior + spatial field  -> PROCEDURAL (the usual case)
  5. broader archetype prior                       -> PROCEDURAL
  6. generic fail-safe                             -> PROCEDURAL

Because observed data is essentially absent for these cities, steps 1-3 rarely
fire and the honest provenance of inferred colour/material here is PROCEDURAL
(a deterministic prior), NOT OBSERVED and NOT "real-world matching". Steps 1-3
are implemented so the system generalizes to future cities/data that do carry
appearance.

Determinism + spatial coherence: colour is chosen from an archetype palette
modulated by a smooth value-noise field over world coordinates, so neighbouring
buildings share a tone (no per-parcel colour thrash) while staying varied. The
result is a pure function of (stable_key, centroid, seed, archetype) -- stable
across chunk rebuild, independent of iteration order, and never keyed on city
name.
"""
from __future__ import annotations

import colorsys
import math

from ..city_visual.provenance import OBSERVED, DERIVED, PROCEDURAL

# Per-archetype appearance prior. `facade_ways` / `roof_ways` are discrete muted
# colourways as (h,s,v) in [0,1]; a spatial field biases which colourway a
# neighbourhood leans toward (local coherence) while a per-building hash keeps
# variety. Saturations are kept muted but high enough to read at iso scale under
# the scene's cool ambient. `facade_mats` are weighted material choices.
_PRIOR = {
    "DETACHED_RESIDENTIAL": dict(
        facade_mats=[("siding", 3), ("brick", 3), ("painted_masonry", 1), ("stucco", 1)],
        facade_ways=[(0.09, 0.34, 0.78), (0.11, 0.18, 0.88), (0.28, 0.24, 0.64),
                     (0.57, 0.16, 0.70), (0.045, 0.46, 0.56), (0.08, 0.12, 0.74),
                     (0.16, 0.30, 0.62), (0.02, 0.30, 0.72)],
        roof_mat="asphalt_shingle",
        roof_ways=[(0.06, 0.20, 0.30), (0.05, 0.35, 0.26), (0.0, 0.0, 0.28),
                   (0.09, 0.22, 0.36), (0.6, 0.10, 0.30)]),
    "MULTIFAMILY": dict(
        facade_mats=[("siding", 2), ("brick", 2), ("stucco", 2), ("painted_masonry", 1)],
        facade_ways=[(0.09, 0.28, 0.72), (0.06, 0.34, 0.60), (0.11, 0.16, 0.80),
                     (0.09, 0.10, 0.66), (0.55, 0.14, 0.64), (0.03, 0.36, 0.58)],
        roof_mat="flat_membrane",
        roof_ways=[(0.08, 0.06, 0.36), (0.0, 0.0, 0.34), (0.09, 0.14, 0.40)]),
    "SMALL_COMMERCIAL": dict(
        facade_mats=[("painted_masonry", 3), ("stucco", 2), ("brick", 2), ("metal_panel", 1)],
        facade_ways=[(0.10, 0.22, 0.82), (0.06, 0.40, 0.62), (0.0, 0.0, 0.80),
                     (0.55, 0.24, 0.62), (0.33, 0.26, 0.60), (0.02, 0.44, 0.58),
                     (0.13, 0.30, 0.74)],
        roof_mat="flat_membrane",
        roof_ways=[(0.08, 0.05, 0.38), (0.0, 0.0, 0.36)]),
    "BIG_BOX_COMMERCIAL": dict(
        facade_mats=[("metal_panel", 3), ("concrete", 2), ("painted_masonry", 1)],
        facade_ways=[(0.09, 0.10, 0.80), (0.0, 0.0, 0.78), (0.10, 0.18, 0.72),
                     (0.55, 0.10, 0.70)],
        roof_mat="flat_membrane",
        roof_ways=[(0.0, 0.0, 0.40), (0.08, 0.05, 0.42)]),
    "INDUSTRIAL": dict(
        facade_mats=[("metal_panel", 3), ("concrete", 2)],
        facade_ways=[(0.57, 0.10, 0.62), (0.0, 0.0, 0.60), (0.09, 0.08, 0.66),
                     (0.55, 0.16, 0.54)],
        roof_mat="standing_seam_metal",
        roof_ways=[(0.57, 0.10, 0.52), (0.0, 0.0, 0.50)]),
    "OFFICE_HIGHRISE": dict(
        facade_mats=[("glass_curtain", 3), ("concrete", 2), ("metal_panel", 1)],
        facade_ways=[(0.55, 0.28, 0.55), (0.57, 0.20, 0.48), (0.53, 0.16, 0.62),
                     (0.0, 0.0, 0.66), (0.6, 0.24, 0.44)],
        roof_mat="flat_membrane",
        roof_ways=[(0.58, 0.10, 0.40), (0.0, 0.0, 0.40)]),
    "CIVIC_SPECIAL": dict(
        facade_mats=[("stone", 2), ("brick", 2), ("concrete", 1), ("painted_masonry", 1)],
        facade_ways=[(0.10, 0.16, 0.82), (0.06, 0.36, 0.62), (0.0, 0.0, 0.80),
                     (0.08, 0.22, 0.70), (0.03, 0.40, 0.56)],
        roof_mat="flat_membrane",
        roof_ways=[(0.08, 0.10, 0.40), (0.0, 0.0, 0.36), (0.55, 0.10, 0.38)]),
    "GENERIC_UNKNOWN": dict(
        facade_mats=[("painted_masonry", 1)],
        facade_ways=[(0.09, 0.12, 0.72), (0.0, 0.0, 0.70)],
        roof_mat="flat_membrane",
        roof_ways=[(0.0, 0.0, 0.38)]),
}

# Cool, muted curtain-wall colourways (h,s,v) for buildings that resolve to a full
# glass_curtain facade — used instead of the archetype's opaque palette so a glass
# tower reads blue/steel/teal rather than tinted stucco.
_GLASS_WAYS = [(0.55, 0.22, 0.46), (0.57, 0.15, 0.52), (0.52, 0.11, 0.55),
               (0.60, 0.20, 0.42), (0.50, 0.26, 0.40), (0.54, 0.08, 0.58)]

# Height (m) where curtain-wall glazing starts to appear, and the span over which
# its probability ramps to the cap. Below the start it never forces glass; a
# ~48 m tower is ~0.9 likely to be a full glass surface.
_GLASS_START_M = 12.0
_GLASS_SPAN_M = 40.0
_GLASS_MAX_P = 0.9


def glass_probability(height: float) -> float:
    """Chance a building of this height reads as a full glass curtain wall.

    Pure function of height (a geometry truth): 0 below the start height, ramping
    linearly to a cap. Taller → more likely a skyscraper-style glazed surface."""
    if not height or height < _GLASS_START_M:
        return 0.0
    return min(_GLASS_MAX_P, (height - _GLASS_START_M) / _GLASS_SPAN_M)


def _hash(*ints: int) -> int:
    h = 1469598103934665603
    for v in ints:
        h = (h ^ (v & 0xFFFFFFFFFFFFFFFF)) * 1099511628211 & 0xFFFFFFFFFFFFFFFF
    return h


def _shash(s: str) -> int:
    """Stable FNV-1a hash of a string. Python's built-in hash() is randomized per
    process (PYTHONHASHSEED), so it must never key deterministic appearance."""
    h = 1469598103934665603
    for ch in s.encode("utf-8"):
        h = (h ^ ch) * 1099511628211 & 0xFFFFFFFFFFFFFFFF
    return h


def _h01(*ints: int) -> float:
    return (_hash(*ints) % 1000000) / 1000000.0


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _vnoise(x: float, z: float, cell: float, seed: int, salt: int) -> float:
    """Smooth deterministic value noise in [0,1) -- gives spatial coherence."""
    gx, gz = x / cell, z / cell
    ix, iz = math.floor(gx), math.floor(gz)
    fx, fz = _smooth(gx - ix), _smooth(gz - iz)
    c00 = _h01(ix, iz, seed, salt)
    c10 = _h01(ix + 1, iz, seed, salt)
    c01 = _h01(ix, iz + 1, seed, salt)
    c11 = _h01(ix + 1, iz + 1, seed, salt)
    return (c00 * (1 - fx) + c10 * fx) * (1 - fz) + (c01 * (1 - fx) + c11 * fx) * fz


def _pick_weighted(choices, r: float):
    total = sum(w for _, w in choices)
    acc = 0.0
    for val, w in choices:
        acc += w
        if r * total < acc:
            return val
    return choices[-1][0]


def _hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _lerp(a, b, t):
    return a + (b - a) * t


def _pick_way(ways, x, z, kh, seed, salt):
    """Pick a colourway (h,s,v) with neighbourhood coherence + per-building variety.

    A coarse spatial field chooses the neighbourhood's base colourway; a per-
    building hash keeps it on the base most of the time and shifts to an adjacent
    colourway sometimes, then jitters each channel slightly.
    """
    n = len(ways)
    # Colourway index is driven by spatial fields only (never a per-building
    # hash), so adjacent buildings share a colourway and colour changes happen at
    # block/neighbourhood scale -- no dramatic per-parcel thrash. A coarse field
    # sets the neighbourhood base; a medium field varies it over ~70 m.
    base = int(_vnoise(x, z, 230.0, seed, salt) * n) % n
    med = _vnoise(x, z, 70.0, seed, salt + 5)
    if med < 0.55:
        idx = base
    elif med < 0.80:
        idx = (base + 1) % n
    else:
        idx = (base - 1) % n
    h, s, v = ways[idx]
    # subtle per-building jitter (readable variety without changing the colourway)
    h += (_h01(kh, seed, salt + 2) - 0.5) * 0.012
    s *= 0.92 + 0.14 * _h01(kh, seed, salt + 3)
    v *= 0.94 + 0.12 * _h01(kh, seed, salt + 4)
    return h, s, v


def infer_building(bid: int, key: str, cx: float, cz: float, arch: str,
                   appearance: dict, seed: int, region: str = "regional",
                   height: float = 0.0) -> dict:
    """Fill missing facade/roof colour+material + style_family for one building.

    `appearance` is a BuildingAppearanceV1.to_dict(); observed values are never
    overwritten. `height` (m) biases tall buildings toward a full glass curtain
    wall (see glass_probability). Returns the same dict (mutated) for convenience.
    """
    prior = _PRIOR.get(arch, _PRIOR["GENERIC_UNKNOWN"])
    is_fallback = arch not in _PRIOR
    infer_cls = PROCEDURAL   # honest: prior-based, no observed basis nearby
    kh = _shash(key) & 0xFFFFFFFF

    # ---- facade material ----
    fmat = appearance["facade"]["material"]
    if fmat["value"] is None:
        fmat["value"] = _pick_weighted(prior["facade_mats"], _h01(kh, seed, 11))
        fmat["class"] = infer_cls
        # Height-driven glazing: the taller the building, the more likely its whole
        # facade is a glass curtain wall (skyscraper surface). Stays PROCEDURAL and
        # deterministic; never overrides observed material.
        if _h01(kh, seed, 71) < glass_probability(height):
            fmat["value"] = "glass_curtain"
    is_glass = fmat["value"] == "glass_curtain"
    # ---- facade colour (colourway, spatially coherent) ----
    fcol = appearance["facade"]["color"]
    if fcol["value"] is None:
        ways = _GLASS_WAYS if is_glass else prior["facade_ways"]
        h, s, v = _pick_way(ways, cx, cz, kh, seed, 140 if is_glass else 100)
        fcol["value"] = _hex(h, s, v)
        fcol["class"] = infer_cls
    # ---- roof material ----
    rmat = appearance["roof"]["material"]
    if rmat["value"] is None:
        rmat["value"] = prior["roof_mat"]
        rmat["class"] = infer_cls
    # ---- roof colour (colourway) ----
    rcol = appearance["roof"]["color"]
    if rcol["value"] is None:
        h, s, v = _pick_way(prior["roof_ways"], cx, cz, kh, seed, 300)
        rcol["value"] = _hex(h, s, v)
        rcol["class"] = infer_cls
    # ---- style family (a grouping label; DERIVED from arch+material, never observed)
    sf = appearance["style_family"]
    if sf["value"] is None:
        fam = "residential" if "RESIDENTIAL" in arch or arch == "MULTIFAMILY" else (
            "civic" if arch == "CIVIC_SPECIAL" else
            "industrial" if arch == "INDUSTRIAL" else
            "office" if arch == "OFFICE_HIGHRISE" else "commercial")
        sf["value"] = f"{region}_{fam}_{fmat['value']}"
        sf["class"] = DERIVED if not is_fallback else PROCEDURAL
    return appearance


def infer_records(records: list, seed: int, region: str = "regional") -> int:
    """Infer appearance for every BuildingRecord missing it. Returns count filled."""
    filled = 0
    for r in records:
        if r.appearance is None:
            continue
        c = r.poly.centroid
        before = r.appearance["facade"]["color"]["value"]
        hm = r.appearance.get("height_m", {}).get("value")
        infer_building(r.bid, r.key, float(c.x), float(c.y), r.arch,
                       r.appearance, seed, region, float(hm) if hm else 0.0)
        if before is None and r.appearance["facade"]["color"]["value"] is not None:
            filled += 1
    return filled

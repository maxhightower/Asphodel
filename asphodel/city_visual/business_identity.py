"""Package H -- deterministic fictional business identity.

Non-residential buildings get a *business identity*: a fictional (never
trademarked) name, a category from a fixed taxonomy, a sign palette, a logo
glyph, a sign family and opening hours. The same identity is meant to inform
several downstream systems (exterior signage, building function, workers,
schedules, interior grammar, loot expectations) -- Package H establishes the
data contract + exterior signage; later work can read the rest.

Honesty (Section: provenance): a generated identity is invented, so its
provenance is always PROCEDURAL. Nothing here is ever labelled OBSERVED. Real
public place names could be adopted in future *only* where the data/licensing
pipeline already permits them (Section 9); V1 does not, to stay clear of real
trademarks -- and generated names are rotated away from a curated blocklist of
well-known real brands so a random draw can never coincide with one.

Determinism + spatial coherence: everything is a pure function of
(stable_key, centroid, archetype, seed). A coarse spatial field nudges palette
hue so a commercial strip shares a tone; a per-building hash keeps names and
glyphs varied. Stable across chunk rebuild, independent of iteration order,
never keyed on city name.
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field
from typing import Optional

from .provenance import PROCEDURAL

# ---- fixed vocabularies -----------------------------------------------------

BUSINESS_CATEGORIES = (
    "hardware_store", "grocery", "pharmacy", "diner", "cafe", "bakery",
    "barber", "laundromat", "auto_parts", "clothing", "bank", "gas_station",
    "dollar_store", "restaurant",
    "big_box", "home_improvement", "department_store", "electronics",
    "law_office", "insurance", "consulting", "tech_office", "medical_office",
    "fabrication", "distribution", "machine_shop", "cold_storage",
    "clinic", "city_office", "place_of_worship", "library", "school",
    "fire_station", "post_office",
)

SIGN_FAMILIES = (
    "storefront_fascia", "wall_sign", "pole_sign", "monument_sign",
    "hanging_sign", "roadside_sign", "directory_sign", "building_number",
)

LOGO_GLYPHS = (
    "disc", "square", "triangle", "diamond", "chevron", "cross", "ring",
    "bars", "star", "arch",
)

# ---- archetype -> weighted category pool ------------------------------------
# Keyed on BUILDING_ARCHETYPES (world_source grammar). Residential archetypes
# have no business identity and are absent here.
_ARCH_CATEGORIES = {
    "SMALL_COMMERCIAL": [
        ("grocery", 3), ("diner", 3), ("cafe", 2), ("pharmacy", 2),
        ("hardware_store", 2), ("barber", 2), ("bakery", 2), ("laundromat", 2),
        ("auto_parts", 2), ("clothing", 2), ("bank", 1), ("gas_station", 2),
        ("dollar_store", 2), ("restaurant", 3),
    ],
    "BIG_BOX_COMMERCIAL": [
        ("big_box", 4), ("home_improvement", 3), ("department_store", 2),
        ("electronics", 2), ("grocery", 2),
    ],
    "OFFICE_HIGHRISE": [
        ("law_office", 2), ("insurance", 2), ("consulting", 2),
        ("tech_office", 2), ("medical_office", 2), ("bank", 1),
    ],
    "INDUSTRIAL": [
        ("fabrication", 3), ("distribution", 3), ("machine_shop", 2),
        ("cold_storage", 2),
    ],
    "CIVIC_SPECIAL": [
        ("clinic", 2), ("city_office", 2), ("place_of_worship", 2),
        ("library", 1), ("school", 2), ("fire_station", 1), ("post_office", 1),
    ],
    "GENERIC_UNKNOWN": [
        ("consulting", 1), ("distribution", 1), ("restaurant", 1),
    ],
}

# category -> sign family bias (which hardware suits the business)
_CATEGORY_SIGN = {
    "big_box": "pole_sign", "home_improvement": "pole_sign",
    "department_store": "pole_sign", "electronics": "pole_sign",
    "gas_station": "pole_sign",
    "grocery": "monument_sign", "auto_parts": "monument_sign",
    "bank": "monument_sign", "dollar_store": "monument_sign",
    "fabrication": "monument_sign", "distribution": "monument_sign",
    "machine_shop": "monument_sign", "cold_storage": "monument_sign",
    "clinic": "monument_sign", "medical_office": "monument_sign",
    "law_office": "wall_sign", "insurance": "wall_sign",
    "consulting": "wall_sign", "tech_office": "wall_sign",
    "city_office": "wall_sign", "post_office": "wall_sign",
    "place_of_worship": "wall_sign", "library": "wall_sign",
    "school": "monument_sign", "fire_station": "wall_sign",
}

# ---- fictional name material ------------------------------------------------
# Generic surnames + region-flavoured adjectives; nothing here is a real brand.
_SURNAMES = (
    "Henderson", "Marsh", "Delgado", "Novak", "Okafor", "Bautista", "Voss",
    "Kranz", "Halloran", "Ibarra", "Whitaker", "Ballard", "Cormier",
    "Nakamura", "Ruiz", "Ellison", "Pruitt", "Danforth", "Yates", "Sokolov",
    "Calloway", "Ashby", "Mercer", "Okonkwo", "Prentiss", "Vance", "Hargrove",
    "Salcedo", "Beckman", "Thornton", "Reyes", "Kowalski", "Abernathy",
    "Fontaine", "Guthrie", "Lindqvist", "Alvarado", "Pemberton", "Rourke",
    "Sandoval",
)
_ADJECTIVES = (
    "Lone Star", "Sunbelt", "Bayou", "Gulf", "Prairie", "Riverside",
    "Meridian", "Ironwood", "Redbud", "Cypress", "Summit", "Oakhaven",
    "Junction", "Frontier", "Cardinal", "Bluebonnet", "Pecan", "Magnolia",
    "Crosstown", "Highland", "Silverline", "Copperfield", "Brazos", "Comal",
)
# per-category nouns; the first is the plainest, later ones add variety.
_NOUNS = {
    "hardware_store": ("Hardware", "Supply Co.", "Hardware & Tool"),
    "grocery": ("Grocery", "Market", "Food Mart", "Grocers"),
    "pharmacy": ("Pharmacy", "Drug Co.", "Apothecary"),
    "diner": ("Diner", "Grill", "Kitchen"),
    "cafe": ("Coffee", "Cafe", "Roasters"),
    "bakery": ("Bakery", "Bread Co.", "Pastry"),
    "barber": ("Barbers", "Barber Shop", "Cuts"),
    "laundromat": ("Laundry", "Wash House", "Cleaners"),
    "auto_parts": ("Auto Parts", "Auto Supply", "Motors"),
    "clothing": ("Apparel", "Clothiers", "Outfitters"),
    "bank": ("Savings", "Trust", "Credit Union"),
    "gas_station": ("Fuel", "Gas & Go", "Service Station"),
    "dollar_store": ("Discount", "Value Store", "Bargain Mart"),
    "restaurant": ("Restaurant", "Eatery", "Bistro"),
    "big_box": ("Superstore", "Warehouse", "Mega Mart"),
    "home_improvement": ("Home Center", "Building Supply", "Improvement Co."),
    "department_store": ("Department Store", "Mercantile", "Outfitters"),
    "electronics": ("Electronics", "Tech Store", "Digital"),
    "law_office": ("Law", "Legal Group", "& Associates"),
    "insurance": ("Insurance", "Assurance", "Coverage"),
    "consulting": ("Consulting", "Advisors", "Group"),
    "tech_office": ("Systems", "Technologies", "Labs"),
    "medical_office": ("Medical", "Clinic", "Health Partners"),
    "fabrication": ("Fabrication", "Manufacturing", "Works"),
    "distribution": ("Distribution", "Logistics", "Freight"),
    "machine_shop": ("Machine", "Machining", "Tool & Die"),
    "cold_storage": ("Cold Storage", "Refrigerated", "Freight"),
    "clinic": ("Clinic", "Health Center", "Family Practice"),
    "city_office": ("Municipal Office", "City Services", "Administration"),
    "place_of_worship": ("Chapel", "Fellowship", "Community Church"),
    "library": ("Public Library", "Library", "Reading Room"),
    "school": ("School", "Academy", "Learning Center"),
    "fire_station": ("Fire Station", "Fire & Rescue", "Engine Co."),
    "post_office": ("Post Office", "Postal Station", "Mail Center"),
}

# Curated set of well-known real brands (normalized) a generated name must never
# coincide with. The generator rotates candidates until one clears this set, so
# the no-trademark test is a guarantee, not a hope.
REAL_BRAND_BLOCKLIST = frozenset({
    "home depot", "walmart", "target", "costco", "kroger", "heb", "safeway",
    "whole foods", "best buy", "circle k", "dollar general", "family dollar",
    "dollar tree", "cvs", "walgreens", "rite aid", "starbucks", "mcdonalds",
    "wendys", "subway", "chase", "wells fargo", "bank of america", "citibank",
    "sterling bank", "frost bank", "exxon", "shell", "chevron", "valero",
    "autozone", "oreilly", "napa", "lowes", "ace hardware", "true value",
    "aldi", "trader joes", "publix", "sams club", "ikea", "fedex", "ups",
    "amazon", "google", "apple", "microsoft", "usps",
})


# ---- deterministic hashing (matches appearance_infer style) -----------------

def _hash(*ints: int) -> int:
    h = 1469598103934665603
    for v in ints:
        h = (h ^ (v & 0xFFFFFFFFFFFFFFFF)) * 1099511628211 & 0xFFFFFFFFFFFFFFFF
    return h


def _shash(s: str) -> int:
    """Stable FNV-1a hash of a string. NEVER use Python's built-in hash() for a
    stable key -- it is randomized per process (PYTHONHASHSEED) and would make
    identity non-deterministic across compiles."""
    h = 1469598103934665603
    for ch in s.encode("utf-8"):
        h = (h ^ ch) * 1099511628211 & 0xFFFFFFFFFFFFFFFF
    return h


def _h01(*ints: int) -> float:
    return (_hash(*ints) % 1000000) / 1000000.0


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _vnoise(x: float, z: float, cell: float, seed: int, salt: int) -> float:
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


def _norm(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum() or c == " ").strip()


# Per-category sign hue family (base hue in [0,1]); palette is built around it.
_CATEGORY_HUE = {
    "hardware_store": 0.06, "grocery": 0.32, "pharmacy": 0.55, "diner": 0.02,
    "cafe": 0.09, "bakery": 0.08, "barber": 0.58, "laundromat": 0.53,
    "auto_parts": 0.60, "clothing": 0.86, "bank": 0.36, "gas_station": 0.02,
    "dollar_store": 0.13, "restaurant": 0.03,
    "big_box": 0.58, "home_improvement": 0.09, "department_store": 0.80,
    "electronics": 0.62, "law_office": 0.60, "insurance": 0.57,
    "consulting": 0.55, "tech_office": 0.63, "medical_office": 0.52,
    "fabrication": 0.09, "distribution": 0.58, "machine_shop": 0.07,
    "cold_storage": 0.56, "clinic": 0.50, "city_office": 0.58,
    "place_of_worship": 0.11, "library": 0.07, "school": 0.60,
    "fire_station": 0.02, "post_office": 0.62,
}

# category -> (open_hour, close_hour) 24h
_CATEGORY_HOURS = {
    "diner": (6, 22), "cafe": (6, 20), "bakery": (6, 18), "restaurant": (11, 23),
    "grocery": (7, 22), "pharmacy": (8, 21), "gas_station": (5, 24),
    "big_box": (8, 22), "home_improvement": (6, 21), "department_store": (10, 21),
    "electronics": (10, 21), "dollar_store": (9, 21), "clothing": (10, 20),
    "hardware_store": (7, 19), "auto_parts": (8, 20), "barber": (9, 19),
    "laundromat": (6, 22), "bank": (9, 17),
    "law_office": (9, 17), "insurance": (9, 17), "consulting": (9, 18),
    "tech_office": (9, 18), "medical_office": (8, 17), "clinic": (8, 18),
    "fabrication": (7, 17), "distribution": (0, 24), "machine_shop": (7, 17),
    "cold_storage": (0, 24), "city_office": (8, 17), "place_of_worship": (7, 21),
    "library": (9, 20), "school": (7, 16), "fire_station": (0, 24),
    "post_office": (8, 18),
}

RESIDENTIAL_ARCHS = ("DETACHED_RESIDENTIAL", "MULTIFAMILY")


@dataclass
class BusinessIdentityV1:
    business_id: str
    category: str
    display_name: str
    palette: dict = field(default_factory=dict)   # primary/secondary/accent hex
    logo_glyph: str = "disc"
    sign_family: str = "wall_sign"
    hours: dict = field(default_factory=dict)      # {open,close}
    provenance: str = PROCEDURAL                   # invented -> always PROCEDURAL

    def to_dict(self) -> dict:
        return {
            "business_id": self.business_id, "category": self.category,
            "display_name": self.display_name, "palette": dict(self.palette),
            "logo_glyph": self.logo_glyph, "sign_family": self.sign_family,
            "hours": dict(self.hours), "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BusinessIdentityV1":
        return cls(
            business_id=d["business_id"], category=d["category"],
            display_name=d["display_name"], palette=dict(d.get("palette", {})),
            logo_glyph=d.get("logo_glyph", "disc"),
            sign_family=d.get("sign_family", "wall_sign"),
            hours=dict(d.get("hours", {})),
            provenance=d.get("provenance", PROCEDURAL))

    def validate(self, where: str = "") -> list:
        w = where or f"business {self.business_id}"
        errs = []
        if self.category not in BUSINESS_CATEGORIES:
            errs.append(f"{w}: bad category {self.category!r}")
        if self.sign_family not in SIGN_FAMILIES:
            errs.append(f"{w}: bad sign_family {self.sign_family!r}")
        if self.logo_glyph not in LOGO_GLYPHS:
            errs.append(f"{w}: bad logo_glyph {self.logo_glyph!r}")
        if self.provenance != PROCEDURAL:
            errs.append(f"{w}: invented identity must be PROCEDURAL, got {self.provenance!r}")
        if not self.display_name.strip():
            errs.append(f"{w}: empty display_name")
        if _norm(self.display_name) in REAL_BRAND_BLOCKLIST:
            errs.append(f"{w}: display_name {self.display_name!r} collides with a real brand")
        for k in ("primary", "secondary", "accent"):
            v = self.palette.get(k, "")
            if not (isinstance(v, str) and len(v) == 7 and v[0] == "#"):
                errs.append(f"{w}: palette.{k} not a #rrggbb hex ({v!r})")
        return errs


def _make_name(category: str, kh: int, seed: int) -> str:
    """Deterministic fictional name; rotates candidates past the brand blocklist."""
    nouns = _NOUNS.get(category, ("Company",))
    si = _hash(kh, seed, 71) % len(_SURNAMES)
    ai = _hash(kh, seed, 73) % len(_ADJECTIVES)
    ni = _hash(kh, seed, 79) % len(nouns)
    pattern = _hash(kh, seed, 83) % 4
    for attempt in range(8):
        s = _SURNAMES[(si + attempt) % len(_SURNAMES)]
        s2 = _SURNAMES[(si + attempt + 7) % len(_SURNAMES)]
        adj = _ADJECTIVES[(ai + attempt) % len(_ADJECTIVES)]
        noun = nouns[(ni + attempt) % len(nouns)]
        p = (pattern + attempt) % 4
        if category in ("law_office", "consulting", "insurance") and p in (0, 1):
            name = f"{s} & {s2}"
            if noun not in ("& Associates",):
                name = f"{s} & {s2} {noun}" if p == 0 else f"{s}, {s2} {noun}"
        elif p == 0:
            name = f"{s} {noun}"
        elif p == 1:
            name = f"{adj} {noun}"
        elif p == 2:
            name = f"{s}'s {noun}"
        else:
            name = f"{adj} {noun} Co." if not noun.endswith("Co.") else f"{adj} {noun}"
        if _norm(name) not in REAL_BRAND_BLOCKLIST:
            return name
    return f"{_SURNAMES[si]} {nouns[0]}"   # exhausted (practically unreachable)


def infer_business(bid: int, key: str, cx: float, cz: float, arch: str,
                   seed: int) -> Optional[BusinessIdentityV1]:
    """Deterministic fictional business identity for a non-residential building,
    or None for residential/unknown-without-pool archetypes."""
    if arch in RESIDENTIAL_ARCHS:
        return None
    pool = _ARCH_CATEGORIES.get(arch)
    if not pool:
        return None
    kh = _shash(key) & 0xFFFFFFFF
    category = _pick_weighted(pool, _h01(kh, seed, 3))

    base_hue = _CATEGORY_HUE.get(category, 0.58)
    # coarse spatial field nudges hue so a strip shares a family; per-building
    # hash sets saturation/value so neighbours still differ.
    hue = base_hue + (_vnoise(cx, cz, 180.0, seed, 9) - 0.5) * 0.05
    sat = 0.52 + 0.20 * _h01(kh, seed, 21)
    val = 0.72 + 0.16 * _h01(kh, seed, 23)
    primary = _hex(hue, sat, val)
    secondary = _hex(hue, sat * 0.55, min(1.0, val * 1.12))
    accent = _hex((hue + 0.5) % 1.0, min(0.9, sat + 0.25), min(1.0, val * 1.05))
    palette = {"primary": primary, "secondary": secondary, "accent": accent}

    glyph = LOGO_GLYPHS[_hash(kh, seed, 41) % len(LOGO_GLYPHS)]
    sign_family = _CATEGORY_SIGN.get(category, "wall_sign")
    open_h, close_h = _CATEGORY_HOURS.get(category, (9, 18))
    name = _make_name(category, kh, seed)

    return BusinessIdentityV1(
        business_id=f"biz_{kh:08x}",
        category=category, display_name=name, palette=palette,
        logo_glyph=glyph, sign_family=sign_family,
        hours={"open": open_h, "close": close_h}, provenance=PROCEDURAL)


def assign_records(records: list, seed: int) -> int:
    """Attach a business identity dict to every non-residential BuildingRecord.

    Sets ``rec.identity`` (dict) in place; leaves residential records untouched.
    Returns the number of identities assigned.
    """
    n = 0
    for r in records:
        biz = infer_business(r.bid, r.key, float(r.poly.centroid.x),
                             float(r.poly.centroid.y), r.arch, seed)
        if biz is not None:
            r.identity = biz.to_dict()
            n += 1
    return n

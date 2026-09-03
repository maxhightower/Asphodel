"""ResidentialArchitectureV1 -- compiled architectural identity of one house.

This is the contract that lets *Python decide what a house is* and *Godot render
that decision*. It is the residential companion to BuildingAppearanceV1: where
appearance carries facade/roof colour+material with provenance, this carries the
architectural grammar -- era, form, style, massing, roof family, multi-material
facade regions, porch, windows, foundation, parking, and later modifications --
so the renderer never re-rolls whether a house is Craftsman, has a porch, etc.

Core principle: FORM and STYLE are independent axes. A BUNGALOW can be CRAFTSMAN
or FOLK_NATIONAL; a FOURSQUARE can be AMERICAN_FOURSQUARE or COLONIAL_REVIVAL.
That independence is what produces combinatorial diversity from a small grammar.

Provenance (reuses OBSERVED/DERIVED/PROCEDURAL):
  * era     -- OBSERVED/DERIVED when a real construction year exists, else the
               cohort prior => PROCEDURAL.
  * form    -- DERIVED: follows from the observed footprint morphology + floors.
  * style   -- PROCEDURAL: chosen from the neighbourhood cohort prior. Never
               OBSERVED (a source almost never states architectural style).
Everything downstream of form/style (roof, porch, windows, ...) is PROCEDURAL
grammar unless it echoes an observed value (observed roof_shape, observed
facade material), in which case the echoed field is provenanced accordingly.

The whole record is versioned, JSON-serialisable, validated, and optional: it is
attached only to DETACHED_RESIDENTIAL buildings; everything else omits it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .provenance import PROVENANCE_CLASSES

RESIDENTIAL_ARCH_VERSION = 1

# --------------------------------------------------------------------------
# Vocabulary (first-wave). Each tuple is the closed enum the validator checks.
# Renderers map every member; unknown members are a hard validation error so the
# serialized contract can never silently drift.
# --------------------------------------------------------------------------

ERAS = (
    "PRE_1900", "1900_1919", "1920_1939", "1940_1959",
    "1960_1979", "1980_1999", "2000_2014", "2015_PLUS", "UNKNOWN",
)

# Structural/massing form -- what shape of house, independent of decoration.
FORMS = (
    "FOLK_COTTAGE", "BUNGALOW", "FOURSQUARE", "VICTORIAN_IRREGULAR",
    "TUDOR_COTTAGE", "REVIVAL_TWO_STORY", "MINIMAL_TRADITIONAL",
    "LINEAR_RANCH", "L_RANCH", "U_RANCH", "SUBURBAN_TWO_STORY",
    "CONTEMPORARY_COMPACT",
    # reserved for later waves (kept in the enum so bundles stay forward-valid)
    "SHOTGUN", "PATIO_HOME", "SPLIT_LEVEL", "COURTYARD", "TOWNHOUSE",
)

# Architectural style -- the decorative/compositional grammar laid over a form.
STYLES = (
    "CRAFTSMAN", "FOLK_NATIONAL", "FOLK_VICTORIAN", "QUEEN_ANNE",
    "AMERICAN_FOURSQUARE", "COLONIAL_REVIVAL", "TUDOR_REVIVAL",
    "MINIMAL_TRADITIONAL", "TRADITIONAL_RANCH", "MID_CENTURY_MODERN",
    "TEXAS_NEO_TRADITIONAL", "SPANISH_ECLECTIC",
    # reserved for later waves
    "PRAIRIE", "FRENCH_ECLECTIC", "SHOTGUN_VERNACULAR", "1970S_CONTEMPORARY",
    "NEO_CRAFTSMAN", "MODERN_FARMHOUSE", "CONTEMPORARY_INFILL",
    "MEDITERRANEAN_SUBURBAN",
)

ROOF_FAMILIES = (
    "FRONT_GABLE", "SIDE_GABLE", "CROSS_GABLE", "HIP", "CROSS_HIP",
    "COMPLEX_HIP_GABLE", "LOW_GABLE", "LOW_HIP", "SHED_COMPOSITE", "FLAT",
)
PITCH_CLASSES = ("VERY_LOW", "LOW", "MEDIUM", "STEEP")
EAVE_CLASSES = ("TIGHT", "NORMAL", "WIDE", "VERY_WIDE")

FOUNDATIONS = ("RAISED_PIER_BEAM", "LOW_CRAWLSPACE", "SLAB_ON_GRADE")

STORY_PROFILES = ("ONE", "ONE_HALF", "TWO", "SPLIT")
SYMMETRY_MODES = ("SYMMETRIC", "NEAR_SYMMETRIC", "ASYMMETRIC")
HORIZONTAL_EMPHASIS = ("LOW", "MEDIUM", "HIGH")

PORCH_FAMILIES = (
    "NONE", "STOOP", "PARTIAL_FRONT", "FULL_WIDTH", "PROJECTING_GABLE",
    "RECESSED", "WRAP_PARTIAL",
)
PORCH_SUPPORTS = (
    "NONE", "SIMPLE_POST", "TAPERED_POST", "TAPERED_POST_BRICK_PIER",
    "PAIRED_POST", "CLASSICAL_SIMPLE", "MCM_THIN", "MCM_SLANTED",
)

WINDOW_GRAMMARS = (
    "SIMPLE_VERTICAL", "CRAFTSMAN_GROUPED", "VICTORIAN_ASYMMETRIC",
    "FOURSQUARE_REGULAR", "COLONIAL_SYMMETRIC", "TUDOR_GROUPED_VERTICAL",
    "RANCH_PICTURE", "MCM_HORIZONTAL", "SUBURBAN_REGULAR",
)

PARKING_FAMILIES = (
    "NONE", "SIDE_DRIVE", "ATTACHED_FRONT_ONE", "ATTACHED_FRONT_TWO",
    "ATTACHED_SIDE", "INTEGRATED_ONE", "INTEGRATED_TWO", "CARPORT",
    "DETACHED_REAR_OBSERVED",
)

# Residential facade material subtypes. Each maps onto a shared physical shader
# family (FACADE_MATERIALS in building_appearance) so the renderer never grows a
# per-subtype shader -- subtype only steers colour/detailing.
FACADE_SUBTYPES = (
    "wood_lap", "fiber_cement_lap", "board_and_batten", "wood_shingle",
    "red_brick", "buff_brick", "dark_brick", "painted_brick",
    "stone_veneer", "smooth_stucco", "metal_panel", "none",
)
FACADE_SUBTYPE_TO_FAMILY = {
    "wood_lap": "siding", "fiber_cement_lap": "siding",
    "board_and_batten": "siding", "wood_shingle": "wood",
    "red_brick": "brick", "buff_brick": "brick", "dark_brick": "brick",
    "painted_brick": "painted_brick", "stone_veneer": "stone",
    "smooth_stucco": "stucco", "metal_panel": "metal_panel", "none": "siding",
}

TRIM_FAMILIES = (
    "CRAFTSMAN_WOOD", "VICTORIAN_GINGERBREAD", "CLASSICAL_WHITE",
    "TUDOR_HALF_TIMBER", "RANCH_MINIMAL", "MCM_PLANK", "STUCCO_SIMPLE",
    "SUBURBAN_TRIM", "NONE",
)

DETAIL_TAGS = (
    "exposed_rafter_tails", "knee_brackets", "gable_vent", "chimney_prominent",
    "chimney_modest", "dormer_front", "gable_decoration", "shutters",
    "arched_entry", "columns", "half_timber_gable", "clerestory_strip",
    "picture_window", "wide_overhang", "bay_projection", "stone_accent_wall",
    "porch_rail", "wrought_iron", "tile_roof_ridge",
)

MODIFICATIONS = (
    "REPAINTED", "PAINTED_BRICK", "REPLACEMENT_SIDING", "METAL_ROOF_RETROFIT",
    "REPLACEMENT_WINDOWS", "PORCH_SCREENED_OR_SIMPLIFIED", "GARAGE_DOOR_REPLACED",
)


# --------------------------------------------------------------------------
# Provenanced scalar (mirrors building_appearance.AppearanceValue)
# --------------------------------------------------------------------------
@dataclass
class ArchValue:
    """One architectural attribute: a value plus how we know it."""
    value: Optional[object]
    provenance: str  # OBSERVED | DERIVED | PROCEDURAL

    def to_dict(self) -> dict:
        return {"value": self.value, "class": self.provenance}

    @classmethod
    def from_dict(cls, d: dict) -> "ArchValue":
        return cls(value=d.get("value"), provenance=d.get("class", "PROCEDURAL"))

    def validate(self, where: str, allowed=None) -> list:
        errs = []
        if self.provenance not in PROVENANCE_CLASSES:
            errs.append(f"{where}: bad provenance {self.provenance!r}")
        if allowed is not None and self.value is not None and self.value not in allowed:
            errs.append(f"{where}: {self.value!r} not in enum")
        return errs


# --------------------------------------------------------------------------
# Nested grammar sub-records
# --------------------------------------------------------------------------
@dataclass
class Foundation:
    family: str = "SLAB_ON_GRADE"
    height_m: float = 0.15   # visible wall-base rise above grade

    def to_dict(self) -> dict:
        return {"family": self.family, "height_m": round(self.height_m, 3)}

    @classmethod
    def from_dict(cls, d: dict) -> "Foundation":
        return cls(family=d.get("family", "SLAB_ON_GRADE"),
                   height_m=float(d.get("height_m", 0.15)))

    def validate(self) -> list:
        e = []
        if self.family not in FOUNDATIONS:
            e.append(f"foundation.family {self.family!r} invalid")
        if not (0.0 <= self.height_m <= 2.0):
            e.append(f"foundation.height_m {self.height_m!r} out of range")
        return e


@dataclass
class Massing:
    story_profile: str = "ONE"
    horizontal_emphasis: str = "MEDIUM"
    symmetry: str = "ASYMMETRIC"

    def to_dict(self) -> dict:
        return {"story_profile": self.story_profile,
                "horizontal_emphasis": self.horizontal_emphasis,
                "symmetry": self.symmetry}

    @classmethod
    def from_dict(cls, d: dict) -> "Massing":
        return cls(d.get("story_profile", "ONE"),
                   d.get("horizontal_emphasis", "MEDIUM"),
                   d.get("symmetry", "ASYMMETRIC"))

    def validate(self) -> list:
        e = []
        if self.story_profile not in STORY_PROFILES:
            e.append(f"massing.story_profile {self.story_profile!r} invalid")
        if self.horizontal_emphasis not in HORIZONTAL_EMPHASIS:
            e.append(f"massing.horizontal_emphasis {self.horizontal_emphasis!r} invalid")
        if self.symmetry not in SYMMETRY_MODES:
            e.append(f"massing.symmetry {self.symmetry!r} invalid")
        return e


@dataclass
class RoofGrammar:
    family: str = "SIDE_GABLE"
    pitch: str = "MEDIUM"
    eave: str = "NORMAL"
    # material/subtype echo the appearance roof material family but let the
    # architecture assert e.g. tile for Spanish, metal retrofit, etc.
    material: str = "asphalt_shingle"
    material_subtype: str = "asphalt_3tab"
    dormer: bool = False

    def to_dict(self) -> dict:
        return {"family": self.family, "pitch": self.pitch, "eave": self.eave,
                "material": self.material, "material_subtype": self.material_subtype,
                "dormer": self.dormer}

    @classmethod
    def from_dict(cls, d: dict) -> "RoofGrammar":
        return cls(d.get("family", "SIDE_GABLE"), d.get("pitch", "MEDIUM"),
                   d.get("eave", "NORMAL"), d.get("material", "asphalt_shingle"),
                   d.get("material_subtype", "asphalt_3tab"),
                   bool(d.get("dormer", False)))

    def validate(self) -> list:
        e = []
        if self.family not in ROOF_FAMILIES:
            e.append(f"roof.family {self.family!r} invalid")
        if self.pitch not in PITCH_CLASSES:
            e.append(f"roof.pitch {self.pitch!r} invalid")
        if self.eave not in EAVE_CLASSES:
            e.append(f"roof.eave {self.eave!r} invalid")
        return e


@dataclass
class FacadeComposition:
    """Multi-material facade regions. Each is a FACADE_SUBTYPES member; map to a
    shared shader family via FACADE_SUBTYPE_TO_FAMILY."""
    front: str = "wood_lap"
    side_rear: str = "wood_lap"
    gable: str = "wood_lap"
    foundation: str = "smooth_stucco"
    accent: str = "none"
    trim: str = "SUBURBAN_TRIM"

    def to_dict(self) -> dict:
        return {"front": self.front, "side_rear": self.side_rear,
                "gable": self.gable, "foundation": self.foundation,
                "accent": self.accent, "trim": self.trim}

    @classmethod
    def from_dict(cls, d: dict) -> "FacadeComposition":
        return cls(d.get("front", "wood_lap"), d.get("side_rear", "wood_lap"),
                   d.get("gable", "wood_lap"), d.get("foundation", "smooth_stucco"),
                   d.get("accent", "none"), d.get("trim", "SUBURBAN_TRIM"))

    def validate(self) -> list:
        e = []
        for name in ("front", "side_rear", "gable", "foundation", "accent"):
            v = getattr(self, name)
            if v not in FACADE_SUBTYPES:
                e.append(f"facade.{name} {v!r} invalid")
        if self.trim not in TRIM_FAMILIES:
            e.append(f"facade.trim {self.trim!r} invalid")
        return e


@dataclass
class PorchGrammar:
    family: str = "NONE"
    depth_m: float = 0.0
    width_fraction: float = 0.0   # of the front edge
    support: str = "NONE"

    def to_dict(self) -> dict:
        return {"family": self.family, "depth_m": round(self.depth_m, 3),
                "width_fraction": round(self.width_fraction, 3),
                "support": self.support}

    @classmethod
    def from_dict(cls, d: dict) -> "PorchGrammar":
        return cls(d.get("family", "NONE"), float(d.get("depth_m", 0.0)),
                   float(d.get("width_fraction", 0.0)), d.get("support", "NONE"))

    def validate(self) -> list:
        e = []
        if self.family not in PORCH_FAMILIES:
            e.append(f"porch.family {self.family!r} invalid")
        if self.support not in PORCH_SUPPORTS:
            e.append(f"porch.support {self.support!r} invalid")
        if not (0.0 <= self.width_fraction <= 1.0):
            e.append(f"porch.width_fraction {self.width_fraction!r} out of range")
        return e


@dataclass
class WindowGrammar:
    family: str = "SIMPLE_VERTICAL"
    symmetric: bool = False

    def to_dict(self) -> dict:
        return {"family": self.family, "symmetric": self.symmetric}

    @classmethod
    def from_dict(cls, d: dict) -> "WindowGrammar":
        return cls(d.get("family", "SIMPLE_VERTICAL"), bool(d.get("symmetric", False)))

    def validate(self) -> list:
        if self.family not in WINDOW_GRAMMARS:
            return [f"windows.family {self.family!r} invalid"]
        return []


# --------------------------------------------------------------------------
# Top-level record
# --------------------------------------------------------------------------
@dataclass
class ResidentialArchitectureV1:
    bid: int
    era: ArchValue = field(default_factory=lambda: ArchValue("UNKNOWN", "PROCEDURAL"))
    form: ArchValue = field(default_factory=lambda: ArchValue("MINIMAL_TRADITIONAL", "DERIVED"))
    style: ArchValue = field(default_factory=lambda: ArchValue("MINIMAL_TRADITIONAL", "PROCEDURAL"))

    cohort_id: int = -1
    builder_family_id: int = -1
    plan_variant: int = 0
    mirrored: bool = False

    foundation: Foundation = field(default_factory=Foundation)
    massing: Massing = field(default_factory=Massing)
    roof: RoofGrammar = field(default_factory=RoofGrammar)
    facade: FacadeComposition = field(default_factory=FacadeComposition)
    porch: PorchGrammar = field(default_factory=PorchGrammar)
    windows: WindowGrammar = field(default_factory=WindowGrammar)
    parking: str = "SIDE_DRIVE"

    details: list = field(default_factory=list)         # subset of DETAIL_TAGS
    modifications: list = field(default_factory=list)   # subset of MODIFICATIONS
    version: int = RESIDENTIAL_ARCH_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version, "bid": self.bid,
            "era": self.era.to_dict(), "form": self.form.to_dict(),
            "style": self.style.to_dict(),
            "cohort_id": self.cohort_id,
            "builder_family_id": self.builder_family_id,
            "plan_variant": self.plan_variant, "mirrored": self.mirrored,
            "foundation": self.foundation.to_dict(),
            "massing": self.massing.to_dict(), "roof": self.roof.to_dict(),
            "facade": self.facade.to_dict(), "porch": self.porch.to_dict(),
            "windows": self.windows.to_dict(), "parking": self.parking,
            "details": list(self.details), "modifications": list(self.modifications),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResidentialArchitectureV1":
        return cls(
            bid=int(d["bid"]),
            era=ArchValue.from_dict(d.get("era", {})),
            form=ArchValue.from_dict(d.get("form", {})),
            style=ArchValue.from_dict(d.get("style", {})),
            cohort_id=int(d.get("cohort_id", -1)),
            builder_family_id=int(d.get("builder_family_id", -1)),
            plan_variant=int(d.get("plan_variant", 0)),
            mirrored=bool(d.get("mirrored", False)),
            foundation=Foundation.from_dict(d.get("foundation", {})),
            massing=Massing.from_dict(d.get("massing", {})),
            roof=RoofGrammar.from_dict(d.get("roof", {})),
            facade=FacadeComposition.from_dict(d.get("facade", {})),
            porch=PorchGrammar.from_dict(d.get("porch", {})),
            windows=WindowGrammar.from_dict(d.get("windows", {})),
            parking=d.get("parking", "SIDE_DRIVE"),
            details=list(d.get("details", [])),
            modifications=list(d.get("modifications", [])),
            version=int(d.get("version", RESIDENTIAL_ARCH_VERSION)),
        )

    def validate(self) -> list:
        e = []
        e += self.era.validate("era", ERAS)
        e += self.form.validate("form", FORMS)
        e += self.style.validate("style", STYLES)
        # style is inferred grammar, never a measured observation.
        if self.style.provenance == "OBSERVED":
            e.append("style may not be OBSERVED (it is always inferred)")
        e += self.foundation.validate()
        e += self.massing.validate()
        e += self.roof.validate()
        e += self.facade.validate()
        e += self.porch.validate()
        e += self.windows.validate()
        if self.parking not in PARKING_FAMILIES:
            e.append(f"parking {self.parking!r} invalid")
        for t in self.details:
            if t not in DETAIL_TAGS:
                e.append(f"detail tag {t!r} invalid")
        for m in self.modifications:
            if m not in MODIFICATIONS:
                e.append(f"modification {m!r} invalid")
        return e

    def is_valid(self) -> bool:
        return not self.validate()

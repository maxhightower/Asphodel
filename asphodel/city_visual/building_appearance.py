"""BuildingAppearanceV1 -- per-building exterior appearance with provenance.

Every appearance attribute retains both a *value* and an *epistemic class*
(OBSERVED / DERIVED / PROCEDURAL). This is the contract that flows:

    source acquisition -> normalize -> WorldSourceV1 -> BuildingRecord
        -> chunk serialization -> Godot exterior renderer

so the renderer can shade an observed brick facade differently from an inferred
one, and so a report can honestly say which buildings are real vs inferred.

VIS-0 census reality (Overture 2026-08-19.0, the pinned release): for Houston /
Austin / San Antonio / Madisonville, facade/roof colour+material coverage is
~0% (height is 68-99%). So in practice almost every building's appearance is
DERIVED/PROCEDURAL; this contract exists to (a) carry the rare OBSERVED values
correctly end-to-end and (b) generalize to future cities/data that do supply
appearance. It must never label an inferred value OBSERVED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .provenance import PROVENANCE_CLASSES, require

# Canonical material families (Section 16). Observed material is snapped to one
# of these; inference fills the rest. Renderers map each to a shared shader.
FACADE_MATERIALS = (
    "brick", "painted_brick", "siding", "stucco", "concrete", "stone",
    "metal_panel", "wood", "glass_curtain", "painted_masonry",
)
ROOF_MATERIALS = (
    "asphalt_shingle", "standing_seam_metal", "flat_membrane", "tile",
    "roof_generic",
)
ROOF_SHAPES = ("flat", "gabled", "hipped", "pyramidal", "complex", "pitched")

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class AppearanceValue:
    """A single appearance attribute: its value plus how we know it."""
    value: Optional[object]
    provenance: str            # OBSERVED | DERIVED | PROCEDURAL

    def to_dict(self) -> dict:
        return {"value": self.value, "class": self.provenance}

    @classmethod
    def from_dict(cls, d: dict) -> "AppearanceValue":
        return cls(value=d.get("value"), provenance=d.get("class", "PROCEDURAL"))

    def validate(self, where: str) -> list:
        errs = []
        if self.provenance not in PROVENANCE_CLASSES:
            errs.append(f"{where}: bad provenance {self.provenance!r}")
        return errs


def _validate_color(av: AppearanceValue, where: str) -> list:
    errs = av.validate(where)
    if av.value is not None and not _HEX_RE.match(str(av.value)):
        errs.append(f"{where}: colour {av.value!r} is not #rrggbb")
    return errs


def _validate_enum(av: AppearanceValue, allowed, where: str) -> list:
    errs = av.validate(where)
    if av.value is not None and av.value not in allowed:
        errs.append(f"{where}: {av.value!r} not in {allowed}")
    return errs


@dataclass
class FacadeAppearance:
    color: AppearanceValue
    material: AppearanceValue

    def to_dict(self) -> dict:
        return {"color": self.color.to_dict(), "material": self.material.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "FacadeAppearance":
        return cls(AppearanceValue.from_dict(d["color"]),
                   AppearanceValue.from_dict(d["material"]))

    def validate(self) -> list:
        return (_validate_color(self.color, "facade.color")
                + _validate_enum(self.material, FACADE_MATERIALS, "facade.material"))


@dataclass
class RoofAppearance:
    color: AppearanceValue
    material: AppearanceValue
    shape: AppearanceValue

    def to_dict(self) -> dict:
        return {"color": self.color.to_dict(), "material": self.material.to_dict(),
                "shape": self.shape.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "RoofAppearance":
        return cls(AppearanceValue.from_dict(d["color"]),
                   AppearanceValue.from_dict(d["material"]),
                   AppearanceValue.from_dict(d["shape"]))

    def validate(self) -> list:
        return (_validate_color(self.color, "roof.color")
                + _validate_enum(self.material, ROOF_MATERIALS, "roof.material")
                + _validate_enum(self.shape, ROOF_SHAPES, "roof.shape"))


@dataclass
class BuildingAppearanceV1:
    bid: int
    facade: FacadeAppearance
    roof: RoofAppearance
    # A derived family label ("gulf_residential_brick", ...) grouping buildings
    # that should read as one architectural style. Always DERIVED/PROCEDURAL.
    style_family: AppearanceValue = field(
        default_factory=lambda: AppearanceValue(None, "PROCEDURAL"))
    # Massing observables carried with provenance (height is the one field
    # Overture actually covers well for the cert cities).
    height_m: AppearanceValue = field(
        default_factory=lambda: AppearanceValue(None, "PROCEDURAL"))
    floors: AppearanceValue = field(
        default_factory=lambda: AppearanceValue(None, "PROCEDURAL"))
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "version": self.version, "bid": self.bid,
            "facade": self.facade.to_dict(), "roof": self.roof.to_dict(),
            "style_family": self.style_family.to_dict(),
            "height_m": self.height_m.to_dict(), "floors": self.floors.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BuildingAppearanceV1":
        return cls(
            bid=int(d["bid"]),
            facade=FacadeAppearance.from_dict(d["facade"]),
            roof=RoofAppearance.from_dict(d["roof"]),
            style_family=AppearanceValue.from_dict(
                d.get("style_family", {"value": None, "class": "PROCEDURAL"})),
            height_m=AppearanceValue.from_dict(
                d.get("height_m", {"value": None, "class": "PROCEDURAL"})),
            floors=AppearanceValue.from_dict(
                d.get("floors", {"value": None, "class": "PROCEDURAL"})),
            version=int(d.get("version", 1)),
        )

    def validate(self) -> list:
        errs = self.facade.validate() + self.roof.validate()
        errs += self.style_family.validate("style_family")
        errs += self.height_m.validate("height_m")
        errs += self.floors.validate("floors")
        # style_family must never claim to be OBSERVED (it is always inferred).
        if self.style_family.provenance == "OBSERVED":
            errs.append("style_family may not be OBSERVED (it is always inferred)")
        return errs

    def is_valid(self) -> bool:
        return not self.validate()

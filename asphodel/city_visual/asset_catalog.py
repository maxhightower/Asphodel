"""AssetCatalogV1 -- the semantic asset registry.

The load-bearing abstraction of the City Assets system: the procedural
generator requests *semantic concepts* (``chair_dining``, ``mailbox_suburban``,
``live_oak_mature``) and the catalog resolves each to a concrete visual variant
deterministically. Generator code must never name a raw ``.glb`` / procedural
mesh directly -- only semantic ids -- so the art library can grow/change without
touching world generation.

The freeze pins the *shape* of the registry and its validation rules. V1 ships
with every variant backed by a procedural mesh fallback (the existing
prop_meshes / interior primitives), because no authored ``.glb`` assets exist
yet; later packages add ``resource`` variants alongside the fallbacks without
changing this contract.

Data lives in ``catalog_v1.yaml`` next to this module; this file owns load +
validation + deterministic selection.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

CATEGORIES = (
    "furniture", "street_furniture", "vegetation", "sign", "utility",
    "commercial_equipment", "workplace", "residential", "clutter",
    "environmental", "vehicle", "infrastructure",
)
PLACEMENTS = ("floor", "wall", "ceiling", "ground", "roof", "surface")
COLLISION_MODES = ("none", "simple", "mesh")
INTERACTION_CLASSES = (
    "none", "sit", "sleep", "cook", "work_at_desk", "stock_shelf",
    "use_register", "examine_patient", "use_machine", "store", "search",
)
CONDITIONS = (
    "NORMAL", "DISRUPTED", "ABANDONED", "LOOTED", "DAMAGED", "OVERRUN",
)


def _stable_hash(s: str, seed: int) -> int:
    h = 1469598103934665603 ^ (seed & 0xFFFFFFFFFFFFFFFF)
    for ch in s.encode("utf-8"):
        h = (h ^ ch) * 1099511628211 & 0xFFFFFFFFFFFFFFFF
    return h


@dataclass
class AssetVariant:
    id: str
    weight: float = 1.0
    resource: Optional[str] = None       # res://... authored asset, or None
    procedural: Optional[str] = None     # procedural fallback kind, or None
    conditions: tuple = ("NORMAL",)      # condition states this variant suits

    def to_dict(self) -> dict:
        return {"id": self.id, "weight": self.weight, "resource": self.resource,
                "procedural": self.procedural, "conditions": list(self.conditions)}

    @classmethod
    def from_dict(cls, d: dict) -> "AssetVariant":
        return cls(id=d["id"], weight=float(d.get("weight", 1.0)),
                   resource=d.get("resource"), procedural=d.get("procedural"),
                   conditions=tuple(d.get("conditions", ["NORMAL"])))

    def validate(self, where: str) -> list:
        errs = []
        if self.weight <= 0:
            errs.append(f"{where}: weight must be > 0")
        if not self.resource and not self.procedural:
            errs.append(f"{where}: variant has neither resource nor procedural fallback")
        if self.resource and not str(self.resource).startswith("res://"):
            errs.append(f"{where}: resource {self.resource!r} must be a res:// path")
        for c in self.conditions:
            if c not in CONDITIONS:
                errs.append(f"{where}: bad condition {c!r}")
        return errs


@dataclass
class AssetFamily:
    semantic_id: str
    category: str
    placement: str = "floor"
    outdoor: bool = False
    dimensions: dict = field(default_factory=dict)     # width_m/depth_m/height_m
    clearance: dict = field(default_factory=dict)      # front_m/...
    collision: str = "simple"
    interaction: str = "none"
    material_family: Optional[str] = None
    room_tags: tuple = ()
    parcel_tags: tuple = ()
    building_tags: tuple = ()
    climate_tags: tuple = ()
    seed_tag: str = ""                                 # deterministic selection key
    lod_fallback: Optional[str] = None                 # procedural kind for far LOD
    variants: list = field(default_factory=list)       # list[AssetVariant]

    def to_dict(self) -> dict:
        return {
            "semantic_id": self.semantic_id, "category": self.category,
            "placement": self.placement, "outdoor": self.outdoor,
            "dimensions": self.dimensions, "clearance": self.clearance,
            "collision": self.collision, "interaction": self.interaction,
            "material_family": self.material_family,
            "room_tags": list(self.room_tags), "parcel_tags": list(self.parcel_tags),
            "building_tags": list(self.building_tags),
            "climate_tags": list(self.climate_tags),
            "seed_tag": self.seed_tag, "lod_fallback": self.lod_fallback,
            "variants": [v.to_dict() for v in self.variants],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AssetFamily":
        return cls(
            semantic_id=d["semantic_id"], category=d["category"],
            placement=d.get("placement", "floor"), outdoor=bool(d.get("outdoor", False)),
            dimensions=d.get("dimensions", {}), clearance=d.get("clearance", {}),
            collision=d.get("collision", "simple"), interaction=d.get("interaction", "none"),
            material_family=d.get("material_family"),
            room_tags=tuple(d.get("room_tags", [])),
            parcel_tags=tuple(d.get("parcel_tags", [])),
            building_tags=tuple(d.get("building_tags", [])),
            climate_tags=tuple(d.get("climate_tags", [])),
            seed_tag=d.get("seed_tag", d["semantic_id"]),
            lod_fallback=d.get("lod_fallback"),
            variants=[AssetVariant.from_dict(v) for v in d.get("variants", [])],
        )

    def validate(self) -> list:
        w = f"family {self.semantic_id}"
        errs = []
        if self.category not in CATEGORIES:
            errs.append(f"{w}: bad category {self.category!r}")
        if self.placement not in PLACEMENTS:
            errs.append(f"{w}: bad placement {self.placement!r}")
        if self.collision not in COLLISION_MODES:
            errs.append(f"{w}: bad collision {self.collision!r}")
        if self.interaction not in INTERACTION_CLASSES:
            errs.append(f"{w}: bad interaction {self.interaction!r}")
        for k in ("width_m", "depth_m", "height_m"):
            v = self.dimensions.get(k)
            if v is None or v <= 0:
                errs.append(f"{w}: dimension {k} must be > 0 (got {v!r})")
        if not self.variants:
            errs.append(f"{w}: no variants")
        for v in self.variants:
            errs += v.validate(f"{w}/{v.id}")
        return errs

    def select(self, seed: int) -> AssetVariant:
        """Deterministic weighted variant pick for a given placement seed."""
        total = sum(v.weight for v in self.variants)
        r = (_stable_hash(self.seed_tag, seed) % 100000) / 100000.0 * total
        acc = 0.0
        for v in self.variants:
            acc += v.weight
            if r < acc:
                return v
        return self.variants[-1]


@dataclass
class AssetCatalogV1:
    families: dict = field(default_factory=dict)    # semantic_id -> AssetFamily
    version: int = 1

    @classmethod
    def from_list(cls, families: list) -> "AssetCatalogV1":
        cat = cls()
        for f in families:
            fam = f if isinstance(f, AssetFamily) else AssetFamily.from_dict(f)
            cat.families[fam.semantic_id] = fam
        return cat

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AssetCatalogV1":
        import yaml
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "catalog_v1.yaml")
        with open(path) as fh:
            doc = yaml.safe_load(fh)
        return cls.from_list(doc.get("families", []))

    def get(self, semantic_id: str) -> AssetFamily:
        if semantic_id not in self.families:
            raise KeyError(f"unknown semantic asset id {semantic_id!r}")
        return self.families[semantic_id]

    def validate(self) -> list:
        errs = []
        seen = set()
        for sid, fam in self.families.items():
            if sid in seen:
                errs.append(f"duplicate semantic_id {sid!r}")
            seen.add(sid)
            if fam.semantic_id != sid:
                errs.append(f"family key {sid!r} != semantic_id {fam.semantic_id!r}")
            errs += fam.validate()
        return errs

    def is_valid(self) -> bool:
        return not self.validate()

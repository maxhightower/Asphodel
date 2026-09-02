"""CityVisualProfileV1 -- a city's derived visual + climatological identity.

Compiled from geography and public data (building appearance distributions,
NOAA climate normals, land cover), never from the city's name. It is the single
artifact the renderer reads to make one city look and feel different from
another: solar/atmosphere inputs, sky/haze priors, palette + material
distributions used by appearance inference, and the regional vegetation family.

Every block records the provenance/source needed to reproduce it (Section 17 /
Section 28). No runtime web dependency: the profile is compiled once and cached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceRef:
    """Where a profile block came from, for reproducibility + licensing."""
    name: str                        # e.g. "NOAA NCEI Climate Normals 1991-2020"
    version: Optional[str] = None    # release/normal-period id
    license: str = "UNKNOWN"         # matches provenance license families
    url: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "version": self.version,
                "license": self.license, "url": self.url, "note": self.note}

    @classmethod
    def from_dict(cls, d: dict) -> "SourceRef":
        return cls(name=d.get("name", "?"), version=d.get("version"),
                   license=d.get("license", "UNKNOWN"), url=d.get("url"),
                   note=d.get("note", ""))


@dataclass
class CityVisualProfileV1:
    city: str                        # identity only (bundle key); never a rule input
    location: dict                   # {latitude, longitude, elevation_m?}
    architecture: dict = field(default_factory=dict)
    #   facade_palette / facade_material_dist / roof_palette / roof_material_dist
    #   (each a {label: fraction} map) + archetype_profiles
    climate: dict = field(default_factory=dict)
    #   temperature_normals / dewpoint_normals / cloud_state_distribution /
    #   wind_speed_normals / prevailing_wind_deg / precipitation
    atmosphere: dict = field(default_factory=dict)
    #   humidity_factor / haze_factor / visibility_prior_m / cloudiness_prior (0..1)
    vegetation: dict = field(default_factory=dict)
    #   regional_family / landcover_distribution
    sources: list = field(default_factory=list)     # list[SourceRef]
    appearance_class: str = "DERIVED"                # profile is inferred, not observed
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "version": self.version, "city": self.city, "location": self.location,
            "architecture": self.architecture, "climate": self.climate,
            "atmosphere": self.atmosphere, "vegetation": self.vegetation,
            "appearance_class": self.appearance_class,
            "sources": [s.to_dict() for s in self.sources],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityVisualProfileV1":
        return cls(
            city=d["city"], location=d["location"],
            architecture=d.get("architecture", {}), climate=d.get("climate", {}),
            atmosphere=d.get("atmosphere", {}), vegetation=d.get("vegetation", {}),
            sources=[SourceRef.from_dict(s) for s in d.get("sources", [])],
            appearance_class=d.get("appearance_class", "DERIVED"),
            version=int(d.get("version", 1)),
        )

    def validate(self) -> list:
        errs = []
        lat = self.location.get("latitude")
        lon = self.location.get("longitude")
        if lat is None or not (-90.0 <= float(lat) <= 90.0):
            errs.append(f"location.latitude out of range: {lat!r}")
        if lon is None or not (-180.0 <= float(lon) <= 180.0):
            errs.append(f"location.longitude out of range: {lon!r}")
        for k in ("humidity_factor", "haze_factor", "cloudiness_prior"):
            v = self.atmosphere.get(k)
            if v is not None and not (0.0 <= float(v) <= 1.0):
                errs.append(f"atmosphere.{k} must be in [0,1]: {v!r}")
        # distributions should sum to ~1 when present
        for block, key in (("architecture", "facade_material_dist"),
                           ("architecture", "roof_material_dist"),
                           ("vegetation", "landcover_distribution")):
            dist = getattr(self, block).get(key)
            if isinstance(dist, dict) and dist:
                s = sum(float(x) for x in dist.values())
                if not (0.95 <= s <= 1.05):
                    errs.append(f"{block}.{key} fractions sum to {s:.3f}, not ~1")
        if self.appearance_class == "OBSERVED":
            errs.append("a CityVisualProfile is DERIVED/PROCEDURAL, never OBSERVED")
        return errs

    def is_valid(self) -> bool:
        return not self.validate()

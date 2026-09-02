"""Asphodel City Assets + Visual Identity System (V1 contracts).

This package freezes the three load-bearing V1 contracts that the City Assets +
Visual Identity mission builds on, keeping them separate from the world-source
compiler so appearance/asset concerns never leak into world semantics:

  * AssetCatalogV1      -- semantic asset registry (semantic_id -> family ->
                           variants), the abstraction that lets the generator
                           request *concepts* (chair_dining, mailbox_suburban)
                           instead of art filenames.
  * BuildingAppearanceV1 -- per-building facade/roof colour + material + shape
                           carrying OBSERVED / DERIVED / PROCEDURAL provenance.
  * CityVisualProfileV1 -- the derived visual/climatological identity of a city,
                           sourced from geography + public data, never keyed on
                           the city name.

All three are pure data contracts (no Godot, no network) with deterministic
serialization and mechanical validation, so Python tests and the Godot renderer
can share one source of truth.
"""

from .provenance import OBSERVED, DERIVED, PROCEDURAL, PROVENANCE_CLASSES
from .building_appearance import (
    BuildingAppearanceV1, FacadeAppearance, RoofAppearance, AppearanceValue,
)
from .asset_catalog import AssetCatalogV1, AssetFamily, AssetVariant
from .city_profile import CityVisualProfileV1

__all__ = [
    "OBSERVED", "DERIVED", "PROCEDURAL", "PROVENANCE_CLASSES",
    "BuildingAppearanceV1", "FacadeAppearance", "RoofAppearance",
    "AppearanceValue",
    "AssetCatalogV1", "AssetFamily", "AssetVariant",
    "CityVisualProfileV1",
]

"""Shared epistemic-provenance vocabulary for the visual-identity system.

Reuses Asphodel's existing OBSERVED / DERIVED / PROCEDURAL philosophy (the same
three classes world_source.schema.OBSERVATION_CLASSES uses) so appearance and
profile data can never silently claim to be measured when it was inferred.

  OBSERVED   -- came directly from a public data source (e.g. an Overture
                facade_color value, a NOAA climate normal). Never inferred.
  DERIVED    -- deterministically inferred from other observed data (nearby
                observed buildings, local distributions, archetype priors).
  PROCEDURAL -- generated from a deterministic rule/seed with no observational
                basis (a fail-safe palette, a default material).
"""
from __future__ import annotations

OBSERVED = "OBSERVED"
DERIVED = "DERIVED"
PROCEDURAL = "PROCEDURAL"

PROVENANCE_CLASSES = (OBSERVED, DERIVED, PROCEDURAL)


def is_valid(pclass: str) -> bool:
    return pclass in PROVENANCE_CLASSES


def require(pclass: str, where: str = "") -> str:
    if pclass not in PROVENANCE_CLASSES:
        raise ValueError(
            f"invalid provenance class {pclass!r}{(' at ' + where) if where else ''}; "
            f"expected one of {PROVENANCE_CLASSES}")
    return pclass

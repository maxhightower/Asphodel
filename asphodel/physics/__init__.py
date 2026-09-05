"""Physical world authority (AS-PHYS-0): the single collision matrix + solidity."""
from __future__ import annotations

from .layers import (
    BODY_PROFILES,
    OBJECT_SOLIDITY,
    BodyProfile,
    BodyRole,
    Layer,
    ObjectPhysicalProfile,
    Solidity,
    classify_object,
    collision_matrix,
    emit_gdscript,
    godot_layer_names,
    physically_blocks,
    senses,
)

__all__ = [
    "Layer",
    "Solidity",
    "BodyRole",
    "BodyProfile",
    "BODY_PROFILES",
    "physically_blocks",
    "senses",
    "ObjectPhysicalProfile",
    "OBJECT_SOLIDITY",
    "classify_object",
    "collision_matrix",
    "godot_layer_names",
    "emit_gdscript",
]

"""Physical world authority: collision layers, masks, and solidity taxonomy.

AS-PHYS-0, §4.1, §2.2. This is the ONE authoritative definition of the physics
collision matrix. Godot must not scatter ad-hoc ``collision_layer = 3`` defaults
across scripts; instead it reads the matrix generated from here
(:func:`emit_gdscript`), so the engine and the sim agree by construction.

Two orthogonal concepts, deliberately separated (§4.1):

* **Layers** — what a body *is* (WORLD_STATIC, PLAYER, NPC, ...).
* **Masks** — what a body *scans for*. A moving body needs the other body's layer
  in its mask to be stopped by it. Sensing/query volumes (triggers, nav rays,
  damage queries) scan bodies without being physical obstacles themselves — an
  asymmetric relationship that is correct, not a bug.

Every generated world object also declares a **solidity** (§2.2) so visual meshes
are never silently used as collision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum
from typing import Dict, List, Tuple


class Layer(IntEnum):
    """Collision layer bits. Value is the bitmask; Godot layer index = bit+1."""

    WORLD_STATIC = 1 << 0   # terrain, walls, floors, permanent structure
    PLAYER = 1 << 1
    NPC = 1 << 2
    VEHICLE = 1 << 3
    DYNAMIC_PROP = 1 << 4   # movable/breakable props, wrecks-as-obstacles
    TRIGGER = 1 << 5        # Area3D sense volumes (doors, zones)
    NAV_QUERY = 1 << 6      # navigation raycasts / shapecasts (non-physical)
    DAMAGE_QUERY = 1 << 7   # hit/damage raycasts (non-physical)

    @property
    def godot_index(self) -> int:
        return self.value.bit_length()  # 1-based index Godot uses in project.godot


class Solidity(Enum):
    """How a generated object participates in the physical world (§2.2)."""

    SOLID = "solid"                 # static, blocks everything
    DYNAMIC = "dynamic"             # rigid body, moves under physics
    BREAKABLE = "breakable"         # solid until destroyed, then debris
    MOVABLE = "movable"             # pushable prop
    NON_SOLID = "non_solid"         # overlappable volume (foliage canopy)
    TRIGGER_ONLY = "trigger_only"   # sense volume, no blocking
    NAVIGATION_ONLY = "navigation_only"  # affects routing, not physics (a lane)
    DECORATION_ONLY = "decoration_only"  # visual only, no collision/nav


class BodyRole(Enum):
    STATIC_BODY = "static_body"
    CHARACTER_BODY = "character_body"
    RIGID_BODY = "rigid_body"
    AREA = "area"
    QUERY = "query"


@dataclass(frozen=True)
class BodyProfile:
    """A physics body type's layer/mask and its Godot node role."""

    name: str
    role: BodyRole
    layer: int          # bitmask of Layer(s) this body occupies
    mask: int           # bitmask of Layer(s) this body scans/collides with

    @property
    def is_physical(self) -> bool:
        return self.role in (BodyRole.STATIC_BODY, BodyRole.CHARACTER_BODY,
                             BodyRole.RIGID_BODY)

    @property
    def is_mover(self) -> bool:
        return self.role in (BodyRole.CHARACTER_BODY, BodyRole.RIGID_BODY)


# The authoritative body profiles. Moving bodies scan WORLD_STATIC and every
# other moving layer so nothing tunnels through anything; static world scans
# nothing (it never moves). Sensors scan agents but do not block them.
_MOVER_MASK = (Layer.WORLD_STATIC | Layer.PLAYER | Layer.NPC | Layer.VEHICLE
               | Layer.DYNAMIC_PROP)

BODY_PROFILES: Dict[str, BodyProfile] = {
    "world_static": BodyProfile("world_static", BodyRole.STATIC_BODY,
                                int(Layer.WORLD_STATIC), 0),
    "player": BodyProfile("player", BodyRole.CHARACTER_BODY,
                          int(Layer.PLAYER), int(_MOVER_MASK)),
    "npc": BodyProfile("npc", BodyRole.CHARACTER_BODY,
                       int(Layer.NPC), int(_MOVER_MASK)),
    "vehicle": BodyProfile("vehicle", BodyRole.RIGID_BODY,
                           int(Layer.VEHICLE), int(_MOVER_MASK)),
    "dynamic_prop": BodyProfile("dynamic_prop", BodyRole.RIGID_BODY,
                                int(Layer.DYNAMIC_PROP), int(_MOVER_MASK)),
    # Area3D sense volume: detects agents, blocks nothing.
    "trigger": BodyProfile("trigger", BodyRole.AREA,
                           int(Layer.TRIGGER),
                           int(Layer.PLAYER | Layer.NPC | Layer.VEHICLE)),
    # Navigation raycast: tests only the solid world (and vehicles as obstacles).
    "nav_query": BodyProfile("nav_query", BodyRole.QUERY,
                             int(Layer.NAV_QUERY),
                             int(Layer.WORLD_STATIC | Layer.VEHICLE
                                 | Layer.DYNAMIC_PROP)),
    # Damage/hit raycast.
    "damage_query": BodyProfile("damage_query", BodyRole.QUERY,
                                int(Layer.DAMAGE_QUERY),
                                int(Layer.WORLD_STATIC | Layer.PLAYER | Layer.NPC
                                    | Layer.VEHICLE)),
}


def physically_blocks(a: BodyProfile, b: BodyProfile) -> bool:
    """Do these two bodies form a solid (blocking) contact?

    Only physical bodies block. A block exists if either body scans the other's
    layer (Godot resolves the contact either way). Query/area profiles never
    block (they are sensors), so a pair involving one is never a physical block.
    """
    if not (a.is_physical and b.is_physical):
        return False
    return bool(a.mask & b.layer) or bool(b.mask & a.layer)


def senses(sensor: BodyProfile, target: BodyProfile) -> bool:
    """Does ``sensor`` (area/query) detect ``target``?"""
    return bool(sensor.mask & target.layer)


# --------------------------------------------------------------------------- #
# Object solidity classification (§2.2). Generated world objects map to these.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ObjectPhysicalProfile:
    kind: str
    solidity: Solidity
    body: str            # key into BODY_PROFILES (or "" for non-physical)
    collision: bool
    navigation: bool     # does it participate in the navigation representation
    note: str = ""


def _obj(kind, solidity, body, collision, navigation, note=""):
    return ObjectPhysicalProfile(kind, solidity, body, collision, navigation, note)


OBJECT_SOLIDITY: Dict[str, ObjectPhysicalProfile] = {
    "terrain_near":      _obj("terrain_near", Solidity.SOLID, "world_static", True, True),
    "terrain_far":       _obj("terrain_far", Solidity.DECORATION_ONLY, "", False, False,
                              "render-only distant terrain (§3.4)"),
    "building_wall":     _obj("building_wall", Solidity.SOLID, "world_static", True, False),
    "building_floor":    _obj("building_floor", Solidity.SOLID, "world_static", True, True),
    "building_roof":     _obj("building_roof", Solidity.SOLID, "world_static", True, False),
    "interior_wall":     _obj("interior_wall", Solidity.SOLID, "world_static", True, False),
    "stairs":            _obj("stairs", Solidity.SOLID, "world_static", True, True),
    "door":              _obj("door", Solidity.BREAKABLE, "world_static", True, True,
                              "openable/breakable; nav connector when open"),
    "doorway":           _obj("doorway", Solidity.NAVIGATION_ONLY, "", False, True,
                              "the passable gap, a nav connector"),
    "road_surface":      _obj("road_surface", Solidity.NAVIGATION_ONLY, "", False, True,
                              "drivable/walkable surface; collision from terrain"),
    "sidewalk":          _obj("sidewalk", Solidity.NAVIGATION_ONLY, "", False, True),
    "barrier":           _obj("barrier", Solidity.SOLID, "world_static", True, False,
                              "permanent barrier / jersey wall"),
    "street_furniture":  _obj("street_furniture", Solidity.MOVABLE, "dynamic_prop", True, False),
    "parked_vehicle":    _obj("parked_vehicle", Solidity.SOLID, "vehicle", True, False,
                              "stationary but a full physical obstacle (§8.2)"),
    "wreck":             _obj("wreck", Solidity.SOLID, "dynamic_prop", True, False,
                              "settled crash -> persistent obstacle (§8.1)"),
    "tree_trunk":        _obj("tree_trunk", Solidity.SOLID, "world_static", True, False),
    "foliage":           _obj("foliage", Solidity.NON_SOLID, "", False, False,
                              "canopy: overlappable, decoration"),
    "trigger_zone":      _obj("trigger_zone", Solidity.TRIGGER_ONLY, "trigger", False, False),
}


def classify_object(kind: str) -> ObjectPhysicalProfile:
    if kind not in OBJECT_SOLIDITY:
        raise KeyError(f"unknown world object kind {kind!r}; declare its solidity")
    return OBJECT_SOLIDITY[kind]


# --------------------------------------------------------------------------- #
# Godot emission — the single source of truth crosses the language boundary.
# --------------------------------------------------------------------------- #
def godot_layer_names() -> Dict[int, str]:
    """project.godot layer-name assignments (1-based indices)."""
    return {ly.godot_index: ly.name.lower() for ly in Layer}


def collision_matrix() -> List[Tuple[str, str, bool]]:
    """Full physical-block truth table over the physical body profiles."""
    physical = [p for p in BODY_PROFILES.values() if p.is_physical]
    rows: List[Tuple[str, str, bool]] = []
    for i, a in enumerate(physical):
        for b in physical[i:]:
            rows.append((a.name, b.name, physically_blocks(a, b)))
    return rows


def emit_gdscript() -> str:
    """Generate a GDScript autoload exposing the authoritative layers/masks.

    Deterministic string so it can be committed and diffed. The Godot project
    loads this as ``CollisionLayers`` and every body sets its layer/mask from it.
    """
    lines: List[str] = []
    lines.append("# GENERATED by asphodel.physics.layers.emit_gdscript() — DO NOT EDIT.")
    lines.append("# The authoritative collision matrix lives in Python (AS-PHYS-0).")
    lines.append("extends Node")
    lines.append("")
    lines.append("# Layer bit constants (Godot layer index = bit position + 1).")
    for ly in Layer:
        lines.append(f"const {ly.name} := {ly.value}  # index {ly.godot_index}")
    lines.append("")
    lines.append("# Per-body-type {layer, mask} the engine assigns on spawn.")
    lines.append("const PROFILES := {")
    for key in sorted(BODY_PROFILES):
        p = BODY_PROFILES[key]
        lines.append(
            f'\t"{key}": {{"layer": {p.layer}, "mask": {p.mask}, '
            f'"role": "{p.role.value}"}},'
        )
    lines.append("}")
    lines.append("")
    lines.append("func layer_of(kind: String) -> int:")
    lines.append('\treturn PROFILES.get(kind, {}).get("layer", 0)')
    lines.append("")
    lines.append("func mask_of(kind: String) -> int:")
    lines.append('\treturn PROFILES.get(kind, {}).get("mask", 0)')
    lines.append("")
    return "\n".join(lines) + "\n"

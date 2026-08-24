"""The item / resource authority model (Package 3A).

Python owns the canonical item vocabulary, stack semantics, gameplay effects, and
the **deterministic procedural contents of containers**. Godot may cache and
render item state, but every gameplay mutation is acknowledged here — the client
never owns the inventory.

Two data layers:

* **Item kinds** — a static registry (``ITEM_KINDS``): stack semantics + the
  minimal survival effects an item has when used. Data, not code.
* **Container contents** — a *pure function of (world seed, building id, container
  index)*. A container's loot is implicit until observed; searching it merely
  reveals what the seed already determined. This is the scalability rule made
  literal: untouched containers cost nothing (they regenerate from the seed);
  only *touched* containers enter a bounded world-delta store (see
  :mod:`asphodel.survival`). Save size never scales with the whole city.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# Item categories (stable strings).
FOOD = "food"
DRINK = "drink"
MEDICAL = "medical"
TOOL = "tool"
MISC = "misc"


@dataclass(frozen=True)
class ItemKind:
    """A kind of item: stack semantics + what using one does to survival state.

    Effect deltas are applied to :class:`~asphodel.survival.PlayerSurvival` on
    ``use``. Hunger/thirst are 0 (sated) .. 100 (critical), so food/drink carry
    **negative** deltas; health/stamina are 0..100, so restoratives are positive.
    """

    kind: str
    category: str = MISC
    stackable: bool = True
    max_stack: int = 99
    consumed_on_use: bool = False
    # survival effects on use (applied to PlayerSurvival, then clamped)
    hunger: float = 0.0
    thirst: float = 0.0
    health: float = 0.0
    stamina: float = 0.0
    label: str = ""

    def display(self) -> str:
        return self.label or self.kind.replace("_", " ")


def _k(kind, **kw) -> ItemKind:
    return ItemKind(kind=kind, **kw)


# The default registry. Consumables carry effects; tools/misc are inert on use
# (they matter for later packages: keys, phones, masks). Kinds referenced by the
# bundles' citizen inventories are included so on-person loadouts resolve cleanly.
_DEFAULT_KINDS = [
    # --- drink ---------------------------------------------------------------
    _k("water_bottle", category=DRINK, consumed_on_use=True, thirst=-40.0),
    _k("water_jug", category=DRINK, consumed_on_use=True, thirst=-70.0, max_stack=9),
    _k("soda", category=DRINK, consumed_on_use=True, thirst=-25.0, hunger=-5.0),
    # --- food ----------------------------------------------------------------
    _k("snack", category=FOOD, consumed_on_use=True, hunger=-20.0),
    _k("energy_bar", category=FOOD, consumed_on_use=True, hunger=-22.0, stamina=12.0),
    _k("canned_food", category=FOOD, consumed_on_use=True, hunger=-45.0),
    _k("mre", category=FOOD, consumed_on_use=True, hunger=-60.0, max_stack=20),
    _k("bread", category=FOOD, consumed_on_use=True, hunger=-30.0),
    # --- medical -------------------------------------------------------------
    _k("bandage", category=MEDICAL, consumed_on_use=True, health=12.0),
    _k("first_aid_kit", category=MEDICAL, consumed_on_use=True, health=30.0, max_stack=9),
    _k("medkit", category=MEDICAL, consumed_on_use=True, health=45.0, max_stack=9),
    _k("painkillers", category=MEDICAL, consumed_on_use=True, health=8.0, stamina=6.0),
    # --- tools / misc (inert on use for now) ---------------------------------
    _k("flashlight", category=TOOL, stackable=False, max_stack=1),
    _k("keys", category=TOOL, stackable=False, max_stack=1),
    _k("phone", category=TOOL, stackable=False, max_stack=1),
    _k("radio", category=TOOL, stackable=False, max_stack=1),
    _k("face_mask", category=MISC, max_stack=20),
    _k("gloves", category=MISC, max_stack=20),
    _k("id_badge", category=MISC, stackable=False, max_stack=1),
    _k("id_card", category=MISC, stackable=False, max_stack=1),
    _k("transit_pass", category=MISC, stackable=False, max_stack=1),
    _k("backpack", category=TOOL, stackable=False, max_stack=1),
    _k("laptop", category=TOOL, stackable=False, max_stack=1),
    _k("notebook", category=MISC, max_stack=9),
]

ITEM_KINDS: dict[str, ItemKind] = {k.kind: k for k in _DEFAULT_KINDS}

# A catch-all for any kind not in the registry (e.g. a bundle inventory oddity):
# inert, stackable, so unknown items still round-trip and can be dropped.
_UNKNOWN = _k("unknown", category=MISC)


def item_kind(kind: str) -> ItemKind:
    """The :class:`ItemKind` for ``kind`` (a permissive fallback for unknowns)."""
    k = ITEM_KINDS.get(str(kind))
    if k is not None:
        return k
    return ItemKind(kind=str(kind), category=MISC)


def is_known(kind: str) -> bool:
    return str(kind) in ITEM_KINDS


@dataclass
class ItemStack:
    """A quantity of one item kind. Instance identity is carried only where
    persistence needs it (dropped world items); container/inventory stacks are
    quantity-based, which is enough for deterministic take/drop/use."""

    kind: str
    quantity: int = 1

    def to_dict(self) -> dict:
        return {"kind": self.kind, "quantity": int(self.quantity)}

    @classmethod
    def from_dict(cls, d: dict) -> "ItemStack":
        return cls(kind=str(d["kind"]), quantity=int(d.get("quantity", 1)))


# --------------------------------------------------------------------------- #
# Deterministic procedural container contents
# --------------------------------------------------------------------------- #
# Loot tables per container "flavour". Each entry: (kind, weight, (min,max) qty).
_LOOT_TABLES = {
    "residential": [
        ("water_bottle", 3.0, (1, 2)), ("snack", 3.0, (1, 3)),
        ("bread", 2.0, (1, 1)), ("canned_food", 2.0, (1, 2)),
        ("bandage", 1.5, (1, 2)), ("first_aid_kit", 0.6, (1, 1)),
        ("painkillers", 1.0, (1, 1)), ("flashlight", 0.5, (1, 1)),
        ("face_mask", 1.0, (1, 3)),
    ],
    "commercial": [
        ("water_jug", 2.0, (1, 2)), ("soda", 3.0, (1, 4)),
        ("energy_bar", 3.0, (1, 4)), ("canned_food", 3.0, (1, 3)),
        ("snack", 2.5, (1, 3)), ("bread", 2.0, (1, 2)),
        ("face_mask", 1.5, (1, 5)), ("gloves", 1.0, (1, 4)),
    ],
    "medical": [
        ("first_aid_kit", 3.0, (1, 2)), ("medkit", 2.0, (1, 1)),
        ("bandage", 3.0, (1, 4)), ("painkillers", 2.5, (1, 3)),
        ("face_mask", 2.0, (2, 6)), ("gloves", 2.0, (2, 6)),
        ("water_bottle", 1.5, (1, 2)),
    ],
}


def container_flavour(world_seed: int, building_id: int) -> str:
    """Deterministic 'kind of place' a building's containers loot as.

    Buildings in the current bundles carry no category, so the flavour is a stable
    hash of (seed, building id). Roughly: a minority are medical, some commercial,
    the rest residential — a plausible mix without needing tagged geometry.
    """
    h = (int(world_seed) * 2654435761 + int(building_id) * 40503) & 0xFFFFFFFF
    r = (h % 100)
    if r < 10:
        return "medical"
    if r < 45:
        return "commercial"
    return "residential"


def n_containers(world_seed: int, building_id: int) -> int:
    """How many searchable containers a building holds (deterministic, 1..4)."""
    rng = np.random.default_rng([int(world_seed), int(building_id), 0xC0FFEE])
    return int(rng.integers(1, 5))


def container_contents(world_seed: int, building_id: int,
                       container_index: int) -> list[ItemStack]:
    """The **base** (pristine, unlooted) contents of one container.

    A pure function of the seed and the container's identity: the same container in
    the same world always contains the same items until something is taken. The
    world-delta store (see :mod:`asphodel.survival`) subtracts what has been taken;
    this function never sees that — it is the regenerable ground truth.
    """
    flavour = container_flavour(world_seed, building_id)
    table = _LOOT_TABLES[flavour]
    rng = np.random.default_rng(
        [int(world_seed), int(building_id), int(container_index)])
    n_items = int(rng.integers(0, 4))            # 0..3 stacks per container
    if n_items == 0:
        return []
    kinds = [t[0] for t in table]
    weights = np.array([t[1] for t in table], dtype=float)
    weights = weights / weights.sum()
    chosen = rng.choice(len(table), size=n_items, replace=True, p=weights)
    # Merge duplicate kinds into single stacks (deterministic order by first pick).
    out: list[ItemStack] = []
    index_of: dict[str, int] = {}
    for ci in chosen:
        kind, _, (lo, hi) = table[int(ci)]
        qty = int(rng.integers(lo, hi + 1))
        if kind in index_of:
            out[index_of[kind]].quantity += qty
        else:
            index_of[kind] = len(out)
            out.append(ItemStack(kind=kind, quantity=qty))
    return out

"""The authoritative survival-resource runtime (Package 3D/3E/3G).

This is the smallest complete gameplay loop where the player alters *persistent*
survival state through the physical world:

    move -> enter/search a place -> inspect a container -> take an item ->
    inventory changes -> use/drop it -> authoritative state changes ->
    save/load preserves it.

Everything here is authoritative Python state. Every mutation validates legality
first, mutates, and returns the new state — the client (Godot) may cache/render
but never owns the inventory or a container's contents.

Scalability rule (why save size does not scale with the city): a container's
pristine contents are a *pure function of the world seed* (see
:mod:`asphodel.items`); only **touched** containers get an entry in the
world-delta store (`_taken`). Untouched containers are always regenerable from the
seed and cost zero bytes. Dropped items are an explicit small list.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from . import items
from .items import ItemStack, item_kind


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(v)))


@dataclass
class SurvivalParams:
    """Needs tuning. Rates are per in-game **day** (scaled by the tick dt)."""

    hunger_per_day: float = 24.0
    thirst_per_day: float = 36.0
    stamina_regen_per_day: float = 40.0
    # When hunger/thirst are maxed, health bleeds at this rate per day.
    starvation_health_per_day: float = 18.0
    dehydration_health_per_day: float = 24.0


@dataclass
class PlayerSurvival:
    """The player's authoritative survival state + on-person inventory.

    hunger/thirst run 0 (sated/hydrated) .. 100 (critical); health/stamina run
    100 (full) .. 0. ``current_building`` is the building the player is inside
    (-1 = outdoors), so container access can require being at the right place.
    """

    health: float = 100.0
    stamina: float = 100.0
    hunger: float = 0.0
    thirst: float = 0.0
    inventory: dict = field(default_factory=dict)   # kind -> quantity (on person)
    current_building: int = -1

    def to_dict(self) -> dict:
        return {"health": self.health, "stamina": self.stamina,
                "hunger": self.hunger, "thirst": self.thirst,
                "inventory": dict(self.inventory),
                "current_building": int(self.current_building)}

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerSurvival":
        return cls(health=float(d.get("health", 100.0)),
                   stamina=float(d.get("stamina", 100.0)),
                   hunger=float(d.get("hunger", 0.0)),
                   thirst=float(d.get("thirst", 0.0)),
                   inventory={str(k): int(v) for k, v in d.get("inventory", {}).items()},
                   current_building=int(d.get("current_building", -1)))


class SurvivalError(Exception):
    """A rejected survival action (illegal take/use/drop). Carries a stable
    machine code for the protocol layer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Survival:
    """Authoritative survival runtime: player state + world item store + ops."""

    def __init__(self, world_seed: int, params: Optional[SurvivalParams] = None):
        self.world_seed = int(world_seed)
        self.params = params or SurvivalParams()
        self.player = PlayerSurvival()
        # world-delta store: only TOUCHED containers appear here.
        #   key "bid:idx" -> {kind: quantity_taken}
        self._taken: dict[str, dict] = {}
        # dropped world items (explicit small list)
        self.dropped: list[dict] = []
        self._drop_counter = 0

    # -------------------------------------------------------------- containers
    @staticmethod
    def _ckey(building_id: int, idx: int) -> str:
        return f"{int(building_id)}:{int(idx)}"

    def building_container_count(self, building_id: int) -> int:
        return items.n_containers(self.world_seed, building_id)

    def inspect_building(self, building_id: int) -> dict:
        """Enumerate a building's containers (counts only — contents stay implicit
        until a container is actually searched)."""
        bid = int(building_id)
        n = self.building_container_count(bid)
        return {
            "building_id": bid,
            "flavour": items.container_flavour(self.world_seed, bid),
            "n_containers": n,
            "containers": [{"index": i,
                            "searched": self._ckey(bid, i) in self._taken}
                           for i in range(n)],
        }

    def container_contents(self, building_id: int, idx: int) -> list[ItemStack]:
        """The **current** contents of a container: pristine seed contents minus
        whatever has already been taken (the world delta). Regenerable for
        untouched containers; deterministic for touched ones."""
        bid, i = int(building_id), int(idx)
        base = items.container_contents(self.world_seed, bid, i)
        taken = self._taken.get(self._ckey(bid, i), {})
        out: list[ItemStack] = []
        for st in base:
            remaining = st.quantity - int(taken.get(st.kind, 0))
            if remaining > 0:
                out.append(ItemStack(kind=st.kind, quantity=remaining))
        return out

    def search_container(self, building_id: int, idx: int) -> dict:
        """Search/open a container: reveal (and mark touched) its current contents.

        Searching creates the world-delta entry so the container is now tracked
        (its absence-of-items persists even if empty)."""
        bid, i = int(building_id), int(idx)
        n = self.building_container_count(bid)
        if not (0 <= i < n):
            raise SurvivalError("no_such_container",
                                f"building {bid} has no container {i} (0..{n-1})")
        key = self._ckey(bid, i)
        self._taken.setdefault(key, {})       # mark touched
        contents = self.container_contents(bid, i)
        return {"building_id": bid, "index": i,
                "contents": [s.to_dict() for s in contents]}

    def take_item(self, building_id: int, idx: int, kind: str,
                  quantity: int = 1) -> dict:
        """Take ``quantity`` of ``kind`` from a container into the player's
        inventory. Validates availability authoritatively (cannot take what is not
        there), removes it from the container exactly once, and records the delta."""
        bid, i = int(building_id), int(idx)
        qty = int(quantity)
        if qty <= 0:
            raise SurvivalError("bad_quantity", "quantity must be positive")
        n = self.building_container_count(bid)
        if not (0 <= i < n):
            raise SurvivalError("no_such_container",
                                f"building {bid} has no container {i}")
        available = {s.kind: s.quantity for s in self.container_contents(bid, i)}
        have = available.get(str(kind), 0)
        if have < qty:
            raise SurvivalError("insufficient_in_container",
                                f"container holds {have} of {kind!r}, cannot take {qty}")
        key = self._ckey(bid, i)
        td = self._taken.setdefault(key, {})
        td[str(kind)] = td.get(str(kind), 0) + qty
        self._add_to_inventory(str(kind), qty)
        return {"taken": {"kind": str(kind), "quantity": qty},
                "container": self.search_container(bid, i)["contents"],
                "inventory": dict(self.player.inventory)}

    # -------------------------------------------------------------- inventory
    def _add_to_inventory(self, kind: str, qty: int) -> None:
        inv = self.player.inventory
        inv[kind] = inv.get(kind, 0) + int(qty)

    def inspect_inventory(self) -> dict:
        return {"inventory": dict(self.player.inventory),
                "survival": self.player.to_dict()}

    def drop_item(self, kind: str, quantity: int, x: float, y: float,
                  zone: int = -1) -> dict:
        """Drop items from inventory into the world at (x, y). Transfers ownership
        exactly once: the quantity leaves the inventory and appears as a persistent
        dropped world item with a stable instance id."""
        kind = str(kind)
        qty = int(quantity)
        if qty <= 0:
            raise SurvivalError("bad_quantity", "quantity must be positive")
        have = self.player.inventory.get(kind, 0)
        if have < qty:
            raise SurvivalError("insufficient_in_inventory",
                                f"inventory holds {have} of {kind!r}, cannot drop {qty}")
        self.player.inventory[kind] = have - qty
        if self.player.inventory[kind] <= 0:
            del self.player.inventory[kind]
        self._drop_counter += 1
        instance_id = self._drop_counter
        item = {"instance_id": instance_id, "kind": kind, "quantity": qty,
                "x": float(x), "y": float(y), "zone": int(zone)}
        self.dropped.append(item)
        return {"dropped": item, "inventory": dict(self.player.inventory)}

    def pick_up_dropped(self, instance_id: int) -> dict:
        """Pick a previously-dropped world item back up (exactly once)."""
        iid = int(instance_id)
        for k, it in enumerate(self.dropped):
            if it["instance_id"] == iid:
                self._add_to_inventory(it["kind"], it["quantity"])
                self.dropped.pop(k)
                return {"picked_up": it, "inventory": dict(self.player.inventory)}
        raise SurvivalError("no_such_dropped_item",
                            f"no dropped item with instance id {iid}")

    def use_item(self, kind: str) -> dict:
        """Use one item from inventory: apply its survival effects and consume it
        if it is a consumable. Validates ownership (cannot use what you do not
        hold)."""
        kind = str(kind)
        have = self.player.inventory.get(kind, 0)
        if have <= 0:
            raise SurvivalError("not_owned", f"you do not hold {kind!r}")
        spec = item_kind(kind)
        p = self.player
        before = p.to_dict()
        p.hunger = _clamp(p.hunger + spec.hunger)
        p.thirst = _clamp(p.thirst + spec.thirst)
        p.health = _clamp(p.health + spec.health)
        p.stamina = _clamp(p.stamina + spec.stamina)
        consumed = bool(spec.consumed_on_use)
        if consumed:
            p.inventory[kind] = have - 1
            if p.inventory[kind] <= 0:
                del p.inventory[kind]
        return {"used": kind, "consumed": consumed,
                "effects": {"hunger": spec.hunger, "thirst": spec.thirst,
                            "health": spec.health, "stamina": spec.stamina},
                "before": before, "survival": p.to_dict(),
                "inventory": dict(p.inventory)}

    # -------------------------------------------------------------- movement
    def enter_building(self, building_id: int) -> dict:
        self.player.current_building = int(building_id)
        return {"current_building": int(building_id),
                **self.inspect_building(building_id)}

    def leave_building(self) -> dict:
        self.player.current_building = -1
        return {"current_building": -1}

    # -------------------------------------------------------------- needs tick
    def on_tick(self, dt_days: float) -> None:
        """Advance survival needs by one authoritative tick. Pure, RNG-free, and
        entirely separate from the epidemic (it never touches the sim). Hunger and
        thirst rise; a maxed need bleeds health; stamina slowly regenerates."""
        dt = float(dt_days)
        p, pr = self.player, self.params
        p.hunger = _clamp(p.hunger + pr.hunger_per_day * dt)
        p.thirst = _clamp(p.thirst + pr.thirst_per_day * dt)
        drain = 0.0
        if p.hunger >= 100.0:
            drain += pr.starvation_health_per_day * dt
        if p.thirst >= 100.0:
            drain += pr.dehydration_health_per_day * dt
        if drain > 0.0:
            p.health = _clamp(p.health - drain)
        else:
            p.stamina = _clamp(p.stamina + pr.stamina_regen_per_day * dt)

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        """Renderer-facing survival state (JSON-safe)."""
        return {
            "survival": self.player.to_dict(),
            "dropped": [dict(it) for it in self.dropped],
        }

    # -------------------------------------------------------------- save/load
    def to_state(self) -> dict:
        return {
            "world_seed": self.world_seed,
            "params": asdict(self.params),
            "player": self.player.to_dict(),
            "taken": {k: dict(v) for k, v in self._taken.items()},
            "dropped": [dict(it) for it in self.dropped],
            "drop_counter": int(self._drop_counter),
        }

    @classmethod
    def from_state(cls, state: dict) -> "Survival":
        s = cls(int(state["world_seed"]),
                SurvivalParams(**state.get("params", {})))
        s.player = PlayerSurvival.from_dict(state.get("player", {}))
        s._taken = {str(k): {str(kk): int(vv) for kk, vv in v.items()}
                    for k, v in state.get("taken", {}).items()}
        s.dropped = [dict(it) for it in state.get("dropped", [])]
        s._drop_counter = int(state.get("drop_counter", 0))
        return s

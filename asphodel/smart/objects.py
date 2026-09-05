"""Smart Objects (ASPHODEL_SMART_OBJECTS_WORK_V1 §3).

A SmartObject is a *stable identity* inside a room of a building with a kind,
a pose, an interaction point, capabilities, affordances, a capacity model and
an authoritative mutable ``state``. Behaviour is never keyed on an object's
name: a register is ``{station, transact}``; a cubicle is ``{station,
desk_work}``; whatever composes those capabilities can be used the same way.

Objects are generated deterministically from the canonical interior descriptor
(:func:`asphodel.interiors.build_interior`): every room's furniture (decor and
container fixtures) becomes an object, so a procedural retail interior knows
its registers and shelves and a procedural office knows its cubicles. The
immutable part costs zero persistent bytes; only *changed* state and the
reservation ledger are saved.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .. import interiors

Vec2 = Tuple[float, float]

REACH_M = 0.9          # how far in front of the object its interaction point is


@dataclass(frozen=True)
class Affordance:
    """What can be done with an object. ``exclusive`` affordances need the
    whole object; shared ones consume one unit of ``capacity``."""
    name: str
    exclusive: bool = True
    duration_s: float = 60.0            # default interaction duration
    requires: Tuple[str, ...] = ()      # capabilities the USER must carry (role tags)
    effects: Tuple[Tuple[str, object], ...] = ()   # state key -> value applied at completion


# kind -> (capabilities, affordances, exclusive, capacity, initial state)
OBJECT_KINDS: Dict[str, dict] = {
    # --- stations -----------------------------------------------------------
    "checkout":     dict(caps={"station", "transact", "counter"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 3600.0, ("cashier",)),
                              Affordance("transact", True, 90.0, ("cashier",)),
                              Affordance("clean", True, 120.0, (), (("dirty", False),))],
                         state={"working": True, "dirty": False, "served": 0}),
    "cubicle":      dict(caps={"station", "desk_work"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 3600.0, ("desk_worker",)),
                              Affordance("desk_work", True, 5400.0, ("desk_worker",)),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"working": True, "dirty": False, "documents_done": 0}),
    "desk":         dict(caps={"station", "desk_work"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 3600.0, ("desk_worker",)),
                              Affordance("desk_work", True, 5400.0, ("desk_worker",)),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"working": True, "dirty": False, "documents_done": 0}),
    "teacher_desk": dict(caps={"station", "desk_work"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 3600.0, ("desk_worker",)),
                              Affordance("desk_work", True, 5400.0, ("desk_worker",))],
                         state={"working": True, "dirty": False, "documents_done": 0}),
    "counter":      dict(caps={"counter", "surface"}, exclusive=False, capacity=2,
                         aff=[Affordance("clean", True, 120.0, (), (("dirty", False),)),
                              Affordance("serve", False, 120.0, ("cashier",))],
                         state={"dirty": False}),
    "workbench":    dict(caps={"station", "bench_work"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 3600.0, ()),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"working": True, "dirty": False}),
    "machine":      dict(caps={"station", "machine"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 3600.0, ())],
                         state={"working": True, "dirty": False}),
    # --- stock / storage ----------------------------------------------------
    "gondola":      dict(caps={"shelf", "stock", "browse"}, exclusive=False, capacity=3,
                         aff=[Affordance("restock", False, 240.0, ("stocker",), (("stock", 100),)),
                              Affordance("browse", False, 120.0, ()),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"stock": 60, "dirty": False}),
    "shelf":        dict(caps={"shelf", "stock", "browse"}, exclusive=False, capacity=2,
                         aff=[Affordance("restock", False, 240.0, ("stocker",), (("stock", 100),)),
                              Affordance("browse", False, 120.0, ()),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"stock": 60, "dirty": False}),
    "display":      dict(caps={"shelf", "browse"}, exclusive=False, capacity=2,
                         aff=[Affordance("browse", False, 90.0, ()),
                              Affordance("clean", True, 60.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "fridge_case":  dict(caps={"shelf", "stock", "browse"}, exclusive=False, capacity=2,
                         aff=[Affordance("restock", False, 300.0, ("stocker",), (("stock", 100),)),
                              Affordance("browse", False, 90.0, ())],
                         state={"stock": 60, "dirty": False}),
    "pallet_rack":  dict(caps={"storage", "goods"}, exclusive=False, capacity=2,
                         aff=[Affordance("retrieve_goods", False, 180.0, ("stocker",))],
                         state={"stock": 100}),
    "crate":        dict(caps={"storage", "goods"}, exclusive=False, capacity=2,
                         aff=[Affordance("retrieve_goods", False, 120.0, ("stocker",))],
                         state={"stock": 100}),
    "freezer_case": dict(caps={"storage", "goods"}, exclusive=True, capacity=1,
                         aff=[Affordance("retrieve_goods", False, 180.0, ("stocker",))],
                         state={"stock": 100}),
    "locker":       dict(caps={"storage"}, exclusive=True, capacity=1,
                         aff=[Affordance("use_storage", True, 30.0, ())],
                         state={"locked": False}),
    "filing_cabinet": dict(caps={"storage"}, exclusive=True, capacity=1,
                         aff=[Affordance("use_storage", True, 45.0, ())], state={"locked": False}),
    "cabinet":      dict(caps={"storage"}, exclusive=True, capacity=1,
                         aff=[Affordance("use_storage", True, 30.0, ())], state={"locked": False}),
    "supply_closet": dict(caps={"storage", "supplies"}, exclusive=True, capacity=1,
                         aff=[Affordance("retrieve_supplies", True, 60.0, ("cleaner",))],
                         state={"supplies": 100}),
    # --- seating / rest / living ------------------------------------------
    "chair":        dict(caps={"seat"}, exclusive=True, capacity=1,
                         aff=[Affordance("sit", True, 600.0, ())], state={"dirty": False}),
    "stool":        dict(caps={"seat"}, exclusive=True, capacity=1,
                         aff=[Affordance("sit", True, 600.0, ())], state={}),
    "armchair":     dict(caps={"seat"}, exclusive=True, capacity=1,
                         aff=[Affordance("sit", True, 900.0, ())], state={}),
    "sofa":         dict(caps={"seat"}, exclusive=False, capacity=2,
                         aff=[Affordance("sit", False, 900.0, ())], state={}),
    "bench":        dict(caps={"seat"}, exclusive=False, capacity=3,
                         aff=[Affordance("sit", False, 600.0, ())], state={}),
    "pew":          dict(caps={"seat"}, exclusive=False, capacity=4,
                         aff=[Affordance("sit", False, 600.0, ())], state={}),
    "table":        dict(caps={"table", "surface"}, exclusive=False, capacity=4,
                         aff=[Affordance("eat", False, 1200.0, ()),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "cafeteria_table": dict(caps={"table", "surface"}, exclusive=False, capacity=6,
                         aff=[Affordance("eat", False, 1200.0, ()),
                              Affordance("clean", True, 90.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "coffee_table": dict(caps={"table"}, exclusive=False, capacity=2,
                         aff=[Affordance("clean", True, 60.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "bed":          dict(caps={"bed"}, exclusive=True, capacity=1,
                         aff=[Affordance("sleep", True, 6 * 3600.0, ())], state={"made": True}),
    "toilet":       dict(caps={"toilet"}, exclusive=True, capacity=1,
                         aff=[Affordance("use_toilet", True, 180.0, ()),
                              Affordance("clean", True, 120.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "sink":         dict(caps={"sink"}, exclusive=True, capacity=1,
                         aff=[Affordance("wash", True, 60.0, ()),
                              Affordance("clean", True, 60.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "stove":        dict(caps={"stove", "cook"}, exclusive=True, capacity=1,
                         aff=[Affordance("cook", True, 900.0, ()),
                              Affordance("clean", True, 120.0, (), (("dirty", False),))],
                         state={"dirty": False, "on": False}),
    "fridge":       dict(caps={"storage", "food"}, exclusive=True, capacity=1,
                         aff=[Affordance("use_storage", True, 30.0, ())], state={"stock": 50}),
    "water_cooler": dict(caps={"drink"}, exclusive=True, capacity=1,
                         aff=[Affordance("drink", True, 45.0, ())], state={"stock": 100}),
    "exam_table":   dict(caps={"station", "treat"}, exclusive=True, capacity=1,
                         aff=[Affordance("occupy_station", True, 1800.0, ()),
                              Affordance("clean", True, 120.0, (), (("dirty", False),))],
                         state={"dirty": False}),
    "med_cart":     dict(caps={"storage", "supplies"}, exclusive=True, capacity=1,
                         aff=[Affordance("retrieve_supplies", True, 60.0, ())],
                         state={"supplies": 100}),
    "printer":      dict(caps={"machine"}, exclusive=True, capacity=1,
                         aff=[Affordance("use_machine", True, 60.0, ())],
                         state={"working": True}),
}

# a room-kind tells the first-choice zone for a worker who has nothing to do
IDLE_ZONES = {"employee_area", "break_room", "stock_room", "office", "workspace"}


@dataclass
class SmartObject:
    object_id: str
    kind: str
    building_id: int
    room_id: int
    x: float
    y: float
    facing: float
    caps: frozenset
    affordances: Tuple[Affordance, ...]
    exclusive: bool
    capacity: int
    state: Dict[str, object]
    source: str = "decor"          # decor | fixture
    source_id: int = -1
    container_index: int = -1      # authoritative loot container when a fixture

    @property
    def use_xy(self) -> Vec2:
        """Where a user stands to interact (in front of the object)."""
        return (self.x + math.cos(self.facing) * REACH_M, self.y + math.sin(self.facing) * REACH_M)

    def affordance(self, name: str) -> Optional[Affordance]:
        for a in self.affordances:
            if a.name == name:
                return a
        return None

    def has(self, *caps: str) -> bool:
        return all(c in self.caps for c in caps)

    def available(self) -> bool:
        """Physically usable (not broken/closed)."""
        return bool(self.state.get("working", True)) and not bool(self.state.get("closed", False))

    def to_row(self) -> dict:
        return {"object_id": self.object_id, "kind": self.kind, "building_id": self.building_id,
                "room_id": self.room_id, "x": round(self.x, 2), "y": round(self.y, 2),
                "facing": round(self.facing, 3), "caps": sorted(self.caps),
                "affordances": [a.name for a in self.affordances],
                "exclusive": self.exclusive, "capacity": self.capacity,
                "state": dict(self.state), "source": self.source}


def _make(bid: int, k: int, kind: str, room_id: int, x: float, y: float, facing: float,
          source: str, source_id: int, container_index: int = -1) -> SmartObject:
    spec = OBJECT_KINDS.get(kind)
    if spec is None:
        return SmartObject(f"so:{bid}:{k}", kind, int(bid), int(room_id), float(x), float(y),
                           float(facing), frozenset({"prop"}), (), True, 1, {}, source, source_id,
                           container_index)
    return SmartObject(f"so:{bid}:{k}", kind, int(bid), int(room_id), float(x), float(y),
                       float(facing), frozenset(spec["caps"]), tuple(spec["aff"]),
                       bool(spec["exclusive"]), int(spec["capacity"]), dict(spec["state"]),
                       source, source_id, container_index)


# A room contributes at most this many smart objects (and this many of one
# kind): a 200 m x 400 m school hall is furnished with thousands of decor
# pieces for presentation, but the *interaction* layer keeps a bounded,
# deterministic subset (generation order = perimeter first, then interior).
MAX_OBJECTS_PER_ROOM = 40
MAX_PER_KIND_PER_ROOM = 12


class SmartObjectRegistry:
    """All smart objects of one building, generated from its interior
    descriptor. Object ids are ``so:<building>:<k>`` with ``k`` the stable
    generation order (fixtures first, then decor), so an id is a pure function
    of (world seed, building, interior generation version)."""

    def __init__(self, building_id: int, descriptor: interiors.InteriorDescriptor):
        self.building_id = int(building_id)
        self.descriptor = descriptor
        self.objects: Dict[str, SmartObject] = {}
        self.by_room: Dict[int, List[str]] = {}
        k = 0
        for f in descriptor.fixtures:
            o = _make(building_id, k, f.kind, f.room_id, f.x, f.y, f.facing, "fixture",
                      f.fixture_id, f.container_index)
            self._add(o)
            k += 1
        per_room: Dict[int, int] = {}
        per_kind: Dict[Tuple[int, str], int] = {}
        for d in descriptor.decor:
            k += 1                      # ids stay stable whether or not the piece is kept
            if per_room.get(d.room_id, 0) >= MAX_OBJECTS_PER_ROOM:
                continue
            if per_kind.get((d.room_id, d.kind), 0) >= MAX_PER_KIND_PER_ROOM:
                continue
            per_room[d.room_id] = per_room.get(d.room_id, 0) + 1
            per_kind[(d.room_id, d.kind)] = per_kind.get((d.room_id, d.kind), 0) + 1
            o = _make(building_id, k - 1, d.kind, d.room_id, d.x, d.y, d.facing, "decor", d.decor_id)
            self._add(o)

    def _add(self, o: SmartObject) -> None:
        self.objects[o.object_id] = o
        self.by_room.setdefault(o.room_id, []).append(o.object_id)

    def __len__(self) -> int:
        return len(self.objects)

    def get(self, object_id: str) -> Optional[SmartObject]:
        return self.objects.get(object_id)

    def with_caps(self, *caps: str) -> List[SmartObject]:
        return [o for _, o in sorted(self.objects.items()) if o.has(*caps)]

    def with_affordance(self, name: str) -> List[SmartObject]:
        return [o for _, o in sorted(self.objects.items()) if o.affordance(name) is not None]

    def in_room(self, room_id: int) -> List[SmartObject]:
        return [self.objects[i] for i in self.by_room.get(int(room_id), [])]

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for o in self.objects.values():
            out[o.kind] = out.get(o.kind, 0) + 1
        return out

    # -- mutable state persistence (deltas only) -----------------------------
    def state_deltas(self) -> Dict[str, dict]:
        """Objects whose state differs from the generated default."""
        out = {}
        for oid, o in sorted(self.objects.items()):
            spec = OBJECT_KINDS.get(o.kind)
            base = dict(spec["state"]) if spec else {}
            if o.state != base:
                out[oid] = dict(o.state)
        return out

    def apply_state_deltas(self, deltas: Dict[str, dict]) -> None:
        for oid, st in (deltas or {}).items():
            o = self.objects.get(oid)
            if o is not None:
                o.state = dict(st)

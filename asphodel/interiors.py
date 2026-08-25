"""Walk-in building interiors — the authority contract + deterministic generator.

A building interior in Asphodel is a **presentation/materialization of authoritative
world state, never a new Godot-local gameplay world**. This module owns the
authoritative half:

* a versioned :class:`InteriorDescriptor` that fully describes an interior's
  *immutable* geometry (rooms, doorways, entrances, fixture anchors), and
* a **pure, deterministic, RNG-isolated** generator that reconstructs it from
  ``(world_seed, building_id, generation_version)`` + the building footprint.

The load-bearing split (handoff Package 1B):

* **Immutable base** — regenerable from city + building_id + gen_version + seed:
  room layout, walls, doorways, furniture archetype positions, and
  *container anchor identities*. Costs zero persistent bytes.
* **Persistent deltas** — stored only when the player changes something:
  a searched/looted container, an indoor dropped item, (later) a door left open.
  These live in the existing authoritative stores (:mod:`asphodel.survival`),
  keyed by the same ``container_index`` the fixtures anchor to — so the save file
  grows with *player-caused changes*, not with the number of buildings in Houston.

Crucially this module introduces **no new authoritative container/item state**. A
fixture's ``container_index`` refers to the *existing* authoritative container
``(building_id, container_index)`` whose contents come from
:func:`asphodel.items.container_contents` and whose deltas come from
:class:`asphodel.survival.Survival`. Furniture is just a deterministic physical
face on containers that already exist.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

from . import items


# Bump when the generation algorithm changes in a way that alters geometry for a
# fixed (world_seed, building_id). A saved delta records the gen_version it was
# made against; a mismatch is surfaced, never silently reinterpreted.
INTERIOR_GEN_VERSION = 1
# Bump on a breaking change to the descriptor *shape* (wire contract).
INTERIOR_SCHEMA_VERSION = 1

# Interior lifecycle states (presentation-side; authority never "unloads").
UNLOADED = "unloaded"
MATERIALIZING = "materializing"
ACTIVE = "active"
UNLOADING = "unloading"

WALL_MARGIN = 0.5          # interior hull inset from the footprint AABB (metres)
MIN_ROOM = 3.0             # do not split a rectangle below this on an axis (m)
FIXTURE_MARGIN = 0.6       # keep fixtures this far inside a room wall (m)
DOOR_WIDTH = 1.1


# --------------------------------------------------------------------------- #
# descriptor dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class Entrance:
    entrance_id: int
    x: float
    y: float
    nx: float            # inward normal (unit)
    ny: float
    room_id: int         # the room this entrance opens into

    def to_dict(self):
        return asdict(self)


@dataclass
class Room:
    room_id: int
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str

    def center(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)

    def to_dict(self):
        return asdict(self)


@dataclass
class Doorway:
    door_id: int
    room_a: int          # -1 == exterior (an entrance)
    room_b: int
    x: float
    y: float
    width: float = DOOR_WIDTH

    def to_dict(self):
        return asdict(self)


@dataclass
class Fixture:
    fixture_id: int
    room_id: int
    x: float
    y: float
    kind: str            # cabinet / fridge / shelf / desk / crate ...
    facing: float        # radians
    container_index: int # -> authoritative container (building_id, container_index)

    def to_dict(self):
        return asdict(self)


@dataclass
class InteriorDescriptor:
    """Everything needed to reconstruct an unloaded interior — immutable base only.

    Persistent deltas (looted containers, dropped items) are NOT here; they live in
    the authoritative survival store keyed by ``(building_id, container_index)``.
    """

    schema_version: int
    gen_version: int
    building_id: int
    seed: int
    archetype: str
    floor_count: int
    simplified_hull: bool          # True when a non-rectangular footprint was AABB'd
    hull: list                     # [[x,y],...] interior hull polygon (world metres)
    entrances: list                # list[Entrance]
    rooms: list                    # list[Room]
    doorways: list                 # list[Doorway]
    fixtures: list                 # list[Fixture]
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "gen_version": self.gen_version,
            "building_id": self.building_id,
            "seed": self.seed,
            "archetype": self.archetype,
            "floor_count": self.floor_count,
            "simplified_hull": self.simplified_hull,
            "hull": [[float(x), float(y)] for x, y in self.hull],
            "entrances": [e.to_dict() for e in self.entrances],
            "rooms": [r.to_dict() for r in self.rooms],
            "doorways": [d.to_dict() for d in self.doorways],
            "fixtures": [f.to_dict() for f in self.fixtures],
            "notes": list(self.notes),
        }

    def geometry_hash(self) -> str:
        """Stable hash of the immutable geometry — the determinism fingerprint."""
        payload = json.dumps(self.to_dict(), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    def container_index_for_fixture(self, fixture_id: int) -> Optional[int]:
        for f in self.fixtures:
            if f.fixture_id == fixture_id:
                return f.container_index
        return None


# --------------------------------------------------------------------------- #
# deterministic seed + archetype
# --------------------------------------------------------------------------- #
def interior_seed(world_seed: int, building_id: int, gen_version: int) -> int:
    h = (int(world_seed) * 1000003 + int(building_id) * 9176 + int(gen_version) * 131)
    return h & 0x7FFFFFFF


# fixture kinds available per archetype (deterministic pick per room).
_ARCH_FIXTURES = {
    "house": ["cabinet", "fridge", "shelf", "dresser", "crate"],
    "retail": ["shelf", "fridge", "crate", "counter"],
    "office": ["desk", "cabinet", "shelf", "crate"],
    "clinic": ["cabinet", "shelf", "fridge", "crate"],
    "generic": ["shelf", "cabinet", "crate"],
}
_ARCH_ROOMS = {
    "house": ["living", "kitchen", "bedroom", "bathroom", "hall"],
    "retail": ["shop_floor", "back_room", "storeroom"],
    "office": ["open_office", "meeting", "break_room", "storeroom"],
    "clinic": ["waiting", "exam", "supply", "office"],
    "generic": ["room"],
}


def archetype_for(world_seed: int, building_id: int, footprint_area: float,
                  height: float) -> str:
    """Deterministic interior archetype. Aligned with the container loot flavour so
    a medical building loots medical and lays out like a clinic, etc."""
    flavour = items.container_flavour(world_seed, building_id)
    if flavour == "medical":
        return "clinic"
    if flavour == "commercial":
        # taller/bigger commercial reads as office; low/wide as retail.
        return "office" if height >= 9.0 or footprint_area >= 1200.0 else "retail"
    # residential
    return "house"


# --------------------------------------------------------------------------- #
# footprint -> interior hull (AABB v1, recorded simplification)
# --------------------------------------------------------------------------- #
def _aabb(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _is_axis_aligned_rect(poly) -> bool:
    if len(poly) not in (4, 5):
        return False
    pts = poly[:4]
    xs = sorted(set(round(p[0], 3) for p in pts))
    ys = sorted(set(round(p[1], 3) for p in pts))
    return len(xs) == 2 and len(ys) == 2


# --------------------------------------------------------------------------- #
# BSP room partition (deterministic; produces a connected room tree)
# --------------------------------------------------------------------------- #
def _partition(rng, x0, y0, x1, y1, target_rooms):
    """Recursively split a rectangle into ``target_rooms`` leaves.

    Returns (rooms, doorways) where each internal split contributes a doorway on
    the split line between its two children — so the room graph is a spanning tree
    and every room is reachable. Deterministic in ``rng``.
    """
    leaves = [(x0, y0, x1, y1)]
    doors = []   # (x, y) placed on split lines; child rectangles adjacency
    # We split the currently-largest leaf until we reach the target count.
    # Track, per leaf, nothing else; doorway is placed at the split midpoint.
    # To keep adjacency correct, split in place and record the door on the seam.
    while len(leaves) < target_rooms:
        # pick the largest leaf by area that is still splittable
        idx = -1
        best_area = -1.0
        for k, (ax0, ay0, ax1, ay1) in enumerate(leaves):
            w, h = ax1 - ax0, ay1 - ay0
            if max(w, h) < 2 * MIN_ROOM:
                continue
            area = w * h
            if area > best_area:
                best_area = area
                idx = k
        if idx < 0:
            break  # nothing left splittable
        ax0, ay0, ax1, ay1 = leaves.pop(idx)
        w, h = ax1 - ax0, ay1 - ay0
        ratio = 0.4 + 0.2 * float(rng.random())      # split point in [0.4,0.6]
        if w >= h:
            sx = ax0 + w * ratio
            sx = min(max(sx, ax0 + MIN_ROOM), ax1 - MIN_ROOM)
            left = (ax0, ay0, sx, ay1)
            right = (sx, ay0, ax1, ay1)
            doors.append((sx, (ay0 + ay1) / 2.0))
            leaves.append(left)
            leaves.append(right)
        else:
            sy = ay0 + h * ratio
            sy = min(max(sy, ay0 + MIN_ROOM), ay1 - MIN_ROOM)
            bot = (ax0, ay0, ax1, sy)
            top = (ax0, sy, ax1, ay1)
            doors.append(((ax0 + ax1) / 2.0, sy))
            leaves.append(bot)
            leaves.append(top)
    return leaves, doors


def _room_containing(rooms, x, y):
    for r in rooms:
        if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1:
            return r.room_id
    # nearest by centre as a fallback
    best, bd = 0, float("inf")
    for r in rooms:
        cx, cy = r.center()
        d = (cx - x) ** 2 + (cy - y) ** 2
        if d < bd:
            bd, best = d, r.room_id
    return best


# --------------------------------------------------------------------------- #
# the generator
# --------------------------------------------------------------------------- #
def build_interior(building_id: int, world_seed: int, footprint_poly,
                   height: float = 6.0, road_xy=None,
                   gen_version: int = INTERIOR_GEN_VERSION,
                   n_containers: Optional[int] = None) -> InteriorDescriptor:
    """Reconstruct a building's immutable interior. Pure + deterministic.

    ``footprint_poly`` is the building's real footprint (list of [x,y], world
    metres). ``road_xy`` (optional) biases the entrance to a street-facing wall.
    ``n_containers`` overrides the authoritative container count (defaults to
    :func:`asphodel.items.n_containers`, keeping fixtures 1:1 with real containers).
    """
    seed = interior_seed(world_seed, building_id, gen_version)
    rng = np.random.default_rng(seed)
    notes = []

    if not footprint_poly or len(footprint_poly) < 3:
        # Safe fallback: a small box around the (assumed centroid) origin.
        footprint_poly = [[-6, -6], [6, -6], [6, 6], [-6, 6]]
        notes.append("no footprint: used fallback box")
    xmin, ymin, xmax, ymax = _aabb(footprint_poly)
    simplified = not _is_axis_aligned_rect(footprint_poly)
    if simplified:
        notes.append("non-rectangular footprint: interior hull simplified to AABB")

    # interior hull = footprint AABB inset by the wall margin
    hx0, hy0 = xmin + WALL_MARGIN, ymin + WALL_MARGIN
    hx1, hy1 = xmax - WALL_MARGIN, ymax - WALL_MARGIN
    if hx1 - hx0 < 2 * MIN_ROOM or hy1 - hy0 < 2 * MIN_ROOM:
        # tiny building: one room, no inset drama
        hx0, hy0, hx1, hy1 = xmin, ymin, xmax, ymax
        notes.append("small footprint: single-room interior")
    hull = [[hx0, hy0], [hx1, hy0], [hx1, hy1], [hx0, hy1]]

    area = (xmax - xmin) * (ymax - ymin)
    archetype = archetype_for(world_seed, building_id, area, height)

    # target room count by archetype, bounded by what fits
    room_names = _ARCH_ROOMS.get(archetype, _ARCH_ROOMS["generic"])
    max_by_size = max(1, int((hx1 - hx0) // MIN_ROOM) * int((hy1 - hy0) // MIN_ROOM))
    target = int(rng.integers(1, len(room_names) + 1))
    target = max(1, min(target, max_by_size, len(room_names)))

    rects, seam_doors = _partition(rng, hx0, hy0, hx1, hy1, target)
    rooms = []
    for i, (rx0, ry0, rx1, ry1) in enumerate(rects):
        kind = room_names[i % len(room_names)]
        rooms.append(Room(room_id=i, x0=rx0, y0=ry0, x1=rx1, y1=ry1, kind=kind))

    # doorways from the recorded split seams (spanning tree -> all reachable)
    doorways = []
    did = 0
    for (dx, dy) in seam_doors:
        # the two rooms adjacent to this seam point
        ra = _room_containing(rooms, dx - 0.01, dy)
        rb = _room_containing(rooms, dx + 0.01, dy)
        if ra == rb:
            ra = _room_containing(rooms, dx, dy - 0.01)
            rb = _room_containing(rooms, dx, dy + 0.01)
        doorways.append(Doorway(door_id=did, room_a=ra, room_b=rb, x=dx, y=dy))
        did += 1

    # entrance: the hull edge midpoint on the wall nearest the road (else +x wall)
    entrances = [_make_entrance(hull, rooms, road_xy)]

    # fixtures: exactly the authoritative container count, round-robin over rooms
    ncont = items.n_containers(world_seed, building_id) if n_containers is None else int(n_containers)
    fixtures = []
    fix_kinds = _ARCH_FIXTURES.get(archetype, _ARCH_FIXTURES["generic"])
    for ci in range(ncont):
        room = rooms[ci % len(rooms)]
        # place against a wall at a deterministic offset inside the room
        fx, fy, facing = _fixture_anchor(rng, room, ci)
        kind = fix_kinds[ci % len(fix_kinds)]
        fixtures.append(Fixture(fixture_id=ci, room_id=room.room_id, x=fx, y=fy,
                                kind=kind, facing=facing, container_index=ci))

    return InteriorDescriptor(
        schema_version=INTERIOR_SCHEMA_VERSION, gen_version=gen_version,
        building_id=int(building_id), seed=seed, archetype=archetype,
        floor_count=1, simplified_hull=simplified, hull=hull,
        entrances=entrances, rooms=rooms, doorways=doorways, fixtures=fixtures,
        notes=notes)


def _make_entrance(hull, rooms, road_xy) -> Entrance:
    hx0, hy0 = hull[0]
    hx1, hy1 = hull[2]
    # candidate wall midpoints with inward normals
    cands = [
        ((hx0 + hx1) / 2.0, hy0, 0.0, 1.0),    # south wall, normal +y
        ((hx0 + hx1) / 2.0, hy1, 0.0, -1.0),   # north wall, normal -y
        (hx0, (hy0 + hy1) / 2.0, 1.0, 0.0),    # west wall, normal +x
        (hx1, (hy0 + hy1) / 2.0, -1.0, 0.0),   # east wall, normal -x
    ]
    if road_xy is not None:
        rx, ry = road_xy
        cands.sort(key=lambda c: (c[0] - rx) ** 2 + (c[1] - ry) ** 2)
    ex, ey, nx, ny = cands[0]
    # the room just inside the entrance
    room_id = _room_containing(rooms, ex + nx * 1.0, ey + ny * 1.0)
    return Entrance(entrance_id=0, x=ex, y=ey, nx=nx, ny=ny, room_id=room_id)


def occupant_anchor(descriptor: InteriorDescriptor, citizen_id: int) -> dict:
    """A deterministic interior anchor (room + position) for an NPC occupying this
    building. Pure function of (descriptor, citizen_id) — the same citizen always
    stands in the same spot of the same interior. Kept away from walls/fixtures by
    using a citizen-hashed point in the interior of a deterministically-chosen room.
    """
    rooms = descriptor.rooms
    if not rooms:
        return {"room_id": -1, "x": 0.0, "y": 0.0}
    r = rooms[int(citizen_id) % len(rooms)]
    # a stable hashed offset within the room's inner area (avoid the very edges)
    h = (int(citizen_id) * 2654435761) & 0xFFFFFFFF
    fx = 0.25 + 0.5 * (((h >> 3) & 0xFF) / 255.0)
    fy = 0.25 + 0.5 * (((h >> 11) & 0xFF) / 255.0)
    x = r.x0 + (r.x1 - r.x0) * fx
    y = r.y0 + (r.y1 - r.y0) * fy
    return {"room_id": r.room_id, "x": float(x), "y": float(y)}


def _fixture_anchor(rng, room: Room, ci: int):
    """A deterministic spot against one of the room's walls, inside its bounds."""
    m = FIXTURE_MARGIN
    wall = int(rng.integers(0, 4))
    cx, cy = room.center()
    if wall == 0:      # against south wall
        return (cx, room.y0 + m, math.pi / 2)
    if wall == 1:      # north
        return (cx, room.y1 - m, -math.pi / 2)
    if wall == 2:      # west
        return (room.x0 + m, cy, 0.0)
    return (room.x1 - m, cy, math.pi)   # east

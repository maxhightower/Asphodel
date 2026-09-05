"""Rooms and functional zones (ASPHODEL_SMART_OBJECTS_WORK_V1 §4) and the
doorway graph used for interior locomotion (§9).

Rooms are the canonical interior descriptor's rooms (world-metre rectangles
partitioned from the footprint, joined by doorways into a spanning tree). This
module adds the *semantic zone* of a room (what it is for) and a tiny
navigation over the doorway graph: a walk from one point inside the building
to another is the chain of doorway points between their rooms. No city
navigation lives here; the TripExecutor still owns getting to the entrance.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Dict, List, Optional, Tuple

from .. import interiors

Vec2 = Tuple[float, float]

# interior room kind -> functional zone
_ZONES = {
    # residential
    "living": "living_room", "kitchen": "kitchen", "bedroom": "bedroom",
    "bathroom": "bathroom", "hall": "hall", "garage": "garage",
    # retail
    "shop_floor": "sales_floor", "back_room": "employee_area", "storeroom": "stock_room",
    "shop": "sales_floor",
    # office
    "open_office": "workspace", "meeting": "meeting_room", "break_room": "break_room",
    "office": "office",
    # medical
    "waiting": "waiting", "exam": "treatment", "supply": "storage",
    # industrial
    "warehouse": "stock_room", "workshop": "workspace", "loading": "loading_dock",
    # school / civic
    "classroom": "workspace", "hallway": "hall", "cafeteria": "break_room",
    "library": "workspace", "lobby": "lobby", "assembly": "assembly",
    "room": "room",
}


def zone_of_room_kind(kind: str) -> str:
    return _ZONES.get(kind, "room")


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class RoomGraph:
    """Rooms, zones, doorways and the entrance of one building, plus BFS
    routing across doorways. Immutable; regenerable from the descriptor."""

    def __init__(self, descriptor: interiors.InteriorDescriptor):
        self.building_id = int(descriptor.building_id)
        self.rooms: Dict[int, interiors.Room] = {r.room_id: r for r in descriptor.rooms}
        self.zones: Dict[int, str] = {r.room_id: zone_of_room_kind(r.kind) for r in descriptor.rooms}
        self.adj: Dict[int, List[Tuple[int, Vec2]]] = {r: [] for r in self.rooms}
        for d in descriptor.doorways:
            if d.room_a in self.rooms and d.room_b in self.rooms and d.room_a != d.room_b:
                self.adj[d.room_a].append((d.room_b, (d.x, d.y)))
                self.adj[d.room_b].append((d.room_a, (d.x, d.y)))
        e = descriptor.entrances[0] if descriptor.entrances else None
        self.entrance_xy: Vec2 = (e.x, e.y) if e else self._center_of(next(iter(self.rooms), 0))
        self.entrance_room: int = e.room_id if e else (next(iter(self.rooms), 0))
        # a point just inside the door, on the room floor
        self.inside_xy: Vec2 = ((e.x + e.nx * 1.2, e.y + e.ny * 1.2) if e else self.entrance_xy)

    def _center_of(self, room_id: int) -> Vec2:
        r = self.rooms.get(room_id)
        return r.center() if r else (0.0, 0.0)

    def room_of(self, xy: Vec2) -> int:
        for rid, r in self.rooms.items():
            if r.x0 - 1e-6 <= xy[0] <= r.x1 + 1e-6 and r.y0 - 1e-6 <= xy[1] <= r.y1 + 1e-6:
                return rid
        best, bd = -1, float("inf")
        for rid, r in self.rooms.items():
            d = _d(r.center(), xy)
            if d < bd:
                best, bd = rid, d
        return best

    def zone(self, room_id: int) -> str:
        return self.zones.get(int(room_id), "room")

    def rooms_of_zone(self, zone: str) -> List[int]:
        return sorted(r for r, z in self.zones.items() if z == zone)

    def route(self, from_xy: Vec2, to_xy: Vec2) -> List[Vec2]:
        """Waypoints from ``from_xy`` to ``to_xy`` through doorways (both
        points inside this building). The first waypoint is the first doorway
        (or the target itself when in the same room); the last is ``to_xy``."""
        a, b = self.room_of(from_xy), self.room_of(to_xy)
        if a == b or a < 0 or b < 0:
            return [to_xy]
        prev: Dict[int, Tuple[int, Vec2]] = {a: (-1, from_xy)}
        q = deque([a])
        while q:
            cur = q.popleft()
            if cur == b:
                break
            for nxt, door in self.adj.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = (cur, door)
                    q.append(nxt)
        if b not in prev:
            return [to_xy]                 # disconnected (should not happen): straight
        doors: List[Vec2] = []
        cur = b
        while cur != a:
            p, door = prev[cur]
            doors.append(door)
            cur = p
        doors.reverse()
        return doors + [to_xy]

    def rows(self) -> List[dict]:
        out = []
        for rid, r in sorted(self.rooms.items()):
            out.append({"room_id": rid, "kind": r.kind, "zone": self.zones[rid],
                        "x0": round(r.x0, 2), "y0": round(r.y0, 2), "x1": round(r.x1, 2),
                        "y1": round(r.y1, 2), "doors": sorted(n for n, _ in self.adj[rid])})
        return out

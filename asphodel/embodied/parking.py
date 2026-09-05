"""Parking anchor selection (ASPHODEL_EMBODIED_MOBILITY_V1 §13).

    destination building -> nearby candidates -> validated anchor -> vehicle parks

Candidates are the compiled world's ``PARKING_ANCHOR`` / ``DRIVEWAY_ANCHOR``
rows (``world/spawn_anchors.json.gz``; procedural, semantic — not surveyed
spaces). A candidate is valid only if it is reachable from a car-legal street
(access connector <= MAX_CONNECTOR_M), does not lie inside a building
footprint, does not block an entrance, and does not overlap a parked vehicle
(static chunk placements or a live VehicleInstance). Selection is
deterministic: nearest valid candidate to the destination entrance, ties by
index. Nothing here teleports a car: the chosen anchor becomes the DRIVE
leg's destination and the PARK step's ``anchor_xy``.
"""
from __future__ import annotations

import bisect
import gzip
import json
import math
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from ..mobility import Mode, MobilityGraph
from .pathing import AccessPoint, access_point

Vec2 = Tuple[float, float]

PARKING_KINDS = ("PARKING_ANCHOR", "DRIVEWAY_ANCHOR")
ENTRANCE_CLEARANCE_M = 5.0      # a parked car must not block an entrance
VEHICLE_CLEARANCE_M = 3.0       # centre-to-centre spacing between parked cars
SEARCH_RADIUS_M = 220.0         # how far from the entrance we will park
MAX_CANDIDATES = 64


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _point_in_poly(p: Vec2, poly) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > y) != (yj > y):
            xx = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < xx:
                inside = not inside
        j = i
    return inside


@dataclass
class ParkingChoice:
    index: int                  # anchor row index (stable key)
    kind: str
    xy: Vec2
    access: AccessPoint
    distance_to_entrance: float
    rejected: Dict[str, int]    # reason -> count of candidates rejected

    @property
    def node_id(self) -> str:
        return f"park:{self.index}"

    def to_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind,
                "xy": [round(self.xy[0], 2), round(self.xy[1], 2)],
                "node": self.node_id,
                "distance_to_entrance_m": round(self.distance_to_entrance, 1),
                "connector_m": round(self.access.connector_m, 1),
                "street_segment": self.access.segment_id,
                "rejected": dict(self.rejected)}


class ParkingIndex:
    """Parking candidates + the static parked-vehicle placements of a compiled
    world, loaded lazily per chunk so a session never pays for the whole city."""

    def __init__(self, bundle_dir: Optional[str], anchors: List[list],
                 entrances: Dict[int, Vec2]):
        self.bundle_dir = bundle_dir
        self.rows: List[Tuple[int, str, Vec2]] = [
            (i, r[0], (float(r[1]), float(r[2]))) for i, r in enumerate(anchors)
            if r[0] in PARKING_KINDS]
        # sorted by x for a cheap window scan
        self.rows.sort(key=lambda t: (t[2][0], t[2][1], t[0]))
        self._xs = [r[2][0] for r in self.rows]
        self.entrances = entrances
        self._ent_xs = sorted((xy[0], xy[1]) for xy in entrances.values())
        self._ent_x = [e[0] for e in self._ent_xs]
        self._chunk_cache: Dict[Tuple[int, int], List[Vec2]] = {}
        self._chunk_meta = None
        if bundle_dir:
            mp = os.path.join(bundle_dir, "world", "world_meta.json")
            if os.path.exists(mp):
                with open(mp) as f:
                    m = json.load(f)
                self._chunk_meta = (m.get("bounds_m"), float(m.get("chunk_size_m", 256.0)),
                                    m.get("chunk_grid", {}))
        # anchors occupied by live vehicles: index -> vehicle_id
        self.occupied: Dict[int, str] = {}
        self.occupied_xy: Dict[str, Vec2] = {}

    # -- static placements ---------------------------------------------------
    def _chunk_of(self, xy: Vec2) -> Optional[Tuple[int, int]]:
        if self._chunk_meta is None or not self._chunk_meta[0]:
            return None
        bounds, size, grid = self._chunk_meta
        cx = int(math.floor((xy[0] - bounds[0]) / size))
        cz = int(math.floor((xy[1] - bounds[1]) / size))
        return (cz, cx)

    def static_vehicles_near(self, xy: Vec2, radius: float) -> List[Vec2]:
        out: List[Vec2] = []
        if self._chunk_meta is None:
            return out
        bounds, size, _grid = self._chunk_meta
        seen = set()
        for dx in (-radius, 0.0, radius):
            for dz in (-radius, 0.0, radius):
                key = self._chunk_of((xy[0] + dx, xy[1] + dz))
                if key is None or key in seen:
                    continue
                seen.add(key)
                out.extend(p for p in self._load_chunk(key) if _d(p, xy) <= radius)
        return out

    def _load_chunk(self, key: Tuple[int, int]) -> List[Vec2]:
        if key in self._chunk_cache:
            return self._chunk_cache[key]
        pts: List[Vec2] = []
        path = os.path.join(self.bundle_dir, "world", "chunks", f"c_{key[0]}_{key[1]}.json.gz")
        if os.path.exists(path):
            try:
                with gzip.open(path, "rt") as f:
                    c = json.load(f)
                for row in c.get("vehicles", []) or []:
                    pts.append((float(row[1]), float(row[2])))
            except (OSError, ValueError):
                pts = []
        self._chunk_cache[key] = pts
        return pts

    # -- candidates ----------------------------------------------------------
    def candidates_near(self, xy: Vec2, radius: float) -> List[Tuple[int, str, Vec2]]:
        lo = bisect.bisect_left(self._xs, xy[0] - radius)
        hi = bisect.bisect_right(self._xs, xy[0] + radius)
        out = [r for r in self.rows[lo:hi] if _d(r[2], xy) <= radius]
        out.sort(key=lambda r: (_d(r[2], xy), r[0]))
        return out[:MAX_CANDIDATES]

    def entrances_near(self, xy: Vec2, radius: float) -> List[Vec2]:
        lo = bisect.bisect_left(self._ent_x, xy[0] - radius)
        hi = bisect.bisect_right(self._ent_x, xy[0] + radius)
        return [e for e in self._ent_xs[lo:hi] if _d(e, xy) <= radius]

    def occupy(self, index: int, vehicle_id: str, xy: Vec2) -> None:
        self.occupied[index] = vehicle_id
        self.occupied_xy[vehicle_id] = xy

    def release(self, vehicle_id: str) -> None:
        for k, v in list(self.occupied.items()):
            if v == vehicle_id:
                del self.occupied[k]
        self.occupied_xy.pop(vehicle_id, None)


def choose_parking(index: ParkingIndex, graph: MobilityGraph, dest_xy: Vec2,
                   building_polys_near: Callable[[Vec2, float], list],
                   exclude_vehicle: Optional[str] = None,
                   radius: float = SEARCH_RADIUS_M,
                   mode: Mode = Mode.CAR) -> Optional[ParkingChoice]:
    """Pick the nearest valid parking anchor to ``dest_xy``.

    ``building_polys_near(xy, r)`` returns footprint polygons within ``r`` of
    ``xy`` (the CitySpatialContext provides this). Returns None with the
    rejection census attached to the caller's failure reason when nothing is
    valid — never a fake spot at the door.
    """
    rejected: Dict[str, int] = {}

    def reject(why: str) -> None:
        rejected[why] = rejected.get(why, 0) + 1

    for idx, kind, xy in index.candidates_near(dest_xy, radius):
        if idx in index.occupied and index.occupied[idx] != exclude_vehicle:
            reject("occupied")
            continue
        ap = access_point(graph, xy, mode)
        if ap is None:
            reject("unreachable_from_road")
            continue
        if any(_point_in_poly(xy, poly) for poly in building_polys_near(xy, 40.0)):
            reject("inside_building")
            continue
        if any(_d(e, xy) < ENTRANCE_CLEARANCE_M for e in index.entrances_near(xy, ENTRANCE_CLEARANCE_M + 1)):
            reject("blocks_entrance")
            continue
        if any(_d(p, xy) < VEHICLE_CLEARANCE_M for p in index.static_vehicles_near(xy, VEHICLE_CLEARANCE_M + 1)):
            reject("overlaps_parked_vehicle")
            continue
        if any(_d(p, xy) < VEHICLE_CLEARANCE_M for vid, p in index.occupied_xy.items()
               if vid != exclude_vehicle):
            reject("overlaps_live_vehicle")
            continue
        return ParkingChoice(idx, kind, xy, ap, _d(xy, dest_xy), rejected)
    return None

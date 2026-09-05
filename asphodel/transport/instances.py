"""Persistent vehicle identity across fidelity states (AS-NAV-3, §8, §12).

A VehicleInstance keeps ONE identity from a far route-state dot, to a nearby
physical car, to a crash, to a persistent wreck — its ``vehicle_id`` never
changes across those transitions (§2.4, §12). Far fidelity advances the vehicle
along its route semantically (no physics); near fidelity is authored in Godot and
reconciles its route progress from the physical position. A settled wreck becomes
a :class:`MobilityObstruction` so the mobility graph reacts to it (§8.1, §10).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from ..mobility import Mode, MobilityGraph, Route
from ..mobility.obstructions import MobilityObstruction, ObstructionKind

Vec2 = Tuple[float, float]


class VehicleFidelity(Enum):
    ABSTRACT = "abstract"                 # exists only as a statistic
    ROUTE_SIMULATED = "route_simulated"   # progresses along a route, no physics
    PHYSICAL_CONTROLLED = "physical_controlled"  # a real Godot body under AI control
    PHYSICAL_CRASH = "physical_crash"     # collision response dominates the AI
    PERSISTENT_WRECK = "persistent_wreck"  # settled obstacle


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def route_polyline(graph: MobilityGraph, route: Route) -> List[Vec2]:
    """Oriented point list along a route (segments flipped to travel direction)."""
    if not route.segments:
        p = graph.nodes.get(route.nodes[0]) if route.nodes else None
        return [p] if p else []
    pts: List[Vec2] = []
    for i, sid in enumerate(route.segments):
        seg = graph.segments[sid]
        pu = graph.nodes[route.nodes[i]]
        poly = list(seg.polyline)
        if _d(poly[0], pu) > _d(poly[-1], pu):
            poly.reverse()
        if pts and _d(pts[-1], poly[0]) < 1e-6:
            poly = poly[1:]
        pts.extend(poly)
    return pts


def _cumulative(pts: List[Vec2]) -> List[float]:
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + _d(a, b))
    return cum


def point_at_distance(pts: List[Vec2], cum: List[float], dist: float) -> Vec2:
    if not pts:
        return (0.0, 0.0)
    if dist <= 0:
        return pts[0]
    if dist >= cum[-1]:
        return pts[-1]
    for i in range(1, len(cum)):
        if cum[i] >= dist:
            span = cum[i] - cum[i - 1]
            t = 0.0 if span < 1e-9 else (dist - cum[i - 1]) / span
            a, b = pts[i - 1], pts[i]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    return pts[-1]


def distance_of_point(pts: List[Vec2], cum: List[float], p: Vec2) -> float:
    """Distance along the polyline of the point on it nearest to ``p``."""
    best_d, best_along = math.inf, 0.0
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        abx, abz = b[0] - a[0], b[1] - a[1]
        seg_len2 = abx * abx + abz * abz
        if seg_len2 < 1e-12:
            continue
        t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * abz) / seg_len2
        t = max(0.0, min(1.0, t))
        proj = (a[0] + abx * t, a[1] + abz * t)
        dd = _d(proj, p)
        if dd < best_d:
            best_d = dd
            best_along = cum[i - 1] + math.sqrt(seg_len2) * t
    return best_along


@dataclass
class VehicleInstance:
    vehicle_id: str
    vtype: str = "car"
    owner: Optional[str] = None
    driver: Optional[str] = None
    passengers: List[str] = field(default_factory=list)
    fidelity: VehicleFidelity = VehicleFidelity.ABSTRACT
    route: Optional[Route] = None
    distance_along: float = 0.0
    speed: float = 0.0
    fuel: float = 1.0
    condition: float = 1.0
    engine_state: str = "off"
    parked_location: Optional[Vec2] = None
    lane: int = 0
    cargo: List[str] = field(default_factory=list)

    _pts: List[Vec2] = field(default_factory=list, repr=False)
    _cum: List[float] = field(default_factory=list, repr=False)

    @property
    def mode(self) -> Mode:
        return Mode.HEAVY if self.vtype in ("truck", "bus") else Mode.CAR

    # -- routing / far-sim ---------------------------------------------------
    def assign_route(self, route: Route, graph: MobilityGraph) -> None:
        self.route = route
        self._pts = route_polyline(graph, route)
        self._cum = _cumulative(self._pts)
        self.distance_along = 0.0
        self.engine_state = "on"
        if self.fidelity == VehicleFidelity.ABSTRACT:
            self.fidelity = VehicleFidelity.ROUTE_SIMULATED

    @property
    def route_length(self) -> float:
        return self._cum[-1] if self._cum else 0.0

    @property
    def route_progress(self) -> float:
        L = self.route_length
        return 0.0 if L <= 0 else min(1.0, self.distance_along / L)

    def position(self, graph: Optional[MobilityGraph] = None) -> Vec2:
        if self.parked_location is not None and self.fidelity in (
                VehicleFidelity.PERSISTENT_WRECK,):
            return self.parked_location
        return point_at_distance(self._pts, self._cum, self.distance_along)

    def current_segment(self, graph: MobilityGraph) -> Optional[str]:
        """Which route segment the vehicle is currently on (by distance)."""
        if not self.route or not self.route.segments:
            return None
        acc = 0.0
        for sid in self.route.segments:
            acc += graph.segments[sid].length
            if self.distance_along <= acc + 1e-6:
                return sid
        return self.route.segments[-1]

    def advance_far(self, dt: float, graph: MobilityGraph) -> None:
        """Progress along the route semantically (§8.1 FAR/MID). No physics."""
        if self.fidelity not in (VehicleFidelity.ROUTE_SIMULATED,
                                 VehicleFidelity.ABSTRACT):
            return
        if not self.route or self.route_length <= 0:
            return
        sid = self.current_segment(graph)
        seg = graph.segments[sid]
        # Effective speed = current dynamic cost implied speed for this vehicle.
        cost = seg.traverse_cost(self.mode)
        if not math.isfinite(cost) or cost <= 0:
            self.speed = 0.0
            return
        self.speed = seg.length / cost
        self.distance_along = min(self.route_length,
                                  self.distance_along + self.speed * dt)

    @property
    def arrived(self) -> bool:
        return self.route is not None and self.route_progress >= 1.0 - 1e-9

    # -- fidelity transitions (identity preserved, §12) ---------------------
    def promote(self, to: VehicleFidelity) -> None:
        self.fidelity = to

    def demote(self, to: VehicleFidelity) -> None:
        self.fidelity = to

    def reconcile_from_physical(self, pos: Vec2) -> None:
        """When physical (NEAR), the body is authority: derive progress from it."""
        if self._pts:
            self.distance_along = distance_of_point(self._pts, self._cum, pos)

    # -- crash / wreck (§8.1, §10) ------------------------------------------
    def to_wreck(self, graph: MobilityGraph,
                 severity: float = 1.0) -> MobilityObstruction:
        """Settle into a persistent wreck and yield the mobility obstruction it is."""
        sid = self.current_segment(graph)
        self.parked_location = self.position(graph)
        self.fidelity = VehicleFidelity.PERSISTENT_WRECK
        self.engine_state = "off"
        self.speed = 0.0
        self.condition = 0.0
        return MobilityObstruction(
            id=f"wreck:{self.vehicle_id}",
            kind=ObstructionKind.WRECK,
            affected_segment=sid,
            location=self.parked_location,
            severity=severity,
            source_entity=self.vehicle_id,
        )

    def to_dict(self, graph: Optional[MobilityGraph] = None) -> dict:
        pos = self.position(graph) if self._pts or self.parked_location else None
        return {
            "vehicle_id": self.vehicle_id,
            "type": self.vtype,
            "driver": self.driver,
            "fidelity": self.fidelity.value,
            "route_progress": round(self.route_progress, 4),
            "distance_along": round(self.distance_along, 2),
            "speed": round(self.speed, 2),
            "segment": self.current_segment(graph) if graph else None,
            "position": [round(pos[0], 2), round(pos[1], 2)] if pos else None,
            "condition": self.condition,
        }

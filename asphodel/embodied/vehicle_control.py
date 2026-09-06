"""Driving controller V1 (ASPHODEL_EMBODIED_MOBILITY_V1 §10, §12).

Deterministic, believable, not a racing AI. Consumes a :class:`PhysicalPath`
(the canonical projection of a MobilityGraph route onto street geometry) and
the vehicle's physical parameters, and produces speed/heading/progress:

* accelerate toward the segment speed limit, brake for curvature ahead;
* keep a safe following distance behind a vehicle ahead on the same path;
* yield at junctions to a vehicle that will reach the junction first;
* stop before a segment that is closed to the vehicle's mode (blocked road);
* stop at the destination anchor.

Roads are never re-planned here — replanning is the planner's (§10 "one route
authority"). When a Godot ``VehicleBody`` embodies the vehicle, physics is the
authority for where the car actually is (:meth:`reconcile_physical`).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..mobility import Mode, MobilityGraph
from ..transport.instances import distance_of_point
from .pathing import PhysicalPath

Vec2 = Tuple[float, float]


@dataclass(frozen=True)
class VehicleParams:
    max_speed: float = 16.0       # m/s (~58 km/h): city ceiling regardless of limit
    accel: float = 2.2            # m/s^2
    brake: float = 4.5            # m/s^2 comfortable braking
    length: float = 4.5           # m
    follow_gap: float = 3.0       # m standstill gap to the car ahead
    time_headway: float = 1.4     # s
    lateral_tolerance: float = 2.2  # m: a car this close to our path is "on it"
    lookahead: float = 60.0       # m
    curve_speed_k: float = 6.0    # v_max = k / turn_angle  (rad) for turns ahead
    junction_yield_m: float = 14.0
    junction_wait_max_s: float = 8.0   # deadlock breaker: go after this long


@dataclass
class OtherVehicle:
    vehicle_id: str
    xy: Vec2
    speed: float
    heading: float
    # For junction conflicts: the junction the other car will reach next and
    # its distance to it (None when not approaching one).
    next_junction: Optional[Vec2] = None
    junction_dist: float = math.inf
    started_s: float = 0.0
    parked: bool = False        # at a kerb/parking anchor (off the carriageway): never a lead
    wreck: bool = False         # an abandoned/crashed car ON the carriageway: always an obstacle


@dataclass
class VehicleController:
    path: PhysicalPath
    params: VehicleParams = field(default_factory=VehicleParams)
    dist: float = 0.0
    speed: float = 0.0
    heading: float = 0.0
    blocked: bool = False
    blocked_s: float = 0.0
    waiting_junction_s: float = 0.0
    distance_driven: float = 0.0
    following: Optional[str] = None
    yielding_to: Optional[str] = None
    road_closed_ahead: Optional[str] = None
    junctions: List[Tuple[float, Vec2]] = field(default_factory=list)  # (dist, xy)
    last_reason: str = "free"
    _events: Dict[str, int] = field(default_factory=dict)

    # -- geometry helpers ----------------------------------------------------
    @property
    def position(self) -> Vec2:
        return self.path.point_at(self.dist)

    @property
    def arrived(self) -> bool:
        return self.dist >= self.path.length - 0.05 and self.speed < 0.2

    def remaining(self) -> float:
        return max(0.0, self.path.length - self.dist)

    def next_junction(self) -> Tuple[Optional[Vec2], float]:
        for d, xy in self.junctions:
            if d > self.dist - 1.0:
                return xy, d - self.dist
        return None, math.inf

    def _curve_limit(self) -> float:
        """Speed ceiling from the sharpest turn within stopping distance."""
        pts, cum = self.path.points, self.path.cum
        limit = self.params.max_speed
        look = self.dist + max(12.0, self.speed * self.speed / (2 * self.params.brake) + 8.0)
        for i in range(1, len(pts) - 1):
            if cum[i] < self.dist:
                continue
            if cum[i] > look:
                break
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            h1 = math.atan2(b[1] - a[1], b[0] - a[0])
            h2 = math.atan2(c[1] - b[1], c[0] - b[0])
            turn = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
            if turn > 0.15:
                v = self.params.curve_speed_k / turn
                # allow braking distance: v_allowed^2 = v^2 + 2 b s
                s = cum[i] - self.dist
                v_now = math.sqrt(max(0.0, v * v + 2 * self.params.brake * s))
                limit = min(limit, max(v, v_now))
        return limit

    def _speed_limit(self, graph: MobilityGraph, mode: Mode) -> float:
        sid = self.path.segment_at(self.dist)
        if sid is None or sid not in graph.segments:
            return min(self.params.max_speed, 6.0)   # connector / driveway crawl
        seg = graph.segments[sid]
        v = seg.travel_speed(mode)
        if not math.isfinite(v) or v <= 0:
            return 0.0
        return min(self.params.max_speed, v)

    def _closed_ahead(self, graph: MobilityGraph, mode: Mode) -> Optional[Tuple[str, float]]:
        """(segment_id, distance to it) of the first closed segment ahead."""
        for sid, s0, s1 in self.path.segments:
            if sid == "conn" or s1 < self.dist:
                continue
            if s0 > self.dist + self.params.lookahead + 40.0:
                break
            seg = graph.segments.get(sid)
            if seg is None:
                continue
            if not math.isfinite(seg.traverse_cost(mode)):
                return sid, max(0.0, s0 - self.dist)
        return None

    def _window(self) -> Tuple[List[Vec2], List[float], float]:
        """The path points from just behind us to the look-ahead horizon, so a
        projection costs O(window) not O(whole route)."""
        pts, cum = self.path.points, self.path.cum
        lo, hi = self.dist - 10.0, self.dist + self.params.lookahead + 20.0
        i0 = max(0, bisect.bisect_right(cum, lo) - 1)
        i1 = min(len(pts), bisect.bisect_left(cum, hi) + 1)
        if i1 - i0 < 2:
            i1 = min(len(pts), i0 + 2)
        base = cum[i0]
        return pts[i0:i1], [c - base for c in cum[i0:i1]], base

    def _lead_gap(self, others: List[OtherVehicle], own_id: str) -> Tuple[float, Optional[str]]:
        """Gap (metres, bumper to bumper) to the nearest vehicle ahead on our path."""
        p = self.position
        best, who = math.inf, None
        wpts, wcum, wbase = self._window()
        for o in others:
            if o.vehicle_id == own_id:
                continue
            if o.parked and not o.wreck:
                continue                      # a car parked at its anchor is not traffic
            if math.hypot(o.xy[0] - p[0], o.xy[1] - p[1]) > self.params.lookahead + 10.0:
                continue
            along = wbase + distance_of_point(wpts, wcum, o.xy)
            if along <= self.dist + 0.5 or along > self.dist + self.params.lookahead:
                continue
            proj = self.path.point_at(along)
            if math.hypot(o.xy[0] - proj[0], o.xy[1] - proj[1]) > self.params.lateral_tolerance:
                continue
            # Streets are one centerline polyline (no lanes in V1): an oncoming
            # car on a two-way street is not a lead vehicle. Only same-direction
            # traffic and wrecks are followed.
            if not o.wreck:
                my_h = self.path.heading_at(along)
                if math.cos(o.heading - my_h) < 0.3:
                    continue
            gap = along - self.dist - self.params.length
            if gap < best:
                best, who = gap, o.vehicle_id
        return best, who

    def _junction_conflict(self, others: List[OtherVehicle], own_id: str,
                           own_started: float) -> Optional[str]:
        jxy, jd = self.next_junction()
        if jxy is None or jd > self.params.junction_yield_m:
            return None
        my_eta = jd / max(self.speed, 1.0)
        for o in others:
            if o.vehicle_id == own_id or o.next_junction is None:
                continue
            if math.hypot(o.next_junction[0] - jxy[0], o.next_junction[1] - jxy[1]) > 6.0:
                continue
            if o.junction_dist > 30.0:
                continue
            o_eta = o.junction_dist / max(o.speed, 1.0)
            # Yield to whoever gets there first; deterministic tie-break by id.
            if o_eta < my_eta - 1e-9 or (abs(o_eta - my_eta) <= 1e-9 and o.vehicle_id < own_id):
                return o.vehicle_id
        return None

    # -- the tick --------------------------------------------------------------
    def advance(self, dt: float, graph: MobilityGraph, mode: Mode,
                others: List[OtherVehicle], own_id: str, now_s: float = 0.0,
                started_s: float = 0.0) -> None:
        p = self.params
        if self.dist >= self.path.length - 1e-6:
            self.speed = 0.0
            return

        target = min(self._speed_limit(graph, mode), self._curve_limit())
        reason = "free"

        # blocked road ahead: stop short of it
        self.road_closed_ahead = None
        closed = self._closed_ahead(graph, mode)
        if closed is not None:
            sid, d_to = closed
            self.road_closed_ahead = sid
            stop_v = math.sqrt(max(0.0, 2 * p.brake * max(0.0, d_to - 3.0)))
            if stop_v < target:
                target, reason = stop_v, "road_closed"

        # following distance (IDM-lite)
        gap, lead = self._lead_gap(others, own_id)
        self.following = lead
        if lead is not None:
            # The braking curve applies at every gap, not only once the comfort
            # headway is breached: at the city ceiling the physical stopping
            # distance (v^2/2b = 28 m at 16 m/s) is LONGER than
            # follow_gap + v * time_headway (25 m), so gating the curve on the
            # headway starts braking too late and the car ends up inside the
            # vehicle ahead. Above the headway distance the curve is slack, so
            # this only ever binds when it must.
            v = math.sqrt(max(0.0, 2 * p.brake * max(0.0, gap - p.follow_gap)))
            if v < target:
                target, reason = v, "following"

        # junction conflict
        self.yielding_to = self._junction_conflict(others, own_id, started_s)
        if self.yielding_to is not None and self.waiting_junction_s < p.junction_wait_max_s:
            _jxy, jd = self.next_junction()
            v = math.sqrt(max(0.0, 2 * p.brake * max(0.0, jd - 2.0)))
            if v < target:
                target, reason = v, "junction"
            self.waiting_junction_s += dt if self.speed < 0.5 else 0.0
        elif self.yielding_to is None:
            self.waiting_junction_s = 0.0

        # stop at the destination
        rem = self.remaining()
        v_stop = math.sqrt(max(0.0, 2 * p.brake * rem))
        if v_stop < target:
            target, reason = v_stop, "arriving"

        # accelerate / brake toward target
        if target > self.speed:
            self.speed = min(target, self.speed + p.accel * dt)
        else:
            self.speed = max(target, self.speed - p.brake * dt)
        step = self.speed * dt
        new = min(self.path.length, self.dist + step)
        if lead is not None:
            # Hard non-penetration: whatever the integrator's step size, the
            # bumper never crosses the standstill gap behind the car ahead.
            new = min(new, self.dist + max(0.0, gap - p.follow_gap))
        self.distance_driven += new - self.dist
        self.dist = new
        self.heading = self.path.heading_at(self.dist)

        moving = self.speed > 0.2 or rem < 0.5
        if reason in ("following", "road_closed", "junction") and not moving:
            if not self.blocked:
                self._events[reason] = self._events.get(reason, 0) + 1
            self.blocked = True
            self.blocked_s += dt
        else:
            self.blocked = False
            self.blocked_s = 0.0
        self.last_reason = reason

    def reconcile_physical(self, pos: Vec2, blocked: bool, dt: float,
                           leash: float = 4.0) -> None:
        """A NEAR body reports where physics put the car. Physics holds the
        vehicle back (never ahead of its plan)."""
        along = distance_of_point(self.path.points, self.path.cum, pos)
        if along + leash < self.dist:
            self.dist = max(0.0, along + leash)
        if blocked:
            self.blocked = True
            self.blocked_s += dt
            self.speed = 0.0

    def events(self) -> Dict[str, int]:
        return dict(self._events)

    def to_state(self) -> dict:
        return {"dist": self.dist, "speed": self.speed, "heading": self.heading,
                "blocked": self.blocked, "blocked_s": self.blocked_s,
                "distance_driven": self.distance_driven,
                "waiting_junction_s": self.waiting_junction_s,
                "events": dict(self._events)}

    def restore(self, st: dict) -> None:
        self.dist = float(st.get("dist", 0.0))
        self.speed = float(st.get("speed", 0.0))
        self.heading = float(st.get("heading", 0.0))
        self.blocked = bool(st.get("blocked", False))
        self.blocked_s = float(st.get("blocked_s", 0.0))
        self.distance_driven = float(st.get("distance_driven", 0.0))
        self.waiting_junction_s = float(st.get("waiting_junction_s", 0.0))
        self._events = {str(k): int(v) for k, v in (st.get("events") or {}).items()}


def junctions_on_path(graph: MobilityGraph, path: PhysicalPath) -> List[Tuple[float, Vec2]]:
    """(distance, xy) of every graph junction (degree >= 3) the path passes."""
    out: List[Tuple[float, Vec2]] = []
    if path.route is None:
        return out
    for nid in path.route.nodes[1:-1] + ([path.route.nodes[-1]] if len(path.route.nodes) > 1 else []):
        xy = graph.nodes.get(nid)
        if xy is None:
            continue
        deg = len(graph._adj.get(nid, []))
        if deg < 3:
            continue
        d = distance_of_point(path.points, path.cum, xy)
        out.append((d, xy))
    out.sort()
    return out

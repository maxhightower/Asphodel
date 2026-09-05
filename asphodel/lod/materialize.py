"""Safe materialization when an entity enters the physical bubble (§12.1).

When a route-simulated citizen or vehicle is promoted to a physical body it must
NOT spawn inside a wall, inside another agent, inside a car, under the terrain, or
in an invalid lane. This resolver takes a desired pose plus predicates describing
the world and returns either a valid pose (possibly adjusted to the nearest valid
route location) or a deferral with a structured diagnostic. It never silently
teleports into invalid geometry (§12.1, §21).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from ..transport.instances import point_at_distance, distance_of_point

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]


@dataclass
class MaterializationRequest:
    entity_id: str
    desired_pos: Vec2
    radius: float = 0.4
    # Optional route to snap along (points + cumulative distances + target dist):
    route_pts: Optional[List[Vec2]] = None
    route_cum: Optional[List[float]] = None
    desired_progress: Optional[float] = None
    search_window: float = 25.0   # metres to search along the route / spiral
    search_step: float = 1.5


@dataclass
class MaterializationResult:
    ok: bool
    pos: Optional[Vec3]
    deferred: bool
    reason: str
    adjusted: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "pos": [round(v, 3) for v in self.pos] if self.pos else None,
            "deferred": self.deferred,
            "reason": self.reason,
            "adjusted": self.adjusted,
        }


def _overlaps(pos: Vec2, occupants: Sequence[Tuple[Vec2, float]], radius: float) -> bool:
    for (op, orad) in occupants:
        if math.hypot(pos[0] - op[0], pos[1] - op[1]) < (radius + orad):
            return True
    return False


def _candidates_along_route(req: MaterializationRequest) -> List[Vec2]:
    """Deterministic candidate poses stepping outward along the route from target."""
    out: List[Vec2] = []
    if not (req.route_pts and req.route_cum):
        return out
    base = req.desired_progress
    if base is None:
        base = distance_of_point(req.route_pts, req.route_cum, req.desired_pos)
    steps = int(req.search_window / req.search_step)
    for k in range(steps + 1):
        for sign in ((0,) if k == 0 else (+1, -1)):
            d = base + sign * k * req.search_step
            if 0.0 <= d <= req.route_cum[-1]:
                out.append(point_at_distance(req.route_pts, req.route_cum, d))
    return out


def _spiral_candidates(center: Vec2, window: float, step: float) -> List[Vec2]:
    """Deterministic outward spiral fallback when no route is available."""
    out = [center]
    r = step
    while r <= window:
        for k in range(8):
            ang = k * math.pi / 4.0
            out.append((center[0] + r * math.cos(ang), center[1] + r * math.sin(ang)))
        r += step
    return out


def resolve_materialization(
    req: MaterializationRequest,
    occupants: Sequence[Tuple[Vec2, float]] = (),
    is_inside_static: Optional[Callable[[Vec2], bool]] = None,
    terrain_height: Optional[Callable[[Vec2], float]] = None,
    valid_lane: Optional[Callable[[Vec2], bool]] = None,
) -> MaterializationResult:
    """Find a valid physical pose for ``req`` or defer with a diagnostic."""
    inside = is_inside_static or (lambda p: False)
    height = terrain_height or (lambda p: 0.0)
    lane_ok = valid_lane or (lambda p: True)

    def valid(p: Vec2) -> bool:
        return (not inside(p)) and (not _overlaps(p, occupants, req.radius)) and lane_ok(p)

    # 1) desired pose as-is.
    if valid(req.desired_pos):
        p = req.desired_pos
        return MaterializationResult(True, (p[0], height(p), p[1]), False,
                                     "materialized at desired pose", adjusted=False)

    # 2) adjust to the nearest valid location, preferring along-route candidates.
    candidates = _candidates_along_route(req)
    if not candidates:
        candidates = _spiral_candidates(req.desired_pos, req.search_window,
                                        req.search_step)
    for p in candidates:
        if p == req.desired_pos:
            continue
        if valid(p):
            return MaterializationResult(
                True, (p[0], height(p), p[1]), False,
                "adjusted to nearest valid route location", adjusted=True)

    # 3) could not resolve -> defer, never force into invalid geometry.
    reason = "blocked at desired pose"
    if inside(req.desired_pos):
        reason = "desired pose inside static geometry"
    elif _overlaps(req.desired_pos, occupants, req.radius):
        reason = "desired pose overlaps another entity"
    elif not lane_ok(req.desired_pos):
        reason = "desired pose in invalid lane"
    return MaterializationResult(False, None, True,
                                 f"deferred: {reason}; no valid pose within window")

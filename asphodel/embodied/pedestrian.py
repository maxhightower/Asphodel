"""Canonical pedestrian execution (ASPHODEL_EMBODIED_MOBILITY_V1 §6).

Consumes a :class:`PhysicalPath` and produces continuous progress: position,
velocity, heading, desired speed, segment index, distance along, destination,
collision/blocked state. Reliability over sophistication: the walker follows
the street/entrance geometry, yields to a moving vehicle directly ahead, and
stops exactly at the destination anchor. When a Godot ``CitizenBody`` embodies
the citizen, physics is the authority: :meth:`reconcile_physical` pulls
progress back to where the body actually got to and records blockage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..transport.instances import distance_of_point
from .pathing import PhysicalPath

Vec2 = Tuple[float, float]

WALK_SPEED = 1.4            # m/s (MODE_TOP_SPEED[FOOT])
YIELD_DISTANCE = 4.0        # stop when a moving vehicle is this close ahead
YIELD_HALF_WIDTH = 2.0      # ... and within this lateral distance of our path
PHYSICS_LEASH = 3.0         # physics may hold us back, never push us ahead


@dataclass
class PedestrianController:
    path: PhysicalPath
    desired_speed: float = WALK_SPEED
    dist: float = 0.0
    speed: float = 0.0
    heading: float = 0.0
    blocked: bool = False
    blocked_s: float = 0.0
    yielding: bool = False
    distance_walked: float = 0.0
    segment_index: int = 0

    @property
    def position(self) -> Vec2:
        return self.path.point_at(self.dist)

    @property
    def velocity(self) -> Vec2:
        return (self.speed * math.cos(self.heading), self.speed * math.sin(self.heading))

    @property
    def arrived(self) -> bool:
        return self.dist >= self.path.length - 1e-6

    @property
    def destination(self) -> Vec2:
        return self.path.points[-1] if self.path.points else (0.0, 0.0)

    def _vehicle_ahead(self, vehicles: List[Tuple[Vec2, float]]) -> bool:
        """Any *moving* vehicle within YIELD_DISTANCE ahead on our path?"""
        if not vehicles:
            return False
        p = self.position
        ahead = self.path.point_at(min(self.path.length, self.dist + YIELD_DISTANCE))
        for vxy, vspeed in vehicles:
            if vspeed < 0.3:
                continue
            # lateral distance to the short look-ahead chord p -> ahead
            ax, az = ahead[0] - p[0], ahead[1] - p[1]
            l2 = ax * ax + az * az
            if l2 < 1e-9:
                if math.hypot(vxy[0] - p[0], vxy[1] - p[1]) < YIELD_HALF_WIDTH:
                    return True
                continue
            t = ((vxy[0] - p[0]) * ax + (vxy[1] - p[1]) * az) / l2
            if t < -0.1 or t > 1.1:
                continue
            proj = (p[0] + ax * t, p[1] + az * t)
            if math.hypot(vxy[0] - proj[0], vxy[1] - proj[1]) < YIELD_HALF_WIDTH:
                return True
        return False

    def advance(self, dt: float, vehicles: Optional[List[Tuple[Vec2, float]]] = None,
                physical: bool = False) -> None:
        """Integrate ``dt`` seconds. ``physical`` = a Godot body is authority for
        where we end up; we still integrate the *intended* progress (the body's
        target) and let :meth:`reconcile_physical` hold it back."""
        if self.arrived:
            self.speed = 0.0
            return
        self.yielding = self._vehicle_ahead(vehicles or [])
        if self.yielding or self.blocked:
            self.speed = 0.0
            self.blocked_s += dt
            return
        self.blocked_s = 0.0
        self.speed = self.desired_speed
        step = self.speed * dt
        new = min(self.path.length, self.dist + step)
        self.distance_walked += new - self.dist
        self.dist = new
        self.heading = self.path.heading_at(self.dist)
        self._update_segment_index()

    def _update_segment_index(self) -> None:
        i = 0
        for k, (_sid, s0, s1) in enumerate(self.path.segments):
            if s0 - 1e-6 <= self.dist <= s1 + 1e-6:
                i = k
                break
        self.segment_index = i

    def reconcile_physical(self, pos: Vec2, blocked: bool, dt: float) -> None:
        """A NEAR body reports where physics actually put it.

        Progress is clamped to the body's projection (+ a small leash) — physics
        can hold the citizen back, never advance it beyond the plan. A body that
        cannot progress reports ``blocked``; the executor escalates after a
        bounded wait (§16)."""
        along = distance_of_point(self.path.points, self.path.cum, pos)
        if along + PHYSICS_LEASH < self.dist:
            self.dist = max(0.0, along + PHYSICS_LEASH)
            self._update_segment_index()
        if blocked:
            self.blocked = True
            self.blocked_s += dt
        else:
            self.blocked = False
            self.blocked_s = 0.0

    def clear_block(self) -> None:
        self.blocked = False
        self.blocked_s = 0.0

    def to_state(self) -> dict:
        return {"dist": self.dist, "speed": self.speed, "heading": self.heading,
                "blocked": self.blocked, "blocked_s": self.blocked_s,
                "distance_walked": self.distance_walked}

    def restore(self, st: dict) -> None:
        self.dist = float(st.get("dist", 0.0))
        self.speed = float(st.get("speed", 0.0))
        self.heading = float(st.get("heading", 0.0))
        self.blocked = bool(st.get("blocked", False))
        self.blocked_s = float(st.get("blocked_s", 0.0))
        self.distance_walked = float(st.get("distance_walked", 0.0))
        self._update_segment_index()

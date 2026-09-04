"""Road segment schema for StreetMap V2 (AS-NAV-0, §5.1).

The legacy bundle stores roads as undirected polylines tagged only by highway
class. This schema is the growth target: directed traversal, per-mode access,
lanes, sidewalks, capacity, and a mutable ``dynamic_state`` for runtime costs.
Not every field must be populated from day one — defaults are derived from the
road class so a legacy polyline upgrades cleanly — but the schema is here so the
graph can grow toward the full model without a re-architecture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

Vec2 = Tuple[float, float]


class Mode(Enum):
    """Travel modes the mobility graph routes separately (§5.2)."""

    FOOT = "foot"
    BICYCLE = "bicycle"
    CAR = "car"
    HEAVY = "heavy"       # trucks, buses
    EMERGENCY = "emergency"


class Direction(Enum):
    BIDIRECTIONAL = "bidirectional"
    FORWARD = "forward"    # only along the polyline order
    BACKWARD = "backward"  # only against it


# Free-flow speed a mode can achieve (m/s), before the segment speed limit caps it.
MODE_TOP_SPEED = {
    Mode.FOOT: 1.4,
    Mode.BICYCLE: 4.5,
    Mode.CAR: 33.0,
    Mode.HEAVY: 25.0,
    Mode.EMERGENCY: 40.0,
}

# Class defaults: (speed_limit m/s, lanes, allowed modes). Data-driven, not code
# dispatch — a new class is a new row, not a new branch.
_CLASS_DEFAULTS = {
    "motorway": (31.0, 3, {Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    "trunk": (25.0, 2, {Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    "primary": (18.0, 2, {Mode.FOOT, Mode.BICYCLE, Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    "secondary": (14.0, 1, {Mode.FOOT, Mode.BICYCLE, Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    "tertiary": (12.0, 1, {Mode.FOOT, Mode.BICYCLE, Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
    "residential": (8.0, 1, {Mode.FOOT, Mode.BICYCLE, Mode.CAR, Mode.EMERGENCY}),
    "service": (6.0, 1, {Mode.FOOT, Mode.BICYCLE, Mode.CAR, Mode.EMERGENCY}),
    "footway": (1.4, 0, {Mode.FOOT, Mode.BICYCLE}),
    "path": (1.4, 0, {Mode.FOOT, Mode.BICYCLE}),
    "sidewalk": (1.4, 0, {Mode.FOOT}),
    "pedestrian": (1.4, 0, {Mode.FOOT, Mode.BICYCLE}),
    "connector": (1.4, 0, {Mode.FOOT, Mode.BICYCLE, Mode.CAR, Mode.HEAVY, Mode.EMERGENCY}),
}


@dataclass
class DynamicState:
    """Mutable runtime traversal state (§5.4). Cost multipliers per segment."""

    congestion: float = 1.0          # >= 1.0; BPR-style volume delay
    blocked_fraction: float = 0.0    # 0..1 of capacity removed by obstructions
    closed_modes: set = field(default_factory=set)  # modes fully forbidden now
    obstruction_ids: set = field(default_factory=set)

    def reset(self) -> None:
        self.congestion = 1.0
        self.blocked_fraction = 0.0
        self.closed_modes = set()
        self.obstruction_ids = set()


@dataclass
class RoadSegment:
    """A directed-capable road segment (§5.1)."""

    id: str
    polyline: List[Vec2]
    road_class: str = "residential"
    directionality: Direction = Direction.BIDIRECTIONAL
    speed_limit: Optional[float] = None            # m/s; class default if None
    lanes: Optional[int] = None
    allowed_modes: Optional[set] = None            # class default if None
    sidewalks: bool = True                          # pedestrians even on a car road
    crossings: List[Vec2] = field(default_factory=list)
    structure: str = "surface"                      # surface/bridge/tunnel/ramp
    capacity: Optional[float] = None                # vehicles/hour equivalent
    turn_permissions: dict = field(default_factory=dict)
    dynamic_state: DynamicState = field(default_factory=DynamicState)

    def __post_init__(self):
        d_speed, d_lanes, d_modes = _CLASS_DEFAULTS.get(
            self.road_class, _CLASS_DEFAULTS["residential"])
        if self.speed_limit is None:
            self.speed_limit = d_speed
        if self.lanes is None:
            self.lanes = d_lanes
        if self.allowed_modes is None:
            modes = set(d_modes)
            if self.sidewalks:
                modes.add(Mode.FOOT)
            self.allowed_modes = modes
        if self.capacity is None:
            self.capacity = 600.0 * max(1, self.lanes)

    @property
    def length(self) -> float:
        return polyline_length(self.polyline)

    @property
    def start(self) -> Vec2:
        return self.polyline[0]

    @property
    def end(self) -> Vec2:
        return self.polyline[-1]

    def allows(self, mode: Mode) -> bool:
        if mode in self.dynamic_state.closed_modes:
            return False
        if self.dynamic_state.blocked_fraction >= 1.0:
            return False
        return mode in self.allowed_modes

    def travel_speed(self, mode: Mode) -> float:
        """Effective free-flow speed for a mode on this segment (m/s)."""
        return min(MODE_TOP_SPEED[mode], self.speed_limit)

    def traverse_cost(self, mode: Mode) -> float:
        """Current traversal time (seconds) including dynamic congestion.

        Returns ``math.inf`` when the mode cannot use the segment now — the
        router treats that as an absent edge, so closures reroute automatically.
        """
        if not self.allows(mode):
            return math.inf
        base = self.length / max(0.1, self.travel_speed(mode))
        ds = self.dynamic_state
        # Congestion multiplies time; partial blockage further slows by the
        # fraction of capacity lost (a half-blocked lane ~doubles delay).
        block_penalty = 1.0 / max(0.05, 1.0 - ds.blocked_fraction)
        return base * max(1.0, ds.congestion) * block_penalty


def polyline_length(points: Sequence[Vec2]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total

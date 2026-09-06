"""CitizenRuntime — the semantic decision layer for one citizen (AS-NAV-1, §6).

Holds the citizen's schedule, needs, beliefs, goals, current plan, and location,
and turns the schedule into goals, goals into an itinerary, and blockages into
replans. It NEVER moves the citizen — local navigation + physics do that. Every
runtime is fully inspectable via :meth:`debug` (machine-readable) and
:meth:`debug_text` (human-readable), which is mandatory for debugging (§6.2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..mobility import Mode, MobilityGraph
from .goals import Goal, GoalKind, GoalStack, goal_from_schedule, SOURCE_BASE_PRIORITY
from .planning import (
    Itinerary,
    build_itinerary,
    choose_mode,
    replan_travel,
)


@dataclass
class ScheduleSlot:
    """A resolved schedule entry: activity + the graph node it happens at."""

    start_hour: float
    end_hour: float
    activity: str
    location_node: str
    task: Optional[str] = None


class CitizenRuntime:
    def __init__(self, citizen_id: str, home_node: str, work_node: str,
                 schedule: List[ScheduleSlot], has_vehicle: bool = False,
                 vehicle_node: Optional[str] = None,
                 needs: Optional[Dict[str, float]] = None):
        self.citizen_id = citizen_id
        self.home_node = home_node
        self.work_node = work_node
        self.schedule = schedule
        self.has_vehicle = has_vehicle
        self.vehicle_node = vehicle_node or home_node
        self.needs = needs or {"energy": 1.0, "hunger": 0.0, "safety": 1.0,
                               "social": 0.6}
        self.beliefs: Dict[str, float] = {}
        self.relationships: Dict[str, float] = {}

        self.goals = GoalStack()
        self.active_goal: Optional[Goal] = None
        self.itinerary: Optional[Itinerary] = None
        self.current_node = home_node
        self.destination: Optional[str] = None
        self.current_mode: Optional[Mode] = None
        self.current_activity = "idle"
        self.last_replan_reason = ""
        self.current_failure = ""
        # --- embodied situation (ASPHODEL_EMBODIED_MOBILITY_V1) ---------------
        # The execution layer reports the citizen's physical situation back so
        # every (re)plan starts from where the citizen really is: inside a
        # building or not, in the car or not. The runtime still never moves.
        self.inside_building = True
        self.in_vehicle = False
        self.vehicle_id: Optional[str] = None
        # node -> {"building_id": int, "xy": (x, y)} for the nodes this citizen
        # plans between (entrances, parking anchors); filled by the embodied runtime.
        self.node_meta: Dict[str, dict] = {}
        # dest_node -> (parking_node, parking_xy) chooser for car trips; None
        # means "park at the destination node" (the legacy planner default).
        self.parking_resolver = None
        self.plan_serial = 0          # bumps whenever self.itinerary is replaced

    # -- schedule -> goal ----------------------------------------------------
    def current_slot(self, now_hour: float) -> Optional[ScheduleSlot]:
        h = now_hour % 24.0
        for s in self.schedule:
            if s.start_hour <= s.end_hour:
                if s.start_hour <= h < s.end_hour:
                    return s
            else:  # wraps past midnight
                if h >= s.start_hour or h < s.end_hour:
                    return s
        return None

    def sync_schedule(self, now_hour: float, graph: MobilityGraph) -> None:
        """Update the active goal from the schedule and (re)plan if needed."""
        slot = self.current_slot(now_hour)
        if slot is not None:
            g = goal_from_schedule(slot.activity, slot.location_node, now_hour,
                                   slot.end_hour, slot.task)
            # Replace any existing schedule-sourced goal with the fresh one.
            self.goals.goals = [x for x in self.goals.goals if x.source != "schedule"]
            self.goals.push(g)
        self._reselect(graph)

    # -- emergencies / need goals (§11) -------------------------------------
    def push_goal(self, goal: Goal, graph: Optional[MobilityGraph] = None) -> bool:
        """Add a competing goal. Returns True if it preempts the current plan."""
        preempts = self.goals.would_preempt(goal)
        self.goals.push(goal)
        if graph is not None:
            self._reselect(graph)
        return preempts

    def push_emergency(self, target_node: str, reason: str,
                       graph: Optional[MobilityGraph] = None,
                       priority: Optional[float] = None) -> bool:
        g = Goal(GoalKind.RETRIEVE, target=target_node, reason=reason,
                 source="emergency",
                 priority=priority if priority is not None
                 else SOURCE_BASE_PRIORITY["emergency"])
        return self.push_goal(g, graph)

    def _reselect(self, graph: MobilityGraph) -> None:
        prev = self.active_goal
        self.active_goal = self.goals.select_active()
        if self.active_goal is None:
            self.itinerary = None
            self.destination = None
            self.current_activity = "idle"
            return
        changed = prev is None or prev.id != self.active_goal.id
        if changed or self.itinerary is None:
            self._plan_for_active(graph)

    # -- embodied situation hooks ------------------------------------------
    def note_situation(self, node: Optional[str] = None,
                       inside_building: Optional[bool] = None,
                       in_vehicle: Optional[bool] = None,
                       vehicle_node: Optional[str] = None) -> None:
        """The execution layer reports where the citizen physically is."""
        if node is not None:
            self.current_node = node
        if inside_building is not None:
            self.inside_building = bool(inside_building)
        if in_vehicle is not None:
            self.in_vehicle = bool(in_vehicle)
        if vehicle_node is not None:
            self.vehicle_node = vehicle_node

    def _meta(self, node: Optional[str], key: str):
        if node is None:
            return None
        return (self.node_meta.get(node) or {}).get(key)

    def _build(self, graph: MobilityGraph, dest: str, mode: Mode,
               activity: Optional[str]) -> Itinerary:
        park_node, park_xy = None, None
        if mode in (Mode.CAR, Mode.HEAVY) and self.parking_resolver is not None:
            chosen = self.parking_resolver(dest)
            if chosen is not None:
                park_node, park_xy = chosen
        veh_node = self.vehicle_node
        return build_itinerary(
            graph, self.current_node, dest, mode,
            vehicle_node=veh_node, parking_node=park_node, activity=activity,
            start_inside_building=self.inside_building,
            start_in_vehicle=self.in_vehicle and mode in (Mode.CAR, Mode.HEAVY),
            vehicle_id=self.vehicle_id,
            origin_building_id=self._meta(self.current_node, "building_id"),
            dest_building_id=self._meta(dest, "building_id"),
            origin_xy=self._meta(self.current_node, "xy"),
            dest_xy=self._meta(dest, "xy"),
            vehicle_xy=self._meta(veh_node, "xy"),
            parking_xy=park_xy)

    def _set_itinerary(self, it: Optional[Itinerary]) -> None:
        self.itinerary = it
        self.plan_serial += 1

    def _plan_for_active(self, graph: MobilityGraph) -> None:
        g = self.active_goal
        if g is None:
            return
        travel = g.kind in (GoalKind.ARRIVE_AT, GoalKind.RETRIEVE, GoalKind.FLEE)
        # A DO_ACTIVITY / IDLE goal somewhere else first requires getting there:
        # the activity begins because the citizen ARRIVED, never because the
        # clock said so (ASPHODEL_EMBODIED_MOBILITY_V1 §15).
        activity = None
        if not travel and g.target and g.target != self.current_node \
                and g.target in graph.nodes:
            travel = True
            activity = g.activity or g.kind.value
        if travel:
            dest = g.target
            dist = self._straight_dist(graph, self.current_node, dest)
            if self.in_vehicle:
                mode = Mode.CAR
            else:
                mode = choose_mode(dist, self.has_vehicle)
            it = self._build(graph, dest, mode, activity)
            if not it.ok and mode != Mode.FOOT:
                self.in_vehicle = False
                it = self._build(graph, dest, Mode.FOOT, activity)
            self._set_itinerary(it)
            self.destination = dest
            self.current_mode = it.mode
            self.current_failure = "" if it.ok else it.failure
            self.current_activity = ("traveling" if it.ok
                                     else "blocked (no route)")
        else:  # DO_ACTIVITY / IDLE in place
            self._set_itinerary(None)
            self.destination = None
            self.current_mode = None
            self.current_activity = g.activity or g.kind.value
            self.current_failure = ""

    # -- blockage / replanning (§7.2) ---------------------------------------
    def on_blockage(self, graph: MobilityGraph, reason: str = "route blocked") -> None:
        """A local nav failure escalated to a strategic replan under new state."""
        if self.itinerary is None or self.destination is None:
            return
        new_it, why = replan_travel(
            graph, self.itinerary, self.current_node, self.destination,
            vehicle_node=self.vehicle_node, runtime=self)
        self._set_itinerary(new_it)
        self.last_replan_reason = f"{reason}: {why}"
        self.current_mode = new_it.mode
        self.current_failure = "" if new_it.ok else new_it.failure
        if not new_it.ok:
            self.current_activity = "stuck (replan failed)"

    def _straight_dist(self, graph: MobilityGraph, a: str, b: str) -> float:
        pa, pb = graph.nodes.get(a), graph.nodes.get(b)
        if pa is None or pb is None:
            return 0.0
        return math.hypot(pb[0] - pa[0], pb[1] - pa[1])

    # -- debug reasoning (MANDATORY, §6.2) ----------------------------------
    def debug(self) -> dict:
        """Machine-readable answer to: what/why/where/goal/plan/mode/failure."""
        g = self.active_goal
        return {
            "citizen_id": self.citizen_id,
            "doing": self.current_activity,
            "active_goal": g.to_dict() if g else None,
            "why": g.reason if g else "no active goal",
            "destination": self.destination,
            "mode": self.current_mode.value if self.current_mode else None,
            "at_node": self.current_node,
            "candidate_goals": [x.to_dict() for x in self.goals.goals],
            "plan": self.itinerary.to_dict() if self.itinerary else None,
            "last_replan": self.last_replan_reason or None,
            "current_failure": self.current_failure or None,
            "needs": {k: round(v, 2) for k, v in self.needs.items()},
        }

    def debug_text(self) -> str:
        d = self.debug()
        lines = [f"Citizen {d['citizen_id']}"]
        if d["active_goal"]:
            lines.append(f"Active goal:\n  {d['active_goal']['kind'].upper()}"
                         f"({d['active_goal']['target']})")
            lines.append(f"Reason:\n  {d['why']}")
        lines.append(f"Destination:\n  {d['destination']}")
        lines.append(f"Mode:\n  {d['mode']}")
        if d["plan"]:
            steps = "\n  ".join(Itinerary.describe(self.itinerary))
            lines.append(f"Plan:\n  {steps}")
        if d["last_replan"]:
            lines.append(f"Replan:\n  {d['last_replan']}")
        lines.append(f"Current failure:\n  {d['current_failure'] or 'none'}")
        return "\n".join(lines)

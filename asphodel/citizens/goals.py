"""Goals, priorities, and interruption (AS-NAV-1 §6.1, AS-NAV-5 §11).

A schedule is an INPUT to goals, not a competing AI. Each schedule entry becomes a
prioritized :class:`Goal`; needs/beliefs/emergencies push competing goals; the
highest-priority goal wins and can interrupt the current plan. This is the
mechanism that lets a worker abandon a shift to retrieve a child (§11) — a
priority comparison, not a bespoke story system.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

_counter = itertools.count()


class GoalKind(Enum):
    ARRIVE_AT = "arrive_at"       # be at a location by a deadline
    DO_ACTIVITY = "do_activity"   # perform a scheduled/needed activity in place
    RETRIEVE = "retrieve"         # go fetch someone/something (emergency-ish)
    FLEE = "flee"                 # get away from a hazard
    IDLE = "idle"


# Baseline priorities by source; the scheduler and emergencies scale from here.
SOURCE_BASE_PRIORITY = {
    "idle": 0.10,
    "need": 0.35,
    "schedule": 0.55,
    "social": 0.45,
    "emergency": 0.92,
    "player": 1.0,
}


@dataclass
class Goal:
    kind: GoalKind
    target: str                     # location id (graph node / building)
    reason: str = ""
    source: str = "schedule"
    priority: float = 0.5
    deadline: Optional[float] = None  # game hour
    activity: Optional[str] = None    # for DO_ACTIVITY
    id: int = field(default_factory=lambda: next(_counter))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "target": self.target,
            "reason": self.reason,
            "source": self.source,
            "priority": round(self.priority, 3),
            "deadline": self.deadline,
            "activity": self.activity,
        }


class GoalStack:
    """Holds candidate goals and selects the active one by priority.

    Hysteresis prevents thrashing: a new goal only preempts the current active
    goal if it is meaningfully higher priority. Ties break by earliest deadline
    then by insertion order (older first), so selection is deterministic.
    """

    def __init__(self, preempt_margin: float = 0.05):
        self.goals: List[Goal] = []
        self.preempt_margin = preempt_margin
        self._active: Optional[Goal] = None
        # Per-stack id sequence: goal ids are unique within a citizen and
        # reproducible across save/load (the module counter is only the
        # default for goals built outside a stack).
        self.seq = 0

    def push(self, goal: Goal) -> None:
        goal.id = self.seq
        self.seq += 1
        self.goals.append(goal)

    def remove(self, goal_id: int) -> None:
        self.goals = [g for g in self.goals if g.id != goal_id]
        if self._active is not None and self._active.id == goal_id:
            self._active = None

    def complete_active(self) -> None:
        if self._active is not None:
            self.remove(self._active.id)

    def _best(self) -> Optional[Goal]:
        if not self.goals:
            return None
        return sorted(
            self.goals,
            key=lambda g: (-g.priority,
                           g.deadline if g.deadline is not None else 1e9,
                           g.id),
        )[0]

    def select_active(self) -> Optional[Goal]:
        """Return the active goal, applying preemption hysteresis."""
        best = self._best()
        if best is None:
            self._active = None
            return None
        if self._active is None:
            self._active = best
        elif best.id != self._active.id:
            # switch only if best is clearly better, or the current one is gone
            if self._active not in self.goals:
                self._active = best
            elif best.priority >= self._active.priority + self.preempt_margin:
                self._active = best
        return self._active

    def would_preempt(self, new: Goal) -> bool:
        cur = self.select_active()
        if cur is None:
            return True
        return new.priority >= cur.priority + self.preempt_margin


# --- schedule -> goal -------------------------------------------------------
# Map a schedule activity to the goal it implies. Data-driven (§6.1).
def goal_from_schedule(activity: str, location: str, now_hour: float,
                       end_hour: Optional[float] = None,
                       task: Optional[str] = None) -> Goal:
    """Turn a schedule entry into the goal it implies.

    ``commute``/``commute_home`` -> ARRIVE_AT(destination) with the shift start as
    deadline; ``work``/``errand``/``leisure`` -> DO_ACTIVITY in place; ``sleep``
    -> IDLE. Priority is the schedule baseline, nudged up as a deadline nears.
    """
    base = SOURCE_BASE_PRIORITY["schedule"]
    act = activity.lower()
    if act in ("commute", "commute_home", "commute_to_work"):
        # Urgency rises as the deadline approaches.
        urgency = 0.0
        if end_hour is not None and end_hour > now_hour:
            urgency = max(0.0, min(0.2, 0.2 * (1.0 - (end_hour - now_hour) / 2.0)))
        return Goal(GoalKind.ARRIVE_AT, target=location,
                    reason=f"scheduled {activity} toward {location}",
                    source="schedule", priority=base + urgency, deadline=end_hour)
    if act == "sleep":
        return Goal(GoalKind.IDLE, target=location, reason="rest period",
                    source="idle", priority=SOURCE_BASE_PRIORITY["idle"])
    return Goal(GoalKind.DO_ACTIVITY, target=location, activity=activity,
                reason=f"scheduled {activity}"
                       + (f": {task}" if task else ""),
                source="schedule", priority=base, deadline=end_hour)

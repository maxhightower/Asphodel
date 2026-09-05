"""Citizen intention runtime (AS-NAV-1/2/5): schedule -> goals -> itinerary.

Note: this is the semantic *decision* layer and is distinct from ``asphodel.citizen``
(the population spawn/schedule catalog). Movement is physics; this only decides.
"""
from __future__ import annotations

from .goals import Goal, GoalKind, GoalStack, goal_from_schedule, SOURCE_BASE_PRIORITY
from .planning import (
    Itinerary,
    PlanStep,
    StepKind,
    build_itinerary,
    choose_mode,
    replan_travel,
)
from .runtime import CitizenRuntime, ScheduleSlot

__all__ = [
    "Goal",
    "GoalKind",
    "GoalStack",
    "goal_from_schedule",
    "SOURCE_BASE_PRIORITY",
    "Itinerary",
    "PlanStep",
    "StepKind",
    "build_itinerary",
    "choose_mode",
    "replan_travel",
    "CitizenRuntime",
    "ScheduleSlot",
]

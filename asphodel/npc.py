"""NPC helper layer (Phase 11 / M2): the simulation-side vocabulary for turning a
citizen's daily *schedule* into a live *activity*, without the micro tier ever
learning about rich citizen objects.

Design constraints preserved from the SP1 plan:

* **Activity is a logical label, not physical clustering.** Assigning an activity
  never moves an agent, changes its density, or touches the epidemic — that would
  silently invalidate the calibrated transmission model. Activity is presentation
  + (later) a hook for reactive behaviour, nothing more in M2.
* **Pure and deterministic.** Everything here is arithmetic + table lookup on the
  citizen schedule and the in-game hour. No RNG, no wall-clock.

``micro.py`` stays ignorant of ``CitizenProfile``; the orchestrator uses these
helpers to fill an :class:`~asphodel.micro.AgentZone`'s ``activity`` int8 array.
"""

from __future__ import annotations

from .citizen import ScheduleEntry, _current_block


# Activity codes stored in AgentZone.activity (int8). Stable mapping — the wire
# snapshot and any renderer key off these integers.
IDLE, SLEEP, COMMUTE, WORK, ERRAND, LEISURE = 0, 1, 2, 3, 4, 5
ACTIVITY_NAMES = ("idle", "sleep", "commute", "work", "errand", "leisure")
ACTIVITY_CODE = {name: i for i, name in enumerate(ACTIVITY_NAMES)}
N_ACTIVITIES = len(ACTIVITY_NAMES)


def activity_code(name: str) -> int:
    """Map a schedule activity string to its stable int8 code (unknown -> IDLE)."""
    return ACTIVITY_CODE.get(str(name).lower(), IDLE)


def activity_name(code: int) -> str:
    """Inverse of :func:`activity_code`."""
    c = int(code)
    return ACTIVITY_NAMES[c] if 0 <= c < N_ACTIVITIES else "idle"


def hour_of_day(tick: int, dt: float, start_hour: float = 0.0) -> float:
    """In-game hour in [0,24) at a simulation tick.

    ``dt`` is the tick length in *days* (``ScenarioConfig.dt``); one tick is
    ``dt * 24`` in-game hours. ``start_hour`` is the wall-clock hour the world
    began at (the player's spawn hour).
    """
    return (start_hour + tick * dt * 24.0) % 24.0


def activity_at_hour(schedule: list[ScheduleEntry], hour: float) -> int:
    """The activity code a citizen's schedule prescribes at ``hour``.

    Reuses the citizen module's block lookup (which handles past-midnight wrap),
    so the NPC layer and the character-screen narrative agree on "what am I doing
    right now". No schedule -> IDLE.
    """
    if not schedule:
        return IDLE
    block = _current_block(schedule, hour % 24.0)
    return activity_code(block.activity) if block is not None else IDLE

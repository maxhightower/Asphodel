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


# ===========================================================================
# M3 / SP2: reactive affordances — need vector + advertised-action chooser
# ===========================================================================
# Action codes stored in AgentZone.chosen_action (int8). Stable mapping.
CONTINUE, SHELTER, FLEE, SEEK, SIGNATURE = 0, 1, 2, 3, 4
ACTION_NAMES = ("continue_schedule", "shelter", "flee", "seek", "signature")
ACTION_CODE = {name: i for i, name in enumerate(ACTION_NAMES)}
N_ACTIONS = len(ACTION_NAMES)

# The need vector an agent scores affordances against.
NEEDS = ("safety", "fatigue", "hunger", "social")

# Which need each action chiefly satisfies (for scoring).
_ACTION_NEED = {
    "continue_schedule": "fatigue",   # routine satisfies low-arousal needs
    "shelter": "safety",
    "flee": "safety",
    "seek": "hunger",
}


def action_code(name: str) -> int:
    return ACTION_CODE.get(str(name).lower(), CONTINUE)


def action_name(code: int) -> str:
    c = int(code)
    return ACTION_NAMES[c] if 0 <= c < N_ACTIONS else "continue_schedule"


def choose_action(advertisements, needs, rng, top_k: int = 2) -> str:
    """Score each advertised ``(action, utility)`` by ``utility * the need it
    serves``, then draw one of the top-k **weighted by score** (The Sims
    anti-robotic rule: not pure argmax, but the stronger affordance wins more
    often — so a rising need materially shifts the action mix, while ties stay
    stochastic).

    Seeded entirely by the caller-supplied per-citizen ``rng`` — deterministic,
    and never touches ``AgentZone.rng``. Empty advertisements -> keep the
    schedule. This is the whole "AI": a weighted lookup + a seeded draw, no
    planner, no behaviour tree.
    """
    if not advertisements:
        return "continue_schedule"
    scored = sorted(
        ((float(u) * float(needs.get(_ACTION_NEED.get(a, "safety"), 0.0)), a)
         for a, u in advertisements),
        key=lambda t: t[0], reverse=True,
    )
    k = min(top_k, len(scored))
    top = scored[:k]
    weights = [max(s, 0.0) for s, _ in top]
    total = sum(weights)
    if total <= 0.0:
        # all-zero scores: uniform among the top-k (deterministic via rng)
        return top[int(rng.integers(k))][1]
    # Weighted draw: cumulative-threshold on a single uniform sample.
    u = float(rng.random()) * total
    acc = 0.0
    for w, (_, action) in zip(weights, top):
        acc += w
        if u < acc:
            return action
    return top[-1][1]


def visual_seed(citizen_id: int) -> int:
    """A stable, deterministic per-citizen appearance seed (M6 recognition).

    A named-roster member must look the same each time the player returns, so
    body/clothing colours are keyed on this seed rather than on anything transient.
    Kept as a tiny integer splitmix so the GDScript renderer can reproduce the exact
    same value (``0 <= seed < 2**31``). ``citizen_id == -1`` (anonymous) -> 0.
    """
    c = int(citizen_id)
    if c < 0:
        return 0
    x = (c * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF
    x ^= (x >> 16)
    x = (x * 0x85EBCA6B) & 0xFFFFFFFF
    x ^= (x >> 13)
    return x & 0x7FFFFFFF


def default_needs(safety: float) -> dict:
    """A citizen's need vector with a live ``safety`` term (from zone belief) and
    modest baseline routine needs. Kept tiny and data-light by design."""
    return {"safety": float(safety), "fatigue": 0.3, "hunger": 0.2, "social": 0.2}


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

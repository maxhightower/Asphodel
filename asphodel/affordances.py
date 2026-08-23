"""Advertised affordances (Phase 11 / M3 SP2).

The Sims' SmartObject inversion: the *environment* advertises weighted actions;
the agent scores them against its needs and picks (see
:func:`asphodel.npc.choose_action`). This module is a pure **projection** of
situation data (tags describing a place/hazard, plus the live zone belief) into
``[(action, utility)]`` — no new content, no numpy, no RNG. Adding a hazard or a
refuge is a single data entry in ``_TAG_AFFORDANCE``.

Kept deliberately small in M3: hazard tags advertise ``flee``; refuge/supply tags
advertise ``shelter``/``seek``; and a belief-scaled ``shelter`` + inverse-belief
``continue_schedule`` baseline is always available, so a tense place invites
sheltering and a calm one invites routine.
"""

from __future__ import annotations


# Tag -> (affordance it implies, base utility in [0,1]).
_TAG_AFFORDANCE = {
    "fire": ("flee", 0.9), "flood": ("flee", 0.9), "structural": ("flee", 0.8),
    "hazmat": ("flee", 0.85), "crowd": ("flee", 0.5),
    "shelter": ("shelter", 0.7), "refuge": ("shelter", 0.7),
    "supplies": ("seek", 0.6), "keys_access": ("seek", 0.5), "tools": ("seek", 0.4),
}


def advertise_from_tags(tags) -> list[tuple[str, float]]:
    """Affordances implied purely by a place's tags."""
    out = []
    for t in (tags or ()):
        key = str(t).lower()
        if key in _TAG_AFFORDANCE:
            out.append(_TAG_AFFORDANCE[key])
    return out


def advertise(environment_tags=None, belief: float = 0.0) -> list[tuple[str, float]]:
    """Affordances offered to an agent in a place with these tags under this zone
    belief.

    Higher belief raises the standing ``shelter`` offer (the safe default) and
    lowers the pull of ``continue_schedule`` — so a tense-but-unhazardous place
    still invites sheltering, while a calm place favours routine.
    """
    b = float(belief)
    ads = advertise_from_tags(environment_tags)
    ads.append(("shelter", 0.2 + 0.6 * b))            # always-available baseline
    ads.append(("continue_schedule", max(0.1, 1.0 - b)))
    return ads

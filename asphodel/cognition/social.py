"""The social-action grammar (§11, §14, §15, §20).

Social actions are semantic acts between citizens. They operate through
world semantics — a HELP is a real smart-object task the WorkRuntime runs, a
WARN creates a communicated memory with provenance in the recipient, an
AVOID is a constraint the existing planner / task selection honours. Each
carries a tiny deterministic utterance label (WARN_THREAT, ASK_HELP, THANK,
ACKNOWLEDGE) that a later dialogue milestone can verbalize.

Information sharing is bounded (§15): it needs an encounter or a strong
tie (a call), a salient fact, a per-pair cooldown, duplicate suppression
(one telling of one origin fact per recipient), a hop limit, and a
sociability-scaled deterministic roll.
"""
from __future__ import annotations

from ..world_source.detrand import hash64
from .memory import (ATTACK_SEEN, ATTACKED_BY, CORPSE_SEEN, DEATH_SEEN, THREAT_PERSON,
                     WORKPLACE_DISRUPTED)

HELP = "HELP"
WARN = "WARN"
SHARE_INFORMATION = "SHARE_INFORMATION"
CHECK_ON = "CHECK_ON"
AVOID_PERSON = "AVOID_PERSON"
AVOID_LOCATION = "AVOID_LOCATION"
FOLLOW = "FOLLOW"

UTTERANCE = {HELP: "OFFER_HELP", WARN: "WARN_THREAT", SHARE_INFORMATION: "SHARE_INFO",
             CHECK_ON: "CHECK_ON", AVOID_PERSON: "", AVOID_LOCATION: "", FOLLOW: ""}
THANK = "THANK"
ACKNOWLEDGE = "ACKNOWLEDGE"

# what is worth telling: kind -> minimum effective confidence
SHAREABLE = {THREAT_PERSON: 0.30, ATTACK_SEEN: 0.30, ATTACKED_BY: 0.30, CORPSE_SEEN: 0.35,
             DEATH_SEEN: 0.30, WORKPLACE_DISRUPTED: 0.40}
MAX_HOPS = 2                      # a fact told twice on is not told again
PAIR_COOLDOWN_S = 1800.0          # one telling per pair per half hour
CALL_FAMILIARITY = 0.55           # a call needs a strong tie (or a household / workplace tie)
CALL_SALIENCE = 0.85              # and a major fact
MAX_CALLS_PER_FACT = 3
SHARE_ROLL_BASE = 0.55            # + 0.45 * sociability


def share_roll(seed: int, sender: int, recipient: int, origin_id: str, sociability: float) -> bool:
    u = (hash64(int(seed), "share", int(sender), int(recipient), str(origin_id)) % 10_000) / 10_000.0
    return u < SHARE_ROLL_BASE + 0.45 * float(sociability)


def told_confidence(sender_conf: float, trust: float, suspicion: float) -> float:
    """What a recipient makes of a telling: the sender's confidence scaled by
    how much the recipient trusts the sender, discounted by suspicion."""
    return max(0.0, min(1.0, sender_conf * (0.45 + 0.55 * trust) * (1.0 - 0.4 * suspicion)))

"""Deterministic surface renderer (§24). Templates over semantic acts; the
epistemic status chooses the frame ("I saw" / "X told me" / "I heard" /
"I think" / "I'm not sure" / "I don't know"); relationship warmth chooses a
small variant. No model, no network, no state. A future LLM could replace
this module only as a realizer of the same frame (§25): the proposition and
the validator stay authoritative and the wording must be checked against
the frame it was given.
"""
from __future__ import annotations

from typing import Optional

from . import acts as A


def who(cid: Optional[int], names=None, me: Optional[int] = None) -> str:
    if cid is None:
        return "someone"
    if me is not None and int(cid) == int(me):
        return "you"
    if names is not None:
        n = names(int(cid))
        if n:
            return n
    return f"citizen {int(cid)}"


def where(p: A.Proposition) -> str:
    if p.building_id is None:
        return "outside"
    if p.room_id is not None:
        return f"room {p.room_id} of building {p.building_id}"
    return f"building {p.building_id}"


def when(t: float, now_s: float) -> str:
    age = now_s - t
    if age < 300:
        return "just now"
    if age < 3600:
        return f"{int(age // 60)} minutes ago"
    if age < 2 * 3600:
        return "an hour ago"
    if age < 6 * 3600:
        return f"{int(age // 3600)} hours ago"
    return "earlier today"


def frame(p: A.Proposition, names=None, me=None) -> str:
    """The epistemic frame that must precede any content claim."""
    e = p.epistemic
    if e == A.DIRECT:
        return "I saw"
    if e == A.EXPERIENCED:
        return "It happened to me:"
    if e == A.SECOND_HAND:
        return f"{who(p.source_citizen, names, me)} told me"
    if e == A.HEARSAY:
        return "I heard"
    if e == A.BELIEF:
        return "I think"
    if e == A.UNCERTAIN:
        return "I'm not sure, but I think"
    return "I don't know"


def content(p: A.Proposition, names=None, me=None, now_s: float = 0.0) -> str:
    k = p.kind
    if k == A.PERSON_IS_DANGEROUS:
        return f"{who(p.subject, names, me)} is dangerous, {where(p)}, {when(p.t, now_s)}"
    if k == A.ATTACK_HAPPENED:
        if p.epistemic == A.EXPERIENCED:
            return f"{who(p.subject, names, me)} attacked me in {where(p)}, {when(p.t, now_s)}"
        return f"{who(p.subject, names, me)} attacked {who(p.target, names, me)} in {where(p)}, {when(p.t, now_s)}"
    if k == A.PERSON_DEAD:
        return f"{who(p.subject, names, me)} is dead, {where(p)}"
    if k == A.PLACE_IS_DANGEROUS:
        if p.subject is not None:
            return f"{where(p)} is not safe — {who(p.subject, names, me)} was there, {when(p.t, now_s)}"
        return f"{where(p)} is not safe"
    if k == A.PLACE_IS_SAFE:
        return f"{where(p)} was fine when I was there"
    if k == A.PERSON_SEEN:
        return f"{who(p.subject, names, me)} in {where(p)}, {when(p.t, now_s)}"
    if k == A.PERSON_HEARD_OF:
        return f"I only heard about {who(p.subject, names, me)} from {who(p.source_citizen, names, me)}"
    if k == A.HELP_RECEIVED:
        return f"{who(p.subject, names, me)} helped me ({p.detail}) in {where(p)}"
    if k == A.STATION_BROKEN:
        return f"the station {p.object_id} broke on {who(p.subject, names, me)} in {where(p)}"
    if k == A.WORKPLACE_DISRUPTED:
        return f"building {p.building_id} was shut down ({p.detail})"
    if k == A.EVENT_LOCATION:
        return f"that was in {where(p)}"
    if k == A.NOTHING_HAPPENED:
        return "nothing happened that I know of"
    return "nothing"


def render(act: str, p: Optional[A.Proposition] = None, *, speaker: Optional[int] = None,
           listener: Optional[int] = None, names=None, now_s: float = 0.0, warmth: float = 0.0,
           reason: str = "", request: Optional[A.Request] = None) -> str:
    """One line of text for one act. Deterministic; warmth in [0,1] is the
    speaker's familiarity + affinity toward the listener."""
    warm = warmth >= 0.5
    L = who(listener, names, speaker) if listener is not None else "you"
    if act == A.GREET:
        return f"Hey, {L}." if warm else "Hello."
    if act == A.END_CONVERSATION:
        return "Take care." if warm else "Goodbye."
    if act == A.ACKNOWLEDGE:
        return "Got it." if warm else "I see."
    if act == A.THANK:
        return "Thanks, I owe you one." if warm else "Thank you."
    if act == A.ASK_FACT:
        if p is not None and p.building_id is not None:
            return f"What happened at building {p.building_id}?"
        if p is not None and p.subject is not None:
            return f"What happened to {who(p.subject, names, speaker)}?"
        return "What happened?"
    if act == A.ASK_LOCATION:
        return "Where was that?"
    if act == A.ASK_PERSON:
        return f"Have you seen {who(p.subject if p else None, names, speaker)}?"
    if act == A.ASK_SAFETY:
        if p is not None and p.room_id is not None:
            return f"Is room {p.room_id} of building {p.building_id} safe?"
        return f"Is building {p.building_id} safe?" if p is not None and p.building_id is not None else "Is this place safe?"
    if act == A.ASK_FOR_HELP:
        r = request
        what = {"cover_station": "cover my register", "repair_station": "help me fix my station",
                "help_clean": "help me with the cleaning", "help_restock": "help me restock"}.get(
            r.kind if r else "", "help me")
        return (f"Could you {what}? ({r.object_id})" if r and r.object_id else f"Could you {what}?")
    if act == A.OFFER_HELP:
        return "Need a hand?"
    if act == A.ACCEPT:
        return "Sure, I'm on it." if warm else "All right, I'll do it."
    if act == A.REFUSE:
        why = {A.R_TOO_DANGEROUS: "it's too dangerous", A.R_BUSY: "I'm tied up right now",
               A.R_NO_CAPABILITY: "I can't do that", A.R_LOW_TRUST: "I don't know you well enough",
               A.R_URGENT_TASK: "I have customers waiting", A.R_UNAVAILABLE: "I can't right now",
               A.R_SHIFT: "I have my own station to mind", A.R_COST: "I'd rather not"}.get(reason, "no")
        return f"Sorry, {why}." if warm else f"No — {why}."
    if act == A.REPORT_PROBLEM:
        return f"My station {request.object_id} is broken." if request and request.object_id else "I have a problem here."
    if act == A.CLARIFY:
        return "Which one do you mean?"
    if act == A.EXPRESS_UNCERTAINTY:
        return "I'm not sure." if not p or p.detail != "decayed" else "I don't remember it clearly any more."
    if act in (A.INFORM, A.WARN, A.ANSWER):
        if p is None or p.kind == A.UNKNOWN:
            if p is not None and p.epistemic == A.UNCERTAIN:
                return "I'm not sure." if p.detail != "decayed" else "I don't remember it clearly any more."
            return "I don't know."
        f = frame(p, names, speaker)
        c = content(p, names, speaker, now_s)
        if p.kind == A.PERSON_HEARD_OF:              # content self-frames ("I only heard about ...")
            return c[0].upper() + c[1:] + "."
        if p.epistemic == A.EXPERIENCED:
            return f"{f} {c}."
        if act == A.WARN and p.epistemic == A.DIRECT:
            return f"Careful — {f} {c}."
        return f"{f} {c}."
    return act.lower()

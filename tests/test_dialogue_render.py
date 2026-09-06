"""The deterministic surface renderer (§24, §25).

Language is presentation over an authoritative semantic act, and the one
thing the wording may never do is claim more than the proposition it was
given: the epistemic status chooses the frame ("I saw" / "X told me" /
"I heard" / "I think" / "I'm not sure" / "I don't know"), relationship
warmth chooses only a variant, and the same input always renders the same
string.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.cognition import memory as M
from asphodel.dialogue import acts as A
from asphodel.dialogue import grounding as G
from asphodel.dialogue.render import content, frame, render, when, where, who

NOW = 100_000.0

CONTENT_KINDS = (A.PERSON_IS_DANGEROUS, A.ATTACK_HAPPENED, A.PERSON_DEAD, A.PLACE_IS_DANGEROUS,
                 A.PLACE_IS_SAFE, A.PERSON_SEEN, A.PERSON_HEARD_OF, A.HELP_RECEIVED,
                 A.STATION_BROKEN, A.WORKPLACE_DISRUPTED, A.EVENT_LOCATION, A.NOTHING_HAPPENED)
EPISTEMICS = (A.DIRECT, A.EXPERIENCED, A.SECOND_HAND, A.HEARSAY, A.BELIEF, A.UNCERTAIN,
              A.NO_KNOWLEDGE)
REASONS = (A.R_TOO_DANGEROUS, A.R_BUSY, A.R_NO_CAPABILITY, A.R_LOW_TRUST, A.R_URGENT_TASK,
           A.R_UNAVAILABLE, A.R_SHIFT, A.R_COST)


def _prop(kind=A.PERSON_IS_DANGEROUS, epistemic=A.DIRECT, **kw):
    d = dict(subject=9, target=8, building_id=100, room_id=0, object_id="reg:1",
             event_ref="1:1", source_citizen=2, origin_witness=3, hops=1, confidence=0.7,
             t=NOW - 600.0, detail="d")
    d.update(kw)
    return A.Proposition(kind=kind, epistemic=epistemic, **d)


def _request(kind="cover_station", object_id="reg:1"):
    return A.Request("req:1", kind, 1, 2, object_id=object_id, building_id=100, problem="unstaffed_queue")


# --------------------------------------------------------------------------- #
# every act says something
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("act", A.ACTS)
def test_every_act_renders_a_non_empty_line(act):
    for p in (None, _prop(), _prop(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE)):
        for warmth in (0.0, 1.0):
            line = render(act, p, speaker=1, listener=2, now_s=NOW, warmth=warmth,
                          reason=A.R_BUSY, request=_request())
            assert isinstance(line, str) and line.strip(), (act, warmth)
            assert "None" not in line, (act, line)


@pytest.mark.parametrize("kind", CONTENT_KINDS)
def test_every_proposition_kind_has_content(kind):
    line = content(_prop(kind=kind), now_s=NOW)
    assert isinstance(line, str) and line.strip() and line != "nothing" or kind == A.NOTHING_HAPPENED


def test_the_helpers_name_places_people_and_times():
    assert who(None) == "someone"
    assert who(7) == "citizen 7"
    assert who(7, me=7) == "you"
    assert who(7, names=lambda c: "Ada") == "Ada"
    assert where(_prop(building_id=None, room_id=None)) == "outside"
    assert where(_prop(building_id=5, room_id=None)) == "building 5"
    assert "room 2" in where(_prop(building_id=5, room_id=2))
    assert when(NOW, NOW) == "just now"
    assert when(NOW - 1800.0, NOW) == "30 minutes ago"
    assert when(NOW - 5400.0, NOW) == "an hour ago"
    assert when(NOW - 4 * 3600.0, NOW) == "4 hours ago"
    assert when(NOW - 20 * 3600.0, NOW) == "earlier today"


# --------------------------------------------------------------------------- #
# the epistemic frame
# --------------------------------------------------------------------------- #
def test_each_epistemic_status_has_its_own_frame():
    assert frame(_prop(epistemic=A.DIRECT)) == "I saw"
    assert frame(_prop(epistemic=A.EXPERIENCED)).startswith("It happened to me")
    assert frame(_prop(epistemic=A.SECOND_HAND)) == "citizen 2 told me"
    assert frame(_prop(epistemic=A.SECOND_HAND, source_citizen=None)) == "someone told me"
    assert frame(_prop(epistemic=A.HEARSAY)) == "I heard"
    assert frame(_prop(epistemic=A.BELIEF)) == "I think"
    assert frame(_prop(epistemic=A.UNCERTAIN)).startswith("I'm not sure")
    assert frame(_prop(epistemic=A.NO_KNOWLEDGE)) == "I don't know"
    assert len({frame(_prop(epistemic=e)) for e in EPISTEMICS}) == len(EPISTEMICS)


def test_the_frame_of_a_told_fact_names_the_teller_by_name():
    p = _prop(epistemic=A.SECOND_HAND, source_citizen=42)
    assert frame(p, names=lambda c: {42: "Ada"}.get(c)) == "Ada told me"


@pytest.mark.parametrize("kind", CONTENT_KINDS)
@pytest.mark.parametrize("act", (A.INFORM, A.WARN, A.ANSWER))
def test_a_told_proposition_is_never_rendered_as_a_first_hand_observation(kind, act):
    """§7/§24: the epistemic frame is not optional. A proposition the
    validator marked SECOND_HAND / HEARSAY must not surface as "I saw"."""
    for epistemic in (A.SECOND_HAND, A.HEARSAY):
        line = render(act, _prop(kind=kind, epistemic=epistemic), speaker=1, listener=2, now_s=NOW)
        assert not line.startswith("I saw"), (kind, act, epistemic, line)
        assert "I saw" not in line, (
            f"{kind} rendered as first-hand from a {epistemic} proposition: {line!r}")


def test_a_first_hand_warning_is_rendered_as_one():
    line = render(A.WARN, _prop(kind=A.PERSON_IS_DANGEROUS, epistemic=A.DIRECT), speaker=1,
                  listener=2, now_s=NOW)
    assert line.startswith("Careful — I saw"), line
    told = render(A.WARN, _prop(kind=A.PERSON_IS_DANGEROUS, epistemic=A.SECOND_HAND), speaker=1,
                  listener=2, now_s=NOW)
    assert told.startswith("citizen 2 told me"), told
    mine = render(A.INFORM, _prop(kind=A.ATTACK_HAPPENED, epistemic=A.EXPERIENCED, subject=9,
                                  target=1), speaker=1, listener=2, now_s=NOW)
    assert mine.startswith("It happened to me:") and "attacked me" in mine, mine


def test_the_renderer_uses_the_grounded_proposition_it_is_handed():
    """The line a speaker with a told fact produces carries the teller, not
    a first-hand claim — end to end from the store through the validator."""
    st = M.MemoryStore(1)
    st.remember(M.THREAT_PERSON, NOW, actor=9, building_id=100, room_id=0, source=M.TOLD,
                source_citizen=2, origin_witness=3, origin_id="3:1", hops=1, confidence=0.8)
    claim = A.Proposition(kind=A.PERSON_IS_DANGEROUS, subject=9, building_id=100,
                          epistemic=A.DIRECT, confidence=1.0)
    g, verdict = G.ground(st, claim, NOW)
    assert verdict == "downgraded:source"
    line = render(A.WARN, g, speaker=1, listener=4, now_s=NOW)
    assert line.startswith("citizen 2 told me") and "I saw" not in line, line


def test_an_unknown_proposition_says_so():
    assert render(A.ANSWER, None, speaker=1, listener=2, now_s=NOW) == "I don't know."
    unknown = A.Proposition(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE)
    for act in (A.INFORM, A.WARN, A.ANSWER):
        assert render(act, unknown, speaker=1, listener=2, now_s=NOW) == "I don't know."
    uncertain = A.Proposition(kind=A.UNKNOWN, epistemic=A.UNCERTAIN)
    assert render(A.ANSWER, uncertain, speaker=1, now_s=NOW) == "I'm not sure."
    decayed = A.Proposition(kind=A.UNKNOWN, epistemic=A.UNCERTAIN, detail="decayed")
    assert render(A.ANSWER, decayed, speaker=1, now_s=NOW) == "I don't remember it clearly any more."
    assert render(A.EXPRESS_UNCERTAINTY, decayed, speaker=1, now_s=NOW) == \
        "I don't remember it clearly any more."


# --------------------------------------------------------------------------- #
# refusals, questions, warmth
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reason", REASONS)
def test_every_structured_refusal_reason_renders_its_own_words(reason):
    cold = render(A.REFUSE, None, speaker=1, listener=2, now_s=NOW, warmth=0.0, reason=reason,
                  request=_request())
    warm = render(A.REFUSE, None, speaker=1, listener=2, now_s=NOW, warmth=1.0, reason=reason,
                  request=_request())
    assert cold.startswith("No — ") and warm.startswith("Sorry, ")
    assert cold != warm and len(cold) > len("No — no.")


def test_refusal_reasons_are_distinguishable_from_each_other():
    lines = {r: render(A.REFUSE, None, speaker=1, listener=2, reason=r) for r in REASONS}
    assert len(set(lines.values())) == len(REASONS), lines
    fallback = render(A.REFUSE, None, speaker=1, listener=2, reason="not_a_reason")
    assert fallback == "No — no." and fallback not in lines.values()


def test_a_request_names_what_was_asked_for():
    for kind, needle in (("cover_station", "cover my register"), ("repair_station", "fix my station"),
                         ("help_clean", "cleaning"), ("help_restock", "restock")):
        line = render(A.ASK_FOR_HELP, None, speaker=1, listener=2, request=_request(kind))
        assert needle in line, (kind, line)
        assert "reg:1" in line
    assert render(A.REPORT_PROBLEM, None, speaker=1, request=_request()) == "My station reg:1 is broken."


def test_the_questions_name_their_topic():
    assert render(A.ASK_FACT, _prop(building_id=100), speaker=1) == "What happened at building 100?"
    assert render(A.ASK_FACT, _prop(building_id=None), speaker=1) == "What happened to citizen 9?"
    assert render(A.ASK_FACT, None, speaker=1) == "What happened?"
    assert render(A.ASK_LOCATION, None, speaker=1) == "Where was that?"
    assert render(A.ASK_PERSON, _prop(subject=9), speaker=1) == "Have you seen citizen 9?"
    assert render(A.ASK_SAFETY, _prop(building_id=100, room_id=2), speaker=1) == \
        "Is room 2 of building 100 safe?"
    assert render(A.ASK_SAFETY, _prop(building_id=100, room_id=None), speaker=1) == \
        "Is building 100 safe?"
    assert render(A.ASK_SAFETY, None, speaker=1) == "Is this place safe?"


@pytest.mark.parametrize("act", (A.GREET, A.END_CONVERSATION, A.ACKNOWLEDGE, A.THANK, A.ACCEPT))
def test_warmth_changes_the_wording_but_not_the_act(act):
    cold = render(act, None, speaker=1, listener=2, warmth=0.0)
    warm = render(act, None, speaker=1, listener=2, warmth=1.0)
    assert cold != warm, act
    assert cold.strip() and warm.strip()
    # the boundary is stable and warmth alone never adds a claim
    assert render(act, None, speaker=1, listener=2, warmth=0.49) == cold
    assert render(act, None, speaker=1, listener=2, warmth=0.5) == warm
    assert "I saw" not in cold and "I saw" not in warm


def test_a_warm_greeting_names_the_listener():
    assert render(A.GREET, None, speaker=1, listener=2, warmth=1.0) == "Hey, citizen 2."
    assert render(A.GREET, None, speaker=1, listener=2, warmth=1.0,
                  names=lambda c: "Ada" if c == 2 else None) == "Hey, Ada."
    assert render(A.GREET, None, speaker=1, listener=1, warmth=1.0) == "Hey, you."


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def test_the_renderer_is_deterministic():
    for act in A.ACTS:
        for kind in CONTENT_KINDS + (A.UNKNOWN,):
            for epistemic in EPISTEMICS:
                p = _prop(kind=kind, epistemic=epistemic)
                args = dict(speaker=1, listener=2, now_s=NOW, warmth=0.7, reason=A.R_LOW_TRUST,
                            request=_request())
                first = render(act, p, **args)
                assert all(render(act, _prop(kind=kind, epistemic=epistemic), **args) == first
                           for _ in range(3)), (act, kind, epistemic)

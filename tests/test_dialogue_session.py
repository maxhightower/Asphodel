"""Bounded persistent conversation sessions (§8, §9).

A conversation is state, not a transcript: acts and rendered lines are both
ring-bounded, the turn alternates deterministically, and the whole session
round-trips through ``to_state`` / ``from_state`` so a saved world resumes
mid-sentence.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.dialogue import acts as A
from asphodel.dialogue.session import (ACTIVE, CALL, CHANNELS, Conversation, ENDED, FACE_TO_FACE,
                                       INTERRUPTED, MAX_ACTS, MAX_TRANSCRIPT, PLAYER, SHOUT)


def _conv(a=1, b=2, channel=FACE_TO_FACE) -> Conversation:
    return Conversation("conv:1", [a, b], channel, 1000.0, last_s=1000.0)


def _row(i: int, speaker: int = 1) -> dict:
    return {"t": 1000.0 + i, "speaker": speaker, "listener": 2, "act": A.INFORM, "n": i,
            "proposition": None, "request_id": None, "reason": "", "line": f"line {i}",
            "answer_to": None}


def test_the_documented_channels_and_states_exist():
    assert {FACE_TO_FACE, SHOUT, CALL, PLAYER} <= set(CHANNELS)
    assert len(set(CHANNELS)) == len(CHANNELS)
    assert (ACTIVE, ENDED, INTERRUPTED) == ("active", "ended", "interrupted")


def test_a_new_conversation_starts_empty_and_active():
    c = _conv()
    assert c.state == ACTIVE and c.acts == [] and c.transcript == [] and c.n_acts == 0
    assert c.speaker() == 1 and c.other(1) == 2 and c.other(2) == 1
    assert c.other(99) in (1, 2)


def test_acts_and_transcript_are_ring_bounded_but_the_count_is_not():
    c = _conv()
    n = MAX_ACTS + MAX_TRANSCRIPT + 17
    for i in range(n):
        c.add(_row(i), f"[1] line {i}")
    assert c.n_acts == n, "the true number of acts is not lost when the ring rolls"
    assert len(c.acts) == MAX_ACTS
    assert len(c.transcript) == MAX_TRANSCRIPT
    # what survives is the most recent window, in order
    assert [r["n"] for r in c.acts] == list(range(n - MAX_ACTS, n))
    assert c.transcript == [f"[1] line {i}" for i in range(n - MAX_TRANSCRIPT, n)]


def test_a_short_conversation_keeps_everything():
    c = _conv()
    for i in range(3):
        c.add(_row(i), f"[1] line {i}")
    assert len(c.acts) == 3 and len(c.transcript) == 3 and c.n_acts == 3


def test_the_turn_alternates_and_can_be_handed_to_a_named_participant():
    c = _conv(7, 9)
    assert c.speaker() == 7
    c.pass_turn()
    assert c.speaker() == 9
    c.pass_turn()
    assert c.speaker() == 7
    c.pass_turn(9)
    assert c.speaker() == 9
    c.pass_turn(9)
    assert c.speaker() == 9, "handing the turn to the current speaker keeps it there"
    c.pass_turn(1234)                 # not a participant: falls back to alternating
    assert c.speaker() == 7


def test_the_session_round_trips_through_its_state():
    c = _conv(5, 6, CALL)
    c.topic = {"kind": "THREAT_PERSON", "event_ref": "5:1", "building_id": 100, "room_id": 0}
    c.open_questions = [{"act": A.ASK_FACT, "asker": 6, "seq": 3, "proposition": None}]
    c.open_requests = ["req:2"]
    c.facts_introduced = ["5:1"]
    c.plan = [{"speaker": 5, "act": A.ANSWER, "fact_id": "5:1"}]
    c.building_id, c.room_id = 100, 0
    c.end_reason = ""
    for i in range(4):
        c.add(_row(i, speaker=(5 if i % 2 == 0 else 6)), f"[5] line {i}")
    c.pass_turn(6)

    st = c.to_state()
    assert json.loads(json.dumps(st, sort_keys=True)) == st, "the session state is JSON"
    back = Conversation.from_state(json.loads(json.dumps(st)))
    assert back.to_state() == st
    for field in ("conv_id", "participants", "channel", "started_s", "last_s", "turn", "acts",
                  "topic", "open_questions", "open_requests", "facts_introduced", "plan", "state",
                  "end_reason", "transcript", "building_id", "room_id", "n_acts"):
        assert getattr(back, field) == getattr(c, field), field
    assert back.speaker() == c.speaker()


def test_a_round_tripped_session_keeps_speaking_where_it_left_off():
    c = _conv(5, 6)
    c.add(_row(0, speaker=5), "[5] hello")
    c.pass_turn(6)
    back = Conversation.from_state(json.loads(json.dumps(c.to_state())))
    back.add(_row(1, speaker=6), "[6] hi")
    c.add(_row(1, speaker=6), "[6] hi")
    assert back.to_state() == c.to_state()


@pytest.mark.parametrize("state", (ENDED, INTERRUPTED))
def test_a_terminated_session_carries_its_reason_through_a_round_trip(state):
    c = _conv()
    c.state, c.end_reason = state, "separated:different_room"
    back = Conversation.from_state(json.loads(json.dumps(c.to_state())))
    assert back.state == state and back.end_reason == "separated:different_room"


def test_a_session_state_that_lost_its_optional_fields_still_loads():
    c = _conv()
    minimal = {"conv_id": "conv:9", "participants": [3, 4], "channel": PLAYER, "started_s": 5.0}
    back = Conversation.from_state(minimal)
    assert back.state == ACTIVE and back.acts == [] and back.n_acts == 0
    assert back.participants == [3, 4] and back.channel == PLAYER
    assert set(back.to_state()) == set(c.to_state())

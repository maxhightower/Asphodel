"""Bounded persistent conversation sessions (§8, §9).

A :class:`Conversation` holds participants, channel, times, whose turn it is,
the recent semantic acts (bounded), the active topic, open questions and
requests, the facts introduced, and its termination state. A short rendered
transcript is kept for UI and debugging only; the acts are the state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

MAX_ACTS = 40
MAX_TRANSCRIPT = 24

FACE_TO_FACE = "face_to_face"
SHOUT = "shout"
CALL = "call"
PLAYER = "player"
PROBE = "probe"                # a question put to a citizen by the player or the certification harness
CHANNELS = (FACE_TO_FACE, SHOUT, CALL, PLAYER, PROBE)

ACTIVE = "active"
ENDED = "ended"
INTERRUPTED = "interrupted"


@dataclass
class Conversation:
    conv_id: str
    participants: List[int]
    channel: str
    started_s: float
    last_s: float = 0.0
    turn: int = 0                         # index into participants of who speaks next
    acts: List[dict] = field(default_factory=list)
    topic: Optional[dict] = None          # {"kind", "subject", "building_id", "room_id", "event_ref"}
    open_questions: List[dict] = field(default_factory=list)   # acts awaiting an answer
    open_requests: List[str] = field(default_factory=list)     # request ids awaiting a decision
    facts_introduced: List[str] = field(default_factory=list)  # origin ids told in this conversation
    plan: List[dict] = field(default_factory=list)             # queued acts (NPC<->NPC, one per second)
    state: str = ACTIVE
    end_reason: str = ""
    transcript: List[str] = field(default_factory=list)
    building_id: Optional[int] = None
    room_id: Optional[int] = None
    n_acts: int = 0

    def add(self, row: dict, line: str) -> None:
        self.acts.append(row)
        self.n_acts += 1
        if len(self.acts) > MAX_ACTS:
            del self.acts[: len(self.acts) - MAX_ACTS]
        self.transcript.append(line)
        if len(self.transcript) > MAX_TRANSCRIPT:
            del self.transcript[: len(self.transcript) - MAX_TRANSCRIPT]

    def other(self, cid: int) -> Optional[int]:
        for p in self.participants:
            if p != cid:
                return p
        return None

    def speaker(self) -> int:
        return self.participants[self.turn % len(self.participants)]

    def pass_turn(self, to: Optional[int] = None) -> None:
        if to is not None and to in self.participants:
            self.turn = self.participants.index(to)
        else:
            self.turn = (self.turn + 1) % len(self.participants)

    def to_state(self) -> dict:
        return {"conv_id": self.conv_id, "participants": list(self.participants), "channel": self.channel,
                "started_s": self.started_s, "last_s": self.last_s, "turn": self.turn, "acts": list(self.acts),
                "topic": self.topic, "open_questions": list(self.open_questions),
                "open_requests": list(self.open_requests), "facts_introduced": list(self.facts_introduced),
                "plan": list(self.plan), "state": self.state, "end_reason": self.end_reason,
                "transcript": list(self.transcript), "building_id": self.building_id, "room_id": self.room_id,
                "n_acts": self.n_acts}

    @classmethod
    def from_state(cls, d: dict) -> "Conversation":
        c = cls(str(d["conv_id"]), [int(x) for x in d["participants"]], str(d["channel"]), float(d["started_s"]))
        for k, v in d.items():
            if k in ("conv_id", "participants", "channel", "started_s"):
                continue
            if hasattr(c, k):
                setattr(c, k, v)
        return c

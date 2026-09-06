"""The speech-act grammar, propositions and requests
(ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 §4, §5, §18).

The semantic act is the authority; natural language is presentation. A
:class:`Proposition` is a structured fact a speaker asserts, always tied to
the memory fact that supports it and carrying its epistemic status; a
:class:`Request` is a bounded commitment (who asked whom to do what to which
object, and where it stands).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

# --- speech acts ------------------------------------------------------------
GREET = "GREET"
INFORM = "INFORM"
WARN = "WARN"
ASK_FACT = "ASK_FACT"              # "what happened?"
ANSWER = "ANSWER"
ASK_LOCATION = "ASK_LOCATION"      # "where was that?" / "where did you see them?"
ASK_PERSON = "ASK_PERSON"          # "have you seen X?"
ASK_SAFETY = "ASK_SAFETY"          # "is this place safe?"
ASK_FOR_HELP = "ASK_FOR_HELP"
OFFER_HELP = "OFFER_HELP"
ACCEPT = "ACCEPT"
REFUSE = "REFUSE"
THANK = "THANK"
ACKNOWLEDGE = "ACKNOWLEDGE"
CLARIFY = "CLARIFY"
EXPRESS_UNCERTAINTY = "EXPRESS_UNCERTAINTY"
REPORT_PROBLEM = "REPORT_PROBLEM"
END_CONVERSATION = "END_CONVERSATION"
# --- survivor-group acts (ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 §33) --------
INVITE_TO_GROUP = "INVITE_TO_GROUP"
ASK_TO_JOIN = "ASK_TO_JOIN"
ACCEPT_MEMBER = "ACCEPT_MEMBER"
REFUSE_MEMBER = "REFUSE_MEMBER"
PROPOSE_SHELTER = "PROPOSE_SHELTER"
ASSIGN_ROLE = "ASSIGN_ROLE"
REQUEST_SUPPLY_RUN = "REQUEST_SUPPLY_RUN"
WARN_GROUP = "WARN_GROUP"
ASK_WHERE_MEMBER_IS = "ASK_WHERE_MEMBER_IS"
REPORT_MEMBER_LOCATION = "REPORT_MEMBER_LOCATION"
PROPOSE_EVACUATION = "PROPOSE_EVACUATION"
GROUP_ACTS = (INVITE_TO_GROUP, ASK_TO_JOIN, ACCEPT_MEMBER, REFUSE_MEMBER, PROPOSE_SHELTER, ASSIGN_ROLE,
              REQUEST_SUPPLY_RUN, WARN_GROUP, ASK_WHERE_MEMBER_IS, REPORT_MEMBER_LOCATION, PROPOSE_EVACUATION)
ACTS = (GREET, INFORM, WARN, ASK_FACT, ANSWER, ASK_LOCATION, ASK_PERSON, ASK_SAFETY, ASK_FOR_HELP,
        OFFER_HELP, ACCEPT, REFUSE, THANK, ACKNOWLEDGE, CLARIFY, EXPRESS_UNCERTAINTY, REPORT_PROBLEM,
        END_CONVERSATION) + GROUP_ACTS
QUESTIONS = (ASK_FACT, ASK_LOCATION, ASK_PERSON, ASK_SAFETY, ASK_FOR_HELP, ASK_TO_JOIN, ASK_WHERE_MEMBER_IS)

# --- proposition kinds --------------------------------------------------------
PERSON_IS_DANGEROUS = "PERSON_IS_DANGEROUS"
ATTACK_HAPPENED = "ATTACK_HAPPENED"
PERSON_DEAD = "PERSON_DEAD"
PLACE_IS_DANGEROUS = "PLACE_IS_DANGEROUS"
PLACE_IS_SAFE = "PLACE_IS_SAFE"
PERSON_SEEN = "PERSON_SEEN"
PERSON_HEARD_OF = "PERSON_HEARD_OF"
HELP_RECEIVED = "HELP_RECEIVED"
STATION_BROKEN = "STATION_BROKEN"
WORKPLACE_DISRUPTED = "WORKPLACE_DISRUPTED"
EVENT_LOCATION = "EVENT_LOCATION"
NOTHING_HAPPENED = "NOTHING_HAPPENED"
UNKNOWN = "UNKNOWN"

# --- epistemic status (§6, §7) ---------------------------------------------------
DIRECT = "DIRECT_OBSERVATION"      # I saw
EXPERIENCED = "EXPERIENCED"        # it happened to me
SECOND_HAND = "SECOND_HAND"        # X told me
HEARSAY = "HEARSAY"                # I heard (two hops or a weak telling)
BELIEF = "BELIEF"                  # I think (derived, no single supporting fact)
UNCERTAIN = "UNCERTAIN"            # I'm not sure
NO_KNOWLEDGE = "UNKNOWN"           # I don't know


@dataclass
class Proposition:
    kind: str
    subject: Optional[int] = None          # citizen the proposition is about
    target: Optional[int] = None           # second citizen
    building_id: Optional[int] = None
    room_id: Optional[int] = None
    object_id: Optional[str] = None
    event_ref: Optional[str] = None        # the supporting memory fact id (speaker's)
    epistemic: str = NO_KNOWLEDGE
    source_citizen: Optional[int] = None   # who told the speaker (SECOND_HAND / HEARSAY)
    origin_witness: Optional[int] = None
    origin_id: str = ""
    hops: int = 0
    confidence: float = 0.0
    t: float = 0.0                         # when it happened
    detail: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = round(self.confidence, 3)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Proposition":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})


# --- requests / commitments (§16–§19) --------------------------------------------
REQ_PENDING = "pending"
REQ_ACCEPTED = "accepted"
REQ_REFUSED = "refused"
REQ_COMPLETED = "completed"
REQ_FAILED = "failed"
REQ_CANCELLED = "cancelled"

# structured refusal reasons
R_TOO_DANGEROUS = "too_dangerous"
R_BUSY = "already_occupied"
R_NO_CAPABILITY = "no_capability"
R_LOW_TRUST = "low_trust"
R_URGENT_TASK = "current_urgent_task"
R_UNAVAILABLE = "unavailable"
R_SHIFT = "shift_obligation"
R_COST = "not_worth_it"


@dataclass
class Request:
    request_id: str
    kind: str                       # a help task id: cover_station | help_clean | help_restock | repair_station
    requester: int
    accepter: int
    object_id: Optional[str] = None
    building_id: Optional[int] = None
    problem: str = ""
    created_s: float = 0.0
    state: str = REQ_PENDING
    decided_s: float = -1.0
    completed_s: float = -1.0
    reason: str = ""                # refusal / failure reason
    score: float = 0.0
    components: dict = field(default_factory=dict)
    conversation_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Request":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__ if k in d})

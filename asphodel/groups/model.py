"""Structured survivor-group state (ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1, §4).

A :class:`SurvivorGroup` is a *social layer* over citizens who remain
individuals. It holds identity, membership, shelter, shared objectives, roles,
a bounded provenance-preserving shared record, invitations/applications, group
decisions and an event log. It never holds a citizen's perception, memory,
beliefs, relationships, goals or body — those stay in the individual
authorities. Nothing here is authoritative over a citizen; the group proposes
and coordinates, the citizen decides and acts.

All state is structured (no prose-as-authority) and round-trips through
``to_state`` / ``from_state`` for byte-identical save/load.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------- membership (§5)
CANDIDATE = "candidate"      # cognition flagged them as a formation/recruit candidate
INVITED = "invited"          # a member has invited them; awaiting their answer
PROVISIONAL = "provisional"  # admitted on trial (e.g. an accepted outsider)
MEMBER = "member"
DEPARTED = "departed"        # left voluntarily
EXPELLED = "expelled"        # removed by the group
MEMBER_STATES = (CANDIDATE, INVITED, PROVISIONAL, MEMBER, DEPARTED, EXPELLED)
ACTIVE_STATES = (PROVISIONAL, MEMBER)

# ---------------------------------------------------------------- roles (§13)
COORDINATOR = "coordinator"  # initiates discussion, proposes, resolves bounded decisions
GUARD = "guard"              # watches a real entrance/room, warns the group
SCAVENGER = "scavenger"      # leaves the shelter to acquire supplies at a known source
CAREGIVER = "caregiver"      # tends an injured/at-risk member (optional fourth role)
ROLES = (COORDINATOR, GUARD, SCAVENGER, CAREGIVER)

# ---------------------------------------------------------------- objectives (§11)
REGROUP = "REGROUP"
REACH_SHELTER = "REACH_SHELTER"
MAINTAIN_SHELTER = "MAINTAIN_SHELTER"
WATCH_ENTRANCE = "WATCH_ENTRANCE"
SEEK_SUPPLIES = "SEEK_SUPPLIES"
HELP_MEMBER = "HELP_MEMBER"
LOCATE_MEMBER = "LOCATE_MEMBER"
WARN_GROUP = "WARN_GROUP"
EVACUATE = "EVACUATE"
ADMIT_OR_REFUSE_PERSON = "ADMIT_OR_REFUSE_PERSON"
OBJECTIVES = (REGROUP, REACH_SHELTER, MAINTAIN_SHELTER, WATCH_ENTRANCE, SEEK_SUPPLIES,
              HELP_MEMBER, LOCATE_MEMBER, WARN_GROUP, EVACUATE, ADMIT_OR_REFUSE_PERSON)

# objective / task lifecycle
OBJ_OPEN = "open"            # created, not yet assigned
OBJ_ASSIGNED = "assigned"    # a member is asked / has accepted
OBJ_ACTIVE = "active"        # the member is acting on it
OBJ_DONE = "done"
OBJ_FAILED = "failed"
OBJ_CANCELLED = "cancelled"

# threat posture (§29)
CALM = "calm"
ALERTED = "alerted"          # a member reported a threat; warning spreading
EVACUATING = "evacuating"


@dataclass
class GroupFact:
    """One entry of the group's shared record (§23). It is only ever created
    from a fact a member *deliberately communicated* as group-relevant, and it
    keeps its provenance; it is not a channel into any citizen's memory. A
    member learns the underlying fact only through cognition.receive_fact, and
    ``recipients`` records who has actually been told."""
    fact_id: str
    kind: str                       # threat_location | shelter | supply_source | missing_member | member_location
    subject: Optional[int] = None   # a citizen the fact is about (attacker, missing member, ...)
    building_id: Optional[int] = None
    room_id: Optional[int] = None
    object_id: Optional[str] = None
    origin_witness: Optional[int] = None   # the citizen who first knew it (preserved lineage)
    source_citizen: Optional[int] = None   # who reported it to the group
    confidence: float = 1.0
    t: float = 0.0
    detail: str = ""
    recipients: List[int] = field(default_factory=list)   # members who have actually received it

    def to_dict(self) -> dict:
        return {"fact_id": self.fact_id, "kind": self.kind, "subject": self.subject,
                "building_id": self.building_id, "room_id": self.room_id, "object_id": self.object_id,
                "origin_witness": self.origin_witness, "source_citizen": self.source_citizen,
                "confidence": round(self.confidence, 4), "t": self.t, "detail": self.detail,
                "recipients": list(self.recipients)}

    @classmethod
    def from_dict(cls, d: dict) -> "GroupFact":
        f = cls(str(d["fact_id"]), str(d["kind"]))
        for k, v in d.items():
            if hasattr(f, k) and k not in ("fact_id", "kind"):
                setattr(f, k, list(v) if k == "recipients" else v)
        return f


@dataclass
class Objective:
    """A shared objective (§11). It never acts; it is realized by a member's
    goal / dialogue request / work task. ``assignee`` is the member carrying it;
    ``goal`` / ``request_id`` / ``task`` link to the individual authorities."""
    obj_id: str
    kind: str
    state: str = OBJ_OPEN
    target_cid: Optional[int] = None       # HELP_MEMBER / LOCATE_MEMBER / admission subject
    building_id: Optional[int] = None
    room_id: Optional[int] = None
    object_id: Optional[str] = None
    role: Optional[str] = None             # role this objective realizes (guard/scavenger/...)
    assignee: Optional[int] = None
    request_id: Optional[str] = None       # the dialogue request that proposed it
    created_s: float = 0.0
    decided_s: float = 0.0
    reason: str = ""
    detail: str = ""
    detail_node: Optional[str] = None      # a target graph node (supply source / missing member)

    def to_dict(self) -> dict:
        return {"obj_id": self.obj_id, "kind": self.kind, "state": self.state,
                "target_cid": self.target_cid, "building_id": self.building_id, "room_id": self.room_id,
                "object_id": self.object_id, "role": self.role, "assignee": self.assignee,
                "request_id": self.request_id, "created_s": self.created_s, "decided_s": self.decided_s,
                "reason": self.reason, "detail": self.detail, "detail_node": self.detail_node}

    @classmethod
    def from_dict(cls, d: dict) -> "Objective":
        o = cls(str(d["obj_id"]), str(d["kind"]))
        for k, v in d.items():
            if hasattr(o, k) and k not in ("obj_id", "kind"):
                setattr(o, k, v)
        return o


@dataclass
class Application:
    """An outsider's request to join, or a member's invitation (§18, §5). The
    decision aggregates member evaluations (§17); each evaluation is grounded in
    that member's own knowledge (trust/relationship/known threat/capacity)."""
    app_id: str
    subject: int                    # the citizen wanting in / invited
    kind: str = "application"       # application (they asked) | invitation (a member asked)
    by: Optional[int] = None        # inviting member, for an invitation
    state: str = "pending"          # pending | accepted | refused | withdrawn
    created_s: float = 0.0
    decided_s: float = 0.0
    reason: str = ""
    votes: Dict[str, list] = field(default_factory=dict)   # cid -> [support(-1..1), reason]

    def to_dict(self) -> dict:
        return {"app_id": self.app_id, "subject": self.subject, "kind": self.kind, "by": self.by,
                "state": self.state, "created_s": self.created_s, "decided_s": self.decided_s,
                "reason": self.reason, "votes": {str(k): list(v) for k, v in self.votes.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Application":
        a = cls(str(d["app_id"]), int(d["subject"]))
        for k, v in d.items():
            if k == "votes":
                a.votes = {int(kk): list(vv) for kk, vv in v.items()}
            elif hasattr(a, k) and k not in ("app_id", "subject"):
                setattr(a, k, v)
        return a


@dataclass
class Decision:
    """A bounded group decision (§17): a proposal, member support weighted by
    trust/influence, resolved (by the coordinator after consultation, or by
    aggregate support). Disagreement is preserved in ``votes``."""
    dec_id: str
    kind: str                       # shelter | admission | evacuate | role | ...
    options: List[str] = field(default_factory=list)
    votes: Dict[str, list] = field(default_factory=dict)   # cid -> [option, weight]
    outcome: Optional[str] = None
    resolved_by: Optional[int] = None
    created_s: float = 0.0
    resolved_s: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {"dec_id": self.dec_id, "kind": self.kind, "options": list(self.options),
                "votes": {str(k): list(v) for k, v in self.votes.items()}, "outcome": self.outcome,
                "resolved_by": self.resolved_by, "created_s": self.created_s, "resolved_s": self.resolved_s,
                "detail": self.detail}

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        x = cls(str(d["dec_id"]), str(d["kind"]))
        for k, v in d.items():
            if k == "votes":
                x.votes = {int(kk): list(vv) for kk, vv in v.items()}
            elif hasattr(x, k) and k not in ("dec_id", "kind"):
                setattr(x, k, v)
        return x


@dataclass
class SurvivorGroup:
    group_id: str
    created_s: float
    founders: List[int] = field(default_factory=list)
    members: Dict[int, str] = field(default_factory=dict)          # cid -> membership state
    joined_s: Dict[int, float] = field(default_factory=dict)       # cid -> when it became active
    membership_history: List[dict] = field(default_factory=list)   # {t, cid, old, new, cause}
    # shelter (§9): a real building/room the members chose from places they know
    shelter_building: Optional[int] = None
    shelter_room: Optional[int] = None
    shelter_node: Optional[str] = None          # graph node members travel to
    entrance_room: Optional[int] = None         # the room a guard watches
    shelter_history: List[dict] = field(default_factory=list)
    objectives: Dict[str, Objective] = field(default_factory=dict)
    roles: Dict[str, int] = field(default_factory=dict)            # role -> cid (single holder per role in V1)
    coordinator: Optional[int] = None
    influence: Dict[int, float] = field(default_factory=dict)      # cid -> influence (trust/competence)
    shared_record: Dict[str, GroupFact] = field(default_factory=dict)
    applications: Dict[str, Application] = field(default_factory=dict)
    decisions: Dict[str, Decision] = field(default_factory=dict)
    supplies: Dict[str, float] = field(default_factory=dict)       # e.g. {"food": 2.0}
    threat_state: str = CALM
    formed_reason: str = ""
    _seq: int = 0                                                  # id counter for objectives/decisions/facts

    # ------------------------------------------------------------------ helpers
    def nid(self, prefix: str) -> str:
        self._seq += 1
        return f"{self.group_id}:{prefix}:{self._seq}"

    def active_members(self) -> List[int]:
        return sorted(c for c, s in self.members.items() if s in ACTIVE_STATES)

    def is_member(self, cid: int) -> bool:
        return self.members.get(int(cid)) in ACTIVE_STATES

    def set_membership(self, cid: int, state: str, now_s: float, cause: str = "") -> None:
        old = self.members.get(int(cid))
        self.members[int(cid)] = state
        self.membership_history.append({"t": round(now_s, 1), "cid": int(cid), "old": old,
                                        "new": state, "cause": cause})
        if state in ACTIVE_STATES and int(cid) not in self.joined_s:
            self.joined_s[int(cid)] = now_s

    # ------------------------------------------------------------------ persistence
    def to_state(self) -> dict:
        return {
            "group_id": self.group_id, "created_s": self.created_s, "founders": list(self.founders),
            "members": {str(c): s for c, s in sorted(self.members.items())},
            "joined_s": {str(c): t for c, t in sorted(self.joined_s.items())},
            "membership_history": list(self.membership_history),
            "shelter_building": self.shelter_building, "shelter_room": self.shelter_room,
            "shelter_node": self.shelter_node, "entrance_room": self.entrance_room,
            "shelter_history": list(self.shelter_history),
            "objectives": {k: o.to_dict() for k, o in sorted(self.objectives.items())},
            "roles": {r: c for r, c in sorted(self.roles.items())},
            "coordinator": self.coordinator,
            "influence": {str(c): round(v, 4) for c, v in sorted(self.influence.items())},
            "shared_record": {k: f.to_dict() for k, f in sorted(self.shared_record.items())},
            "applications": {k: a.to_dict() for k, a in sorted(self.applications.items())},
            "decisions": {k: d.to_dict() for k, d in sorted(self.decisions.items())},
            "supplies": {k: round(v, 4) for k, v in sorted(self.supplies.items())},
            "threat_state": self.threat_state, "formed_reason": self.formed_reason, "_seq": self._seq,
        }

    @classmethod
    def from_state(cls, d: dict) -> "SurvivorGroup":
        g = cls(str(d["group_id"]), float(d["created_s"]))
        g.founders = [int(x) for x in d.get("founders", [])]
        g.members = {int(c): s for c, s in d.get("members", {}).items()}
        g.joined_s = {int(c): float(t) for c, t in d.get("joined_s", {}).items()}
        g.membership_history = list(d.get("membership_history", []))
        g.shelter_building = d.get("shelter_building")
        g.shelter_room = d.get("shelter_room")
        g.shelter_node = d.get("shelter_node")
        g.entrance_room = d.get("entrance_room")
        g.shelter_history = list(d.get("shelter_history", []))
        g.objectives = {k: Objective.from_dict(v) for k, v in d.get("objectives", {}).items()}
        g.roles = {r: int(c) for r, c in d.get("roles", {}).items()}
        g.coordinator = d.get("coordinator")
        g.influence = {int(c): float(v) for c, v in d.get("influence", {}).items()}
        g.shared_record = {k: GroupFact.from_dict(v) for k, v in d.get("shared_record", {}).items()}
        g.applications = {k: Application.from_dict(v) for k, v in d.get("applications", {}).items()}
        g.decisions = {k: Decision.from_dict(v) for k, v in d.get("decisions", {}).items()}
        g.supplies = {k: float(v) for k, v in d.get("supplies", {}).items()}
        g.threat_state = str(d.get("threat_state", CALM))
        g.formed_reason = str(d.get("formed_reason", ""))
        g._seq = int(d.get("_seq", 0))
        return g

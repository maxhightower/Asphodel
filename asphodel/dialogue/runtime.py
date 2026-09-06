"""DialogueRuntime — grounded conversations between citizens and with the
player (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1).

    ConversationContext -> speech act -> Proposition -> grounding validator ->
    surface renderer -> listener cognition (the ONE existing transmission path)
    -> memory / belief / relationship / goal / WorkRuntime help task

Authority split:

* the speaker's own memory store (and the beliefs derived from it) is the
  only source of any assertion (:mod:`grounding`); this runtime never reads
  outbreak records, other citizens' stores or executors' positions to decide
  what someone says — it reads them only to decide who can talk to whom
  (availability, co-presence: §11, §27);
* transmission of a told fact is cognition's ``receive_fact`` (provenance,
  told confidence, trust rules, avoidance decision): dialogue is a channel
  into it, never a second memory path (§14);
* a request accepted by a citizen becomes a ``WorkRuntime.assist`` task —
  dialogue moves nobody and performs no work (§3, §17);
* NPC<->NPC conversations are sparse and context-driven: a question when
  meeting an alarmed citizen, a request when a coworker has a visible
  problem, a shout or a call at a first-hand threat (§39); they are
  sequenced one act per second so a threat can interrupt them (§9, §28);
* player conversations are driven by the bridge ``TALK`` command; the player
  is a registered citizen whose store receives what it is told (§11).

Everything is deterministic and persisted (sessions, requests, cooldowns,
events, counts) so save/load continues byte-identically.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

from ..cognition import memory as M
from ..cognition.runtime import HELP_THRESHOLD
from ..embodied.executor import EmbodimentState
from . import acts as A
from . import grounding as G
from .render import render
from .session import (ACTIVE, CALL, CHANNELS, Conversation, ENDED, FACE_TO_FACE, INTERRUPTED, PLAYER, PROBE, SHOUT)

DIALOGUE_SCHEMA_VERSION = 1
MAX_EVENTS = 5000
MAX_CONVERSATIONS_KEPT = 400        # ended conversations kept (ring)
TALK_RADIUS_M = 6.0                 # face-to-face outdoors / player reach
REQUEST_COOLDOWN_S = 3600.0         # after a refusal the same pair is not asked again for an hour
ASK_COOLDOWN_S = 1800.0             # one "what happened?" per pair per half hour
PLAYER_TIMEOUT_S = 120.0            # an idle player conversation ends
REQ_TIMEOUT_S = 1800.0              # an accepted request not started in time fails


def _d(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class DialogueRuntime:
    def __init__(self, cognition, names: Optional[Callable[[int], str]] = None):
        self.cog = cognition
        self.mobility = cognition.mobility
        self.work = cognition.work
        self.names = names
        self.now_s = float(cognition.now_s)
        self.conversations: Dict[str, Conversation] = {}
        self.requests: Dict[str, A.Request] = {}
        self.events: List[dict] = []
        self.event_seq = 0
        self.counts: Dict[str, int] = {}
        self.seq = 0                                  # conversation / request id counter
        self.ask_last: Dict[Tuple[int, int], float] = {}
        self.request_last: Dict[Tuple[int, int], float] = {}
        self.player_sessions: Dict[int, str] = {}     # player cid -> conv id
        self.rendered: List[dict] = []                # small transcript for UI (ring)
        cognition.dialogue = self

    # ------------------------------------------------------------------ basics
    def event(self, kind: str, **info) -> dict:
        self.event_seq += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        row = {"seq": self.event_seq, "t": round(self.now_s, 1), "event": kind}
        row.update(info)
        self.events.append(row)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return row

    def _nid(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}:{self.seq}"

    def warmth(self, a: int, b: int) -> float:
        r = self.cog.rels.get(a, b)
        return (r.familiarity + r.affinity) / 2.0 if r else 0.0

    # ------------------------------------------------------------------ availability (§27)
    def available(self, cid: int, channel: str) -> Tuple[bool, str]:
        ex = self.mobility.execs.get(int(cid))
        if ex is None:
            return False, "not_registered"
        if ex.override in ("incapacitated", "corpse", "undead"):
            return False, f"override:{ex.override}"
        rt = self.mobility.citizens.get(int(cid))
        g = rt.active_goal if rt is not None else None
        # a fleeing citizen does not stop for a chat; it will shout a warning in
        # passing (one act) and answer the player briefly (§27)
        if channel == FACE_TO_FACE and g is not None and g.source == "emergency" and g.kind.value == "flee" \
                and ex.state not in (EmbodimentState.DOING_ACTIVITY, EmbodimentState.INSIDE_BUILDING):
            return False, "fleeing"
        if channel in (FACE_TO_FACE, PLAYER) and str(ex.activity) == "sleep":
            return False, "asleep"
        return True, ""

    def _fresh_threat(self, cid: int, since_s: float) -> bool:
        st = self.cog.memories.get(int(cid))
        return st is not None and any(f.kind in M.THREAT_KINDS and f.first_hand() and f.last_t > since_s
                                      for f in st.facts.values())

    def co_present(self, a: int, b: int) -> Tuple[bool, str]:
        ea, eb = self.mobility.execs.get(a), self.mobility.execs.get(b)
        if ea is None or eb is None:
            return False, "missing"
        if ea.inside or eb.inside:
            if ea.inside and eb.inside and ea.building_id == eb.building_id:
                ca, cb = self.cog._ctx(a), self.cog._ctx(b)
                if ca.get("room_id") == cb.get("room_id"):
                    return True, "same_room"
                return False, "different_room"
            return False, "one_inside"
        return (_d(ea.pos, eb.pos) <= TALK_RADIUS_M), "outdoors"

    def can_call(self, a: int, b: int) -> bool:
        r = self.cog.rels.get(a, b)
        return r is not None and (r.origin in ("household", "workplace") or r.familiarity >= 0.55)

    # ------------------------------------------------------------------ sessions
    def _start(self, a: int, b: int, channel: str, topic: Optional[dict] = None) -> Conversation:
        conv = Conversation(self._nid("conv"), [int(a), int(b)], channel, self.now_s, last_s=self.now_s, topic=topic)
        ex = self.mobility.execs.get(int(a))
        if ex is not None and ex.inside:
            conv.building_id = int(ex.building_id)
            conv.room_id = self.cog._ctx(int(a)).get("room_id")
        self.conversations[conv.conv_id] = conv
        self.event("CONVERSATION_STARTED", conv_id=conv.conv_id, speaker=int(a), listener=int(b), channel=channel,
                   building_id=conv.building_id, room_id=conv.room_id, topic=topic)
        return conv

    def _end(self, conv: Conversation, reason: str, interrupted: bool = False) -> None:
        if conv.state != ACTIVE:
            return
        conv.state = INTERRUPTED if interrupted else ENDED
        conv.end_reason = reason
        conv.last_s = self.now_s
        dropped = len(conv.open_questions) + len(conv.plan)
        conv.open_questions = []
        conv.plan = []
        for rid in conv.open_requests:
            r = self.requests.get(rid)
            if r is not None and r.state == A.REQ_PENDING:
                r.state = A.REQ_CANCELLED
                r.reason = reason
                self.event("REQUEST_CANCELLED", request_id=rid, reason=reason, conv_id=conv.conv_id)
        conv.open_requests = []
        self.event("CONVERSATION_INTERRUPTED" if interrupted else "CONVERSATION_ENDED", conv_id=conv.conv_id,
                   participants=list(conv.participants), channel=conv.channel, reason=reason,
                   acts=conv.n_acts, dropped=dropped)
        for p in list(self.player_sessions):
            if self.player_sessions[p] == conv.conv_id:
                del self.player_sessions[p]
        self._trim()

    def _trim(self) -> None:
        done = [k for k, c in self.conversations.items() if c.state != ACTIVE]
        if len(done) > MAX_CONVERSATIONS_KEPT:
            for k in sorted(done, key=lambda k: self.conversations[k].last_s)[: len(done) - MAX_CONVERSATIONS_KEPT]:
                del self.conversations[k]

    # ------------------------------------------------------------------ speaking
    def say(self, conv: Conversation, speaker: int, act: str, prop: Optional[A.Proposition] = None, *,
            request: Optional[A.Request] = None, reason: str = "", answer_to: Optional[int] = None) -> Optional[dict]:
        """Emit one act. Any proposition is grounded against the SPEAKER's own
        store first; an unsupported one is rejected and not spoken."""
        listener = conv.other(speaker)
        grounded, verdict = (None, "accepted")
        if prop is not None:
            store = self.cog.memories.get(int(speaker))
            grounded, verdict = G.ground(store, prop, self.now_s)
            if grounded is None:
                self.event("GROUNDING_REJECTED", conv_id=conv.conv_id, speaker=int(speaker), listener=listener, act=act,
                           proposition=prop.to_dict(), verdict=verdict)
                grounded = A.Proposition(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE, subject=prop.subject,
                                         building_id=prop.building_id, room_id=prop.room_id)
                act = A.ANSWER if act in (A.INFORM, A.WARN, A.ANSWER) else act
            elif verdict.startswith("downgraded"):
                self.event("GROUNDING_DOWNGRADED", conv_id=conv.conv_id, speaker=int(speaker), listener=listener,
                           act=act, asked=prop.to_dict(), grounded=grounded.to_dict(), verdict=verdict)
        line = render(act, grounded, speaker=speaker, listener=listener, names=self.names, now_s=self.now_s,
                      warmth=self.warmth(speaker, listener) if listener is not None else 0.0, reason=reason,
                      request=request)
        row = {"t": round(self.now_s, 1), "speaker": int(speaker), "listener": listener, "act": act,
               "proposition": (grounded.to_dict() if grounded is not None else None),
               "request_id": (request.request_id if request else None), "reason": reason, "line": line,
               "answer_to": answer_to}
        conv.add(row, f"[{int(speaker)}] {line}")
        conv.last_s = self.now_s
        conv.pass_turn(listener)
        self.event("SPEECH_ACT", conv_id=conv.conv_id, speaker=int(speaker), listener=listener, channel=conv.channel,
                   act=act, proposition=(grounded.to_dict() if grounded is not None else None),
                   request_id=(request.request_id if request else None), reason=reason, line=line,
                   building_id=conv.building_id, room_id=conv.room_id, grounding=verdict)
        if act in A.QUESTIONS:
            conv.open_questions.append({"act": act, "asker": int(speaker), "seq": self.event_seq,
                                        "proposition": (grounded.to_dict() if grounded is not None else None)})
            self.event("QUESTION_ASKED", conv_id=conv.conv_id, speaker=int(speaker), listener=listener, act=act,
                       proposition=(grounded.to_dict() if grounded is not None else None))
        if act == A.ANSWER and conv.open_questions:
            q = conv.open_questions.pop(0)
            self.event("ANSWERED", conv_id=conv.conv_id, speaker=int(speaker), listener=listener, question=q["act"],
                       proposition=(grounded.to_dict() if grounded is not None else None),
                       epistemic=(grounded.epistemic if grounded is not None else None))
        if act == A.THANK:
            self.event("THANKED", conv_id=conv.conv_id, speaker=int(speaker), listener=listener)
        self.rendered.append({"t": round(self.now_s, 1), "conv_id": conv.conv_id, "speaker": int(speaker),
                              "listener": listener, "act": act, "line": line})
        if len(self.rendered) > 200:
            del self.rendered[: len(self.rendered) - 200]
        return row

    # -- transmission: the ONE path into the listener's cognition ---------------------
    def transmit(self, conv: Conversation, speaker: int, listener: int, fact: M.MemoryFact, act: str = A.INFORM,
                 answer_to: Optional[int] = None, kind: Optional[str] = None) -> Optional[A.Proposition]:
        """Speak a fact and hand it to cognition's receive_fact. The fact must
        be the speaker's own (grounding checks that); the listener's copy gets
        its provenance, told confidence and rules from cognition."""
        prop = G.proposition_from_fact(fact, self.now_s, kind=kind)
        row = self.say(conv, speaker, act, prop, answer_to=answer_to)
        g = row.get("proposition") if row else None
        if not g or g.get("kind") == A.UNKNOWN:
            return None
        res = self.cog.receive_fact(int(listener), int(speaker), fact, conv.channel, conv.building_id, conv.room_id)
        if res is None:
            return A.Proposition.from_dict(g)
        told, created, conf = res
        conv.facts_introduced.append(fact.origin_id)
        self.event("FACT_SHARED", conv_id=conv.conv_id, speaker=int(speaker), listener=int(listener), act=act,
                   fact_id=fact.fact_id, origin_id=fact.origin_id, origin_witness=fact.origin_witness,
                   hops=fact.hops + 1, epistemic=g.get("epistemic"), confidence=g.get("confidence"),
                   channel=conv.channel, building_id=fact.building_id, room_id=fact.room_id, fact_kind=fact.kind)
        # report the lineage that was actually TOLD (origin witness, origin id, hop count),
        # the same values cognition logs in WARNING_RECEIVED and this method logs in
        # FACT_SHARED. When the telling merged into a fact the listener already held from
        # a different source, the stored copy keeps its own lineage, but the dialogue and
        # cognition streams must not disagree about who said what.
        self.event("FACT_RECEIVED", conv_id=conv.conv_id, speaker=int(speaker), listener=int(listener),
                   fact_id=told.fact_id, origin_id=fact.origin_id, origin_witness=fact.origin_witness,
                   hops=fact.hops + 1, confidence=round(conf, 3), created=created, channel=conv.channel,
                   fact_kind=told.kind, building_id=told.building_id, room_id=told.room_id)
        return A.Proposition.from_dict(g)

    # ------------------------------------------------------------------ NPC <-> NPC (§12, §13)
    def warn(self, sender: int, recipient: int, fact: M.MemoryFact, channel: str, bid=None, rid=None) -> bool:
        """Cognition decided ``sender`` tells ``recipient`` ``fact`` over
        ``channel`` (the roll, cooldowns and dedupe are cognition's). A shout
        is one act now; a face-to-face encounter or a call is a short
        sequenced conversation the listener opens with a question."""
        def fleeing(c):
            rt = self.mobility.citizens.get(c)
            g = rt.active_goal if rt is not None else None
            return g is not None and g.source == "emergency"
        if channel == SHOUT or (channel != CALL and (fleeing(sender) or fleeing(recipient))):
            # a shout through the building, or an alarmed citizen calling out to
            # someone it passes: one act, no exchange to sit through
            ch = SHOUT if channel == SHOUT else FACE_TO_FACE
            if ch == FACE_TO_FACE and not self.co_present(sender, recipient)[0]:
                # a warning in passing still needs the two within talking distance (§27);
                # cognition's encounter radius is wider than the runtime's TALK_RADIUS_M
                self.event("TALK_REFUSED", speaker=sender, listener=recipient, reason="not_co_present", channel=ch)
                return False
            conv = self._start(sender, recipient, ch, topic={"kind": fact.kind, "event_ref": fact.fact_id})
            p = self.transmit(conv, sender, recipient, fact, act=A.WARN)
            self._end(conv, "shout" if ch == SHOUT else "warning_in_passing")
            return p is not None
        if channel == CALL and not self.can_call(sender, recipient):
            self.event("CALL_REFUSED", speaker=sender, listener=recipient, reason="no_contact_channel")
            return False
        ch = CALL if channel == CALL else FACE_TO_FACE
        if ch == FACE_TO_FACE and not self.co_present(sender, recipient)[0]:
            # a sequenced face-to-face warning requires co-presence, the same rule ask()
            # and _step_plan enforce; without it the telling does not happen face to face
            self.event("TALK_REFUSED", speaker=sender, listener=recipient, reason="not_co_present", channel=ch)
            return False
        for k, c in self.conversations.items():
            if c.state == ACTIVE and set(c.participants) == {sender, recipient}:
                return False           # already talking
        conv = self._start(sender, recipient, ch, topic={"kind": fact.kind, "event_ref": fact.fact_id,
                                                          "building_id": fact.building_id, "room_id": fact.room_id})
        # the recipient sees an alarmed person / picks up: asks; the sender answers with the fact,
        # says where when asked, is thanked; sequenced one act per second
        conv.plan = [{"speaker": recipient, "act": A.GREET if ch == CALL else A.ASK_FACT},
                     {"speaker": sender, "act": A.WARN if ch == CALL else A.ANSWER, "fact_id": fact.fact_id},
                     {"speaker": recipient, "act": A.ASK_LOCATION, "if_place": True},
                     {"speaker": sender, "act": A.ANSWER, "location_of": fact.fact_id},
                     {"speaker": recipient, "act": A.THANK},
                     {"speaker": sender, "act": A.END_CONVERSATION}]
        if ch == CALL:
            conv.plan[0] = {"speaker": recipient, "act": A.GREET}
        self._step_plan(conv)          # the first act happens at once
        return True

    def _step_plan(self, conv: Conversation) -> None:
        if conv.state != ACTIVE or not conv.plan:
            return
        a, b = conv.participants
        for c in (a, b):
            ok, why = self.available(c, conv.channel)
            if not ok:
                self._end(conv, why, interrupted=True)
                return
        if conv.channel == FACE_TO_FACE:
            ok, why = self.co_present(a, b)
            if not ok:
                self._end(conv, f"separated:{why}", interrupted=True)
                return
        if conv.channel != SHOUT and any(self._fresh_threat(c, conv.last_s) for c in (a, b)) and conv.n_acts > 0 \
                and (conv.topic or {}).get("kind") not in M.THREAT_KINDS:
            self._end(conv, "threat", interrupted=True)
            return
        step = conv.plan.pop(0)
        sp = int(step["speaker"])
        st = self.cog.memories.get(sp)
        act = step["act"]
        if act in (A.ANSWER, A.WARN, A.INFORM) and step.get("fact_id"):
            f = st.facts.get(step["fact_id"]) if st else None
            if f is None or f.effective(self.now_s) < G.RETRIEVAL_FLOOR:
                self.say(conv, sp, A.ANSWER, A.Proposition(kind=A.UNKNOWN, epistemic=A.UNCERTAIN, detail="decayed"))
            else:
                self.transmit(conv, sp, conv.other(sp), f, act=act)
        elif act == A.ASK_LOCATION and step.get("if_place"):
            last = conv.acts[-1].get("proposition") if conv.acts else None
            if not last or last.get("kind") == A.UNKNOWN or last.get("building_id") is None:
                # nothing to locate: drop the where/answer pair AND the recipient's own later THANK
                # so the recipient does not speak twice in a row — it thanks now and yields the turn.
                conv.plan = [s for s in conv.plan if not s.get("location_of")
                             and not (int(s["speaker"]) == sp and s["act"] == A.THANK)]
                self.say(conv, sp, A.THANK)
            else:
                self.say(conv, sp, A.ASK_LOCATION)
        elif act == A.ANSWER and step.get("location_of"):
            p = G.location_answer(st, self.now_s, step["location_of"])
            self.say(conv, sp, A.ANSWER, p)
        else:
            self.say(conv, sp, act)
        if not conv.plan:
            self._end(conv, "done")

    # -- questions between citizens (also used by the certification harness) -----------
    def ask(self, asker: int, answerer: int, act: str, *, subject: Optional[int] = None,
            building_id: Optional[int] = None, room_id: Optional[int] = None, event_ref: Optional[str] = None,
            channel: str = FACE_TO_FACE, thank: bool = True) -> Optional[dict]:
        """One question and its grounded answer (both acts now). Returns the
        answer row or None when the two cannot talk."""
        for c in (asker, answerer):
            ok, why = self.available(c, channel)
            if not ok:
                self.event("TALK_REFUSED", speaker=asker, listener=answerer, reason=f"{c}:{why}", channel=channel)
                return None
        if channel == FACE_TO_FACE:
            ok, why = self.co_present(asker, answerer)
            if not ok:
                self.event("TALK_REFUSED", speaker=asker, listener=answerer, reason=f"not_co_present:{why}", channel=channel)
                return None
        if channel == CALL and not self.can_call(asker, answerer):
            self.event("TALK_REFUSED", speaker=asker, listener=answerer, reason="no_contact_channel", channel=channel)
            return None
        conv = self._start(asker, answerer, channel, topic={"kind": act, "subject": subject, "building_id": building_id,
                                                            "room_id": room_id, "event_ref": event_ref})
        q = A.Proposition(kind=A.UNKNOWN, subject=subject, building_id=building_id, room_id=room_id, event_ref=event_ref)
        self.say(conv, asker, act, q)
        row = self._answer(conv, answerer, asker, act, subject, building_id, room_id, event_ref)
        if thank:
            self.say(conv, asker, A.THANK if row and row["proposition"] and row["proposition"].get("kind") != A.UNKNOWN
                     else A.ACKNOWLEDGE)
        self._end(conv, "done")
        return row

    def _answer(self, conv: Conversation, answerer: int, asker: int, act: str, subject, building_id, room_id,
                event_ref) -> Optional[dict]:
        st = self.cog.memories.get(int(answerer))
        if act == A.ASK_FACT:
            p = G.event_answer(st, self.now_s, building_id=building_id, subject=subject)
        elif act == A.ASK_PERSON:
            p = G.person_answer(st, self.now_s, int(subject)) if subject is not None else \
                A.Proposition(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE)
        elif act == A.ASK_SAFETY:
            bid = building_id
            if bid is None:
                ex = self.mobility.execs.get(int(answerer))
                bid = int(ex.building_id) if ex is not None and ex.inside else None
            p = G.safety_answer(st, self.cog.beliefs(int(answerer)), self.now_s, bid, room_id) if bid is not None else \
                A.Proposition(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE)
        elif act == A.ASK_LOCATION:
            ref = event_ref
            if ref is None:
                # the last fact this answerer asserted in this or its previous conversation with the asker
                for c in sorted(self.conversations.values(), key=lambda c: -c.last_s):
                    if set(c.participants) == {int(asker), int(answerer)}:
                        for r in reversed(c.acts):
                            pr = r.get("proposition")
                            if r["speaker"] == int(answerer) and pr and pr.get("event_ref"):
                                ref = pr["event_ref"]
                                break
                    if ref:
                        break
            p = G.location_answer(st, self.now_s, ref)
        else:
            p = A.Proposition(kind=A.UNKNOWN, epistemic=A.NO_KNOWLEDGE)
        if p.kind == A.UNKNOWN:
            row = self.say(conv, answerer, A.ANSWER, p)
            self.event("ANSWER_UNKNOWN", conv_id=conv.conv_id, speaker=int(answerer), listener=int(asker), question=act,
                       epistemic=p.epistemic, detail=p.detail, subject=subject, building_id=building_id)
            return row
        f = st.facts.get(p.event_ref) if (st is not None and p.event_ref) else None
        if conv.channel != PROBE and f is not None and act in (A.ASK_FACT, A.ASK_PERSON, A.ASK_SAFETY) \
                and p.kind != A.PLACE_IS_SAFE:
            # an answer that carries a fact is a telling: it goes through cognition like any warning.
            # a PROBE is a read-only inspection ("what would you say"): it renders the answer with its
            # true epistemic frame but never writes the fact into the asker's store.
            self.transmit(conv, answerer, asker, f, act=A.ANSWER, kind=p.kind)
            return conv.acts[-1] if conv.acts else None
        return self.say(conv, answerer, A.ANSWER, p)

    # ------------------------------------------------------------------ requests (§16–§19)
    def evaluate_request(self, helper: int, requester: int, problem: dict) -> Tuple[bool, str, float, dict, Optional[Tuple[str, str]]]:
        """The decision boundary: cognition's help score plus the structured
        reason when it refuses. Returns (accept, reason, score, components, target)."""
        w = self.work
        score, comps = self.cog.help_score(helper, requester, problem)
        r = self.cog.rels.get(helper, requester)
        a = w.activities.get(helper) if w is not None else None
        if a is None or a.kind != "worker" or a.help_for >= 0:
            return False, A.R_UNAVAILABLE, score, comps, None
        if a.task_id in ("man_register", "serve_customer", "cover_station") and w.queues.get(a.object_id or ""):
            return False, A.R_URGENT_TASK, score, comps, None
        tgt = w.help_target(helper, problem)
        if tgt is None:
            return False, A.R_NO_CAPABILITY, score, comps, None
        if r is not None and (r.fear + r.hostility) >= 0.3:
            return False, A.R_TOO_DANGEROUS, score, comps, tgt
        if score >= HELP_THRESHOLD:
            return True, "", score, comps, tgt
        rel = (r.familiarity + r.affinity + r.obligation) if r else 0.0
        return False, (A.R_LOW_TRUST if rel < 0.5 else A.R_COST), score, comps, tgt

    def request_help(self, requester: int, helper: int, problem: dict, channel: str = FACE_TO_FACE) -> Optional[A.Request]:
        """``requester`` asks ``helper`` for help with ``problem`` (a
        WorkRuntime.problems row). The helper decides through cognition; an
        acceptance becomes a real WorkRuntime help task at once."""
        w = self.work
        if w is None:
            return None
        key = (int(requester), int(helper))
        if self.now_s - self.request_last.get(key, -1e9) < REQUEST_COOLDOWN_S:
            return None
        for c in (requester, helper):
            ok, why = self.available(c, channel)
            if not ok:
                return None
        if channel == FACE_TO_FACE and not self.co_present(requester, helper)[0]:
            # a face-to-face request needs the two in the same room, exactly as ask()/warn() do
            return None
        self.request_last[key] = self.now_s
        kind_hint = {"unstaffed_queue": "cover_station", "queue_overload": "cover_station",
                     "station_failed": "repair_station", "cleaning_workload": "help_clean",
                     "restock_workload": "help_restock"}.get(problem.get("kind"), "help")
        req = A.Request(self._nid("req"), kind_hint, int(requester), int(helper), object_id=problem.get("object_id"),
                        building_id=int(w.activities[requester].building_id) if requester in w.activities else None,
                        problem=str(problem.get("kind")), created_s=self.now_s)
        conv = self._start(requester, helper, channel, topic={"kind": "request", "request_id": req.request_id})
        req.conversation_id = conv.conv_id
        self.requests[req.request_id] = req
        conv.open_requests.append(req.request_id)
        self.say(conv, requester, A.REPORT_PROBLEM, request=req)
        self.say(conv, requester, A.ASK_FOR_HELP, request=req)
        self.event("REQUEST_MADE", request_id=req.request_id, conv_id=conv.conv_id, speaker=int(requester),
                   listener=int(helper), request_kind=req.kind, problem=req.problem, object_id=req.object_id,
                   building_id=req.building_id, channel=channel)
        accept, reason, score, comps, tgt = self.evaluate_request(helper, requester, problem)
        cf_score, _ = self.cog.help_score(helper, requester, problem, rel_override=False)
        req.score, req.components, req.decided_s = score, comps, self.now_s
        if accept and tgt is not None:
            task_id, oid = tgt
            req.kind, req.object_id = task_id, oid
            if w.assist(helper, task_id, oid, requester):
                req.state = A.REQ_ACCEPTED
                self.say(conv, helper, A.ACCEPT, request=req)
                self.cog.help_pairs[(helper, requester)] = self.cog.help_pairs.get((helper, requester), 0) + 1
                row = self.cog.event("HELP_DECIDED", citizen_id=helper, beneficiary=requester, problem=problem.get("kind"),
                                     problem_object=problem.get("object_id"), task_id=task_id, object_id=oid,
                                     building_id=req.building_id, score=score, threshold=HELP_THRESHOLD,
                                     components=comps, score_without_history=cf_score,
                                     would_help_without_history=bool(cf_score >= HELP_THRESHOLD),
                                     via="request", request_id=req.request_id, utterance="ACCEPT")
                self.cog.pending_help[helper] = row
                self.cog.help_log.append({k: v for k, v in row.items() if k != "components"} | {"components": comps})
                self.event("REQUEST_ACCEPTED", request_id=req.request_id, conv_id=conv.conv_id, speaker=int(helper),
                           listener=int(requester), task_id=task_id, object_id=oid, score=score, components=comps,
                           score_without_history=cf_score, building_id=req.building_id)
                conv.open_requests = [x for x in conv.open_requests if x != req.request_id]
                self.say(conv, requester, A.THANK)
                self._end(conv, "request_accepted")
                return req
            req.state = A.REQ_FAILED
            req.reason = "assist_failed"
            self.say(conv, helper, A.REFUSE, request=req, reason=A.R_UNAVAILABLE)
            self.event("REQUEST_FAILED", request_id=req.request_id, reason="assist_failed", conv_id=conv.conv_id)
            conv.open_requests = [x for x in conv.open_requests if x != req.request_id]
            self._end(conv, "request_failed")
            return req
        req.state = A.REQ_REFUSED
        req.reason = reason
        self.say(conv, helper, A.REFUSE, request=req, reason=reason)
        self.event("REQUEST_REFUSED", request_id=req.request_id, conv_id=conv.conv_id, speaker=int(helper),
                   listener=int(requester), reason=reason, score=score, threshold=HELP_THRESHOLD, components=comps,
                   score_without_history=cf_score, building_id=req.building_id)
        # the requester remembers the refusal; it will not ask this coworker again for a while
        self.cog.remember(requester, M.REFUSED_BY, source=M.PARTICIPANT, actor=int(helper), target=int(requester),
                          building_id=req.building_id, detail=reason)
        self.cog.relate(requester, helper, "refused_by", reason=reason)
        self.say(conv, requester, A.ACKNOWLEDGE)
        conv.open_requests = [x for x in conv.open_requests if x != req.request_id]
        self._end(conv, "request_refused")
        return req

    def on_help_done(self, helper: int, beneficiary: int, task_id: str, object_id: str) -> None:
        for r in self.requests.values():
            if r.state == A.REQ_ACCEPTED and r.accepter == helper and r.requester == beneficiary:
                r.state = A.REQ_COMPLETED
                r.completed_s = self.now_s
                self.event("REQUEST_COMPLETED", request_id=r.request_id, speaker=int(helper), listener=int(beneficiary),
                           task_id=task_id, object_id=object_id, elapsed_s=round(self.now_s - r.created_s, 1))
                # a thank-you where they stand (no new session needed)
                conv = self.conversations.get(r.conversation_id)
                if conv is not None:
                    conv.state = ACTIVE
                    self.say(conv, beneficiary, A.THANK)
                    conv.state = ENDED
                break

    # ------------------------------------------------------------------ player (§11, §26)
    PLAYER_OPTIONS = ("ASK_FACT", "ASK_LOCATION", "ASK_PERSON", "ASK_SAFETY", "ASK_FOR_HELP", "END_CONVERSATION")

    def player_talk(self, player: int, npc: int, act: str, args: Optional[dict] = None) -> dict:
        """The bridge TALK command. The player is a registered citizen; its
        acts are structured; the NPC's answer is grounded in the NPC's store."""
        args = args or {}
        player, npc = int(player), int(npc)
        conv_id = self.player_sessions.get(player)
        conv = self.conversations.get(conv_id) if conv_id else None
        if conv is not None and (conv.state != ACTIVE or npc not in conv.participants):
            conv = None
        if conv is None:
            ok, why = self.available(npc, PLAYER)
            if not ok:
                return {"ok": False, "reason": why, "npc": npc}
            ok, why = self.co_present(player, npc)
            if not ok:
                return {"ok": False, "reason": f"not_co_present:{why}", "npc": npc}
            conv = self._start(player, npc, PLAYER)
            self.player_sessions[player] = conv.conv_id
            # the greeting pair opens the session; it lands in the transcript, not in
            # this turn's returned lines
            self.say(conv, player, A.GREET)
            self.say(conv, npc, A.GREET)
        else:
            ok, why = self.available(npc, PLAYER)
            if not ok:
                self._end(conv, why, interrupted=True)
                return {"ok": False, "reason": why, "npc": npc, "conv_id": conv.conv_id}
        act = str(act).upper()
        lines_before = len(conv.acts)
        if act == A.END_CONVERSATION:
            self.say(conv, player, A.END_CONVERSATION)
            self.say(conv, npc, A.END_CONVERSATION)
            self._end(conv, "player_left")
        elif act in (A.ASK_FACT, A.ASK_PERSON, A.ASK_SAFETY, A.ASK_LOCATION):
            subject = args.get("citizen_id", args.get("subject"))
            bid = args.get("building_id")
            rid = args.get("room_id")
            if act == A.ASK_SAFETY and bid is None:
                ex = self.mobility.execs.get(player)
                if ex is not None and ex.inside:
                    bid = int(ex.building_id)
                    rid = self.cog._ctx(player).get("room_id") if rid is None else rid
            q = A.Proposition(kind=A.UNKNOWN, subject=subject, building_id=bid, room_id=rid, event_ref=args.get("event_ref"))
            self.say(conv, player, act, q)
            self._answer(conv, npc, player, act, subject, bid, rid, args.get("event_ref"))
        elif act == A.ASK_FOR_HELP:
            self._player_request(conv, player, npc, args)
        elif act == A.THANK:
            self.say(conv, player, A.THANK)
            self.say(conv, npc, A.ACKNOWLEDGE)
        elif act == A.GREET:
            pass
        else:
            return {"ok": False, "reason": "unknown_act", "npc": npc, "options": list(self.PLAYER_OPTIONS)}
        new = conv.acts[lines_before:]
        return {"ok": True, "conv_id": conv.conv_id, "npc": npc, "state": conv.state, "acts": new,
                "lines": [r["line"] for r in new], "transcript": list(conv.transcript),
                "options": list(self.PLAYER_OPTIONS), "warmth": round(self.warmth(npc, player), 3),
                "relationship": (self.cog.rels.get(npc, player).to_dict() if self.cog.rels.get(npc, player) else None)}

    def _player_request(self, conv: Conversation, player: int, npc: int, args: dict) -> None:
        w = self.work
        kind = str(args.get("kind", "cover_station"))
        oid = args.get("object_id")
        problem = None
        if w is not None:
            ex = self.mobility.execs.get(player)
            bid = int(ex.building_id) if ex is not None and ex.inside else None
            if bid is not None:
                for pr in w.problems(bid):
                    if oid and pr.get("object_id") == oid:
                        problem = pr
                        break
                    if pr.get("citizen_id") == player:
                        problem = pr
                if problem is None:
                    reg = w.registry(bid)
                    if oid and reg.get(oid) is not None:
                        o = reg.get(oid)
                        problem = {"kind": "station_failed" if not o.available() else "unstaffed_queue",
                                   "object_id": oid, "citizen_id": player, "queue": len(w.queues.get(oid, []))}
                    else:
                        problem = {"kind": {"cover_station": "unstaffed_queue", "repair_station": "station_failed",
                                            "help_clean": "cleaning_workload", "help_restock": "restock_workload"}.get(kind, "unstaffed_queue"),
                                   "object_id": oid, "citizen_id": player}
        req = A.Request(self._nid("req"), kind, player, npc, object_id=oid, building_id=(problem or {}).get("building_id"),
                        problem=(problem or {}).get("kind", kind), created_s=self.now_s, conversation_id=conv.conv_id)
        self.requests[req.request_id] = req
        conv.open_requests.append(req.request_id)
        self.say(conv, player, A.ASK_FOR_HELP, request=req)
        self.event("REQUEST_MADE", request_id=req.request_id, conv_id=conv.conv_id, speaker=player, listener=npc,
                   request_kind=req.kind, problem=req.problem, object_id=req.object_id, channel=PLAYER)
        if w is None or problem is None:
            req.state, req.reason = A.REQ_REFUSED, A.R_NO_CAPABILITY
            self.say(conv, npc, A.REFUSE, request=req, reason=A.R_NO_CAPABILITY)
            # no problem to evaluate: the refusal still carries the (empty) score components,
            # so every accept/refuse decision in the tape is uniformly shaped
            self.event("REQUEST_REFUSED", request_id=req.request_id, conv_id=conv.conv_id, speaker=npc, listener=player,
                       reason=A.R_NO_CAPABILITY, score=-1.0, components={})
            conv.open_requests.remove(req.request_id)
            return
        accept, reason, score, comps, tgt = self.evaluate_request(npc, player, problem)
        req.score, req.components, req.decided_s = score, comps, self.now_s
        if accept and tgt is not None and w.assist(npc, tgt[0], tgt[1], player):
            req.kind, req.object_id, req.state = tgt[0], tgt[1], A.REQ_ACCEPTED
            self.say(conv, npc, A.ACCEPT, request=req)
            self.event("REQUEST_ACCEPTED", request_id=req.request_id, conv_id=conv.conv_id, speaker=npc, listener=player,
                       task_id=tgt[0], object_id=tgt[1], score=score, components=comps)
            self.cog.help_pairs[(npc, player)] = self.cog.help_pairs.get((npc, player), 0) + 1
            self.cog.pending_help[npc] = self.cog.event("HELP_DECIDED", citizen_id=npc, beneficiary=player,
                                                        problem=problem.get("kind"), task_id=tgt[0], object_id=tgt[1],
                                                        building_id=req.building_id, score=score, threshold=HELP_THRESHOLD,
                                                        components=comps, via="player_request", request_id=req.request_id)
        else:
            req.state, req.reason = A.REQ_REFUSED, (reason or A.R_UNAVAILABLE)
            self.say(conv, npc, A.REFUSE, request=req, reason=req.reason)
            self.event("REQUEST_REFUSED", request_id=req.request_id, conv_id=conv.conv_id, speaker=npc, listener=player,
                       reason=req.reason, score=score, components=comps)
            self.cog.relate(player, npc, "refused_by", reason=req.reason)
        conv.open_requests = [x for x in conv.open_requests if x != req.request_id]

    # ------------------------------------------------------------------ clock
    def advance(self, dt_s: float) -> None:
        remaining = float(dt_s)
        while remaining > 1e-9:
            step = min(1.0, remaining)
            self.now_s += step
            self._substep()
            remaining -= step

    def _substep(self) -> None:
        for k in sorted(self.conversations):
            conv = self.conversations[k]
            if conv.state != ACTIVE:
                continue
            if conv.plan:
                self._step_plan(conv)
            elif conv.channel == PLAYER:
                npc = conv.participants[1]
                ok, why = self.available(npc, PLAYER)
                if not ok:
                    self._end(conv, why, interrupted=True)
                    continue
                if self._fresh_threat(npc, conv.last_s) or self._fresh_threat(conv.participants[0], conv.last_s):
                    self._end(conv, "threat", interrupted=True)
                    continue
                ok, why = self.co_present(conv.participants[0], npc)
                if not ok:
                    self._end(conv, f"separated:{why}", interrupted=True)
                elif self.now_s - conv.last_s > PLAYER_TIMEOUT_S:
                    self._end(conv, "timeout")
            elif not conv.open_requests and not conv.open_questions:
                self._end(conv, "done")
        for r in self.requests.values():
            if r.state == A.REQ_ACCEPTED and self.now_s - r.decided_s > REQ_TIMEOUT_S:
                a = self.work.activities.get(r.accepter) if self.work is not None else None
                if a is None or a.help_for != r.requester:
                    r.state, r.reason = A.REQ_FAILED, "not_started"
                    self.event("REQUEST_FAILED", request_id=r.request_id, reason="not_started", speaker=r.accepter,
                               listener=r.requester)
                    self.cog.relate(r.requester, r.accepter, "abandoned_by", reason="promise_not_kept")

    # ------------------------------------------------------------------ queries
    def active_conversation_of(self, cid: int) -> Optional[Conversation]:
        for c in self.conversations.values():
            if c.state == ACTIVE and int(cid) in c.participants:
                return c
        return None

    def row(self, cid: int) -> dict:
        c = self.active_conversation_of(cid)
        reqs = [r.request_id for r in self.requests.values() if r.state == A.REQ_ACCEPTED and int(cid) in (r.requester, r.accepter)]
        return {"conversation": (c.conv_id if c else None), "with": (c.other(int(cid)) if c else None),
                "channel": (c.channel if c else None), "open_requests": reqs}

    def snapshot(self, since_seq: int = 0) -> dict:
        active = [c.to_state() for k, c in sorted(self.conversations.items()) if c.state == ACTIVE]
        return {"version": DIALOGUE_SCHEMA_VERSION, "now_s": self.now_s, "n_conversations": len(self.conversations),
                "active": active, "requests": {k: r.to_dict() for k, r in sorted(self.requests.items())
                                                 if r.state in (A.REQ_PENDING, A.REQ_ACCEPTED)},
                "events": [e for e in self.events if e["seq"] > int(since_seq)], "event_seq": self.event_seq,
                "counts": dict(sorted(self.counts.items())), "recent_lines": self.rendered[-20:]}

    # ------------------------------------------------------------------ persistence
    def to_state(self) -> dict:
        return {"version": DIALOGUE_SCHEMA_VERSION, "now_s": self.now_s, "seq": self.seq,
                "conversations": {k: c.to_state() for k, c in sorted(self.conversations.items())},
                "requests": {k: r.to_dict() for k, r in sorted(self.requests.items())},
                "ask_last": {f"{a}:{b}": t for (a, b), t in sorted(self.ask_last.items())},
                "request_last": {f"{a}:{b}": t for (a, b), t in sorted(self.request_last.items())},
                "player_sessions": {str(p): c for p, c in sorted(self.player_sessions.items())},
                "rendered": list(self.rendered), "events": list(self.events), "event_seq": self.event_seq,
                "counts": dict(sorted(self.counts.items()))}

    @classmethod
    def from_state(cls, st: dict, cognition, names=None) -> "DialogueRuntime":
        d = cls(cognition, names=names)
        d.now_s = float(st.get("now_s", d.now_s))
        d.seq = int(st.get("seq", 0))
        d.conversations = {k: Conversation.from_state(v) for k, v in (st.get("conversations") or {}).items()}
        d.requests = {k: A.Request.from_dict(v) for k, v in (st.get("requests") or {}).items()}
        d.ask_last = {(int(k.split(":")[0]), int(k.split(":")[1])): float(v) for k, v in (st.get("ask_last") or {}).items()}
        d.request_last = {(int(k.split(":")[0]), int(k.split(":")[1])): float(v)
                          for k, v in (st.get("request_last") or {}).items()}
        d.player_sessions = {int(k): str(v) for k, v in (st.get("player_sessions") or {}).items()}
        d.rendered = list(st.get("rendered") or [])
        d.events = list(st.get("events") or [])
        d.event_seq = int(st.get("event_seq", 0))
        d.counts = {str(k): int(v) for k, v in (st.get("counts") or {}).items()}
        return d

#!/usr/bin/env python3
"""Per-city smoke test for the NPC dialogue runtime
(ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1).

For each requested city bundle: boot the world exactly as the game does
(bridge ``START_WORLD`` with a player citizen, which enables mobility, work,
cognition and — by default — conversations), run one day (05:00 -> 17:00 in
60 s steps) with the certification threat stressor seeded inside the busiest
shop at ~10:35, drain ``GET_DIALOGUE`` every game minute and report what the
citizens actually said:

    * the day: CONVERSATION_STARTED / ENDED / INTERRUPTED, SPEECH_ACT,
      QUESTION_ASKED, ANSWERED, ANSWER_UNKNOWN, FACT_SHARED / FACT_RECEIVED,
      REQUEST_MADE / ACCEPTED / REFUSED / COMPLETED, GROUNDING_REJECTED,
      THANKED, TALK_REFUSED — as emitted events and as the runtime's
      persistent counts;
    * the channel histogram of every spoken act (face_to_face / shout / call /
      player) and the epistemic histogram of every proposition spoken
      ("I saw" / "X told me" / "I heard" / "I think" / "I'm not sure" /
      "I don't know");
    * a grounding audit: every SPEECH_ACT whose proposition is not UNKNOWN is
      checked against the SPEAKER's own memory store in the same game minute —
      the store must hold the ``event_ref`` fact the proposition cites. Nobody
      may say what they do not know. The audit is repeated over
      ``session.world.cognition.memories`` after the run, where a fact
      consolidated away since it was spoken shows up as ``since_forgotten``
      rather than as a violation;
    * one TALK probe: the player greets a co-present NPC, asks it what
      happened and leaves (INFO when no NPC is co-present with anyone in the
      probe window);
    * determinism: the city is built and run twice — booted at 05:00, seeded
      by the same rule at the same game minute and advanced three further game
      hours — and the two dialogue event lists and the rendered lines must be
      identical;
    * cost: wall time and milliseconds per game minute.

Status per city:
    PASS   conversations happened, at least one fact was received or a request
           was decided, the grounding audit is clean, no rejected proposition
           of a real kind reached a listener, and the run was deterministic
    INFO   no compiled world in the bundle (nothing to embody), or no citizen
           in the bundle is employable (nobody is ever delivered to work, so
           there is nothing to perceive and nothing to say)
    FAIL   anything else

Exit code is non-zero when any city FAILs.
Writes artifacts/npc_dialogue_v1/city_smoke.json.

    PYTHONPATH=. python3 tools/dialogue_city_smoke.py [city ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from collections import Counter
from typing import Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.bridge.worldfactory import resolve_bundle_dir           # noqa: E402
from asphodel.dialogue import acts as A                               # noqa: E402
from asphodel.dialogue import runtime as DR                           # noqa: E402
from asphodel.dialogue import session as DS                           # noqa: E402

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio", "boulder"]
ARTIFACT = os.path.join(REPO, "artifacts", "npc_dialogue_v1", "city_smoke.json")

START_HOUR = 5.0
END_HOUR = 17.0
STEP_S = 60.0
SEED_HOUR = 10.5833                  # 10:35 — the earliest the stressor may be seeded
SEED_CUTOFF_HOUR = 12.0
PATHOGEN = "classic_zombie_fast"
FALLBACK_PATHOGEN = "classic_zombie"
DETERMINISM_HOURS = 3.0              # game hours run past the seeding in each replay
SEED = 0
PROBE_FROM = 9.0                     # the TALK probe is attempted between these hours
PROBE_TO = 12.0
PLAYER_CITIZEN = 0                   # any registered citizen: TALK needs a player at START_WORLD

# the events that tell the story of a day of conversation, in reading order
STORY_EVENTS = ("CONVERSATION_STARTED", "SPEECH_ACT", "QUESTION_ASKED", "ANSWERED",
                "ANSWER_UNKNOWN", "FACT_SHARED", "FACT_RECEIVED", "REQUEST_MADE",
                "REQUEST_ACCEPTED", "REQUEST_REFUSED", "REQUEST_COMPLETED", "REQUEST_FAILED",
                "REQUEST_CANCELLED", "GROUNDING_REJECTED", "GROUNDING_DOWNGRADED", "THANKED",
                "TALK_REFUSED", "CALL_REFUSED", "CONVERSATION_ENDED", "CONVERSATION_INTERRUPTED")
HEADLINE = ("CONVERSATION_STARTED", "CONVERSATION_ENDED", "CONVERSATION_INTERRUPTED", "SPEECH_ACT",
            "QUESTION_ASKED", "ANSWERED", "ANSWER_UNKNOWN", "FACT_SHARED", "FACT_RECEIVED",
            "REQUEST_MADE", "REQUEST_ACCEPTED", "REQUEST_REFUSED", "REQUEST_COMPLETED",
            "GROUNDING_REJECTED", "THANKED", "TALK_REFUSED")


def has_compiled_world(bundle_dir: str) -> bool:
    """A bundle is embodiable only if its compiled world carries spawn anchors."""
    return os.path.exists(os.path.join(bundle_dir, "world", "spawn_anchors.json.gz"))


def build_world(city: str, start_hour: float, seed: int = SEED,
                player_citizen: Optional[int] = PLAYER_CITIZEN):
    """World + mobility + work + cognition + dialogue, exactly as the game
    boots one (START_WORLD enables dialogue by default whenever cognition is
    on). Returns ``(session, world, player_citizen)`` — the session issues
    SEED_OUTBREAK, TALK and GET_DIALOGUE the way the client does."""
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
           "start_hour": float(start_hour)}
    if player_citizen is not None:
        msg["player_citizen"] = int(player_citizen)
    r = s.handle(msg)
    if not r.get("ok") and player_citizen is not None:
        msg.pop("player_citizen")           # a bundle whose population lacks that id
        r = s.handle(msg)
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    if not r.get("dialogue_enabled"):
        raise RuntimeError(f"START_WORLD did not enable dialogue for {city}: {r}")
    return s, s.world, s.player_citizen


class EventTape:
    """The complete dialogue event trace.

    ``DialogueRuntime.events`` is a ring buffer capped at ``MAX_EVENTS`` (5000)
    and a threatened city turns it over quickly, so the tape drains the runtime
    once per game minute through ``GET_DIALOGUE(since_seq)`` and keeps
    everything. ``dropped`` records whether the ring lost rows between two
    drains (it never should at a one-minute drain interval).
    """

    def __init__(self, session):
        self.session = session
        self.events: List[dict] = []
        self.last_seq = 0
        self.dropped = 0
        self.drain()

    def drain(self) -> List[dict]:
        snap = self.session.handle({"cmd": Command.GET_DIALOGUE,
                                    "since_seq": self.last_seq})["dialogue"]
        rows = snap["events"]
        if rows and rows[0]["seq"] > self.last_seq + 1:
            self.dropped += rows[0]["seq"] - self.last_seq - 1
        if rows:
            self.events.extend(rows)
            self.last_seq = rows[-1]["seq"]
        return rows


def customer_sessions(w) -> Dict[int, List[int]]:
    """Open ``customer`` work sessions grouped by building (never by name)."""
    out: Dict[int, List[int]] = {}
    wk = w.work
    if wk is None:
        return out
    for cid, a in sorted(wk.activities.items()):
        if a.kind == "customer":
            out.setdefault(int(a.building_id), []).append(int(cid))
    return out


def try_seed(session, w, seed_hour: float, cutoff_hour: float) -> Optional[dict]:
    """Seed the stressor if this game minute is the moment to do it.

    The moment is the first game minute at or after ``seed_hour`` in which any
    building has an open customer session; the busiest such building (ties by
    lowest id) is the shop and its lowest customer id is the index case. Past
    ``cutoff_hour`` with no customer anywhere, the fallback pathogen is seeded
    with the data-driven index case.
    """
    hour = w.current_hour()
    if hour < seed_hour - 1e-9:
        return None
    by_b = customer_sessions(w)
    if by_b:
        bid = sorted(by_b.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0][0]
        cid = min(by_b[bid])
        r = session.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": PATHOGEN,
                            "citizen_id": int(cid)})
        if not r.get("ok"):
            raise RuntimeError(f"SEED_OUTBREAK failed: {r}")
        return {"pathogen": PATHOGEN, "building_id": int(bid), "citizen_id": int(cid),
                "index_case": r.get("index_case"), "hour": round(hour, 4), "fallback": False,
                "n_customer_sessions_there": len(by_b[bid]),
                "n_buildings_with_customers": len(by_b),
                "note": ("the busiest shop is the building with the most open customer work "
                         f"sessions at the first game minute at or after {seed_hour:.4f}h in "
                         "which any customer session exists; ties by lowest building id, index "
                         "case = lowest customer id there")}
    if hour >= cutoff_hour - 1e-9:
        r = session.handle({"cmd": Command.SEED_OUTBREAK, "pathogen": FALLBACK_PATHOGEN})
        if not r.get("ok"):
            raise RuntimeError(f"SEED_OUTBREAK (fallback) failed: {r}")
        return {"pathogen": FALLBACK_PATHOGEN, "building_id": None, "citizen_id": None,
                "index_case": r.get("index_case"), "hour": round(hour, 4), "fallback": True,
                "note": (f"no customer work session existed anywhere between {seed_hour:.2f}h and "
                         f"{cutoff_hour:.2f}h, so the fallback was seeded: {FALLBACK_PATHOGEN} "
                         "with the data-driven index case")}
    return None


# --------------------------------------------------------------------------- #
# the grounding audit (checked live, in the game minute the words were said)
# --------------------------------------------------------------------------- #
class GroundingAudit:
    """Nobody may say what they do not know.

    Every ``SPEECH_ACT`` whose proposition is not ``UNKNOWN`` cites an
    ``event_ref``: the id of the fact in the SPEAKER's own store that supports
    it (dialogue/grounding.py: ``ground`` returns a proposition built from that
    fact and nothing else). The audit checks the citation against
    ``cognition.memories[speaker]`` in the same game minute the words were
    said, because ``MemoryStore.consolidate`` runs every 600 s of game time and
    a fact spoken at 09:00 may legitimately be gone by 17:00.
    """

    def __init__(self, w):
        self.cog = w.cognition
        self.checked = 0
        self.missing: List[dict] = []
        self.no_event_ref: List[dict] = []
        self.by_kind: Counter = Counter()
        self.seen: List[Tuple[int, str, dict]] = []      # (speaker, event_ref, row) for the re-check

    def check(self, rows: List[dict]) -> None:
        for e in rows:
            if e.get("event") != "SPEECH_ACT":
                continue
            p = e.get("proposition")
            if not p or p.get("kind") in (None, A.UNKNOWN):
                continue
            self.by_kind[p["kind"]] += 1
            self.checked += 1
            speaker = int(e["speaker"])
            ref = p.get("event_ref")
            row = {"t": e["t"], "seq": e["seq"], "speaker": speaker, "act": e.get("act"),
                   "kind": p["kind"], "epistemic": p.get("epistemic"), "event_ref": ref,
                   "line": e.get("line")}
            if not ref:
                self.no_event_ref.append(row)
                continue
            st = self.cog.memories.get(speaker)
            if st is None or ref not in st.facts:
                self.missing.append(row)
            else:
                self.seen.append((speaker, ref, row))

    def report(self, w) -> dict:
        """The live verdict, plus the same citations re-checked against
        ``world.cognition.memories`` after the run."""
        still, forgotten = 0, []
        for speaker, ref, row in self.seen:
            st = w.cognition.memories.get(speaker)
            if st is not None and ref in st.facts:
                still += 1
            elif len(forgotten) < 10:
                forgotten.append(row)
        n_forgotten = len(self.seen) - still
        return {
            "n_propositions_checked": self.checked,
            "n_unsupported_when_spoken": len(self.missing),
            "n_without_event_ref": len(self.no_event_ref),
            "clean": bool(not self.missing and not self.no_event_ref),
            "unsupported_examples": self.missing[:10],
            "without_event_ref_examples": self.no_event_ref[:10],
            "kinds_spoken": dict(self.by_kind.most_common()),
            "after_the_run": {
                "n_citations_still_held": still,
                "n_citations_since_forgotten": n_forgotten,
                "forgotten_examples": forgotten,
                "note": ("re-read from session.world.cognition.memories after the run; a citation "
                         "no longer held was consolidated away between being spoken and the end "
                         "of the day (MemoryStore.consolidate runs every 600 s of game time), "
                         "which is memory working, not a grounding failure"),
            },
            "note": ("every proposition of a kind other than UNKNOWN must cite a fact the SPEAKER "
                     "holds, checked in the same game minute it was spoken"),
        }


def leaked_rejections(events: List[dict]) -> dict:
    """A rejected proposition must never reach the listener.

    ``say`` replaces an unsupported proposition with an UNKNOWN one before it
    is rendered (dialogue/runtime.py, GROUNDING_REJECTED), so for every
    rejection the next act by that speaker in that conversation must carry
    either no proposition or an UNKNOWN one.
    """
    by_seq = sorted(events, key=lambda e: e["seq"])
    leaks: List[dict] = []
    rejects = [e for e in by_seq if e["event"] == "GROUNDING_REJECTED"]
    for r in rejects:
        for e in by_seq:
            if e["seq"] <= r["seq"] or e["event"] != "SPEECH_ACT":
                continue
            if e.get("conv_id") != r.get("conv_id") or int(e["speaker"]) != int(r["speaker"]):
                continue
            p = e.get("proposition") or {}
            if p.get("kind") not in (None, A.UNKNOWN):
                leaks.append({"rejected": r, "spoken": e})
            break
    return {"n_grounding_rejected": len(rejects), "n_reached_the_listener": len(leaks),
            "clean": not leaks, "examples": leaks[:5],
            "rejection_verdicts": dict(Counter(r.get("verdict") for r in rejects).most_common()),
            "note": ("a rejected proposition is downgraded to UNKNOWN before it is rendered, so "
                     "the act that follows a GROUNDING_REJECTED in the same conversation must "
                     "carry an UNKNOWN proposition or none")}


# --------------------------------------------------------------------------- #
# the TALK probe
# --------------------------------------------------------------------------- #
def co_present_pair(w, prefer: Optional[int] = None) -> Optional[dict]:
    """Two citizens the dialogue runtime agrees are co-present and available.

    Read from ``work.occupants_by_room`` (never by building name) and confirmed
    through ``DialogueRuntime.co_present`` / ``available``. A room holding the
    booted player citizen wins, so the probe is the real player when it can be.
    """
    d, wk = w.dialogue, w.work
    if d is None or wk is None:
        return None
    bids = sorted({int(ex.building_id) for ex in w.mobility.execs.values()
                   if ex.inside and ex.building_id is not None})
    best = None
    for bid in bids:
        for rid, occ in sorted(wk.occupants_by_room(bid).items(), key=lambda kv: str(kv[0])):
            occ = sorted(int(c) for c in occ if d.available(int(c), DS.PLAYER)[0])
            if len(occ) < 2:
                continue
            first = prefer if (prefer in occ) else occ[0]
            for b in occ:
                if b == first or not d.co_present(first, b)[0]:
                    continue
                cand = {"player": first, "npc": b, "building_id": bid, "room_id": rid,
                        "n_in_room": len(occ), "is_booted_player": bool(first == prefer)}
                if best is None or (cand["is_booted_player"], cand["n_in_room"]) > \
                        (best["is_booted_player"], best["n_in_room"]):
                    best = cand
                break
        if best is not None and best["is_booted_player"]:
            return best
    return best


def talk_probe(session, w, player: Optional[int]) -> dict:
    """GREET + ASK_FACT + END_CONVERSATION through the bridge TALK command.

    ``player_citizen`` is passed on the command (the bridge accepts it per
    TALK) so the probe is a genuinely co-present pair: the citizen booted as
    the player is rarely standing in a room with anybody.
    """
    pair = co_present_pair(w, prefer=player)
    if pair is None:
        return {"ok": False, "status": "INFO", "hour": round(w.current_hour(), 4),
                "reason": "no NPC was co-present with any citizen in any room in the probe window"}
    out = {"ok": True, "hour": round(w.current_hour(), 4), "pair": pair, "turns": []}
    for act, args in (("GREET", {}), ("ASK_FACT", {"building_id": pair["building_id"]}),
                      ("END_CONVERSATION", {})):
        t0 = time.perf_counter()
        r = session.handle({"cmd": Command.TALK, "citizen_id": int(pair["npc"]),
                            "player_citizen": int(pair["player"]), "act": act, "args": args})
        out["turns"].append({"act": act, "ok": bool(r.get("ok")), "reason": r.get("reason"),
                             "error": r.get("error"), "lines": r.get("lines"),
                             "transcript": r.get("transcript"), "state": r.get("state"),
                             "warmth": r.get("warmth"),
                             "ms": round((time.perf_counter() - t0) * 1000.0, 3)})
    out["ok"] = all(t["ok"] for t in out["turns"])
    out["note"] = ("the player is a registered citizen; TALK needs it co-present with the NPC in "
                   "the same room (dialogue/runtime.py co_present)")
    return out


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #
def run_day(session, w, end_hour: float, tape: Optional[EventTape] = None,
            audit: Optional[GroundingAudit] = None, seed_hour: float = SEED_HOUR,
            cutoff_hour: float = SEED_CUTOFF_HOUR,
            stop_hours_after_seed: Optional[float] = None,
            probe: bool = False, player: Optional[int] = None) -> dict:
    """Advance in 60 s steps, seeding the stressor at its moment, draining the
    tape and auditing every game minute, and attempting one TALK probe."""
    spent = 0.0
    minutes = 0
    seeding: Optional[dict] = None
    probe_row: Optional[dict] = None
    stop_at = end_hour
    while w.current_hour() < stop_at - 1e-9:
        if seeding is None:
            seeding = try_seed(session, w, seed_hour, cutoff_hour)
            if seeding is not None and stop_hours_after_seed is not None:
                stop_at = min(end_hour, w.current_hour() + stop_hours_after_seed)
        t0 = time.perf_counter()
        w.advance_seconds(STEP_S)
        spent += time.perf_counter() - t0
        minutes += 1
        if tape is not None:
            rows = tape.drain()
            if audit is not None:
                audit.check(rows)
        if probe and probe_row is None and PROBE_FROM <= w.current_hour() < PROBE_TO:
            r = talk_probe(session, w, player)
            if r.get("ok") or w.current_hour() >= PROBE_TO - 1.0 / 60.0:
                probe_row = r
                if tape is not None:
                    rows = tape.drain()
                    if audit is not None:
                        audit.check(rows)
    return {"advance_s": spent, "seeding": seeding, "game_minutes": minutes,
            "probe": probe_row, "hour_after": round(w.current_hour(), 4)}


def dialogue_report(w, events: List[dict]) -> dict:
    """What was said, over which channel, with what epistemic standing."""
    d = w.dialogue
    speech = [e for e in events if e["event"] == "SPEECH_ACT"]
    props = [e["proposition"] for e in speech if e.get("proposition")]
    channels: Counter = Counter(e.get("channel") for e in speech)
    epistemic: Counter = Counter(p.get("epistemic") for p in props)
    kinds: Counter = Counter(p.get("kind") for p in props)
    acts: Counter = Counter(e.get("act") for e in speech)
    conv_channels: Counter = Counter(e.get("channel") for e in events
                                     if e["event"] == "CONVERSATION_STARTED")
    ends: Counter = Counter(e.get("reason") for e in events
                            if e["event"] in ("CONVERSATION_ENDED", "CONVERSATION_INTERRUPTED"))
    refusals: Counter = Counter(e.get("reason") for e in events if e["event"] == "REQUEST_REFUSED")
    per_citizen: Counter = Counter()
    for e in events:
        if e["event"] == "CONVERSATION_STARTED":
            per_citizen[int(e["speaker"])] += 1
            per_citizen[int(e["listener"])] += 1
    return {
        "n_speech_acts": len(speech),
        "n_propositions_spoken": len(props),
        "n_speakers": len({int(e["speaker"]) for e in speech}),
        "n_citizens_in_a_conversation": len(per_citizen),
        "conversations_per_citizen_max": max(per_citizen.values()) if per_citizen else 0,
        "acts": dict(acts.most_common()),
        "speech_act_channels": dict(sorted(channels.items())),
        "conversation_channels": dict(sorted(conv_channels.items())),
        "epistemic_histogram": dict(epistemic.most_common()),
        "proposition_kinds": dict(kinds.most_common()),
        "conversation_end_reasons": dict(ends.most_common()),
        "refusal_reasons": dict(refusals.most_common()),
        "rings": {"events_in_ring": len(d.events), "events_ring_cap": DR.MAX_EVENTS,
                  "conversations_kept": len(d.conversations),
                  "ended_conversations_kept": sum(1 for c in d.conversations.values()
                                                  if c.state != DS.ACTIVE),
                  "conversations_kept_cap": DR.MAX_CONVERSATIONS_KEPT,
                  "rendered_lines": len(d.rendered), "rendered_cap": 200,
                  "n_requests_tracked": len(d.requests),
                  "requests_by_state": dict(sorted(Counter(r.state for r in d.requests.values())
                                                   .items()))},
        "epistemic_note": ("the epistemic status is set by the fact the proposition is grounded "
                           "in, never by the speaker's intent: DIRECT_OBSERVATION / EXPERIENCED "
                           "are first-hand, SECOND_HAND / HEARSAY are told, and a told fact can "
                           "never be rendered as \"I saw\" (dialogue/grounding.py epistemic_of)"),
    }


def digest(w) -> dict:
    """A stable digest of every conversation and every request."""
    d = w.dialogue
    convs = [(c.conv_id, tuple(c.participants), c.channel, round(c.started_s, 3),
              round(c.last_s, 3), c.state, c.end_reason, c.n_acts, tuple(c.transcript),
              tuple(c.facts_introduced), c.building_id, c.room_id)
             for _k, c in sorted(d.conversations.items())]
    reqs = [(r.request_id, r.kind, r.requester, r.accepter, r.object_id, r.state, r.reason,
             round(r.score, 6), round(r.created_s, 3)) for _k, r in sorted(d.requests.items())]
    lines = [(round(x["t"], 1), x["conv_id"], x["speaker"], x["listener"], x["act"], x["line"])
             for x in d.rendered]

    def sha(obj) -> str:
        return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]

    return {"conversations": sha(convs), "requests": sha(reqs), "rendered": sha(lines),
            "n_conversations": len(convs), "n_requests": len(reqs),
            "n_rendered_lines": len(lines), "event_seq": d.event_seq,
            "counts": dict(sorted(d.counts.items()))}


def determinism_check(city: str, hours: float, seed: int = SEED,
                      seed_hour: float = SEED_HOUR) -> dict:
    """Two fresh worlds, each booted at 05:00, seeded by the same rule at the
    same game minute and advanced ``hours`` game hours past the seeding: the
    dialogue event lists, the rendered lines and the digests must match. No
    TALK probe runs here — the replay must be the world talking to itself."""
    runs = []
    for _ in range(2):
        session, w, _p = build_world(city, START_HOUR, seed)
        tape = EventTape(session)
        r = run_day(session, w, END_HOUR, tape, None, seed_hour, SEED_CUTOFF_HOUR,
                    stop_hours_after_seed=hours)
        lines = [(e["seq"], e.get("line")) for e in tape.events if e["event"] == "SPEECH_ACT"]
        runs.append((tape.events, digest(w), r["seeding"], r["game_minutes"], r["hour_after"],
                     lines))
    a_ev, a_dig, a_seed, a_min, a_hour, a_lines = runs[0]
    b_ev, b_dig, b_seed, b_min, b_hour, b_lines = runs[1]
    identical = json.dumps(a_ev, sort_keys=True) == json.dumps(b_ev, sort_keys=True)
    first_diff = None
    if not identical:
        for i in range(max(len(a_ev), len(b_ev))):
            x = a_ev[i] if i < len(a_ev) else None
            y = b_ev[i] if i < len(b_ev) else None
            if json.dumps(x, sort_keys=True) != json.dumps(y, sort_keys=True):
                first_diff = {"i": i, "run1": x, "run2": y}
                break
    lines_identical = a_lines == b_lines
    first_line_diff = None
    if not lines_identical:
        for i in range(max(len(a_lines), len(b_lines))):
            x = a_lines[i] if i < len(a_lines) else None
            y = b_lines[i] if i < len(b_lines) else None
            if x != y:
                first_line_diff = {"i": i, "run1": x, "run2": y}
                break
    same_seeding = json.dumps(a_seed, sort_keys=True) == json.dumps(b_seed, sort_keys=True)
    return {"hours_after_seeding": hours, "n_events_run1": len(a_ev), "n_events_run2": len(b_ev),
            "events_identical": identical, "first_difference": first_diff,
            "n_lines_run1": len(a_lines), "n_lines_run2": len(b_lines),
            "lines_identical": lines_identical, "first_line_difference": first_line_diff,
            "digest_run1": a_dig, "digest_run2": b_dig, "digests_identical": a_dig == b_dig,
            "seeding_run1": a_seed, "seeding_run2": b_seed, "seeding_identical": same_seeding,
            "game_minutes_run1": a_min, "game_minutes_run2": b_min,
            "hour_after_run1": a_hour, "hour_after_run2": b_hour,
            "deterministic": bool(identical and lines_identical and a_dig == b_dig and same_seeding),
            "note": (f"two freshly built worlds booted at {START_HOUR:.0f}:00, each seeding the "
                     "stressor by the same rule at the same game minute and advancing "
                     f"{hours:.0f} further game hours; the full dialogue event lists and every "
                     "rendered line are compared verbatim plus a digest of every conversation, "
                     "request and transcript")}


def story_sample(events: List[dict], start_hour: float, per_kind: int = 25) -> List[dict]:
    """The first ``per_kind`` rows of each story event kind, in time order.

    A flat head of the trace would be all SPEECH_ACT in a talkative city; the
    per-kind cap keeps the rarer, more interesting kinds visible.
    """
    seen: Counter = Counter()
    out = []
    for e in events:
        kind = e["event"]
        if kind not in STORY_EVENTS or seen[kind] >= per_kind:
            continue
        seen[kind] += 1
        out.append({"hour": round(start_hour + e["t"] / 3600.0, 3),
                    **{k: v for k, v in e.items() if k not in ("seq", "t")}})
    return out


# --------------------------------------------------------------------------- #
# one city
# --------------------------------------------------------------------------- #
def smoke_city(city: str, start_hour: float = START_HOUR, end_hour: float = END_HOUR,
               det_hours: float = DETERMINISM_HOURS, seed: int = SEED,
               seed_hour: float = SEED_HOUR, verbose: bool = True) -> dict:
    out = {"city": city, "status": "FAIL", "reason": ""}
    try:
        bundle_dir = resolve_bundle_dir(city)
    except FileNotFoundError as exc:
        return {**out, "status": "INFO", "reason": str(exc)}
    out["bundle_dir"] = bundle_dir
    if not has_compiled_world(bundle_dir):
        return {**out, "status": "INFO",
                "reason": "no compiled world (world/spawn_anchors.json.gz absent) — "
                          "nothing to embody"}

    t0 = time.perf_counter()
    session, w, player = build_world(city, start_hour, seed)
    out["setup_s"] = round(time.perf_counter() - t0, 2)
    out["player_citizen"] = player
    if w.mobility is None:
        return {**out, "status": "INFO",
                "reason": "no street graph in the bundle: mobility never started, so no "
                          "citizen is ever delivered into a building"}
    if w.dialogue is None:
        return {**out, "status": "FAIL", "reason": "START_WORLD did not enable the dialogue runtime"}

    out["n_citizens"] = len(w.mobility.execs)
    out["n_employed"] = len(w.work.employment) if w.work is not None else 0
    if not out["n_employed"]:
        n_wp = len({int(r.work_building_id) for r in w.mobility.records.values()
                    if r.work_building_id is not None})
        out["status"] = "INFO"
        out["reason"] = (f"nobody is employed: none of the {out['n_citizens']} registered citizens "
                         f"has a workplace whose smart objects support a job role ({n_wp} "
                         "workplace(s) in the bundle), so no citizen is ever delivered to work, "
                         "nothing is perceived and there is nothing to say")
        if verbose:
            print(f"  {city}: INFO — {out['reason']}")
        return out

    # -- the day -----------------------------------------------------------
    tape = EventTape(session)
    audit = GroundingAudit(w)
    t0 = time.perf_counter()
    run = run_day(session, w, end_hour, tape, audit, seed_hour, SEED_CUTOFF_HOUR,
                  probe=True, player=player)
    run_s = time.perf_counter() - t0
    events = tape.events
    d = w.dialogue
    minutes = run["game_minutes"]

    by_event = Counter(e["event"] for e in events)
    counts = dict(sorted(d.counts.items()))
    report = dialogue_report(w, events)
    audit_row = audit.report(w)
    leaks = leaked_rejections(events)

    out.update({
        "start_hour": start_hour, "end_hour": end_hour, "step_s": STEP_S,
        "game_minutes": minutes, "run_s": round(run_s, 2),
        "ms_per_game_minute": round(run["advance_s"] * 1000.0 / minutes, 3),
        "ms_per_game_minute_with_instrumentation": round(run_s * 1000.0 / minutes, 3),
        "threat_seed": run["seeding"],
        "n_events": len(events),
        "n_events_in_runtime_ring": len(d.events),
        "n_events_dropped_between_drains": tape.dropped,
        "counts": {k: int(counts.get(k, 0)) for k in HEADLINE},
        "counts_all": counts,
        "events_by_kind": dict(sorted(by_event.items())),
        "story_counts": {k: int(by_event.get(k, 0)) for k in STORY_EVENTS},
        "dialogue": report,
        "grounding_audit": audit_row,
        "rejections_reaching_listeners": leaks,
        "talk_probe": run["probe"] or {"ok": False, "status": "INFO",
                                       "reason": "the probe window passed without a co-present "
                                                 "pair"},
        "counts_note": ("`counts` are the runtime's persistent counters; `story_counts` are the "
                        "events actually emitted and drained through GET_DIALOGUE"),
        "story": story_sample(events, start_hour),
        "transcript_sample": [x for x in d.rendered[-20:]],
    })

    # -- determinism -------------------------------------------------------
    t0 = time.perf_counter()
    det = determinism_check(city, det_hours, seed, seed_hour)
    det["repeat_s"] = round(time.perf_counter() - t0, 2)
    out["determinism"] = det

    n_conv = int(counts.get("CONVERSATION_STARTED", 0))
    n_decided = sum(int(counts.get(k, 0)) for k in
                    ("FACT_RECEIVED", "REQUEST_ACCEPTED", "REQUEST_REFUSED"))
    reasons = []
    if not n_conv:
        reasons.append("no conversation happened all day")
    if not int(counts.get("SPEECH_ACT", 0)):
        reasons.append("no speech act was ever spoken")
    if not n_decided:
        reasons.append("nothing was transmitted or decided: no FACT_RECEIVED and no request "
                       "accepted or refused")
    if not audit_row["clean"]:
        reasons.append(f"the grounding audit found {audit_row['n_unsupported_when_spoken']} "
                       f"proposition(s) the speaker's store did not hold and "
                       f"{audit_row['n_without_event_ref']} with no citation at all")
    if not leaks["clean"]:
        reasons.append(f"{leaks['n_reached_the_listener']} rejected proposition(s) of a real kind "
                       "reached the listener")
    if not det["deterministic"]:
        reasons.append("the two replays diverged"
                       + ("" if det["events_identical"] else " (event lists differ)")
                       + ("" if det["lines_identical"] else " (rendered lines differ)")
                       + ("" if det["seeding_identical"] else " (the stressor was seeded "
                                                              "differently)"))
    out["n_conversations"] = n_conv
    out["n_transmissions_or_decisions"] = n_decided
    out["status"] = "FAIL" if reasons else "PASS"
    out["reason"] = "; ".join(reasons)
    if verbose:
        s = out["counts"]
        pb = out["talk_probe"]
        print(f"  {city}: {out['status']} ({out['n_citizens']} citizens, {n_conv} conversations, "
              f"{s['SPEECH_ACT']} speech acts, {s['QUESTION_ASKED']} questions, "
              f"{s['ANSWERED']} answered / {s['ANSWER_UNKNOWN']} unknown, "
              f"{s['FACT_RECEIVED']} facts received, {s['REQUEST_MADE']} requests "
              f"({s['REQUEST_ACCEPTED']} accepted / {s['REQUEST_REFUSED']} refused), "
              f"audit {audit_row['n_propositions_checked']} checked "
              f"{'clean' if audit_row['clean'] else 'DIRTY'}, "
              f"probe {'ok' if pb.get('ok') else 'INFO'}, {run_s:.0f} s run)")
        if out["reason"]:
            print(f"      reason: {out['reason']}")
    return out


def print_table(results: dict) -> None:
    cols = [("city", 16), ("status", 6), ("cits", 5), ("empl", 5), ("conv", 6), ("acts", 6),
            ("ask", 5), ("ans", 5), ("unk", 5), ("shar", 5), ("recv", 5), ("req", 4),
            ("acc", 4), ("ref", 4), ("done", 4), ("rej", 4), ("thx", 5), ("intr", 5),
            ("audit", 6), ("probe", 6), ("det", 4), ("ms/gm", 7)]
    print("")
    print("  ".join(n.ljust(w) for n, w in cols))
    print("  ".join("-" * w for _, w in cols))
    for city, r in results.items():
        if r["status"] == "INFO":
            vals = [city, "INFO"] + ["-"] * (len(cols) - 2)
        else:
            s, a, d = r["counts"], r["grounding_audit"], r["determinism"]
            vals = [city, r["status"], r["n_citizens"], r["n_employed"],
                    s["CONVERSATION_STARTED"], s["SPEECH_ACT"], s["QUESTION_ASKED"],
                    s["ANSWERED"], s["ANSWER_UNKNOWN"], s["FACT_SHARED"], s["FACT_RECEIVED"],
                    s["REQUEST_MADE"], s["REQUEST_ACCEPTED"], s["REQUEST_REFUSED"],
                    s["REQUEST_COMPLETED"], s["GROUNDING_REJECTED"], s["THANKED"],
                    s["CONVERSATION_INTERRUPTED"],
                    ("ok" if a["clean"] else "DIRTY") + f":{a['n_propositions_checked']}",
                    "ok" if r["talk_probe"].get("ok") else "none",
                    "ok" if d["deterministic"] else "DIFF", r["ms_per_game_minute"]]
        print("  ".join(str(v).ljust(w) for v, (_, w) in zip(vals, cols)))
    print("")
    for city, r in results.items():
        if r["status"] == "INFO":
            print(f"  {city} [INFO]: {r['reason']}")
            continue
        rep, a, ts = r["dialogue"], r["grounding_audit"], (r["threat_seed"] or {})
        pb = r["talk_probe"]
        print(f"  {city}: threat {ts.get('pathogen')} seeded on citizen {ts.get('citizen_id')} in "
              f"building {ts.get('building_id')} at {ts.get('hour')}h"
              + (" [FALLBACK]" if ts.get("fallback") else "")
              + f"; {rep['n_speech_acts']} acts by {rep['n_speakers']} speakers over "
              f"{rep['n_citizens_in_a_conversation']} citizens (max "
              f"{rep['conversations_per_citizen_max']} conversations each); channels "
              f"{rep['speech_act_channels']}; epistemic {rep['epistemic_histogram']}; "
              f"audit {a['n_propositions_checked']} propositions checked, "
              f"{a['n_unsupported_when_spoken']} unsupported, "
              f"{a['after_the_run']['n_citations_since_forgotten']} citations consolidated away "
              f"after being spoken; rejections reaching listeners "
              f"{r['rejections_reaching_listeners']['n_reached_the_listener']}; determinism "
              f"{'ok' if r['determinism']['deterministic'] else 'DIVERGED'} "
              f"({r['determinism']['n_events_run1']} events, "
              f"{r['determinism']['n_lines_run1']} lines)")
        if pb.get("ok"):
            lines = [ln for t in pb["turns"] for ln in (t.get("lines") or [])]
            print(f"      TALK probe at {pb['hour']}h: citizen {pb['pair']['player']} -> NPC "
                  f"{pb['pair']['npc']} in room {pb['pair']['room_id']} of building "
                  f"{pb['pair']['building_id']}: " + " | ".join(lines[:4]))
        else:
            print(f"      TALK probe: [INFO] {pb.get('reason')}")
        if r["reason"]:
            print(f"  {city} [{r['status']}]: {r['reason']}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", default=None)
    ap.add_argument("--start-hour", type=float, default=START_HOUR)
    ap.add_argument("--end-hour", type=float, default=END_HOUR)
    ap.add_argument("--seed-hour", type=float, default=SEED_HOUR,
                    help="earliest hour at which the threat stressor may be seeded")
    ap.add_argument("--determinism-hours", type=float, default=DETERMINISM_HOURS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)
    cities = args.cities or DEFAULT_CITIES

    t_all = time.perf_counter()
    results: Dict[str, dict] = {}
    for city in cities:
        print(f"[{city}] ...")
        try:
            results[city] = smoke_city(city, start_hour=args.start_hour, end_hour=args.end_hour,
                                       det_hours=args.determinism_hours, seed=args.seed,
                                       seed_hour=args.seed_hour)
        except Exception as exc:                     # a crash is a FAIL, not a stack trace
            traceback.print_exc()
            results[city] = {"city": city, "status": "FAIL",
                             "reason": f"exception: {type(exc).__name__}: {exc}"}
    wall_s = time.perf_counter() - t_all

    doc = {"version": 1, "milestone": "ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1",
           "start_hour": args.start_hour, "end_hour": args.end_hour, "step_s": STEP_S,
           "seed_hour": args.seed_hour, "pathogen": PATHOGEN,
           "fallback_pathogen": FALLBACK_PATHOGEN,
           "determinism_hours_after_seeding": args.determinism_hours, "seed": args.seed,
           "probe_window": [PROBE_FROM, PROBE_TO],
           "channels": list(DS.CHANNELS), "acts": list(A.ACTS),
           "wall_s": round(wall_s, 1), "python": sys.version.split()[0],
           "pass_requires": ["conversations happen (CONVERSATION_STARTED and SPEECH_ACT)",
                             "at least one FACT_RECEIVED or one request accepted or refused",
                             "the grounding audit is clean: every proposition of a kind other "
                             "than UNKNOWN cites a fact the speaker held when it spoke",
                             "no GROUNDING_REJECTED proposition of a kind other than UNKNOWN "
                             "reached the listener",
                             "identical dialogue events, rendered lines and digests over the "
                             "determinism replay, including the same seeding minute"],
           "cities": results}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
    print_table(results)
    print(f"  wall: {wall_s:.1f} s")
    print(f"  artifact: {args.out}")
    failed = [c for c, r in results.items() if r["status"] == "FAIL"]
    if failed:
        print(f"  FAIL: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Grounded conversations against a real Houston day
(ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 §2, §6-§9, §11-§21, §26, §27).

One world, 05:00 -> ~11:30, with a case of ``classic_zombie_fast`` seeded
into the first customer standing inside the busiest shop (15873) at the
first minute past 10:00. That citizen rises and attacks in room 0 at about
10:45; the witnesses shout, warn the people they pass and call the ties they
have, and the coworkers of the city ask each other for help all morning.

What that day has to prove:

* **D4 (no omniscience)** — every proposition anybody spoke was supported, at
  the second it was spoken, by a fact in THAT speaker's own store, with the
  same subject and place, an epistemic status equal to the one the fact's
  source dictates, and a confidence no higher than the fact's; nobody ever
  asserted a threat about a building it held no threat fact for, and no
  answer leaned on a fact that had decayed past the retrieval floor (**D26**).
* **D5 / D6** — a witness answers first-hand; a citizen who was told answers
  SECOND_HAND, naming its teller and carrying hops >= 1.
* **D8** — a citizen who knows nothing says "I don't know." and that answer
  is logged as ANSWER_UNKNOWN.
* **D11 / D12** — a face-to-face conversation only ever starts between
  co-present citizens (asking a far pair is refused ``not_co_present``); a
  call needs a contact channel (a household/workplace tie or familiarity),
  and without one it is refused ``no_contact_channel``.
* **D13** — an NPC<->NPC call is a sequenced exchange (GREET, WARN,
  ASK_LOCATION, ANSWER, THANK, END_CONVERSATION), one act per second.
* **D15** — transmission is cognition's: every FACT_RECEIVED has the matching
  cognition WARNING_RECEIVED with the same lineage, and the told fact is
  really in the listener's store.
* **D18-D21** — a request is decided, not assumed: every REQUEST_MADE ends
  accepted (a real WorkRuntime help task that completes and changes the
  object's state) or refused with a structured reason; a refusal creates no
  help task for that pair, leaves a REFUSED_BY memory and costs the refuser
  affinity.
* **D22 / D23** — the refusal was a threshold decision (the same request from
  a trusted, liked, owed coworker crosses HELP_THRESHOLD), and a completed
  request leaves obligation and affinity behind.
* **D24 / D25** — a conversation that lost a participant ends interrupted
  with its open questions dropped, and no fact is ever received without
  having been shared.
* **Q1** — knowledge, not the world, is what is being spoken: delete the
  witness's threat memories and the same question answers "I don't know."
"""
from __future__ import annotations

import math
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.cognition import memory as M
from asphodel.cognition.relationships import Relationship
from asphodel.cognition.runtime import HELP_THRESHOLD
from asphodel.dialogue import acts as A
from asphodel.dialogue import grounding as G
from asphodel.dialogue.session import ACTIVE, CALL, FACE_TO_FACE, INTERRUPTED, SHOUT
from asphodel.embodiment import CitySpatialContext

CITY = "houston"
START_HOUR = 5.0
END_HOUR = 11.5
SEED_AT_HOUR = 10.0
SHOP = 15873
FAR = (9000.0, 9000.0)
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
FIRST_HAND = (A.DIRECT, A.EXPERIENCED)
THREAT_PROPS = (A.PERSON_IS_DANGEROUS, A.ATTACK_HAPPENED, A.PERSON_DEAD, A.PLACE_IS_DANGEROUS)


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _probe(dl, asker: int, answerer: int, act: str, **kw) -> dict | None:
    """One question and its grounded answer between any two citizens. A real
    channel is used when the pair has one; otherwise the conversation is
    constructed directly (the same acts, no availability shortcut) so a
    citizen's knowledge can be questioned from the outside."""
    if dl.can_call(asker, answerer):
        row = dl.ask(asker, answerer, act, channel=CALL, **kw)
        if row is not None:
            return row
    subject, bid = kw.get("subject"), kw.get("building_id")
    rid, ref = kw.get("room_id"), kw.get("event_ref")
    conv = dl._start(asker, answerer, CALL, topic={"kind": act, "subject": subject,
                                                   "building_id": bid, "room_id": rid,
                                                   "event_ref": ref})
    dl.say(conv, asker, act, A.Proposition(kind=A.UNKNOWN, subject=subject, building_id=bid,
                                           room_id=rid, event_ref=ref))
    row = dl._answer(conv, answerer, asker, act, subject, bid, rid, ref)
    dl._end(conv, "done")
    return row


@pytest.fixture(scope="module")
def day():
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO, seed=0)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    c = w.enable_cognition()
    ob = w.enable_outbreak("classic_zombie_fast", seed_index_case=False)
    dl = w.enable_dialogue()
    w.mobility.set_focus_xy(FAR)

    # --- instrumentation: the ground truth each gate needs AT THE SECOND it
    # happened (stores decay and conversations roll, so nothing is inferred
    # from the end-of-day state).
    spoken: list[dict] = []
    started: list[dict] = []
    received: list[dict] = []
    rel_at: dict[tuple, dict] = {}

    work_log: list[dict] = []
    warning_log: list[dict] = []
    orig_cog_event = c.event

    def cog_event(kind, **info):
        row = orig_cog_event(kind, **info)
        if kind in ("WARNING_RECEIVED", "WARNING_SHARED"):
            warning_log.append(dict(row))
        return row

    c.event = cog_event
    orig_work_event = w.work.event

    def work_event(kind, **info):
        row = orig_work_event(kind, **info)
        if kind in ("HELP_TASK", "HELP_DONE", "STATE_CHANGE"):
            work_log.append(dict(row))
        return row

    w.work.event = work_event
    orig_start, orig_say, orig_event = dl._start, dl.say, dl.event

    def start(a, b, channel, topic=None):
        ok, why = dl.co_present(int(a), int(b))
        ea, eb = w.mobility.execs.get(int(a)), w.mobility.execs.get(int(b))
        gap = None
        if ea is not None and eb is not None and not ea.inside and not eb.inside:
            gap = round(math.hypot(ea.pos[0] - eb.pos[0], ea.pos[1] - eb.pos[1]), 1)
        conv = orig_start(a, b, channel, topic)
        started.append({"conv_id": conv.conv_id, "t": dl.now_s, "a": int(a), "b": int(b),
                        "channel": channel, "co_present": bool(ok), "why": why,
                        "topic": (topic or {}).get("kind"), "gap_m": gap,
                        "inside": (None if ea is None else (ea.inside, ea.building_id)),
                        "other_inside": (None if eb is None else (eb.inside, eb.building_id))})
        return conv

    def say(conv, speaker, act, prop=None, **kw):
        row = orig_say(conv, speaker, act, prop, **kw)
        if row is not None:
            p = row.get("proposition")
            st = c.memories.get(int(speaker))
            f = st.facts.get(p["event_ref"]) if (st and p and p.get("event_ref")) else None
            spoken.append({"t": dl.now_s, "conv_id": conv.conv_id, "channel": conv.channel,
                           "speaker": int(speaker), "listener": row.get("listener"),
                           "act": row["act"], "line": row["line"], "proposition": p,
                           "fact": (f.to_dict() if f is not None else None),
                           "effective": (None if f is None else f.effective(dl.now_s)),
                           "epistemic_of_fact": (None if f is None else G.epistemic_of(f, dl.now_s)),
                           "threat_facts_here": sorted(
                               g.fact_id for g in (st.facts.values() if st else ())
                               if g.kind in M.THREAT_KINDS and p is not None
                               and g.building_id == p.get("building_id"))})
        return row

    def event(kind, **info):
        row = orig_event(kind, **info)
        if kind == "FACT_RECEIVED":
            st = c.memories.get(int(info["listener"]))
            f = st.facts.get(info["fact_id"]) if st is not None else None
            received.append({"row": dict(row), "fact": (None if f is None else f.to_dict())})
        if kind in ("REQUEST_MADE", "REQUEST_ACCEPTED", "REQUEST_REFUSED", "REQUEST_COMPLETED"):
            req = dl.requests.get(info.get("request_id"))
            if req is not None:
                r = c.rels.get(req.requester, req.accepter)
                rel_at[(kind, req.request_id)] = (None if r is None else r.to_dict())
        return row

    dl._start, dl.say, dl.event = start, say, event

    seeded = None
    while w.current_hour() < END_HOUR:
        w.advance_seconds(60.0, focus_xy=FAR)
        if seeded is None and w.current_hour() >= SEED_AT_HOUR:
            inside = sorted(cid for cid, a in w.work.activities.items()
                            if a.building_id == SHOP and a.kind == "customer"
                            and w.mobility.execs[cid].inside
                            and w.mobility.execs[cid].building_id == SHOP)
            if inside:
                seeded = inside[0]
                ob.seed_index_case(seeded)
    assert seeded is not None, "no customer was ever inside the busiest shop"

    events = [dict(e) for e in dl.events]
    cog_events = warning_log        # live: the probes below add to it too
    work_events = work_log
    conversations = {k: v.to_state() for k, v in dl.conversations.items()}
    requests = {k: r.to_dict() for k, r in dl.requests.items()}

    def alive(cid):
        ex = w.mobility.execs.get(int(cid))
        return ex is not None and not ex.override

    def about_shop(f):
        return f.building_id == SHOP and f.kind in M.THREAT_KINDS

    witnesses = sorted(cid for cid, st in c.memories.items()
                       if alive(cid) and any(about_shop(f) and f.first_hand() for f in st.facts.values()))
    hearsay = sorted(cid for cid, st in c.memories.items()
                     if alive(cid) and not any(about_shop(f) and f.first_hand() for f in st.facts.values())
                     and any(about_shop(f) and f.source == M.TOLD for f in st.facts.values()))
    ignorant = sorted(cid for cid in c.memories
                      if alive(cid) and not any(f.kind in M.THREAT_KINDS
                                                for f in c.memories[cid].facts.values()))
    assert witnesses and hearsay and len(ignorant) >= 3, (witnesses, hearsay, len(ignorant))

    # --- the probes (all mutation of the day happens here, in this order)
    probes: dict = {}
    seq_before = dl.event_seq
    probes["ignorant"] = {"answerer": ignorant[0], "asker": ignorant[1],
                          "row": _probe(dl, ignorant[1], ignorant[0], A.ASK_FACT, building_id=SHOP)}
    probes["ignorant"]["events"] = [e for e in dl.events if e["seq"] > seq_before]

    probes["witness"] = {"answerer": witnesses[0], "asker": ignorant[2],
                         "row": _probe(dl, ignorant[2], witnesses[0], A.ASK_FACT, building_id=SHOP),
                         "store": [f.to_dict() for f in c.memories[witnesses[0]].facts.values()]}
    probes["told"] = {"answerer": hearsay[0], "asker": ignorant[3],
                      "row": _probe(dl, ignorant[3], hearsay[0], A.ASK_FACT, building_id=SHOP)}

    # a face-to-face question to somebody far away, and a call to a stranger
    execs = w.mobility.execs
    far_pair = None
    for a in ignorant[4:40]:
        for b in reversed(ignorant[4:40]):
            if a == b or not (dl.available(a, FACE_TO_FACE)[0] and dl.available(b, FACE_TO_FACE)[0]):
                continue
            if not dl.co_present(a, b)[0]:
                far_pair = (a, b)
                break
        if far_pair:
            break
    no_tie = None
    for a in ignorant[4:40]:
        for b in reversed(ignorant[4:40]):
            if a != b and not dl.can_call(a, b) and dl.available(a, CALL)[0] and dl.available(b, CALL)[0]:
                no_tie = (a, b)
                break
        if no_tie:
            break
    assert far_pair and no_tie, (far_pair, no_tie)
    seq_before = dl.event_seq
    probes["far"] = {"pair": far_pair,
                     "row": dl.ask(far_pair[0], far_pair[1], A.ASK_FACT, building_id=SHOP,
                                   channel=FACE_TO_FACE),
                     "events": None}
    probes["far"]["events"] = [e for e in dl.events if e["seq"] > seq_before]
    seq_before = dl.event_seq
    probes["no_tie"] = {"pair": no_tie,
                        "row": dl.ask(no_tie[0], no_tie[1], A.ASK_FACT, building_id=SHOP, channel=CALL)}
    probes["no_tie"]["events"] = [e for e in dl.events if e["seq"] > seq_before]

    # retrieval on a real store stays bounded
    probes["retrieval"] = {"cid": witnesses[0],
                           "n": len(G.retrieve(c.memories[witnesses[0]], dl.now_s,
                                               kinds=G.EVENT_KINDS, building_id=SHOP)),
                           "n_facts": len(c.memories[witnesses[0]].facts)}

    # --- Q1: the same witness, with its threat memories deleted
    wit = witnesses[0]
    st = c.memories[wit]
    forgotten = [f.fact_id for f in list(st.facts.values())
                 if f.kind in M.THREAT_KINDS or (f.building_id == SHOP and f.kind in G.EVENT_KINDS)]
    for fid in forgotten:
        st.forget(fid)
    c._beliefs.pop(wit, None)
    probes["forgotten"] = {"cid": wit, "ids": forgotten,
                           "row": _probe(dl, ignorant[2], wit, A.ASK_FACT, building_id=SHOP)}

    return {"world": w, "cog": c, "dialogue": dl, "seeded": seeded, "events": events,
            "cog_events": cog_events, "work_events": work_events, "conversations": conversations,
            "requests": requests, "spoken": spoken, "started": started, "received": received,
            "rel_at": rel_at, "witnesses": witnesses, "hearsay": hearsay, "ignorant": ignorant,
            "probes": probes, "counts": dict(dl.counts)}


def _rows(day, kind):
    return [e for e in day["events"] if e["event"] == kind]


# --------------------------------------------------------------------------- #
# the day happened at all
# --------------------------------------------------------------------------- #
def test_the_day_produced_conversations_warnings_and_requests(day):
    for kind in ("CONVERSATION_STARTED", "CONVERSATION_ENDED", "SPEECH_ACT", "FACT_SHARED",
                 "FACT_RECEIVED", "REQUEST_MADE", "REQUEST_ACCEPTED", "REQUEST_REFUSED",
                 "REQUEST_COMPLETED"):
        assert _rows(day, kind), f"the day never produced a {kind}"
    channels = Counter(r["channel"] for r in _rows(day, "CONVERSATION_STARTED"))
    assert channels[SHOUT] and channels[FACE_TO_FACE] and channels[CALL], channels
    assert day["counts"]["SPEECH_ACT"] > 100


# --------------------------------------------------------------------------- #
# D4 / D26: no omniscience — every assertion is the speaker's own memory
# --------------------------------------------------------------------------- #
def test_every_proposition_was_supported_by_the_speakers_own_fact(day):
    checked = 0
    for s in day["spoken"]:
        p = s["proposition"]
        if not p or p["kind"] == A.UNKNOWN:
            continue
        checked += 1
        f = s["fact"]
        assert p["event_ref"], (s["act"], p)
        assert f is not None, f"{s['speaker']} asserted {p['kind']} with no fact {p['event_ref']}"
        assert f["owner"] == s["speaker"], (s["speaker"], f["owner"])
        subject = f["target"] if f["kind"] in (M.CORPSE_SEEN, M.DEATH_SEEN) else f["actor"]
        if p["kind"] not in (A.PLACE_IS_DANGEROUS, A.PLACE_IS_SAFE, A.EVENT_LOCATION):
            assert p["subject"] == subject, (s["act"], p["kind"], p["subject"], subject)
        if p["kind"] not in (A.PLACE_IS_DANGEROUS, A.PLACE_IS_SAFE):
            assert p["building_id"] == f["building_id"], (s["act"], p, f["building_id"])
            assert p["room_id"] == f["room_id"], (s["act"], p, f["room_id"])
        assert p["origin_id"] == f["origin_id"] and p["hops"] == f["hops"], (p, f)
        assert p["origin_witness"] == f["origin_witness"]
    assert checked > 50, f"only {checked} grounded propositions were spoken all day"


def test_the_epistemic_status_of_every_line_is_the_status_of_its_fact(day):
    seen = Counter()
    for s in day["spoken"]:
        p = s["proposition"]
        if not p or p["kind"] == A.UNKNOWN or s["fact"] is None:
            continue
        f = s["fact"]
        if p["kind"] in (A.PLACE_IS_DANGEROUS, A.PLACE_IS_SAFE):
            continue          # the safety answer states a belief over the place, not the fact
        assert p["epistemic"] == s["epistemic_of_fact"], (s["act"], p["epistemic"], f["source"])
        if f["source"] == M.TOLD:
            assert p["epistemic"] in (A.SECOND_HAND, A.HEARSAY), (p, f)
            assert p["source_citizen"] == f["source_citizen"] and p["hops"] >= 1
            assert "I saw" not in s["line"], s["line"]
        else:
            assert p["epistemic"] in FIRST_HAND and p["source_citizen"] is None, (p, f)
        assert p["confidence"] <= round(min(1.0, f["confidence"]), 3) + 1e-6, (p, f)
        seen[p["epistemic"]] += 1
    assert seen[A.DIRECT] or seen[A.EXPERIENCED], seen
    assert seen[A.SECOND_HAND] or seen[A.HEARSAY], f"nobody ever repeated what they were told: {seen}"


def test_nobody_asserted_a_threat_about_a_building_it_held_no_fact_for(day):
    for s in day["spoken"]:
        p = s["proposition"]
        if not p or p["kind"] not in THREAT_PROPS:
            continue
        assert s["threat_facts_here"], (
            f"{s['speaker']} claimed {p['kind']} about building {p['building_id']} "
            f"holding no threat fact for it: {s['line']!r}")
        assert p["event_ref"] in s["threat_facts_here"] or p["kind"] == A.PLACE_IS_DANGEROUS


def test_no_line_leaned_on_a_fact_that_had_decayed_past_recall(day):
    for s in day["spoken"]:
        if s["fact"] is None:
            continue
        assert s["effective"] >= G.RETRIEVAL_FLOOR, (s["act"], s["effective"], s["line"])


def test_retrieval_stays_bounded_on_a_real_store(day):
    r = day["probes"]["retrieval"]
    assert r["n_facts"] > G.TOP_K, r
    assert r["n"] <= G.TOP_K, r


# --------------------------------------------------------------------------- #
# D5 / D6 / D8 / Q1: who knows what, and how they say it
# --------------------------------------------------------------------------- #
def test_a_witness_answers_first_hand(day):
    p = day["probes"]["witness"]
    row = p["row"]
    assert row is not None and row["proposition"], p["answerer"]
    prop = row["proposition"]
    assert prop["kind"] != A.UNKNOWN, row["line"]
    assert prop["epistemic"] in FIRST_HAND, prop
    assert prop["source_citizen"] is None and prop["hops"] == 0
    assert prop["building_id"] == SHOP
    assert row["line"].startswith("I saw") or row["line"].startswith("It happened to me"), row["line"]


def test_a_citizen_who_was_told_answers_second_hand_and_names_its_teller(day):
    p = day["probes"]["told"]
    row = p["row"]
    assert row is not None and row["proposition"], p["answerer"]
    prop = row["proposition"]
    assert prop["kind"] != A.UNKNOWN, row["line"]
    assert prop["epistemic"] in (A.SECOND_HAND, A.HEARSAY), prop
    assert prop["source_citizen"] is not None and prop["hops"] >= 1, prop
    assert prop["origin_witness"] not in (None, p["answerer"]), prop
    assert "I saw" not in row["line"], row["line"]


def test_a_citizen_who_knows_nothing_says_so_and_it_is_logged(day):
    p = day["probes"]["ignorant"]
    row = p["row"]
    assert row is not None
    assert row["proposition"]["kind"] == A.UNKNOWN, row
    assert row["line"] == "I don't know.", row["line"]
    unknown = [e for e in p["events"] if e["event"] == "ANSWER_UNKNOWN"]
    assert unknown and unknown[0]["speaker"] == p["answerer"], p["events"]
    assert unknown[0]["question"] == A.ASK_FACT
    assert unknown[0]["epistemic"] == A.NO_KNOWLEDGE


def test_a_witness_that_has_forgotten_the_attack_no_longer_reports_it(day):
    p = day["probes"]["forgotten"]
    assert p["ids"], "the witness held no threat memory to delete"
    row = p["row"]
    assert row is not None
    assert row["proposition"]["kind"] == A.UNKNOWN, row["line"]
    assert row["line"] in ("I don't know.", "I don't remember it clearly any more."), row["line"]
    before = day["probes"]["witness"]["row"]["proposition"]
    assert before["kind"] != A.UNKNOWN, "the same citizen answered the same question earlier"


# --------------------------------------------------------------------------- #
# D11 / D12 / D13: channels
# --------------------------------------------------------------------------- #
def test_a_face_to_face_warning_needs_co_presence(day):
    """D11/§27: a warning in passing is spoken to somebody within talking
    distance. Cognition's encounter radius (20 m) is wider than the
    dialogue runtime's own TALK_RADIUS_M (6 m), so the alarmed-encounter
    path opens conversations between citizens ``co_present`` rejects."""
    rows = [r for r in day["started"] if r["channel"] == FACE_TO_FACE and r["topic"] != "request"]
    assert rows
    bad = [r for r in rows if not r["co_present"]]
    gaps = sorted(r["gap_m"] for r in bad if r["gap_m"] is not None)
    assert not bad, (f"{len(bad)} of {len(rows)} face-to-face warnings started between citizens "
                     f"the runtime reports as not co-present (outdoor gaps up to "
                     f"{gaps[-1] if gaps else None} m against TALK_RADIUS_M): {bad[:3]}")


def test_a_face_to_face_request_needs_co_presence_too(day):
    """D11/§27: ``co_present`` is the runtime's own definition of who can
    speak face to face — two workers in different rooms of the same shop are
    not co-present, and ``request_help`` must apply the same rule the
    warnings and questions do."""
    rows = [r for r in day["started"] if r["channel"] == FACE_TO_FACE and r["topic"] == "request"]
    assert rows, "the day produced no face-to-face request"
    bad = [r for r in rows if not r["co_present"]]
    assert not bad, (
        f"{len(bad)} of {len(rows)} help requests were spoken face to face between citizens the "
        f"runtime itself reports as not co-present (request_help only checks the building, while "
        f"ask()/_step_plan check the room): {bad[:3]}")


def test_a_shout_stays_inside_one_building(day):
    rows = [r for r in day["started"] if r["channel"] == SHOUT]
    assert rows
    for r in rows:
        a, b = r["inside"], r["other_inside"]
        if a is not None and b is not None and a[0] and b[0]:
            assert a[1] == b[1], r


def test_asking_somebody_far_away_face_to_face_is_refused(day):
    p = day["probes"]["far"]
    assert p["row"] is None, p["pair"]
    refused = [e for e in p["events"] if e["event"] == "TALK_REFUSED"]
    assert refused, p["events"]
    assert refused[0]["reason"].startswith("not_co_present"), refused[0]
    assert refused[0]["speaker"] == p["pair"][0] and refused[0]["listener"] == p["pair"][1]
    assert not [e for e in p["events"] if e["event"] == "SPEECH_ACT"]


def test_calling_a_citizen_with_no_contact_channel_is_refused(day):
    p = day["probes"]["no_tie"]
    assert not day["dialogue"].can_call(*p["pair"])
    assert p["row"] is None, p["pair"]
    refused = [e for e in p["events"] if e["event"] == "TALK_REFUSED"]
    assert refused and refused[0]["reason"] == "no_contact_channel", p["events"]
    assert not [e for e in p["events"] if e["event"] == "SPEECH_ACT"]


def test_a_call_between_npcs_is_a_sequenced_exchange(day):
    calls = [c for c in day["conversations"].values() if c["channel"] == CALL and c["n_acts"] >= 4]
    assert calls, "the day produced no NPC call"
    for conv in calls:
        acts = [r["act"] for r in conv["acts"]]
        assert acts[0] == A.GREET, acts
        assert A.WARN in acts and A.ASK_LOCATION in acts and A.ANSWER in acts
        assert A.THANK in acts and acts[-1] == A.END_CONVERSATION, acts
        seconds = {r["t"] for r in conv["acts"]}
        assert len(seconds) >= 5, f"a six-act call happened in {len(seconds)} seconds: {sorted(seconds)}"
        assert sorted(seconds) == [conv["acts"][0]["t"] + i for i in range(len(conv["acts"]))], seconds
        speakers = [r["speaker"] for r in conv["acts"]]
        assert all(x != y for x, y in zip(speakers, speakers[1:])), speakers
    assert any(A.WARN in [r["act"] for r in c["acts"]] for c in calls)


# --------------------------------------------------------------------------- #
# D15 / D24 / D25: transmission is cognition's, and only through a conversation
# --------------------------------------------------------------------------- #
def test_every_received_fact_is_really_in_the_listeners_store(day):
    assert day["received"], "nothing was ever told to anybody"
    for r in day["received"]:
        row, fact = r["row"], r["fact"]
        assert fact is not None, f"the told fact is not in {row['listener']}'s store: {row}"
        assert fact["owner"] == row["listener"]
        assert fact["fact_id"] == row["fact_id"] and fact["kind"] == row["fact_kind"]
        assert fact["origin_id"] == row["origin_id"] and fact["hops"] == row["hops"]
        assert fact["origin_witness"] == row["origin_witness"] not in (None, row["listener"])
        if row["created"]:
            assert fact["source"] == M.TOLD, row
            assert fact["source_citizen"] == row["speaker"], row
            assert fact["hops"] >= 1, row
        else:
            # a telling that reinforced a fact the listener already held
            assert fact["source"] in (M.TOLD, M.DIRECT, M.PARTICIPANT), row
            assert fact["count"] > 1, row


def test_every_received_fact_matches_a_cognition_warning_with_the_same_lineage(day):
    idx = {}
    for e in day["cog_events"]:
        if e["event"] == "WARNING_RECEIVED":
            idx.setdefault((e["citizen_id"], e["sender"], e["origin_id"], e["hops"]), []).append(e)
    assert day["received"], "nothing was ever told to anybody"
    fresh = [r for r in day["received"] if r["row"]["created"]]
    assert fresh, "no telling ever created a new memory"
    for r in fresh:
        row = r["row"]
        key = (row["listener"], row["speaker"], row["origin_id"], row["hops"])
        assert key in idx, f"a new told fact with no matching WARNING_RECEIVED: {row}"
    mismatched = []
    for r in day["received"]:
        row = r["row"]
        key = (row["listener"], row["speaker"], row["origin_id"], row["hops"])
        if key not in idx:
            mismatched.append(row)
            continue
        w = idx[key][0]
        assert w["fact_id"] == row["fact_id"] and w["channel"] == row["channel"]
    assert not mismatched, (
        f"{len(mismatched)} of {len(day['received'])} FACT_RECEIVED rows carry a lineage no "
        f"WARNING_RECEIVED reports: when the telling reinforces a fact the listener already held, "
        f"dialogue reports the STORED fact's origin_id/hops while cognition reports the ones that "
        f"were actually told, so the two streams disagree about who said what: {mismatched[:2]}")


def test_no_fact_was_received_without_having_been_shared(day):
    shared = Counter((e["speaker"], e["listener"], e["fact_kind"]) for e in _rows(day, "FACT_SHARED"))
    got = Counter((e["speaker"], e["listener"], e["fact_kind"]) for e in _rows(day, "FACT_RECEIVED"))
    assert got and not (got - shared), sorted((got - shared).items())[:5]
    assert len(_rows(day, "FACT_RECEIVED")) == len(_rows(day, "FACT_SHARED"))


def test_a_conversation_that_lost_a_participant_ended_interrupted_and_dropped_its_questions(day):
    interrupted = [c for c in day["conversations"].values() if c["state"] == INTERRUPTED]
    rows = _rows(day, "CONVERSATION_INTERRUPTED")
    assert len(rows) == len(interrupted)
    for conv in interrupted:
        assert conv["end_reason"], conv["conv_id"]
        assert conv["open_questions"] == [] and conv["plan"] == [] and conv["open_requests"] == []
    for conv in day["conversations"].values():
        if conv["state"] == ACTIVE:
            continue
        assert conv["end_reason"], conv["conv_id"]
    # every ended conversation is accounted for by exactly one event
    ends = len(_rows(day, "CONVERSATION_ENDED")) + len(rows)
    assert ends >= len([c for c in day["conversations"].values() if c["state"] != ACTIVE])


# --------------------------------------------------------------------------- #
# D18-D23: requests, refusals and what they leave behind
# --------------------------------------------------------------------------- #
def test_every_request_was_decided_one_way_or_the_other(day):
    made = _rows(day, "REQUEST_MADE")
    assert made
    decided = {e["request_id"] for e in _rows(day, "REQUEST_ACCEPTED")} | \
              {e["request_id"] for e in _rows(day, "REQUEST_REFUSED")} | \
              {e["request_id"] for e in _rows(day, "REQUEST_FAILED")} | \
              {e["request_id"] for e in _rows(day, "REQUEST_CANCELLED")}
    assert {e["request_id"] for e in made} <= decided
    for e in _rows(day, "REQUEST_REFUSED"):
        assert e["reason"] in (A.R_TOO_DANGEROUS, A.R_BUSY, A.R_NO_CAPABILITY, A.R_LOW_TRUST,
                               A.R_URGENT_TASK, A.R_UNAVAILABLE, A.R_SHIFT, A.R_COST), e
        assert e["score"] < HELP_THRESHOLD or e["reason"] in (A.R_UNAVAILABLE, A.R_NO_CAPABILITY,
                                                              A.R_URGENT_TASK, A.R_TOO_DANGEROUS), e
    for rid, req in day["requests"].items():
        assert req["state"] != A.REQ_PENDING, req
        assert req["decided_s"] >= req["created_s"] or req["state"] == A.REQ_CANCELLED, req


def test_an_accepted_request_became_a_real_help_task_that_completed(day):
    accepted = _rows(day, "REQUEST_ACCEPTED")
    completed = _rows(day, "REQUEST_COMPLETED")
    assert accepted and completed
    tasks = [e for e in day["work_events"] if e["event"] == "HELP_TASK"]
    assert tasks
    for e in accepted:
        req = day["requests"][e["request_id"]]
        mine = [t for t in tasks if t["citizen_id"] == req["accepter"]
                and t["beneficiary"] == req["requester"] and t["object_id"] == e["object_id"]]
        assert mine, f"an accepted request with no HELP_TASK: {e}"
        assert mine[0]["task_id"] == e["task_id"]
    for e in completed:
        req = day["requests"][e["request_id"]]
        assert req["state"] == A.REQ_COMPLETED and req["completed_s"] > req["created_s"]
        done = [t for t in day["work_events"] if t["event"] == "HELP_DONE"
                and t["citizen_id"] == req["accepter"]]
        assert done, f"REQUEST_COMPLETED with no HELP_DONE: {e}"


def test_a_refused_request_creates_no_help_task_for_that_pair(day):
    refused = _rows(day, "REQUEST_REFUSED")
    assert refused
    for e in refused:
        req = day["requests"][e["request_id"]]
        window = [t for t in day["work_events"]
                  if t["event"] == "HELP_TASK" and t["citizen_id"] == req["accepter"]
                  and t["beneficiary"] == req["requester"]
                  and req["decided_s"] <= t["t"] <= req["decided_s"] + 600.0]
        assert not window, f"a refusal that helped anyway: {e} -> {window}"


def test_a_refusal_is_remembered_and_costs_the_refuser_affinity(day):
    c = day["cog"]
    refused = _rows(day, "REQUEST_REFUSED")
    assert refused
    for e in refused:
        req = day["requests"][e["request_id"]]
        st = c.memories.get(req["requester"])
        facts = [f for f in st.facts.values() if f.kind == M.REFUSED_BY and f.actor == req["accepter"]]
        assert facts, f"{req['requester']} does not remember being refused by {req['accepter']}"
        reasons = {x["reason"] for x in refused
                   if day["requests"][x["request_id"]]["requester"] == req["requester"]
                   and day["requests"][x["request_id"]]["accepter"] == req["accepter"]}
        f = facts[0]
        assert f.source == M.PARTICIPANT and f.detail in reasons, (f.detail, reasons)
        before = day["rel_at"][("REQUEST_REFUSED", req["request_id"])]
        after = c.rels.get(req["requester"], req["accepter"])
        assert after is not None
        if before is not None and before["affinity"] > 0.0:
            assert after.affinity < before["affinity"], (before, after.to_dict())
            assert after.trust <= before["trust"] + 1e-9


def test_the_same_request_from_a_trusted_coworker_would_have_been_accepted(day):
    """D22 / Q3: the refusal was a threshold decision on the relationship,
    not a property of the task."""
    c = day["cog"]
    refused = [e for e in _rows(day, "REQUEST_REFUSED") if e["reason"] == A.R_LOW_TRUST]
    assert refused, "the day produced no low-trust refusal"
    crossed = 0
    for e in refused:
        req = day["requests"][e["request_id"]]
        problem = {"kind": req["problem"], "object_id": req["object_id"]}
        base = e["score"]              # the score the decision was actually taken on
        assert base < HELP_THRESHOLD, e
        warm = Relationship(req["accepter"], req["requester"], familiarity=0.9, trust=0.9,
                            affinity=0.9, obligation=0.9)
        score, comps = c.help_score(req["accepter"], req["requester"], problem, rel_override=warm)
        assert score > base, (score, base)
        crossed += int(score >= HELP_THRESHOLD)
    assert crossed == len(refused), f"only {crossed}/{len(refused)} refusals were relationship-bound"


def test_a_completed_request_leaves_obligation_and_affinity_behind(day):
    c = day["cog"]
    completed = _rows(day, "REQUEST_COMPLETED")
    assert completed
    for e in completed:
        req = day["requests"][e["request_id"]]
        rel = c.rels.get(req["requester"], req["accepter"])
        assert rel is not None
        assert rel.obligation > 0.0, (req["request_id"], rel.to_dict())
        before = day["rel_at"][("REQUEST_MADE", req["request_id"])]
        if before is not None:
            assert rel.affinity > before["affinity"], (before, rel.to_dict())
            assert rel.trust >= before["trust"]
        st = c.memories.get(req["requester"])
        assert any(f.kind == M.HELPED_BY and f.actor == req["accepter"] for f in st.facts.values()), \
            f"{req['requester']} does not remember being helped by {req['accepter']}"


def test_the_help_that_completed_changed_the_object_it_was_asked_about(day):
    w = day["world"]
    completed = [e for e in _rows(day, "REQUEST_COMPLETED") if e.get("object_id")]
    assert completed
    for e in completed:
        reg = w.work.registry(day["requests"][e["request_id"]]["building_id"])
        obj = reg.get(e["object_id"])
        assert obj is not None, e
        done = [t for t in day["work_events"] if t["event"] == "HELP_DONE"
                and t.get("object_id") == e["object_id"]]
        assert done, e
        assert done[0]["effect"], f"a help task that changed nothing: {done[0]}"
        changed = [t for t in day["work_events"] if t["event"] == "STATE_CHANGE"
                   and t.get("object_id") == e["object_id"] and t["t"] >= done[0]["t"] - 1.0]
        assert changed or done[0]["effect"], (done[0], e)

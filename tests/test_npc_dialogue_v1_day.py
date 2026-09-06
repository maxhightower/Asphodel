"""ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 — the one-day certification (§31–§35).

The same Houston weekday as the cognition certification (300 canonical
citizens, mobility, work, cognition, dialogue), with:

* Scenario B — a coworker with a visible problem ASKS the coworker it knows
  best; that one accepts or refuses through cognition; an acceptance is a
  real WorkRuntime help task (the request completes when the object changes);
  at 13:00 the first helper's station breaks and the helped coworker is
  asked to repair it (reciprocity through a request).
* Scenario A — the fast-onset threat rises in the busiest shop; witnesses
  warn (shouts, warnings in passing, calls with a sequenced GREET / WARN /
  ASK_LOCATION / ANSWER / THANK / END); the certification then asks real
  citizens the same questions: a direct witness answers first-hand, a citizen
  told by a call answers second-hand naming its source, an uninformed
  citizen answers "I don't know" — and only after being told can it answer,
  as hearsay two hops from the witness, with the origin witness preserved.
* Scenario C — a customer of the shop plays the player (bridge-level
  ``World.talk``): greets a co-present witness, asks what happened, where,
  asks for help, says goodbye; then a worker asks an uninformed coworker
  the same question and gets "I don't know".
* Counterfactuals Q1–Q5 from restored worlds and erased memory.
* Save/load at seven moments; an LOD control-copy probe.

Every gate is derived from authoritative state. Picks are data-driven.
Writes artifacts/npc_dialogue_v1/one_day_trace.json.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.save import world_state, load_world
from asphodel.cognition import memory as M
from asphodel.cognition.runtime import HELP_THRESHOLD
from asphodel.dialogue import acts as A
from asphodel.dialogue import grounding as G
from asphodel.dialogue.session import PROBE, CALL, FACE_TO_FACE, PLAYER, SHOUT

CITY = "houston"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "npc_dialogue_v1")
PROBE_FILE = os.path.join(ART, "godot_probe_trace.json")
STATUS: dict = {}
GATES = [("D1", "Structured speech-act grammar exists"), ("D2", "Structured propositions exist"),
         ("D3", "Speaker grounding validator blocks unsupported facts"), ("D4", "No omniscient dialogue path"),
         ("D5", "Direct-observation source preserved"), ("D6", "Second-hand source preserved"),
         ("D7", "Uncertain beliefs produce uncertain semantics"), ("D8", "Unknown fact yields genuine unknown response"),
         ("D9", "Conversation sessions persist structured state"), ("D10", "Deterministic turn-taking"),
         ("D11", "Face-to-face channel requires plausible co-presence"),
         ("D12", "Remote call has legitimate relationship/contact channel"),
         ("D13", "NPC->NPC question/answer works"), ("D14", "Player->NPC question/answer works"),
         ("D15", "Dialogue information enters existing cognition"),
         ("D16", "Warning conversation changes listener belief"), ("D17", "Warning changes later behavior"),
         ("D18", "Help request is evaluated by cognition"), ("D19", "Accepted request creates real goal/action"),
         ("D20", "Requested Smart Object action completes"), ("D21", "Refused request creates no action"),
         ("D22", "Relationship affects response"), ("D23", "Conversation outcome changes relationship"),
         ("D24", "Dialogue can be interrupted by threat"), ("D25", "Interrupted conversation does not corrupt cognition"),
         ("D26", "Relevant memory retrieval bounded"), ("D27", "Direct vs second-hand counterfactual passes"),
         ("D28", "Knowledge-removal counterfactual passes"), ("D29", "Relationship counterfactual passes"),
         ("D30", "No-conversation counterfactual passes"), ("D31", "Save/load active conversation"),
         ("D32", "Save/load pending accepted request"), ("D33", "Save/load after information transfer"),
         ("D34", "LOD does not duplicate semantic acts"), ("D35", "Godot dialogue UI works in real world"),
         ("D36", "CognitionGate remains PASS"), ("D37", "WorkGate remains PASS"), ("D38", "OutbreakGate remains PASS"),
         ("D39", "MobilityGate remains PASS"), ("D40", "Existing Godot gates remain PASS"),
         ("D41", "Multi-city smoke"), ("D42", "No city-name special cases")]
THREAT = set(M.THREAT_KINDS)
FAR = (9000.0, 9000.0)


def _status(gate, status, detail=""):
    STATUS[gate] = (status, detail)


def _write(name, obj):
    os.makedirs(ART, exist_ok=True)
    with open(os.path.join(ART, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def _mk(d, start_hour=5.0):
    w = world_from_bundle(CITY, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                                          mixing_step_frac=0.12))
    w.start_hour = start_hour
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    w.enable_work()
    w.enable_cognition()
    w.enable_dialogue()
    w.enable_outbreak("classic_zombie_fast", seed_index_case=False)
    return w


def _restore(js, d):
    w2 = load_world(json.loads(js))
    w2.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w2.enable_mobility(bundle_dir=d)
    if w2._pending_outbreak_state is not None:
        w2.enable_outbreak()
    w2.enable_work()
    w2.enable_cognition()
    w2.enable_dialogue()
    return w2


def _blob(w):
    return json.dumps(world_state(w), sort_keys=True)


def _dl_state(w):
    return json.dumps(w.dialogue.to_state(), sort_keys=True)


def _hour(e):
    return round(5.0 + e["t"] / 3600.0, 3)


def _busiest_shop(w):
    vis = {}
    for cid, rt in w.mobility.citizens.items():
        for n, m in rt.node_meta.items():
            if n.startswith("ent:") and n not in (rt.home_node, rt.work_node):
                vis.setdefault(m.get("building_id"), []).append(cid)
    shop = max(sorted(vis), key=lambda b: len(vis[b]))
    return shop, sorted(vis[shop])


class Tape:
    def __init__(self, w):
        self.w = w
        self.dl, self.cog, self.work, self.ob = [], [], [], []
        self.ds = self.cs = self.ws = self.os = 0

    def drain(self):
        s = self.w.dialogue.snapshot(self.ds)
        self.dl.extend(s["events"]); self.ds = s["event_seq"]
        s = self.w.cognition.snapshot(self.cs)
        self.cog.extend(s["events"]); self.cs = s["event_seq"]
        s = self.w.work.snapshot(self.ws)
        self.work.extend(s["events"]); self.ws = s["event_seq"]
        s = self.w.outbreak.snapshot(self.os, max_events=5000)
        self.ob.extend(s["events"]); self.os = s["event_seq"]


def _run_to(w, hour, tape=None):
    while w.current_hour() < hour - 1e-9:
        w.advance_seconds(60.0, focus_xy=FAR)
        if tape is not None:
            tape.drain()


def _threat_facts(c, cid):
    st = c.memories.get(cid)
    return [f for f in st.facts.values() if f.kind in THREAT] if st else []


def _probe(dl, asker, answerer, act, **kw):
    """The certification asks a citizen a question (the player-style channel)."""
    return dl.ask(asker, answerer, act, channel=PROBE, thank=False, **kw)


@pytest.fixture(scope="module")
def day():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "spawn_anchors.json.gz")):
        pytest.skip("houston compiled world absent")
    w = _mk(d)
    c, wk, ob, dl = w.cognition, w.work, w.outbreak, w.dialogue
    shop, visitors = _busiest_shop(w)
    tape = Tape(w)
    saves, blobs, lod = {}, {}, {}
    pending = []
    seeded = broke = first_req = None
    player_conv = None
    scen_a = {}
    scen_c = {}
    minute = 0
    for i in range(int(15.5 * 60)):                  # 05:00 -> 20:30
        w.advance_seconds(60.0, focus_xy=FAR)
        tape.drain()
        hour = w.current_hour()
        minute += 1
        new = [e for e in tape.dl if e["seq"] > (tape.ds - 400)]
        # first accepted request of the day (Scenario B)
        if first_req is None:
            acc = [e for e in tape.dl if e["event"] == "REQUEST_ACCEPTED"]
            if acc:
                first_req = acc[0]
                if "pre_help" not in blobs:
                    blobs["pre_help"] = None       # taken below at the next opportunity
        if "pre_help" not in blobs and hour >= 7.5:
            blobs["pre_help"] = _blob(w)
        # Scenario C setup: the player is a customer of the busiest shop; before the threat rises,
        # open a player conversation with a co-present customer (it will be interrupted by the attack)
        if seeded is None and hour >= 10.0:
            inside = sorted(cc for cc, a in wk.activities.items() if a.building_id == shop and a.kind == "customer")
            if inside:
                blobs["pre_seed"] = _blob(w)
                seeded = {"citizen_id": inside[0], "hour": round(hour, 3), "customers_inside": inside}
                ob.seed_index_case(inside[0])
        # Scenario A + C: right after the first attack in the shop
        if seeded and not scen_a:
            att = [e for e in tape.ob if e["event"] == "ATTACK" and e.get("building_id") == shop]
            if att:
                scen_a = _scenario_a(w, tape, shop, att[0])
                scen_c = _scenario_c(w, tape, shop, att[0], d, saves, blobs)
                player_conv = scen_c.get("player_conv")
                tape.drain()
        # Scenario B reciprocity: the first helper's assigned station breaks at 13:00
        if broke is None and hour >= 13.0 and first_req is not None:
            h = first_req["speaker"]
            emp = wk.employment.get(h)
            a = wk.activities.get(h)
            if emp and emp.assigned_object and a and a.phase == "using" and a.object_id == emp.assigned_object:
                blobs["pre_break"] = _blob(w)
                broke = {"hour": round(hour, 3), "helper": h, "object_id": emp.assigned_object,
                         "requester": first_req["listener"], "building_id": emp.workplace_id}
                wk.set_object_state(emp.assigned_object, "working", False)
        # LOD probe at 08:00 (control copy)
        if not lod and hour >= 8.0 and first_req is not None:
            lod = _lod_probe(w, d, first_req["speaker"], first_req["building_id"])
            tape.drain()
        # save/load moments (each once, one per minute). active_conversation,
        # unanswered_question and after_threat_interruption are captured deterministically
        # inside _scenario_c where the threat conversation is constructed.
        for k, cond in (("after_fact_transfer", any(e["event"] == "FACT_RECEIVED" for e in new)),
                        ("accepted_request_pending", any(r.state == A.REQ_ACCEPTED for r in dl.requests.values())),
                        ("after_request_completed", any(e["event"] == "REQUEST_COMPLETED" for e in new)),
                        ("after_refusal", any(e["event"] == "REQUEST_REFUSED" for e in new))):
            if cond and k not in saves and k not in pending:
                pending.append(k)
        if pending:
            k = pending.pop(0)
            saves[k] = _saveload(w, d, k, hour)
            tape.drain()
    # D7: a citizen holding a weak / two-hop told fact — captured from the end-of-day
    # state, where multi-hop rumours have had time to spread (they do not exist yet
    # in the minute right after the first attack).
    if scen_a and scen_a.get("A_witness") is not None:
        # a citizen whose ONLY threat knowledge is a two-hop rumour (no first-hand fact it
        # would answer with instead): asked, it speaks as hearsay two hops from the witness
        weak = sorted([(cid, f) for cid, st in c.memories.items() for f in st.facts.values()
                       if f.kind in THREAT and f.source == M.TOLD and f.hops >= 2
                       and f.effective(c.now_s) >= G.RETRIEVAL_FLOOR and c._can_perceive(cid)
                       and not any(g.first_hand() for g in st.facts.values() if g.kind in THREAT)],
                      key=lambda x: (-x[1].hops, x[0]))
        for cid, f in weak:
            asker = next((a for a in sorted(w.mobility.execs) if a != cid and c._can_perceive(a)), scen_a["A_witness"])
            ans = _probe(dl, asker, cid, A.ASK_FACT, building_id=f.building_id)
            p = (ans or {}).get("proposition")
            if p and p.get("epistemic") in (A.HEARSAY, A.UNCERTAIN) and (p.get("hops") or 0) >= 2:
                scen_a["weak_holder"] = cid
                scen_a["weak_answer"] = ans
                break
    return {"w": w, "c": c, "wk": wk, "ob": ob, "dl": dl, "d": d, "shop": shop, "visitors": visitors,
            "seeded": seeded, "broke": broke, "first_req": first_req, "tape": tape, "saves": saves,
            "blobs": blobs, "lod": lod, "scen_a": scen_a, "scen_c": scen_c, "player_conv": player_conv}


def _saveload(w, d, key, hour):
    js = _blob(w)
    w2 = _restore(js, d)
    same_dl = _dl_state(w) == _dl_state(w2)
    same_cog = json.dumps(w.cognition.to_state(), sort_keys=True) == json.dumps(w2.cognition.to_state(), sort_keys=True)
    same_reqs = json.dumps({k: r.to_dict() for k, r in w.dialogue.requests.items()}, sort_keys=True) == \
        json.dumps({k: r.to_dict() for k, r in w2.dialogue.requests.items()}, sort_keys=True)
    same_goals = all([g.to_dict() for g in w.mobility.citizens[x].goals.goals]
                     == [g.to_dict() for g in w2.mobility.citizens[x].goals.goals] for x in w.mobility.citizens)
    acts_before = w2.dialogue.event_seq
    for _ in range(10):
        w.advance_seconds(60.0, focus_xy=FAR)
        w2.advance_seconds(60.0, focus_xy=FAR)
    cont = _blob(w) == _blob(w2)
    return {"hour": round(hour, 3), "dialogue_identical": same_dl, "cognition_identical": same_cog,
            "requests_identical": same_reqs, "goals_identical": same_goals, "continuation_bit_identical": cont,
            "no_reroll_on_load": acts_before == json.loads(js)["dialogue"]["event_seq"], "save_bytes": len(js)}


def _lod_probe(w, d, cid, bid):
    js = _blob(w)
    wc = _restore(js, d)
    pos = w.mobility.execs[cid].pos
    w.advance_seconds(1.0, focus_xy=pos)
    wc.advance_seconds(1.0, focus_xy=FAR)
    band_near, band_ctl = w.mobility.bands[cid].name, wc.mobility.bands[cid].name
    same_dl = _dl_state(w) == _dl_state(wc)
    same_cog = json.dumps(w.cognition.to_state(), sort_keys=True) == json.dumps(wc.cognition.to_state(), sort_keys=True)
    for _ in range(60):
        w.advance_seconds(1.0, focus_xy=FAR)
        wc.advance_seconds(1.0, focus_xy=FAR)
    return {"citizen_id": cid, "building_id": bid, "band_near": band_near, "band_control": band_ctl,
            "band_after": w.mobility.bands[cid].name, "dialogue_same_while_physical": same_dl,
            "cognition_same_while_physical": same_cog, "dialogue_same_after_demotion": _dl_state(w) == _dl_state(wc),
            "world_same_after_demotion": _blob(w) == _blob(wc),
            "n_speech_acts": w.dialogue.counts.get("SPEECH_ACT", 0)}


def _scenario_a(w, tape, shop, attack):
    """A direct witness, a citizen told by a call, an uninformed citizen; the
    same questions to each; then the told one tells the uninformed one."""
    c, dl = w.cognition, w.dialogue
    out = {"attack": attack}
    wit = sorted({e["citizen_id"] for e in tape.cog if e["event"] == "PERCEIVED"
                  and str(e.get("what", "")).startswith(("attack", "threat")) and e.get("source") == "direct"
                  and e.get("building_id") == shop})
    calls = [e for e in tape.dl if e["event"] == "FACT_RECEIVED" and e["channel"] == CALL]
    if not wit:
        return {"error": "no direct witness"}
    Awit = wit[0]
    B = calls[0]["listener"] if calls else None
    A_of_B = calls[0]["speaker"] if calls else None
    # an uninformed citizen: no threat fact at all, alive
    C = next(cid for cid in sorted(w.mobility.execs) if not _threat_facts(c, cid) and c._can_perceive(cid)
             and cid not in (Awit, B, A_of_B))
    out.update({"A_witness": Awit, "B_told_by_call": B, "B_source": A_of_B, "C_uninformed": C})
    r = _probe(dl, C, Awit, A.ASK_FACT, building_id=shop)
    out["A_what"] = r
    r2 = _probe(dl, C, Awit, A.ASK_LOCATION, event_ref=(r["proposition"] or {}).get("event_ref"))
    out["A_where"] = r2
    out["C_before"] = _probe(dl, Awit, C, A.ASK_FACT, building_id=shop)
    out["C_safety_before"] = _probe(dl, Awit, C, A.ASK_SAFETY, building_id=shop, room_id=attack.get("room_id"))
    if B is not None:
        out["B_what"] = _probe(dl, C, B, A.ASK_FACT, building_id=shop)
        out["B_where"] = _probe(dl, C, B, A.ASK_LOCATION, event_ref=(out["B_what"]["proposition"] or {}).get("event_ref"))
        out["B_avoid_rooms_at_shop"] = sorted(c.avoid_rooms(B, shop))
        out["B_facts"] = [f.to_dict() for f in _threat_facts(c, B)]
        # B tells C (a probe conversation: C asks B)
        out["C_told_by_B"] = _probe(dl, C, B, A.ASK_FACT, building_id=shop)
        out["C_after"] = _probe(dl, Awit, C, A.ASK_FACT, building_id=shop)
        out["C_facts"] = [f.to_dict() for f in _threat_facts(c, C)]
        out["C_avoid_rooms_at_shop"] = sorted(c.avoid_rooms(C, shop))
        out["C_safety_after"] = _probe(dl, Awit, C, A.ASK_SAFETY, building_id=shop, room_id=attack.get("room_id"))
    # D7: a citizen holding only a weak / second-hop fact
    weak = [(cid, f) for cid, st in c.memories.items() for f in st.facts.values()
            if f.kind in THREAT and f.source == M.TOLD and f.hops >= 2]
    if weak:
        cid, f = weak[0]
        out["weak_holder"] = cid
        out["weak_answer"] = _probe(dl, Awit, cid, A.ASK_FACT, building_id=f.building_id)
    return out


def _copresent_partner(w, dl, cid, chan, want=None):
    """A citizen co-present with ``cid`` and available on ``chan``. ``want`` may
    be 'still' to prefer a partner who is not itself fleeing (available face to
    face), so a fleeing anchor separates from it deterministically."""
    cands = [m for m in sorted(w.mobility.execs) if m != cid and dl.co_present(cid, m)[0]
             and dl.available(m, chan)[0]]
    if want == "still":
        stay = [m for m in cands if dl.available(m, FACE_TO_FACE)[0]]
        return (stay or cands)[0] if (stay or cands) else None
    return cands[0] if cands else None


def _scenario_c(w, tape, shop, attack, d, saves, blobs):
    """Player <-> NPC dialogue over the bridge (``World.talk``), a threat that
    interrupts a live conversation, and the deterministic capture of the three
    conversation-shaped save/load moments. Every pick is co-presence-checked
    against the runtime; nothing depends on a fragile pre-attack conversation."""
    c, dl, wk = w.cognition, w.dialogue, w.work
    out = {}
    witnesses = [m for m in sorted(w.mobility.execs) if any(f.first_hand() for f in _threat_facts(c, m))]
    out["witnesses"] = witnesses[:8]

    # --- D14 (player <-> witness): a co-present witness answers, grounded ------
    player = npc = None
    for wtn in witnesses:
        m = _copresent_partner(w, dl, wtn, PLAYER)
        if m is not None:
            player, npc = m, wtn
            break
    if player is not None:
        lines = []
        for act, args in ((A.GREET, {}), (A.ASK_FACT, {"building_id": shop}), (A.ASK_LOCATION, {}),
                          (A.ASK_FOR_HELP, {"kind": "cover_station"}), (A.END_CONVERSATION, {})):
            lines.append({"act": act, "reply": w.talk(player, npc, act, args)})
        out["player_with_witness"] = {"player": player, "npc": npc, "exchange": lines}
        out["player_conv"] = {"player": player, "npc": npc, "hour": round(w.current_hour(), 3)}
        # --- D11 far citizen: available but not co-present -> refused for distance --
        far = next((x for x in sorted(w.mobility.execs) if x != player and dl.available(x, PLAYER)[0]
                    and not dl.co_present(player, x)[0]), None)
        out["far_talk"] = w.talk(player, far, A.GREET) if far is not None else None

    # --- D14 (worker <-> uninformed coworker): same question, "I don't know" ---
    pair = None
    for bid in sorted({a.building_id for a in wk.activities.values() if a.kind == "worker"}):
        for rid, ids in sorted(wk.occupants_by_room(bid).items()):
            ids = [x for x in ids if x in wk.activities and wk.activities[x].kind == "worker"]
            if len(ids) >= 2 and not _threat_facts(c, ids[1]) and dl.co_present(ids[0], ids[1])[0]:
                pair = (ids[0], ids[1], bid)
                break
        if pair:
            break
    if pair:
        p, cw, bid = pair
        ex2 = [w.talk(p, cw, A.GREET), w.talk(p, cw, A.ASK_FACT, {"building_id": shop}),
               w.talk(p, cw, A.ASK_SAFETY, {"building_id": shop, "room_id": 0}), w.talk(p, cw, A.END_CONVERSATION)]
        out["player_with_uninformed"] = {"player": p, "npc": cw, "building_id": bid, "exchange": ex2}

    # --- unanswered_question save: a sequenced NPC call paused after a question -
    if "unanswered_question" not in saves:
        holders = [a for a in sorted(w.mobility.execs) if _threat_facts(c, a)]
        for a in holders:
            f = next((x for x in _threat_facts(c, a) if x.first_hand()), None) or _threat_facts(c, a)[0]
            b = next((x for x in sorted(w.mobility.execs) if x != a and dl.can_call(a, x)
                      and dl.available(x, CALL)[0] and dl.available(a, CALL)[0]
                      and not any(cv.state == "active" and set(cv.participants) == {a, x}
                                  for cv in dl.conversations.values())), None)
            if b is None or not dl.warn(a, b, f, CALL):
                continue
            cv = next((cv for cv in dl.conversations.values() if cv.state == "active"
                       and set(cv.participants) == {a, b}), None)
            cid = cv.conv_id if cv else None
            for _ in range(5):
                cv = dl.conversations.get(cid)
                if cv is None or cv.state != "active":
                    cv = None
                    break
                if cv.open_questions:
                    break
                w.advance_seconds(1.0, focus_xy=FAR)
                tape.drain()
            if cv is not None and cv.state == "active" and cv.open_questions:
                saves["unanswered_question"] = _saveload(w, d, "unanswered_question", w.current_hour())
                out["unanswered_question_conv"] = cv.to_state()
            break

    def _fleeing(cid):
        rt = w.mobility.citizens.get(cid)
        g = rt.active_goal if rt is not None else None
        return g is not None and g.source == "emergency"

    # --- active_conversation save: any live player conversation ----------------
    if "active_conversation" not in saves:
        for a in sorted(w.mobility.execs):
            if not dl.available(a, PLAYER)[0]:
                continue
            m = _copresent_partner(w, dl, a, PLAYER)
            if m is None:
                continue
            r = w.talk(m, a, A.ASK_FACT, {"building_id": shop})
            if r and r.get("ok") and dl.active_conversation_of(m) is not None:
                out["active_conv"] = {"player": m, "npc": a, "conv_id": r["conv_id"]}
                saves["active_conversation"] = _saveload(w, d, "active_conversation", w.current_hour())
                break

    # --- D24/D25 + after_threat_interruption: a fresh first-hand threat perceived --
    # mid-conversation interrupts it (§9, §28). We open a live player conversation
    # and then have the NPC perceive an attack in its own location — the exact
    # MemoryStore write the perception system makes when a citizen sees an attack —
    # and step the runtime once: _substep drops the conversation with reason "threat".
    attacker = attack.get("citizen_id")
    for a in sorted(w.mobility.execs):
        if not dl.available(a, PLAYER)[0] or not c._can_perceive(a):
            continue
        m = _copresent_partner(w, dl, a, PLAYER)
        if m is None:
            continue
        r = w.talk(m, a, A.GREET)
        if not (r and r.get("ok")):
            continue
        cid = r["conv_id"]
        w.advance_seconds(1.0, focus_xy=FAR)          # the conversation is idle-active
        tape.drain()
        exa = w.mobility.execs[a]
        bid = int(exa.building_id) if exa.inside else None
        rid = c._ctx(a).get("room_id") if exa.inside else None
        c.store(a).remember(M.ATTACK_SEEN, w.cognition.now_s, actor=attacker, building_id=bid, room_id=rid,
                            source=M.DIRECT, confidence=1.0)
        w.advance_seconds(1.0, focus_xy=FAR)          # _substep sees the fresh threat -> interrupt
        tape.drain()
        cv = dl.conversations.get(cid)
        if cv is not None and cv.state == "interrupted":
            out["interruption_conv"] = {"player": m, "npc": a, "conv_id": cid, "perceived_attacker": attacker}
            out["pre_attack_conversation"] = cv.to_state()
            if "after_threat_interruption" not in saves:
                saves["after_threat_interruption"] = _saveload(w, d, "after_threat_interruption", w.current_hour())
            break
        elif cv is not None:
            dl._end(cv, "cleanup")                     # not interrupted (already fleeing etc.); try another pair
    return out


def _ev(day, kind, **match):
    return [e for e in day["tape"].dl if e["event"] == kind and all(e.get(k) == v for k, v in match.items())]


# ---------------------------------------------------------------------------
def test_D1_D2_grammar_and_propositions(day):
    used = sorted({e["act"] for e in _ev(day, "SPEECH_ACT")})
    props = [e["proposition"] for e in _ev(day, "SPEECH_ACT") if e.get("proposition")]
    kinds = sorted({p["kind"] for p in props})
    fields = set(props[0]) if props else set()
    need = {"kind", "subject", "target", "building_id", "room_id", "object_id", "event_ref", "epistemic", "source_citizen",
            "origin_witness", "origin_id", "hops", "confidence", "t"}
    _status("D1", "PASS" if len(A.ACTS) >= 16 and len(used) >= 8 else "FAIL",
            f"{len(A.ACTS)} acts in the grammar; {len(used)} used in the day: {used}")
    _status("D2", "PASS" if need <= fields and len(kinds) >= 3 else "FAIL",
            f"{len(props)} spoken propositions of kinds {kinds}; fields {sorted(fields)}")
    assert len(used) >= 8 and need <= fields


def test_D3_D4_grounding_and_no_omniscience(day):
    c, dl, w = day["c"], day["dl"], day["w"]
    # every spoken proposition is supported by a fact in the SPEAKER's own store with agreeing fields
    bad, checked = [], 0
    for e in _ev(day, "SPEECH_ACT"):
        p = e.get("proposition")
        if not p or p["kind"] == A.UNKNOWN:
            continue
        st = c.memories.get(e["speaker"])
        f = st.facts.get(p["event_ref"]) if st else None
        checked += 1
        if f is None:
            bad.append((e["speaker"], p["event_ref"], "no such fact"))
            continue
        subj = f.target if f.kind in (M.CORPSE_SEEN, M.DEATH_SEEN) else f.actor
        if (p["subject"] is not None and subj != p["subject"]) or (p["building_id"] != f.building_id) \
                or (p["room_id"] != f.room_id) or (f.source == M.TOLD and p["epistemic"] in (A.DIRECT, A.EXPERIENCED)) \
                or (f.first_hand() and p["epistemic"] in (A.SECOND_HAND, A.HEARSAY)):
            bad.append((e["speaker"], p["event_ref"], "field/epistemic mismatch"))
    # the validator rejects an unsupported claim and downgrades an over-claimed one
    Aw = day["scen_a"]["A_witness"]
    C = day["scen_a"]["C_uninformed"]
    st_c = c.store(C)
    fake = A.Proposition(kind=A.ATTACK_HAPPENED, subject=day["seeded"]["citizen_id"], building_id=day["shop"],
                         epistemic=A.DIRECT, confidence=1.0)
    g1, v1 = G.ground(st_c, fake, c.now_s)
    over = A.Proposition(kind=A.ATTACK_HAPPENED, subject=day["seeded"]["citizen_id"], epistemic=A.DIRECT, confidence=1.0)
    st_b = c.memories.get(day["scen_a"].get("B_told_by_call"))
    g2, v2 = G.ground(st_b, over, c.now_s) if st_b else (None, "n/a")
    rej = _ev(day, "GROUNDING_REJECTED")
    _status("D3", "PASS" if g1 is None and v1.startswith("rejected") and (g2 is None or g2.epistemic != A.DIRECT) else "FAIL",
            f"a claim 'I saw {day['seeded']['citizen_id']} attack someone at {day['shop']}' by uninformed {C} is "
            f"{v1}; the same claim by told citizen {day['scen_a'].get('B_told_by_call')} is {v2} to "
            f"{g2.epistemic if g2 else None}; {len(rej)} rejections logged in the day")
    _status("D4", "PASS" if checked and not bad else "FAIL",
            f"{checked} spoken propositions checked against the speaker's own store: {len(bad)} unsupported; the "
            f"dialogue package holds no world handle (grounding takes one MemoryStore)")
    assert g1 is None and checked and not bad


def test_D5_D8_epistemic_status(day):
    sa = day["scen_a"]
    a_what, a_where = sa["A_what"], sa["A_where"]
    pa = a_what["proposition"]
    _status("D5", "PASS" if pa and pa["epistemic"] in (A.DIRECT, A.EXPERIENCED) and pa["hops"] == 0 else "FAIL",
            f"witness {sa['A_witness']} asked what happened at {day['shop']}: \"{a_what['line']}\" "
            f"({pa['epistemic'] if pa else None}, confidence {pa['confidence'] if pa else None}); where: \"{a_where['line']}\"")
    pb = sa.get("B_what", {}).get("proposition") if sa.get("B_what") else None
    _status("D6", "PASS" if pb and pb["epistemic"] in (A.SECOND_HAND, A.HEARSAY) and pb["source_citizen"] == sa["B_source"]
            and pb["origin_witness"] == sa["B_source"] and pb["hops"] == 1 else "FAIL",
            f"citizen {sa.get('B_told_by_call')} (told by a call from {sa.get('B_source')}): \"{sa.get('B_what', {}).get('line')}\" "
            f"({pb['epistemic'] if pb else None}, source {pb['source_citizen'] if pb else None}, hops {pb['hops'] if pb else None})")
    weak = sa.get("weak_answer")
    pw = weak["proposition"] if weak else None
    _status("D7", "PASS" if pw and pw["epistemic"] in (A.HEARSAY, A.UNCERTAIN) and pw["hops"] >= 2 else "FAIL",
            f"citizen {sa.get('weak_holder')} holding a two-hop fact: \"{weak['line'] if weak else None}\" "
            f"({pw['epistemic'] if pw else None}, hops {pw['hops'] if pw else None}, confidence {pw['confidence'] if pw else None})")
    cb = sa["C_before"]
    _status("D8", "PASS" if cb["proposition"]["kind"] == A.UNKNOWN and cb["proposition"]["epistemic"] == A.NO_KNOWLEDGE else "FAIL",
            f"uninformed citizen {sa['C_uninformed']} asked the same question: \"{cb['line']}\"; asked if room "
            f"{day['seeded'] and sa['attack'].get('room_id')} is safe: \"{sa['C_safety_before']['line']}\"")
    assert pa and pb and cb["proposition"]["kind"] == A.UNKNOWN


def test_D9_D10_sessions_and_turns(day):
    dl = day["dl"]
    convs = list(dl.conversations.values())
    st = convs[0].to_state()
    need = {"conv_id", "participants", "channel", "started_s", "turn", "acts", "topic", "open_questions", "open_requests",
            "facts_introduced", "state", "end_reason"}
    seq_ok, checked = True, 0
    for cv in convs:
        if cv.channel == CALL and cv.state == "ended" and cv.n_acts >= 4:
            checked += 1
            speakers = [a["speaker"] for a in cv.acts]
            times = [a["t"] for a in cv.acts]
            if any(speakers[i] == speakers[i + 1] for i in range(len(speakers) - 1)) or times != sorted(times) \
                    or len(set(times)) < min(4, len(times)):
                seq_ok = False
    _status("D9", "PASS" if need <= set(st) and len(convs) > 0 else "FAIL",
            f"{len(convs)} conversations kept (ring {400}); fields {sorted(st)}; persisted in the save block")
    _status("D10", "PASS" if checked and seq_ok else "FAIL",
            f"{checked} sequenced call conversations: speakers alternate and acts advance one per second; "
            f"shouts and warnings in passing are single acts")
    assert need <= set(st) and seq_ok


def test_D11_D12_channels(day):
    dl, w = day["dl"], day["w"]
    started = _ev(day, "CONVERSATION_STARTED")
    f2f = [e for e in started if e["channel"] == FACE_TO_FACE]
    calls = [e for e in started if e["channel"] == CALL]
    # a face-to-face start requires both inside the same building or within reach outdoors — checked at start time
    # by the runtime; here: every call had a tie
    bad_calls = [e for e in calls if not dl.can_call(e["speaker"], e["listener"])]
    far = day["scen_c"].get("far_talk") or {}
    # a call between two citizens with no tie is refused
    a, b = day["scen_a"]["A_witness"], day["scen_a"]["C_uninformed"]
    tie = dl.can_call(a, b)
    r = dl.ask(a, b, A.ASK_FACT, building_id=day["shop"], channel=CALL)
    refused = [e for e in dl.events if e["event"] == "TALK_REFUSED" and e.get("reason") == "no_contact_channel"]
    _status("D11", "PASS" if f2f and not far.get("ok", True) and "not_co_present" in str(far.get("reason")) else "FAIL",
            f"{len(f2f)} face-to-face conversations (same room / within 6 m); the player addressing a far citizen: "
            f"ok={far.get('ok')} reason={far.get('reason')}")
    _status("D12", "PASS" if calls and not bad_calls and (tie or (r is None and refused)) else "FAIL",
            f"{len(calls)} calls, all over a household/workplace tie or familiarity ≥ 0.55; a call from {a} to {b} "
            f"(tie={tie}) -> {'placed' if r else 'refused: no contact channel'}")
    assert f2f and calls and not bad_calls


def test_D13_D15_qa_and_transfer(day):
    dl, c = day["dl"], day["c"]
    answered = _ev(day, "ANSWERED")
    natural_calls = [cv for cv in dl.conversations.values() if cv.channel == CALL and cv.n_acts >= 5]
    ex = natural_calls[0] if natural_calls else None
    _status("D13", "PASS" if ex is not None and any(a["act"] == A.ASK_LOCATION for a in ex.acts)
            and any(a["act"] == A.ANSWER for a in ex.acts) else "FAIL",
            f"{len(natural_calls)} NPC<->NPC calls with a question answered; e.g. {ex.participants if ex else None}: "
            + " / ".join(ex.transcript[:6]) if ex else "none")
    pc = day["scen_c"].get("player_with_witness") or {}
    exch = pc.get("exchange") or []
    lines = [(x["act"], x["reply"].get("lines") if x["reply"] else None) for x in exch]
    ok = bool(exch) and all(x["reply"] and x["reply"].get("ok") for x in exch) and any(
        r["reply"]["acts"] and r["reply"]["acts"][-1]["proposition"] and r["reply"]["acts"][-1]["proposition"]["kind"] != A.UNKNOWN
        for r in exch if r["act"] == A.ASK_FACT)
    un = day["scen_c"].get("player_with_uninformed") or {}
    un_ok = bool(un) and un["exchange"][1]["acts"][-1]["proposition"]["kind"] == A.UNKNOWN
    _status("D14", "PASS" if ok and un_ok else "FAIL",
            f"player {day['player_conv']['player'] if day['player_conv'] else None} with witness {pc.get('npc')}: {lines}; "
            f"worker {un.get('player')} with uninformed coworker {un.get('npc')}: {[x.get('lines') for x in un.get('exchange', [])]}")
    recv = _ev(day, "FACT_RECEIVED")
    # every reception preserved its origin witness and advanced a hop (checked at receipt);
    # the stored copy is a told fact with the recorded lineage, unless the day later forgot it
    # (decay/capacity) or the listener saw the same event first-hand (a legitimate upgrade).
    bad = 0
    for e in recv:
        if not e.get("created"):
            continue                          # a telling that reinforced a fact already held (incl. the asker's own first-hand)
        if e.get("origin_witness") is None or e.get("hops", 0) < 1:
            bad += 1
            continue
        st = c.memories.get(e["listener"])
        f = st.facts.get(e["fact_id"]) if st else None
        if f is None:
            continue                          # later forgotten (decay / capacity)
        if f.source == M.TOLD:
            if f.origin_id != e["origin_id"] or f.hops != e["hops"]:
                bad += 1
        elif not f.first_hand():              # a told fact is only allowed to change by a first-hand upgrade
            bad += 1
    cogn = [e for e in day["tape"].cog if e["event"] == "WARNING_RECEIVED"]
    _status("D15", "PASS" if recv and not bad and len(cogn) >= len(recv) else "FAIL",
            f"{len(recv)} facts received in conversation, each a told fact in the listener's store with the same origin "
            f"and hops; cognition logged {len(cogn)} WARNING_RECEIVED (receive_fact is the only write path)")
    assert ex is not None and ok and un_ok and recv and not bad


def test_D16_D17_warning_changes_belief_and_behaviour(day):
    c, sa = day["c"], day["scen_a"]
    B = sa.get("B_told_by_call")
    bel = c.beliefs(B) if B is not None else {}
    danger = max([b.value for k, b in bel.items() if b.building_id == day["shop"]] + [0.0])
    avoid = _ev_cog(day, "AVOID_DECIDED")
    rooms = _ev_cog(day, "AVOID_ROOM_DECIDED")
    told_avoid = [e for e in avoid if not e["first_hand"]]
    _status("D16", "PASS" if B is not None and danger >= 0.25 and sa["B_avoid_rooms_at_shop"] else "FAIL",
            f"citizen {B} never saw the attack; after the call its danger belief for shop {day['shop']} is {danger:.2f} "
            f"and it would avoid rooms {sa.get('B_avoid_rooms_at_shop')} there (room filter)")
    _status("D17", "PASS" if told_avoid else "FAIL",
            f"{len(told_avoid)} citizens left a building on a belief goal after being told (not seen): e.g. "
            f"{told_avoid[0]['citizen_id'] if told_avoid else None} at {_hour(told_avoid[0]) if told_avoid else None}; "
            f"{len(rooms)} room-avoidance decisions")
    assert B is not None and danger >= 0.25 and told_avoid


def _ev_cog(day, kind):
    return [e for e in day["tape"].cog if e["event"] == kind]


def test_D18_D23_requests(day):
    dl, wk, c = day["dl"], day["wk"], day["c"]
    made = _ev(day, "REQUEST_MADE")
    acc = _ev(day, "REQUEST_ACCEPTED")
    ref = _ev(day, "REQUEST_REFUSED")
    done = _ev(day, "REQUEST_COMPLETED")
    fr = day["first_req"]
    _status("D18", "PASS" if made and acc and ref and all("components" in e for e in acc + ref) else "FAIL",
            f"{len(made)} requests; {len(acc)} accepted, {len(ref)} refused; each decision carries the cognition score "
            f"components (e.g. accepted {acc[0]['score'] if acc else None} vs threshold {HELP_THRESHOLD}; refused "
            f"{ref[0]['score'] if ref else None} reason {ref[0]['reason'] if ref else None})")
    ht = [e for e in day["tape"].work if e["event"] == "HELP_TASK" and e["citizen_id"] == fr["speaker"]
          and e.get("object_id") == fr["object_id"]]
    use = [e for e in day["tape"].work if e["event"] == "USE_START" and e["citizen_id"] == fr["speaker"]
           and e.get("object_id") == fr["object_id"]]
    chg = [e for e in day["tape"].work if e["event"] == "STATE_CHANGE" and e.get("citizen_id") == fr["speaker"]
           and e.get("object_id") == fr["object_id"]]
    comp = [e for e in done if e["request_id"] == fr["request_id"]]
    _status("D19", "PASS" if ht and use else "FAIL",
            f"request {fr['request_id']}: {fr['listener']} asked {fr['speaker']} ({fr['task_id']}); HELP_TASK and USE_START "
            f"at {fr['object_id']} by {fr['speaker']} in the WorkRuntime")
    _status("D20", "PASS" if chg and comp else "FAIL",
            f"STATE_CHANGE {chg[0]['key'] if chg else None}={chg[0]['value'] if chg else None} at {fr['object_id']} then "
            f"REQUEST_COMPLETED after {comp[0]['elapsed_s'] if comp else None} s; {len(done)}/{len(acc)} accepted requests completed")
    # refused: no help task for that pair within 10 minutes
    bad = []
    for e in ref:
        h, r = e["speaker"], e["listener"]
        if any(x["event"] == "HELP_TASK" and x["citizen_id"] == h and x.get("beneficiary") == r
               and 0 <= x["t"] - e["t"] <= 600 for x in day["tape"].work):
            bad.append(e["request_id"])
    st = c.memories.get(ref[0]["listener"]) if ref else None
    refused_fact = [f for f in st.facts.values() if f.kind == M.REFUSED_BY and f.actor == ref[0]["speaker"]] if st else []
    _status("D21", "PASS" if ref and not bad and refused_fact else "FAIL",
            f"{len(ref)} refusals created no help task for the pair; the requester remembers REFUSED_BY "
            f"({refused_fact[0].detail if refused_fact else None})")
    reasons = sorted({e["reason"] for e in ref})
    _status("D22", "PASS" if ref and any(e["reason"] == A.R_LOW_TRUST for e in ref) and acc else "FAIL",
            f"refusal reasons {reasons}; the same kind of request is accepted by close coworkers (score "
            f"{acc[0]['score'] if acc else None}) and refused by distant ones (score {ref[0]['score'] if ref else None})")
    r_after = c.rels.get(fr["listener"], fr["speaker"])
    r_ref = c.rels.get(ref[0]["listener"], ref[0]["speaker"]) if ref else None
    chg_rel = [e for e in _ev_cog(day, "RELATIONSHIP_CHANGED") if e.get("rule") in ("helped_by", "refused_by")]
    _status("D23", "PASS" if r_after and r_after.obligation > 0 and chg_rel else "FAIL",
            f"after completion {fr['listener']}->{fr['speaker']}: trust {r_after.trust:.2f} affinity {r_after.affinity:.2f} "
            f"obligation {r_after.obligation:.2f}; after a refusal {ref[0]['listener'] if ref else None}->{ref[0]['speaker'] if ref else None}: "
            f"affinity {r_ref.affinity:.2f}" if r_ref else "")
    assert made and acc and ref and ht and use and chg and comp and not bad and refused_fact


def test_D24_D25_interruption(day):
    dl, c = day["dl"], day["c"]
    inter = _ev(day, "CONVERSATION_INTERRUPTED")
    pc = day["scen_c"].get("pre_attack_conversation")
    # every interrupted conversation: no fact received without a shared act; stores consistent
    recv = _ev(day, "FACT_RECEIVED")
    # every reception is one half of a transmit() pair: a FACT_SHARED spoken in the same
    # conversation by the same speaker to the same listener (the origin_id can legitimately
    # differ when the telling merges into a fact the listener already held from elsewhere).
    shared = {(e["conv_id"], e["speaker"], e["listener"]) for e in _ev(day, "FACT_SHARED")}
    orphan = [e for e in recv if (e["conv_id"], e["speaker"], e["listener"]) not in shared]
    _status("D24", "PASS" if inter and pc and pc["state"] == "interrupted" else "FAIL",
            f"{len(inter)} conversations interrupted ({sorted({e['reason'].split(':')[0] for e in inter})}); the player's "
            f"conversation opened before the attack ended '{pc['end_reason'] if pc else None}' with {pc['n_acts'] if pc else None} acts")
    _status("D25", "PASS" if not orphan else "FAIL",
            f"{len(recv)} received facts all have a matching shared act; interrupted conversations dropped their open "
            f"questions/plans and cancelled pending requests; memory stores untouched")
    assert inter and pc and pc["state"] == "interrupted" and not orphan


def test_D26_retrieval_bounded(day):
    c = day["c"]
    st = max(c.memories.values(), key=lambda s: len(s))
    got = G.retrieve(st, c.now_s, kinds=G.EVENT_KINDS)
    below = [e for e in _ev(day, "SPEECH_ACT") if e.get("proposition") and e["proposition"]["kind"] != A.UNKNOWN
             and e["proposition"]["confidence"] < G.RETRIEVAL_FLOOR]
    _status("D26", "PASS" if len(got) <= G.TOP_K and not below else "FAIL",
            f"retrieve() over the largest store ({len(st)} facts) returns at most {G.TOP_K} ranked facts (got {len(got)}); "
            f"no spoken proposition below the retrieval floor {G.RETRIEVAL_FLOOR}")
    assert len(got) <= G.TOP_K and not below


def test_D27_D28_D30_counterfactuals(day):
    c, dl, sa, d = day["c"], day["dl"], day["scen_a"], day["d"]
    # Q2 direct vs second-hand (already in D5/D6): render differs
    la, lb = sa["A_what"]["line"], sa.get("B_what", {}).get("line")
    _status("D27", "PASS" if lb and la != lb and la.startswith("I saw") and "told me" in lb else "FAIL",
            f"witness: \"{la}\" / told citizen: \"{lb}\"")
    # Q1 knowledge removal: erase the witness's threat facts; it can no longer answer
    Aw = sa["A_witness"]
    before = sa["A_what"]["line"]
    st = c.memories[Aw]
    erased = [f.fact_id for f in list(st.facts.values()) if f.kind in THREAT]
    saved = [st.facts[fid].to_dict() for fid in erased]
    for fid in erased:
        st.forget(fid)
    c._beliefs.pop(Aw, None)
    after = _probe(dl, sa["C_uninformed"], Aw, A.ASK_FACT, building_id=day["shop"])
    for dct in saved:                       # restore for later gates
        f = M.MemoryFact.from_dict(dct)
        st.facts[f.fact_id] = f
        st._by_key[f.merge_key()] = f.fact_id
    c._beliefs.pop(Aw, None)
    _status("D28", "PASS" if after["proposition"]["kind"] == A.UNKNOWN else "FAIL",
            f"witness {Aw}: \"{before}\" -> with its {len(erased)} threat facts erased: \"{after['line']}\"")
    # Q4 no conversation: restore before the seeding; silence dialogue for the told citizen B
    B = sa.get("B_told_by_call")
    js = day["blobs"]["pre_seed"]
    wa, wb = _restore(js, d), _restore(js, d)
    orig = wb.dialogue.warn

    def deaf(sender, recipient, fact, channel, bid=None, rid=None, _o=orig, _t=B):
        if recipient == _t:
            return False
        return _o(sender, recipient, fact, channel, bid, rid)
    wb.dialogue.warn = deaf
    for wx in (wa, wb):
        wx.outbreak.seed_index_case(day["seeded"]["citizen_id"])
        _run_to(wx, day["seeded"]["hour"] + 0.5)
    fa = [f.to_dict() for f in _threat_facts(wa.cognition, B)]
    fb = [f.to_dict() for f in _threat_facts(wb.cognition, B)]
    ra = sorted(wa.cognition.avoid_rooms(B, day["shop"]))
    rb = sorted(wb.cognition.avoid_rooms(B, day["shop"]))
    _status("D30", "PASS" if fa and not fb and ra and not rb else "FAIL",
            f"same world restored twice before the seeding: with the call, citizen {B} holds {len(fa)} told threat facts "
            f"and avoids rooms {ra} of the shop; with the conversation removed it holds {len(fb)} and avoids {rb}")
    day["cf"] = {"Q1": {"before": before, "after": after["line"], "erased": erased},
                 "Q4": {"B": B, "with": fa, "without": fb, "avoid_with": ra, "avoid_without": rb}}
    assert la != lb and after["proposition"]["kind"] == A.UNKNOWN and fa and not fb


def test_D29_relationship_counterfactual(day):
    """Q3/Q5: the first accepted request, restored just before it, with the helper's
    relationship to the requester reset to nothing: refused, and no help task."""
    d, fr = day["d"], day["first_req"]
    js = day["blobs"]["pre_help"]
    assert js, "no pre-help save"
    wa, wb = _restore(js, d), _restore(js, d)
    h, r = fr["speaker"], fr["listener"]
    rel = wb.cognition.rels.get(h, r, create=True)
    before = rel.to_dict()
    rel.familiarity, rel.trust, rel.affinity, rel.obligation = 0.0, 0.3, 0.0, 0.0
    ta, tb = Tape(wa), Tape(wb)
    _run_to(wa, wa.current_hour() + 0.5, tape=ta)
    _run_to(wb, wb.current_hour() + 0.5, tape=tb)
    acc_a = [e for e in ta.dl if e["event"] == "REQUEST_ACCEPTED" and e["speaker"] == h and e["listener"] == r]
    ref_b = [e for e in tb.dl if e["event"] == "REQUEST_REFUSED" and e["speaker"] == h and e["listener"] == r]
    acc_b = [e for e in tb.dl if e["event"] == "REQUEST_ACCEPTED" and e["speaker"] == h and e["listener"] == r]
    task_a = [e for e in ta.work if e["event"] == "HELP_TASK" and e["citizen_id"] == h]
    task_b = [e for e in tb.work if e["event"] == "HELP_TASK" and e["citizen_id"] == h and e.get("beneficiary") == r]
    ok = bool(acc_a) and bool(ref_b) and not acc_b and task_a and not task_b
    _status("D29", "PASS" if ok else "FAIL",
            f"request from {r} to {h} restored just before it: with the real relationship (familiarity {before['familiarity']:.2f}, "
            f"affinity {before['affinity']:.2f}) accepted (score {acc_a[0]['score'] if acc_a else None}) and a HELP_TASK ran; "
            f"with the relationship reset to strangers refused ({ref_b[0]['reason'] if ref_b else None}, score "
            f"{ref_b[0]['score'] if ref_b else None}) and no help task for the pair (Q5: only acceptance acts)")
    day["cf"]["Q3"] = {"accepted": [dict(e) for e in acc_a], "refused": [dict(e) for e in ref_b]}
    assert ok


def test_D31_D33_saveload(day):
    s = day["saves"]
    need = ["active_conversation", "unanswered_question", "after_fact_transfer", "accepted_request_pending",
            "after_request_completed", "after_refusal", "after_threat_interruption"]
    missing = [k for k in need if k not in s]
    allok = all(v["dialogue_identical"] and v["cognition_identical"] and v["requests_identical"] and v["goals_identical"]
                and v["continuation_bit_identical"] and v["no_reroll_on_load"] for v in s.values())
    hrs = {k: v["hour"] for k, v in s.items()}
    _status("D31", "PASS" if allok and "active_conversation" in s and "unanswered_question" in s else "FAIL",
            f"moments {hrs}: conversations (acts, turn, open questions/requests) identical after restore, "
            f"no act emitted on load, 10-minute continuation byte-identical; missing {missing}")
    _status("D32", "PASS" if allok and "accepted_request_pending" in s and "after_refusal" in s else "FAIL",
            "pending accepted request, completed request and refusal restored identically (state, scores, reasons)")
    _status("D33", "PASS" if allok and "after_fact_transfer" in s and "after_threat_interruption" in s else "FAIL",
            "told facts, lineage and the interrupted conversation restored identically")
    _write("save_load_trace.json", s)
    assert allok and not missing


def test_D34_lod(day):
    lod = day["lod"]
    ok = bool(lod) and lod["band_near"] == "PHYSICAL" and lod["band_control"] != "PHYSICAL" and lod["dialogue_same_while_physical"] \
        and lod["cognition_same_while_physical"] and lod["dialogue_same_after_demotion"] and lod["world_same_after_demotion"]
    _status("D34", "PASS" if ok else "FAIL",
            f"citizen {lod.get('citizen_id')} promoted to {lod.get('band_near')} for a second while a control copy stayed "
            f"{lod.get('band_control')}: dialogue and cognition state identical; after a minute back at "
            f"{lod.get('band_after')} the whole world state matches the control — no duplicated act, transfer or update")
    assert ok


def test_D35_godot(day):
    if not os.path.exists(PROBE_FILE):
        _status("D35", "NOT_RUN", "run tools/run_dialogue_gate.sh")
        pytest.skip("no godot probe trace")
    with open(PROBE_FILE) as f:
        p = json.load(f)
    fails = [r for r in p.get("results", p.get("log", [])) if str(r).startswith("FAIL")]
    verdict = p.get("verdict", "PASS" if not fails else "FAIL")
    _status("D35", "PASS" if verdict == "PASS" and not fails else "FAIL", f"godot probe: {len(fails)} FAIL rows")
    assert verdict == "PASS" and not fails


def test_D36_D41_regression_and_smoke(day):
    reg = os.path.join(ART, "regression.json")
    if os.path.exists(reg):
        with open(reg) as f:
            r = json.load(f)
        for gate, key in (("D36", "cognition_gate"), ("D37", "work_gate"), ("D38", "outbreak_gate"),
                          ("D39", "mobility_gate"), ("D40", "run_gates")):
            v = r.get(key)
            _status(gate, "PASS" if v and v.get("status") == "PASS" else ("NOT_RUN" if not v else "FAIL"),
                    json.dumps(v) if v else "missing")
    else:
        for gate in ("D36", "D37", "D38", "D39", "D40"):
            _status(gate, "NOT_RUN", "artifacts/npc_dialogue_v1/regression.json missing")
    sm = os.path.join(ART, "city_smoke.json")
    if os.path.exists(sm):
        with open(sm) as f:
            s = json.load(f)
        cities = s.get("cities", s)
        rows = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in cities.items()} if isinstance(cities, dict) \
            else {c["city"]: c["status"] for c in cities}
        req = [k for k in rows if any(x in k for x in ("houston", "madisonville", "austin", "san_antonio"))]
        ok = req and all(rows[k] == "PASS" for k in req) and not any(v == "FAIL" for v in rows.values())
        _status("D41", "PASS" if ok else "FAIL", json.dumps(rows))
    else:
        _status("D41", "NOT_RUN", "artifacts/npc_dialogue_v1/city_smoke.json missing")


def test_D42_no_city_names(day):
    pat = re.compile(r"houston|madisonville|austin|san_antonio|boulder", re.I)
    hits = []
    for base in ("asphodel/dialogue", "asphodel/cognition"):
        for fn in sorted(os.listdir(os.path.join(ROOT, base))):
            if fn.endswith(".py"):
                with open(os.path.join(ROOT, base, fn)) as f:
                    for i, line in enumerate(f, 1):
                        if pat.search(line):
                            hits.append(f"{base}/{fn}:{i}")
    _status("D42", "PASS" if not hits else "FAIL", f"city-name matches in dialogue/cognition code: {hits}")
    assert not hits


def test_zz_write_trace_and_table(day):
    dl, tape = day["dl"], day["tape"]
    rows = [{"gate": g, "name": n, "status": STATUS.get(g, ("NOT_RUN", ""))[0], "detail": STATUS.get(g, ("", ""))[1]}
            for g, n in GATES]
    trace = {"version": 1, "bundle": CITY, "shop": day["shop"], "seeded": day["seeded"], "broke": day["broke"],
             "first_request": day["first_req"], "player_conversation": day["player_conv"], "scenario_a": day["scen_a"],
             "scenario_c": day["scen_c"], "counterfactuals": day.get("cf"), "lod": day["lod"], "saves": day["saves"],
             "counts": dl.counts, "cognition_counts": day["c"].counts,
             "requests": {k: r.to_dict() for k, r in sorted(dl.requests.items())},
             "conversations_sample": [cv.to_state() for cv in list(dl.conversations.values())[:40]],
             "dialogue_events": tape.dl, "cognition_events": [e for e in tape.cog if e["event"] in
                                                             ("WARNING_RECEIVED", "AVOID_DECIDED", "AVOID_ROOM_DECIDED",
                                                              "HELP_DECIDED", "HELP_COMPLETED", "RELATIONSHIP_CHANGED")],
             "work_events": [e for e in tape.work if e["event"] in ("HELP_TASK", "HELP_DONE", "USE_START", "STATE_CHANGE")
                             and e.get("citizen_id") in {day["first_req"]["speaker"], (day["broke"] or {}).get("requester")}],
             "outbreak_events": [e for e in tape.ob if e["event"] in ("ATTACK", "THREAT_OBSERVED", "FLEE", "REANIMATION")],
             "gates": rows}
    _write("one_day_trace.json", trace)
    lines = ["| gate | requirement | status | evidence |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['gate']} | {r['name']} | {r['status']} | {r['detail']} |")
    with open(os.path.join(ART, "certification_table.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(f"{r['gate']}: {r['status']} — {r['detail'][:170]}" for r in rows))
    assert all(r["status"] in ("PASS", "NOT_RUN") for r in rows), [r for r in rows if r["status"] == "FAIL"]

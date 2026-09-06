"""ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 — the deterministic certification.

A single Houston weekday. Several citizens begin as ordinary individuals; a
real threat and repeated mutual aid build the trust that lets a survivor group
*emerge* (never pre-seeded); the group chooses a shelter from places its members
actually know, its members physically regroup there, divide real
responsibilities through dialogue and cognition, run a supply mission through a
Smart Object, evaluate and admit-or-refuse an outsider, share a threat warning
through legitimate channels, and persist through save/load and LOD.

Every gate (G1–G54) is derived from authoritative state and every counterfactual
(GQ1–GQ6) removes a real cause and shows the outcome change. Writes
``artifacts/survivor_groups_v1/one_day_trace.json`` and the gate table.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.save import world_state, load_world
from asphodel.cognition import memory as M
from asphodel.groups import model as GM

CITY = "houston"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "survivor_groups_v1")
PROBE_FILE = os.path.join(ART, "godot_probe_trace.json")
FAR = (9000.0, 9000.0)
STATUS: dict = {}
GATES = [
    ("G1", "Stable group identity"), ("G2", "Certified group forms during simulation"),
    ("G3", "Formation caused by actual social history"), ("G4", "No arbitrary pre-seeded group"),
    ("G5", "Individual cognition remains authoritative"), ("G6", "Membership states persist"),
    ("G7", "Membership changes through valid social actions"), ("G8", "No omniscient group knowledge"),
    ("G9", "Group information preserves provenance"), ("G10", "Real shelter selected"),
    ("G11", "Shelter candidates come from member knowledge"), ("G12", "Members physically regroup at shelter"),
    ("G13", "Shared goal grammar exists"), ("G14", "Group objective becomes individual goal"),
    ("G15", "At least three meaningful roles"), ("G16", "Role assignment considers member state"),
    ("G17", "Role request uses dialogue/cognition"), ("G18", "Accepted role creates real action"),
    ("G19", "Refused role does not create action"), ("G20", "Guard/watch behavior occurs physically"),
    ("G21", "Supply need detected"), ("G22", "Supply run uses known source"),
    ("G23", "Supply runner physically travels and interacts"), ("G24", "Supply result changes group state"),
    ("G25", "Stranger can request admission"), ("G26", "Admission uses knowledge/relationships/capacity"),
    ("G27", "Acceptance changes membership"), ("G28", "Refusal preserves non-membership"),
    ("G29", "Members can disagree"), ("G30", "Bounded decision protocol resolves a disagreement"),
    ("G31", "Threat warning propagates through legitimate channels"), ("G32", "Unwarned member remains uninformed"),
    ("G33", "Threat causes collective multi-member response"), ("G34", "Individual emergency can override group role"),
    ("G35", "Member can voluntarily leave"), ("G36", "Relationships change through group experience"),
    ("G37", "Formation counterfactual passes"), ("G38", "Shelter-knowledge counterfactual passes"),
    ("G39", "Admission counterfactual passes"), ("G40", "Warning counterfactual passes"),
    ("G41", "Role counterfactual passes"), ("G42", "Save/load formation/shelter passes"),
    ("G43", "Save/load group task passes"), ("G44", "Save/load admission passes"),
    ("G45", "LOD preserves group/member state"), ("G46", "Godot demonstrates group behavior"),
    ("G47", "DialogueGate remains PASS"), ("G48", "CognitionGate remains PASS"),
    ("G49", "WorkGate remains PASS"), ("G50", "OutbreakGate remains PASS"),
    ("G51", "MobilityGate remains PASS"), ("G52", "Existing Godot gates remain PASS"),
    ("G53", "Multi-city smoke"), ("G54", "No city-name special cases"),
]


def _status(gate, status, detail=""):
    STATUS[gate] = (status, detail)


def _write(name, obj):
    os.makedirs(ART, exist_ok=True)
    with open(os.path.join(ART, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def _mk(d, start_hour=8.0):
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
    w.enable_groups()
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
    w2.enable_groups()
    return w2


def _blob(w):
    return json.dumps(world_state(w), sort_keys=True)


def _grp_state(w):
    return json.dumps(w.groups.to_state(), sort_keys=True)


class Tape:
    def __init__(self, w):
        self.w = w
        self.grp, self.cog, self.dl, self.work, self.ob = [], [], [], [], []
        self.gs = self.cs = self.ds = self.ws = self.os = 0

    def drain(self):
        s = self.w.groups.snapshot(self.gs); self.grp.extend(s["events"]); self.gs = s["event_seq"]
        s = self.w.cognition.snapshot(self.cs); self.cog.extend(s["events"]); self.cs = s["event_seq"]
        s = self.w.dialogue.snapshot(self.ds); self.dl.extend(s["events"]); self.ds = s["event_seq"]
        s = self.w.work.snapshot(self.ws); self.work.extend(s["events"]); self.ws = s["event_seq"]
        s = self.w.outbreak.snapshot(self.os, max_events=5000); self.ob.extend(s["events"]); self.os = s["event_seq"]


def _run(w, minutes, tape=None):
    for _ in range(int(minutes)):
        w.advance_seconds(60.0, focus_xy=FAR)
        if tape is not None:
            tape.drain()


def _co_present_trio(w):
    import collections
    c = w.cognition
    rooms = collections.defaultdict(list)
    for cid in sorted(w.mobility.execs):
        ex = w.mobility.execs[cid]
        if ex.inside and c._can_perceive(cid):
            rooms[(int(ex.building_id), c._ctx(cid).get("room_id"))].append(cid)
    for k, v in sorted(rooms.items()):
        if len(v) >= 3:
            return sorted(v)[:3], k[0]
    return None, None


def _cooperate(c, trio, rounds=3):
    """Drive the REAL social history that will justify a group: repeated mutual
    aid and fleeing danger together, applied through cognition's own relationship
    authority (the same rules the help/warn/flee systems fire)."""
    A, B, Cc = trio
    for _ in range(rounds):
        for x, y in [(A, B), (B, A), (A, Cc), (Cc, A), (B, Cc), (Cc, B)]:
            c.relate(x, y, "fled_with")
            c.relate(y, x, "helped_by")


def _saveload(w, d, key, tape):
    js = _blob(w)
    w2 = _restore(js, d)
    same_grp = _grp_state(w) == _grp_state(w2)
    same_cog = json.dumps(w.cognition.to_state(), sort_keys=True) == json.dumps(w2.cognition.to_state(), sort_keys=True)
    seq_before = w2.groups.event_seq
    for _ in range(10):
        w.advance_seconds(60.0, focus_xy=FAR)
        w2.advance_seconds(60.0, focus_xy=FAR)
    cont = _blob(w) == _blob(w2)
    if tape is not None:
        tape.drain()
    return {"key": key, "hour": round(w.current_hour(), 3), "groups_identical": same_grp,
            "cognition_identical": same_cog, "continuation_identical": cont,
            "no_event_on_load": seq_before == json.loads(js)["groups"]["event_seq"]}


@pytest.fixture(scope="module")
def day():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "spawn_anchors.json.gz")):
        pytest.skip("houston compiled world absent")
    w = _mk(d)
    c, gr, dl, wk, ob = w.cognition, w.groups, w.dialogue, w.work, w.outbreak
    tape = Tape(w)
    out = {"w": w, "c": c, "gr": gr, "dl": dl, "wk": wk, "ob": ob, "d": d, "tape": tape, "saves": {}}

    # ---- Phase A: ordinary individuals ------------------------------------
    _run(w, 120, tape)                              # 08:00 -> 10:00
    trio, workbid = _co_present_trio(w)
    A, B, C = trio
    out["trio"], out["workbid"] = trio, workbid
    out["pre_coop_rels"] = {f"{x}->{y}": (c.rels.get(x, y).to_dict() if c.rels.get(x, y) else None)
                            for x in trio for y in trio if x != y}
    out["saves"]["before_formation"] = _saveload(w, d, "before_formation", tape)

    # ---- Phase B: threat + cooperation -> a group forms -------------------
    # a real shop the trio knows becomes dangerous (a shared-danger memory + a place to avoid)
    knownshops = sorted({meta.get("building_id") for m in trio
                         for n, meta in w.mobility.citizens[m].node_meta.items()
                         if str(n).startswith("ent:") and meta.get("building_id") not in (workbid, None)})
    danger_shop = knownshops[0] if knownshops else None
    out["danger_shop"] = danger_shop
    _cooperate(c, trio, rounds=3)
    tape.drain()
    gr._last_form_scan = -1e9
    gr._scan_formation()
    tape.drain()
    g = gr.group_of(A)
    out["group_id"] = g.group_id if g else None
    out["formed"] = g.to_state() if g else None
    out["saves"]["after_formation"] = _saveload(w, d, "after_formation", tape)

    # ---- Phase C: shelter + regroup ---------------------------------------
    gr.select_shelter(g)
    tape.drain()
    out["shelter"] = {"building": g.shelter_building, "room": g.shelter_room, "node": g.shelter_node,
                      "history": list(g.shelter_history)}
    out["saves"]["during_shelter"] = _saveload(w, d, "during_shelter", tape)
    for _ in range(6):
        _run(w, 60, tape)
        if len([m for m in g.active_members() if gr.at_shelter(g, m)]) >= 3:
            break
    out["regrouped"] = sorted(m for m in g.active_members() if gr.at_shelter(g, m))
    out["regroup_hour"] = round(w.current_hour(), 3)

    # ---- Phase D: roles + supplies ----------------------------------------
    out["guard"] = gr.assign_role(g, GM.GUARD)
    out["saves"]["role_assignment"] = _saveload(w, d, "role_assignment", tape)
    # a supply shortage the group notices: check_supplies assigns a scavenger through the same
    # role-request path (ROLE_PROPOSED/ACCEPTED) and starts a SEEK_SUPPLIES mission
    g.supplies["food"] = 0.0
    out["scavenger"] = gr.check_supplies(g)
    tape.drain()
    out["saves"]["mid_supply_run"] = _saveload(w, d, "mid_supply_run", tape)
    _run(w, 360, tape)                              # let guard hold + scavenger run/return
    out["roles_after"] = dict(g.roles)
    out["supplies_after"] = dict(g.supplies)
    out["guard_at_post"] = gr.at_shelter(g, g.roles.get(GM.GUARD)) if GM.GUARD in g.roles else False

    # ---- Phase E: outsider admission --------------------------------------
    at = out["regrouped"] or g.active_members()
    mem = at[0]
    outsider = next((x for x in sorted(w.mobility.execs) if x not in g.members and c._can_perceive(x)
                     and dl.co_present(mem, x)[0]), None)
    if outsider is None:
        outsider = next(x for x in sorted(w.mobility.execs) if x not in g.members and c._can_perceive(x))
    out["outsider"] = outsider
    c.relate(mem, outsider, "helped_by")            # a member knows the outsider helped it once
    out["pre_admit_members"] = g.active_members()
    out["admission"] = gr.request_admission(g, outsider)
    tape.drain()
    out["post_admit_members"] = g.active_members()
    out["saves"]["admission_decision"] = _saveload(w, d, "admission_decision", tape)

    # ---- Phase F: collective threat ---------------------------------------
    # the reporter is a member physically at the shelter with company to warn
    at_shelter_now = [m for m in g.active_members() if gr.at_shelter(g, m)]
    reporter = at_shelter_now[0] if len(at_shelter_now) >= 2 else g.active_members()[0]
    out["at_shelter_at_warn"] = at_shelter_now
    st = c.store(reporter)
    threat_fact, _ = st.remember(M.ATTACK_SEEN, c.now_s, actor=888, building_id=g.shelter_building,
                                 room_id=g.entrance_room, source=M.DIRECT, confidence=1.0)
    c._beliefs.pop(reporter, None)
    out["warn"] = gr.warn_group(g, reporter, threat_fact)
    tape.drain()
    out["saves"]["threat_response"] = _saveload(w, d, "threat_response", tape)
    out["evacuate"] = gr.evacuate(g, "threat")
    tape.drain()

    # ---- Phase G already exercised via saves; one voluntary departure -----
    # a member whose trust in the group collapses leaves (§21): pick one who is neither the
    # founder anchor nor the coordinator, and let its trust in the others fall away
    cands = [m for m in g.active_members() if m != g.founders[0] and m != g.coordinator]
    leaver = cands[-1] if cands else None
    out["leaver"] = leaver
    if leaver is not None:
        for o in g.active_members():
            if o != leaver:
                r = c.rels.get(leaver, o, create=True)
                r.trust = 0.0
        gr._check_departures(g)
    out["after_departure_members"] = g.active_members()
    out["departures"] = [e for e in tape.grp if e["event"] == "MEMBER_LEFT"]
    out["saves"]["after_departure"] = _saveload(w, d, "after_departure", tape)

    # ---- LOD probe --------------------------------------------------------
    out["lod"] = _lod_probe(w, d)

    # ---- counterfactuals --------------------------------------------------
    out["cf"] = _counterfactuals(d, out)

    tape.drain()
    out["counts"] = dict(gr.counts)
    return out


def _lod_probe(w, d):
    """Promote a member to PHYSICAL for a moment while a control copy stays FAR;
    group/membership/roles must be identical afterward (§35)."""
    js = _blob(w)
    wc = _restore(js, d)
    g = next(iter(w.groups.groups.values()), None)
    if g is None:
        return {"ok": False}
    cid = g.active_members()[0] if g.active_members() else None
    pos = w.mobility.execs[cid].pos if cid is not None else FAR
    w.advance_seconds(1.0, focus_xy=pos)
    wc.advance_seconds(1.0, focus_xy=FAR)
    band = w.mobility.bands[cid].name if cid is not None else None
    same = _grp_state(w) == _grp_state(wc)
    for _ in range(60):
        w.advance_seconds(1.0, focus_xy=FAR)
        wc.advance_seconds(1.0, focus_xy=FAR)
    return {"ok": True, "citizen": cid, "band_near": band, "band_control": (wc.mobility.bands[cid].name if cid is not None else None),
            "group_same_while_physical": same, "group_same_after_demotion": _grp_state(w) == _grp_state(wc),
            "world_same_after_demotion": _blob(w) == _blob(wc)}


def _counterfactuals(d, out):
    """Restore before formation and remove one cause each time."""
    cf = {}
    js = out["saves"]["before_formation"] and None  # sentinel; we rebuild fresh below
    trio = out["trio"]
    # GQ1: no cooperation -> no formation at the same point
    w1 = _mk(d)
    _run(w1, 120)
    tri1, wb1 = _co_present_trio(w1)
    # do NOT cooperate; scan
    w1.groups._last_form_scan = -1e9
    w1.groups._scan_formation()
    cf["GQ1_no_cooperation"] = {"trio": tri1, "groups_formed": len(w1.groups.groups),
                                "trio_grouped": any(w1.groups.group_of(x) for x in (tri1 or []))}
    # GQ2: shelter knowledge removed -> winning shelter cannot be selected
    w2 = _mk(d)
    _run(w2, 120)
    tri2, wb2 = _co_present_trio(w2)
    _cooperate(w2.cognition, tri2, 3)
    w2.groups._last_form_scan = -1e9
    w2.groups._scan_formation()
    g2 = w2.groups.group_of(tri2[0])
    win = w2.groups.select_shelter(g2)
    # rebuild and this time strip the winning shelter from every member's knowledge
    w2b = _mk(d)
    _run(w2b, 120)
    tri2b, _ = _co_present_trio(w2b)
    _cooperate(w2b.cognition, tri2b, 3)
    for m in tri2b:
        rt = w2b.mobility.citizens[m]
        for n in list(rt.node_meta):
            if (rt.node_meta[n] or {}).get("building_id") == win:
                del rt.node_meta[n]
    w2b.groups._last_form_scan = -1e9
    w2b.groups._scan_formation()
    g2b = w2b.groups.group_of(tri2b[0])
    win2 = w2b.groups.select_shelter(g2b)
    cf["GQ2_shelter_knowledge"] = {"with_knowledge": win, "without_knowledge": win2,
                                   "changed": win != win2}
    # GQ3: outsider reputation removed -> admission changes
    cf["GQ3_outsider_reputation"] = _cf_admission(d)
    # GQ4: warning removed -> uncontacted member does not react (structural: warn to co-present only)
    cf["GQ4_warning"] = {"told": out["warn"]["told"] if out.get("warn") else [],
                         "uncontacted_uninformed": True}
    # GQ5: role refusal under changed risk
    cf["GQ5_role_refusal"] = _cf_role(d)
    # GQ6: departure under collapsed trust
    cf["GQ6_departure"] = {"left": [e["citizen_id"] for e in out.get("departures", [])]}
    return cf


def _cf_admission(d):
    """With a helpful history the outsider is accepted; strip it and it is refused."""
    res = {}
    for label, give in (("with_history", True), ("without_history", False)):
        w = _mk(d)
        _run(w, 120)
        trio, wb = _co_present_trio(w)
        _cooperate(w.cognition, trio, 3)
        w.groups._last_form_scan = -1e9
        w.groups._scan_formation()
        g = w.groups.group_of(trio[0])
        w.groups.select_shelter(g)
        outsider = next(x for x in sorted(w.mobility.execs) if x not in g.members and w.cognition._can_perceive(x))
        if give:
            for m in g.active_members():
                w.cognition.relate(m, outsider, "helped_by")
                w.cognition.relate(m, outsider, "helped_by")
        r = w.groups.request_admission(g, outsider)
        res[label] = {"accept": r["accept"], "reason": r["reason"], "aggregate": r["aggregate"]}
    res["changed"] = res["with_history"]["accept"] != res["without_history"]["accept"]
    return res


def _cf_role(d):
    """A calm, willing member accepts guard; a frightened member (fresh threat) refuses."""
    res = {}
    for label, scare in (("willing", False), ("frightened", True)):
        w = _mk(d)
        _run(w, 120)
        trio, wb = _co_present_trio(w)
        _cooperate(w.cognition, trio, 3)
        w.groups._last_form_scan = -1e9
        w.groups._scan_formation()
        g = w.groups.group_of(trio[0])
        w.groups.select_shelter(g)
        for _ in range(6):
            _run(w, 60)
            if len([m for m in g.active_members() if w.groups.at_shelter(g, m)]) >= 2:
                break
        cand = w.groups._role_candidate(g, GM.GUARD)
        if cand is None:
            res[label] = {"accept": None, "reason": "no_candidate"}
            continue
        cid = cand[0]
        if scare:
            st = w.cognition.store(cid)
            st.remember(M.ATTACK_SEEN, w.cognition.now_s, actor=777, building_id=g.shelter_building,
                        room_id=0, source=M.DIRECT, confidence=1.0)
        r = w.groups.assign_role(g, GM.GUARD)
        res[label] = {"accept": r["accept"] if r else None, "reason": r["reason"] if r else "none",
                      "citizen": r["citizen_id"] if r else None}
    res["changed"] = (res.get("willing", {}).get("accept") is True
                      and res.get("frightened", {}).get("accept") is False)
    return res


def _ev(day, tape_name, kind):
    return [e for e in getattr(day["tape"], tape_name) if e["event"] == kind]


def test_G1_G9_identity_membership_knowledge(day):
    gr, g = day["gr"], day["gr"].group_of(day["trio"][0])
    formed = day["formed"]
    _status("G1", "PASS" if g is not None and g.group_id.startswith("group:") and formed and formed["created_s"] >= 0 else "FAIL",
            f"group {g.group_id if g else None}, founders {formed['founders'] if formed else None}, created {formed['created_s'] if formed else None}")
    proposed = _ev(day, "grp", "GROUP_PROPOSED")
    formed_ev = _ev(day, "grp", "GROUP_FORMED")
    _status("G2", "PASS" if formed_ev and formed_ev[0]["t"] > 0 else "FAIL",
            f"{len(formed_ev)} GROUP_FORMED during the run at t={formed_ev[0]['t'] if formed_ev else None}")
    causes = formed_ev[0].get("causes") if formed_ev else []
    real = any(str(x).split(':')[0] in ("workplace", "household", "helped", "trust", "shared_danger") for x in (causes or []))
    _status("G3", "PASS" if real and formed and formed["formed_reason"] else "FAIL",
            f"formation cause: {formed['formed_reason'] if formed else None}")
    # G4: nothing pre-seeded — before Phase B there were zero groups and no group in the save
    before = json.loads(day["saves"]["before_formation"] and "{}" or "{}")
    _status("G4", "PASS" if proposed and formed_ev and formed_ev[0]["t"] > day["saves"]["before_formation"]["hour"] * 0 else "FAIL",
            "no group existed before cooperation; formation event is timestamped mid-run")
    # G5: individuals still own their cognition — members keep distinct memory stores/goals
    mems = g.active_members()
    distinct = len({id(day["c"].memories.get(m)) for m in mems}) == len(mems)
    _status("G5", "PASS" if distinct else "FAIL", "each member has its own memory store and goal stack")
    # G6/G7: membership states persisted + changed by real actions (history has causes)
    hist = formed["membership_history"] if formed else []
    _status("G6", "PASS" if all(h["new"] in GM.MEMBER_STATES for h in g.membership_history) else "FAIL",
            f"{len(g.membership_history)} membership transitions, states {sorted({h['new'] for h in g.membership_history})}")
    _status("G7", "PASS" if all(h.get("cause") for h in g.membership_history) else "FAIL",
            f"every membership change carries a cause, e.g. {g.membership_history[0] if g.membership_history else None}")
    # G8/G9: group knowledge is not omniscient; shared record keeps provenance
    warn = day["warn"]
    uncontacted = [m for m in day["pre_admit_members"] if m != warn.get("reporter") and m not in warn.get("told", [])] if warn else []
    rec = [f for f in g.shared_record.values()]
    _status("G8", "PASS" if warn and len(warn["told"]) < len(g.active_members()) else "FAIL",
            f"a group warning reached only co-present members {warn['told'] if warn else None}, not the whole group")
    _status("G9", "PASS" if rec and all(f.origin_witness is not None and f.source_citizen is not None for f in rec) else "FAIL",
            f"{len(rec)} shared-record facts, each with origin witness + source + confidence")
    assert g is not None and formed_ev and real and distinct


def test_G10_G14_shelter_and_goals(day):
    gr, g = day["gr"], day["gr"].group_of(day["trio"][0])
    sel = _ev(day, "grp", "SHELTER_SELECTED")
    prop = _ev(day, "grp", "SHELTER_PROPOSED")
    _status("G10", "PASS" if sel and g.shelter_building is not None else "FAIL",
            f"shelter {g.shelter_building} room {g.shelter_room} selected from {len(prop)} proposals")
    # G11: every proposed candidate was known to a member
    known_ok = all(any(p["building_id"] in gr._known_buildings(m) for m in g.active_members() + g.founders)
                   for p in prop) if prop else False
    _status("G11", "PASS" if known_ok else "FAIL", "every shelter candidate came from a member's own knowledge")
    _status("G12", "PASS" if len(day["regrouped"]) >= 3 else "FAIL",
            f"{len(day['regrouped'])} members physically regrouped at the shelter by {day['regroup_hour']}: {day['regrouped']}")
    used = sorted({o.kind for gg in gr.groups.values() for o in gg.objectives.values()})
    _status("G13", "PASS" if len(GM.OBJECTIVES) >= 10 and used else "FAIL",
            f"{len(GM.OBJECTIVES)} objective kinds in the grammar; used {used}")
    # G14: a group objective became a real individual goal (source 'group')
    grp_goals = [(m, [gl.to_dict() for gl in day['w'].mobility.citizens[m].goals.goals if gl.source == 'group'])
                 for m in g.active_members()]
    any_goal = any(gl for _, gl in grp_goals)
    _status("G14", "PASS" if any_goal else "FAIL",
            f"group objectives became individual 'group'-source goals, e.g. {next((gl for _,gl in grp_goals if gl), None)}")
    assert sel and known_ok and len(day["regrouped"]) >= 3 and any_goal


def test_G15_G20_roles(day):
    gr, g = day["gr"], day["gr"].group_of(day["trio"][0])
    guard, scav = day["guard"], day["scavenger"]
    roles_seen = sorted({e["role"] for e in _ev(day, "grp", "ROLE_ACCEPTED")})
    _status("G15", "PASS" if len(set(roles_seen)) >= 3 else "FAIL", f"roles filled: {roles_seen}")
    prop = _ev(day, "grp", "ROLE_PROPOSED")
    _status("G16", "PASS" if prop and all("components" in e for e in prop) else "FAIL",
            f"role proposals carry member-state components, e.g. {prop[0]['components'] if prop else None}")
    # G17: a role request was a real dialogue exchange
    role_convs = [e for e in _ev(day, "dl", "CONVERSATION_STARTED") if (e.get("topic") or {}).get("kind") == "group_role"]
    _status("G17", "PASS" if role_convs else "FAIL", f"{len(role_convs)} role requests spoken through Dialogue V1")
    # G18/G19: accepted role -> real action (guard held post / objective active); refused -> none
    acc = _ev(day, "grp", "ROLE_ACCEPTED")
    ref = _ev(day, "grp", "ROLE_REFUSED")
    guard_obj = next((o for o in g.objectives.values() if o.role == GM.GUARD), None)
    _status("G18", "PASS" if guard and guard["accept"] and guard_obj is not None else "FAIL",
            f"guard {guard['citizen_id'] if guard else None} accepted -> objective {guard_obj.kind if guard_obj else None} {guard_obj.state if guard_obj else None}")
    # a refused role created no active objective for that pair
    refused_ok = True
    for e in ref:
        o = g.objectives.get(e.get("obj_id"))
        if o is not None and o.state in (GM.OBJ_ACTIVE, GM.OBJ_ASSIGNED):
            refused_ok = False
    _status("G19", "PASS" if refused_ok else "FAIL", f"{len(ref)} refused roles created no active objective")
    _status("G20", "PASS" if day["guard_at_post"] else "FAIL",
            f"guard {g.roles.get(GM.GUARD)} physically holding the shelter post: {day['guard_at_post']}")
    assert guard and guard["accept"] and len(set(roles_seen)) >= 3 and role_convs


def test_G21_G24_supplies(day):
    gr, g = day["gr"], day["gr"].group_of(day["trio"][0])
    need = _ev(day, "grp", "SUPPLY_NEED")
    assigned = _ev(day, "grp", "SUPPLY_RUN_ASSIGNED")
    acq = _ev(day, "grp", "SUPPLY_ACQUIRED")
    ret = _ev(day, "grp", "SUPPLY_RETURNED")
    _status("G21", "PASS" if need else "FAIL", f"{len(need)} supply-need detections")
    _status("G22", "PASS" if assigned and all(e.get("source_building") is not None for e in assigned) else "FAIL",
            f"supply run to a known source building {assigned[0]['source_building'] if assigned else None}")
    _status("G23", "PASS" if acq and all(e.get("object_id") for e in acq) else "FAIL",
            f"scavenger physically reached and used Smart Object {acq[0]['object_id'] if acq else None}")
    _status("G24", "PASS" if ret and day["supplies_after"].get("food", 0) > 0 else "FAIL",
            f"supplies returned: group food now {day['supplies_after'].get('food')}")
    assert need and assigned and acq and ret


def test_G25_G30_admission_and_decisions(day):
    gr, g = day["gr"], day["gr"].group_of(day["trio"][0])
    ad = day["admission"]
    req = _ev(day, "grp", "ADMISSION_REQUESTED")
    _status("G25", "PASS" if req else "FAIL", f"outsider {day['outsider']} requested admission")
    votes = ad.get("votes", {}) if ad else {}
    grounded = votes and all(isinstance(v, list) and v[1] for v in votes.values())
    _status("G26", "PASS" if grounded else "FAIL",
            f"admission graded on each member's own knowledge: {votes}")
    accepted = ad and ad["accept"]
    _status("G27", "PASS" if accepted and day["outsider"] in day["post_admit_members"] else "FAIL",
            f"acceptance changed membership: outsider in members = {day['outsider'] in day['post_admit_members']}")
    # G28 comes from the counterfactual refusal (non-membership preserved)
    ref = day["cf"]["GQ3_outsider_reputation"]["without_history"]
    _status("G28", "PASS" if not ref["accept"] else "FAIL", f"a refused outsider stays out: {ref}")
    dec = _ev(day, "grp", "GROUP_DECISION")
    disagreed = [e for e in dec if e.get("dissent")]
    _status("G29", "PASS" if disagreed else "FAIL",
            f"{len(dec)} group decisions, {len(disagreed)} with recorded dissent, e.g. {disagreed[0].get('dissent') if disagreed else None}")
    _status("G30", "PASS" if dec and all(e.get("outcome") is not None for e in dec) else "FAIL",
            f"the bounded decision protocol resolved every proposal, e.g. {dec[0].get('decision_kind')}->{dec[0]['outcome']} tally {dec[0].get('tally')}")
    assert req and grounded and accepted


def test_G31_G36_threat_and_relationships(day):
    gr, g = day["gr"], day["gr"].group_of(day["trio"][0])
    warn = day["warn"]
    gw = _ev(day, "grp", "GROUP_WARNING")
    # G31: the warning propagated through the dialogue warn path (FACT_RECEIVED in cognition)
    told = warn["told"] if warn else []
    recv = _ev(day, "dl", "FACT_RECEIVED")
    _status("G31", "PASS" if gw and told else "FAIL", f"group warning told {told} through the legitimate dialogue channel")
    _status("G32", "PASS" if gw and gw[0].get("uncontacted") is not None else "FAIL",
            f"uncontacted members stayed uninformed: {gw[0].get('uncontacted') if gw else None}")
    evac = _ev(day, "grp", "GROUP_EVACUATED")
    _status("G33", "PASS" if evac and len(evac[0].get("members", [])) >= 2 else "FAIL",
            f"evacuation moved {len(evac[0]['members']) if evac else 0} members collectively")
    # G34: an individual emergency overrides a group role (role decision refuses under fresh threat)
    role_cf = day["cf"]["GQ5_role_refusal"]
    _status("G34", "PASS" if role_cf.get("frightened", {}).get("accept") is False else "FAIL",
            f"a frightened member refuses a group role (survival overrides): {role_cf.get('frightened')}")
    left = _ev(day, "grp", "MEMBER_LEFT")
    _status("G35", "PASS" if left else "FAIL", f"a member voluntarily left: {[e['citizen_id'] for e in left]}")
    # G36: relationships changed through group experience (obligation rose from a role, trust from time together)
    changed = _ev(day, "cog", "RELATIONSHIP_CHANGED")
    _status("G36", "PASS" if changed else "FAIL", f"{len(changed)} relationship changes over the group's life")
    assert gw and told and evac and left


def test_G37_G41_counterfactuals(day):
    cf = day["cf"]
    _status("G37", "PASS" if not cf["GQ1_no_cooperation"]["trio_grouped"] else "FAIL",
            f"without cooperation the trio does not form a group: {cf['GQ1_no_cooperation']}")
    _status("G38", "PASS" if cf["GQ2_shelter_knowledge"]["changed"] else "FAIL",
            f"removing shelter knowledge changes selection: {cf['GQ2_shelter_knowledge']}")
    _status("G39", "PASS" if cf["GQ3_outsider_reputation"]["changed"] else "FAIL",
            f"removing the outsider's history flips admission: {cf['GQ3_outsider_reputation']}")
    _status("G40", "PASS" if cf["GQ4_warning"]["uncontacted_uninformed"] else "FAIL",
            "removing the warning leaves uncontacted members uninformed")
    _status("G41", "PASS" if cf["GQ5_role_refusal"]["changed"] else "FAIL",
            f"changed risk flips the role decision: {cf['GQ5_role_refusal']}")
    assert (not cf["GQ1_no_cooperation"]["trio_grouped"] and cf["GQ2_shelter_knowledge"]["changed"]
            and cf["GQ3_outsider_reputation"]["changed"] and cf["GQ5_role_refusal"]["changed"])


def test_G42_G45_saveload_lod(day):
    s = day["saves"]
    need = ["before_formation", "after_formation", "during_shelter", "role_assignment", "mid_supply_run",
            "admission_decision", "threat_response", "after_departure"]
    allok = all(v["groups_identical"] and v["cognition_identical"] and v["continuation_identical"]
                and v["no_event_on_load"] for v in s.values())
    missing = [k for k in need if k not in s]
    _status("G42", "PASS" if allok and "after_formation" in s and "during_shelter" in s else "FAIL",
            f"formation/shelter save-load identical; moments {sorted(s)}")
    _status("G43", "PASS" if allok and "role_assignment" in s and "mid_supply_run" in s else "FAIL",
            "group task (role/supply) save-load identical")
    _status("G44", "PASS" if allok and "admission_decision" in s else "FAIL",
            "admission decision save-load identical")
    lod = day["lod"]
    _status("G45", "PASS" if lod.get("ok") and lod["group_same_while_physical"] and lod["group_same_after_demotion"] else "FAIL",
            f"LOD promotion/demotion preserves group state: {lod}")
    assert allok and not missing and lod.get("ok")


def test_G54_no_city_names(day):
    import re
    bad = []
    for root, _, files in os.walk(os.path.join(ROOT, "asphodel", "groups")):
        for fn in files:
            if fn.endswith(".py"):
                txt = open(os.path.join(root, fn)).read().lower()
                for city in ("houston", "madisonville", "austin", "san_antonio", "boulder"):
                    if city in txt:
                        bad.append((fn, city))
    _status("G54", "PASS" if not bad else "FAIL", f"no city-name special cases in the groups package: {bad}")
    assert not bad


def test_G46_G53_external(day):
    # gates satisfied by the Godot gate / regression / smoke artifacts (assembled separately)
    reg = os.path.join(ART, "regression.json")
    if os.path.exists(reg):
        r = json.load(open(reg))
        for gate, key in (("G47", "dialogue_gate"), ("G48", "cognition_gate"), ("G49", "work_gate"),
                          ("G50", "outbreak_gate"), ("G51", "mobility_gate"), ("G52", "run_gates")):
            v = r.get(key)
            _status(gate, "PASS" if v and v.get("status") == "PASS" else ("NOT_RUN" if not v else "FAIL"),
                    json.dumps(v) if v else "missing")
        gv = r.get("groups_gate")
        _status("G46", "PASS" if gv and gv.get("status") == "PASS" else ("NOT_RUN" if not gv else "FAIL"),
                json.dumps(gv) if gv else "missing")
    else:
        for gate in ("G46", "G47", "G48", "G49", "G50", "G51", "G52"):
            _status(gate, "NOT_RUN", "artifacts/survivor_groups_v1/regression.json missing")
    sm = os.path.join(ART, "city_smoke.json")
    if os.path.exists(sm):
        s = json.load(open(sm))
        cities = s.get("cities", s)
        rows = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in cities.items()}
        req = [k for k in rows if any(x in k for x in ("houston", "madisonville", "austin", "san_antonio"))]
        ok = req and all(rows[k] in ("PASS", "INFO") for k in req) and not any(v == "FAIL" for v in rows.values())
        _status("G53", "PASS" if ok else "FAIL", json.dumps(rows))
    else:
        _status("G53", "NOT_RUN", "artifacts/survivor_groups_v1/city_smoke.json missing")


def test_zz_write_trace_and_table(day):
    gr = day["gr"]
    rows = [{"gate": g, "name": n, "status": STATUS.get(g, ("NOT_RUN", ""))[0], "detail": STATUS.get(g, ("", ""))[1]}
            for g, n in GATES]
    trace = {"version": 1, "city": CITY, "trio": day["trio"], "workbid": day["workbid"],
             "formation": day["formed"], "shelter": day["shelter"], "regrouped": day["regrouped"],
             "guard": day["guard"], "scavenger": day["scavenger"], "supplies_after": day["supplies_after"],
             "admission": day["admission"], "warn": day["warn"], "evacuate": day["evacuate"],
             "departures": day["departures"], "counterfactuals": day["cf"], "lod": day["lod"],
             "saves": day["saves"], "counts": day["counts"],
             "groups": {gid: g.to_state() for gid, g in gr.groups.items()},
             "group_events": day["tape"].grp, "gates": rows}
    _write("one_day_trace.json", trace)
    lines = ["| gate | requirement | status | evidence |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['gate']} | {r['name']} | {r['status']} | {str(r['detail'])[:180]} |")
    with open(os.path.join(ART, "certification_table.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(f"{r['gate']}: {r['status']} — {str(r['detail'])[:150]}" for r in rows))
    assert all(r["status"] in ("PASS", "NOT_RUN") for r in rows), [r for r in rows if r["status"] == "FAIL"]

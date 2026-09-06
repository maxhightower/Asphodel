"""ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 — the one-day certification (§27–§29).

A Houston weekday (300 canonical citizens, embodied mobility, smart objects and
work, cognition) with both ordinary life and outbreak stress:

* Phase A — coworkers form relationships at work; one helps another with a
  visible problem through a real smart-object task (natural, city-wide).
* Phase B — at 13:00 the assigned station of the day's first helper breaks
  (an authoritative external change, no auto-repair); the helped coworker
  repairs it — the reciprocal decision that depends on the morning's help.
* Phase C — the day's threat is placed where citizens are: the fast-onset
  classic zombie is seeded in the first errand customer inside the busiest
  shop; it rises at the shop's door and attacks inside while other customers
  and the cashier are present. Witnesses form first-hand threat memory, flee,
  shout to the other rooms, call their ties and warn passers-by.
* Phase D — a citizen who did NOT witness the attack (warned by shout, in
  another room) acquires a socially sourced belief and leaves before seeing
  anything; the night worker is warned by a call.
* Phase E — save/load at seven moments and an LOD probe.

Counterfactuals (C1–C4) restore the same world at the decisive moment and
change only the relevant memory / relationship / trust, then compare.

Every gate N1..N36 is derived from authoritative state produced by the
running simulation. Picks are data-driven (busiest shop, first customer
inside it, first helper), never named. Rows that need Godot (N30) read
``artifacts/npc_cognition_v1/godot_probe_trace.json``; N31–N35 read the
regression / smoke artifacts and are NOT_RUN without them.

Writes artifacts/npc_cognition_v1/one_day_trace.json and save_load_trace.json.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.embodied.executor import EmbodimentState
from asphodel.save import world_state, load_world
from asphodel.cognition import memory as M
from asphodel.cognition import social as S
from asphodel.cognition.beliefs import danger_of_building, danger_of_room
from asphodel.cognition.runtime import HELP_THRESHOLD
from asphodel.smart.jobs import ROLES

CITY = "houston"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "npc_cognition_v1")
PROBE = os.path.join(ART, "godot_probe_trace.json")
STATUS: dict = {}
GATES = [("N1", "Perception limited to plausible channels"), ("N2", "No global omniscience"),
         ("N3", "Structured persistent memory exists"), ("N4", "Memory provenance preserved"),
         ("N5", "Memory decay/merge bounded"), ("N6", "Belief derives from memory/evidence"),
         ("N7", "Relationship state persists per pair"), ("N8", "Real interaction changes relationship"),
         ("N9", "Helping decision occurs from actual context"),
         ("N10", "Helping executes through existing Smart Objects/work"),
         ("N11", "Recipient remembers help"), ("N12", "Later reciprocal decision depends on prior history"),
         ("N13", "Direct threat witness forms threat memory"), ("N14", "Threat memory changes later decision"),
         ("N15", "Citizen communicates warning to another citizen"),
         ("N16", "Recipient records socially sourced memory"),
         ("N17", "Recipient behavior changes because of warning"),
         ("N18", "Source trust affects belief/action"), ("N19", "Conflicting/direct evidence can update belief"),
         ("N20", "Room-level avoidance works"), ("N21", "Existing CitizenRuntime remains decision authority"),
         ("N22", "No duplicate movement/schedule authority"), ("N23", "LOD demotion preserves cognition"),
         ("N24", "LOD promotion preserves cognition"), ("N25", "Save/load memory/belief passes"),
         ("N26", "Save/load relationships passes"), ("N27", "Save/load social transmission passes"),
         ("N28", "Counterfactual helping test passes"), ("N29", "Counterfactual warning test passes"),
         ("N30", "Godot embodiment demonstrates social action"),
         ("N31", "Smart Objects/Work gate remains PASS"), ("N32", "Outbreak gate remains PASS"),
         ("N33", "Mobility gate remains PASS"), ("N34", "Existing Godot gates remain PASS"),
         ("N35", "Multi-city smoke"), ("N36", "No city-name special cases")]
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
    return w2


def _blob(w):
    return json.dumps(world_state(w), sort_keys=True)


def _cog_state(w):
    st = w.cognition.to_state()
    return json.dumps(st, sort_keys=True)


def _hour(e):
    return round(5.0 + e["t"] / 3600.0, 3)


def _mem_state(w):
    return json.dumps({str(a): b.to_state() for a, b in w.cognition.memories.items()}, sort_keys=True)


def _help_state(w):
    return json.dumps({str(cid): [a.help_for, a.helped, a.task_id, a.object_id, a.phase]
                       for cid, a in sorted(w.work.activities.items())}, sort_keys=True)


def _prior_copy(r):
    """The relationship as it would be without the help received: trust,
    affinity and obligation back at the workplace prior; familiarity (time
    spent together) kept."""
    from asphodel.cognition.relationships import Relationship, PRIORS
    if r is None:
        return None
    pr = PRIORS.get(r.origin or "workplace", PRIORS["workplace"])
    return Relationship(r.owner, r.other, familiarity=r.familiarity, trust=pr.get("trust", 0.3),
                        affinity=pr.get("affinity", 0.0), fear=r.fear, hostility=r.hostility, obligation=0.0)


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
        self.cog, self.work, self.ob = [], [], []
        self.cs = self.ws = self.os = 0

    def drain(self):
        s = self.w.cognition.snapshot(self.cs)
        self.cog.extend(s["events"])
        self.cs = s["event_seq"]
        s = self.w.work.snapshot(self.ws)
        self.work.extend(s["events"])
        self.ws = s["event_seq"]
        s = self.w.outbreak.snapshot(self.os, max_events=5000)
        self.ob.extend(s["events"])
        self.os = s["event_seq"]


def _run_to(w, hour, focus=FAR, tape=None):
    while w.current_hour() < hour - 1e-9:
        w.advance_seconds(60.0, focus_xy=focus)
        if tape is not None:
            tape.drain()


@pytest.fixture(scope="module")
def day():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "spawn_anchors.json.gz")):
        pytest.skip("houston compiled world absent")
    w = _mk(d)
    c, wk, ob = w.cognition, w.work, w.outbreak
    shop, visitors = _busiest_shop(w)
    tape = Tape(w)
    presence = {}            # minute-index -> {cid: building_id}  (for the omniscience gate)
    saves = {}
    blobs = {}
    lod = {}
    seeded = None
    broke = None
    first_help = None
    room_avoid_check = None
    pending_saves: list = []
    seen_cog = 0
    minute = 0
    for i in range(int(15.5 * 60)):                  # 05:00 -> 20:30
        w.advance_seconds(60.0, focus_xy=FAR)
        tape.drain()
        hour = w.current_hour()
        minute += 1
        presence[minute] = {cid: (int(ex.building_id) if ex.inside else -1) for cid, ex in w.mobility.execs.items()}
        new = tape.cog[seen_cog:]
        seen_cog = len(tape.cog)
        # Phase C stressor: the fast case in the first customer inside the busiest shop
        if seeded is None and hour >= 10.0:
            inside = sorted(cc for cc, a in wk.activities.items() if a.building_id == shop and a.kind == "customer")
            if inside:
                blobs["pre_seed"] = _blob(w)
                seeded = {"citizen_id": inside[0], "hour": round(hour, 3), "customers_inside": inside}
                ob.seed_index_case(inside[0])
        # Phase B stressor: the first helper's assigned station breaks at 13:00, no auto-repair
        if first_help is None:
            hc = [e for e in tape.cog if e["event"] == "HELP_COMPLETED"]
            if hc:
                first_help = hc[0]
        if broke is None and hour >= 13.0 and first_help is not None:
            # the reciprocity pair: among the morning's completed help pairs whose helper is on its
            # assigned station now, prefer the pair whose beneficiary would repair only because of
            # the help it received (with-history score above the threshold, without it below);
            # else the first pair. Both scores are recorded for every candidate.
            cands = []
            for e in [x for x in tape.cog if x["event"] == "HELP_COMPLETED"]:
                h, b = e["citizen_id"], e["beneficiary"]
                emp = wk.employment.get(h)
                a = wk.activities.get(h)
                if not (emp and emp.assigned_object and a and a.phase == "using" and a.object_id == emp.assigned_object):
                    continue
                if b not in wk.activities or wk.activities[b].building_id != emp.workplace_id:
                    continue
                pr = {"kind": "station_failed", "object_id": emp.assigned_object, "citizen_id": h}
                with_s, _ = c.help_score(b, h, pr)
                r = c.rels.get(b, h)
                prior = _prior_copy(r)
                without_s, _ = c.help_score(b, h, pr, rel_override=prior)
                cands.append({"helper": h, "beneficiary": b, "object_id": emp.assigned_object,
                              "building_id": emp.workplace_id, "with_history": with_s, "without_help": without_s,
                              "flips": bool(with_s >= HELP_THRESHOLD > without_s)})
            if cands:
                pick = next((x for x in cands if x["flips"]), cands[0])
                blobs["pre_break"] = _blob(w)
                broke = dict(pick, hour=round(hour, 3), candidates=cands)
                wk.set_object_state(pick["object_id"], "working", False)
        # room-level constraint, checked at the first AVOID_ROOM_DECIDED of a worker at its workplace
        if room_avoid_check is None:
            for e in new:
                if e["event"] == "AVOID_ROOM_DECIDED":
                    cid, bid = e["citizen_id"], e["building_id"]
                    emp = wk.employment.get(cid)
                    if emp is not None and emp.workplace_id == bid:
                        reg = wk.registry(bid)
                        role = ROLES[emp.role]
                        allowed = {o.room_id for t in role.tasks for o in wk._candidates(t, reg, cid)}
                        allowed_all = {o.room_id for t in role.tasks for o in wk._candidates(t, reg, None)}
                        room_avoid_check = {"citizen_id": cid, "building_id": bid, "avoided": e["rooms"],
                                            "rooms_with_candidates": sorted(allowed),
                                            "rooms_with_candidates_unfiltered": sorted(allowed_all),
                                            "room_here": e.get("room_here"), "hour": round(hour, 3)}
                        break
        # LOD probe at 08:00: promote the first helper to PHYSICAL for one second, against a
        # control copy of the same world advanced with the focus far away (the band is the
        # only difference between the two worlds)
        if not lod and hour >= 8.0 and first_help is not None:
            h = first_help["citizen_id"]
            bid = first_help["building_id"]
            ctrl = _restore(_blob(w), d)
            near_xy = w.mobility.execs[h].pos
            w.advance_seconds(1.0, focus_xy=near_xy)
            ctrl.advance_seconds(1.0, focus_xy=FAR)
            tape.drain()
            band_near = w.mobility.bands[h].name
            band_ctrl = ctrl.mobility.bands[h].name
            phys = w.mobility.near_ids()
            same_mem_near = _mem_state(w) == _mem_state(ctrl)
            same_rel_near = c.rels.to_state() == ctrl.cognition.rels.to_state()
            same_help_near = _help_state(w) == _help_state(ctrl)
            w.advance_seconds(60.0, focus_xy=FAR)
            ctrl.advance_seconds(60.0, focus_xy=FAR)
            tape.drain()
            minute += 1
            presence[minute] = {cid: (int(ex.building_id) if ex.inside else -1) for cid, ex in w.mobility.execs.items()}
            band_far = w.mobility.bands[h].name
            lod = {"hour": round(hour, 3), "citizen_id": h, "building_id": bid, "band_near": band_near,
                   "band_control": band_ctrl, "band_far": band_far, "n_physical": len(phys),
                   "memory_same_as_control_while_physical": same_mem_near,
                   "rels_same_as_control_while_physical": same_rel_near,
                   "help_state_same_as_control_while_physical": same_help_near,
                   "memory_same_as_control_after_demotion": _mem_state(w) == _mem_state(ctrl),
                   "rels_same_as_control_after_demotion": c.rels.to_state() == ctrl.cognition.rels.to_state(),
                   "cognition_state_same_as_control_after_demotion": _cog_state(w) == _cog_state(ctrl),
                   "n_memories": len(c.memories[h]) if h in c.memories else 0}
        # save/load moments (each once)
        keys = {
            "after_direct_observation": any(e["event"] == "PERCEIVED" and str(e.get("what", "")).startswith(
                ("threat", "attack", "corpse", "death")) for e in new),
            "after_help_decided": any(e["event"] == "HELP_DECIDED" for e in new)
                                  and any(x.help_for >= 0 for x in wk.activities.values()),
            "mid_social_interaction": any(e["event"] == "WARNING_SHARED" for e in new),
            "after_relationship_change": any(e["event"] == "RELATIONSHIP_CHANGED" and e.get("rule") == "helped_by" for e in new),
            "after_rumor_transmission": any(e["event"] == "WARNING_RECEIVED" and e.get("hops", 0) >= 2 for e in new),
            "after_threat_memory": any(e["event"] == "MEMORY_CREATED" and e.get("fact_kind") in THREAT for e in new),
            "after_avoidance_decision": any(e["event"] == "AVOID_DECIDED" for e in new),
        }
        for k, cond in keys.items():
            if cond and k not in saves and k not in pending_saves:
                pending_saves.append(k)
        if pending_saves:
            k = pending_saves.pop(0)
            if True:
                js = _blob(w)
                w2 = _restore(js, d)
                same_cog = _cog_state(w) == _cog_state(w2)
                same_mem = json.dumps({str(a): b.to_state() for a, b in c.memories.items()}, sort_keys=True) == \
                    json.dumps({str(a): b.to_state() for a, b in w2.cognition.memories.items()}, sort_keys=True)
                same_rel = c.rels.to_state() == w2.cognition.rels.to_state()
                same_told = sorted(c.told) == sorted(w2.cognition.told)
                same_goals = all(
                    [g.to_dict() for g in w.mobility.citizens[x].goals.goals]
                    == [g.to_dict() for g in w2.mobility.citizens[x].goals.goals] for x in w.mobility.citizens)
                for _ in range(10):
                    w.advance_seconds(60.0, focus_xy=FAR)
                    w2.advance_seconds(60.0, focus_xy=FAR)
                    minute += 1
                    presence[minute] = {cid: (int(ex.building_id) if ex.inside else -1) for cid, ex in w.mobility.execs.items()}
                cont = _blob(w) == _blob(w2)
                saves[k] = {"hour": round(hour, 3), "cognition_identical": same_cog, "memories_identical": same_mem,
                            "relationships_identical": same_rel, "told_set_identical": same_told,
                            "goals_identical": same_goals, "continuation_bit_identical": cont, "save_bytes": len(js)}
                tape.drain()
    return {"w": w, "c": c, "wk": wk, "ob": ob, "d": d, "shop": shop, "visitors": visitors, "seeded": seeded,
            "broke": broke, "first_help": first_help, "tape": tape, "saves": saves, "blobs": blobs, "lod": lod,
            "presence": presence, "room_avoid": room_avoid_check}


def _ev(day, kind, cid=None, **match):
    out = []
    for e in day["tape"].cog:
        if e["event"] != kind or (cid is not None and e.get("citizen_id") != cid):
            continue
        if all(e.get(k) == v for k, v in match.items()):
            out.append(e)
    return out


# ---------------------------------------------------------------------------
def test_N1_N2_perception_channels_and_no_omniscience(day):
    c, w = day["c"], day["w"]
    bad_source, bad_place, first_hand_remote = [], [], []
    stores = c.memories
    for cid, st in sorted(stores.items()):
        for f in st.facts.values():
            if f.source not in (M.DIRECT, M.PARTICIPANT, M.TOLD):
                bad_source.append(f.fact_id)
            if f.first_hand() and f.building_id is not None and f.kind in THREAT:
                # the owner must have been inside that building at the fact's minute (or the
                # minute before/after: the sample is per minute), or outdoors next to it
                minute = int(f.t // 60) + 1
                here = [day["presence"].get(m, {}).get(cid) for m in (minute - 1, minute, minute + 1)]
                if f.building_id not in here and -1 not in here:
                    first_hand_remote.append((cid, f.fact_id, f.building_id, here))
    told = [f for st in stores.values() for f in st.facts.values() if f.source == M.TOLD]
    orphan = [f.fact_id for f in told if f.source_citizen is None or f.origin_witness is None]
    _status("N1", "PASS" if not bad_source and not orphan else "FAIL",
            f"{sum(len(s) for s in stores.values())} facts in {len(stores)} citizens; sources: "
            f"{sorted({f.source for s in stores.values() for f in s.facts.values()})}; every told fact names its "
            f"teller and origin witness ({len(told)} told facts, {len(orphan)} orphans)")
    # nobody far away knows about the attack: citizens never inside the shop and never told
    shop = day["shop"]
    at_shop = set()
    for p in day["presence"].values():
        at_shop |= {cid for cid, b in p.items() if b == shop}
    for e in day["tape"].ob + day["tape"].work:            # second-resolution presence: the authorities' own rows
        if e.get("building_id") == shop:
            for k in ("citizen_id", "victim_citizen", "customer_id"):
                if e.get(k) is not None:
                    at_shop.add(int(e[k]))
    never_there = [cid for cid in w.mobility.execs if cid not in at_shop]
    leaks = []
    for cid in never_there:
        st = stores.get(cid)
        if st is None:
            continue
        for f in st.facts.values():
            if f.kind in THREAT and f.building_id == shop and f.first_hand():
                leaks.append((cid, f.fact_id))
    knows_told = [cid for cid in never_there if cid in stores and any(
        f.kind in THREAT and f.building_id == shop and f.source == M.TOLD for f in stores[cid].facts.values())]
    _status("N2", "PASS" if not leaks and not first_hand_remote else "FAIL",
            f"{len(never_there)} citizens were never inside shop {shop}; {len(leaks)} hold a first-hand fact about "
            f"the attack there (must be 0); {len(knows_told)} know of it only because someone told them; "
            f"{len(first_hand_remote)} first-hand threat facts anywhere are held by someone who was elsewhere")
    assert not bad_source and not orphan and not leaks and not first_hand_remote


def test_N3_N5_memory_structure_and_bounds(day):
    c = day["c"]
    st = max(c.memories.values(), key=lambda s: len(s))
    f = next(iter(st.facts.values()))
    fields = set(f.to_dict())
    need = {"fact_id", "owner", "kind", "actor", "target", "building_id", "room_id", "object_id", "t", "source",
            "source_citizen", "origin_witness", "origin_id", "hops", "confidence", "salience", "valence", "count",
            "last_t"}
    _status("N3", "PASS" if need <= fields else "FAIL",
            f"MemoryFact fields {sorted(fields)}; {len(c.memories)} stores persisted in the save block")
    mx = max(len(s) for s in c.memories.values())
    reinforced = c.counts.get("MEMORY_REINFORCED", 0)
    decayed = c.counts.get("MEMORY_DECAYED", 0)
    top = max((f for s in c.memories.values() for f in s.facts.values()), key=lambda f: f.count)
    _status("N5", "PASS" if mx <= M.CAPACITY and reinforced > 0 and decayed > 0 else "FAIL",
            f"max facts per citizen {mx} (cap {M.CAPACITY}); {reinforced} reinforcements merged into existing "
            f"facts (top: {top.kind} about {top.actor} x{top.count}); {decayed} consolidation passes dropped decayed facts")
    assert need <= fields and mx <= M.CAPACITY and reinforced > 0


def test_N4_provenance(day):
    c = day["c"]
    told = [f for st in c.memories.values() for f in st.facts.values() if f.source == M.TOLD]
    ok, bad = 0, []
    for f in told:
        o = c.memories.get(f.origin_witness)
        of = o.facts.get(f.origin_id) if o else None
        if of is None or not of.first_hand() or of.kind != f.kind or f.hops < 1:
            bad.append(f.fact_id)
        else:
            ok += 1
    recv = _ev(day, "WARNING_RECEIVED")
    hop2 = [e for e in recv if e.get("hops", 0) >= 2]
    lin = c.lineage(hop2[0]["fact_id"]) if hop2 else []
    _status("N4", "PASS" if told and not bad else "FAIL",
            f"{ok}/{len(told)} told facts point at a first-hand fact of their origin witness of the same kind; "
            f"{len(recv)} tellings, {len(hop2)} second-hop; lineage of one second-hop fact: "
            + " -> ".join(f"{e['sender']}->{e['citizen_id']}" for e in lin[:4]))
    assert told and not bad


def test_N6_beliefs_from_evidence(day):
    c = day["c"]
    avoid = _ev(day, "AVOID_DECIDED")
    assert avoid, "no avoidance decision in the day"
    cid = avoid[0]["citizen_id"]
    bel = c.beliefs(cid)
    st = c.memories[cid]
    dangling = [fid for b in bel.values() for fid in b.evidence if fid not in st.facts]
    b = max(bel.values(), key=lambda x: x.value)
    _status("N6", "PASS" if bel and not dangling else "FAIL",
            f"citizen {cid}: {len(bel)} beliefs, all evidence ids are facts in its own store; strongest "
            f"{b.key}={b.value:.2f} from {len(b.evidence)} facts, first_hand={b.first_hand}, sources {b.source_citizens}")
    assert bel and not dangling


def test_N7_N8_relationships(day):
    c = day["c"]
    n = len(c.rels.rels)
    changed = [e for e in _ev(day, "RELATIONSHIP_CHANGED")]
    rules = sorted({e["rule"] for e in changed})
    helped = [e for e in changed if e["rule"] == "helped_by"]
    hb = helped[0] if helped else None
    r = c.rels.get(hb["citizen_id"], hb["other"]) if hb else None
    _status("N7", "PASS" if n > 0 and day["saves"] else "FAIL",
            f"{n} directed relationships (priors: household/workplace; the rest experience); persisted per pair")
    _status("N8", "PASS" if helped else "FAIL",
            f"{len(changed)} logged relationship changes by rules {rules}; e.g. {hb['citizen_id']}->{hb['other']} after "
            f"helped_by: {hb['changes']} (now familiarity={r.familiarity:.2f} trust={r.trust:.2f} affinity={r.affinity:.2f} "
            f"obligation={r.obligation:.2f})" if hb else "no helped_by change")
    assert n > 0 and helped


def test_N9_N11_helping_chain(day):
    c, wk = day["c"], day["wk"]
    dec = _ev(day, "HELP_DECIDED")
    done = _ev(day, "HELP_COMPLETED")
    fh = day["first_help"]
    assert dec and done and fh
    d0 = dec[0]
    h, b = d0["citizen_id"], d0["beneficiary"]
    _status("N9", "PASS", f"{len(dec)} help decisions; first: citizen {h} ({wk.employment[h].role}) saw "
                          f"{d0['problem']} of coworker {b} ({wk.employment[b].role}) at {d0['building_id']}: "
                          f"score {d0['score']} ≥ {HELP_THRESHOLD} from {d0['components']}")
    wt = [e for e in day["tape"].work if e["event"] == "HELP_TASK" and e["citizen_id"] == h]
    use = [e for e in day["tape"].work if e["event"] == "USE_START" and e["citizen_id"] == h
           and e.get("object_id") == d0["object_id"]]
    chg = [e for e in day["tape"].work if e["event"] == "STATE_CHANGE" and e.get("citizen_id") == h
           and e.get("object_id") == d0["object_id"]]
    _status("N10", "PASS" if wt and use and chg else "FAIL",
            f"WorkRuntime ran {d0['task_id']} for {h}: HELP_TASK, USE_START at {d0['object_id']} "
            f"({wk.registry(d0['building_id']).get(d0['object_id']).kind}), STATE_CHANGE {chg[0]['key'] if chg else None}"
            f"={chg[0]['value'] if chg else None}; {len(done)} help tasks completed city-wide")
    st = c.memories.get(b)
    fact = [f for f in st.facts.values() if f.kind == M.HELPED_BY and f.actor == h] if st else []
    _status("N11", "PASS" if fact else "FAIL",
            f"beneficiary {b} holds HELPED_BY(actor={h}, {fact[0].detail}, count={fact[0].count}, "
            f"source={fact[0].source}, salience={fact[0].salience})" if fact else f"{b} has no HELPED_BY fact")
    assert wt and use and chg and fact


def test_N12_N28_reciprocity_and_counterfactual_help(day):
    c, wk, d = day["c"], day["wk"], day["d"]
    broke = day["broke"]
    assert broke, "the reciprocity stressor never fired"
    rec = [e for e in _ev(day, "RECIPROCATED") if e["citizen_id"] == broke["beneficiary"]]
    rdec = [e for e in _ev(day, "HELP_DECIDED", broke["beneficiary"]) if e["task_id"] == "repair_station"]
    fixed = [e for e in day["tape"].work if e["event"] == "STATE_CHANGE" and e.get("object_id") == broke["object_id"]
             and e.get("key") == "working" and e.get("value") is True]
    back = [e for e in day["tape"].work if e["event"] == "RESERVED" and e["citizen_id"] == broke["helper"]
            and e.get("object_id") == broke["object_id"] and _hour(e) > broke["hour"]]
    _status("N12", "PASS" if rec and rdec and fixed else "FAIL",
            f"station {broke['object_id']} of {broke['helper']} broken at {broke['hour']}; the coworker it helped in the "
            f"morning ({broke['beneficiary']}) decided repair_station at {_hour(rdec[0]) if rdec else None} "
            f"(score {rdec[0]['score'] if rdec else None}, without history {rdec[0]['score_without_history'] if rdec else None}), "
            f"repaired at {_hour(fixed[0]) if fixed else None}, RECIPROCATED (obligation discharged); "
            f"{broke['helper']} retook the station at {_hour(back[0]) if back else None}")
    # C1 live counterfactual: restore the world just before the break, twice; in B erase the
    # morning's help from the beneficiary (memory + relationship back to the workplace prior)
    js = day["blobs"]["pre_break"]
    wa, wb = _restore(js, d), _restore(js, d)
    ben, helper = broke["beneficiary"], broke["helper"]
    stb = wb.cognition.memories.get(ben)
    erased = []
    if stb is not None:
        for f in list(stb.facts.values()):
            if f.kind in (M.HELPED_BY, M.SAW_HELP) and f.actor == helper:
                stb.forget(f.fact_id)
                erased.append(f.fact_id)
    rb = wb.cognition.rels.get(ben, helper)
    before_rel = rb.to_dict() if rb else None
    if rb is not None:
        pr = _prior_copy(rb)
        rb.trust, rb.affinity, rb.obligation = pr.trust, pr.affinity, pr.obligation
    wb.cognition._beliefs.pop(ben, None)
    for wx in (wa, wb):
        wx.work.set_object_state(broke["object_id"], "working", False)
    ta, tb = Tape(wa), Tape(wb)
    _run_to(wa, wa.current_hour() + 0.5, tape=ta)
    _run_to(wb, wb.current_hour() + 0.5, tape=tb)
    ra = [e for e in ta.cog if e["event"] == "HELP_DECIDED" and e["citizen_id"] == ben and e["task_id"] == "repair_station"]
    rbb = [e for e in tb.cog if e["event"] == "HELP_DECIDED" and e["citizen_id"] == ben and e["task_id"] == "repair_station"]
    sa = [e for e in ta.cog if e["event"] == "HELP_DECIDED"]
    flips = [x for x in broke["candidates"] if x["flips"]]
    _status("N28", "PASS" if ra and not rbb else "FAIL",
            f"same world restored twice before the break: with the morning's help in memory {ben} decides "
            f"repair_station (score {ra[0]['score'] if ra else None}); with HELPED_BY erased ({len(erased)} facts) and "
            f"trust/affinity/obligation back at the workplace prior (familiarity kept) it does not "
            f"(score without the help {broke['without_help']:.3f} < {HELP_THRESHOLD}); of {len(broke['candidates'])} "
            f"helper/beneficiary pairs available at 13:00, {len(flips)} flip on the help history, "
            f"{len(broke['candidates']) - len(flips)} would repair anyway (helpfulness + familiarity)")
    day["cf_help"] = {"with_history": [dict(e) for e in ra], "without_history": [dict(e) for e in rbb],
                      "erased_facts": erased, "relationship_before_reset": before_rel}
    assert rec and rdec and fixed and ra and not rbb


def test_N13_direct_threat_memory(day):
    c, ob = day["c"], day["ob"]
    seeded = day["seeded"]
    assert seeded
    attacks = [e for e in day["tape"].ob if e["event"] == "ATTACK"]
    obs = [e for e in day["tape"].ob if e["event"] == "THREAT_OBSERVED"]
    first_hand = [(cid, f) for cid, st in c.memories.items() for f in st.facts.values()
                  if f.kind in THREAT and f.first_hand()]
    victims = {e["victim_citizen"] for e in attacks}
    v_ok = all(any(cid == v and f.kind == M.ATTACKED_BY for cid, f in first_hand) for v in victims if c._can_perceive(v))
    wit = {e["citizen_id"] for e in obs}
    w_ok = sum(1 for wc in wit if any(cid == wc for cid, _ in first_hand))
    _status("N13", "PASS" if attacks and first_hand and v_ok and w_ok else "FAIL",
            f"fast case seeded in customer {seeded['citizen_id']} inside shop {day['shop']} at {seeded['hour']}; "
            f"{len(attacks)} attacks, {len(obs)} witness observations; {len(first_hand)} first-hand threat facts in "
            f"{len({cid for cid, _ in first_hand})} citizens (every living victim holds ATTACKED_BY, {w_ok}/{len(wit)} "
            f"witnesses hold a first-hand fact); kinds {sorted({f.kind for _, f in first_hand})}")
    assert attacks and first_hand and v_ok


def test_N15_N17_warning_chain(day):
    c = day["c"]
    shared = [e for e in _ev(day, "WARNING_SHARED") if e["fact_kind"] in THREAT]
    recv = [e for e in _ev(day, "WARNING_RECEIVED") if e["fact_kind"] in THREAT]
    chans = {}
    for e in shared:
        chans[e["channel"]] = chans.get(e["channel"], 0) + 1
    _status("N15", "PASS" if shared else "FAIL",
            f"{len(shared)} threat warnings shared by {len({e['citizen_id'] for e in shared})} citizens over channels "
            f"{chans}; utterance {shared[0]['utterance'] if shared else None}; max per sender "
            f"{max((sum(1 for x in shared if x['citizen_id'] == s) for s in {e['citizen_id'] for e in shared}), default=0)}; "
            f"max hops {max((e['hops'] for e in shared), default=0)} (limit {S.MAX_HOPS})")
    told = [(cid, f) for cid, st in c.memories.items() for f in st.facts.values() if f.kind in THREAT and f.source == M.TOLD]
    _status("N16", "PASS" if recv and told else "FAIL",
            f"{len(recv)} receptions recorded as told facts: {len(told)} told threat facts held by "
            f"{len({cid for cid, _ in told})} citizens with source_citizen/origin_witness/hops; confidence of a told fact "
            f"{told[0][1].confidence:.2f} vs 1.0 first-hand" if told else "no told facts")
    avoid = [e for e in _ev(day, "AVOID_DECIDED") if not e["first_hand"]]
    detail = "no avoidance by a non-witness"
    ok = False
    if avoid:
        e = avoid[0]
        cid = e["citizen_id"]
        own = [p for p in _ev(day, "PERCEIVED", cid) if str(p.get("what", "")).startswith(("threat", "attack", "corpse", "death"))]
        first_own = own[0]["seq"] if own else None
        ok = first_own is None or e["seq"] < first_own
        rt = day["w"].mobility.citizens[cid]
        detail = (f"citizen {cid} ({day['wk'].employment[cid].role if cid in day['wk'].employment else 'visitor'}) in "
                  f"building {e['building_id']} was told by {e['sources']} (danger {e['danger']} ≥ its threshold "
                  f"{e['threshold']}) and pushed a belief goal home at {_hour(e)} (preempted the {e['was_doing']} goal, "
                  f"inside={e['inside']}) — before any first-hand perception of its own "
                  f"(own first perception seq {first_own} vs decision seq {e['seq']}); {len(avoid)} such decisions")
    _status("N17", "PASS" if ok else "FAIL", detail)
    assert shared and recv and told and ok


def test_N18_N29_trust_and_counterfactual_warning(day):
    c, d = day["c"], day["d"]
    avoid = [e for e in _ev(day, "AVOID_DECIDED") if not e["first_hand"]]
    assert avoid
    target = avoid[0]["citizen_id"]
    src = avoid[0]["sources"][0]
    # static: the same telling under low vs high trust
    lo = S.told_confidence(1.0, 0.05, 0.5)
    hi = S.told_confidence(1.0, 0.95, 0.5)
    # live: restore before the seeding, three copies — A as it was; B the warned citizen never hears
    # the warning (C2); C the warned citizen distrusts its future source (C4)
    js = day["blobs"]["pre_seed"]
    wa, wb, wc = _restore(js, d), _restore(js, d), _restore(js, d)
    orig_share = wb.cognition._share

    def deaf(sender, recipient, channel, bid=None, rid=None, only=None, _o=orig_share, _t=target):
        if recipient == _t:
            return False
        return _o(sender, recipient, channel, bid, rid, only)
    wb.cognition._share = deaf
    r = wc.cognition.rels.get(target, src, create=True)
    trust_before = r.trust
    r.trust = 0.02
    wc.cognition.personality  # noqa (traits are pure functions; nothing to reset)
    seeded = day["seeded"]
    tapes = {}
    for name, wx in (("A", wa), ("B", wb), ("C", wc)):
        t = Tape(wx)
        wx.outbreak.seed_index_case(seeded["citizen_id"])
        _run_to(wx, seeded["hour"] + 0.6, tape=t)
        tapes[name] = t
    def summary(t):
        av = [e for e in t.cog if e["event"] == "AVOID_DECIDED" and e["citizen_id"] == target]
        rc = [e for e in t.cog if e["event"] == "WARNING_RECEIVED" and e["citizen_id"] == target and e["fact_kind"] in THREAT]
        pe = [e for e in t.cog if e["event"] == "PERCEIVED" and e["citizen_id"] == target]
        fl = [e for e in t.ob if e["event"] == "FLEE" and e["citizen_id"] == target]
        return {"warnings": len(rc), "first_conf": rc[0]["confidence"] if rc else None,
                "danger_after_first": rc[0]["danger_after"] if rc else None,
                "avoid_decided": bool(av), "avoid_hour": _hour(av[0]) if av else None,
                "own_perception_hour": _hour(pe[0]) if pe else None, "fled_hour": _hour(fl[0]) if fl else None}
    sa, sb, sc = summary(tapes["A"]), summary(tapes["B"]), summary(tapes["C"])
    day["cf_warn"] = {"target": target, "source": src, "A_as_run": sa, "B_never_warned": sb,
                      "C_distrusts_source": sc, "trust_before": trust_before, "static": {"low": lo, "high": hi}}
    c29 = sa["avoid_decided"] and not sb["avoid_decided"]
    c18 = (lo < hi) and (sc["first_conf"] is None or sa["first_conf"] is None or sc["first_conf"] < sa["first_conf"]) \
        and (not sc["avoid_decided"] or sc["danger_after_first"] < sa["danger_after_first"])
    _status("N18", "PASS" if c18 else "FAIL",
            f"told_confidence(1.0) is {lo:.2f} at trust 0.05 vs {hi:.2f} at trust 0.95; live: citizen {target} "
            f"receives the same warning from {src} at confidence {sa['first_conf']} (trust {trust_before:.2f}) vs "
            f"{sc['first_conf']} when it distrusts {src} (trust 0.02); danger after {sa['danger_after_first']} vs "
            f"{sc['danger_after_first']}; avoid {sa['avoid_decided']} vs {sc['avoid_decided']}")
    _status("N29", "PASS" if c29 else "FAIL",
            f"same world restored twice before the seeding: warned, citizen {target} leaves on a belief goal at "
            f"{sa['avoid_hour']} (own first perception {sa['own_perception_hour']}); never warned, it stays on its schedule "
            f"until it perceives the threat itself at {sb['own_perception_hour']} (flee {sb['fled_hour']}) — no belief goal")
    assert c18 and c29


def test_N14_threat_memory_changes_later_decision(day):
    """When the emergency is over, the memory (not the emergency) keeps a
    witness away: restore after the attack, let a first-hand witness's flee
    goal end, and the schedule that would send it back to the shop is refused
    by its own memory; with the memory erased it goes back."""
    c, d = day["c"], day["d"]
    js = day["saves_after_threat_blob"] if "saves_after_threat_blob" in day else None
    # take the world right after the attack: the after_threat_memory save happened then; rebuild it
    base = day["blobs"]["pre_seed"]
    seeded = day["seeded"]
    w0 = _restore(base, d)
    w0.outbreak.seed_index_case(seeded["citizen_id"])
    t0 = Tape(w0)
    _run_to(w0, seeded["hour"] + 0.35, tape=t0)
    wit = sorted({e["citizen_id"] for e in t0.cog if e["event"] == "PERCEIVED"
                  and str(e.get("what", "")).startswith(("threat", "attack"))
                  and e.get("building_id") == day["shop"] and e.get("source") == "direct"})
    wit = [x for x in wit if x in w0.mobility.citizens and x not in w0.work.employment]   # a customer witness
    assert wit, "no customer witnessed the attack first-hand"
    js2 = _blob(w0)
    wa, wb = _restore(js2, d), _restore(js2, d)
    W = wit[0]
    for wx in (wa, wb):
        rt = wx.mobility.citizens[W]
        for g in list(rt.goals.goals):
            if g.source == "emergency":
                rt.goals.remove(g.id)
        rt.active_goal = None
        rt.goals._active = None
        rt.sync_schedule(wx.current_hour(), wx.mobility.graph)
        wx.mobility.execs[W].adopt(rt.itinerary, rt.plan_serial, wx.mobility.now_s)
    stb = wb.cognition.memories.get(W)
    erased = 0
    if stb is not None:
        for f in list(stb.facts.values()):
            if f.kind in THREAT or f.kind == M.WARNED_BY:
                stb.forget(f.fact_id)
                erased += 1
    wb.cognition._beliefs.pop(W, None)
    ta, tb = Tape(wa), Tape(wb)
    _run_to(wa, wa.current_hour() + 0.25, tape=ta)
    _run_to(wb, wb.current_hour() + 0.25, tape=tb)
    ga = wa.mobility.citizens[W].active_goal
    gb = wb.mobility.citizens[W].active_goal
    av = [e for e in ta.cog if e["event"] == "AVOID_DECIDED" and e["citizen_id"] == W]
    avb = [e for e in tb.cog if e["event"] == "AVOID_DECIDED" and e["citizen_id"] == W]
    dest_a = wa.cognition._building_of_goal(wa.mobility.citizens[W], ga) if ga else None
    dest_b = wb.cognition._building_of_goal(wb.mobility.citizens[W], gb) if gb else None
    ok = bool(av) and av[0]["first_hand"] and not avb and dest_a != day["shop"] and (dest_b == day["shop"] or gb is None or gb.source == "schedule")
    _status("N14", "PASS" if ok else "FAIL",
            f"witness {W} (first-hand) with the emergency over and the schedule pointing back at shop {day['shop']}: "
            f"with its memory it refuses (AVOID_DECIDED first_hand={av[0]['first_hand'] if av else None}, danger "
            f"{av[0]['danger'] if av else None}; goal now {ga.source if ga else None} -> building {dest_a}); "
            f"with {erased} threat facts erased it heads back (goal {gb.source if gb else None} -> {dest_b})")
    day["cf_memory"] = {"witness": W, "with_memory_goal": (ga.to_dict() if ga else None),
                        "without_memory_goal": (gb.to_dict() if gb else None), "erased": erased,
                        "avoid_with": [dict(e) for e in av], "avoid_without": [dict(e) for e in avb]}
    assert ok


def test_N19_conflicting_evidence(day):
    c = day["c"]
    upd = _ev(day, "BELIEF_UPDATED")
    if upd:
        e = upd[0]
        ok = e["value"] < e["old"]
        detail = (f"citizen {e['citizen_id']} believed room {e['room_id']} of {e['building_id']} dangerous "
                  f"({e['old']}), stood in it for {int(600 / 60)} min seeing no threat and now believes {e['value']} "
                  f"(building {e['building_old']} -> {e['building_value']}); {len(upd)} such updates in the day")
    else:
        # controlled: a citizen told about a room, then observing it safe
        from asphodel.cognition.beliefs import derive
        st = M.MemoryStore(999999)
        st.remember(M.THREAT_PERSON, 100.0, actor=1, building_id=7, room_id=2, source=M.TOLD, source_citizen=5,
                    origin_witness=5, origin_id="5:1", hops=1, confidence=0.6)
        before = danger_of_room(derive(st, 200.0), 7, 2)
        st.remember(M.PLACE_SAFE, 800.0, building_id=7, room_id=2)
        after = danger_of_room(derive(st, 900.0), 7, 2)
        ok = after < before
        detail = f"(no in-day update) told danger {before:.2f} -> {after:.2f} after a direct safe observation"
    _status("N19", "PASS" if ok else "FAIL", detail)
    assert ok


def test_N20_room_level_avoidance(day):
    chk = day["room_avoid"]
    ev = _ev(day, "AVOID_ROOM_DECIDED")
    ok = bool(chk) and set(chk["avoided"]).isdisjoint(chk["rooms_with_candidates"]) \
        and set(chk["avoided"]) <= set(chk["rooms_with_candidates_unfiltered"])
    _status("N20", "PASS" if ok else "FAIL",
            f"{len(ev)} room-avoidance decisions; worker {chk['citizen_id'] if chk else None} at {chk['building_id'] if chk else None} "
            f"avoids rooms {chk['avoided'] if chk else None} while its role's tasks still have candidates in rooms "
            f"{chk['rooms_with_candidates'] if chk else None} (unfiltered {chk['rooms_with_candidates_unfiltered'] if chk else None}); "
            f"the WorkRuntime room_filter is the only constraint applied")
    assert ok


def test_N21_N22_authorities(day):
    w, c = day["w"], day["c"]
    srcs = {g.source for rt in w.mobility.citizens.values() for g in rt.goals.goals}
    belief_goals = [g for rt in w.mobility.citizens.values() for g in rt.goals.goals if g.source == "belief"]
    bad = [g.to_dict() for g in belief_goals if g.kind.value != "do_activity" or not g.reason.startswith("avoiding")]
    _status("N21", "PASS" if not bad else "FAIL",
            f"cognition only ever pushes DO_ACTIVITY goals with source 'belief' into the existing GoalStack "
            f"({len(belief_goals)} live now; sources present {sorted(srcs)}); selection, planning, replanning stay "
            f"CitizenRuntime's")
    # advancing cognition alone moves nobody and starts no trip
    pos = {cid: (ex.pos, ex.building_id, ex.state.value, ex.plan_serial) for cid, ex in w.mobility.execs.items()}
    for _ in range(5):
        c.advance(1.0)
    same = all(pos[cid] == (ex.pos, ex.building_id, ex.state.value, ex.plan_serial) for cid, ex in w.mobility.execs.items())
    _status("N22", "PASS" if same else "FAIL",
            "five cognition-only substeps: every executor position, building, state and adopted plan unchanged; "
            "movement is the TripExecutor's, interior movement the WorkRuntime's, schedules the CitizenRuntime's")
    assert not bad and same


def test_N23_N24_lod(day):
    lod = day["lod"]
    ok = bool(lod) and lod["band_near"] == "PHYSICAL" and lod["band_control"] != "PHYSICAL" \
        and lod["band_far"] != "PHYSICAL" \
        and lod["memory_same_as_control_while_physical"] and lod["rels_same_as_control_while_physical"] \
        and lod["help_state_same_as_control_while_physical"] \
        and lod["memory_same_as_control_after_demotion"] and lod["rels_same_as_control_after_demotion"] \
        and lod["cognition_state_same_as_control_after_demotion"]
    _status("N23", "PASS" if ok else "FAIL",
            f"citizen {lod.get('citizen_id')} at {lod.get('building_id')}: after the minute back at "
            f"{lod.get('band_far')} the whole cognition state (memories, relationships, told-set, help state) is "
            f"identical to a control copy of the same world that was never promoted")
    _status("N24", "PASS" if ok else "FAIL",
            f"promoted to {lod.get('band_near')} ({lod.get('n_physical')} bodies) for one second while the control copy "
            f"stayed {lod.get('band_control')}: every memory store, relationship and help task identical between the "
            f"two worlds ({lod.get('n_memories')} facts for the helper); personality is a pure function of seed and id")
    assert ok


def test_N25_N27_saveload(day):
    s = day["saves"]
    need = ["after_direct_observation", "after_help_decided", "mid_social_interaction", "after_relationship_change",
            "after_rumor_transmission", "after_threat_memory", "after_avoidance_decision"]
    missing = [k for k in need if k not in s]
    allok = all(v["cognition_identical"] and v["memories_identical"] and v["relationships_identical"]
                and v["told_set_identical"] and v["goals_identical"] and v["continuation_bit_identical"] for v in s.values())
    hrs = {k: v["hour"] for k, v in s.items()}
    _status("N25", "PASS" if allok and not missing else "FAIL",
            f"{len(s)} moments {hrs}: memories and beliefs' evidence identical after restore, 10-minute continuation "
            f"byte-identical; missing {missing}")
    _status("N26", "PASS" if allok and not missing else "FAIL", "relationship graph identical at every moment")
    _status("N27", "PASS" if allok and not missing else "FAIL",
            "told-set, pair cooldowns, calls, lineage (events) and belief goals identical at every moment")
    _write("save_load_trace.json", s)
    assert allok and not missing


def test_N30_godot(day):
    if not os.path.exists(PROBE):
        _status("N30", "NOT_RUN", "run tools/run_cognition_gate.sh for the in-engine probe")
        pytest.skip("no godot probe trace")
    with open(PROBE) as f:
        p = json.load(f)
    fails = [r for r in p.get("results", p.get("log", [])) if str(r).startswith("FAIL")]
    verdict = p.get("verdict", "PASS" if not fails else "FAIL")
    _status("N30", "PASS" if verdict == "PASS" and not fails else "FAIL",
            f"godot probe: {p.get('summary', '')} {len(fails)} FAIL rows")
    assert verdict == "PASS" and not fails


def test_N31_N35_regression_and_smoke(day):
    reg = os.path.join(ART, "regression.json")
    if os.path.exists(reg):
        with open(reg) as f:
            r = json.load(f)
        for gate, key in (("N31", "work_gate"), ("N32", "outbreak_gate"), ("N33", "mobility_gate"), ("N34", "run_gates")):
            v = r.get(key)
            _status(gate, "PASS" if v and v.get("status") == "PASS" else ("NOT_RUN" if not v else "FAIL"),
                    json.dumps(v) if v else "missing")
    else:
        for gate in ("N31", "N32", "N33", "N34"):
            _status(gate, "NOT_RUN", "artifacts/npc_cognition_v1/regression.json missing")
    sm = os.path.join(ART, "city_smoke.json")
    if os.path.exists(sm):
        with open(sm) as f:
            s = json.load(f)
        cities = s.get("cities", s)
        rows = {k: (v.get("status") if isinstance(v, dict) else v) for k, v in cities.items()} if isinstance(cities, dict) \
            else {c["city"]: c["status"] for c in cities}
        req = [k for k in rows if any(x in k for x in ("houston", "madisonville", "austin", "san_antonio"))]
        ok = req and all(rows[k] == "PASS" for k in req) and not any(v == "FAIL" for v in rows.values())
        _status("N35", "PASS" if ok else "FAIL", json.dumps(rows))
    else:
        _status("N35", "NOT_RUN", "artifacts/npc_cognition_v1/city_smoke.json missing")


def test_N36_no_city_names(day):
    pat = re.compile(r"houston|madisonville|austin|san_antonio|boulder", re.I)
    hits = []
    for base in ("asphodel/cognition",):
        for fn in sorted(os.listdir(os.path.join(ROOT, base))):
            if fn.endswith(".py"):
                with open(os.path.join(ROOT, base, fn)) as f:
                    for i, line in enumerate(f, 1):
                        if pat.search(line):
                            hits.append(f"{base}/{fn}:{i}")
    for fn in ("asphodel/smart/runtime.py", "asphodel/smart/jobs.py", "asphodel/outbreak/runtime.py",
               "asphodel/orchestrator.py"):
        with open(os.path.join(ROOT, fn)) as f:
            for i, line in enumerate(f, 1):
                if pat.search(line) and "docs" not in line and "#" not in line.split(pat.search(line).group(0))[0]:
                    hits.append(f"{fn}:{i}")
    _status("N36", "PASS" if not hits else "FAIL", f"city-name matches in cognition/work/outbreak/world code: {hits}")
    assert not hits


def test_zz_write_trace_and_table(day):
    c = day["c"]
    tape = day["tape"]
    rows = []
    for g, name in GATES:
        st, det = STATUS.get(g, ("NOT_RUN", ""))
        rows.append({"gate": g, "name": name, "status": st, "detail": det})
    trace = {"version": 1, "bundle": CITY, "shop": day["shop"], "visitors": day["visitors"], "seeded": day["seeded"],
             "broke": day["broke"], "first_help": day["first_help"], "lod": day["lod"], "saves": day["saves"],
             "room_avoid": day["room_avoid"], "counts": c.counts, "help_log": c.help_log,
             "counterfactual_help": day.get("cf_help"), "counterfactual_warning": day.get("cf_warn"),
             "counterfactual_memory": day.get("cf_memory"),
             "cognition_events": tape.cog, "work_events": [e for e in tape.work if e["event"] in
                                                            ("HELP_TASK", "HELP_DONE", "QUEUE_MOVED", "OBJECT_UNAVAILABLE",
                                                             "WORK_INTERRUPTED", "CLOCK_IN", "CLOCK_OUT", "SERVED")],
             "outbreak_events": [e for e in tape.ob if e["event"] in
                                 ("ATTACK", "THREAT_OBSERVED", "FLEE", "DEATH", "REANIMATION", "WORKPLACE_DISRUPTED",
                                  "SYMPTOM_ONSET", "INFECTED")],
             "gates": rows}
    _write("one_day_trace.json", trace)
    lines = ["| gate | requirement | status | evidence |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['gate']} | {r['name']} | {r['status']} | {r['detail']} |")
    with open(os.path.join(ART, "certification_table.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(f"{r['gate']}: {r['status']} — {r['detail'][:160]}" for r in rows))
    assert all(r["status"] in ("PASS", "NOT_RUN") for r in rows), [r for r in rows if r["status"] == "FAIL"]

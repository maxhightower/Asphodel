"""The social layer against a real Houston day
(ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §11-§16, §20-§23).

One world, 05:00 -> 11:00, with a case of ``classic_zombie_fast`` seeded into
the first customer standing inside the busiest shop (15873) at about 10:35.
That citizen rises a few minutes later and attacks in room 0 while a cashier
is working in room 1 and a night worker is asleep across town.

What that day has to prove:

* **N1 / N2 (no omniscience)** — every threat fact a citizen holds was either
  perceived by that citizen (a PERCEIVED row of its own) or told to it by a
  named sender who held the same origin fact earlier (a WARNING_RECEIVED row
  with the lineage on it). Nobody who was never inside the shop holds a
  first-hand memory of what happened there, and no memory names a building
  its owner was never in and was never told about.
* **N4** — told facts carry origin_witness (a first-hand holder), hops >= 1
  and the teller.
* **N15 / N16** — warnings are real acts: a SHARED/RECEIVED pair about a
  threat kind, with the utterance labels.
* **N17** — the cashier in room 1 acts on hearsay: an AVOID_DECIDED with
  first_hand False whose goal source is "belief", decided before it ever
  perceived the attack itself.
* **N18** — trust matters: the same telling is believed more by a recipient
  who trusts the teller.
* **N20** — room-level avoidance is a real constraint on the WorkRuntime:
  the avoided rooms leave usable rooms, and a told threat about one room of a
  worker's own workplace removes that room's objects from its task candidates.
* **N5 / §15** — rumour spread is bounded: no pair is told the same origin
  twice, hops never exceed MAX_HOPS, no sender floods the city.
* **C1 / N8 / N11** — helping is relationship-driven (a decision that would
  not have been taken without history), completes, and leaves a HELPED_BY
  memory plus affinity in the helper and obligation in the beneficiary.
* **N21 / N22** — cognition never moves anybody: ten cognition-only steps
  change no executor position, and every goal it pushed has source "belief".
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.cognition import memory as M
from asphodel.cognition import social as S
from asphodel.cognition.relationships import PRIORS
from asphodel.embodiment import CitySpatialContext
from asphodel.smart.jobs import ROLES

CITY = "houston"
START_HOUR = 5.0
FAR = (200000.0, 200000.0)
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
SHOP = 15873                # the busiest shop of the seed-0 day
SEED_AT_HOUR = 10.5         # the errand customers arrive 10:35-10:48
END_HOUR = 11.0
FIRST_HAND = (M.DIRECT, M.PARTICIPANT)


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


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
    w.mobility.set_focus_xy(FAR)

    # who was in which building, sampled every game second: the ground truth
    # the omniscience gates are checked against.
    was_inside = defaultdict(set)
    shop_at = {}

    def _sample():
        t = round(c.now_s, 1)
        here = []
        for cid, ex in w.mobility.execs.items():
            if ex.inside:
                was_inside[cid].add(int(ex.building_id))
                if int(ex.building_id) == SHOP:
                    here.append(cid)
        shop_at[t] = set(here)

    def _customers_inside():
        return sorted(cid for cid, a in w.work.activities.items()
                      if a.building_id == SHOP and a.kind == "customer"
                      and w.mobility.execs[cid].inside
                      and w.mobility.execs[cid].building_id == SHOP)

    seeded = None
    while w.current_hour() < END_HOUR:
        w.advance_seconds(1.0, focus_xy=FAR)
        _sample()
        if seeded is None and w.current_hour() >= SEED_AT_HOUR:
            inside = _customers_inside()
            if inside:
                seeded = inside[0]
                ob.seed_index_case(seeded)
    assert seeded is not None, "no customer was ever inside the busiest shop"

    events = [dict(e) for e in c.events]
    memories = {cid: [f for f in st.facts.values()] for cid, st in c.memories.items()}

    # ---- N21/N22: cognition alone, with movement / work / outbreak stopped
    before = {cid: (tuple(ex.pos), ex.building_id, ex.inside)
              for cid, ex in w.mobility.execs.items()}
    for _ in range(10):
        c.advance(1.0)
    after = {cid: (tuple(ex.pos), ex.building_id, ex.inside)
             for cid, ex in w.mobility.execs.items()}
    moved = [cid for cid in before if before[cid] != after[cid]]

    # every goal the cognition layer pushed, as the citizen runtimes hold it
    pushed = []
    for cid, held in sorted(c.avoid_goals.items()):
        rt = w.mobility.citizens.get(cid)
        g = next((x for x in (rt.goals.goals if rt else []) if x.id == held["goal_id"]), None)
        pushed.append({"citizen_id": cid, "goal_id": held["goal_id"],
                       "source": None if g is None else g.source,
                       "sources_of_belief_goals": sorted({x.source for x in (rt.goals.goals if rt else [])
                                                          if x.source == "belief"})})

    # ---- N20: a told threat about one room of a worker's own workplace
    inject = _inject_room_threat(w, c)

    return {"world": w, "cog": c, "outbreak": ob, "seeded": seeded, "events": events,
            "memories": memories, "was_inside": dict(was_inside), "shop_at": shop_at,
            "moved_by_cognition": moved, "pushed_goals": pushed, "inject": inject,
            "n_execs": len(w.mobility.execs)}


def _inject_room_threat(w, c):
    """Tell one worker that a room of its own workplace is dangerous and see
    the WorkRuntime's task candidates lose that room's objects."""
    wk = w.work
    for cid, a in sorted(wk.activities.items()):
        if a.kind != "worker" or a.role not in ROLES:
            continue
        reg = wk.registry(a.building_id)
        for task in ROLES[a.role].tasks:
            before = wk._candidates(task, reg, cid)
            rooms = {o.room_id for o in before}
            if len(rooms) < 2:
                continue
            room = sorted(r for r in rooms if r is not None)[0]
            victims = sorted(o.object_id for o in before if o.room_id == room)
            c.store(cid).remember(M.THREAT_PERSON, c.now_s, actor=-1, building_id=a.building_id,
                                  room_id=room, source=M.TOLD, source_citizen=0,
                                  origin_witness=0, origin_id="0:1", hops=1, confidence=0.9)
            c._beliefs.pop(cid, None)
            c._invalidate_avoid(cid)
            after = wk._candidates(task, reg, cid)
            return {"citizen_id": cid, "building_id": a.building_id, "role": a.role,
                    "task_id": task.task_id, "room": room,
                    "before": sorted(o.object_id for o in before),
                    "after": sorted(o.object_id for o in after),
                    "victims": victims,
                    "avoid_rooms": sorted(c.avoid_rooms(cid, a.building_id)),
                    "threshold": c.room_threshold(cid)}
    return None


def _rows(day, kind):
    return [e for e in day["events"] if e["event"] == kind]


def _threat_facts(day):
    for cid, facts in sorted(day["memories"].items()):
        for f in sorted(facts, key=lambda x: x.fact_id):
            if f.kind in M.THREAT_KINDS:
                yield cid, f


# --------------------------------------------------------------------------- #
# the day happened at all
# --------------------------------------------------------------------------- #
def test_the_day_produced_helping_warnings_and_avoidance(day):
    c = day["cog"]
    assert day["seeded"] is not None
    for kind in ("HELP_DECIDED", "HELP_COMPLETED", "WARNING_SHARED", "WARNING_RECEIVED",
                 "PERCEIVED", "AVOID_ROOM_DECIDED", "AVOID_DECIDED"):
        assert _rows(day, kind), f"the day never produced a {kind}"
    assert c.counts["ENCOUNTER"] > 100
    assert sum(len(v) for v in day["memories"].values()) > 200


# --------------------------------------------------------------------------- #
# N1 / N2: nobody is omniscient
# --------------------------------------------------------------------------- #
def test_every_threat_fact_was_perceived_or_told_by_a_named_sender(day):
    """N1/N2: a threat memory is either the owner's own perception (with its
    PERCEIVED row) or a telling whose sender demonstrably held it first."""
    perceived = defaultdict(set)
    for e in _rows(day, "PERCEIVED"):
        perceived[e["citizen_id"]].add(str(e.get("what", "")).upper())
    received = {(e["citizen_id"], e["sender"], e["origin_id"]): e
                for e in _rows(day, "WARNING_RECEIVED")}
    memories = day["memories"]
    n_first, n_told = 0, 0
    for cid, f in _threat_facts(day):
        if f.source in FIRST_HAND:
            n_first += 1
            assert f.kind in perceived[cid], \
                f"citizen {cid} holds a first-hand {f.kind} it never perceived ({f.fact_id})"
            assert f.hops == 0 and f.source_citizen is None
        else:
            n_told += 1
            assert f.source == M.TOLD, (cid, f.fact_id, f.source)
            sender = f.source_citizen
            assert sender is not None, f"a told fact with no teller: {cid} {f.fact_id}"
            key = (cid, sender, f.origin_id)
            assert key in received, \
                f"citizen {cid} holds {f.fact_id} from {sender} with no WARNING_RECEIVED row"
            held = [g for g in memories.get(sender, []) if g.origin_id == f.origin_id]
            assert held, f"the teller {sender} never held origin {f.origin_id} it told {cid}"
            assert min(g.t for g in held) <= received[key]["t"] + 1e-6, \
                f"the teller {sender} learned {f.origin_id} after telling {cid}"
    assert n_first > 0 and n_told > 0, (n_first, n_told)


def test_nobody_outside_the_shop_holds_a_first_hand_memory_of_the_attack(day):
    """N2: the attack happened in one room of one building; only people who
    were in that building at the time saw it."""
    shop_at = day["shop_at"]
    ever = day["was_inside"]
    checked = 0
    for cid, f in _threat_facts(day):
        if f.building_id != SHOP or f.source not in FIRST_HAND:
            continue
        checked += 1
        assert SHOP in ever.get(cid, set()), \
            f"citizen {cid} saw {f.kind} in shop {SHOP} it was never inside"
        window = [t for t in shop_at if abs(t - f.t) <= 5.0]
        assert any(cid in shop_at[t] for t in window), \
            f"citizen {cid} was elsewhere at t={f.t} yet holds a first-hand {f.kind} in {SHOP}"
    assert checked >= 3, checked


def test_a_memory_only_names_a_building_its_owner_was_in_or_was_told_about(day):
    """N1: no citizen's memory mentions a place it neither visited nor heard of."""
    ever = day["was_inside"]
    bad = []
    for cid, facts in sorted(day["memories"].items()):
        for f in facts:
            if f.building_id is None or f.building_id < 0:
                continue
            if f.source == M.TOLD:
                continue
            if f.building_id not in ever.get(cid, set()):
                bad.append((cid, f.fact_id, f.kind, f.building_id, f.source))
    assert not bad, f"first-hand memories of places never visited: {bad[:8]}"


def test_the_warned_cashier_never_perceived_what_it_was_warned_about_first(day):
    """The whole point of a warning: the recipient knew before it could see."""
    received = _rows(day, "WARNING_RECEIVED")
    perceived = _rows(day, "PERCEIVED")
    first_perception = {}
    for e in perceived:
        first_perception.setdefault(e["citizen_id"], e["seq"])
    ahead = [e for e in received
             if e["citizen_id"] not in first_perception or e["seq"] < first_perception[e["citizen_id"]]]
    assert ahead, "every warning arrived after its recipient had already seen the threat"


# --------------------------------------------------------------------------- #
# N4 / N15 / N16: provenance and the social act
# --------------------------------------------------------------------------- #
def test_told_facts_keep_the_original_witness_the_teller_and_the_hop_depth(day):
    memories = day["memories"]
    told = [(cid, f) for cid, f in _threat_facts(day) if f.source == M.TOLD]
    assert told, "nothing was ever passed on"
    for cid, f in told:
        assert f.hops >= 1, (cid, f.fact_id, f.hops)
        assert f.source_citizen is not None
        assert f.origin_witness is not None and f.origin_id
        origin = f.origin_witness
        held = [g for g in memories.get(origin, []) if g.fact_id == f.origin_id]
        assert held, f"origin_witness {origin} does not hold origin fact {f.origin_id}"
        assert held[0].source in FIRST_HAND, \
            f"the origin witness {origin} of {f.origin_id} is not a first-hand holder"
        assert held[0].owner == origin


def test_a_warning_is_a_shared_received_pair_about_a_threat(day):
    shared = _rows(day, "WARNING_SHARED")
    received = _rows(day, "WARNING_RECEIVED")
    assert len(shared) == len(received), (len(shared), len(received))
    threat = [(s, r) for s, r in zip(shared, received) if s["fact_kind"] in M.THREAT_KINDS]
    assert threat, "no warning was ever about a threat"
    for s, r in threat[:20]:
        assert r["seq"] == s["seq"] + 1
        assert r["citizen_id"] == s["recipient"] and r["sender"] == s["citizen_id"]
        assert r["origin_id"] == s["origin_id"] and r["hops"] == s["hops"]
        assert s["utterance"] == S.UTTERANCE[S.WARN]
        assert r["utterance"] == S.ACKNOWLEDGE
        assert r["channel"] in ("shout", "call", "encounter")
    acts = [e for e in _rows(day, "SOCIAL_ACTION") if e["action"] == S.WARN]
    assert acts, "no WARN social action was recorded"


# --------------------------------------------------------------------------- #
# N17: acting on hearsay
# --------------------------------------------------------------------------- #
def test_a_citizen_leaves_a_building_on_hearsay_before_seeing_anything(day):
    rows = [e for e in _rows(day, "AVOID_DECIDED") if e["first_hand"] is False]
    assert rows, "nobody ever avoided a building on hearsay alone"
    e = rows[0]
    cid = e["citizen_id"]
    assert e["sources"], "a hearsay avoidance with no named source"
    assert e["danger"] >= e["threshold"]
    assert e["building_id"] == SHOP
    # it was warned before it decided, and it decided before it perceived
    warned = [x for x in _rows(day, "WARNING_RECEIVED")
              if x["citizen_id"] == cid and x["seq"] < e["seq"]]
    assert warned, f"citizen {cid} avoided {SHOP} without a warning"
    assert warned[0]["sender"] in e["sources"]
    own = [x for x in _rows(day, "PERCEIVED") if x["citizen_id"] == cid]
    assert not own or own[0]["seq"] > e["seq"], \
        f"citizen {cid} had already seen the threat when it decided to leave"
    # the goal it now holds is belief-sourced, and it was doing something else
    assert e["was_doing"] and e["was_target"], e
    later = [x for x in _rows(day, "WARNING_RECEIVED")
             if x["citizen_id"] == cid and x["seq"] > e["seq"]]
    assert later and later[0]["goal_before"] == "belief", \
        "the avoidance goal did not become the citizen's active goal"
    assert day["cog"].avoid_goals.get(cid, {}).get("building_id") == SHOP


def test_the_night_worker_across_town_is_warned_by_a_call(day):
    calls = [e for e in _rows(day, "WARNING_RECEIVED") if e["channel"] == "call"]
    assert calls, "no warning was ever phoned to a strong tie"
    for e in calls:
        assert e["fact_kind"] in M.THREAT_KINDS
        assert M.SALIENCE[e["fact_kind"]] >= S.CALL_SALIENCE
        assert e["citizen_id"] not in day["shop_at"].get(round(e["t"], 1), set()), \
            "a 'call' went to somebody standing in the same building"


# --------------------------------------------------------------------------- #
# N18: trust changes what a telling is worth
# --------------------------------------------------------------------------- #
def test_the_same_telling_is_believed_more_by_a_recipient_who_trusts_the_teller():
    for suspicion in (0.0, 0.3, 0.9):
        low = S.told_confidence(1.0, 0.1, suspicion)
        high = S.told_confidence(1.0, 0.9, suspicion)
        assert high > low, (suspicion, low, high)
        assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0
    # suspicion pulls the other way
    assert S.told_confidence(1.0, 0.5, 0.9) < S.told_confidence(1.0, 0.5, 0.0)


def test_in_world_confidences_are_exactly_trust_and_suspicion_applied(day):
    c = day["cog"]
    rows = _rows(day, "WARNING_RECEIVED")
    assert rows
    for e in rows:
        sus = c.personality(e["citizen_id"]).suspicion
        want = S.told_confidence(e["sender_confidence"] if "sender_confidence" in e else 1.0,
                                 e["trust_in_sender"], sus)
        shared = next(x for x in _rows(day, "WARNING_SHARED") if x["seq"] == e["seq"] - 1)
        want = S.told_confidence(shared["sender_confidence"], e["trust_in_sender"], sus)
        assert e["confidence"] == pytest.approx(want, abs=2e-3), (e["citizen_id"], e["confidence"], want)


def test_two_recipients_of_one_telling_differ_by_how_much_they_trust_the_teller(day):
    """Same origin fact, same sender, same second: only trust and suspicion
    separate what the two recipients now believe."""
    c = day["cog"]
    by_origin = defaultdict(list)
    for e in _rows(day, "WARNING_RECEIVED"):
        by_origin[(e["sender"], e["origin_id"])].append(e)
    pairs = 0
    for _, rows in sorted(by_origin.items()):
        if len(rows) < 2:
            continue
        assert len({e["confidence"] for e in rows}) > 1, "one telling landed identically on everybody"
        pairs += 1
        for a in rows:
            for b in rows:
                sa = c.personality(a["citizen_id"]).suspicion
                sb = c.personality(b["citizen_id"]).suspicion
                if sa == sb and a["trust_in_sender"] > b["trust_in_sender"]:
                    assert a["confidence"] > b["confidence"], (a, b)
    assert pairs >= 1, "no telling reached two people"
    # and the same origin told to a truster is worth more than to a stranger
    trusted = [e for e in _rows(day, "WARNING_RECEIVED") if e["trust_in_sender"] > 0.35]
    assert trusted, "nobody was warned by somebody they knew"


# --------------------------------------------------------------------------- #
# N20: room-level avoidance is a constraint on work, not a mood
# --------------------------------------------------------------------------- #
def test_avoided_rooms_are_excluded_from_work_but_leave_somewhere_to_work(day):
    w = day["world"]
    c = day["cog"]
    rows = _rows(day, "AVOID_ROOM_DECIDED")
    assert rows, "no room-level avoidance was ever decided"
    for e in rows:
        cid, bid = e["citizen_id"], e["building_id"]
        assert e["rooms"], e
        assert all(v >= e["threshold"] for v in e["dangers"].values()), e
        all_rooms = set(w.work.graph(bid).rooms)
        avoided = set(w.work.room_filter(cid, bid))
        assert set(e["rooms"]) <= all_rooms, (cid, bid, e["rooms"])
        assert avoided <= all_rooms, (cid, bid, avoided)
        assert set(e["rooms"]) <= avoided, "the announced rooms are not the ones filtered"
        assert all_rooms - avoided, f"citizen {cid} avoided every room of {bid}"
        assert avoided == c.avoid_rooms(cid, bid)


def test_a_told_threat_removes_that_rooms_objects_from_a_workers_task_targets(day):
    """Directly: one TOLD fact about one room, and the WorkRuntime stops
    offering that room's objects to that worker (and only to that worker)."""
    inj = day["inject"]
    assert inj is not None, "no worker had candidates in more than one room"
    assert inj["victims"], inj
    assert set(inj["victims"]) <= set(inj["before"])
    assert set(inj["after"]) == set(inj["before"]) - set(inj["victims"]), inj
    assert inj["after"], "the worker was left with no candidate object at all"
    assert inj["room"] in inj["avoid_rooms"], inj
    assert 0.9 >= inj["threshold"], inj
    # the constraint is per citizen: a coworker on the same objects is unaffected
    w = day["world"]
    wk = w.work
    reg = wk.registry(inj["building_id"])
    task = next(t for t in ROLES[inj["role"]].tasks if t.task_id == inj["task_id"])
    others = [c2 for c2, a in sorted(wk.activities.items())
              if a.building_id == inj["building_id"] and a.role == inj["role"]
              and c2 != inj["citizen_id"]]
    for other in others[:2]:
        cands = sorted(o.object_id for o in wk._candidates(task, reg, other))
        assert set(inj["victims"]) <= set(cands), \
            f"citizen {inj['citizen_id']}'s belief constrained coworker {other}"


# --------------------------------------------------------------------------- #
# N5 / §15: bounded rumour
# --------------------------------------------------------------------------- #
def test_no_pair_is_told_the_same_origin_fact_twice(day):
    told = [(e["citizen_id"], e["recipient"], e["origin_id"]) for e in _rows(day, "WARNING_SHARED")]
    dupes = [k for k, n in Counter(told).items() if n > 1]
    assert not dupes, f"duplicate tellings: {dupes[:5]}"
    # every telling that happened is in the suppression set (which also holds the
    # pairs that decided NOT to mention it, so it is the larger of the two)
    assert set(told) <= day["cog"].told
    assert len(day["cog"].told) >= len(told) > 0


def test_hearsay_never_travels_further_than_the_hop_limit(day):
    hops = [f.hops for facts in day["memories"].values() for f in facts]
    assert max(hops) <= S.MAX_HOPS, max(hops)
    assert max(hops) >= 1, "nothing was ever passed on at all"
    for e in _rows(day, "WARNING_SHARED"):
        assert 1 <= e["hops"] <= S.MAX_HOPS, e


def test_no_sender_floods_the_city_with_warnings(day):
    per_sender = Counter(e["citizen_id"] for e in _rows(day, "WARNING_SHARED"))
    assert per_sender, "nobody warned anybody"
    worst = per_sender.most_common(1)[0]
    assert worst[1] < 60, worst
    assert len(per_sender) > 1, "one citizen did all the talking"
    calls = Counter(e["origin_id"] for e in _rows(day, "WARNING_SHARED") if e["channel"] == "call")
    for origin, n in calls.items():
        assert n <= S.MAX_CALLS_PER_FACT, (origin, n)


def test_only_salient_facts_are_shared_at_all(day):
    for e in _rows(day, "WARNING_SHARED"):
        assert e["fact_kind"] in S.SHAREABLE, e["fact_kind"]
        assert e["sender_confidence"] >= S.SHAREABLE[e["fact_kind"]], e


# --------------------------------------------------------------------------- #
# C1 / N8 / N11: helping
# --------------------------------------------------------------------------- #
def test_helping_is_driven_by_relationship_history(day):
    """C1: at least one help would not have happened between strangers."""
    rows = _rows(day, "HELP_DECIDED")
    assert rows
    because = [e for e in rows if e["would_help_without_history"] is False]
    assert because, "every help decision would have happened without any history"
    for e in because:
        assert e["score"] >= e["threshold"] > e["score_without_history"], e
        assert e["components"]["familiarity"] > 0.0 or e["components"]["affinity"] > 0.0 \
            or e["components"]["obligation"] > 0.0, e
        assert e["utterance"] == S.UTTERANCE[S.HELP]


def test_every_help_decision_was_carried_out_and_left_a_memory(day):
    """N8/N11: the help ran as a real task and both sides remember it."""
    c = day["cog"]
    decided = _rows(day, "HELP_DECIDED")
    completed = _rows(day, "HELP_COMPLETED")
    assert decided and completed
    by_decision = {e["decision_seq"]: e for e in completed if e.get("decision_seq") is not None}
    for e in decided:
        done = by_decision.get(e["seq"])
        assert done is not None, f"HELP_DECIDED {e['seq']} never completed: {e}"
        helper, ben = e["citizen_id"], e["beneficiary"]
        assert (done["citizen_id"], done["beneficiary"]) == (helper, ben)
        assert done["task_id"] == e["task_id"] and done["object_id"] == e["object_id"]
        facts = c.store(ben).find(M.HELPED_BY, actor=helper)
        assert facts, f"beneficiary {ben} does not remember being helped by {helper}"
        assert facts[0].source == M.PARTICIPANT and facts[0].target == ben
        assert c.store(helper).find(M.HELPED, target=ben), \
            f"helper {helper} does not remember helping {ben}"
        h2b = c.rels.get(helper, ben)
        b2h = c.rels.get(ben, helper)
        assert h2b is not None and b2h is not None
        assert h2b.affinity > PRIORS["workplace"]["affinity"], (helper, ben, h2b.affinity)
        assert b2h.obligation > 0.0, (ben, helper, b2h.obligation)
        assert b2h.trust > PRIORS["workplace"]["trust"], (ben, helper, b2h.trust)
    assert len(by_decision) == len(decided)


def test_the_helper_and_the_beneficiary_are_coworkers_in_the_same_building(day):
    wk = day["world"].work
    for e in _rows(day, "HELP_DECIDED"):
        assert e["problem"] in ("unstaffed_queue", "queue_overload", "station_failed",
                                "cleaning_workload", "restock_workload"), e
        assert e["task_id"] in ("cover_station", "help_clean", "help_restock", "repair_station"), e
        assert e["object_id"].startswith(f"so:{e['building_id']}:"), e
        assert e["citizen_id"] != e["beneficiary"]


def test_a_thank_you_follows_every_completed_help(day):
    thanks = [e for e in _rows(day, "SOCIAL_ACTION") if e["action"] == S.THANK]
    completed = _rows(day, "HELP_COMPLETED")
    assert len(thanks) == len(completed), (len(thanks), len(completed))
    for t, done in zip(thanks, completed):
        assert t["citizen_id"] == done["beneficiary"] and t["target"] == done["citizen_id"]


# --------------------------------------------------------------------------- #
# N21 / N22: cognition decides, it never executes
# --------------------------------------------------------------------------- #
def test_ten_cognition_only_steps_move_nobody(day):
    assert day["n_execs"] > 100
    assert day["moved_by_cognition"] == [], \
        f"cognition moved {len(day['moved_by_cognition'])} executors: {day['moved_by_cognition'][:6]}"


def test_every_goal_cognition_pushed_is_belief_sourced(day):
    pushed = day["pushed_goals"]
    assert pushed, "cognition never pushed a goal"
    for row in pushed:
        assert row["source"] in (None, "belief"), row      # None: already superseded
        assert row["sources_of_belief_goals"] in ([], ["belief"]), row
    assert any(r["source"] == "belief" for r in pushed) or \
        any(e["goal_id"] for e in _rows(day, "AVOID_DECIDED")), pushed
    for e in _rows(day, "AVOID_DECIDED"):
        assert e["action"] == S.AVOID_LOCATION
        assert e["goal_id"] is not None


def test_cognition_writes_no_work_session_of_its_own(day):
    """The only way cognition touches work is the help task the WorkRuntime
    itself runs (help_for) and the room filter it installed."""
    wk = day["world"].work
    assert wk.room_filter == day["cog"].avoid_rooms
    helping = [c for c, a in sorted(wk.activities.items()) if a.help_for >= 0]
    for c in helping:
        a = wk.activities[c]
        assert a.task_id in ("cover_station", "help_clean", "help_restock", "repair_station"), a

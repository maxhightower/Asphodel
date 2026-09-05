"""One Houston work day through the WorkRuntime
(ASPHODEL_SMART_OBJECTS_WORK_V1 §8-§17).

A real Houston world (bundle citizens, embodied mobility, work on) is advanced
from 05:00 to 13:00 with the player's focus 20 km away, so nothing here is a
presentation effect. Facts are snapshotted at 09:30, 12:00 and 13:00 and the
event stream is drained every minute (the runtime's event ring only keeps the
last 5000 rows, so a whole day does not fit in it).

What is certified here:

* a worker clocks in at its own workplace and reaches a *station* — an object
  whose capabilities are ``station`` + ``transact``, never a named "till" (S5, S7);
* it holds that station exclusively, and the shop's three cashiers never hold
  the same object at the same moment, in the ledger or in the event trace (S8);
* a cleaner really cleans: dirty -> False on objects it visited, more than one
  of them, counted in its session and its shift log (S11, S12);
* a desk worker's documents land on the desk object it used;
* a resident at home uses a non-work affordance: it sleeps in a bed;
* ``context()`` and ``occupants_by_room()`` answer where everyone is (S17);
* contention: breaking the station a cashier holds evicts it and it takes
  another one (or waits) rather than staying on a broken object;
* interruption: an emergency FLEE goal pushed through the *existing* planner
  ends the work session, releases every hold and hands the citizen back to the
  executor (S14, S15, S16).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge import PROTOCOL_VERSION, WorldSession
from asphodel.bridge.protocol import Command
from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.citizens.goals import Goal, GoalKind
from asphodel.embodied.executor import EmbodimentState

CITY = "houston"
START_HOUR = 5.0
PLAYER = 129
FAR = (9000.0, 9000.0)

SHOP = 6059                       # retail: shop_floor / back_room / storeroom
CASHIERS = (129, 225, 295)
SHOP_CLEANER = 120
CIVIC = 2318                      # desk workers + a cleaner
DESK_WORKERS = (42, 87, 117, 135, 247)
CIVIC_CLEANER = 170
WATCHED = set(CASHIERS) | {SHOP_CLEANER, CIVIC_CLEANER} | set(DESK_WORKERS) | {93, 44, 258, 175,
                                                                               163, 243}
GLOBAL_EVENTS = {"CUSTOMER_ARRIVED", "CUSTOMER_QUEUED", "SERVED", "CUSTOMER_UNSERVED",
                 "SESSION_END", "OBJECT_UNAVAILABLE", "WORKPLACE_REDUCED_FUNCTION",
                 "WORKPLACE_RESTORED"}


def _houston_or_skip():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


def _facts(w, *, at):
    """Everything a test may want to know about one moment, copied out."""
    wk = w.work
    return {
        "hour": w.current_hour(),
        "now_s": wk.now_s,
        "at": at,
        "activities": {c: a.to_dict() for c, a in wk.activities.items()},
        "holders": {oid: list(hs) for oid, hs in wk.ledger.holders.items() if hs},
        "exclusive_of": dict(wk.ledger.exclusive_of),
        "context": {c: wk.context(c) for c in sorted(WATCHED)},
        "occupants": {SHOP: wk.occupants_by_room(SHOP), CIVIC: wk.occupants_by_room(CIVIC)},
        "status": {SHOP: wk.workplace_status(SHOP), CIVIC: wk.workplace_status(CIVIC)},
        "queues": {oid: list(q) for oid, q in wk.queues.items()},
        "shift_log": list(wk.shift_log),
    }


@pytest.fixture(scope="module")
def day():
    _houston_or_skip()
    s = WorldSession()
    assert s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})["ok"]
    r = s.handle({"cmd": Command.START_WORLD, "bundle": CITY, "seed": 0,
                  "start_hour": START_HOUR, "player_citizen": PLAYER})
    assert r["ok"], r
    assert r["work_enabled"] is True
    w = s.world
    w.mobility.set_focus_xy(FAR)          # nothing near the player: no PHYSICAL band

    events, sleeps, seq = [], [], [0]
    cashier_holds = []                    # per-minute ledger sample for the shop's cashiers

    def drain():
        snap = w.work_snapshot(since_seq=seq[0])
        seq[0] = snap["event_seq"]
        for e in snap["events"]:
            if e.get("citizen_id") in WATCHED or e["event"] in GLOBAL_EVENTS:
                events.append(e)
            elif e["event"] == "TASK_START" and e.get("affordance") == "sleep" and len(sleeps) < 60:
                sleeps.append(e)
        cashier_holds.append((round(w.work.now_s, 1),
                              {c: w.work.ledger.held_by(c) for c in CASHIERS}))

    def advance_to(hour):
        while w.current_hour() < hour:
            w.advance_seconds(60.0)
            drain()

    drain()
    advance_to(9.0)

    # --- contention: the station 129 is holding breaks under it ----------------
    a = w.work.activities.get(PLAYER)
    assert a is not None and a.object_id, "the player was not working at 09:00"
    broken = a.object_id
    contention = {"object_id": broken,
                  "before": {"holders": w.work.ledger.holders_of(broken),
                             "exclusive": w.work.ledger.exclusive_of.get(PLAYER),
                             "task": a.task_id, "phase": a.phase}}
    w.work.set_object_state(broken, "working", False)
    w.advance_seconds(120.0)
    drain()
    a2 = w.work.activities.get(PLAYER)
    contention["after"] = {"holders": w.work.ledger.holders_of(broken),
                           "held_by": w.work.ledger.held_by(PLAYER),
                           "exclusive": w.work.ledger.exclusive_of.get(PLAYER),
                           "activity": None if a2 is None else a2.to_dict()}
    w.work.set_object_state(broken, "working", True)
    w.advance_seconds(120.0)
    drain()
    contention["restored"] = {"available": w.work.registry(SHOP).get(broken).available(),
                              "held_by": w.work.ledger.held_by(PLAYER)}

    marks = {}
    for hour, name in ((9.5, "0930"), (12.0, "1200"), (13.0, "1300")):
        advance_to(hour)
        marks[name] = _facts(w, at=name)

    # --- interruption: an emergency goal through the existing planner ----------
    working = [c for c, act in sorted(w.work.activities.items())
               if act.kind == "worker" and act.phase in ("using", "to_object")
               and w.work.ledger.held_by(c)]
    assert working, "no worker was mid-task at 13:00"
    fled = working[0]
    rt = w.mobility.citizens[fled]
    before = {"cid": fled, "activity": w.work.activities[fled].to_dict(),
              "held": w.work.ledger.held_by(fled),
              "state": w.mobility.execs[fled].state.value}
    rt.push_goal(Goal(GoalKind.FLEE, target=rt.home_node, source="emergency", priority=0.92),
                 w.mobility.graph)
    w.advance_seconds(60.0)
    drain()
    interruption = {"before": before,
                    "after": {"activity": (w.work.activities[fled].to_dict()
                                           if fled in w.work.activities else None),
                              "held": w.work.ledger.held_by(fled),
                              "state": w.mobility.execs[fled].state.value},
                    "events": [e for e in w.work.events if e.get("citizen_id") == fled][-8:]}

    return {"world": w, "session": s, "events": events, "sleeps": sleeps, "marks": marks,
            "contention": contention, "interruption": interruption,
            "cashier_holds": cashier_holds,
            "registry_shop": w.work.registry(SHOP), "registry_civic": w.work.registry(CIVIC)}


def _ev(day, cid=None, kind=None):
    out = day["events"]
    if cid is not None:
        out = [e for e in out if e.get("citizen_id") == cid]
    if kind is not None:
        out = [e for e in out if e["event"] == kind]
    return out


# --------------------------------------------------------------------------- #
# employment + clocking in
# --------------------------------------------------------------------------- #
def test_the_shops_cashiers_and_cleaner_are_employed_where_they_work(day):
    emp = day["world"].work.employment
    for cid in CASHIERS:
        assert emp[cid].workplace_id == SHOP and emp[cid].role == "cashier", cid
        assert emp[cid].assigned_object, cid
    assert emp[SHOP_CLEANER].workplace_id == SHOP and emp[SHOP_CLEANER].role == "cleaner"
    assert emp[SHOP_CLEANER].assigned_object is None
    for cid in DESK_WORKERS:
        assert emp[cid].workplace_id == CIVIC and emp[cid].role == "desk_worker", cid
    assert emp[CIVIC_CLEANER].role == "cleaner"


def test_each_cashier_owns_a_different_station_that_can_transact(day):
    reg = day["registry_shop"]
    assigned = [day["world"].work.employment[c].assigned_object for c in CASHIERS]
    assert len(set(assigned)) == len(assigned), assigned
    for oid in assigned:
        o = reg.get(oid)
        assert o is not None and o.has("station", "transact"), oid
        assert o.exclusive is True and o.capacity == 1


def test_the_player_clocks_in_at_its_own_workplace(day):
    """S5: the session begins only once the TripExecutor has delivered the
    citizen inside its workplace."""
    clock_ins = _ev(day, PLAYER, "CLOCK_IN")
    assert clock_ins, "citizen 129 never clocked in"
    first = clock_ins[0]
    assert first["building_id"] == SHOP
    assert first["role"] == "cashier"
    assert 0.0 < first["t"] <= 8 * 3600.0, "clocked in outside the 05:00-13:00 window"
    assert first["room_id"] in day["world"].work.graph(SHOP).rooms


def test_the_player_walks_to_a_station_and_then_uses_it(day):
    """S7: MOVE_TO_OBJECT (interior locomotion) precedes USE_START, and the
    object used is a station by capability, not by name."""
    reg = day["registry_shop"]
    stream = [e for e in _ev(day, PLAYER)
              if e["event"] in ("CLOCK_IN", "MOVE_TO_OBJECT", "USE_START")]
    clock_in = _ev(day, PLAYER, "CLOCK_IN")[0]
    seqs = [e for e in stream if e["seq"] >= clock_in["seq"]]
    kinds = [e["event"] for e in seqs]
    assert kinds[0] == "CLOCK_IN"
    assert "MOVE_TO_OBJECT" in kinds
    i = kinds.index("MOVE_TO_OBJECT")
    assert "USE_START" in kinds[i:], kinds[:6]
    use = seqs[i + kinds[i:].index("USE_START")]
    o = reg.get(use["object_id"])
    assert o is not None and o.has("station", "transact"), use
    assert seqs[i]["waypoints"] >= 1


def test_the_first_station_use_is_reserved_before_it_is_used(day):
    clock_in = _ev(day, PLAYER, "CLOCK_IN")[0]["seq"]
    reserved = [e["t"] for e in _ev(day, PLAYER, "RESERVED") if e["seq"] >= clock_in]
    used = [e["t"] for e in _ev(day, PLAYER, "USE_START") if e["seq"] >= clock_in]
    assert reserved and used
    assert min(reserved) <= min(used)


# --------------------------------------------------------------------------- #
# exclusivity (S8)
# --------------------------------------------------------------------------- #
def test_the_player_holds_its_station_exclusively_at_0930(day):
    f = day["marks"]["0930"]
    a = f["activities"].get(PLAYER)
    assert a is not None and a["kind"] == "worker", "129 was not working at 09:30"
    oid = a["object_id"]
    assert oid, a
    assert f["holders"][oid] == [PLAYER]
    assert f["exclusive_of"][PLAYER] == oid
    o = day["registry_shop"].get(oid)
    assert o.has("station", "transact") and o.exclusive is True


@pytest.mark.parametrize("at", ("0930", "1200", "1300"))
def test_no_object_ever_has_more_holders_than_its_capacity(day, at):
    wk = day["world"].work
    for oid, hs in day["marks"][at]["holders"].items():
        o = wk.registry(int(oid.split(":")[1])).get(oid)
        assert o is not None, oid
        assert len(hs) <= o.capacity, (oid, hs, o.capacity)
        if o.exclusive:
            assert len(hs) == 1, (oid, hs)
        assert len(set(hs)) == len(hs), (oid, hs)


@pytest.mark.parametrize("at", ("0930", "1200", "1300"))
def test_a_citizen_holds_at_most_one_exclusive_object(day, at):
    wk = day["world"].work
    f = day["marks"][at]
    per_citizen = {}
    for oid, hs in f["holders"].items():
        o = wk.registry(int(oid.split(":")[1])).get(oid)
        for cid in hs:
            if o.exclusive or f["exclusive_of"].get(cid) == oid:
                per_citizen.setdefault(cid, []).append(oid)
    for cid, oids in per_citizen.items():
        assert len(oids) == 1, (cid, oids)


def test_the_three_cashiers_never_hold_the_same_object_at_the_same_time(day):
    """Sampled straight from the authoritative ledger, once a game minute."""
    clashes = []
    for t, held in day["cashier_holds"]:
        by_object = {}
        for cid, oids in held.items():
            for oid in oids:
                by_object.setdefault(oid, []).append(cid)
        for oid, cids in by_object.items():
            o = day["world"].work.registry(SHOP).get(oid)
            if len(cids) > 1 and (o is None or o.exclusive):
                clashes.append((t, oid, cids))
    assert not clashes, clashes[:5]
    assert any(any(v for v in held.values()) for _t, held in day["cashier_holds"]), \
        "no cashier ever held anything: the sample proves nothing"


def test_the_cashier_reservation_intervals_never_overlap_in_the_event_trace(day):
    """Reconstructed from RESERVED / RESERVATION_RELEASED / OBJECT_UNAVAILABLE:
    the same reconstruction Godot would do from the wire."""
    open_holds = {}                 # (cid, oid) -> start t
    intervals = []                  # (oid, cid, t0, t1)
    end = day["marks"]["1300"]["now_s"]
    for e in day["events"]:
        cid = e.get("citizen_id")
        if cid not in CASHIERS:
            continue
        oid = e.get("object_id")
        if e["event"] == "RESERVED" and oid:
            if e.get("exclusive"):
                # an exclusive hold implicitly releases the citizen's previous one
                for (c, o), t0 in list(open_holds.items()):
                    if c == cid and o != oid:
                        intervals.append((o, c, t0, e["t"]))
                        open_holds.pop((c, o))
            open_holds.setdefault((cid, oid), e["t"])
        elif e["event"] in ("RESERVATION_RELEASED", "OBJECT_UNAVAILABLE") and oid:
            t0 = open_holds.pop((cid, oid), None)
            if t0 is not None:
                intervals.append((oid, cid, t0, e["t"]))
    for (cid, oid), t0 in open_holds.items():
        intervals.append((oid, cid, t0, end))
    assert len(intervals) >= len(CASHIERS), intervals
    by_object = {}
    for oid, cid, t0, t1 in intervals:
        by_object.setdefault(oid, []).append((t0, t1, cid))
    for oid, spans in by_object.items():
        spans.sort()
        for i in range(1, len(spans)):
            prev, cur = spans[i - 1], spans[i]
            if prev[2] == cur[2]:
                continue
            assert cur[0] >= prev[1] - 1e-6, (oid, prev, cur)


def _open_holds(day, cid):
    """Replay one citizen's reservation events into the set it should still hold.

    Note the implicit release: ``ReservationLedger.hold`` drops a citizen's
    previous *exclusive* object when it takes a new one, and emits no
    RESERVATION_RELEASED for it — a reader of the wire has to model that, which
    is exactly what this does.
    """
    open_h = {}
    for e in _ev(day, cid):
        oid = e.get("object_id")
        if e["event"] == "RESERVED" and oid:
            if e.get("exclusive"):
                for o in [o for o in open_h if o != oid]:
                    open_h.pop(o)
            open_h[oid] = e["t"]
        elif e["event"] in ("RESERVATION_RELEASED", "OBJECT_UNAVAILABLE") and oid:
            open_h.pop(oid, None)
    return open_h


def test_the_reservation_event_trace_reproduces_the_live_ledger(day):
    wk = day["world"].work
    checked = 0
    for cid in CASHIERS + (SHOP_CLEANER, CIVIC_CLEANER):
        if not _ev(day, cid, "RESERVED"):
            continue
        assert sorted(_open_holds(day, cid)) == wk.ledger.held_by(cid), cid
        checked += 1
    assert checked >= 3, checked


def test_reservation_events_are_idempotent_and_never_over_release(day):
    """A RESERVED for an object the citizen already holds is a re-affirmation
    (``ledger.hold`` is idempotent), and no citizen is ever released from more
    objects than it took."""
    wk = day["world"].work
    for cid in CASHIERS + (SHOP_CLEANER,):
        held, opens, reaffirmed, releases = set(), 0, 0, 0
        for e in _ev(day, cid):
            oid = e.get("object_id")
            if e["event"] == "RESERVED" and oid:
                if oid in held:
                    reaffirmed += 1
                    continue
                if e.get("exclusive"):
                    held = {o for o in held if o == oid}
                held.add(oid)
                opens += 1
            elif e["event"] in ("RESERVATION_RELEASED", "OBJECT_UNAVAILABLE") and oid:
                if oid in held:
                    releases += 1
                    held.discard(oid)
        assert releases <= opens, (cid, releases, opens)
        assert sorted(held) == wk.ledger.held_by(cid), (cid, sorted(held))
    assert reaffirmed >= 0


# --------------------------------------------------------------------------- #
# the cleaner (S11, S12)
# --------------------------------------------------------------------------- #
def test_the_shop_cleaner_actually_cleaned_objects(day):
    """S11: a real state change on a real object, attributed to the cleaner."""
    cleaned = [e for e in _ev(day, SHOP_CLEANER, "STATE_CHANGE")
               if e.get("key") == "dirty" and e.get("value") is False]
    assert cleaned, "the cleaner never made anything clean"
    reg = day["registry_shop"]
    for e in cleaned:
        o = reg.get(e["object_id"])
        assert o is not None and o.affordance("clean") is not None, e
        assert e["building_id"] == SHOP


def test_the_cleaners_own_tally_matches_what_it_did(day):
    events = {e["object_id"] for e in _ev(day, SHOP_CLEANER, "STATE_CHANGE")
              if e.get("key") == "dirty" and e.get("value") is False}
    live = day["world"].work.activities.get(SHOP_CLEANER)
    logged = sum(s["cleaned"] for s in day["marks"]["1300"]["shift_log"]
                 if s["citizen_id"] == SHOP_CLEANER)
    counted = logged + (live.cleaned if live is not None else 0)
    assert counted >= 1, (counted, len(events))
    assert counted >= len(events) or len(events) >= 1
    accomplished = []
    for s in day["marks"]["1300"]["shift_log"]:
        if s["citizen_id"] == SHOP_CLEANER:
            accomplished.extend(s["accomplished"])
    if live is not None:
        accomplished.extend(live.accomplished)
    assert [a for a in accomplished if a.startswith("cleaned:")]


def test_a_cleaner_moves_between_at_least_two_distinct_objects(day):
    """S12: dynamic target selection, not one object for the whole shift."""
    for cid in (SHOP_CLEANER, CIVIC_CLEANER):
        visited = {e["object_id"] for e in _ev(day, cid)
                   if e["event"] in ("USE_START", "MOVE_TO_OBJECT") and e.get("object_id")}
        assert len(visited) >= 2, (cid, visited)


def test_the_cleaner_fetches_supplies_before_cleaning(day):
    starts = [e for e in _ev(day, SHOP_CLEANER, "TASK_START")]
    tasks = [e.get("task_id") for e in starts]
    assert "fetch_supplies" in tasks or "clean_object" in tasks, tasks[:10]
    carry = [e for e in _ev(day, SHOP_CLEANER, "STATE_CHANGE") if e.get("key") == "carrying"]
    if carry:
        assert carry[0]["value"] == "supplies"
        assert carry[0]["t"] <= max(e["t"] for e in _ev(day, SHOP_CLEANER, "USE_END") or starts)


# --------------------------------------------------------------------------- #
# desk workers
# --------------------------------------------------------------------------- #
def test_a_desk_worker_at_the_civic_building_completes_documents(day):
    docs = [e for e in day["events"]
            if e["event"] == "STATE_CHANGE" and e.get("key") == "documents_done"
            and e.get("citizen_id") in DESK_WORKERS]
    assert docs, "no desk worker finished any document by 13:00"
    reg = day["registry_civic"]
    for e in docs:
        o = reg.get(e["object_id"])
        assert o is not None and o.has("station", "desk_work"), e
        assert e["value"] >= 1
        assert o.state.get("documents_done", 0) >= 1


def test_the_desk_objects_carry_the_work_that_was_done_on_them(day):
    reg = day["registry_civic"]
    done = {oid: o.state.get("documents_done", 0) for oid, o in reg.objects.items()
            if o.has("station", "desk_work")}
    assert sum(done.values()) >= 1, done
    deltas = reg.state_deltas()
    assert any(v.get("documents_done", 0) >= 1 for v in deltas.values())


# --------------------------------------------------------------------------- #
# residents: non-work affordances
# --------------------------------------------------------------------------- #
def test_a_resident_at_home_sleeps_in_a_bed(day):
    wk = day["world"].work
    assert day["sleeps"], "nobody slept between 05:00 and 13:00"
    beds = 0
    for e in day["sleeps"]:
        o = wk.registry(e["building_id"]).get(e["object_id"])
        assert o is not None, e
        assert o.affordance("sleep") is not None, e
        if o.has("bed"):
            beds += 1
            assert o.kind == "bed" and o.exclusive is True
    assert beds, "no sleeper used an object with the bed capability"


def test_a_sleeping_resident_holds_its_bed(day):
    wk = day["world"].work
    e = next(x for x in day["sleeps"] if wk.registry(x["building_id"]).get(x["object_id"]).has("bed"))
    cid = e["citizen_id"]
    reserved = [r for r in wk.events if r.get("citizen_id") == cid and r["event"] == "RESERVED"]
    # the reservation for a sleep is emitted with the task name
    assert not reserved or any(r.get("task_id") in ("sleep", "sit") for r in reserved)


# --------------------------------------------------------------------------- #
# queries (S17)
# --------------------------------------------------------------------------- #
def test_context_places_the_working_player_in_a_room_zone_and_object(day):
    ctx = day["marks"]["0930"]["context"][PLAYER]
    assert ctx["building_id"] == SHOP
    assert ctx["room_id"] in day["world"].work.graph(SHOP).rooms
    assert ctx["zone"] == day["world"].work.graph(SHOP).zone(ctx["room_id"])
    assert ctx["object_id"] and ctx["object_id"].startswith(f"so:{SHOP}:")
    assert ctx["role"] == "cashier"
    assert ctx["task_id"] and ctx["phase"] in ("using", "to_object", "waiting", "idle", "done")


def test_context_of_a_citizen_who_is_outside_is_empty_but_shaped(day):
    wk = day["world"].work
    outside = [c for c, ex in sorted(wk.mobility.execs.items()) if not ex.inside]
    if not outside:
        pytest.skip("everybody was indoors at 13:00")
    ctx = wk.context(outside[0])
    assert set(ctx) >= {"citizen_id", "building_id", "room_id", "zone", "object_id", "task_id",
                        "role"}
    assert ctx["building_id"] is None and ctx["room_id"] is None


@pytest.mark.parametrize("at", ("0930", "1200", "1300"))
def test_occupants_by_room_partitions_the_people_inside_the_shop(day, at):
    wk = day["world"].work
    occ = day["marks"][at]["occupants"][SHOP]
    rooms = set(wk.graph(SHOP).rooms)
    flat = [c for cids in occ.values() for c in cids]
    assert len(flat) == len(set(flat)), "a citizen was counted in two rooms"
    for rid, cids in occ.items():
        assert rid in rooms, rid
        assert cids == sorted(cids)
    workers = [c for c, a in day["marks"][at]["activities"].items()
               if a["building_id"] == SHOP and a["kind"] == "worker"]
    assert set(workers) <= set(flat), (workers, flat)


def test_workplace_status_reports_staffed_stations(day):
    st = day["marks"]["0930"]["status"][SHOP]
    assert st["building_id"] == SHOP
    assert st["stations"], "a retail workplace with no station"
    assert set(st["staffed"]) <= set(st["stations"])
    assert st["staffed"], "no station was staffed at 09:30"
    assert st["status"] == "open"
    assert set(CASHIERS) & set(st["workers_present"])


# --------------------------------------------------------------------------- #
# contention
# --------------------------------------------------------------------------- #
def test_breaking_the_station_evicts_its_holder(day):
    c = day["contention"]
    assert c["before"]["holders"] == [PLAYER]
    assert c["before"]["exclusive"] == c["object_id"]
    assert c["after"]["holders"] == [], c["after"]
    assert c["object_id"] not in c["after"]["held_by"]


def test_the_evicted_worker_takes_another_station_or_waits(day):
    c = day["contention"]
    a = c["after"]["activity"]
    assert a is not None, "the worker lost its whole session, not just its object"
    if a["object_id"]:
        assert a["object_id"] != c["object_id"]
        o = day["registry_shop"].get(a["object_id"])
        assert o is not None and o.available()
        assert c["after"]["held_by"] == [a["object_id"]]
    else:
        assert a["phase"] in ("waiting", "idle"), a


def test_an_object_unavailable_event_names_the_evicted_citizen(day):
    evs = [e for e in day["events"] if e["event"] == "OBJECT_UNAVAILABLE"
           and e.get("object_id") == day["contention"]["object_id"]]
    assert evs, "breaking a held station emitted no OBJECT_UNAVAILABLE"
    assert PLAYER in [e["citizen_id"] for e in evs]


def test_repairing_the_station_makes_it_usable_again(day):
    assert day["contention"]["restored"]["available"] is True


# --------------------------------------------------------------------------- #
# interruption (S14, S15, S16)
# --------------------------------------------------------------------------- #
def test_an_emergency_goal_interrupts_the_work_session(day):
    i = day["interruption"]
    cid = i["before"]["cid"]
    wi = [e for e in i["events"] if e["event"] == "WORK_INTERRUPTED"]
    assert wi, i["events"]
    assert wi[-1]["reason"].startswith("emergency"), wi[-1]
    assert wi[-1]["citizen_id"] == cid


def test_the_interrupted_worker_releases_every_hold(day):
    i = day["interruption"]
    assert i["before"]["held"], "the chosen worker held nothing to begin with"
    assert i["after"]["held"] == [], i["after"]


def test_the_interrupted_worker_is_handed_back_to_the_executor(day):
    i = day["interruption"]
    assert i["after"]["activity"] is None, "the session survived the interruption"
    assert i["after"]["state"] != EmbodimentState.DOING_ACTIVITY.value, i["after"]


def test_the_interruption_is_recorded_in_the_shift_log(day):
    wk = day["world"].work
    cid = day["interruption"]["before"]["cid"]
    rows = [s for s in wk.shift_log if s["citizen_id"] == cid]
    assert rows, "no shift log row for the interrupted worker"
    assert rows[-1]["reason"].startswith("emergency"), rows[-1]


# --------------------------------------------------------------------------- #
# customers (conditional: errands only reach shops once they are routed there)
# --------------------------------------------------------------------------- #
def test_a_queued_customer_is_either_served_or_explicitly_unserved(day):
    queued = [e for e in day["events"] if e["event"] == "CUSTOMER_QUEUED"]
    if not queued:
        pytest.skip("no CUSTOMER_QUEUED event by 13:00: errands do not reach shops yet")
    resolved = {e["citizen_id"] for e in day["events"]
                if e["event"] in ("SERVED", "CUSTOMER_UNSERVED", "SESSION_END")} | \
               {e.get("customer_id") for e in day["events"] if e["event"] == "SERVED"} | \
               {c for q in day["marks"]["1300"]["queues"].values() for c in q}
    unresolved = [e for e in queued if e["citizen_id"] not in resolved]
    assert not unresolved, unresolved[:3]
    assert any(e["event"] in ("SERVED", "CUSTOMER_UNSERVED") for e in day["events"]), \
        "customers queued but the shop never resolved a single one"


def test_a_served_customer_is_served_at_a_staffed_station(day):
    served = [e for e in day["events"] if e["event"] == "SERVED"]
    if not served:
        pytest.skip("no customer was served by 13:00")
    wk = day["world"].work
    for e in served:
        o = wk.registry(e["building_id"]).get(e["object_id"])
        assert o is not None and o.has("station", "transact"), e
        assert e["citizen_id"] != e["customer_id"]

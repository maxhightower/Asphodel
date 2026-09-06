"""CognitionRuntime — perception, memory, belief, relationships, social
decisions for persistent citizens (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1).

    perception -> memory/belief -> evaluation -> CitizenRuntime goal / WorkRuntime
    constraint or help task -> existing execution

Authority split (nothing here moves, schedules or executes):

* **perception** — the only ways a citizen learns something: (a) it happened
  in the citizen's own room (the WorkRuntime's occupants-by-room) or within
  the outdoor perception radius of its canonical position, (b) the citizen
  took part in it (served, helped, attacked, fled), (c) another citizen told
  it — at an encounter (same room / outdoors nearby) or by a call to a
  strong tie. The backend event streams of the work and outbreak runtimes are
  the raw material; every row is filtered through those channels before it
  becomes anybody's memory. The world knows everything; no citizen does.
* **memory / belief** — :mod:`memory`, :mod:`beliefs` (structured, bounded,
  with provenance; beliefs derived, cached, possibly wrong).
* **relationships** — :mod:`relationships` (six bounded dimensions, updated
  only by rules fired by perceived events; household/workplace priors).
* **decision** — a bounded evaluation each game minute: help a coworker whose
  problem this citizen can see (through ``WorkRuntime.assist``), avoid a room
  believed dangerous (a ``WorkRuntime.room_filter`` constraint), refuse a
  building believed dangerous (a ``belief``-sourced goal pushed to the
  existing CitizenRuntime, which stays the decision authority), warn others.
* **social transmission** — bounded (§15): encounter or strong tie, salience,
  per-pair cooldown, duplicate suppression, hop limit, sociability roll;
  every told fact keeps origin witness, teller and hop depth.

Everything is deterministic (hash rolls keyed by seed and ids; sorted
iteration) and fully persisted, so save/load continues byte-identically.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..citizens.goals import Goal, GoalKind, SOURCE_BASE_PRIORITY
from ..embodied.executor import EmbodimentState
from ..world_source.detrand import hash64
from . import memory as M
from .beliefs import Belief, derive, danger_of_building, danger_of_room, danger_of_person
from .personality import Personality, personality_for
from .relationships import RelationshipGraph, DIMS
from . import social as S

Vec2 = Tuple[float, float]

COGNITION_SCHEMA_VERSION = 1
MAX_EVENTS = 5000
OUTDOOR_RADIUS_M = 20.0        # outdoor perception / encounter radius (canonical positions)
COPRESENCE_INTERVAL_S = 300.0  # co-presence scan (familiarity + encounters)
DECISION_INTERVAL_S = 60.0
CONSOLIDATE_INTERVAL_S = 600.0
PAIR_CAP = 6                   # co-presence partners per citizen per scan in a crowded room
HELP_THRESHOLD = 0.40
HELP_COOLDOWN_S = 300.0        # after a completed help task before the same helper helps again
HELP_MAX_PER_PAIR = 6          # help tasks one citizen runs for another per day
HELP_COST = {"unstaffed_queue": 0.10, "queue_overload": 0.15, "station_failed": 0.25,
             "cleaning_workload": 0.15, "restock_workload": 0.15}
AVOID_HOLD_S = 4.0 * 3600.0    # a building-avoidance goal is held this long before re-evaluation
SAFE_OBSERVATION_S = 600.0     # in a "dangerous" room for this long with no threat => PLACE_SAFE
FALSE_WARNING_WINDOW_S = 900.0 # a told threat contradicted within this window of its time is a false warning
ALARM_S = 1800.0               # a first-hand threat keeps a citizen alarmed (warning passers-by) this long


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class CognitionRuntime:
    def __init__(self, mobility, world_seed: int, work=None, outbreak_fn: Optional[Callable] = None):
        self.mobility = mobility
        self.seed = int(world_seed)
        self.work = work if work is not None else getattr(mobility, "work", None)
        self._outbreak_fn = outbreak_fn or (lambda: None)
        self.memories: Dict[int, M.MemoryStore] = {}
        self.rels = RelationshipGraph()
        self.events: List[dict] = []
        self.event_seq = 0
        self.counts: Dict[str, int] = {}
        self.now_s = float(getattr(mobility, "now_s", 0.0))
        self._work_seq = 0
        self._ob_seq = 0
        self._next_copresence_s = self.now_s
        self._next_decision_s = self.now_s
        self._next_consolidate_s = self.now_s + CONSOLIDATE_INTERVAL_S
        # social bookkeeping (all persisted)
        self.told: Set[Tuple[int, int, str]] = set()         # (sender, recipient, origin_id)
        self.pair_last_s: Dict[Tuple[int, int], float] = {}   # last telling per (sender, recipient)
        self.calls: Dict[str, int] = {}                       # origin_id -> calls made
        self.help_cooldown: Dict[int, float] = {}             # helper -> earliest next help
        self.help_pairs: Dict[Tuple[int, int], int] = {}      # (helper, beneficiary) -> tasks run
        self.help_log: List[dict] = []                        # every HELP decision with its components
        self.avoid_goals: Dict[int, dict] = {}                # cid -> {building_id, goal_id, since_s, ...}
        self.safe_since: Dict[Tuple[int, int, int], float] = {}   # (cid, bid, rid) -> since
        self.pending_help: Dict[int, dict] = {}               # helper -> decision row until HELP_DONE
        self.room_avoid_reported: Set[Tuple[int, int]] = set()   # (cid, bid) room avoidance announced
        # caches (never persisted; rebuilt on demand)
        self._beliefs: Dict[int, Tuple[int, Dict[str, Belief], float]] = {}   # cid -> (store.seq+len, beliefs, t)
        self._avoid_cache: Dict[Tuple[int, int], Tuple[int, Set[int]]] = {}
        self._pers: Dict[int, Personality] = {}
        self._occ_cache: Dict[int, Tuple[float, Dict[int, List[int]]]] = {}
        self._alarmed: List[int] = []
        if self.work is not None:
            self.work.room_filter = self.avoid_rooms
        mobility.cognition = self

    # ------------------------------------------------------------------ basics
    @property
    def outbreak(self):
        return self._outbreak_fn()

    def store(self, cid: int) -> M.MemoryStore:
        m = self.memories.get(int(cid))
        if m is None:
            m = M.MemoryStore(int(cid))
            self.memories[int(cid)] = m
        return m

    def personality(self, cid: int) -> Personality:
        p = self._pers.get(int(cid))
        if p is None:
            p = personality_for(self.seed, int(cid))
            self._pers[int(cid)] = p
        return p

    def event(self, kind: str, **info) -> dict:
        self.event_seq += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        row = {"seq": self.event_seq, "t": round(self.now_s, 1), "event": kind}
        row.update(info)
        self.events.append(row)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return row

    def _count(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1

    # ------------------------------------------------------------------ priors
    def init_priors(self, profiles: Dict[int, object]) -> int:
        """Household and workplace priors (§10) for registered citizens."""
        by_home: Dict[int, List[int]] = {}
        by_work: Dict[int, List[int]] = {}
        for cid in sorted(profiles):
            if cid not in self.mobility.execs:
                continue
            p = profiles[cid]
            hb = getattr(p, "home_building_id", None)
            wb = getattr(p, "work_building_id", None)
            if hb is not None:
                by_home.setdefault(int(hb), []).append(int(cid))
            if wb is not None:
                by_work.setdefault(int(wb), []).append(int(cid))
        n = 0
        for group, origin in ((by_home, "household"), (by_work, "workplace")):
            for _, ids in sorted(group.items()):
                for a in ids:
                    for b in ids:
                        if a != b:
                            self.rels.prior(a, b, origin, self.now_s)
                            n += 1
        self.event("PRIORS", pairs=n, households=sum(1 for v in by_home.values() if len(v) > 1),
                   workplaces=sum(1 for v in by_work.values() if len(v) > 1))
        return n

    # ------------------------------------------------------------------ clock
    def advance(self, dt_s: float) -> None:
        remaining = float(dt_s)
        while remaining > 1e-9:
            step = min(1.0, remaining)
            self.now_s += step
            self._substep(step)
            remaining -= step

    def _substep(self, dt: float) -> None:
        self._occ_cache.clear()
        if self.work is not None:
            self._perceive_work()
        ob = self.outbreak
        if ob is not None:
            self._perceive_outbreak(ob)
        if self._alarmed:
            self._alarmed_encounters()
        if self.now_s >= self._next_copresence_s:
            self._next_copresence_s = self.now_s + COPRESENCE_INTERVAL_S
            self._copresence()
        if self.now_s >= self._next_decision_s:
            self._next_decision_s = self.now_s + DECISION_INTERVAL_S
            self._decide()
        if self.now_s >= self._next_consolidate_s:
            self._next_consolidate_s = self.now_s + CONSOLIDATE_INTERVAL_S
            self._consolidate()

    # ------------------------------------------------------------------ where / who sees
    def _ctx(self, cid: int) -> dict:
        if self.work is not None:
            return self.work.context(int(cid))
        ex = self.mobility.execs.get(int(cid))
        bid = int(ex.building_id) if ex is not None and ex.inside else None
        return {"citizen_id": cid, "building_id": bid, "room_id": None, "zone": None,
                "object_id": None, "task_id": None, "role": None}

    def _occupants(self, bid: int) -> Dict[int, List[int]]:
        c = self._occ_cache.get(int(bid))
        if c is not None:
            return c[1]
        if self.work is not None:
            occ = self.work.occupants_by_room(int(bid))
        else:
            occ = {0: [c for c, ex in sorted(self.mobility.execs.items()) if ex.inside and ex.building_id == int(bid)]}
        self._occ_cache[int(bid)] = (self.now_s, occ)
        return occ

    def _room_mates(self, cid: int, bid: Optional[int], rid: Optional[int]) -> List[int]:
        """Citizens who can see what happens to ``cid`` right now: same room
        indoors, or within the outdoor radius of its canonical position."""
        ex = self.mobility.execs.get(int(cid))
        if ex is None:
            return []
        if ex.inside and bid is not None and bid >= 0:
            occ = self._occupants(bid)
            if rid is None:
                rid = self._ctx(cid).get("room_id")
            return [c for c in occ.get(rid, []) if c != cid and self._can_perceive(c)]
        out = []
        for c, ox in sorted(self.mobility.execs.items()):
            if c == cid or ox.inside or not self._can_perceive(c):
                continue
            if _d(ox.pos, ex.pos) <= OUTDOOR_RADIUS_M:
                out.append(c)
        return out

    def _can_perceive(self, cid: int) -> bool:
        ex = self.mobility.execs.get(int(cid))
        return ex is not None and ex.override not in ("incapacitated", "corpse", "undead")

    # ------------------------------------------------------------------ memory writes
    def remember(self, cid: int, kind: str, *, source: str = M.DIRECT, **kw) -> Optional[M.MemoryFact]:
        if not self._can_perceive(cid):
            return None
        st = self.store(cid)
        f, created = st.remember(kind, self.now_s, source=source, **kw)
        self._beliefs.pop(int(cid), None)
        self._invalidate_avoid(int(cid))
        if created:
            if f.salience >= 0.2:
                self.event("MEMORY_CREATED", citizen_id=int(cid), fact_id=f.fact_id, fact_kind=kind,
                           actor=f.actor, target=f.target, building_id=f.building_id, room_id=f.room_id,
                           object_id=f.object_id, source=f.source, source_citizen=f.source_citizen,
                           origin_witness=f.origin_witness, origin_id=f.origin_id, hops=f.hops,
                           confidence=round(f.confidence, 3), salience=f.salience)
            else:
                self._count("MEMORY_CREATED")
        else:
            if f.salience >= 0.4:
                self.event("MEMORY_REINFORCED", citizen_id=int(cid), fact_id=f.fact_id, fact_kind=kind,
                           count=f.count, confidence=round(f.confidence, 3))
            else:
                self._count("MEMORY_REINFORCED")
        return f

    def relate(self, owner: int, other: int, rule: str, scale: float = 1.0, **ctx) -> None:
        if owner == other or other is None or owner is None:
            return
        r = self.rels.get(owner, other)
        old_trust = r.trust if r else 0.3
        changes = self.rels.apply(owner, other, rule, self.now_s, scale)
        if not changes:
            return
        big = rule not in ("worked_beside", "met", "served", "served_by") or any(
            int(o * 10) != int(n * 10) for _, o, n in changes)
        if big:
            self.event("RELATIONSHIP_CHANGED", citizen_id=int(owner), other=int(other), rule=rule,
                       changes=[{"dim": d, "old": o, "new": n} for d, o, n in changes], **ctx)
        else:
            self._count("RELATIONSHIP_CHANGED")
        r = self.rels.get(owner, other)
        if r is not None and abs(r.trust - old_trust) >= 0.05:
            self.event("TRUST_CHANGED", citizen_id=int(owner), other=int(other), old=round(old_trust, 3),
                       new=round(r.trust, 3), rule=rule)

    # ------------------------------------------------------------------ perception: work
    def _perceive_work(self) -> None:
        w = self.work
        if w.event_seq <= self._work_seq:
            return
        rows = [e for e in w.events if e["seq"] > self._work_seq]
        self._work_seq = w.event_seq
        for e in rows:
            k = e["event"]
            if k == "SERVED":
                cashier, cust = int(e["citizen_id"]), int(e["customer_id"])
                bid, rid = e.get("building_id"), e.get("room_id")
                self.remember(cashier, M.SERVED, source=M.PARTICIPANT, target=cust, building_id=bid, room_id=rid,
                              object_id=e.get("object_id"))
                self.remember(cust, M.SERVED_BY, source=M.PARTICIPANT, actor=cashier, building_id=bid, room_id=rid,
                              object_id=e.get("object_id"))
                self.relate(cashier, cust, "served")
                self.relate(cust, cashier, "served_by")
                self._count("PERCEIVED")
            elif k == "OBJECT_UNAVAILABLE":
                cid = e.get("citizen_id")
                if cid is None:
                    continue
                cid = int(cid)
                c = self._ctx(cid)
                bid, rid = c.get("building_id"), c.get("room_id")
                self.remember(cid, M.STATION_FAILED, source=M.PARTICIPANT, actor=cid, building_id=bid,
                              room_id=rid, object_id=e.get("object_id"))
                for o in self._room_mates(cid, bid, rid):
                    self.remember(o, M.STATION_FAILED, actor=cid, building_id=bid, room_id=rid,
                                  object_id=e.get("object_id"))
                self.event("PERCEIVED", citizen_id=cid, what="station_failed", object_id=e.get("object_id"),
                           building_id=bid, room_id=rid, observers=self._room_mates(cid, bid, rid))
            elif k == "WORK_INTERRUPTED":
                cid = int(e["citizen_id"])
                bid, rid = e.get("building_id"), e.get("room_id")
                obs = self._room_mates(cid, bid, rid)
                for o in obs:
                    self.remember(o, M.COWORKER_INTERRUPTED, actor=cid, building_id=bid, room_id=rid,
                                  detail=str(e.get("reason", "")))
                if obs:
                    self.event("PERCEIVED", citizen_id=cid, what="coworker_interrupted", building_id=bid,
                               room_id=rid, observers=obs, reason=e.get("reason"))
            elif k == "HELP_TASK":
                self.event("HELP_STARTED", citizen_id=int(e["citizen_id"]), beneficiary=int(e["beneficiary"]),
                           task_id=e.get("task_id"), object_id=e.get("object_id"),
                           building_id=e.get("building_id"), room_id=e.get("room_id"))
            elif k == "HELP_DONE":
                helper, ben = int(e["citizen_id"]), int(e["beneficiary"])
                bid, rid = e.get("building_id"), e.get("room_id")
                self.remember(ben, M.HELPED_BY, source=M.PARTICIPANT, actor=helper, target=ben, building_id=bid,
                              room_id=rid, object_id=e.get("object_id"), detail=str(e.get("task_id", "")))
                self.remember(helper, M.HELPED, source=M.PARTICIPANT, actor=helper, target=ben, building_id=bid,
                              room_id=rid, object_id=e.get("object_id"), detail=str(e.get("task_id", "")))
                self.relate(ben, helper, "helped_by", task_id=e.get("task_id"))
                self.relate(helper, ben, "helped", task_id=e.get("task_id"))
                r = self.rels.get(helper, ben)
                if r is not None and r.obligation > 0.05:
                    self.relate(helper, ben, "reciprocated", task_id=e.get("task_id"))
                    self.event("RECIPROCATED", citizen_id=helper, beneficiary=ben, task_id=e.get("task_id"))
                for o in self._room_mates(ben, bid, rid):
                    if o != helper:
                        self.remember(o, M.SAW_HELP, actor=helper, target=ben, building_id=bid, room_id=rid)
                        self.relate(o, helper, "saw_help")
                dec = self.pending_help.pop(helper, None)
                self.event("HELP_COMPLETED", citizen_id=helper, beneficiary=ben, task_id=e.get("task_id"),
                           object_id=e.get("object_id"), effect=e.get("effect"), building_id=bid, room_id=rid,
                           decision_seq=(dec or {}).get("seq"))
                self.event("SOCIAL_ACTION", citizen_id=ben, target=helper, action=S.THANK, utterance=S.THANK,
                           building_id=bid, room_id=rid)
                self.help_cooldown[helper] = self.now_s + HELP_COOLDOWN_S

    # ------------------------------------------------------------------ perception: outbreak
    def _perceive_outbreak(self, ob) -> None:
        if ob.event_seq <= self._ob_seq:
            return
        rows = [e for e in ob.events if e["seq"] > self._ob_seq]
        self._ob_seq = ob.event_seq
        attacks = [e for e in ob.events[-200:] if e["event"] == "ATTACK"]
        for e in rows:
            k = e["event"]
            if k == "THREAT_OBSERVED":
                w = int(e["citizen_id"])
                t = int(e["threat_citizen"])
                kind = e.get("threat")
                # where: the threat's room when it is indoors, else where the witness
                # stood (the outbreak stamps the witness's building/room on the row)
                tc = self._ctx(t)
                bid, rid = tc.get("building_id"), tc.get("room_id")
                if bid is None:
                    eb = e.get("building_id")
                    bid = int(eb) if eb is not None and int(eb) >= 0 else None
                    rid = e.get("room_id") if bid is not None else None
                if kind == "undead":
                    self._threat_memory(w, M.THREAT_PERSON, actor=t, building_id=bid, room_id=rid, rule="threat_seen")
                elif kind == "corpse":
                    self._threat_memory(w, M.CORPSE_SEEN, target=t, building_id=bid, room_id=rid, rule=None)
                elif kind == "attack":
                    victim = next((a["victim_citizen"] for a in reversed(attacks) if a["citizen_id"] == t), None)
                    self._threat_memory(w, M.ATTACK_SEEN, actor=t, target=victim, building_id=bid, room_id=rid,
                                        rule="attack_seen")
            elif k == "ATTACK":
                u, v = int(e["citizen_id"]), int(e["victim_citizen"])
                bid, rid = e.get("building_id"), e.get("room_id")
                if bid is not None and int(bid) < 0:
                    bid = None
                self._threat_memory(v, M.ATTACKED_BY, actor=u, target=v, building_id=bid, room_id=rid,
                                    rule="attacked_by", source=M.PARTICIPANT)
            elif k == "DEATH":
                cid = int(e["citizen_id"])
                bid, rid = e.get("building_id"), e.get("room_id")
                if bid is not None and int(bid) < 0:
                    bid = None
                for o in self._room_mates(cid, bid, rid):
                    self._threat_memory(o, M.DEATH_SEEN, target=cid, building_id=bid, room_id=rid, rule=None)
            elif k == "REANIMATION":
                cid = int(e["citizen_id"])
                bid, rid = e.get("building_id"), e.get("room_id")
                if bid is not None and int(bid) < 0:
                    bid = None
                for o in self._room_mates(cid, bid, rid):
                    self._threat_memory(o, M.THREAT_PERSON, actor=cid, building_id=bid, room_id=rid,
                                        rule="threat_seen")
            elif k == "FLEE":
                cid, thr = int(e["citizen_id"]), e.get("threat_citizen")
                recent = [x for x in ob.events[-80:] if x["event"] == "FLEE" and x.get("threat_citizen") == thr
                          and x["citizen_id"] != cid and self.now_s - x["t"] <= 120.0
                          and x.get("building_id") == e.get("building_id")]
                for x in recent:
                    o = int(x["citizen_id"])
                    self.remember(cid, M.FLED_WITH, source=M.PARTICIPANT, actor=o, building_id=e.get("building_id"))
                    self.remember(o, M.FLED_WITH, source=M.PARTICIPANT, actor=cid, building_id=e.get("building_id"))
                    self.relate(cid, o, "fled_with")
                    self.relate(o, cid, "fled_with")
            elif k == "WORKPLACE_DISRUPTED":
                bid = int(e["building_id"])
                for c in sorted(int(x) for x in e.get("workers", [])):
                    ex = self.mobility.execs.get(c)
                    if ex is not None and ex.inside and ex.building_id == bid:
                        self.remember(c, M.WORKPLACE_DISRUPTED, source=M.PARTICIPANT, building_id=bid,
                                      detail=str(e.get("reason", "")))

    def _threat_memory(self, cid: int, kind: str, *, actor=None, target=None, building_id=None,
                       room_id=None, rule: Optional[str], source: str = M.DIRECT) -> None:
        f = self.remember(cid, kind, source=source, actor=actor, target=target, building_id=building_id,
                          room_id=room_id)
        if f is None:
            return
        self.event("PERCEIVED", citizen_id=int(cid), what=kind.lower(), actor=actor, target=target,
                   building_id=building_id, room_id=room_id, source=source)
        if rule and actor is not None:
            self.relate(cid, int(actor), rule)
        # a witness who was told about it before now knows first-hand: the teller was right
        for g in self.store(cid).facts.values():
            if g.kind == kind and g.actor == actor and g.source_citizen is not None and g.fact_id != f.fact_id:
                self.relate(cid, int(g.source_citizen), "warning_confirmed")
        # an urgent first-hand fact is shouted to whoever is in the building and
        # called to strong ties (§14): the burst is the encounter
        self._share_burst(cid, f)

    # ------------------------------------------------------------------ co-presence
    def _copresence(self) -> None:
        execs = self.mobility.execs
        # indoors: per building, per room
        by_b: Dict[int, List[int]] = {}
        outdoors: List[int] = []
        for cid in sorted(execs):
            ex = execs[cid]
            if not self._can_perceive(cid):
                continue
            if ex.inside and ex.building_id >= 0:
                by_b.setdefault(int(ex.building_id), []).append(cid)
            elif not ex.in_vehicle:
                outdoors.append(cid)
        for bid, ids in sorted(by_b.items()):
            if len(ids) < 2:
                continue
            occ = self._occupants(bid)
            for rid, room_ids in sorted(occ.items()):
                room_ids = [c for c in room_ids if self._can_perceive(c)]
                if len(room_ids) < 2:
                    continue
                n = len(room_ids)
                for i, a in enumerate(room_ids):
                    for j in range(1, min(PAIR_CAP, n - 1) + 1):
                        b = room_ids[(i + j) % n]
                        if a == b:
                            continue
                        self._meet(a, b, bid, rid)
        # outdoors: a grid hash over canonical positions
        cell = OUTDOOR_RADIUS_M
        grid: Dict[Tuple[int, int], List[int]] = {}
        for cid in outdoors:
            p = execs[cid].pos
            grid.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(cid)
        seen: Set[Tuple[int, int]] = set()
        for (gx, gy), ids in sorted(grid.items()):
            for a in ids:
                pa = execs[a].pos
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for b in grid.get((gx + dx, gy + dy), []):
                            if b <= a or (a, b) in seen:
                                continue
                            if _d(pa, execs[b].pos) <= OUTDOOR_RADIUS_M:
                                seen.add((a, b))
                                self._meet(a, b, None, None)

    def _meet(self, a: int, b: int, bid: Optional[int], rid: Optional[int]) -> None:
        w = self.work
        both_work = (w is not None and bid is not None
                     and a in w.activities and b in w.activities
                     and w.activities[a].kind == "worker" and w.activities[b].kind == "worker")
        kind, rule = (M.WORKED_BESIDE, "worked_beside") if both_work else (M.MET, "met")
        for x, y in ((a, b), (b, a)):
            self.remember(x, kind, actor=y, building_id=bid, room_id=rid)
            self.relate(x, y, rule)
        self._count("ENCOUNTER")
        self._share(a, b, "encounter", bid, rid)
        self._share(b, a, "encounter", bid, rid)

    # ------------------------------------------------------------------ transmission
    def _shareable(self, sender: int) -> List[M.MemoryFact]:
        st = self.memories.get(sender)
        if st is None:
            return []
        out = []
        for f in st.facts.values():
            m = S.SHAREABLE.get(f.kind)
            if m is None or f.hops >= S.MAX_HOPS or f.effective(self.now_s) < m:
                continue
            out.append(f)
        return sorted(out, key=lambda f: (-(f.salience * f.effective(self.now_s)), f.fact_id))

    def _share(self, sender: int, recipient: int, channel: str, bid=None, rid=None,
               only: Optional[M.MemoryFact] = None) -> bool:
        if not self._can_perceive(sender) or not self._can_perceive(recipient):
            return False
        facts = [only] if only is not None else self._shareable(sender)
        if not facts:
            return False
        key = (sender, recipient)
        if self.now_s - self.pair_last_s.get(key, -1e9) < S.PAIR_COOLDOWN_S:
            return False
        rst = self.store(recipient)
        pers = self.personality(sender)
        for f in facts:
            tk = (sender, recipient, f.origin_id)
            if tk in self.told or f.origin_witness == recipient:
                continue
            # the recipient already knows it first-hand: nothing to tell
            dup = [g for g in rst.facts.values() if g.merge_key() == f.merge_key()]
            if dup and any(g.first_hand() for g in dup):
                self.told.add(tk)
                continue
            # a casual encounter mentions it by a sociability roll; a call to a
            # household / workplace tie about a first-hand threat is always made
            if channel != "call" and not S.share_roll(self.seed, sender, recipient, f.origin_id, pers.sociability):
                self.told.add(tk)          # decided not to mention it; do not re-roll every encounter
                continue
            self.told.add(tk)
            self.pair_last_s[key] = self.now_s
            rrel = self.rels.get(recipient, sender, create=True)
            rpers = self.personality(recipient)
            conf = S.told_confidence(f.effective(self.now_s), rrel.trust, rpers.suspicion)
            g, created = rst.remember(f.kind, self.now_s, actor=f.actor, target=f.target, building_id=f.building_id,
                                      room_id=f.room_id, object_id=f.object_id, source=M.TOLD,
                                      source_citizen=sender, origin_witness=f.origin_witness,
                                      origin_id=f.origin_id, hops=f.hops + 1, confidence=conf,
                                      detail=f.detail, t=f.t)
            self._beliefs.pop(recipient, None)
            self._invalidate_avoid(recipient)
            rst.remember(M.WARNED_BY, self.now_s, actor=sender, building_id=bid, room_id=rid,
                         source=M.PARTICIPANT, salience=0.5, detail=f.kind)
            self.event("WARNING_SHARED", citizen_id=sender, recipient=recipient, fact_id=f.fact_id,
                       fact_kind=f.kind, actor=f.actor, target=f.target, about_building=f.building_id,
                       about_room=f.room_id, origin_witness=f.origin_witness, origin_id=f.origin_id,
                       hops=f.hops + 1, channel=channel, building_id=bid, room_id=rid,
                       utterance=(S.UTTERANCE[S.WARN] if f.kind in M.THREAT_KINDS else S.UTTERANCE[S.SHARE_INFORMATION]),
                       sender_confidence=round(f.effective(self.now_s), 3))
            rrt = self.mobility.citizens.get(recipient)
            rg = rrt.active_goal if rrt is not None else None
            self.event("WARNING_RECEIVED", citizen_id=recipient, sender=sender, fact_id=g.fact_id,
                       fact_kind=f.kind, goal_before=(None if rg is None else rg.source),
                       goal_building=(None if rrt is None else self._building_of_goal(rrt, rg)),
                       danger_after=round(danger_of_building(self.beliefs(recipient), f.building_id), 3)
                       if f.building_id is not None else None,
                       threshold=round(self.building_threshold(recipient), 3), actor=f.actor, target=f.target, about_building=f.building_id,
                       about_room=f.room_id, origin_witness=f.origin_witness, origin_id=f.origin_id,
                       hops=f.hops + 1, channel=channel, confidence=round(conf, 3),
                       trust_in_sender=round(rrel.trust, 3), created=created, utterance=S.ACKNOWLEDGE)
            act = S.WARN if f.kind in M.THREAT_KINDS else S.SHARE_INFORMATION
            self.event("SOCIAL_ACTION", citizen_id=sender, target=recipient, action=act,
                       utterance=S.UTTERANCE[act], fact_id=f.fact_id, channel=channel,
                       building_id=bid, room_id=rid)
            self.relate(recipient, sender, "warned_by")
            if f.kind in (M.THREAT_PERSON, M.ATTACK_SEEN, M.ATTACKED_BY) and f.actor is not None:
                self.relate(recipient, int(f.actor), "told_threat", scale=conf)
            if f.kind in M.THREAT_KINDS:
                self._decide_avoid_one(recipient)      # a warning is acted on at once, not next minute
            return True
        return False

    def _share_burst(self, witness: int, f: M.MemoryFact) -> None:
        ex = self.mobility.execs.get(witness)
        if ex is None or f.kind not in S.SHAREABLE:
            return
        # everyone in the building (a shout carries through walls) or nearby outdoors
        if ex.inside and ex.building_id >= 0:
            around = [c for ids in self._occupants(int(ex.building_id)).values() for c in ids
                      if c != witness and self._can_perceive(c)]
            bid = int(ex.building_id)
        else:
            around = self._room_mates(witness, None, None)
            bid = None
        for c in sorted(around):
            self._share(witness, c, "shout", bid, None, only=f)
        # calls to strong ties
        if f.salience >= S.CALL_SALIENCE:
            ties = [r for r in self.rels.of(witness)
                    if r.familiarity >= S.CALL_FAMILIARITY or r.origin in ("household", "workplace")]
            ties.sort(key=lambda r: (-r.familiarity, r.other))
            for r in ties:
                if self.calls.get(f.origin_id, 0) >= S.MAX_CALLS_PER_FACT:
                    break
                if r.other in around or not self._can_perceive(r.other):
                    continue
                if self._share(witness, r.other, "call", None, None, only=f):
                    self.calls[f.origin_id] = self.calls.get(f.origin_id, 0) + 1

    # ------------------------------------------------------------------ beliefs / constraints
    def beliefs(self, cid: int) -> Dict[str, Belief]:
        st = self.memories.get(int(cid))
        if st is None:
            return {}
        # derived at most once per game minute per citizen unless the store
        # changed; keyed by the minute (not "age of the cache") so a restored
        # world derives the same values at the same seconds
        stamp = (st.seq, len(st.facts), int(self.now_s // 60))
        c = self._beliefs.get(int(cid))
        if c is not None and c[0] == stamp:
            return c[1]
        b = derive(st, self.now_s)
        self._beliefs[int(cid)] = (stamp, b, self.now_s)
        return b

    def _invalidate_avoid(self, cid: int) -> None:
        for k in [k for k in self._avoid_cache if k[0] == cid]:
            self._avoid_cache.pop(k, None)

    def room_threshold(self, cid: int) -> float:
        return 0.25 + 0.30 * self.personality(cid).risk_tolerance

    def building_threshold(self, cid: int) -> float:
        return 0.35 + 0.30 * self.personality(cid).risk_tolerance

    def avoid_rooms(self, cid: int, bid: int) -> Set[int]:
        """Rooms of ``bid`` this citizen will not use (the WorkRuntime constraint)."""
        st = self.memories.get(int(cid))
        if st is None:
            return set()
        key = (int(cid), int(bid))
        stamp = (st.seq, len(st.facts), int(self.now_s // 60))
        c = self._avoid_cache.get(key)
        if c is not None and c[0] == stamp:
            return c[1]
        thr = self.room_threshold(cid)
        out = {b.room_id for b in self.beliefs(cid).values()
               if b.room_id is not None and b.building_id == int(bid) and b.value >= thr}
        self._avoid_cache[key] = (stamp, out)
        return out

    # ------------------------------------------------------------------ decisions
    def _decide(self) -> None:
        self._refresh_alarmed()
        self._decide_help()
        self._decide_avoid()
        self._observe_safety()

    # -- alarmed citizens warn whoever they pass ------------------------------------
    def _refresh_alarmed(self) -> None:
        """Who saw a threat first-hand in the last ALARM_S (refreshed per minute)."""
        self._alarmed = [cid for cid in sorted(self.memories)
                         if any(f.kind in M.THREAT_KINDS and f.first_hand() and self.now_s - f.t <= ALARM_S
                                for f in self.memories[cid].facts.values())]

    def _alarmed_encounters(self) -> None:
        """An alarmed citizen warns the people it passes outdoors (its own
        canonical position against theirs) every second, not only at the
        5-minute co-presence scan: a fleeing witness shouting at passers-by.
        Bounded by the number of alarmed citizens, which is small; the pair
        cooldown and the told-set make repeated checks free."""
        execs = self.mobility.execs
        alarmed = [c for c in self._alarmed if c in execs and not execs[c].inside and self._can_perceive(c)]
        if not alarmed:
            return
        outdoors = [(c, ex.pos) for c, ex in sorted(execs.items()) if not ex.inside and self._can_perceive(c)]
        for a in alarmed:
            pa = execs[a].pos
            for b, pb in outdoors:
                if b != a and _d(pa, pb) <= OUTDOOR_RADIUS_M:
                    if self._share(a, b, "encounter", None, None):
                        self._count("ENCOUNTER")

    # -- helping ---------------------------------------------------------------
    def help_score(self, helper: int, beneficiary: int, problem: dict,
                   rel_override=None) -> Tuple[float, dict]:
        p = self.personality(helper)
        r = rel_override if rel_override is not None else self.rels.get(helper, beneficiary)
        fam = r.familiarity if r else 0.0
        aff = r.affinity if r else 0.0
        obl = r.obligation if r else 0.0
        trust = r.trust if r else 0.3
        fear = r.fear if r else 0.0
        host = r.hostility if r else 0.0
        cost = HELP_COST.get(problem.get("kind"), 0.2)
        comps = {"helpfulness": round(0.50 * p.helpfulness, 3), "familiarity": round(0.25 * fam, 3),
                 "affinity": round(0.35 * aff, 3), "obligation": round(0.60 * (0.7 + 0.6 * p.loyalty) * obl, 3),
                 "trust": round(0.15 * trust, 3), "fear_hostility": round(-0.5 * (fear + host), 3),
                 "cost": -cost}
        return round(sum(comps.values()), 3), comps

    def _helpers_at(self, bid: int, w) -> List[int]:
        out = []
        for c, a in sorted(w.activities.items()):
            if a.building_id != bid or a.kind != "worker" or a.help_for >= 0 or a.task_id == "take_break":
                continue
            if self.help_cooldown.get(c, -1e9) > self.now_s or not self._can_perceive(c):
                continue
            ex = self.mobility.execs.get(c)
            if ex is None or ex.override or ex.state is not EmbodimentState.DOING_ACTIVITY:
                continue
            # a cashier with customers at its own station is busy
            if a.task_id in ("man_register", "serve_customer", "cover_station") and w.queues.get(a.object_id or ""):
                continue
            out.append(c)
        return out

    def _decide_help(self) -> None:
        w = self.work
        if w is None:
            return
        by_b: Dict[int, int] = {}
        for c, a in w.activities.items():
            if a.kind == "worker":
                by_b[a.building_id] = by_b.get(a.building_id, 0) + 1
        for bid in sorted(b for b, n in by_b.items() if n >= 2):
            problems = w.problems(bid)
            if not problems:
                continue
            helpers = self._helpers_at(bid, w)
            if not helpers:
                continue
            used: Set[int] = set()
            for pr in problems:
                ben = pr.get("citizen_id")
                if ben is None:
                    continue
                ben = int(ben)
                ben_role = w.activities[ben].role if ben in w.activities else None
                best = None
                for h in helpers:
                    if h == ben or h in used:
                        continue
                    if pr["kind"] in ("cleaning_workload", "restock_workload") and w.activities[h].role == ben_role:
                        continue           # that is its own job, not help
                    if self.help_pairs.get((h, ben), 0) >= HELP_MAX_PER_PAIR:
                        continue
                    # the helper must be able to see the problem: same building, and for a
                    # person-bound problem the beneficiary must be in the helper's room
                    # or the problem visible in the building's shared state (queues, workloads)
                    score, comps = self.help_score(h, ben, pr)
                    if score < HELP_THRESHOLD:
                        continue
                    tgt = w.help_target(h, pr)
                    if tgt is None:
                        continue
                    if best is None or (score, -h) > (best[0], -best[1]):
                        best = (score, h, comps, tgt)
                if best is None:
                    continue
                score, h, comps, (task_id, oid) = best
                # counterfactual: the same decision with no relationship history
                cf_score, _ = self.help_score(h, ben, pr, rel_override=False)
                if not w.assist(h, task_id, oid, ben):
                    continue
                used.add(h)
                self.help_pairs[(h, ben)] = self.help_pairs.get((h, ben), 0) + 1
                row = self.event("HELP_DECIDED", citizen_id=h, beneficiary=ben, problem=pr["kind"],
                                 problem_object=pr.get("object_id"), task_id=task_id, object_id=oid,
                                 building_id=bid, score=score, threshold=HELP_THRESHOLD, components=comps,
                                 score_without_history=cf_score,
                                 would_help_without_history=bool(cf_score >= HELP_THRESHOLD),
                                 utterance=S.UTTERANCE[S.HELP])
                self.event("SOCIAL_ACTION", citizen_id=h, target=ben, action=S.HELP, task_id=task_id,
                           object_id=oid, building_id=bid, utterance=S.UTTERANCE[S.HELP])
                self.pending_help[h] = row
                self.help_log.append({k: v for k, v in row.items() if k != "components"} | {"components": comps})
                if len(self.help_log) > 2000:
                    del self.help_log[: len(self.help_log) - 2000]

    # -- avoidance ---------------------------------------------------------------
    def _building_of_goal(self, rt, g) -> Optional[int]:
        if g is None:
            return None
        m = rt.node_meta.get(g.target) or {}
        return m.get("building_id")

    def _decide_avoid(self) -> None:
        # only citizens holding threat facts are candidates (an index, not a scan)
        for cid in sorted(self.memories):
            st = self.memories[cid]
            if not any(f.kind in M.THREAT_KINDS for f in st.facts.values()):
                continue
            self._decide_avoid_one(cid)

    def _decide_avoid_one(self, cid: int) -> None:
        rt = self.mobility.citizens.get(cid)
        ex = self.mobility.execs.get(cid)
        if rt is None or ex is None or not self._can_perceive(cid):
            return
        bel = self.beliefs(cid)
        thr = self.building_threshold(cid)
        # room-level: the rooms this citizen will not use in the building it is in
        if ex.inside and ex.building_id >= 0:
            rooms = self.avoid_rooms(cid, int(ex.building_id))
            key = (cid, int(ex.building_id))
            if rooms and key not in self.room_avoid_reported:
                self.room_avoid_reported.add(key)
                here = self._ctx(cid).get("room_id")
                self.event("AVOID_ROOM_DECIDED", citizen_id=cid, building_id=int(ex.building_id),
                           rooms=sorted(rooms), room_here=here, threshold=round(self.room_threshold(cid), 3),
                           action=S.AVOID_LOCATION,
                           dangers={str(r): round(danger_of_room(bel, int(ex.building_id), r), 3) for r in sorted(rooms)})
        held = self.avoid_goals.get(cid)
        if held is not None:
            still = any(g.source == "belief" for g in rt.goals.goals)
            expired = self.now_s - held["since_s"] >= AVOID_HOLD_S
            faded = danger_of_building(bel, held["building_id"]) < thr
            if not still or expired or faded:
                for g in list(rt.goals.goals):
                    if g.source == "belief":
                        rt.goals.remove(g.id)
                        if rt.active_goal is not None and rt.active_goal.id == g.id:
                            rt.active_goal = None
                rt._reselect(self.mobility.graph)
                self.avoid_goals.pop(cid, None)
                self.event("AVOID_ENDED", citizen_id=cid, building_id=held["building_id"],
                           reason="faded" if faded else ("expired" if expired else "superseded"))
            return
        # an emergency / health goal already owns this citizen
        if rt.active_goal is not None and rt.active_goal.source in ("emergency", "health", "disruption"):
            return
        # where is the schedule sending me (or keeping me)?
        g = rt.active_goal
        dest_bid = self._building_of_goal(rt, g)
        if dest_bid is None:
            return
        danger = danger_of_building(bel, int(dest_bid))
        if danger < thr:
            return
        home_bid = (rt.node_meta.get(rt.home_node) or {}).get("building_id")
        if int(dest_bid) == home_bid:
            return            # V1: nowhere else to go; the room filter still applies at home
        b = bel.get(f"danger:building:{int(dest_bid)}")
        srcs = sorted({int(s) for k, x in bel.items() if x.building_id == int(dest_bid) for s in x.source_citizens})
        first_hand = any(x.first_hand for x in bel.values() if x.building_id == int(dest_bid))
        goal = Goal(GoalKind.DO_ACTIVITY, target=rt.home_node, source="belief",
                    priority=SOURCE_BASE_PRIORITY["belief"] + 0.12 * min(1.0, danger), activity="rest",
                    reason=f"avoiding building {int(dest_bid)}: danger {danger:.2f} "
                           + ("seen" if first_hand else f"reported by {srcs}"))
        preempt = rt.push_goal(goal, self.mobility.graph)
        self.avoid_goals[cid] = {"building_id": int(dest_bid), "goal_id": goal.id, "since_s": self.now_s,
                                 "danger": round(danger, 3), "first_hand": first_hand, "sources": srcs}
        self.event("AVOID_DECIDED", citizen_id=cid, building_id=int(dest_bid), danger=round(danger, 3),
                   threshold=round(thr, 3), first_hand=first_hand, sources=srcs, goal_id=goal.id,
                   preempted=bool(preempt), was_doing=(g.kind.value if g else None),
                   was_target=(g.target if g else None), inside=bool(ex.inside and ex.building_id == int(dest_bid)),
                   action=S.AVOID_LOCATION, evidence=(b.evidence if b else []))
        self.event("SOCIAL_ACTION", citizen_id=cid, action=S.AVOID_LOCATION, building_id=int(dest_bid))

    # -- contradicting evidence -----------------------------------------------------
    def _observe_safety(self) -> None:
        ob = self.outbreak
        for cid in sorted(self.memories):
            st = self.memories[cid]
            if not any(f.kind in M.THREAT_KINDS and f.building_id is not None for f in st.facts.values()):
                continue
            ex = self.mobility.execs.get(cid)
            if ex is None or not ex.inside or not self._can_perceive(cid):
                continue
            bid = int(ex.building_id)
            c = self._ctx(cid)
            rid = c.get("room_id")
            bel = self.beliefs(cid)
            key = (cid, bid, rid if rid is not None else -1)
            if danger_of_room(bel, bid, rid) <= 0.0 and danger_of_building(bel, bid) <= 0.0:
                self.safe_since.pop(key, None)
                continue
            # is a threat actually here (in my room / this building) right now?
            present = False
            if ob is not None:
                for t, r in ob.records.items():
                    if r.state.value in ("undead", "corpse") and t in self.mobility.execs:
                        tx = self.mobility.execs[t]
                        if tx.inside and tx.building_id == bid and self._ctx(t).get("room_id") == rid:
                            present = True
                            break
            if present:
                self.safe_since.pop(key, None)
                continue
            since = self.safe_since.setdefault(key, self.now_s)
            if self.now_s - since < SAFE_OBSERVATION_S:
                continue
            self.safe_since[key] = self.now_s
            before = (danger_of_room(bel, bid, rid), danger_of_building(bel, bid))
            f = self.remember(cid, M.PLACE_SAFE, building_id=bid, room_id=rid)
            if f is None:
                continue
            bel2 = self.beliefs(cid)
            after = (danger_of_room(bel2, bid, rid), danger_of_building(bel2, bid))
            if after != before:
                self.event("BELIEF_UPDATED", citizen_id=cid, key=f"danger:room:{bid}:{rid}", building_id=bid,
                           room_id=rid, reason="observed safe", old=round(before[0], 3), value=round(after[0], 3),
                           building_old=round(before[1], 3), building_value=round(after[1], 3), fact_id=f.fact_id)
            # a told threat about this very room, claimed for a time I can now check: a false warning
            for g in list(st.facts.values()):
                if g.kind in M.THREAT_KINDS and g.source == M.TOLD and g.building_id == bid and g.room_id == rid \
                        and g.source_citizen is not None and self.now_s - g.t <= FALSE_WARNING_WINDOW_S \
                        and not st.find(M.FALSE_WARNING, actor=int(g.source_citizen), building_id=bid, room_id=rid):
                    self.remember(cid, M.FALSE_WARNING, actor=int(g.source_citizen), building_id=bid, room_id=rid)
                    self.relate(cid, int(g.source_citizen), "false_warning")

    # ------------------------------------------------------------------ consolidation
    def _consolidate(self) -> None:
        for cid in sorted(self.memories):
            st = self.memories[cid]
            dropped = st.consolidate(self.now_s)
            if dropped:
                self._beliefs.pop(cid, None)
                self._invalidate_avoid(cid)
                self._count("MEMORY_DECAYED")
                self.event("MEMORY_DECAYED", citizen_id=cid, dropped=len(dropped), remaining=len(st.facts),
                           sample=dropped[:4])

    # ------------------------------------------------------------------ queries (the context API, §19)
    def citizen_context(self, cid: int, n_memories: int = 8) -> dict:
        cid = int(cid)
        ex = self.mobility.execs.get(cid)
        rt = self.mobility.citizens.get(cid)
        c = self._ctx(cid)
        st = self.memories.get(cid)
        bel = self.beliefs(cid)
        bid = c.get("building_id")
        rid = c.get("room_id")
        nearby = self._room_mates(cid, bid, rid) if ex is not None else []
        rels = {r.other: r for r in self.rels.of(cid)}
        danger_here = max([danger_of_building(bel, bid) if bid is not None else 0.0,
                           danger_of_room(bel, bid, rid) if bid is not None and rid is not None else 0.0]
                          + [danger_of_person(bel, o) for o in nearby])
        g = rt.active_goal if rt is not None else None
        recent = [e for e in self.events[-400:]
                  if e.get("citizen_id") == cid or e.get("target") == cid or e.get("recipient") == cid
                  or e.get("beneficiary") == cid or e.get("other") == cid][-6:]
        return {
            "citizen_id": cid,
            "location": {"building_id": bid, "room_id": rid, "zone": c.get("zone"),
                         "x": None if ex is None else round(ex.pos[0], 2), "y": None if ex is None else round(ex.pos[1], 2),
                         "inside": bool(ex.inside) if ex is not None else None,
                         "band": self.mobility.bands.get(cid).name.lower() if self.mobility.bands.get(cid) else None},
            "task": {"task_id": c.get("task_id"), "object_id": c.get("object_id"), "phase": c.get("phase"),
                     "role": c.get("role")},
            "goal": g.to_dict() if g is not None else None,
            "needs": dict(rt.needs) if rt is not None else {},
            "health": (self.outbreak.health_row(cid)["state"] if self.outbreak is not None else "susceptible"),
            "personality": self.personality(cid).to_dict(),
            "memories": [f.to_dict() | {"effective": round(f.effective(self.now_s), 3)}
                         for f in (st.salient(self.now_s, n_memories) if st else [])],
            "n_memories": len(st) if st else 0,
            "people_nearby": [{"citizen_id": o, "relationship": (rels[o].to_dict() if o in rels else None),
                               "danger": round(danger_of_person(bel, o), 3)} for o in nearby[:12]],
            "relationships": [r.to_dict() for r in sorted(rels.values(),
                                                           key=lambda r: (-r.familiarity, r.other))[:8]],
            "beliefs": [b.to_dict() for b in sorted(bel.values(), key=lambda b: (-b.value, b.key))[:8]],
            "perceived_danger": round(danger_here, 3),
            "avoiding": self.avoid_goals.get(cid),
            "avoid_rooms_here": sorted(self.avoid_rooms(cid, bid)) if bid is not None else [],
            "recent_social": recent,
        }

    def lineage(self, fact_id: str) -> List[dict]:
        """Who told whom: every telling of the origin fact behind ``fact_id``."""
        origin = None
        for st in self.memories.values():
            f = st.facts.get(fact_id)
            if f is not None:
                origin = f.origin_id
                break
        if origin is None:
            origin = fact_id
        return [e for e in self.events if e["event"] == "WARNING_RECEIVED" and e.get("origin_id") == origin]

    def row(self, cid: int) -> dict:
        st = self.memories.get(int(cid))
        bel = self.beliefs(cid) if st else {}
        top = max(bel.values(), key=lambda b: b.value) if bel else None
        return {"n_memories": len(st) if st else 0, "n_relationships": len(self.rels.of(cid)),
                "top_belief": None if top is None else {"key": top.key, "value": round(top.value, 3)},
                "avoiding": (self.avoid_goals.get(int(cid)) or {}).get("building_id"),
                "helping": next((a.help_for for c, a in self.work.activities.items() if c == int(cid) and a.help_for >= 0), None)
                if self.work is not None else None}

    def snapshot(self, since_seq: int = 0) -> dict:
        return {"version": COGNITION_SCHEMA_VERSION, "now_s": self.now_s,
                "n_citizens_with_memory": len(self.memories),
                "n_facts": sum(len(s) for s in self.memories.values()),
                "n_relationships": len(self.rels.rels),
                "events": [e for e in self.events if e["seq"] > int(since_seq)],
                "event_seq": self.event_seq, "counts": dict(sorted(self.counts.items())),
                "avoiding": {str(c): v for c, v in sorted(self.avoid_goals.items())}}

    # ------------------------------------------------------------------ persistence
    def to_state(self) -> dict:
        return {"version": COGNITION_SCHEMA_VERSION, "seed": self.seed, "now_s": self.now_s,
                "work_seq": self._work_seq, "ob_seq": self._ob_seq,
                "next_copresence_s": self._next_copresence_s, "next_decision_s": self._next_decision_s,
                "next_consolidate_s": self._next_consolidate_s,
                "memories": {str(c): self.memories[c].to_state() for c in sorted(self.memories)},
                "relationships": self.rels.to_state(),
                "told": sorted([list(map(str, t)) for t in self.told]),
                "pair_last_s": {f"{a}:{b}": t for (a, b), t in sorted(self.pair_last_s.items())},
                "calls": dict(sorted(self.calls.items())),
                "help_cooldown": {str(c): t for c, t in sorted(self.help_cooldown.items())},
                "help_pairs": {f"{a}:{b}": n for (a, b), n in sorted(self.help_pairs.items())},
                "help_log": list(self.help_log),
                "avoid_goals": {str(c): v for c, v in sorted(self.avoid_goals.items())},
                "safe_since": {f"{c}:{b}:{r}": t for (c, b, r), t in sorted(self.safe_since.items())},
                "pending_help": {str(c): v for c, v in sorted(self.pending_help.items())},
                "room_avoid_reported": sorted([list(k) for k in self.room_avoid_reported]),
                "alarmed": list(self._alarmed),
                "events": list(self.events), "event_seq": self.event_seq,
                "counts": dict(sorted(self.counts.items()))}

    @classmethod
    def from_state(cls, st: dict, mobility, work=None, outbreak_fn=None) -> "CognitionRuntime":
        c = cls(mobility, int(st.get("seed", 0)), work=work, outbreak_fn=outbreak_fn)
        c.now_s = float(st.get("now_s", c.now_s))
        c._work_seq = int(st.get("work_seq", 0))
        c._ob_seq = int(st.get("ob_seq", 0))
        c._next_copresence_s = float(st.get("next_copresence_s", c.now_s))
        c._next_decision_s = float(st.get("next_decision_s", c.now_s))
        c._next_consolidate_s = float(st.get("next_consolidate_s", c.now_s))
        for k, v in (st.get("memories") or {}).items():
            c.memories[int(k)] = M.MemoryStore.from_state(v)
        c.rels = RelationshipGraph.from_state(st.get("relationships") or {})
        c.told = {(int(a), int(b), str(o)) for a, b, o in (st.get("told") or [])}
        c.pair_last_s = {(int(k.split(":")[0]), int(k.split(":")[1])): float(v)
                         for k, v in (st.get("pair_last_s") or {}).items()}
        c.calls = {str(k): int(v) for k, v in (st.get("calls") or {}).items()}
        c.help_cooldown = {int(k): float(v) for k, v in (st.get("help_cooldown") or {}).items()}
        c.help_pairs = {(int(k.split(":")[0]), int(k.split(":")[1])): int(v)
                        for k, v in (st.get("help_pairs") or {}).items()}
        c.help_log = list(st.get("help_log") or [])
        c.avoid_goals = {int(k): v for k, v in (st.get("avoid_goals") or {}).items()}
        c.safe_since = {(int(k.split(":")[0]), int(k.split(":")[1]), int(k.split(":")[2])): float(v)
                        for k, v in (st.get("safe_since") or {}).items()}
        c.pending_help = {int(k): v for k, v in (st.get("pending_help") or {}).items()}
        c.room_avoid_reported = {(int(a), int(b)) for a, b in (st.get("room_avoid_reported") or [])}
        c._alarmed = [int(x) for x in (st.get("alarmed") or [])]
        c.events = list(st.get("events") or [])
        c.event_seq = int(st.get("event_seq", 0))
        c.counts = {str(k): int(v) for k, v in (st.get("counts") or {}).items()}
        return c

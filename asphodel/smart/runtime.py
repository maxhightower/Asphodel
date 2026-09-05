"""WorkRuntime — executes tasks through rooms and smart objects for citizens
the TripExecutor has delivered into a building (ASPHODEL_SMART_OBJECTS_WORK_V1
§8–§15).

Authority split (nothing here duplicates an existing owner):

* CitizenRuntime chooses the goal (the schedule's ``work`` slot, a health or
  emergency goal); TripExecutor gets the citizen to the building and reports
  ``DOING_ACTIVITY`` inside it. Only then does this runtime act.
* This runtime owns *interior* locomotion (a walk across rooms through
  doorways to an object's interaction point — never a city trip), task
  selection through the job grammar, reservations and mutable object state.
* The moment the executor leaves ``DOING_ACTIVITY`` (a new plan, a health
  override, a flee) the session is interrupted: every hold is released and
  the planner/executor carry on untouched.

Everything is deterministic (durations and dirt are hash rolls) and fully
persisted, so save/load continues byte-identically.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Tuple

from ..embodied.executor import EmbodimentState, TripExecutor
from ..world_source.detrand import hash64
from .jobs import ROLES, Employment, JobRole, TaskDefinition, employment_for, task_duration
from .objects import SmartObject, SmartObjectRegistry
from .reservations import ReservationLedger
from .rooms import RoomGraph

Vec2 = Tuple[float, float]

WALK_SPEED = 1.3               # interior walking speed (m/s)
ARRIVE_M = 0.35
WAIT_RETRY_S = 30.0            # a waiting worker re-evaluates this often
CUSTOMER_PATIENCE_S = 1200.0   # a queued customer gives up after this (outlasts a 15-min break)
QUEUE_SPACING_M = 1.0
DIRT_ROLL = 0.30               # chance a completed use dirties the object
DEPLETE_PER_BROWSE = 8
RESTOCK_BELOW = 45
MAX_EVENTS = 5000

# event vocabulary
EV = ("EMPLOYED", "CLOCK_IN", "TASK_START", "MOVE_TO_OBJECT", "RESERVED", "RESERVATION_DENIED",
      "WAIT", "USE_START", "USE_END", "TASK_END", "STATE_CHANGE", "CUSTOMER_ARRIVED",
      "CUSTOMER_QUEUED", "SERVED", "CUSTOMER_UNSERVED", "BREAK_START", "BREAK_END",
      "WORK_INTERRUPTED", "RESERVATION_RELEASED", "CLOCK_OUT", "OBJECT_UNAVAILABLE",
      "WORKPLACE_REDUCED_FUNCTION", "WORKPLACE_RESTORED", "SESSION_START", "SESSION_END")


@dataclass
class ActivityState:
    """One citizen's live session inside one building."""
    citizen_id: int
    building_id: int
    kind: str                      # worker | customer | resident
    role: str = ""                 # job role for workers; "customer"/"resident" otherwise
    phase: str = "idle"            # idle | to_object | using | waiting | done
    task_id: str = ""
    task_instance: int = 0
    object_id: Optional[str] = None
    room_id: int = -1
    waypoints: List[List[float]] = field(default_factory=list)
    progress_s: float = 0.0
    duration_s: float = 0.0
    started_s: float = 0.0
    session_start_s: float = 0.0
    worked_s: float = 0.0          # continuous work since the last break
    wait_since_s: float = -1.0
    carrying: str = ""
    served: int = 0
    documents: int = 0
    cleaned: int = 0
    restocked: int = 0
    served_by: int = -1            # customers: cashier who served them
    interrupted: str = ""
    accomplished: List[str] = field(default_factory=list)
    next_s: float = 0.0            # nothing to do before this clock time (wake scheduling)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActivityState":
        a = cls(int(d["citizen_id"]), int(d["building_id"]), str(d["kind"]))
        for k, v in d.items():
            if hasattr(a, k):
                setattr(a, k, v)
        a.waypoints = [[float(p[0]), float(p[1])] for p in (d.get("waypoints") or [])]
        return a


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class WorkRuntime:
    def __init__(self, mobility, world_seed: int, descriptor_fn: Callable[[int], object]):
        self.mobility = mobility
        self.seed = int(world_seed)
        self._descriptor_fn = descriptor_fn
        self.registries: Dict[int, SmartObjectRegistry] = {}
        self.graphs: Dict[int, RoomGraph] = {}
        self.employment: Dict[int, Employment] = {}
        self.ledger = ReservationLedger()
        self.activities: Dict[int, ActivityState] = {}
        self.queues: Dict[str, List[int]] = {}          # station object -> waiting customers
        self.events: List[dict] = []
        self.event_seq = 0
        self.now_s = float(getattr(mobility, "now_s", 0.0))
        self.reduced: Dict[int, bool] = {}              # workplace -> reduced-function flag
        self.shift_log: List[dict] = []                 # completed sessions (accomplishments)
        self.counts: Dict[str, int] = {}                # event kind -> total ever (the ring drops old rows)
        self._pending_deltas: Dict[int, dict] = {}      # object state loaded before registry build
        self._next_minute_s = self.now_s
        mobility.work = self

    # -- building semantics (regenerable) ----------------------------------------
    def registry(self, bid: int) -> SmartObjectRegistry:
        bid = int(bid)
        reg = self.registries.get(bid)
        if reg is None:
            desc = self._descriptor_fn(bid)
            reg = SmartObjectRegistry(bid, desc)
            self.registries[bid] = reg
            self.graphs[bid] = RoomGraph(desc)
            if bid in self._pending_deltas:
                reg.apply_state_deltas(self._pending_deltas.pop(bid))
            else:
                self._initial_dirt(reg)
        return reg

    def graph(self, bid: int) -> RoomGraph:
        self.registry(bid)
        return self.graphs[int(bid)]

    def _initial_dirt(self, reg: SmartObjectRegistry) -> None:
        """A deterministic share of cleanable objects start the day dirty and
        shelves start partly depleted, so maintenance roles have real work."""
        for oid, o in sorted(reg.objects.items()):
            if "dirty" in o.state and (hash64(self.seed, "dirt0", oid) % 100) < 25:
                o.state["dirty"] = True
            if "stock" in o.state and o.has("shelf") and (hash64(self.seed, "stock0", oid) % 100) < 40:
                o.state["stock"] = 20 + hash64(self.seed, "stock0v", oid) % 20

    # -- employment ----------------------------------------------------------------
    def employ_all(self, profiles: Dict[int, object]) -> int:
        """Deterministic employment for every registered citizen with a
        workplace. ``profiles`` maps citizen id -> profile (needs
        ``work_building_id`` and ``occupation``)."""
        taken_by_wp: Dict[int, Dict[str, int]] = {}
        n = 0
        for cid in sorted(profiles):
            if cid in self.employment or cid not in self.mobility.execs:
                continue
            p = profiles[cid]
            wb = getattr(p, "work_building_id", None)
            if wb is None:
                continue
            reg = self.registry(int(wb))
            taken = taken_by_wp.setdefault(int(wb), {})
            emp = employment_for(self.seed, cid, getattr(p, "occupation", ""), int(wb), reg, taken)
            if emp is None:
                continue
            self.employment[cid] = emp
            n += 1
            self.event("EMPLOYED", citizen_id=cid, building_id=int(wb), role=emp.role,
                       object_id=emp.assigned_object, occupation=emp.occupation)
        return n

    # -- events ------------------------------------------------------------------
    def event(self, kind: str, **info) -> dict:
        self.event_seq += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        row = {"seq": self.event_seq, "t": round(self.now_s, 1), "event": kind}
        row.update(info)
        self.events.append(row)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return row

    def _where(self, ex: TripExecutor, a: Optional[ActivityState] = None) -> dict:
        d = {"x": round(ex.pos[0], 2), "y": round(ex.pos[1], 2), "building_id": int(ex.building_id)}
        if a is not None:
            d.update({"room_id": a.room_id, "object_id": a.object_id, "task_id": a.task_id,
                      "phase": a.phase})
        return d

    # -- the clock ---------------------------------------------------------------
    def advance(self, dt_s: float) -> None:
        """Called by World.advance_seconds after mobility; integrates in the
        mobility's 1 s substeps (dt may be longer: it is split)."""
        remaining = float(dt_s)
        while remaining > 1e-9:
            step = min(1.0, remaining)
            self.now_s += step
            self._substep(step)
            remaining -= step

    def _substep(self, dt: float) -> None:
        execs = self.mobility.execs
        activities = self.activities
        for cid in sorted(execs):
            ex = execs[cid]
            a = activities.get(cid)
            if a is not None and a.next_s > self.now_s and not ex.override \
                    and ex.state is EmbodimentState.DOING_ACTIVITY and ex.building_id == a.building_id \
                    and ex.current_step is None:
                # a sleeping session in an unchanged situation: progress is
                # exactly what the awake path would have added
                if a.phase == "using":
                    a.progress_s += dt
                    if a.kind == "worker" and a.task_id != "take_break":
                        a.worked_s += dt
                continue
            if a is None and (ex.state is not EmbodimentState.DOING_ACTIVITY or ex.override):
                continue                      # nobody to start a session for
            session_kind = self._session_kind(cid, ex)
            if session_kind is None:
                if a is not None:
                    self._end_session(cid, ex, a)
                continue
            if a is None or a.building_id != ex.building_id or a.kind != session_kind:
                if a is not None:
                    self._end_session(cid, ex, a)
                a = self._start_session(cid, ex, session_kind)
                if a is None:
                    continue
            if a.next_s > self.now_s:
                continue                      # asleep until its wake time (progress is implicit)
            self._advance_session(cid, ex, a, dt)
        if self.now_s >= self._next_minute_s:
            self._next_minute_s = self.now_s + 60.0
            self._minute_scan()

    def _session_kind(self, cid: int, ex: TripExecutor) -> Optional[str]:
        """What kind of interior session this citizen is in right now, or
        None (outside, travelling, overridden by health, or nothing to do)."""
        if ex.override or not ex.inside or ex.state != EmbodimentState.DOING_ACTIVITY:
            return None
        if ex.current_step is not None:
            return None
        act = str(ex.activity or "")
        emp = self.employment.get(cid)
        if emp is not None and ex.building_id == emp.workplace_id and act != "sleep":
            return "worker"           # at the workplace: on shift (the commute's "arrived" included)
        if act == "sleep":
            return "resident"
        if act in ("errand", "leisure", "idle", "arrived", "rest"):
            rt = self.mobility.citizens.get(cid)
            home_bid = None
            if rt is not None:
                home_bid = (rt.node_meta.get(rt.home_node) or {}).get("building_id")
            if ex.building_id == home_bid:
                return "resident"
            return "customer"
        return None

    # -- sessions ------------------------------------------------------------------
    def _start_session(self, cid: int, ex: TripExecutor, kind: str) -> Optional[ActivityState]:
        reg = self.registry(ex.building_id)
        g = self.graphs[ex.building_id]
        a = ActivityState(cid, int(ex.building_id), kind)
        a.session_start_s = self.now_s
        a.room_id = g.room_of(ex.pos)
        if kind == "worker":
            a.role = self.employment[cid].role
            self.event("CLOCK_IN", citizen_id=cid, role=a.role, **self._where(ex, a))
        else:
            a.role = kind
            self.event("SESSION_START", citizen_id=cid, session=kind, **self._where(ex, a))
            if kind == "customer":
                self.event("CUSTOMER_ARRIVED", citizen_id=cid, **self._where(ex, a))
        self.activities[cid] = a
        return a

    def _end_session(self, cid: int, ex: TripExecutor, a: ActivityState, reason: str = "") -> None:
        if not reason:
            reason = self._interruption_reason(cid, ex)
        released = self.ledger.release(cid)
        for oid in released:
            self.event("RESERVATION_RELEASED", citizen_id=cid, object_id=oid, reason=reason)
        for oid, q in list(self.queues.items()):
            if cid in q:
                q.remove(cid)
                if not q:
                    self.queues.pop(oid, None)
                self.event("CUSTOMER_UNSERVED", citizen_id=cid, reason="left the queue", object_id=oid,
                           building_id=a.building_id)
        summary = {"citizen_id": cid, "building_id": a.building_id, "kind": a.kind, "role": a.role,
                   "start_s": a.session_start_s, "end_s": self.now_s, "served": a.served,
                   "documents": a.documents, "cleaned": a.cleaned, "restocked": a.restocked,
                   "accomplished": list(a.accomplished), "reason": reason,
                   "last_task": a.task_id, "last_object": a.object_id}
        self.shift_log.append(summary)
        if len(self.shift_log) > 2000:
            del self.shift_log[: len(self.shift_log) - 2000]
        if a.kind == "worker":
            if reason in ("shift_end", "left"):
                self.event("CLOCK_OUT", citizen_id=cid, role=a.role, served=a.served,
                           documents=a.documents, cleaned=a.cleaned, restocked=a.restocked,
                           reason=reason, **self._where(ex, a))
            else:
                self.event("WORK_INTERRUPTED", citizen_id=cid, role=a.role, reason=reason,
                           progress_s=round(a.progress_s, 1), **self._where(ex, a))
        else:
            self.event("SESSION_END", citizen_id=cid, session=a.kind, reason=reason, **self._where(ex, a))
        self.activities.pop(cid, None)

    def _interruption_reason(self, cid: int, ex: TripExecutor) -> str:
        if ex.override:
            return f"health:{ex.override}"
        rt = self.mobility.citizens.get(cid)
        g = rt.active_goal if rt is not None else None
        if g is not None and g.source in ("emergency", "health", "disruption"):
            return f"{g.source}:{g.kind.value}"
        if g is not None and g.source == "schedule":
            return "shift_end"
        if not ex.inside:
            return "left"
        return "shift_end"

    # -- session advance -----------------------------------------------------------
    def _advance_session(self, cid: int, ex: TripExecutor, a: ActivityState, dt: float) -> None:
        reg = self.registries[a.building_id]
        g = self.graphs[a.building_id]
        if a.phase == "to_object":
            self._walk(ex, a, g, dt)
            if not a.waypoints:
                a.phase = "using"
                a.progress_s = 0.0
                a.started_s = self.now_s
                self.event("USE_START", citizen_id=cid, **self._where(ex, a))
            return
        if a.phase == "using":
            self._use(cid, ex, a, reg, dt)
            if a.phase == "using":
                serving = a.task_id == "man_register" and bool(self.queues.get(a.object_id or ""))
                a.next_s = self.now_s if serving else min(a.started_s + a.duration_s, self.now_s + 60.0)
            return
        if a.phase == "waiting":
            self._wait(cid, ex, a, reg, g, dt)
            if a.phase == "waiting" and not a.waypoints:
                a.next_s = self.now_s + (WAIT_RETRY_S if a.kind != "customer" else 5.0)
            return
        if a.phase == "done":
            a.next_s = self.now_s + 60.0
            return
        # idle: pick the next thing to do
        if a.kind == "worker":
            self._select_work_task(cid, ex, a, reg, g)
        elif a.kind == "customer":
            self._customer_next(cid, ex, a, reg, g)
        else:
            self._resident_next(cid, ex, a, reg, g)

    def _walk(self, ex: TripExecutor, a: ActivityState, g: RoomGraph, dt: float) -> None:
        budget = WALK_SPEED * dt
        while a.waypoints and budget > 1e-9:
            tx, ty = a.waypoints[0]
            d = _d(ex.pos, (tx, ty))
            if d <= max(ARRIVE_M, budget):
                ex.pos = (float(tx), float(ty))
                a.waypoints.pop(0)
                budget -= d
                continue
            ex.heading = math.atan2(ty - ex.pos[1], tx - ex.pos[0])
            ex.pos = (ex.pos[0] + (tx - ex.pos[0]) / d * budget, ex.pos[1] + (ty - ex.pos[1]) / d * budget)
            budget = 0.0
        ex.speed = 0.0 if not a.waypoints else WALK_SPEED
        a.room_id = g.room_of(ex.pos)

    def _go_to(self, cid: int, ex: TripExecutor, a: ActivityState, g: RoomGraph, xy: Vec2) -> None:
        start = ex.pos
        pts: List[Vec2] = []
        if g.room_of(start) < 0 or _d(start, g.entrance_xy) < 0.6 or not self._inside_hull(g, start):
            pts.append(g.inside_xy)
            start = g.inside_xy
        pts.extend(g.route(start, xy))
        a.waypoints = [[float(p[0]), float(p[1])] for p in pts]
        a.phase = "to_object"
        self.event("MOVE_TO_OBJECT", citizen_id=cid, waypoints=len(a.waypoints), **self._where(ex, a))

    @staticmethod
    def _inside_hull(g: RoomGraph, xy: Vec2) -> bool:
        for r in g.rooms.values():
            if r.x0 <= xy[0] <= r.x1 and r.y0 <= xy[1] <= r.y1:
                return True
        return False

    # -- workers ---------------------------------------------------------------------
    def _select_work_task(self, cid: int, ex: TripExecutor, a: ActivityState,
                          reg: SmartObjectRegistry, g: RoomGraph) -> None:
        role = ROLES[a.role]
        emp = self.employment[cid]
        for task in sorted(role.tasks, key=lambda t: -t.priority):
            if not self._precondition(task, a, reg, emp):
                continue
            target = self._select_target(task, a, reg, emp, cid)
            if target is None:
                continue
            if not self._take(cid, target, task, a):
                # contention: the preferred station is held by someone else
                self.event("RESERVATION_DENIED", citizen_id=cid, object_id=target.object_id,
                           holders=self.ledger.holders_of(target.object_id), task_id=task.task_id)
                alt = self._alternative(task, a, reg, emp, cid, exclude=target.object_id)
                if alt is not None and self._take(cid, alt, task, a):
                    target = alt
                else:
                    continue
            self._begin_task(cid, ex, a, g, task, target)
            return
        # nothing doable: wait in the role's zone and retry
        self._begin_wait(cid, ex, a, g, reg, role)

    def _precondition(self, task: TaskDefinition, a: ActivityState, reg: SmartObjectRegistry,
                      emp: Employment) -> bool:
        p = task.precondition
        if p == "break_due":
            # a break waits while customers are queued at this worker's station
            oid = a.object_id if a.object_id and self.ledger.exclusive_of.get(a.citizen_id) == a.object_id \
                else emp.assigned_object
            return a.worked_s >= ROLES[a.role].break_after_s and not (oid and self.queues.get(oid))
        if p == "customer_waiting":
            oid = a.object_id if a.object_id and self.ledger.exclusive_of.get(a.citizen_id) == a.object_id \
                else emp.assigned_object
            return bool(oid and self.queues.get(oid))
        if p == "has_supplies":
            return a.carrying == "supplies" and any(
                o.state.get("dirty") and o.affordance("clean") for o in reg.objects.values())
        if p == "needs_supplies":
            return a.carrying != "supplies" and any(
                o.state.get("dirty") and o.affordance("clean") for o in reg.objects.values())
        if p == "has_goods":
            return a.carrying == "goods"
        if p == "needs_goods":
            return a.carrying != "goods" and any(
                o.has("shelf", "stock") and int(o.state.get("stock", 100)) < RESTOCK_BELOW
                for o in reg.objects.values())
        return True

    def _candidates(self, task: TaskDefinition, reg: SmartObjectRegistry) -> List[SmartObject]:
        objs = reg.with_affordance(task.affordance) if task.affordance else list(reg.objects.values())
        if task.caps:
            objs = [o for o in objs if o.has(*task.caps)]
        return [o for o in objs if o.available()]

    def _select_target(self, task: TaskDefinition, a: ActivityState, reg: SmartObjectRegistry,
                       emp: Employment, cid: int) -> Optional[SmartObject]:
        cands = self._candidates(task, reg)
        if not cands:
            return None
        sel = task.selector
        if sel == "assigned":
            if emp.assigned_object:
                o = reg.get(emp.assigned_object)
                if o is not None and o.available():
                    return o
            return self._nearest_free(cands, a, cid)
        if sel == "dirtiest":
            dirty = [o for o in cands if o.state.get("dirty")]
            return self._nearest_free(dirty, a, cid) if dirty else None
        if sel == "depleted":
            low = [o for o in cands if int(o.state.get("stock", 100)) < RESTOCK_BELOW]
            return self._nearest_free(low, a, cid) if low else None
        if sel in ("supplies", "goods"):
            return self._nearest_free(cands, a, cid)
        if sel == "seat":
            zones = ("break_room", "employee_area", "hall")
            g = self.graphs[reg.building_id]
            pref = [o for o in cands if g.zone(o.room_id) in zones]
            return self._nearest_free(pref or cands, a, cid)
        return self._nearest_free(cands, a, cid)

    def _nearest_free(self, objs: List[SmartObject], a: ActivityState, cid: int) -> Optional[SmartObject]:
        ex = self.mobility.execs[cid]
        free = [o for o in objs if self.ledger.is_free(o, o.exclusive) or cid in self.ledger.holders_of(o.object_id)]
        if not free:
            return None                   # everything is held: the caller waits, no denial storm
        return min(free, key=lambda o: (_d(ex.pos, o.use_xy), o.object_id))

    def _alternative(self, task: TaskDefinition, a: ActivityState, reg: SmartObjectRegistry,
                     emp: Employment, cid: int, exclude: str) -> Optional[SmartObject]:
        cands = [o for o in self._candidates(task, reg) if o.object_id != exclude
                 and self.ledger.is_free(o, o.exclusive)]
        return self._nearest_free(cands, a, cid) if cands else None

    def _take(self, cid: int, obj: SmartObject, task: TaskDefinition, a: ActivityState) -> bool:
        if task.hold == "none":
            return True
        excl = (task.hold == "exclusive") or obj.exclusive
        if cid in self.ledger.holders_of(obj.object_id):
            return True                   # already ours: no duplicate RESERVED
        old = self.ledger.exclusive_of.get(cid) if excl else None
        ok = self.ledger.hold(obj, cid, self.now_s, exclusive=excl)
        if ok:
            if old is not None and old != obj.object_id:
                self.event("RESERVATION_RELEASED", citizen_id=cid, object_id=old, reason="switched station")
            self.event("RESERVED", citizen_id=cid, object_id=obj.object_id, exclusive=excl,
                       task_id=task.task_id)
        return ok

    def _begin_task(self, cid: int, ex: TripExecutor, a: ActivityState, g: RoomGraph,
                    task: TaskDefinition, obj: SmartObject) -> None:
        a.task_instance += 1
        a.task_id = task.task_id
        a.object_id = obj.object_id
        a.duration_s = task_duration(self.seed, cid, task, a.task_instance)
        a.progress_s = 0.0
        a.wait_since_s = -1.0
        a.next_s = 0.0
        self.event("TASK_START", citizen_id=cid, duration_s=round(a.duration_s, 1),
                   affordance=task.affordance, **self._where(ex, a))
        if task.task_id == "take_break":
            self.event("BREAK_START", citizen_id=cid, **self._where(ex, a))
        if _d(ex.pos, obj.use_xy) <= ARRIVE_M:
            a.waypoints = []
            a.phase = "using"
            a.started_s = self.now_s
            self.event("USE_START", citizen_id=cid, **self._where(ex, a))
        else:
            self._go_to(cid, ex, a, g, obj.use_xy)

    def _begin_wait(self, cid: int, ex: TripExecutor, a: ActivityState, g: RoomGraph,
                    reg: SmartObjectRegistry, role: JobRole) -> None:
        a.task_id = "wait"
        a.object_id = None
        a.phase = "waiting"
        a.wait_since_s = self.now_s
        # stand in the role's idle zone (its first zone that exists here)
        target = None
        for z in role.workplace_zones:
            rooms = g.rooms_of_zone(z)
            if rooms:
                target = g.rooms[rooms[0]].center()
                break
        if target is None:
            target = g.inside_xy
        self.event("WAIT", citizen_id=cid, reason="no available task/object", **self._where(ex, a))
        if _d(ex.pos, target) > ARRIVE_M:
            a.waypoints = [[float(target[0]), float(target[1])]]

    def _wait(self, cid: int, ex: TripExecutor, a: ActivityState, reg: SmartObjectRegistry,
              g: RoomGraph, dt: float) -> None:
        if a.waypoints:
            self._walk(ex, a, g, dt)
            return
        if a.kind == "customer":
            self._customer_wait(cid, ex, a, reg, g, dt)
            return
        if self.now_s - a.wait_since_s >= WAIT_RETRY_S:
            a.phase = "idle"

    def _use(self, cid: int, ex: TripExecutor, a: ActivityState, reg: SmartObjectRegistry, dt: float) -> None:
        obj = reg.get(a.object_id) if a.object_id else None
        if obj is None or not obj.available():
            self._object_lost(cid, ex, a, "object unavailable")
            return
        a.progress_s += dt
        if a.kind == "worker" and a.task_id != "take_break":
            a.worked_s += dt
        if a.task_id == "man_register":
            # serve whoever is queued while manning the station
            q = self.queues.get(obj.object_id)
            if q:
                self._serve(cid, ex, a, obj, q[0])
        if a.progress_s < a.duration_s:
            return
        self._complete(cid, ex, a, reg, obj)

    def _serve(self, cid: int, ex: TripExecutor, a: ActivityState, obj: SmartObject, customer: int) -> None:
        """One customer at the head of the queue is served over ~90 s."""
        c = self.activities.get(customer)
        if c is None or c.phase != "waiting":
            self.queues[obj.object_id].remove(customer)
            return
        c.progress_s += 1.0
        if c.progress_s < 90.0:
            return
        self.queues[obj.object_id].remove(customer)
        if not self.queues[obj.object_id]:
            self.queues.pop(obj.object_id, None)
        a.served += 1
        obj.state["served"] = int(obj.state.get("served", 0)) + 1
        c.served_by = cid
        c.phase = "done"
        c.task_id = "served"
        a.accomplished.append(f"served:{customer}")
        self.event("SERVED", citizen_id=cid, customer_id=customer, object_id=obj.object_id,
                   building_id=a.building_id, room_id=a.room_id, served_total=a.served)
        self._maybe_dirty(obj, cid, a.served)

    def _complete(self, cid: int, ex: TripExecutor, a: ActivityState, reg: SmartObjectRegistry,
                  obj: SmartObject) -> None:
        task = self._task_def(a)
        self.event("USE_END", citizen_id=cid, elapsed_s=round(a.progress_s, 1), **self._where(ex, a))
        effect = task.effect if task else ""
        if effect == "clean" and obj.state.get("dirty"):
            obj.state["dirty"] = False
            a.cleaned += 1
            a.accomplished.append(f"cleaned:{obj.object_id}")
            self.event("STATE_CHANGE", citizen_id=cid, object_id=obj.object_id, key="dirty",
                       value=False, building_id=a.building_id, room_id=obj.room_id)
            if a.kind == "worker" and a.role == "cleaner":
                a.carrying = "" if (hash64(self.seed, "supplies", cid, a.task_instance) % 3 == 0) else a.carrying
        elif effect == "restock":
            obj.state["stock"] = 100
            a.restocked += 1
            a.carrying = ""
            a.accomplished.append(f"restocked:{obj.object_id}")
            self.event("STATE_CHANGE", citizen_id=cid, object_id=obj.object_id, key="stock",
                       value=100, building_id=a.building_id, room_id=obj.room_id)
        elif effect == "documents":
            obj.state["documents_done"] = int(obj.state.get("documents_done", 0)) + 1
            a.documents += 1
            a.accomplished.append(f"documents:{obj.object_id}")
            self.event("STATE_CHANGE", citizen_id=cid, object_id=obj.object_id, key="documents_done",
                       value=obj.state["documents_done"], building_id=a.building_id, room_id=obj.room_id)
            self._maybe_dirty(obj, cid, a.documents)
        elif effect in ("supplies", "goods"):
            a.carrying = effect
            if "supplies" in obj.state:
                obj.state["supplies"] = max(0, int(obj.state["supplies"]) - 10)
            if "stock" in obj.state and obj.has("storage"):
                obj.state["stock"] = max(0, int(obj.state["stock"]) - 10)
            self.event("STATE_CHANGE", citizen_id=cid, object_id=obj.object_id, key="carrying",
                       value=effect, building_id=a.building_id, room_id=obj.room_id)
        elif effect == "rest":
            a.worked_s = 0.0
            self.event("BREAK_END", citizen_id=cid, **self._where(ex, a))
        elif effect == "served":
            pass
        # residents / customers
        if a.kind == "customer" and effect == "" and task is None and a.task_id == "browse":
            self._deplete(obj, cid)
        self.event("TASK_END", citizen_id=cid, effect=effect, **self._where(ex, a))
        keep_station = (a.kind == "worker" and a.task_id in ("man_register", "serve_customer")
                        and self._task_def(a) is not None)
        if not keep_station:
            for oid in self.ledger.release(cid, obj.object_id):
                self.event("RESERVATION_RELEASED", citizen_id=cid, object_id=oid, reason="task complete")
        if a.kind == "customer" and a.task_id == "browse":
            a.task_id = "browsed"          # next: queue at a register
        elif a.kind == "customer" and a.task_id == "sit":
            a.task_id = "visited"
            a.phase = "done"
            a.next_s = 0.0
            return
        else:
            a.task_id = ""
        a.phase = "idle"
        a.next_s = 0.0
        if a.kind == "worker" and keep_station:
            # stay on station: a new instance of the same station task unless a break is due
            pass

    def _task_def(self, a: ActivityState) -> Optional[TaskDefinition]:
        role = ROLES.get(a.role)
        if role is None:
            return None
        for t in role.tasks:
            if t.task_id == a.task_id:
                return t
        return None

    def _maybe_dirty(self, obj: SmartObject, cid: int, n: int) -> None:
        if "dirty" in obj.state and not obj.state["dirty"] \
                and (hash64(self.seed, "dirt", obj.object_id, cid, n) % 100) < int(DIRT_ROLL * 100):
            obj.state["dirty"] = True
            self.event("STATE_CHANGE", citizen_id=cid, object_id=obj.object_id, key="dirty", value=True,
                       building_id=obj.building_id, room_id=obj.room_id)

    def _deplete(self, obj: SmartObject, cid: int) -> None:
        if "stock" in obj.state and obj.has("shelf"):
            obj.state["stock"] = max(0, int(obj.state["stock"]) - DEPLETE_PER_BROWSE)
            self.event("STATE_CHANGE", citizen_id=cid, object_id=obj.object_id, key="stock",
                       value=obj.state["stock"], building_id=obj.building_id, room_id=obj.room_id)

    def _object_lost(self, cid: int, ex: TripExecutor, a: ActivityState, reason: str) -> None:
        for oid in self.ledger.release(cid, a.object_id):
            self.event("RESERVATION_RELEASED", citizen_id=cid, object_id=oid, reason=reason)
        self.event("TASK_END", citizen_id=cid, effect="abandoned", reason=reason, **self._where(ex, a))
        a.task_id = ""
        a.object_id = None
        a.phase = "idle"
        a.waypoints = []
        a.next_s = 0.0

    # -- customers -------------------------------------------------------------------
    def _customer_next(self, cid: int, ex: TripExecutor, a: ActivityState,
                       reg: SmartObjectRegistry, g: RoomGraph) -> None:
        stations = reg.with_caps("station", "transact")
        if a.task_id == "":
            shelves = [o for o in reg.with_affordance("browse") if o.available()]
            if shelves and stations:
                k = hash64(self.seed, "browse", cid, a.session_start_s) % len(shelves)
                o = shelves[k]
                if self.ledger.hold(o, cid, self.now_s, exclusive=False):
                    a.task_id = "browse"
                    a.object_id = o.object_id
                    a.duration_s = 120.0
                    a.progress_s = 0.0
                    a.next_s = 0.0
                    self.event("TASK_START", citizen_id=cid, affordance="browse", duration_s=120.0,
                               **self._where(ex, a))
                    self._go_to(cid, ex, a, g, o.use_xy)
                    return
            if not stations:
                # not a shop: a visitor sits or stands (a seat if there is one)
                seat = self._nearest_free([o for o in reg.with_affordance("sit") if o.available()], a, cid)
                if seat is not None and self.ledger.hold(seat, cid, self.now_s, exclusive=seat.exclusive):
                    a.task_id = "sit"
                    a.object_id = seat.object_id
                    a.duration_s = 900.0
                    a.progress_s = 0.0
                    a.next_s = 0.0
                    self.event("TASK_START", citizen_id=cid, affordance="sit", duration_s=900.0,
                               **self._where(ex, a))
                    self._go_to(cid, ex, a, g, seat.use_xy)
                    return
                a.phase = "done"
                a.task_id = "visit"
                return
        # browsed (or nothing to browse): queue at a staffed register
        if a.task_id in ("", "browsed"):
            staffed = [o for o in stations if o.available() and self.ledger.holders_of(o.object_id)]
            pool = staffed or [o for o in stations if o.available()]
            workers_here = any(x.kind == "worker" and x.building_id == a.building_id
                               for x in self.activities.values())
            if not pool or (not staffed and not workers_here):
                # no register, or a shop with nobody on duty: the customer leaves at once
                a.phase = "done"
                a.task_id = "unserved"
                self.event("CUSTOMER_UNSERVED", citizen_id=cid,
                           reason="no register" if not pool else "shop closed (no staff present)",
                           **self._where(ex, a))
                return
            # the shortest queue, nearest first (a deterministic tie-break)
            o = min(pool, key=lambda s: (len(self.queues.get(s.object_id, [])),
                                         round(_d(ex.pos, s.use_xy), 3), s.object_id))
            q = self.queues.setdefault(o.object_id, [])
            q.append(cid)
            a.task_id = "checkout"
            a.object_id = o.object_id
            a.progress_s = 0.0
            a.wait_since_s = self.now_s
            a.phase = "waiting"
            a.next_s = 0.0
            self.event("CUSTOMER_QUEUED", citizen_id=cid, position=len(q), staffed=bool(staffed),
                       **self._where(ex, a))
            qi = len(q) - 1
            ux, uy = o.use_xy
            back = (ux + math.cos(o.facing) * QUEUE_SPACING_M * (qi + 1),
                    uy + math.sin(o.facing) * QUEUE_SPACING_M * (qi + 1))
            self._go_to(cid, ex, a, g, back)
            a.phase = "waiting"
            return
        if a.task_id in ("sit",):
            a.phase = "using"
        elif a.task_id in ("visited", "served", "unserved"):
            a.phase = "done"

    def _customer_wait(self, cid: int, ex: TripExecutor, a: ActivityState,
                       reg: SmartObjectRegistry, g: RoomGraph, dt: float) -> None:
        q = self.queues.get(a.object_id or "", [])
        obj = reg.get(a.object_id) if a.object_id else None
        staffed = obj is not None and obj.available() and bool(self.ledger.holders_of(obj.object_id))
        if cid in q and staffed:
            # progress is advanced by the cashier's _serve
            return
        if self.now_s - a.wait_since_s >= CUSTOMER_PATIENCE_S or obj is None or not obj.available():
            if cid in q:
                q.remove(cid)
                if not q:
                    self.queues.pop(a.object_id, None)
            a.phase = "done"
            a.task_id = "unserved"
            self.event("CUSTOMER_UNSERVED", citizen_id=cid, reason="no staffed register",
                       waited_s=round(self.now_s - a.wait_since_s, 1), **self._where(ex, a))
            self._flag_reduced(a.building_id, reg)

    # -- residents (non-work affordances) -------------------------------------------
    def _resident_next(self, cid: int, ex: TripExecutor, a: ActivityState,
                       reg: SmartObjectRegistry, g: RoomGraph) -> None:
        act = str(ex.activity or "")
        want = "sleep" if act == "sleep" else "sit"
        cands = [o for o in reg.with_affordance(want) if o.available()]
        if not cands:
            want = "sit" if want == "sleep" else "eat"
            cands = [o for o in reg.with_affordance(want) if o.available()]
        o = self._nearest_free(cands, a, cid) if cands else None
        if o is None or not self.ledger.hold(o, cid, self.now_s, exclusive=o.exclusive):
            a.phase = "done"
            a.task_id = "idle"
            return
        a.task_id = want
        a.object_id = o.object_id
        a.duration_s = 10.0 * 3600.0 if want == "sleep" else 4.0 * 3600.0
        a.progress_s = 0.0
        a.next_s = 0.0
        self.event("RESERVED", citizen_id=cid, object_id=o.object_id, exclusive=o.exclusive, task_id=want)
        self.event("TASK_START", citizen_id=cid, affordance=want, duration_s=a.duration_s, **self._where(ex, a))
        self._go_to(cid, ex, a, g, o.use_xy)

    # -- workplace function --------------------------------------------------------
    def workplace_status(self, bid: int) -> dict:
        reg = self.registry(bid)
        stations = reg.with_caps("station", "transact")
        staffed = [o.object_id for o in stations if o.available() and self.ledger.holders_of(o.object_id)]
        workers = [c for c, a in self.activities.items() if a.building_id == int(bid) and a.kind == "worker"]
        queued = sum(len(q) for oid, q in self.queues.items() if oid.startswith(f"so:{int(bid)}:"))
        status = "open"
        if stations and not staffed:
            status = "reduced_function" if workers else "closed"
        return {"building_id": int(bid), "stations": [o.object_id for o in stations],
                "staffed": staffed, "workers_present": sorted(workers), "customers_queued": queued,
                "status": status, "reduced": bool(self.reduced.get(int(bid), False))}

    def _flag_reduced(self, bid: int, reg: SmartObjectRegistry) -> None:
        st = self.workplace_status(bid)
        if st["status"] == "reduced_function" and not self.reduced.get(bid):
            self.reduced[bid] = True
            self.event("WORKPLACE_REDUCED_FUNCTION", building_id=int(bid), status=st["status"],
                       stations=len(st["stations"]), staffed=len(st["staffed"]))

    def _minute_scan(self) -> None:
        for bid in sorted(self.reduced):
            if self.reduced[bid] and self.workplace_status(bid)["status"] == "open":
                self.reduced[bid] = False
                self.event("WORKPLACE_RESTORED", building_id=int(bid))

    def set_object_state(self, object_id: str, key: str, value) -> Optional[SmartObject]:
        """Authoritative external change (a register breaks, a door closes)."""
        bid = int(object_id.split(":")[1])
        reg = self.registry(bid)
        o = reg.get(object_id)
        if o is None:
            return None
        o.state[key] = value
        self.event("STATE_CHANGE", citizen_id=None, object_id=object_id, key=key, value=value,
                   building_id=bid, room_id=o.room_id, source="external")
        if not o.available():
            for cid in self.ledger.release_object(object_id):
                self.event("OBJECT_UNAVAILABLE", citizen_id=cid, object_id=object_id)
                a = self.activities.get(cid)
                if a is not None and a.object_id == object_id:
                    ex = self.mobility.execs[cid]
                    self._object_lost(cid, ex, a, f"{key}={value}")
            for c in list(self.queues.pop(object_id, [])):
                ca = self.activities.get(c)
                if ca is not None:
                    ca.phase = "idle"
                    ca.task_id = ""
                    ca.object_id = None
            self._flag_reduced(bid, reg)
        return o

    # -- queries ---------------------------------------------------------------------
    def context(self, cid: int) -> dict:
        """Room/zone/object/task context of a citizen (for outbreak, dialogue…)."""
        ex = self.mobility.execs.get(cid)
        a = self.activities.get(cid)
        if ex is None or not ex.inside:
            return {"citizen_id": cid, "building_id": None, "room_id": None, "zone": None,
                    "object_id": None, "task_id": None, "role": None}
        bid = int(ex.building_id)
        g = self.graph(bid)
        rid = a.room_id if a is not None else g.room_of(ex.pos)
        emp = self.employment.get(cid)
        return {"citizen_id": cid, "building_id": bid, "room_id": rid, "zone": g.zone(rid),
                "object_id": a.object_id if a else None, "task_id": a.task_id if a else None,
                "phase": a.phase if a else None,
                "role": (a.role if a else (emp.role if emp and emp.workplace_id == bid else None))}

    def occupants_by_room(self, bid: int) -> Dict[int, List[int]]:
        out: Dict[int, List[int]] = {}
        g = self.graph(bid)
        for cid, ex in sorted(self.mobility.execs.items()):
            if ex.inside and ex.building_id == int(bid):
                a = self.activities.get(cid)
                rid = a.room_id if a is not None else g.room_of(ex.pos)
                out.setdefault(rid, []).append(cid)
        return out

    def row(self, cid: int) -> dict:
        a = self.activities.get(cid)
        emp = self.employment.get(cid)
        ex = self.mobility.execs.get(cid)
        rid = None
        if a is not None:
            rid = a.room_id
        elif ex is not None and ex.inside and ex.building_id in self.graphs:
            rid = self.graphs[ex.building_id].room_of(ex.pos)
        return {"role": (a.role if a else (emp.role if emp else None)),
                "workplace_id": emp.workplace_id if emp else None,
                "task": a.task_id if a else None, "phase": a.phase if a else None,
                "object_id": a.object_id if a else None, "room_id": rid,
                "zone": (self.graphs[a.building_id].zone(a.room_id) if a else None),
                "carrying": a.carrying if a else ""}

    def snapshot(self, since_seq: int = 0) -> dict:
        return {"now_s": self.now_s, "n_employed": len(self.employment),
                "n_sessions": len(self.activities),
                "sessions": {str(c): a.to_dict() for c, a in sorted(self.activities.items())},
                "reservations": self.ledger.to_state(),
                "queues": {k: list(v) for k, v in sorted(self.queues.items())},
                "events": [e for e in self.events if e["seq"] > int(since_seq)],
                "event_seq": self.event_seq, "counts": dict(sorted(self.counts.items())),
                "reduced": {str(b): v for b, v in sorted(self.reduced.items()) if v}}

    # -- persistence -----------------------------------------------------------------
    def to_state(self) -> dict:
        return {"version": 1, "seed": self.seed, "now_s": self.now_s, "next_minute_s": self._next_minute_s,
                "employment": {str(c): e.to_dict() for c, e in sorted(self.employment.items())},
                "activities": {str(c): a.to_dict() for c, a in sorted(self.activities.items())},
                "ledger": self.ledger.to_state(),
                "queues": {k: list(v) for k, v in sorted(self.queues.items())},
                "objects": {str(b): r.state_deltas() for b, r in sorted(self.registries.items())},
                "known_buildings": sorted(self.registries),
                "reduced": {str(b): v for b, v in sorted(self.reduced.items())},
                "events": list(self.events), "event_seq": self.event_seq,
                "counts": dict(sorted(self.counts.items())),
                "shift_log": list(self.shift_log)}

    @classmethod
    def from_state(cls, st: dict, mobility, descriptor_fn) -> "WorkRuntime":
        w = cls(mobility, int(st.get("seed", 0)), descriptor_fn)
        w.now_s = float(st.get("now_s", w.now_s))
        w._next_minute_s = float(st.get("next_minute_s", w.now_s))
        for c, e in (st.get("employment") or {}).items():
            w.employment[int(c)] = Employment(int(e["citizen_id"]), int(e["workplace_id"]), str(e["role"]),
                                              e.get("assigned_object"), str(e.get("occupation", "")))
        w._pending_deltas = {int(b): d for b, d in (st.get("objects") or {}).items()}
        for b in st.get("known_buildings") or []:
            w.registry(int(b))
        for c, a in (st.get("activities") or {}).items():
            w.activities[int(c)] = ActivityState.from_dict(a)
        w.ledger = ReservationLedger.from_state(st.get("ledger") or {})
        w.queues = {k: [int(c) for c in v] for k, v in (st.get("queues") or {}).items()}
        w.reduced = {int(b): bool(v) for b, v in (st.get("reduced") or {}).items()}
        w.events = list(st.get("events") or [])
        w.event_seq = int(st.get("event_seq", 0))
        w.counts = {str(k): int(v) for k, v in (st.get("counts") or {}).items()}
        w.shift_log = list(st.get("shift_log") or [])
        return w

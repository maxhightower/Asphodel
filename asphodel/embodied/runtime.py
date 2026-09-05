"""MobilityRuntime — the one movement authority World.step drives (ASPHODEL_EMBODIED_MOBILITY_V1).

    schedule -> goals -> CitizenRuntime planner -> itinerary
             -> TripExecutor (this runtime advances it) -> Godot embodiment

Owns, for every embodied citizen: its :class:`CitizenRuntime` (planner), its
:class:`TripExecutor` (execution state), its persistent :class:`VehicleInstance`
(one identity through spawn/park/enter/drive/exit/save/load/LOD), parking
occupancy, the distance-banded LOD state, and the physical-report
reconciliation from Godot bodies. Everything is deterministic in
``(bundle, seed, citizen set, sequence of advance(dt) calls)`` and consumes no
simulation RNG.

Tiers (§17):

    ABSTRACT          not registered here: `embodiment.resolve_physical_location`
                      (schedule state) stays the FAR authority
    ROUTE_SIMULATED   registered + active: itinerary executed here, no body
                      (frozen when far from focus; caught up on re-activation)
    PHYSICAL          registered + within the physical radius of the focus:
                      a Godot CitizenBody/VehicleBody embodies it and physics
                      reconciles progress through `apply_physical_report`
"""
from __future__ import annotations

import gzip
import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..citizen import ScheduleEntry
from ..citizens import CitizenRuntime, ScheduleSlot
from ..citizens.planning import Mode
from ..lod.entity import LODBand, LODController
from ..mobility import MobilityGraph
from ..transport import TrafficReconciler, VehicleFidelity, VehicleInstance
from .executor import EmbodimentState, TripExecutor
from .parking import ParkingIndex, choose_parking
from .pathing import attach_anchor
from .vehicle_control import OtherVehicle, VehicleParams

Vec2 = Tuple[float, float]

MOBILITY_SCHEMA_VERSION = 1
SUBSTEP_S = 1.0            # fixed integration step (game seconds); determinism
CATCHUP_SUBSTEP_S = 5.0    # coarse step used to fast-forward a re-activated citizen
MAX_FAILURES_PER_GOAL = 3
RETRY_WAIT_S = 120.0


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def load_entrances(bundle_dir: str) -> Tuple[Dict[int, Vec2], List[list]]:
    """BUILDING_ENTRANCE anchors by building id + the raw anchor rows."""
    path = os.path.join(bundle_dir, "world", "spawn_anchors.json.gz")
    if not os.path.exists(path):
        return {}, []
    with gzip.open(path, "rt") as f:
        rows = json.load(f)["anchors"]
    ent: Dict[int, Vec2] = {}
    for kind, x, z, bid in rows:
        if kind == "BUILDING_ENTRANCE" and bid >= 0 and int(bid) not in ent:
            ent[int(bid)] = (float(x), float(z))
    return ent, rows


@dataclass
class CitizenRecord:
    citizen_id: int
    home_building_id: int
    work_building_id: Optional[int]
    schedule: List[ScheduleEntry]
    has_vehicle: bool
    home_xy: Vec2
    work_xy: Optional[Vec2]


class MobilityRuntime:
    def __init__(self, graph: MobilityGraph, entrances: Dict[int, Vec2],
                 anchors: Sequence[list], ctx=None, bundle_dir: Optional[str] = None,
                 seed: int = 0, lod: Optional[LODController] = None):
        self.graph = graph
        self.ctx = ctx
        self.bundle_dir = bundle_dir
        self.seed = int(seed)
        self.entrances = entrances
        self.parking = ParkingIndex(bundle_dir, list(anchors), entrances)
        self.lod = lod or LODController(physical_radius=150.0, near_radius=400.0,
                                        route_radius=2500.0, hysteresis=40.0)
        self.max_active = 256          # ROUTE_SIMULATED budget before ABSTRACT overflow
        self.now_s = 0.0
        self.focus_xy: Optional[Vec2] = None
        self.records: Dict[int, CitizenRecord] = {}
        self.citizens: Dict[int, CitizenRuntime] = {}
        self.execs: Dict[int, TripExecutor] = {}
        self.vehicles: Dict[str, VehicleInstance] = {}
        self.vehicle_of: Dict[int, str] = {}
        self.reconciler = TrafficReconciler(graph)
        self.bands: Dict[int, LODBand] = {}
        self.frozen_at: Dict[int, float] = {}     # cid -> now_s when deactivated
        self._last_slot: Dict[int, str] = {}
        self._retry_at: Dict[int, float] = {}
        self._accum = 0.0
        self.route_ms: List[float] = []            # route timings (perf evidence)
        self.events: List[dict] = []
        self.transitions: List[dict] = []           # LOD promotions / demotions
        self.unregistered: Dict[int, str] = {}      # cid -> reason it stays FAR

    # -- registration --------------------------------------------------------
    def node_for_building(self, bid: int) -> Optional[str]:
        key = f"ent:{bid}"
        xy = self.entrances.get(int(bid))
        if xy is None:
            xy = self.ctx.building_xy(int(bid)) if self.ctx is not None else None
        if xy is None:
            return None
        got = attach_anchor(self.graph, key, xy, [Mode.FOOT], Mode.FOOT)
        return None if got is None else got[0]

    def entrance_of(self, bid: Optional[int]) -> Optional[Vec2]:
        if bid is None or bid < 0:
            return None
        xy = self.entrances.get(int(bid))
        if xy is None and self.ctx is not None:
            xy = self.ctx.building_xy(int(bid))
        return xy

    def _errand_building(self, home_bid: int, home_xy: Vec2) -> Optional[int]:
        """A deterministic nearby non-home building with an entrance."""
        if self.ctx is None:
            return None
        best, bestd = None, math.inf
        cents = self.ctx.building_centroids
        if cents.shape[0] == 0:
            return None
        import numpy as np
        d2 = (cents[:, 0] - home_xy[0]) ** 2 + (cents[:, 1] - home_xy[1]) ** 2
        for idx in np.argsort(d2, kind="stable")[:40]:
            b = int(idx)
            if b == home_bid or b not in self.entrances:
                continue
            d = float(d2[idx])
            if 30.0 ** 2 <= d < bestd:
                best, bestd = b, d
        return best

    def register(self, profile, now_hour: float, activate: bool = True,
                 spawn_vehicle: bool = True) -> bool:
        """Register a canonical citizen (CitizenProfile / _CitizenLite)."""
        cid = int(profile.citizen_id)
        if cid in self.execs:
            return True
        hb = getattr(profile, "home_building_id", None)
        wb = getattr(profile, "work_building_id", None)
        if hb is None:
            return False
        home_node = self.node_for_building(int(hb))
        if home_node is None:
            # Explicit, not silent: this citizen stays a FAR (schedule-state)
            # citizen because its home entrance is not at a walkable street.
            self.events.append({"t": self.now_s, "event": "unregistered", "citizen_id": cid,
                                "reason": "home entrance not within %.0f m of a foot street" % 60.0,
                                "building_id": int(hb)})
            self.unregistered[cid] = "no_street_access"
            return False
        work_node = self.node_for_building(int(wb)) if wb is not None else None
        home_xy = self.entrances.get(int(hb)) or tuple(profile.home_xy)
        errand_bid = self._errand_building(int(hb), home_xy)
        errand_node = self.node_for_building(errand_bid) if errand_bid is not None else None
        inv = dict(getattr(profile, "inventory", {}) or {})
        has_vehicle = bool(inv.get("car_keys") or inv.get("keys"))
        sched = list(getattr(profile, "schedule", []) or [])
        slots = self._slots(sched, home_node, work_node or home_node, errand_node or home_node)
        rt = CitizenRuntime(str(cid), home_node, work_node or home_node, slots,
                            has_vehicle=has_vehicle, vehicle_node=home_node)
        rt.node_meta[home_node] = {"building_id": int(hb), "xy": home_xy}
        if work_node is not None:
            rt.node_meta[work_node] = {"building_id": int(wb), "xy": self.entrances.get(int(wb))}
        if errand_node is not None:
            rt.node_meta[errand_node] = {"building_id": int(errand_bid),
                                         "xy": self.entrances.get(int(errand_bid))}
        rt.parking_resolver = lambda dest, _cid=cid: self._resolve_parking(_cid, dest)
        rt.vehicle_id = f"veh:{cid}" if has_vehicle else None
        self.records[cid] = CitizenRecord(cid, int(hb), None if wb is None else int(wb),
                                          sched, has_vehicle, home_xy,
                                          self.entrances.get(int(wb)) if wb is not None else None)
        self.citizens[cid] = rt
        # initial situation from the schedule: inside the block's building (no teleport later)
        from ..citizen import _current_block
        block = _current_block(sched, now_hour % 24.0) if sched else None
        act = block.activity if block is not None else "sleep"
        start_bid = int(hb)
        if act == "work" and wb is not None:
            start_bid = int(wb)
        start_xy = self.entrances.get(start_bid) or home_xy
        ex = TripExecutor(cid, (float(start_xy[0]), float(start_xy[1])),
                          state=EmbodimentState.INSIDE_BUILDING, building_id=start_bid)
        ex.activity = act if act in ("sleep", "work", "leisure") else "idle"
        self.execs[cid] = ex
        rt.note_situation(node=self.node_for_building(start_bid), inside_building=True)
        if has_vehicle and spawn_vehicle:
            self._spawn_vehicle(cid, rt, start_bid)
        self.bands[cid] = LODBand.ROUTE_SIMULATED
        if not activate:
            self.frozen_at[cid] = self.now_s
        return True

    def _slots(self, sched: List[ScheduleEntry], home: str, work: str, errand: str) -> List[ScheduleSlot]:
        out: List[ScheduleSlot] = []
        n = len(sched)
        for i, e in enumerate(sched):
            act = e.activity
            if act == "work":
                node = work
            elif act == "errand":
                node = errand
            elif act == "commute":
                nxt = sched[(i + 1) % n].activity if n else "work"
                node = work if nxt == "work" else home
                act = "commute" if node == work else "commute_home"
            else:
                node = home
            out.append(ScheduleSlot(float(e.start_hour), float(e.end_hour), act, node,
                                    getattr(e, "task", None) or None))
        return out

    def _spawn_vehicle(self, cid: int, rt: CitizenRuntime, near_bid: int) -> None:
        vid = f"veh:{cid}"
        dest_xy = self.entrances.get(near_bid)
        choice = None
        if dest_xy is not None:
            choice = choose_parking(self.parking, self.graph, dest_xy, self._polys_near,
                                    exclude_vehicle=vid)
        veh = VehicleInstance(vid, "car", owner=str(cid))
        if choice is None:
            # No valid parking near the start building: the citizen has no usable
            # car today (explicit, not faked) — plans fall back to walking.
            rt.has_vehicle = False
            rt.vehicle_id = None
            self.events.append({"t": self.now_s, "event": "no_parking_for_vehicle",
                                "citizen_id": cid, "building_id": near_bid})
            return
        node = attach_anchor(self.graph, choice.node_id, choice.xy, [Mode.CAR, Mode.FOOT], Mode.CAR)
        if node is None:
            rt.has_vehicle = False
            rt.vehicle_id = None
            return
        veh.parked_location = choice.xy
        veh._pts = [choice.xy]
        veh._cum = [0.0]
        veh.fidelity = VehicleFidelity.ROUTE_SIMULATED
        self.vehicles[vid] = veh
        self.vehicle_of[cid] = vid
        self.reconciler.add_vehicle(veh)
        self.parking.occupy(choice.index, vid, choice.xy)
        rt.vehicle_node = choice.node_id
        rt.node_meta[choice.node_id] = {"xy": choice.xy, "parking_index": choice.index}
        self.events.append({"t": self.now_s, "event": "vehicle_spawned", "vehicle_id": vid,
                            "citizen_id": cid, "parking": choice.to_dict()})

    def _polys_near(self, xy: Vec2, r: float) -> list:
        if self.ctx is None or not self.ctx.building_polys:
            return []
        import numpy as np
        cents = self.ctx.building_centroids
        d2 = (cents[:, 0] - xy[0]) ** 2 + (cents[:, 1] - xy[1]) ** 2
        idx = np.nonzero(d2 <= (r + 60.0) ** 2)[0]
        return [self.ctx.building_polys[int(i)] for i in idx if self.ctx.building_polys[int(i)]]

    def _resolve_parking(self, cid: int, dest_node: str) -> Optional[Tuple[str, Vec2]]:
        rt = self.citizens[cid]
        meta = rt.node_meta.get(dest_node) or {}
        dest_xy = meta.get("xy")
        if dest_xy is None:
            dest_xy = self.graph.nodes.get(dest_node)
        if dest_xy is None:
            return None
        vid = self.vehicle_of.get(cid)
        choice = choose_parking(self.parking, self.graph, dest_xy, self._polys_near,
                                exclude_vehicle=vid)
        if choice is None:
            return None
        got = attach_anchor(self.graph, choice.node_id, choice.xy, [Mode.CAR, Mode.FOOT], Mode.CAR)
        if got is None:
            return None
        rt.node_meta[choice.node_id] = {"xy": choice.xy, "parking_index": choice.index}
        ex = self.execs.get(cid)
        if ex is not None:
            ex.event(self.now_s, "parking_chosen", parking=choice.to_dict())
        return choice.node_id, choice.xy

    def parking_occupy(self, node: Optional[str], veh: VehicleInstance) -> None:
        if node is None:
            return
        cid = int(veh.owner) if veh.owner is not None and veh.owner.isdigit() else None
        meta = (self.citizens[cid].node_meta.get(node) if cid in self.citizens else None) or {}
        idx = meta.get("parking_index")
        if idx is not None:
            self.parking.occupy(int(idx), veh.vehicle_id, veh.parked_location)

    # -- LOD / focus ----------------------------------------------------------
    def set_focus_xy(self, xy: Optional[Vec2]) -> None:
        self.focus_xy = None if xy is None else (float(xy[0]), float(xy[1]))

    def activate(self, cid: int) -> None:
        """ABSTRACT -> ROUTE_SIMULATED: catch the frozen citizen up to now."""
        t0 = self.frozen_at.pop(cid, None)
        if t0 is None:
            return
        gap = self.now_s - t0
        self.transitions.append({"t": self.now_s, "citizen_id": cid, "from": "abstract",
                                 "to": "route_simulated", "catch_up_s": round(gap, 1)})
        saved_now = self.now_s
        self.now_s = t0
        while gap > 1e-9:
            dt = min(CATCHUP_SUBSTEP_S, gap)
            self._advance_one(cid, dt)
            self.now_s += dt
            gap -= dt
        self.now_s = saved_now

    def deactivate(self, cid: int) -> None:
        if cid in self.execs and cid not in self.frozen_at:
            self.frozen_at[cid] = self.now_s
            self.bands[cid] = LODBand.ABSTRACT
            self.transitions.append({"t": self.now_s, "citizen_id": cid,
                                     "from": "route_simulated", "to": "abstract"})

    def _update_bands(self) -> None:
        if self.focus_xy is None:
            return
        # ABSTRACT (frozen + catch-up) is an overflow band: every registered
        # citizen stays ROUTE_SIMULATED until more than `max_active` are
        # registered, then the farthest beyond the route radius freeze.
        dists = {cid: _d(self.execs[cid].pos, self.focus_xy) for cid in self.execs}
        overflow: set = set()
        if len(dists) > self.max_active:
            far = sorted((d, cid) for cid, d in dists.items() if d > self.lod.route_radius)
            overflow = {cid for _, cid in far[max(0, len(far) - (len(dists) - self.max_active)):]}
        for cid in sorted(self.execs):
            ex = self.execs[cid]
            d = dists[cid]
            cur = self.bands.get(cid, LODBand.ROUTE_SIMULATED)
            new = self.lod.band_for(d, cur)
            if new == LODBand.NEAR_SIMPLIFIED:
                new = LODBand.ROUTE_SIMULATED     # V1: no separate near-simplified citizen tier
            if new == LODBand.ABSTRACT and cid not in overflow:
                new = LODBand.ROUTE_SIMULATED
            if new != cur:
                self.transitions.append({"t": self.now_s, "citizen_id": cid,
                                         "from": cur.name.lower(), "to": new.name.lower(),
                                         "distance": round(d, 1),
                                         "pos": [round(ex.pos[0], 1), round(ex.pos[1], 1)],
                                         "step": ex.step_index, "state": ex.state.value})
                self.bands[cid] = new
                if new == LODBand.ABSTRACT:
                    self.frozen_at.setdefault(cid, self.now_s)
                elif cur == LODBand.ABSTRACT:
                    self.activate(cid)
            ex.has_body = (self.bands[cid] == LODBand.PHYSICAL)

    def near_ids(self) -> List[int]:
        return [cid for cid in sorted(self.execs) if self.bands.get(cid) == LODBand.PHYSICAL]

    # -- environment queries used by executors --------------------------------
    def moving_vehicles_near(self, xy: Vec2, radius: float) -> List[Tuple[Vec2, float]]:
        out = []
        for vid in sorted(self.vehicles):
            v = self.vehicles[vid]
            if v.speed < 0.3:
                continue
            p = v.position()
            if _d(p, xy) <= radius:
                out.append((p, v.speed))
        return out

    def other_vehicles(self, own_id: str, xy: Vec2) -> List[OtherVehicle]:
        out: List[OtherVehicle] = []
        for vid in sorted(self.vehicles):
            if vid == own_id:
                continue
            v = self.vehicles[vid]
            p = v.position()
            if _d(p, xy) > 120.0:
                continue
            ex = self._exec_of_vehicle(vid)
            nj, jd = (None, math.inf)
            heading = 0.0
            if ex is not None and ex.car is not None:
                nj, jd = ex.car.next_junction()
                heading = ex.car.heading
            out.append(OtherVehicle(vid, p, float(v.speed), heading, nj, jd))
        return out

    def _exec_of_vehicle(self, vid: str) -> Optional[TripExecutor]:
        for cid, ex in self.execs.items():
            if ex.vehicle_id == vid:
                return ex
        return None

    def vehicle_params(self, veh: Optional[VehicleInstance]) -> VehicleParams:
        return VehicleParams()

    def distance_walked_base(self, ex: TripExecutor) -> float:
        return float(getattr(ex, "_walk_base", 0.0))

    def distance_driven_base(self, ex: TripExecutor) -> float:
        return float(getattr(ex, "_drive_base", 0.0))

    # -- failure policy (§16) -------------------------------------------------
    def on_failure(self, ex: TripExecutor, rt: CitizenRuntime, reason: str) -> None:
        cid = ex.citizen_id
        self.events.append({"t": self.now_s, "event": "failure", "citizen_id": cid,
                            "reason": reason, "step": ex.step_index})
        if ex.failures > MAX_FAILURES_PER_GOAL:
            ex.trip_failed = True
            ex.state = EmbodimentState.TRIP_FAILED
            ex.speed = 0.0
            rt.current_failure = f"trip failed: {reason}"
            self.events.append({"t": self.now_s, "event": "trip_failed", "citizen_id": cid,
                                "reason": reason})
            return
        if reason.startswith("vehicle unavailable") or reason.startswith("vehicle too far"):
            # fall back to walking this trip
            rt.has_vehicle = False
            rt.in_vehicle = False
            rt.on_blockage(self.graph, reason)
            return
        # otherwise: wait, then retry the same plan
        self._retry_at[cid] = self.now_s + RETRY_WAIT_S
        rt.on_blockage(self.graph, reason)

    def on_blocked(self, ex: TripExecutor, rt: CitizenRuntime, reason: str) -> None:
        self.events.append({"t": self.now_s, "event": "blocked", "citizen_id": ex.citizen_id,
                            "reason": reason})
        rt.on_blockage(self.graph, reason)

    # -- advancing ------------------------------------------------------------
    def advance(self, dt_s: float, now_hour: float) -> None:
        """Advance every active citizen by ``dt_s`` game seconds (fixed substeps)."""
        self._accum += float(dt_s)
        # The hour advances with every substep (one ADVANCE may span a long
        # stretch of game time; a schedule boundary inside it must be seen).
        hour_base, t_base = float(now_hour), self.now_s
        while self._accum >= SUBSTEP_S - 1e-9:
            self._substep(SUBSTEP_S, hour_base + (self.now_s - t_base) / 3600.0)
            self._accum -= SUBSTEP_S
        self._update_bands()

    def _substep(self, dt: float, now_hour: float) -> None:
        hour = now_hour % 24.0
        sync_now = (int(self.now_s) % 60 == 0)
        for cid in sorted(self.execs):
            if cid in self.frozen_at:
                continue
            if sync_now or cid not in self._last_slot:
                self._sync(cid, hour)
            ex = self.execs[cid]
            # An idle citizen inside a building with nothing to execute costs
            # nothing between schedule syncs (the LOD budget lives here).
            if ex.override in ("incapacitated", "corpse"):
                continue
            if ex.current_step is None and ex.inside and self.citizens[cid].plan_serial == ex.plan_serial:
                continue
            self._advance_one(cid, dt)
        # FAR congestion from MID vehicles: a city-wide pass, so once a game minute.
        if int(self.now_s) % 60 == 0:
            self.reconciler.update_congestion()
        self.now_s += dt

    def _sync(self, cid: int, hour: float) -> None:
        rt = self.citizens[cid]
        slot = rt.current_slot(hour)
        key = f"{slot.start_hour}:{slot.activity}:{slot.location_node}" if slot else "none"
        ex = self.execs[cid]
        if self._last_slot.get(cid) != key or (ex.trip_failed and self._retry_at.get(cid, math.inf) <= self.now_s):
            self._last_slot[cid] = key
            self._retry_at.pop(cid, None)
            t0 = _perf()
            rt.sync_schedule(hour, self.graph)
            self.route_ms.append((_perf() - t0) * 1000.0)

    def _advance_one(self, cid: int, dt: float) -> None:
        rt = self.citizens[cid]
        ex = self.execs[cid]
        ex.advance(dt, rt, self)

    # -- physical reports (NEAR bodies) ---------------------------------------
    def apply_physical_report(self, bodies: Sequence[dict], dt: float) -> int:
        """Godot reports where physics put each embodied body. Returns the
        number of reports applied (ids that are not embodied are ignored)."""
        n = 0
        for b in bodies:
            bid = str(b.get("id", ""))
            x, z = float(b.get("x", 0.0)), float(b.get("z", 0.0))
            blocked = bool(b.get("blocked", False))
            if bid.startswith("cit:"):
                cid = int(bid[4:])
                ex = self.execs.get(cid)
                if ex is None or not ex.has_body:
                    continue
                if ex.state in (EmbodimentState.ON_FOOT, EmbodimentState.APPROACHING_VEHICLE,
                                EmbodimentState.DRIVING):
                    ex.reconcile_physical((x, z), blocked, dt, self)
                    n += 1
            elif bid.startswith("veh:"):
                ex = self._exec_of_vehicle(bid)
                if ex is None or not ex.has_body or ex.state != EmbodimentState.DRIVING:
                    continue
                ex.reconcile_physical((x, z), blocked, dt, self)
                n += 1
        return n

    # -- snapshot -------------------------------------------------------------
    def citizen_row(self, cid: int) -> dict:
        ex = self.execs[cid]
        rt = self.citizens[cid]
        step = ex.current_step
        veh = self.vehicles.get(ex.vehicle_id or "")
        return {
            "citizen_id": cid,
            "x": round(ex.pos[0], 3), "y": round(ex.pos[1], 3),
            "heading": round(ex.heading, 4), "speed": round(ex.speed, 3),
            "state": ex.state.value, "activity": ex.activity,
            "building_id": ex.building_id, "vehicle_id": ex.vehicle_id,
            "step": None if step is None else step.kind.value,
            "step_index": ex.step_index,
            "n_steps": 0 if ex.itinerary is None else len(ex.itinerary.steps),
            "progress": round(ex.route_progress(), 4),
            "destination": (None if ex.destination() is None
                            else [round(ex.destination()[0], 2), round(ex.destination()[1], 2)]),
            "band": self.bands.get(cid, LODBand.ROUTE_SIMULATED).name.lower(),
            "goal": None if rt.active_goal is None else rt.active_goal.kind.value,
            "goal_target": None if rt.active_goal is None else rt.active_goal.target,
            "override": ex.override,
            "failure": ex.failure or rt.current_failure or "",
            "trip_failed": ex.trip_failed,
            "blocked": bool((ex.car and ex.car.blocked) or (ex.ped and ex.ped.blocked)),
            "in_vehicle_speed": None if veh is None else round(veh.speed, 2),
        }

    def vehicle_row(self, vid: str) -> dict:
        v = self.vehicles[vid]
        p = v.position()
        ex = self._exec_of_vehicle(vid)
        return {
            "vehicle_id": vid, "type": v.vtype, "owner": v.owner, "driver": v.driver,
            "x": round(p[0], 3), "y": round(p[1], 3),
            "heading": round(ex.heading if ex is not None and ex.state == EmbodimentState.DRIVING
                             else float(getattr(v, "_heading", 0.0)), 4),
            "speed": round(v.speed, 3), "fidelity": v.fidelity.value,
            "engine": v.engine_state, "parked": v.parked_location is not None,
            "progress": round(v.route_progress, 4),
            "segment": v.current_segment(self.graph) if v.route else None,
            "condition": v.condition,
            "band": ("physical" if (ex is not None and ex.has_body and ex.state == EmbodimentState.DRIVING)
                     or (self.focus_xy is not None and _d(p, self.focus_xy) <= self.lod.physical_radius)
                     else "route_simulated"),
        }

    def snapshot(self, include_routes: bool = True, max_route_points: int = 400) -> dict:
        near = self.near_ids()
        rows = [self.citizen_row(cid) for cid in sorted(self.execs)]
        vrows = [self.vehicle_row(vid) for vid in sorted(self.vehicles)]
        out = {"version": MOBILITY_SCHEMA_VERSION, "t_s": round(self.now_s, 3),
               "focus_xy": None if self.focus_xy is None else [self.focus_xy[0], self.focus_xy[1]],
               "n_citizens": len(rows), "n_vehicles": len(vrows),
               "near": [f"cit:{c}" for c in near],
               "citizens": rows, "vehicles": vrows}
        if include_routes:
            routes = {}
            for cid in near:
                pts = self.execs[cid].route_ahead(max_route_points)
                if pts:
                    routes[f"cit:{cid}"] = [[round(p[0], 2), round(p[1], 2)] for p in pts]
            out["routes"] = routes
        return out

    # -- persistence -----------------------------------------------------------
    def to_state(self) -> dict:
        return {
            "version": MOBILITY_SCHEMA_VERSION,
            "now_s": float(self.now_s), "accum": float(self._accum),
            "focus_xy": None if self.focus_xy is None else [self.focus_xy[0], self.focus_xy[1]],
            "citizens": {str(cid): {
                "runtime": self._runtime_state(self.citizens[cid]),
                "executor": self.execs[cid].to_state(),
                "band": self.bands.get(cid, LODBand.ROUTE_SIMULATED).name,
                "frozen_at": self.frozen_at.get(cid),
                "last_slot": self._last_slot.get(cid),
                "retry_at": self._retry_at.get(cid),
            } for cid in sorted(self.execs)},
            "vehicles": {vid: self._vehicle_state(self.vehicles[vid]) for vid in sorted(self.vehicles)},
            "vehicle_of": {str(k): v for k, v in sorted(self.vehicle_of.items())},
            "parking_occupied": {str(k): v for k, v in sorted(self.parking.occupied.items())},
            "parking_nodes": {n: [xy[0], xy[1]] for n, xy in sorted(self._parking_nodes().items())},
            # live graph state that routes/costs depend on (bit-identical continuation)
            "congestion": {sid: seg.dynamic_state.congestion
                           for sid, seg in sorted(self.graph.segments.items())
                           if seg.dynamic_state.congestion != 1.0},
            "obstructions": [self._obstruction_state(o)
                             for _, o in sorted(self.graph._obstructions.items())],
        }

    @staticmethod
    def _obstruction_state(o) -> dict:
        return {"id": o.id, "kind": o.kind.value, "affected_segment": o.affected_segment,
                "location": None if o.location is None else [o.location[0], o.location[1]],
                "severity": float(o.severity),
                "modes_affected": None if o.modes_affected is None else sorted(m.value for m in o.modes_affected),
                "source_entity": o.source_entity}

    def _parking_nodes(self) -> Dict[str, Vec2]:
        out = {}
        for rt in self.citizens.values():
            for n, m in rt.node_meta.items():
                if n.startswith("park:") and m.get("xy") is not None:
                    out[n] = (float(m["xy"][0]), float(m["xy"][1]))
        return out

    @staticmethod
    def _runtime_state(rt: CitizenRuntime) -> dict:
        return {
            "current_node": rt.current_node, "destination": rt.destination,
            "inside_building": rt.inside_building, "in_vehicle": rt.in_vehicle,
            "vehicle_node": rt.vehicle_node, "vehicle_id": rt.vehicle_id,
            "has_vehicle": rt.has_vehicle, "plan_serial": rt.plan_serial,
            "current_activity": rt.current_activity, "current_failure": rt.current_failure,
            "last_replan_reason": rt.last_replan_reason,
            "itinerary": None if rt.itinerary is None else rt.itinerary.to_state(),
            "active_goal": None if rt.active_goal is None else rt.active_goal.to_dict(),
            "goals": [g.to_dict() for g in rt.goals.goals],
            "goal_seq": int(rt.goals.seq),
            "node_meta": {n: {"building_id": m.get("building_id"),
                              "xy": (None if m.get("xy") is None else [m["xy"][0], m["xy"][1]]),
                              "parking_index": m.get("parking_index")}
                          for n, m in sorted(rt.node_meta.items())},
        }

    @staticmethod
    def _vehicle_state(v: VehicleInstance) -> dict:
        return {"vehicle_id": v.vehicle_id, "vtype": v.vtype, "owner": v.owner,
                "driver": v.driver, "fidelity": v.fidelity.value,
                "distance_along": float(v.distance_along), "speed": float(v.speed),
                "fuel": v.fuel, "condition": v.condition, "engine_state": v.engine_state,
                "parked_location": None if v.parked_location is None else
                [v.parked_location[0], v.parked_location[1]],
                "position": list(v.position())}

    @classmethod
    def from_state(cls, state: dict, graph: MobilityGraph, entrances: Dict[int, Vec2],
                   anchors: Sequence[list], profiles: Dict[int, object], ctx=None,
                   bundle_dir: Optional[str] = None, seed: int = 0) -> "MobilityRuntime":
        from ..citizens.goals import Goal, GoalKind
        rt_obj = cls(graph, entrances, anchors, ctx=ctx, bundle_dir=bundle_dir, seed=seed)
        rt_obj.now_s = float(state.get("now_s", 0.0))
        rt_obj._accum = float(state.get("accum", 0.0))
        f = state.get("focus_xy")
        rt_obj.focus_xy = None if f is None else (float(f[0]), float(f[1]))
        # parking nodes must exist before routes through them are restored
        for node, xy in (state.get("parking_nodes") or {}).items():
            attach_anchor(graph, node, (float(xy[0]), float(xy[1])), [Mode.CAR, Mode.FOOT], Mode.CAR)
        # vehicles
        for vid, vs in (state.get("vehicles") or {}).items():
            v = VehicleInstance(vid, vs.get("vtype", "car"), owner=vs.get("owner"),
                                driver=vs.get("driver"))
            v.fidelity = VehicleFidelity(vs.get("fidelity", "route_simulated"))
            v.distance_along = float(vs.get("distance_along", 0.0))
            v.speed = float(vs.get("speed", 0.0))
            v.fuel = vs.get("fuel", 1.0)
            v.condition = vs.get("condition", 1.0)
            v.engine_state = vs.get("engine_state", "off")
            pl = vs.get("parked_location")
            v.parked_location = None if pl is None else (float(pl[0]), float(pl[1]))
            pos = vs.get("position") or pl or [0.0, 0.0]
            v._pts = [(float(pos[0]), float(pos[1]))]
            v._cum = [0.0]
            rt_obj.vehicles[vid] = v
            rt_obj.reconciler.add_vehicle(v)
        rt_obj.vehicle_of = {int(k): v for k, v in (state.get("vehicle_of") or {}).items()}
        # citizens: rebuild planner from profile + restore its state, then executor
        for cid_s, cs in (state.get("citizens") or {}).items():
            cid = int(cid_s)
            prof = profiles.get(cid)
            if prof is None:
                continue
            rt_obj.register(prof, 0.0, activate=True, spawn_vehicle=False)
            rt = rt_obj.citizens[cid]
            rs = cs["runtime"]
            saved_vid = (state.get("vehicle_of") or {}).get(str(cid))
            if saved_vid is not None:
                rt_obj.vehicle_of[cid] = saved_vid
            else:
                rt_obj.vehicle_of.pop(cid, None)
            for n, m in (rs.get("node_meta") or {}).items():
                xy = m.get("xy")
                rt.node_meta[n] = {"building_id": m.get("building_id"),
                                   "xy": None if xy is None else (float(xy[0]), float(xy[1])),
                                   "parking_index": m.get("parking_index")}
                if n.startswith("park:") and xy is not None and n not in graph.nodes:
                    attach_anchor(graph, n, (float(xy[0]), float(xy[1])), [Mode.CAR, Mode.FOOT], Mode.CAR)
            rt.current_node = rs.get("current_node", rt.current_node)
            rt.destination = rs.get("destination")
            rt.inside_building = bool(rs.get("inside_building", True))
            rt.in_vehicle = bool(rs.get("in_vehicle", False))
            rt.vehicle_node = rs.get("vehicle_node", rt.vehicle_node)
            rt.vehicle_id = rs.get("vehicle_id")
            rt.has_vehicle = bool(rs.get("has_vehicle", False))
            rt.plan_serial = int(rs.get("plan_serial", 0))
            rt.current_activity = rs.get("current_activity", "idle")
            rt.current_failure = rs.get("current_failure", "")
            rt.last_replan_reason = rs.get("last_replan_reason", "")
            from ..citizens.planning import Itinerary
            it = rs.get("itinerary")
            rt.itinerary = None if it is None else Itinerary.from_state(it)
            rt.goals.goals = []
            rt.goals.seq = int(rs.get("goal_seq", 0))
            for gd in rs.get("goals") or []:
                g = Goal(GoalKind(gd["kind"]), gd["target"], gd.get("reason", ""),
                         gd.get("source", "schedule"), float(gd.get("priority", 0.5)),
                         gd.get("deadline"), gd.get("activity"))
                g.id = int(gd["id"])
                rt.goals.goals.append(g)
            ag = rs.get("active_goal")
            if ag is not None:
                rt.active_goal = next((g for g in rt.goals.goals if g.id == int(ag["id"])), None)
                rt.goals._active = rt.active_goal
            rt_obj.execs[cid] = TripExecutor.from_state(cs["executor"], rt_obj)
            rt_obj.bands[cid] = LODBand[cs.get("band", "ROUTE_SIMULATED")]
            if cs.get("frozen_at") is not None:
                rt_obj.frozen_at[cid] = float(cs["frozen_at"])
            if cs.get("last_slot") is not None:
                rt_obj._last_slot[cid] = cs["last_slot"]
            if cs.get("retry_at") is not None:
                rt_obj._retry_at[cid] = float(cs["retry_at"])
            rt_obj.execs[cid].has_body = (rt_obj.bands[cid] == LODBand.PHYSICAL)
        # live graph state
        for sid, factor in (state.get("congestion") or {}).items():
            if sid in graph.segments:
                graph.set_congestion(sid, float(factor))
        from ..mobility import MobilityObstruction, ObstructionKind
        for od in state.get("obstructions") or []:
            if od["affected_segment"] not in graph.segments or od["id"] in graph._obstructions:
                continue
            loc = od.get("location")
            ma = od.get("modes_affected")
            graph.apply_obstruction(MobilityObstruction(
                id=od["id"], kind=ObstructionKind(od["kind"]), affected_segment=od["affected_segment"],
                location=None if loc is None else (float(loc[0]), float(loc[1])),
                severity=float(od.get("severity", 1.0)),
                modes_affected=None if ma is None else {Mode(m) for m in ma},
                source_entity=od.get("source_entity")))
        # parking occupancy as saved
        rt_obj.parking.occupied = {}
        rt_obj.parking.occupied_xy = {}
        for idx_s, vid in (state.get("parking_occupied") or {}).items():
            v = rt_obj.vehicles.get(vid)
            if v is not None and v.parked_location is not None:
                rt_obj.parking.occupy(int(idx_s), vid, v.parked_location)
        return rt_obj


def _perf() -> float:
    import time
    return time.perf_counter()

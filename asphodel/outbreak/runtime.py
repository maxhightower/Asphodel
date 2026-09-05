"""OutbreakRuntime — the outbreak acting on persistent citizens (ASPHODEL_OUTBREAK_V1).

Attached to :class:`World` next to the MobilityRuntime and advanced on the same
movement clock (``World.advance_seconds``). It owns one :class:`HealthRecord`
per registered citizen and does four things, all through existing
authorities:

* **contact** — exposure opportunities come from the mobility executors'
  real situation: co-occupancy of a building (``TripExecutor.building_id``),
  a shared vehicle, NEAR outdoor proximity, and undead attacks (bites);
* **progression** — scheduled transitions decided once at infection
  (symptom onset, incapacitation, death, reanimation), applied when the
  clock reaches them, identical after save/load;
* **behaviour** — health invalidates plans through the planner: a
  symptomatic citizen gets a high-priority "go home" goal, a witness of a
  threat gets a FLEE goal, an undead citizen gets a hunt goal; the
  TripExecutor executes them (no outbreak movement controller). Incapacitated
  citizens, corpses and the undead are executor overrides that hold the
  citizen at its authoritative place;
* **civil breakdown** — an incapacitated driver's car becomes a persistent
  wreck and a MobilityObstruction on its street (every later route sees it);
  a workplace with enough incapacitated/dead/undead workers, or an undead or
  corpse inside, is DISRUPTED and its workers are sent home.

Every event is recorded with actors, time and location (``events``), which is
the certification trace.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from ..citizens.goals import Goal, GoalKind
from ..embodied.executor import EmbodimentState, TripExecutor
from ..mobility import Mode
from ..transport.instances import VehicleFidelity
from .health import ALIVE, HealthRecord, HealthState, roll
from .pathogen import OutbreakPathogen, pathogen_by_name

Vec2 = Tuple[float, float]

OUTBREAK_SCHEMA_VERSION = 1
CONTACT_INTERVAL_S = 60.0      # co-occupancy hazard is integrated per game minute
UNDEAD_INTERVAL_S = 5.0        # hunt/attack cadence
THREAT_RADIUS_M = 25.0         # outdoor witness radius for an undead / attack / corpse
FLEE_PRIORITY = 0.92           # emergency (goals.SOURCE_BASE_PRIORITY["emergency"])
HEALTH_PRIORITY = 0.80         # above any schedule goal (<= 0.75), below emergencies
DISRUPTION_PRIORITY = 0.78
UNDEAD_PRIORITY = 0.95
MAX_EVENTS = 5000


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class OutbreakRuntime:
    def __init__(self, mobility, world_seed: int, pathogen: OutbreakPathogen):
        self.mobility = mobility
        self.seed = int(world_seed)
        self.pathogen = pathogen
        self.records: Dict[int, HealthRecord] = {}
        self.events: List[dict] = []
        self.event_seq = 0
        self.now_s = 0.0
        self._accum = 0.0
        self._next_contact_s = 0.0
        self._next_undead_s = 0.0
        self.disrupted_buildings: Dict[int, dict] = {}     # bid -> {t, reason}
        self.obstructions: List[str] = []                  # obstruction ids we applied
        self.undead_targets: Dict[int, int] = {}           # undead cid -> victim cid
        self.attack_cooldown: Dict[int, float] = {}
        self._known_threats: Dict[int, set] = {}           # witness cid -> threat ids seen
        self.workers_by_building: Dict[int, List[int]] = {}
        self._index_workers()

    # -- registry --------------------------------------------------------------
    def _index_workers(self) -> None:
        by: Dict[int, List[int]] = {}
        for cid, rec in self.mobility.records.items():
            if rec.work_building_id is not None:
                by.setdefault(int(rec.work_building_id), []).append(int(cid))
        self.workers_by_building = {k: sorted(v) for k, v in by.items()}

    def record(self, cid: int) -> HealthRecord:
        r = self.records.get(int(cid))
        if r is None:
            r = HealthRecord(int(cid))
            self.records[int(cid)] = r
        return r

    def event(self, kind: str, **info) -> dict:
        self.event_seq += 1
        row = {"seq": self.event_seq, "t": round(self.now_s, 1), "event": kind}
        row.update(info)
        self.events.append(row)
        if len(self.events) > MAX_EVENTS:
            del self.events[: len(self.events) - MAX_EVENTS]
        return row

    def _where(self, ex: TripExecutor) -> dict:
        return {"x": round(ex.pos[0], 1), "y": round(ex.pos[1], 1),
                "building_id": int(ex.building_id), "vehicle_id": ex.vehicle_id,
                "embodiment": ex.state.value}

    # -- seeding ---------------------------------------------------------------
    def seed_index_case(self, cid: int, context: str = "index_case") -> HealthRecord:
        ex = self.mobility.execs[int(cid)]
        rec = self.record(cid)
        rec.infect(self.pathogen, self.seed, self.now_s, None, context, ex.pos, [])
        self.event("EXPOSURE", citizen_id=int(cid), source_citizen=None, context=context, **self._where(ex))
        self.event("INFECTED", citizen_id=int(cid), pathogen=self.pathogen.name,
                   symptom_t=rec.symptom_t, incapacitation_t=rec.incapacitation_t,
                   death_t=rec.death_t, reanimate_t=rec.reanimate_t, fatal=rec.fatal,
                   will_reanimate=rec.will_reanimate, **self._where(ex))
        return rec

    def choose_index_case(self) -> Optional[int]:
        """Data-driven index case: a day-shift worker at the workplace with the
        most registered workers (ties: lowest building id, then lowest citizen id)."""
        best = None
        for bid, workers in sorted(self.workers_by_building.items()):
            day = [c for c in workers if any(s.activity == "work" and 6.0 <= s.start_hour <= 10.0
                                            for s in self.mobility.citizens[c].schedule)]
            if len(day) >= 2 and (best is None or len(day) > best[0]):
                best = (len(day), bid, day[0])
        return None if best is None else best[2]

    # -- the tick ---------------------------------------------------------------
    def advance(self, dt_s: float) -> None:
        self._accum += float(dt_s)
        while self._accum >= 1.0 - 1e-9:
            self._substep(1.0)
            self._accum -= 1.0

    def _substep(self, dt: float) -> None:
        self.now_s += dt
        self._progress()
        if self.now_s >= self._next_contact_s:
            self._next_contact_s = self.now_s + CONTACT_INTERVAL_S
            self._contacts(CONTACT_INTERVAL_S)
            self._disruption_scan()
            self._reissue_constraints()
        if self.now_s >= self._next_undead_s:
            self._next_undead_s = self.now_s + UNDEAD_INTERVAL_S
            self._undead(UNDEAD_INTERVAL_S)
            self._witnesses()

    # -- progression -----------------------------------------------------------
    def _progress(self) -> None:
        for cid in sorted(self.records):
            rec = self.records[cid]
            while True:
                nxt = rec.next_transition(self.now_s)
                if nxt is None or nxt[1] > self.now_s:
                    break
                name, _t = nxt
                getattr(self, "_on_" + name)(cid, rec)

    def _on_symptom_onset(self, cid: int, rec: HealthRecord) -> None:
        ex = self.mobility.execs[cid]
        rec.state = HealthState.SYMPTOMATIC
        self.event("SYMPTOM_ONSET", citizen_id=cid, **self._where(ex))
        self._go_home(cid, "symptomatic: going home")

    def _on_recovery(self, cid: int, rec: HealthRecord) -> None:
        rec.state = HealthState.RECOVERED
        rt = self.mobility.citizens[cid]
        rt.goals.goals = [g for g in rt.goals.goals if g.source != "health"]
        self.event("RECOVERED", citizen_id=cid, **self._where(self.mobility.execs[cid]))

    def _on_incapacitation(self, cid: int, rec: HealthRecord) -> None:
        ex = self.mobility.execs[cid]
        rt = self.mobility.citizens[cid]
        rec.state = HealthState.INCAPACITATED
        # civil breakdown: an incapacitated driver's car stops where it is
        if ex.state == EmbodimentState.DRIVING and ex.vehicle_id:
            self._abandon_vehicle(cid, ex, "driver incapacitated")
        ex.set_override("incapacitated", self.now_s)
        rt.goals.goals = [g for g in rt.goals.goals if g.source != "health"]
        self.event("INCAPACITATED", citizen_id=cid, **self._where(ex))
        self.event("PLAN_INVALIDATED", citizen_id=cid, reason="incapacitated", **self._where(ex))

    def _on_death(self, cid: int, rec: HealthRecord) -> None:
        ex = self.mobility.execs[cid]
        rec.state = HealthState.CORPSE if rec.will_reanimate else HealthState.DEAD
        rec.corpse_xy = [round(ex.pos[0], 2), round(ex.pos[1], 2)]
        rec.corpse_building_id = int(ex.building_id)
        rec.corpse_vehicle_id = ex.vehicle_id
        ex.set_override("corpse", self.now_s)
        self.event("DEATH", citizen_id=cid, will_reanimate=bool(rec.will_reanimate),
                   reanimate_t=rec.reanimate_t, **self._where(ex))
        self.event("CORPSE_CREATED", citizen_id=cid, corpse_xy=rec.corpse_xy,
                   corpse_building_id=rec.corpse_building_id, corpse_vehicle_id=rec.corpse_vehicle_id)
        self._disruption_scan()

    def _on_reanimation(self, cid: int, rec: HealthRecord) -> None:
        ex = self.mobility.execs[cid]
        rt = self.mobility.citizens[cid]
        rec.state = HealthState.UNDEAD
        rec.undead_since_t = self.now_s
        # the undead leaves a vehicle it died in (beside the car; identity kept)
        if ex.vehicle_id:
            veh = self.mobility.vehicles.get(ex.vehicle_id)
            if veh is not None and veh.driver == str(cid):
                veh.driver = None
            ex.vehicle_id = None
        ex.set_override("undead", self.now_s, speed=self.pathogen.undead_speed)
        rt.goals.goals = []
        rt.active_goal = None
        rt.goals._active = None
        rt._set_itinerary(None)
        rt.current_activity = "undead"
        self.event("REANIMATION", citizen_id=cid, original_citizen_id=cid,
                   lineage=list(rec.lineage), **self._where(ex))
        self._disruption_scan()

    # -- behaviour: health -> goals -> planner -> executor ---------------------
    def _go_home(self, cid: int, reason: str) -> None:
        rt = self.mobility.citizens[cid]
        ex = self.mobility.execs[cid]
        home = rt.home_node
        rt.goals.goals = [g for g in rt.goals.goals if g.source != "health"]
        g = Goal(GoalKind.DO_ACTIVITY, target=home, reason=reason, source="health",
                 priority=HEALTH_PRIORITY, activity="rest")
        preempted = rt.push_goal(g, self.mobility.graph)
        self.event("PLAN_INVALIDATED", citizen_id=cid, reason=reason, goal="go_home",
                   preempted=bool(preempted), **self._where(ex))
        if ex.current_step is not None and ex.state not in (EmbodimentState.INSIDE_BUILDING,
                                                             EmbodimentState.DOING_ACTIVITY):
            self.event("TRIP_ABORTED", citizen_id=cid, at_step=ex.current_step.kind.value,
                       step_index=ex.step_index, **self._where(ex))

    def _flee(self, cid: int, threat_id: int, reason: str) -> None:
        rt = self.mobility.citizens[cid]
        ex = self.mobility.execs[cid]
        home = rt.home_node
        # if the threat is in our home, flee to the errand building instead
        thr = self.mobility.execs.get(threat_id)
        target = home
        if thr is not None and thr.inside and thr.building_id == (rt.node_meta.get(home) or {}).get("building_id"):
            alt = next((n for n, m in rt.node_meta.items()
                        if n.startswith("ent:") and n != home and m.get("building_id") is not None), None)
            target = alt or home
        rt.goals.goals = [g for g in rt.goals.goals if g.source != "emergency"]
        g = Goal(GoalKind.FLEE, target=target, reason=reason, source="emergency", priority=FLEE_PRIORITY)
        rt.push_goal(g, self.mobility.graph)
        self.event("FLEE", citizen_id=cid, threat_citizen=threat_id, target=target, reason=reason,
                   **self._where(ex))

    def _reissue_constraints(self) -> None:
        """Health/disruption goals must survive the planner's schedule sync
        (which only replaces schedule-sourced goals) — re-push when missing."""
        for cid in sorted(self.records):
            rec = self.records[cid]
            rt = self.mobility.citizens.get(cid)
            if rt is None:
                continue
            if rec.state == HealthState.SYMPTOMATIC and not any(g.source == "health" for g in rt.goals.goals):
                self._go_home(cid, "symptomatic: going home")
        for bid in sorted(self.disrupted_buildings):
            for cid in self.workers_by_building.get(bid, []):
                rt = self.mobility.citizens.get(cid)
                rec = self.records.get(cid)
                if rt is None or (rec is not None and rec.state not in ALIVE):
                    continue
                work_node = rt.work_node
                if rt.active_goal is not None and rt.active_goal.target == work_node \
                        and rt.active_goal.source == "schedule":
                    g = Goal(GoalKind.DO_ACTIVITY, target=rt.home_node, source="disruption",
                             reason=f"workplace {bid} disrupted", priority=DISRUPTION_PRIORITY,
                             activity="rest")
                    rt.goals.goals = [x for x in rt.goals.goals if x.source != "disruption"]
                    rt.push_goal(g, self.mobility.graph)
                    self.event("PLAN_INVALIDATED", citizen_id=cid, reason=f"workplace {bid} disrupted",
                               goal="go_home", **self._where(self.mobility.execs[cid]))

    # -- contact model ------------------------------------------------------------
    def _contacts(self, window_s: float) -> None:
        p = self.pathogen
        execs = self.mobility.execs
        sources = [(cid, r.infectious_weight(p, self.now_s)) for cid, r in sorted(self.records.items())]
        sources = [(cid, w) for cid, w in sources if w > 0.0 and cid in execs]
        if not sources:
            return
        # susceptible = registered citizens without a record or SUSCEPTIBLE/RECOVERED(no)
        hours = window_s / 3600.0
        bucket = int(self.now_s // window_s)
        for scid, w in sources:
            sx = execs[scid]
            for vcid in sorted(execs):
                if vcid == scid:
                    continue
                vrec = self.records.get(vcid)
                if vrec is not None and vrec.state != HealthState.SUSCEPTIBLE:
                    continue
                vx = execs[vcid]
                if not vx.alive_for_contact():
                    continue
                context = None
                rate = 0.0
                if sx.inside and vx.inside and sx.building_id == vx.building_id and sx.building_id >= 0:
                    context, rate = f"building:{sx.building_id}", p.building_rate_per_h
                elif sx.vehicle_id and sx.vehicle_id == vx.vehicle_id:
                    context, rate = f"vehicle:{sx.vehicle_id}", p.vehicle_rate_per_h
                elif not sx.inside and not vx.inside and not sx.in_vehicle and not vx.in_vehicle \
                        and _d(sx.pos, vx.pos) <= p.proximity_radius_m:
                    context, rate = "proximity", p.proximity_rate_per_h
                if context is None:
                    continue
                prob = 1.0 - math.exp(-rate * w * hours)
                u = roll(self.seed, vcid, f"contact:{scid}", bucket)
                if u < prob:
                    self._expose(vcid, scid, context, vx.pos)
                else:
                    self.record(vcid).exposures_resisted += 1

    def _expose(self, vcid: int, scid: Optional[int], context: str, location: Vec2) -> HealthRecord:
        rec = self.record(vcid)
        src = self.records.get(scid) if scid is not None else None
        lineage = list(src.lineage) if src is not None else []
        rec.infect(self.pathogen, self.seed, self.now_s, scid, context, location, lineage)
        ex = self.mobility.execs[vcid]
        self.event("EXPOSURE", citizen_id=vcid, source_citizen=scid, context=context, **self._where(ex))
        self.event("INFECTED", citizen_id=vcid, source_citizen=scid, pathogen=self.pathogen.name,
                   symptom_t=rec.symptom_t, incapacitation_t=rec.incapacitation_t,
                   death_t=rec.death_t, reanimate_t=rec.reanimate_t, fatal=rec.fatal,
                   will_reanimate=rec.will_reanimate, lineage=list(rec.lineage), **self._where(ex))
        return rec

    # -- undead behaviour -----------------------------------------------------------
    def _undead(self, window_s: float) -> None:
        p = self.pathogen
        execs = self.mobility.execs
        for ucid in sorted(self.records):
            if self.records[ucid].state != HealthState.UNDEAD:
                continue
            ux = execs[ucid]
            urt = self.mobility.citizens[ucid]
            # target: nearest living citizen in the same building, else within sense radius outdoors
            best, bestd = None, math.inf
            for vcid in sorted(execs):
                if vcid == ucid:
                    continue
                vrec = self.records.get(vcid)
                if vrec is not None and vrec.state not in ALIVE:
                    continue
                vx = execs[vcid]
                if not vx.alive_for_contact():
                    continue
                if ux.inside:
                    if not (vx.inside and vx.building_id == ux.building_id):
                        continue
                    d = _d(ux.pos, vx.pos)
                else:
                    if vx.in_vehicle:
                        continue
                    d = _d(ux.pos, vx.pos)
                    if d > p.undead_sense_m and not (vx.inside and d <= p.undead_sense_m):
                        continue
                if d < bestd:
                    best, bestd = vcid, d
            if best is None:
                self.undead_targets.pop(ucid, None)
                continue
            vx = execs[best]
            same_place = (ux.inside and vx.inside and ux.building_id == vx.building_id)
            if same_place or bestd <= p.attack_reach_m:
                cd = self.attack_cooldown.get(ucid, -1e9)
                if self.now_s - cd >= p.attack_cooldown_s:
                    self.attack_cooldown[ucid] = self.now_s
                    self._attack(ucid, best)
                continue
            # hunt: plan toward the victim's node (the planner + executor move the body)
            vrt = self.mobility.citizens[best]
            tgt = vrt.current_node
            if self.undead_targets.get(ucid) != best or urt.active_goal is None:
                self.undead_targets[ucid] = best
                urt.goals.goals = []
                g = Goal(GoalKind.RETRIEVE, target=tgt, reason=f"hunting citizen {best}",
                         source="emergency", priority=UNDEAD_PRIORITY)
                urt.push_goal(g, self.mobility.graph)
                self.event("HUNT", citizen_id=ucid, target_citizen=best, distance_m=round(bestd, 1),
                           **self._where(ux))

    def _attack(self, ucid: int, vcid: int) -> None:
        p = self.pathogen
        ux, vx = self.mobility.execs[ucid], self.mobility.execs[vcid]
        rec = self.records[ucid]
        rec.attacks += 1
        u = roll(self.seed, vcid, f"bite:{ucid}", rec.attacks)
        took = u < p.bite_probability
        self.event("ATTACK", citizen_id=ucid, victim_citizen=vcid, exposed=bool(took), **self._where(vx))
        vrec = self.record(vcid)
        if took and vrec.state == HealthState.SUSCEPTIBLE:
            vrec.bitten_by = ucid
            self._expose(vcid, ucid, "bite", vx.pos)
        # the victim always flees an attack
        self._flee(vcid, ucid, "attacked")
        self._known_threats.setdefault(vcid, set()).add(ucid)

    # -- fear / observation -----------------------------------------------------------
    def _witnesses(self) -> None:
        execs = self.mobility.execs
        threats = [(cid, r) for cid, r in sorted(self.records.items())
                   if r.state in (HealthState.UNDEAD, HealthState.CORPSE)]
        if not threats:
            return
        recent_attacks = [e for e in self.events[-50:] if e["event"] == "ATTACK" and self.now_s - e["t"] <= UNDEAD_INTERVAL_S]
        for wcid in sorted(execs):
            wrec = self.records.get(wcid)
            if wrec is not None and wrec.state not in ALIVE:
                continue
            wx = execs[wcid]
            if wx.override in ("incapacitated",):
                continue
            seen = self._known_threats.setdefault(wcid, set())
            for tcid, trec in threats:
                if tcid in seen or tcid == wcid:
                    continue
                tx = execs[tcid]
                near = (wx.inside and tx.inside and wx.building_id == tx.building_id) or \
                       (not wx.inside and not tx.inside and _d(wx.pos, tx.pos) <= THREAT_RADIUS_M)
                if not near:
                    continue
                seen.add(tcid)
                kind = "undead" if trec.state == HealthState.UNDEAD else "corpse"
                self.event("THREAT_OBSERVED", citizen_id=wcid, threat_citizen=tcid, threat=kind,
                           **self._where(wx))
                if kind == "undead":
                    self._flee(wcid, tcid, f"saw undead citizen {tcid}")
                elif wx.inside and wx.state == EmbodimentState.DOING_ACTIVITY:
                    self._flee(wcid, tcid, f"corpse of citizen {tcid} here")
            for e in recent_attacks:
                if e["victim_citizen"] == wcid or e["citizen_id"] == wcid:
                    continue
                vx = execs.get(e["victim_citizen"])
                if vx is None:
                    continue
                near = (wx.inside and vx.inside and wx.building_id == vx.building_id) or \
                       (not wx.inside and _d(wx.pos, vx.pos) <= THREAT_RADIUS_M)
                key = ("attack", e["seq"])
                if near and key not in seen:
                    seen.add(key)
                    self.event("THREAT_OBSERVED", citizen_id=wcid, threat_citizen=e["citizen_id"],
                               threat="attack", **self._where(wx))
                    self._flee(wcid, e["citizen_id"], "witnessed an attack")

    # -- civil breakdown ---------------------------------------------------------------
    def _abandon_vehicle(self, cid: int, ex: TripExecutor, reason: str) -> None:
        veh = self.mobility.vehicles.get(ex.vehicle_id or "")
        if veh is None:
            return
        graph = self.mobility.graph
        pos = veh.position()
        veh.speed = 0.0
        veh.engine_state = "off"
        obs = veh.to_wreck(graph, severity=1.0)     # PERSISTENT_WRECK at its position
        veh.driver = None
        sid = obs.affected_segment
        if sid is not None and sid in graph.segments and obs.id not in graph._obstructions:
            graph.apply_obstruction(obs)
            self.obstructions.append(obs.id)
        if ex.car is not None:
            ex.car.speed = 0.0
        ex.speed = 0.0
        self.mobility.reconciler.update_congestion()
        self.event("VEHICLE_ABANDONED", citizen_id=cid, vehicle_id=veh.vehicle_id, reason=reason,
                   x=round(pos[0], 1), y=round(pos[1], 1), segment=sid)
        self.event("ROAD_OBSTRUCTED", vehicle_id=veh.vehicle_id, segment=sid, obstruction_id=obs.id,
                   closed_modes=sorted(m.value for m in obs.closed_modes()),
                   x=round(pos[0], 1), y=round(pos[1], 1))

    def _disruption_scan(self) -> None:
        p = self.pathogen
        execs = self.mobility.execs
        for bid, workers in sorted(self.workers_by_building.items()):
            if bid in self.disrupted_buildings:
                continue
            down = [c for c in workers if self.records.get(c) is not None
                    and self.records[c].state in (HealthState.INCAPACITATED, HealthState.DEAD,
                                                  HealthState.CORPSE, HealthState.UNDEAD)]
            hazard = [c for c, r in self.records.items()
                      if r.state in (HealthState.UNDEAD, HealthState.CORPSE, HealthState.INCAPACITATED)
                      and c in execs and execs[c].inside and execs[c].building_id == bid]
            reason = None
            if hazard:
                reason = f"{len(hazard)} incapacitated/dead/undead inside"
            elif workers and len(down) / len(workers) >= p.workplace_disruption_fraction:
                reason = f"{len(down)}/{len(workers)} workers down"
            if reason:
                self.disrupted_buildings[bid] = {"t": self.now_s, "reason": reason,
                                                 "workers": list(workers), "down": down, "hazard": hazard}
                self.event("WORKPLACE_DISRUPTED", building_id=bid, reason=reason, workers=list(workers),
                           down=down, hazard=hazard)

    # -- snapshot / persistence ------------------------------------------------------
    def health_row(self, cid: int) -> dict:
        r = self.records.get(cid)
        if r is None:
            return {"citizen_id": cid, "state": "susceptible"}
        d = {"citizen_id": cid, "state": r.state.value, "pathogen": r.pathogen,
             "source_citizen": r.source_citizen, "context": r.exposure_context,
             "infection_t": r.infection_t, "symptom_t": r.symptom_t,
             "death_t": r.death_t, "reanimate_t": r.reanimate_t,
             "corpse_building_id": r.corpse_building_id, "corpse_vehicle_id": r.corpse_vehicle_id,
             "lineage": list(r.lineage), "attacks": r.attacks}
        return d

    def snapshot(self, since_seq: int = 0, max_events: int = 200) -> dict:
        counts: Dict[str, int] = {}
        for r in self.records.values():
            counts[r.state.value] = counts.get(r.state.value, 0) + 1
        n_reg = len(self.mobility.execs)
        counts["susceptible"] = counts.get("susceptible", 0) + (n_reg - len(self.records))
        return {"version": OUTBREAK_SCHEMA_VERSION, "t_s": round(self.now_s, 1),
                "pathogen": self.pathogen.name, "counts": counts,
                "health": [self.health_row(c) for c in sorted(self.records)],
                "disrupted_buildings": {str(k): v for k, v in sorted(self.disrupted_buildings.items())},
                "obstructions": list(self.obstructions),
                "events": [e for e in self.events if e["seq"] > since_seq][-max_events:],
                "event_seq": self.event_seq}

    def to_state(self) -> dict:
        return {"version": OUTBREAK_SCHEMA_VERSION, "seed": self.seed,
                "pathogen": self.pathogen.to_dict(), "now_s": self.now_s, "accum": self._accum,
                "next_contact_s": self._next_contact_s, "next_undead_s": self._next_undead_s,
                "event_seq": self.event_seq, "events": list(self.events[-MAX_EVENTS:]),
                "records": {str(c): r.to_state() for c, r in sorted(self.records.items())},
                "disrupted_buildings": {str(k): v for k, v in sorted(self.disrupted_buildings.items())},
                "obstructions": list(self.obstructions),
                "undead_targets": {str(k): v for k, v in sorted(self.undead_targets.items())},
                "attack_cooldown": {str(k): v for k, v in sorted(self.attack_cooldown.items())},
                "known_threats": {str(k): sorted(str(x) for x in v) for k, v in sorted(self._known_threats.items())}}

    @classmethod
    def from_state(cls, st: dict, mobility) -> "OutbreakRuntime":
        o = cls(mobility, int(st["seed"]), OutbreakPathogen.from_dict(st["pathogen"]))
        o.now_s = float(st.get("now_s", 0.0))
        o._accum = float(st.get("accum", 0.0))
        o._next_contact_s = float(st.get("next_contact_s", 0.0))
        o._next_undead_s = float(st.get("next_undead_s", 0.0))
        o.event_seq = int(st.get("event_seq", 0))
        o.events = list(st.get("events") or [])
        o.records = {int(k): HealthRecord.from_state(v) for k, v in (st.get("records") or {}).items()}
        o.disrupted_buildings = {int(k): v for k, v in (st.get("disrupted_buildings") or {}).items()}
        o.obstructions = list(st.get("obstructions") or [])
        o.undead_targets = {int(k): int(v) for k, v in (st.get("undead_targets") or {}).items()}
        o.attack_cooldown = {int(k): float(v) for k, v in (st.get("attack_cooldown") or {}).items()}
        kt = {}
        for k, v in (st.get("known_threats") or {}).items():
            s = set()
            for x in v:
                if x.startswith("('attack', "):
                    s.add(("attack", int(x.split(",")[1].strip(" )"))))
                else:
                    s.add(int(x))
            kt[int(k)] = s
        o._known_threats = kt
        # executor overrides follow the restored health state
        for cid, r in o.records.items():
            ex = mobility.execs.get(cid)
            if ex is None:
                continue
            if r.state == HealthState.INCAPACITATED:
                ex.set_override("incapacitated", o.now_s)
            elif r.state in (HealthState.CORPSE, HealthState.DEAD):
                ex.set_override("corpse", o.now_s)
            elif r.state == HealthState.UNDEAD:
                ex.set_override("undead", o.now_s, speed=o.pathogen.undead_speed)
        return o

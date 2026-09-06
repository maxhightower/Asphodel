"""Multimodal itinerary planning + replanning (AS-NAV-1/2, §5.3, §6, §7.2).

The planner turns a goal ("be at the hospital") into an ITINERARY: an ordered
list of plan steps describing HOW the citizen intends to get there — leave the
apartment, walk to the parked car, drive a route, park, walk to the entrance,
enter. It never moves the citizen; local navigation + physics do that. Each
travel leg carries a concrete :class:`Route` from the MobilityGraph under CURRENT
dynamic costs, so a closure or wreck changes the plan on replan.

Route/plan failures are explicit (an Itinerary with ``ok=False`` and a reason),
never silently ignored (§21).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ..mobility import Mode, MobilityGraph, Route


class StepKind(Enum):
    LEAVE_BUILDING = "leave_building"
    WALK = "walk"
    ENTER_VEHICLE = "enter_vehicle"
    DRIVE = "drive"
    PARK = "park"
    EXIT_VEHICLE = "exit_vehicle"
    ENTER_BUILDING = "enter_building"
    DO_ACTIVITY = "do_activity"


@dataclass
class PlanStep:
    """One semantic mobility step (ASPHODEL_EMBODIED_MOBILITY_V1 §4).

    The planner decides WHAT happens; the execution layer
    (:mod:`asphodel.embodied`) owns HOW it physically progresses. Every step
    therefore carries the typed parameters execution needs and nothing is
    recovered from string parsing:

    * ``LEAVE_BUILDING`` / ``ENTER_BUILDING``: ``building_id`` (canonical
      buildings.json index) and ``anchor_xy`` (its exterior entrance anchor).
    * ``WALK`` / ``DRIVE``: ``from_node``/``to_node`` (street-graph nodes), the
      graph ``route`` and ``anchor_xy`` (the destination anchor the leg ends at).
    * ``ENTER_VEHICLE`` / ``PARK`` / ``EXIT_VEHICLE``: ``vehicle_id`` and, for
      PARK, ``anchor_xy`` (the parking anchor).
    * ``DO_ACTIVITY``: ``activity`` and ``building_id``.
    """

    kind: StepKind
    mode: Optional[Mode] = None
    from_node: Optional[str] = None
    to_node: Optional[str] = None
    route: Optional[Route] = None
    detail: str = ""
    # --- typed execution parameters (all optional; None = not applicable) ---
    building_id: Optional[int] = None
    vehicle_id: Optional[str] = None
    anchor_xy: Optional[tuple] = None
    activity: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "mode": self.mode.value if self.mode else None,
            "from": self.from_node,
            "to": self.to_node,
            "distance": round(self.route.distance, 1) if self.route else None,
            "seconds": round(self.route.cost, 1) if self.route else None,
            "detail": self.detail,
            "building_id": self.building_id,
            "vehicle_id": self.vehicle_id,
            "anchor_xy": (None if self.anchor_xy is None
                          else [round(float(self.anchor_xy[0]), 2),
                                round(float(self.anchor_xy[1]), 2)]),
            "activity": self.activity,
        }

    # -- exact serialization (save/load keeps the planned route verbatim) -----
    def to_state(self) -> dict:
        d = self.to_dict()
        d["route"] = (None if self.route is None else {
            "nodes": list(self.route.nodes), "segments": list(self.route.segments),
            "distance": float(self.route.distance), "cost": float(self.route.cost),
            "mode": self.route.mode.value})
        return d

    @classmethod
    def from_state(cls, d: dict) -> "PlanStep":
        r = d.get("route")
        route = None if r is None else Route(list(r["nodes"]), list(r["segments"]),
                                              float(r["distance"]), float(r["cost"]),
                                              Mode(r["mode"]))
        axy = d.get("anchor_xy")
        return cls(StepKind(d["kind"]), Mode(d["mode"]) if d.get("mode") else None,
                   d.get("from"), d.get("to"), route, d.get("detail", ""),
                   building_id=d.get("building_id"), vehicle_id=d.get("vehicle_id"),
                   anchor_xy=(None if axy is None else (float(axy[0]), float(axy[1]))),
                   activity=d.get("activity"))


@dataclass
class Itinerary:
    steps: List[PlanStep] = field(default_factory=list)
    ok: bool = True
    failure: str = ""
    mode: Mode = Mode.FOOT

    @property
    def total_distance(self) -> float:
        return sum(s.route.distance for s in self.steps if s.route)

    @property
    def total_seconds(self) -> float:
        return sum(s.route.cost for s in self.steps if s.route)

    def describe(self) -> List[str]:
        return [f"{s.kind.value}"
                + (f" ({s.mode.value})" if s.mode else "")
                + (f" {round(s.route.distance)}m" if s.route else "")
                for s in self.steps]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "failure": self.failure,
            "mode": self.mode.value,
            "total_distance": round(self.total_distance, 1),
            "total_seconds": round(self.total_seconds, 1),
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_state(self) -> dict:
        return {"ok": self.ok, "failure": self.failure, "mode": self.mode.value,
                "steps": [s.to_state() for s in self.steps]}

    @classmethod
    def from_state(cls, d: dict) -> "Itinerary":
        return cls(steps=[PlanStep.from_state(x) for x in d.get("steps", [])],
                   ok=bool(d.get("ok", True)), failure=str(d.get("failure", "")),
                   mode=Mode(d.get("mode", "foot")))


def choose_mode(distance_m: float, has_vehicle: bool,
                short_walk_m: float = 900.0) -> Mode:
    """Pick a default travel mode. Short trips walk; longer trips drive if able."""
    if has_vehicle and distance_m > short_walk_m:
        return Mode.CAR
    return Mode.FOOT


def _fail(mode: Mode, why: str) -> Itinerary:
    return Itinerary(steps=[], ok=False, failure=why, mode=mode)


def build_itinerary(graph: MobilityGraph, origin_node: str, dest_node: str,
                    mode: Mode, vehicle_node: Optional[str] = None,
                    parking_node: Optional[str] = None,
                    activity: Optional[str] = None,
                    *,
                    start_inside_building: bool = True,
                    start_in_vehicle: bool = False,
                    vehicle_id: Optional[str] = None,
                    origin_building_id: Optional[int] = None,
                    dest_building_id: Optional[int] = None,
                    origin_xy: Optional[tuple] = None,
                    dest_xy: Optional[tuple] = None,
                    vehicle_xy: Optional[tuple] = None,
                    parking_xy: Optional[tuple] = None) -> Itinerary:
    """Build the plan from origin building to destination building.

    For a foot trip: leave -> walk -> enter. For a car trip: leave -> walk to the
    parked car -> enter -> drive -> park -> exit -> walk to the entrance -> enter.
    ``vehicle_node``/``parking_node`` default to the origin/destination nodes when
    not given (car parked at the door).
    """
    it = Itinerary(mode=mode)
    if start_inside_building and not start_in_vehicle:
        it.steps.append(PlanStep(StepKind.LEAVE_BUILDING, from_node=origin_node,
                                 detail="exit origin building",
                                 building_id=origin_building_id, anchor_xy=origin_xy))

    if mode in (Mode.CAR, Mode.HEAVY):
        veh = vehicle_node or origin_node
        park = parking_node or dest_node
        if not start_in_vehicle:
            # walk to the parked vehicle
            if veh != origin_node:
                wr = graph.route(origin_node, veh, Mode.FOOT)
                if wr is None:
                    return _fail(mode, f"no walking route to vehicle at {veh}")
                it.steps.append(PlanStep(StepKind.WALK, Mode.FOOT, origin_node, veh, wr,
                                         "walk to parked car", anchor_xy=vehicle_xy))
            it.steps.append(PlanStep(StepKind.ENTER_VEHICLE, detail="get in car",
                                     vehicle_id=vehicle_id, anchor_xy=vehicle_xy))
        dr = graph.route(veh, park, mode)
        if dr is None:
            return _fail(mode, f"no {mode.value} route {veh}->{park}")
        it.steps.append(PlanStep(StepKind.DRIVE, mode, veh, park, dr, "drive route",
                                 vehicle_id=vehicle_id, anchor_xy=parking_xy))
        it.steps.append(PlanStep(StepKind.PARK, detail="park", vehicle_id=vehicle_id,
                                 to_node=park, anchor_xy=parking_xy))
        it.steps.append(PlanStep(StepKind.EXIT_VEHICLE, detail="get out",
                                 vehicle_id=vehicle_id, anchor_xy=parking_xy))
        if park != dest_node:
            wr2 = graph.route(park, dest_node, Mode.FOOT)
            if wr2 is None:
                return _fail(mode, f"no walking route parking->dest {park}->{dest_node}")
            it.steps.append(PlanStep(StepKind.WALK, Mode.FOOT, park, dest_node, wr2,
                                     "walk from parking to entrance", anchor_xy=dest_xy))
    else:
        wr = graph.route(origin_node, dest_node, mode)
        if wr is None:
            return _fail(mode, f"no {mode.value} route {origin_node}->{dest_node}")
        it.steps.append(PlanStep(StepKind.WALK, mode, origin_node, dest_node, wr,
                                 "walk to destination", anchor_xy=dest_xy))

    it.steps.append(PlanStep(StepKind.ENTER_BUILDING, to_node=dest_node,
                             detail="enter destination building",
                             building_id=dest_building_id, anchor_xy=dest_xy))
    if activity:
        it.steps.append(PlanStep(StepKind.DO_ACTIVITY, detail=activity,
                                 activity=activity, building_id=dest_building_id,
                                 to_node=dest_node))
    return it


def replan_travel(graph: MobilityGraph, itinerary: Itinerary,
                  origin_node: str, dest_node: str,
                  vehicle_node: Optional[str] = None,
                  parking_node: Optional[str] = None,
                  allow_abandon_vehicle: bool = True,
                  runtime=None) -> tuple[Itinerary, str]:
    """Recompute the itinerary under current graph state (§7.2, §11).

    If the driving route has become impossible and abandonment is allowed, the
    citizen downgrades to walking from their current vehicle position — the
    "abandon the car and continue on foot" behaviour. Returns (itinerary, reason).
    """
    activity = next((s.activity for s in itinerary.steps
                     if s.kind == StepKind.DO_ACTIVITY), None)
    mode = itinerary.mode
    if runtime is not None:
        # Embodied replan: start from the citizen's real situation. A citizen
        # whose car has become unusable (§16 "vehicle unavailable" clears
        # has_vehicle) must not be handed the same car plan again — that is a
        # replan livelock, not a reaction. Walking is the fallback.
        if mode in (Mode.CAR, Mode.HEAVY) and not runtime.has_vehicle \
                and not runtime.in_vehicle:
            mode = Mode.FOOT
        new = runtime._build(graph, dest_node, mode, activity)
    else:
        new = build_itinerary(graph, origin_node, dest_node, itinerary.mode,
                              vehicle_node, parking_node)
    if new.ok:
        if mode != itinerary.mode:
            return new, "vehicle unavailable; continuing on foot"
        return new, "rerouted under current mobility state"
    if mode in (Mode.CAR, Mode.HEAVY) and allow_abandon_vehicle:
        # Abandon the car where it is and walk the rest.
        start = vehicle_node or origin_node
        if runtime is not None:
            runtime.in_vehicle = False
            runtime.inside_building = False
            foot = runtime._build(graph, dest_node, Mode.FOOT, activity)
        else:
            foot = build_itinerary(graph, start, dest_node, Mode.FOOT)
        if foot.ok:
            foot.steps.insert(0, PlanStep(StepKind.EXIT_VEHICLE,
                                          detail="abandon blocked vehicle"))
            return foot, "vehicle route blocked; abandoned car, continuing on foot"
    return new, f"replan failed: {new.failure}"

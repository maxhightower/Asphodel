"""TripExecutor — World.step consumes the itinerary (ASPHODEL_EMBODIED_MOBILITY_V1 §5, §9, §16).

One executor per embodied citizen. It never chooses WHAT to do (that is the
:class:`CitizenRuntime` planner's itinerary); it owns HOW the current step
physically progresses and reports the situation back so the next plan starts
from reality. Explicit state machine (§9):

    INSIDE_BUILDING -> ON_FOOT -> APPROACHING_VEHICLE -> ENTERING_VEHICLE
      -> IN_VEHICLE -> DRIVING -> PARKED -> EXITING_VEHICLE -> ON_FOOT
      -> INSIDE_BUILDING -> DOING_ACTIVITY

Identity (citizen_id, vehicle_id, building_id) is preserved at every
transition; nothing here teleports: a step that cannot be executed fails with
a reason and the runtime chooses a bounded reaction (retry / wait / replan /
walk / trip failed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ..citizens.planning import Itinerary, PlanStep, StepKind
from ..mobility import Mode
from ..transport.instances import VehicleFidelity, VehicleInstance, distance_of_point
from .pathing import PhysicalPath
from .pedestrian import PedestrianController, WALK_SPEED
from .vehicle_control import VehicleController, VehicleParams, junctions_on_path

Vec2 = Tuple[float, float]


class EmbodimentState(str, Enum):
    INSIDE_BUILDING = "inside_building"
    DOING_ACTIVITY = "doing_activity"
    ON_FOOT = "on_foot"
    APPROACHING_VEHICLE = "approaching_vehicle"
    ENTERING_VEHICLE = "entering_vehicle"
    IN_VEHICLE = "in_vehicle"
    DRIVING = "driving"
    PARKED = "parked"
    EXITING_VEHICLE = "exiting_vehicle"
    TRIP_FAILED = "trip_failed"
    # ASPHODEL_OUTBREAK_V1: health overrides (the HealthRecord is the authority;
    # these are how the executor holds the body where the person really is)
    INCAPACITATED = "incapacitated"
    CORPSE = "corpse"
    UNDEAD = "undead"


# Transition dwell times (game seconds): believable, not instantaneous.
DWELL_LEAVE_BUILDING = 3.0
DWELL_ENTER_BUILDING = 2.0
DWELL_ENTER_VEHICLE = 2.5
DWELL_EXIT_VEHICLE = 2.0
DWELL_PARK = 1.5
VEHICLE_REACH_M = 6.0          # close enough to open the door
ENTRANCE_REACH_M = 6.0
APPROACH_LIMIT_M = 30.0        # straight-line approach beyond this is not allowed
PED_BLOCK_REPLAN_S = 20.0
CAR_BLOCK_REPLAN_S = 45.0
MAX_TRACE = 400
RESUME_TOLERANCE_M = 8.0       # how far off a new leg's path we still "are on it"
WALK_APPROACH_LIMIT_M = 200.0  # a walk leg may begin with a straight approach to its start within this
KERB_OFFSET_M = 4.5            # pedestrians walk this far to the right of the street centreline (kerb side)


def _resume_dist(path: PhysicalPath, pos: Vec2) -> float:
    """Where on ``path`` a citizen standing at ``pos`` already is.

    A plan can be replaced mid-leg (the schedule ticked over, a blockage
    escalated). The replacement leg usually re-covers the ground the citizen
    has already walked/driven, so the controller must start from the citizen's
    projection onto it — starting at 0 would teleport them back to the start of
    the street. When the citizen is not on the new path at all (they are
    somewhere else entirely) the leg starts at its beginning."""
    if not path.points:
        return 0.0
    along = distance_of_point(path.points, path.cum, pos)
    p = path.point_at(along)
    return along if math.hypot(p[0] - pos[0], p[1] - pos[1]) <= RESUME_TOLERANCE_M else 0.0


def walk_path(graph, route) -> PhysicalPath:
    """The physical path of a walking leg: the route polyline walked along the
    kerb (``KERB_OFFSET_M`` right of the street centreline) so pedestrians do
    not share the carriageway with the authoritative cars, which drive the
    centreline. Used for execution and for restoring a saved leg alike."""
    return PhysicalPath.from_route(graph, route).kerb_offset(KERB_OFFSET_M)


@dataclass
class TripExecutor:
    citizen_id: int
    pos: Vec2
    state: EmbodimentState = EmbodimentState.INSIDE_BUILDING
    building_id: int = -1               # the building we are inside (-1 outside)
    vehicle_id: Optional[str] = None    # the vehicle we are in (None on foot)
    heading: float = 0.0
    speed: float = 0.0
    activity: str = "idle"              # the activity we are actually performing
    step_index: int = 0
    plan_serial: int = -1
    dwell_s: float = 0.0
    failure: str = ""
    failures: int = 0
    trip_failed: bool = False
    distance_walked: float = 0.0
    distance_driven: float = 0.0
    blocked_events: int = 0
    trips_completed: int = 0
    itinerary: Optional[Itinerary] = None
    ped: Optional[PedestrianController] = None
    car: Optional[VehicleController] = None
    trace: List[dict] = field(default_factory=list)
    has_body: bool = False              # a Godot body embodies this citizen now
    last_report_s: float = -1.0
    _walk_base: float = 0.0             # metres walked on completed legs
    _drive_base: float = 0.0            # metres driven on completed legs
    state_log: List[tuple] = field(default_factory=list)   # (t, state) transitions
    # health override: "" | "incapacitated" | "corpse" | "undead" (outbreak runtime)
    override: str = ""
    override_since: float = -1.0
    speed_override: float = 0.0            # undead walking speed (m/s), 0 = default
    _pre_override_state: str = ""

    # -- helpers -------------------------------------------------------------
    def event(self, now_s: float, kind: str, **info) -> None:
        row = {"t": round(now_s, 1), "event": kind}
        row.update(info)
        self.trace.append(row)
        if len(self.trace) > MAX_TRACE:
            del self.trace[: len(self.trace) - MAX_TRACE]

    @property
    def current_step(self) -> Optional[PlanStep]:
        if self.itinerary is None or not self.itinerary.ok:
            return None
        if self.step_index >= len(self.itinerary.steps):
            return None
        return self.itinerary.steps[self.step_index]

    @property
    def in_vehicle(self) -> bool:
        return self.state in (EmbodimentState.IN_VEHICLE, EmbodimentState.DRIVING,
                              EmbodimentState.PARKED, EmbodimentState.EXITING_VEHICLE)

    @property
    def inside(self) -> bool:
        return self.state in (EmbodimentState.INSIDE_BUILDING, EmbodimentState.DOING_ACTIVITY)

    @property
    def moving(self) -> bool:
        return self.speed > 0.05

    def location_mode(self) -> str:
        if self.inside:
            return "building"
        return "street"

    def movement(self) -> str:
        if self.state == EmbodimentState.DRIVING:
            return "driving"
        if self.state in (EmbodimentState.ON_FOOT, EmbodimentState.APPROACHING_VEHICLE) and self.moving:
            return "walking"
        return "stationary"

    def route_progress(self) -> float:
        if self.car is not None and self.car.path.length > 0:
            return self.car.dist / self.car.path.length
        if self.ped is not None and self.ped.path.length > 0:
            return self.ped.dist / self.ped.path.length
        return 0.0

    def destination(self) -> Optional[Vec2]:
        if self.car is not None:
            return self.car.path.points[-1]
        if self.ped is not None:
            return self.ped.path.points[-1]
        return None

    def route_ahead(self, max_points: int = 400) -> List[Vec2]:
        if self.car is not None:
            return self.car.path.remaining_points(self.car.dist, max_points)
        if self.ped is not None:
            return self.ped.path.remaining_points(self.ped.dist, max_points)
        return []

    # -- plan adoption -------------------------------------------------------
    def adopt(self, itinerary: Optional[Itinerary], serial: int, now_s: float) -> None:
        # The same plan re-adopted after a failure keeps the failure streak
        # (otherwise fail -> replan -> identical plan -> fail loops forever).
        same_plan = (self.failure != "" and itinerary is not None and self.itinerary is not None
                     and itinerary.describe() == self.itinerary.describe())
        self.itinerary = itinerary
        self.plan_serial = serial
        self.step_index = 0
        # A leg abandoned mid-way keeps the metres it really covered.
        if self.ped is not None:
            self._walk_base += self.ped.distance_walked
        if self.car is not None:
            self._drive_base += self.car.distance_driven
        self.ped = None
        self.car = None
        self.dwell_s = 0.0
        self.failure = "" if (itinerary is None or itinerary.ok) else itinerary.failure
        if self.state == EmbodimentState.TRIP_FAILED:
            self.state = EmbodimentState.ON_FOOT if self.building_id < 0 else EmbodimentState.INSIDE_BUILDING
        self.trip_failed = False
        if not same_plan:
            self.failures = 0
        # A citizen that was driving keeps its situation; the new plan (built
        # from the reported situation) starts at DRIVE / EXIT_VEHICLE.
        if self.state in (EmbodimentState.APPROACHING_VEHICLE, EmbodimentState.ENTERING_VEHICLE):
            self.state = EmbodimentState.ON_FOOT
        elif self.state == EmbodimentState.DRIVING:
            self.state = EmbodimentState.IN_VEHICLE
        elif self.state == EmbodimentState.DOING_ACTIVITY:
            self.state = EmbodimentState.INSIDE_BUILDING
        self.event(now_s, "plan", steps=(itinerary.describe() if itinerary else []),
                   ok=(itinerary.ok if itinerary else None),
                   failure=(itinerary.failure if itinerary else ""))

    # -- the tick ------------------------------------------------------------
    def advance(self, dt: float, rt, env) -> None:
        """Advance ``dt`` game seconds. ``rt`` is the CitizenRuntime (planner),
        ``env`` the MobilityRuntime (graph, vehicles, anchors, failure policy)."""
        if rt.plan_serial != self.plan_serial:
            self.adopt(rt.itinerary, rt.plan_serial, env.now_s)
        self._advance(dt, rt, env)
        if not self.state_log or self.state_log[-1][1] != self.state.value:
            self.state_log.append((round(env.now_s, 1), self.state.value))
            if len(self.state_log) > MAX_TRACE:
                del self.state_log[: len(self.state_log) - MAX_TRACE]

    # -- health overrides (ASPHODEL_OUTBREAK_V1) ---------------------------------
    def set_override(self, kind: str, now_s: float, speed: Optional[float] = None) -> None:
        """Hold the citizen where it physically is (incapacitated / corpse) or
        turn it undead (walks under the same executor at ``speed``). Position,
        building_id and vehicle_id are preserved: a citizen who collapses at
        the wheel is still in that car, one who dies at work is still at work."""
        if kind == self.override:
            return
        if not self.override:
            self._pre_override_state = self.state.value
        self.override = kind
        self.override_since = now_s
        self.speed = 0.0
        self.ped = None
        self.car = None
        if kind == "incapacitated":
            self.state = EmbodimentState.INCAPACITATED
            self.activity = "incapacitated"
        elif kind == "corpse":
            self.state = EmbodimentState.CORPSE
            self.activity = "dead"
        elif kind == "undead":
            # an undead that rose inside a building is still inside it (it
            # leaves through the entrance like anyone else); outdoors it stands
            self.state = EmbodimentState.INSIDE_BUILDING if self.building_id >= 0 else EmbodimentState.UNDEAD
            self.activity = "undead"
            self.speed_override = float(speed or 0.9)
            self.itinerary = None
            self.step_index = 0
        elif kind == "":
            self.state = EmbodimentState(self._pre_override_state or "on_foot")
        self.event(now_s, "override", override=kind, building_id=self.building_id, vehicle_id=self.vehicle_id)

    def alive_for_contact(self) -> bool:
        """Can this citizen be exposed / attacked (alive and not already undead)?"""
        return self.override not in ("corpse", "undead")

    def _advance(self, dt: float, rt, env) -> None:
        if self.override in ("incapacitated", "corpse"):
            self.speed = 0.0
            return
        if self.trip_failed:
            # holds until the runtime retries or a new plan is adopted
            self.speed = 0.0
            return
        step = self.current_step
        if step is None:
            self._in_place(rt, env)
            return
        done = False
        k = step.kind
        if k == StepKind.LEAVE_BUILDING:
            done = self._leave_building(dt, step, rt, env)
        elif k == StepKind.WALK:
            done = self._walk(dt, step, rt, env)
        elif k == StepKind.ENTER_VEHICLE:
            done = self._enter_vehicle(dt, step, rt, env)
        elif k == StepKind.DRIVE:
            done = self._drive(dt, step, rt, env)
        elif k == StepKind.PARK:
            done = self._park(dt, step, rt, env)
        elif k == StepKind.EXIT_VEHICLE:
            done = self._exit_vehicle(dt, step, rt, env)
        elif k == StepKind.ENTER_BUILDING:
            done = self._enter_building(dt, step, rt, env)
        elif k == StepKind.DO_ACTIVITY:
            done = self._do_activity(dt, step, rt, env)
        if done:
            self.step_index += 1
            self.dwell_s = 0.0
            self.ped = None
            self.car = None
            self.event(env.now_s, "step_done", step_kind=k.value, step=self.step_index - 1)
            if self.current_step is None:
                self.trips_completed += 1
                self._in_place(rt, env)

    def _in_place(self, rt, env) -> None:
        """No executable step: hold the situation; perform the activity only if
        the citizen is physically at the goal's location (§15)."""
        self.speed = 0.0
        if self.state == EmbodimentState.TRIP_FAILED:
            return
        if self.override == "undead":
            self.state = EmbodimentState.INSIDE_BUILDING if self.inside else EmbodimentState.UNDEAD
            self.activity = "undead"
            return
        g = rt.active_goal
        if self.inside and g is not None and g.target == rt.current_node \
                and self.building_id == (rt.node_meta.get(rt.current_node) or {}).get("building_id", self.building_id):
            act = g.activity or {"idle": "sleep", "arrive_at": "arrived"}.get(g.kind.value, g.kind.value)
            if self.state != EmbodimentState.DOING_ACTIVITY or self.activity != act:
                self.state = EmbodimentState.DOING_ACTIVITY
                self.activity = act
                self.event(env.now_s, "activity", activity=act, building_id=self.building_id)
        elif self.inside:
            self.state = EmbodimentState.INSIDE_BUILDING
            self.activity = "idle"
        elif self.in_vehicle:
            self.activity = "idle"
        else:
            self.state = EmbodimentState.ON_FOOT
            self.activity = "idle"

    # -- failure policy (§16) ------------------------------------------------
    def fail(self, reason: str, rt, env) -> None:
        self.failure = reason
        self.failures += 1
        self.event(env.now_s, "failure", reason=reason, count=self.failures)
        env.on_failure(self, rt, reason)

    # -- steps ---------------------------------------------------------------
    def _leave_building(self, dt, step, rt, env) -> bool:
        if not self.inside:
            return True                     # already outside: nothing to leave
        anchor = step.anchor_xy or env.entrance_of(self.building_id)
        if anchor is None:
            self.fail("cannot leave building: no entrance anchor", rt, env)
            return False
        self.dwell_s += dt
        if self.dwell_s < DWELL_LEAVE_BUILDING:
            return False
        left = self.building_id
        self.pos = (float(anchor[0]), float(anchor[1]))
        self.state = EmbodimentState.ON_FOOT
        self.building_id = -1
        self.activity = "traveling"
        rt.note_situation(node=step.from_node, inside_building=False)
        self.event(env.now_s, "left_building", building_id=left)
        return True

    def _walk(self, dt, step, rt, env) -> bool:
        if self.ped is None:
            if step.route is None:
                self.fail("walk step without a route", rt, env)
                return False
            path = walk_path(env.graph, step.route)
            if path.length <= 0.0 and step.anchor_xy is None:
                return True
            self.ped = PedestrianController(path)
            if self.speed_override > 0.0:
                self.ped.desired_speed = self.speed_override
            # start from where we physically are: project onto the path
            rd = _resume_dist(path, self.pos)
            d0 = math.hypot(path.points[0][0] - self.pos[0], path.points[0][1] - self.pos[1])
            if rd == 0.0 and d0 > RESUME_TOLERANCE_M:
                if d0 > WALK_APPROACH_LIMIT_M:
                    # never relocate: a leg that starts elsewhere is a planning error
                    self.ped = None
                    self.fail("walk leg does not start where the citizen is", rt, env)
                    return False
                # The plan was built from the last node this citizen passed and
                # heads off in another direction: walk straight back to where
                # the leg starts (the street just walked), never relocate.
                self.ped = None
                v = self.speed_override if self.speed_override > 0.0 else WALK_SPEED
                step_m = min(d0, v * dt)
                self.pos = (self.pos[0] + (path.points[0][0] - self.pos[0]) / d0 * step_m,
                            self.pos[1] + (path.points[0][1] - self.pos[1]) / d0 * step_m)
                self.heading = math.atan2(path.points[0][1] - self.pos[1], path.points[0][0] - self.pos[0])
                self.speed = v
                self._walk_base += step_m
                self.distance_walked = self._walk_base
                self.state = EmbodimentState.ON_FOOT
                self.activity = "traveling"
                return False
            self.ped.dist = rd
            self.ped._update_segment_index()
            self.state = EmbodimentState.ON_FOOT
            self.activity = "traveling"
            self.event(env.now_s, "walk_start", length_m=round(path.length, 1),
                       segments=len(path.street_segments()))
        c = self.ped
        c.advance(dt, env.moving_vehicles_near(self.pos, 30.0), physical=self.has_body)
        self.pos = c.position
        nb = c.path.node_before(c.dist)
        if nb is not None and nb != rt.current_node:
            rt.note_situation(node=nb)
        self.heading = c.heading
        self.speed = c.speed
        self.distance_walked = self._walk_base + c.distance_walked
        if c.blocked_s > PED_BLOCK_REPLAN_S:
            self.blocked_events += 1
            c.clear_block()
            env.on_blocked(self, rt, "pedestrian blocked")
            return False
        if c.arrived:
            self.speed = 0.0
            rt.note_situation(node=step.to_node)
            self.event(env.now_s, "walk_done", walked_m=round(c.distance_walked, 1))
            self._walk_base += c.distance_walked
            return True
        return False

    def _enter_vehicle(self, dt, step, rt, env) -> bool:
        vid = step.vehicle_id or rt.vehicle_id
        veh = env.vehicles.get(vid) if vid else None
        if veh is None or veh.driver not in (None, str(self.citizen_id)) \
                or veh.fidelity == VehicleFidelity.PERSISTENT_WRECK or veh.condition <= 0.0:
            self.fail("vehicle unavailable", rt, env)
            return False
        vxy = veh.position()
        d = math.hypot(vxy[0] - self.pos[0], vxy[1] - self.pos[1])
        if d > VEHICLE_REACH_M:
            if d > APPROACH_LIMIT_M:
                self.fail(f"vehicle too far to approach ({d:.0f} m)", rt, env)
                return False
            # short straight approach across the kerb/driveway to the car door
            self.state = EmbodimentState.APPROACHING_VEHICLE
            step_m = min(d, WALK_SPEED * dt)
            self.pos = (self.pos[0] + (vxy[0] - self.pos[0]) / d * step_m,
                        self.pos[1] + (vxy[1] - self.pos[1]) / d * step_m)
            self.heading = math.atan2(vxy[1] - self.pos[1], vxy[0] - self.pos[0])
            self.speed = WALK_SPEED
            self._walk_base += step_m
            self.distance_walked = self._walk_base
            return False
        self.speed = 0.0
        self.state = EmbodimentState.ENTERING_VEHICLE
        self.dwell_s += dt
        if self.dwell_s < DWELL_ENTER_VEHICLE:
            return False
        veh.driver = str(self.citizen_id)
        veh.engine_state = "on"
        self.vehicle_id = veh.vehicle_id
        self.state = EmbodimentState.IN_VEHICLE
        self.pos = vxy
        env.parking.release(veh.vehicle_id)
        veh.parked_location = None
        rt.note_situation(in_vehicle=True)
        self.event(env.now_s, "entered_vehicle", vehicle_id=veh.vehicle_id)
        return True

    def _drive(self, dt, step, rt, env) -> bool:
        veh = env.vehicles.get(self.vehicle_id or step.vehicle_id or "")
        if veh is None or not self.in_vehicle:
            self.fail("drive step while not in a vehicle", rt, env)
            return False
        if self.car is None:
            if step.route is None:
                self.fail("drive step without a route", rt, env)
                return False
            path = PhysicalPath.from_route(env.graph, step.route)
            veh.assign_route(step.route, env.graph)
            self.car = VehicleController(path, params=env.vehicle_params(veh))
            self.car.junctions = junctions_on_path(env.graph, path)
            rd = _resume_dist(path, veh.position())
            vp = veh.position()
            if rd == 0.0 and math.hypot(path.points[0][0] - vp[0], path.points[0][1] - vp[1]) > RESUME_TOLERANCE_M:
                self.car = None
                self.fail("drive leg does not start where the vehicle is", rt, env)
                return False
            self.car.dist = rd
            veh.fidelity = (VehicleFidelity.PHYSICAL_CONTROLLED if self.has_body
                            else VehicleFidelity.ROUTE_SIMULATED)
            self.state = EmbodimentState.DRIVING
            self.activity = "traveling"
            self.event(env.now_s, "drive_start", vehicle_id=veh.vehicle_id,
                       length_m=round(path.length, 1), segments=len(path.street_segments()))
        c = self.car
        c.advance(dt, env.graph, veh.mode, env.other_vehicles(veh.vehicle_id, self.pos),
                  veh.vehicle_id, env.now_s)
        veh.distance_along = c.dist
        veh.speed = c.speed
        self.pos = c.position
        self.heading = c.heading
        self.speed = c.speed
        nb = c.path.node_before(c.dist)
        if nb is not None and nb != rt.vehicle_node:
            rt.note_situation(node=nb, vehicle_node=nb)
        self.distance_driven = self._drive_base + c.distance_driven
        if c.blocked and c.blocked_s <= dt:
            self.blocked_events += 1
            self.event(env.now_s, "blocked", reason=c.last_reason,
                       following=c.following, closed=c.road_closed_ahead)
        if c.blocked_s > CAR_BLOCK_REPLAN_S:
            why = (f"road blocked: {c.road_closed_ahead}" if c.road_closed_ahead is not None
                   else f"stuck {c.last_reason} {c.following or c.yielding_to or ''}")
            self.blocked_events += 1
            env.on_blocked(self, rt, why)
            return False
        if c.arrived or c.dist >= c.path.length - 1e-6:
            self.speed = 0.0
            veh.speed = 0.0
            self._drive_base += c.distance_driven
            rt.note_situation(node=step.to_node, vehicle_node=step.to_node)
            self.event(env.now_s, "drive_done", driven_m=round(c.distance_driven, 1),
                       blocked=c.events())
            return True
        return False

    def _park(self, dt, step, rt, env) -> bool:
        veh = env.vehicles.get(self.vehicle_id or "")
        if veh is None:
            self.fail("park step without a vehicle", rt, env)
            return False
        self.state = EmbodimentState.PARKED
        self.dwell_s += dt
        if self.dwell_s < DWELL_PARK:
            return False
        anchor = step.anchor_xy or veh.position()
        d = math.hypot(anchor[0] - veh.position()[0], anchor[1] - veh.position()[1])
        if d > VEHICLE_REACH_M:
            self.fail(f"parking anchor not reached ({d:.0f} m away)", rt, env)
            return False
        veh.parked_location = (float(anchor[0]), float(anchor[1]))
        veh.engine_state = "off"
        veh.speed = 0.0
        veh.fidelity = VehicleFidelity.ROUTE_SIMULATED
        env.parking_occupy(step.to_node, veh)
        rt.note_situation(vehicle_node=step.to_node)
        self.event(env.now_s, "parked", vehicle_id=veh.vehicle_id,
                   anchor=[round(anchor[0], 1), round(anchor[1], 1)], node=step.to_node)
        return True

    def _exit_vehicle(self, dt, step, rt, env) -> bool:
        veh = env.vehicles.get(self.vehicle_id or "")
        if veh is None:
            self.fail("exit step without a vehicle", rt, env)
            return False
        self.state = EmbodimentState.EXITING_VEHICLE
        self.dwell_s += dt
        if self.dwell_s < DWELL_EXIT_VEHICLE:
            return False
        vxy = veh.position()
        # step out beside the car (perpendicular to its heading)
        h = self.heading + math.pi / 2.0
        self.pos = (vxy[0] + 1.3 * math.cos(h), vxy[1] + 1.3 * math.sin(h))
        veh.driver = None
        self.vehicle_id_last = veh.vehicle_id
        self.vehicle_id = None
        self.state = EmbodimentState.ON_FOOT
        rt.note_situation(in_vehicle=False)
        self.event(env.now_s, "exited_vehicle", vehicle_id=veh.vehicle_id)
        return True

    def _enter_building(self, dt, step, rt, env) -> bool:
        bid = step.building_id
        if bid is None:
            bid = (rt.node_meta.get(step.to_node) or {}).get("building_id")
        anchor = step.anchor_xy or (env.entrance_of(bid) if bid is not None else None)
        if bid is None or anchor is None:
            self.fail("enter building: unknown building/entrance", rt, env)
            return False
        d = math.hypot(anchor[0] - self.pos[0], anchor[1] - self.pos[1])
        if d > ENTRANCE_REACH_M:
            if d > APPROACH_LIMIT_M:
                self.fail(f"entrance unreachable ({d:.0f} m away)", rt, env)
                return False
            step_m = min(d, WALK_SPEED * dt)
            self.pos = (self.pos[0] + (anchor[0] - self.pos[0]) / d * step_m,
                        self.pos[1] + (anchor[1] - self.pos[1]) / d * step_m)
            self.speed = WALK_SPEED
            self._walk_base += step_m
            self.distance_walked = self._walk_base
            return False
        self.speed = 0.0
        self.dwell_s += dt
        if self.dwell_s < DWELL_ENTER_BUILDING:
            return False
        self.pos = (float(anchor[0]), float(anchor[1]))
        self.building_id = int(bid)
        self.state = EmbodimentState.INSIDE_BUILDING
        rt.note_situation(node=step.to_node, inside_building=True)
        self.event(env.now_s, "entered_building", building_id=int(bid))
        return True

    def _do_activity(self, dt, step, rt, env) -> bool:
        if not self.inside or (step.building_id is not None and self.building_id != step.building_id):
            self.fail("activity requires being inside the destination building", rt, env)
            return False
        self.state = EmbodimentState.DOING_ACTIVITY
        self.activity = step.activity or "activity"
        self.event(env.now_s, "activity", activity=self.activity, building_id=self.building_id,
                   arrived=True)
        return True

    # -- physical reconciliation (NEAR) ---------------------------------------
    def reconcile_physical(self, pos: Vec2, blocked: bool, dt: float, env) -> None:
        if self.car is not None:
            self.car.reconcile_physical(pos, blocked, dt)
            veh = env.vehicles.get(self.vehicle_id or "")
            if veh is not None:
                veh.distance_along = self.car.dist
            self.pos = self.car.position
        elif self.ped is not None:
            self.ped.reconcile_physical(pos, blocked, dt)
            self.pos = self.ped.position
        if blocked:
            self.blocked_events += 1

    # -- serialization --------------------------------------------------------
    def to_state(self) -> dict:
        st = {
            "citizen_id": int(self.citizen_id), "state": self.state.value,
            "pos": [float(self.pos[0]), float(self.pos[1])],
            "building_id": int(self.building_id), "vehicle_id": self.vehicle_id,
            "heading": float(self.heading), "speed": float(self.speed),
            "activity": self.activity, "step_index": int(self.step_index),
            "plan_serial": int(self.plan_serial), "dwell_s": float(self.dwell_s),
            "failure": self.failure, "failures": int(self.failures),
            "trip_failed": bool(self.trip_failed),
            "distance_walked": float(self.distance_walked),
            "distance_driven": float(self.distance_driven),
            "walk_base": float(self._walk_base),
            "drive_base": float(self._drive_base),
            "blocked_events": int(self.blocked_events),
            "trips_completed": int(self.trips_completed),
            "override": self.override, "override_since": float(self.override_since),
            "speed_override": float(self.speed_override),
            "pre_override_state": self._pre_override_state,
            "itinerary": None if self.itinerary is None else self.itinerary.to_state(),
            "ped": None if self.ped is None else self.ped.to_state(),
            "car": None if self.car is None else self.car.to_state(),
            "trace": list(self.trace[-50:]),
            "state_log": [list(x) for x in self.state_log[-50:]],
        }
        return st

    @classmethod
    def from_state(cls, st: dict, env) -> "TripExecutor":
        ex = cls(int(st["citizen_id"]), (float(st["pos"][0]), float(st["pos"][1])),
                 state=EmbodimentState(st["state"]), building_id=int(st.get("building_id", -1)),
                 vehicle_id=st.get("vehicle_id"), heading=float(st.get("heading", 0.0)),
                 speed=float(st.get("speed", 0.0)), activity=str(st.get("activity", "idle")),
                 step_index=int(st.get("step_index", 0)), plan_serial=int(st.get("plan_serial", -1)),
                 dwell_s=float(st.get("dwell_s", 0.0)), failure=str(st.get("failure", "")),
                 failures=int(st.get("failures", 0)), trip_failed=bool(st.get("trip_failed", False)),
                 distance_walked=float(st.get("distance_walked", 0.0)),
                 distance_driven=float(st.get("distance_driven", 0.0)),
                 blocked_events=int(st.get("blocked_events", 0)),
                 trips_completed=int(st.get("trips_completed", 0)))
        ex.override = str(st.get("override", ""))
        ex.override_since = float(st.get("override_since", -1.0))
        ex.speed_override = float(st.get("speed_override", 0.0))
        ex._pre_override_state = str(st.get("pre_override_state", ""))
        ex._walk_base = float(st.get("walk_base", 0.0))
        ex._drive_base = float(st.get("drive_base", 0.0))
        ex.trace = list(st.get("trace") or [])
        ex.state_log = [tuple(x) for x in (st.get("state_log") or [])]
        it = st.get("itinerary")
        ex.itinerary = None if it is None else Itinerary.from_state(it)
        step = ex.current_step
        if st.get("ped") is not None and step is not None and step.route is not None:
            ex.ped = PedestrianController(walk_path(env.graph, step.route))
            ex.ped.restore(st["ped"])
            if ex.speed_override > 0.0:          # an undead keeps its shambling speed
                ex.ped.desired_speed = ex.speed_override
        if st.get("car") is not None and step is not None and step.route is not None:
            veh = env.vehicles.get(ex.vehicle_id or "")
            path = PhysicalPath.from_route(env.graph, step.route)
            ex.car = VehicleController(path, params=env.vehicle_params(veh) if veh else VehicleParams())
            ex.car.junctions = junctions_on_path(env.graph, path)
            ex.car.restore(st["car"])
            if veh is not None:
                veh.assign_route(step.route, env.graph)
                veh.distance_along = ex.car.dist
        return ex

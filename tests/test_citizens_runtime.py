"""Tests for the citizen intention runtime (AS-NAV-1/2/5, §17.5)."""
from __future__ import annotations

from asphodel.mobility import (
    Mode,
    MobilityGraph,
    MobilityObstruction,
    ObstructionKind,
    RoadSegment,
)
from asphodel.citizens import (
    CitizenRuntime,
    Goal,
    GoalKind,
    GoalStack,
    ScheduleSlot,
    StepKind,
    build_itinerary,
    goal_from_schedule,
)


def _city():
    """H --hw-- W --ws-- S, all car+foot."""
    g = MobilityGraph()
    g.add_node("H", (0, 0))
    g.add_node("W", (1000, 0))
    g.add_node("S", (2000, 0))
    g.add_segment(RoadSegment("hw", [(0, 0), (1000, 0)], "secondary"), "H", "W")
    g.add_segment(RoadSegment("ws", [(1000, 0), (2000, 0)], "secondary"), "W", "S")
    return g


def _worker(g):
    sched = [
        ScheduleSlot(0, 7, "sleep", "H"),
        ScheduleSlot(7, 8, "commute", "W"),
        ScheduleSlot(8, 16, "work", "W", task="triage"),
        ScheduleSlot(16, 17, "commute_home", "H"),
        ScheduleSlot(17, 24, "leisure", "H"),
    ]
    return CitizenRuntime("c1", "H", "W", sched, has_vehicle=True, vehicle_node="H")


# -- schedule -> goal --------------------------------------------------------
def test_schedule_activity_maps_to_goal_kind():
    assert goal_from_schedule("commute", "W", 7.5, 8.0).kind == GoalKind.ARRIVE_AT
    assert goal_from_schedule("sleep", "H", 2.0).kind == GoalKind.IDLE
    dg = goal_from_schedule("work", "W", 9.0, 16.0, task="triage")
    assert dg.kind == GoalKind.DO_ACTIVITY and "triage" in dg.reason


def test_commute_goal_carries_deadline_and_location():
    g = goal_from_schedule("commute", "W", 7.2, 8.0)
    assert g.target == "W" and g.deadline == 8.0


def test_sync_schedule_sets_arrive_goal_and_plans():
    g = _city()
    c = _worker(g)
    c.sync_schedule(7.5, g)
    assert c.active_goal.kind == GoalKind.ARRIVE_AT
    assert c.destination == "W"
    assert c.itinerary is not None and c.itinerary.ok


def test_travel_plan_selects_car_for_long_trip():
    g = _city()
    c = _worker(g)
    c.sync_schedule(7.5, g)
    assert c.current_mode == Mode.CAR
    kinds = [s.kind for s in c.itinerary.steps]
    assert StepKind.DRIVE in kinds and StepKind.ENTER_VEHICLE in kinds


def test_short_trip_walks():
    g = _city()
    c = _worker(g)
    c.has_vehicle = True
    # A tiny hop: put destination one short block away.
    g.add_node("Kiosk", (200, 0))
    g.add_segment(RoadSegment("hk", [(0, 0), (200, 0)], "residential"), "H", "Kiosk")
    c.push_goal(Goal(GoalKind.ARRIVE_AT, "Kiosk", "grab coffee", "need", 0.4), g)
    assert c.current_mode == Mode.FOOT


# -- goal interruption (§11) -------------------------------------------------
def test_emergency_goal_preempts_schedule():
    stack = GoalStack()
    stack.push(Goal(GoalKind.DO_ACTIVITY, "W", "work shift", "schedule", 0.55))
    assert stack.select_active().source == "schedule"
    emergency = Goal(GoalKind.RETRIEVE, "S", "child in danger", "emergency", 0.92)
    assert stack.would_preempt(emergency)
    stack.push(emergency)
    assert stack.select_active().source == "emergency"


def test_working_citizen_interrupted_replans_toward_new_goal():
    g = _city()
    c = _worker(g)
    c.sync_schedule(9.0, g)               # at work, doing activity
    c.current_node = "W"
    assert c.active_goal.kind == GoalKind.DO_ACTIVITY
    preempts = c.push_emergency("S", "child may be in danger", g, priority=0.92)
    assert preempts
    assert c.active_goal.kind == GoalKind.RETRIEVE
    assert c.destination == "S"
    assert c.itinerary is not None and c.itinerary.ok


def test_returns_to_schedule_after_emergency_resolved():
    g = _city()
    c = _worker(g)
    c.sync_schedule(9.0, g)
    c.push_emergency("S", "child", g, priority=0.92)
    assert c.active_goal.source == "emergency"
    c.goals.complete_active()             # emergency resolved
    c.sync_schedule(9.0, g)               # back to the schedule
    assert c.active_goal.source == "schedule"


# -- replanning (§7.2, §11) --------------------------------------------------
def test_blocked_car_route_triggers_replan_and_abandons_to_foot():
    g = _city()
    c = _worker(g)
    c.current_node = "W"
    c.vehicle_node = "W"
    # Drive toward school, then the road closes to cars (foot still allowed).
    c.push_goal(Goal(GoalKind.RETRIEVE, "S", "emergency", "emergency", 0.92), g)
    assert c.current_mode == Mode.CAR and c.itinerary.ok
    g.apply_obstruction(MobilityObstruction("wreck", ObstructionKind.CLOSURE, "ws"))
    c.on_blockage(g, reason="road blocked ahead")
    assert c.itinerary.ok
    assert c.itinerary.mode == Mode.FOOT          # abandoned the car
    assert "foot" in c.last_replan_reason


def test_replan_failure_is_reported_not_swallowed():
    g = _city()
    c = _worker(g)
    c.current_node = "W"
    c.vehicle_node = "W"
    c.push_goal(Goal(GoalKind.RETRIEVE, "S", "emergency", "emergency", 0.92), g)
    # Close the segment to EVERYTHING (fire): no foot route either.
    seg = g.segments["ws"]
    seg.dynamic_state.closed_modes = {Mode.FOOT, Mode.BICYCLE, Mode.CAR,
                                      Mode.HEAVY, Mode.EMERGENCY}
    c.on_blockage(g, reason="total closure")
    assert not c.itinerary.ok
    assert c.current_failure                       # failure surfaced, not silent


# -- debug reasoning (MANDATORY, §6.2) ---------------------------------------
def test_debug_report_is_machine_and_human_readable():
    g = _city()
    c = _worker(g)
    c.sync_schedule(7.5, g)
    d = c.debug()
    for key in ["citizen_id", "doing", "active_goal", "why", "destination",
                "mode", "plan", "candidate_goals"]:
        assert key in d
    assert d["active_goal"]["kind"] == "arrive_at"
    text = c.debug_text()
    assert "Citizen c1" in text
    assert "Active goal" in text and "Mode" in text and "Plan" in text

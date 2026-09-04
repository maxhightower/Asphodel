"""Traffic ecology + semantic/physical reconciliation (AS-NAV-4, §9).

The three-tier hierarchy from §9:
  FAR   aggregate congestion on segments
  MID   individual semantic VehicleInstances progressing along routes
  NEAR  physical Godot cars (authored in engine)

This reconciler makes the layers agree instead of being disconnected fakes: the
MID instances' positions produce the FAR aggregate congestion that then feeds
back into every vehicle's route cost, so a morning commute — many people
independently driving to work over shared roads — makes congestion emerge on the
shared segments. Physical NEAR cars reconcile their route progress from their
physical position (physics is authority) via VehicleInstance.reconcile_from_physical.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..mobility import MobilityGraph, Route
from .instances import VehicleInstance, VehicleFidelity


class TrafficReconciler:
    def __init__(self, graph: MobilityGraph, ref_capacity: float = 8.0,
                 bpr_alpha: float = 0.15, bpr_beta: float = 4.0):
        self.graph = graph
        self.vehicles: Dict[str, VehicleInstance] = {}
        self.ref_capacity = ref_capacity
        self.bpr_alpha = bpr_alpha
        self.bpr_beta = bpr_beta

    def add_vehicle(self, v: VehicleInstance) -> None:
        self.vehicles[v.vehicle_id] = v

    def route_vehicle(self, vehicle_id: str, route: Route) -> None:
        self.vehicles[vehicle_id].assign_route(route, self.graph)

    # -- FAR aggregate from MID instances -----------------------------------
    def segment_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for v in self.vehicles.values():
            if v.fidelity in (VehicleFidelity.ROUTE_SIMULATED,
                              VehicleFidelity.PHYSICAL_CONTROLLED,
                              VehicleFidelity.PHYSICAL_CRASH) and not v.arrived:
                sid = v.current_segment(self.graph)
                if sid is not None:
                    counts[sid] = counts.get(sid, 0) + 1
        return counts

    def update_congestion(self) -> Dict[str, float]:
        """Set each segment's congestion from live vehicle counts (BPR). §9 feedback."""
        counts = self.segment_counts()
        factors: Dict[str, float] = {}
        for sid, seg in self.graph.segments.items():
            n = counts.get(sid, 0)
            cap = max(1.0, self.ref_capacity * max(1, seg.lanes))
            factor = 1.0 + self.bpr_alpha * (n / cap) ** self.bpr_beta
            seg.dynamic_state.congestion = factor
            factors[sid] = factor
        return factors

    def step(self, dt: float) -> None:
        """Advance the MID layer then reconcile FAR congestion. Deterministic."""
        for v in self.vehicles.values():
            v.advance_far(dt, self.graph)
        self.update_congestion()

    # -- NEAR <-> MID reconciliation ----------------------------------------
    def reconcile_physical(self, vehicle_id: str, physical_pos) -> None:
        self.vehicles[vehicle_id].reconcile_from_physical(physical_pos)

    def materialize_position(self, vehicle_id: str):
        """The semantic world position a NEAR car should spawn at (§12.1)."""
        return self.vehicles[vehicle_id].position(self.graph)

    def snapshot(self) -> List[dict]:
        return [v.to_dict(self.graph) for v in self.vehicles.values()]

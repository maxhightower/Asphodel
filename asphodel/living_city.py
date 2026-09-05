"""Headless living-city driver: a morning commute on a real bundle (§19, §25).

Loads a bundle's mobility graph, spawns a commuting population (homes on the
periphery, workplaces near the core), builds each citizen a route with the
CitizenRuntime's mode logic, and steps them through the morning peak with the
TrafficReconciler so congestion emerges from independent trips. Records every
agent's position each frame to a playback.json the Godot living-city scene renders.

Everything here is the same authoritative Python layer the tests exercise — this
just wires it to a concrete city and time window and writes positions out.
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .mobility import Mode, MobilityGraph, Route
from .transport import VehicleInstance, TrafficReconciler
from .transport.instances import route_polyline, _cumulative, point_at_distance

Vec2 = Tuple[float, float]

# agent state codes for the renderer
AT_HOME, EN_ROUTE, AT_WORK = 0, 1, 2


@dataclass
class _Agent:
    cid: str
    mode: Mode
    depart: float                 # game hour
    pts: List[Vec2]
    cum: List[float]
    speed_walk: float = 1.4
    vehicle: Optional[VehicleInstance] = None
    dist: float = 0.0             # metres travelled along the route
    state: int = AT_HOME

    @property
    def length(self) -> float:
        return self.cum[-1] if self.cum else 0.0

    def position(self) -> Vec2:
        if not self.pts:
            return (0.0, 0.0)
        if self.vehicle is not None:
            return self.vehicle.position()
        return point_at_distance(self.pts, self.cum, self.dist)


def simulate_commute(bundle_dir: str, n_citizens: int = 130, seed: int = 0,
                     start_hour: float = 6.5, end_hour: float = 9.0,
                     dt_min: float = 3.0, car_fraction: float = 0.55,
                     peak_hour: float = 7.3, peak_spread: float = 0.5) -> dict:
    """Run the commute and return the playback dict (also written to the bundle)."""
    with open(os.path.join(bundle_dir, "streetmap.json")) as f:
        graph = MobilityGraph.from_artifact(json.load(f))
    rng = random.Random(seed)

    # Work near the core (0,0); homes further out.
    nodes = list(graph.nodes.items())
    nodes.sort(key=lambda kv: kv[1][0] ** 2 + kv[1][1] ** 2)
    if len(nodes) < 8:
        raise ValueError("mobility graph too small to simulate")
    core = [nid for nid, _ in nodes[: max(4, len(nodes) // 4)]]
    outer = [nid for nid, _ in nodes[len(nodes) // 2:]]

    # A low reference capacity so convergence on the core approaches shows as
    # congestion (a coarse morning-rush proxy on the dispersed synth grid).
    reconciler = TrafficReconciler(graph, ref_capacity=2.0)
    agents: List[_Agent] = []
    for i in range(n_citizens):
        home = rng.choice(outer)
        work = rng.choice(core)
        if home == work:
            continue
        has_vehicle = rng.random() < car_fraction
        depart = min(end_hour - 0.5,
                     max(start_hour, rng.gauss(peak_hour, peak_spread)))
        mode = Mode.CAR if has_vehicle else Mode.FOOT
        route = graph.route(home, work, mode)
        if route is None or not route.segments:
            route = graph.route(home, work, Mode.FOOT)
            mode = Mode.FOOT
        if route is None or not route.segments:
            continue
        pts = route_polyline(graph, route)
        cum = _cumulative(pts)
        veh = None
        if mode == Mode.CAR:
            veh = VehicleInstance(f"veh{i}", "car")
            veh.assign_route(route, graph)
            reconciler.add_vehicle(veh)
        agents.append(_Agent(f"c{i}", mode, depart, pts, cum, vehicle=veh))

    # Step the morning.
    frames = []
    t = start_hour
    dt_h = dt_min / 60.0
    while t <= end_hour + 1e-9:
        dt_s = dt_h * 3600.0
        # advance cars that have departed (congestion-aware), then reconcile.
        for a in agents:
            if a.mode != Mode.CAR:
                continue
            if t >= a.depart and a.vehicle is not None and not a.vehicle.arrived:
                a.vehicle.advance_far(dt_s, graph)
        reconciler.update_congestion()
        # advance pedestrians.
        for a in agents:
            if a.mode == Mode.FOOT and t >= a.depart and a.dist < a.length:
                a.dist = min(a.length, a.dist + a.speed_walk * dt_s)
        # snapshot
        peds, cars = [], []
        for a in agents:
            if t < a.depart:
                a.state = AT_HOME
                pos = a.pts[0]
            else:
                done = (a.vehicle.arrived if a.vehicle else a.dist >= a.length)
                a.state = AT_WORK if done else EN_ROUTE
                pos = a.position()
            row = [round(pos[0], 1), round(pos[1], 1), a.state]
            if a.mode == Mode.CAR:
                cars.append(row)
            else:
                peds.append(row)
        congestion = [[sid, round(seg.dynamic_state.congestion, 2)]
                      for sid, seg in graph.segments.items()
                      if seg.dynamic_state.congestion > 1.05]
        frames.append({"t": round(t, 3), "peds": peds, "cars": cars,
                       "congestion": congestion})
        t += dt_h

    playback = {
        "version": "1",
        "bundle": os.path.basename(bundle_dir.rstrip("/")),
        "start_hour": start_hour, "end_hour": end_hour, "dt_min": dt_min,
        "n_citizens": len(agents),
        "n_cars": sum(1 for a in agents if a.mode == Mode.CAR),
        "frames": frames,
    }
    with open(os.path.join(bundle_dir, "playback.json"), "w") as f:
        json.dump(playback, f, separators=(",", ":"))
    return playback

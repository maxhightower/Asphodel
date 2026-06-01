"""
Vehicles & traffic: how citizens move across the street map, and the congestion
that emerges when they all move at once.

This closes the loop citizens -> buildings -> streets that the world layer opened:

* every commuter gets a **travel mode** (walk / bike / car / motorcycle / public
  transit) or, for driving jobs, their **work vehicle** (bus, van, truck, taxi,
  ambulance ...), chosen deterministically from occupation, trip distance, age,
  and whether the city actually has transit;
* a **road network** is derived from the ``StreetMap`` (each segment gets a
  free-flow speed and a capacity), and a **traffic assignment** routes a set of
  trips over it and computes congested travel times with the standard BPR volume
  -delay relation -- so a morning commute, or a panicked mass exodus, produces
  real jams instead of instant teleport.

This is also the micro-tier origin of the macro model's *emergent transport
hazard* (``EventParams``: panic-congestion ~ outflow^2, operator incapacitation
~ infected fraction of fleers). ``congestion_report`` exposes the network load
index those expectations are meant to track.

Distances are metres (the world frame), speeds km/h internally, times seconds.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ===========================================================================
# Vehicle catalogue
# ===========================================================================
@dataclass(frozen=True)
class VehicleSpec:
    """A vehicle kind.  ``pcu`` (passenger-car-units) is its weight in traffic;
    foot/bike are 0 (they don't jam roads).  ``occupancy`` is informational."""

    kind: str
    free_flow_kph: float
    pcu: float                          # road-space weight (car = 1.0)
    occupancy: int = 1
    length_m: float = 4.5
    emergency: bool = False

    @property
    def motorized(self) -> bool:
        return self.pcu > 0.0

    def speed_mps(self) -> float:
        return self.free_flow_kph * 1000.0 / 3600.0


# foot / bike are "vehicles" too so every trip has one uniform spec.
FOOT = VehicleSpec("foot", 5.0, 0.0, 1, 0.5)
BICYCLE = VehicleSpec("bicycle", 15.0, 0.0, 1, 1.8)
MOTORCYCLE = VehicleSpec("motorcycle", 45.0, 0.5, 1, 2.2)
CAR = VehicleSpec("car", 50.0, 1.0, 5, 4.5)
VAN = VehicleSpec("van", 45.0, 1.5, 3, 5.5)
TRUCK = VehicleSpec("truck", 40.0, 2.5, 2, 12.0)
BUS = VehicleSpec("bus", 30.0, 2.5, 50, 12.0)
AMBULANCE = VehicleSpec("ambulance", 60.0, 1.5, 2, 6.0, emergency=True)
FIRE_ENGINE = VehicleSpec("fire_engine", 50.0, 2.5, 4, 10.0, emergency=True)
POLICE_CAR = VehicleSpec("police_car", 60.0, 1.0, 4, 4.8, emergency=True)

VEHICLES: dict[str, VehicleSpec] = {
    v.kind: v for v in (FOOT, BICYCLE, MOTORCYCLE, CAR, VAN, TRUCK, BUS,
                        AMBULANCE, FIRE_ENGINE, POLICE_CAR)
}

# Driving / emergency jobs that come with a work vehicle.  These citizens travel
# in (and operate) that vehicle; everyone else picks a personal commute mode.
OCCUPATION_VEHICLE: dict[str, str] = {
    "bus_driver": "bus",
    "taxi_driver": "car",
    "truck_driver": "truck",
    "delivery_driver": "van",
    "postal_worker": "van",
    "courier": "bicycle",
    "paramedic": "ambulance",
    "firefighter": "fire_engine",
    "police_officer": "police_car",
}


def work_vehicle_for(occupation: str) -> Optional[str]:
    return OCCUPATION_VEHICLE.get(occupation)


def vehicle_class(kind: str) -> str:
    """Coarse class used to match travel events: nonmotorized / transit / motorized."""
    if kind in ("foot", "bicycle"):
        return "nonmotorized"
    if kind == "bus":
        return "transit"
    return "motorized"


# Per road-structure capacity and free-flow-speed multipliers.  Bridges and
# tunnels are chokepoints (they jam first under an exodus); highways flow fast.
STRUCT_CAPACITY = {"surface": 1.0, "highway": 1.6, "bridge": 0.5,
                   "tunnel": 0.5, "ramp": 0.6}
STRUCT_SPEED = {"surface": 1.0, "highway": 1.8, "bridge": 0.9,
                "tunnel": 0.8, "ramp": 0.7}


# ===========================================================================
# Mode choice
# ===========================================================================
@dataclass
class TrafficParams:
    """Knobs for mode choice and the traffic assignment."""

    # Mode-choice distance thresholds (metres).
    walk_max_m: float = 1500.0
    bike_max_m: float = 6000.0
    min_driving_age: int = 17

    # Personal-mode base weights by distance band (walk, bike, car, motorcycle).
    short_weights: tuple = (5.0, 3.0, 1.5, 0.4)     # <= walk_max
    medium_weights: tuple = (1.0, 3.0, 4.0, 0.8)    # <= bike_max
    long_weights: tuple = (0.0, 0.6, 6.0, 1.0)      # > bike_max
    transit_weight: float = 2.5                     # added when transit exists

    # Road network.
    default_speed_kph: float = 50.0
    capacity_per_segment: float = 600.0   # PCU/hour a street segment carries
    bpr_alpha: float = 0.15               # BPR volume-delay coefficients
    bpr_beta: float = 4.0


def choose_commute(rng: np.random.Generator, occupation: str, distance_m: float,
                   age: int, transit_available: bool,
                   params: TrafficParams = TrafficParams()) -> tuple[str, str]:
    """Pick a (mode, vehicle_kind) for one commuter.  Deterministic given ``rng``.

    Driving jobs use their work vehicle.  Otherwise the choice is distance- and
    age-aware: short hops favour walking/cycling, long ones driving or transit,
    and under-age citizens never drive a car.
    """
    wv = work_vehicle_for(occupation)
    if wv is not None:
        mode = "transit" if wv == "bus" else "drive_work"
        return mode, wv

    # Personal modes: (label, vehicle_kind, base_weight)
    if distance_m <= params.walk_max_m:
        w = params.short_weights
    elif distance_m <= params.bike_max_m:
        w = params.medium_weights
    else:
        w = params.long_weights
    options = [("walk", "foot", w[0]), ("bike", "bicycle", w[1]),
               ("car", "car", w[2]), ("motorcycle", "motorcycle", w[3])]
    if transit_available:
        options.append(("transit", "bus", params.transit_weight))

    # Under driving age: drop car/motorcycle.
    if age < params.min_driving_age:
        options = [o for o in options if o[1] not in ("car", "motorcycle")]

    weights = np.array([o[2] for o in options], dtype=float)
    if weights.sum() <= 0:
        choice = options[0]
    else:
        choice = options[int(rng.choice(len(options), p=weights / weights.sum()))]
    return choice[0], choice[1]


# ===========================================================================
# Road network + traffic assignment
# ===========================================================================
def _edge_key(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u <= v else (v, u)


@dataclass
class RoadNetwork:
    """A routable road network derived from a ``StreetMap``.

    Edges are undirected; each carries a length, a free-flow traversal time, and
    a capacity.  ``shortest_path`` is Dijkstra over free-flow time (the route
    drivers would take in light traffic); congestion is layered on afterwards.
    """

    nodes: dict[int, tuple[float, float]]
    adj: dict[int, list[tuple[int, tuple[int, int], float, float]]]  # nbr,key,len,fftime
    capacity: dict[tuple[int, int], float]
    length: dict[tuple[int, int], float]
    fftime: dict[tuple[int, int], float]

    @classmethod
    def from_street_map(cls, sm, params: TrafficParams = TrafficParams()) -> "RoadNetwork":
        base_mps = params.default_speed_kph * 1000.0 / 3600.0
        adj: dict[int, list] = {n: [] for n in sm.nodes}
        cap: dict[tuple[int, int], float] = {}
        length: dict[tuple[int, int], float] = {}
        fft: dict[tuple[int, int], float] = {}
        for u, v, w in sm.edges:
            key = _edge_key(u, v)
            structure = sm.edge_structure(u, v)
            speed_mps = base_mps * STRUCT_SPEED.get(structure, 1.0)
            t = w / speed_mps
            cap[key] = params.capacity_per_segment * STRUCT_CAPACITY.get(structure, 1.0)
            length[key] = w
            fft[key] = t
            adj[u].append((v, key, w, t))
            adj[v].append((u, key, w, t))
        return cls(nodes=dict(sm.nodes), adj=adj, capacity=cap,
                   length=length, fftime=fft)

    def shortest_path(self, origin: int, dest: int
                      ) -> tuple[list[tuple[int, int]], float]:
        """Return (list of edge keys along the route, total length)."""
        if origin == dest:
            return [], 0.0
        dist = {origin: 0.0}
        prev: dict[int, tuple[int, tuple[int, int]]] = {}
        pq = [(0.0, origin)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == dest:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, key, w, t in self.adj[u]:
                nd = d + t
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = (u, key)
                    heapq.heappush(pq, (nd, v))
        if dest not in prev and dest != origin:
            return [], math.inf
        # Reconstruct.
        edges, total_len, node = [], 0.0, dest
        while node != origin:
            pnode, key = prev[node]
            edges.append(key)
            total_len += self.length[key]
            node = pnode
        edges.reverse()
        return edges, total_len


@dataclass
class Trip:
    """One citizen's journey across the network."""

    citizen_id: int
    origin: int                          # street node id
    dest: int
    vehicle: str                         # vehicle kind
    mode: str = ""


@dataclass
class TrafficResult:
    """The outcome of assigning a trip set to the road network."""

    edge_volume: dict[tuple[int, int], float]      # PCU per edge
    edge_voc: dict[tuple[int, int], float]         # volume / capacity
    trip_seconds: dict[int, float]                 # citizen_id -> travel time (s)
    total_pcu: float
    loaded_edges: int

    def mean_voc(self) -> float:
        vals = [v for v in self.edge_voc.values() if v > 0]
        return float(np.mean(vals)) if vals else 0.0

    def max_voc(self) -> float:
        return float(max(self.edge_voc.values(), default=0.0))


def assign_traffic(trips: list[Trip], road: RoadNetwork,
                   params: TrafficParams = TrafficParams()) -> TrafficResult:
    """All-or-nothing assignment with BPR congestion.

    1. route every trip on its free-flow shortest path and accumulate PCU on each
       edge (walk/bike add 0 -- they don't consume road capacity);
    2. derive each edge's congested time via BPR
       ``t = t0 * (1 + alpha*(V/C)^beta)``;
    3. each trip's travel time is the sum of congested times along its route
       (non-motorised trips instead use distance / their own speed, so a cyclist
       isn't slowed by car jams).

    A single pass (no iterative equilibrium) -- adequate for a commute snapshot
    or an exodus pulse; iterating to user-equilibrium is the documented next step.
    """
    volume: dict[tuple[int, int], float] = {}
    routes: dict[int, tuple[list[tuple[int, int]], float, VehicleSpec]] = {}

    for tr in trips:
        spec = VEHICLES.get(tr.vehicle, CAR)
        edges, length = road.shortest_path(tr.origin, tr.dest)
        routes[tr.citizen_id] = (edges, length, spec)
        if spec.pcu > 0:
            for key in edges:
                volume[key] = volume.get(key, 0.0) + spec.pcu

    voc: dict[tuple[int, int], float] = {}
    ctime: dict[tuple[int, int], float] = {}
    for key, t0 in road.fftime.items():
        v = volume.get(key, 0.0)
        c = road.capacity.get(key, params.capacity_per_segment)
        ratio = v / c if c > 0 else 0.0
        voc[key] = ratio
        ctime[key] = t0 * (1.0 + params.bpr_alpha * ratio ** params.bpr_beta)

    trip_seconds: dict[int, float] = {}
    for cid, (edges, length, spec) in routes.items():
        if not math.isfinite(length):
            trip_seconds[cid] = math.inf
            continue
        if spec.motorized:
            trip_seconds[cid] = sum(ctime[k] for k in edges)
        else:
            trip_seconds[cid] = length / spec.speed_mps() if spec.speed_mps() else math.inf

    return TrafficResult(
        edge_volume=volume,
        edge_voc=voc,
        trip_seconds=trip_seconds,
        total_pcu=float(sum(volume.values())),
        loaded_edges=sum(1 for v in volume.values() if v > 0),
    )


# ===========================================================================
# Building trips out of a spawned population
# ===========================================================================
def build_commute_trips(world, population) -> list[Trip]:
    """Home->work trips for every commuter in a world-spawned population.

    Uses each citizen's resolved home/work buildings (their nearest street
    nodes) and chosen vehicle.  Citizens with no workplace, or whose mode wasn't
    resolved, are skipped.
    """
    by_id = world.street_map.by_id()
    trips: list[Trip] = []
    for c in population:
        if c.work_building_id is None or c.home_building_id is None:
            continue
        if not c.vehicle:
            continue
        home_b = by_id.get(c.home_building_id)
        work_b = by_id.get(c.work_building_id)
        if home_b is None or work_b is None:
            continue
        trips.append(Trip(citizen_id=c.citizen_id, origin=home_b.street_node,
                          dest=work_b.street_node, vehicle=c.vehicle,
                          mode=c.commute_mode or ""))
    return trips


def congestion_report(world, population,
                      params: TrafficParams = TrafficParams()) -> dict:
    """Assign the population's morning commute and summarise the load.

    The ``network_load`` / ``max_voc`` here are the micro-tier signal the macro
    model's panic-congestion expectation (~ outflow^2) is meant to approximate;
    a panicked mass exodus (everyone routing to the edge of the map) drives these
    sharply up, which is the hook into the infrastructure/event cascade.
    """
    road = RoadNetwork.from_street_map(world.street_map, params)
    trips = build_commute_trips(world, population)
    res = assign_traffic(trips, road, params)
    finite = [s for s in res.trip_seconds.values() if math.isfinite(s)]
    return {
        "commuters": len(trips),
        "motorized": sum(1 for t in trips if VEHICLES.get(t.vehicle, CAR).pcu > 0),
        "total_pcu": res.total_pcu,
        "loaded_edges": res.loaded_edges,
        "network_load": res.mean_voc(),      # mean volume/capacity over used edges
        "max_voc": res.max_voc(),            # worst bottleneck
        "mean_commute_min": (float(np.mean(finite)) / 60.0) if finite else 0.0,
        "result": res,
    }

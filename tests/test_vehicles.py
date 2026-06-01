"""
Vehicle & traffic tests: mode choice, the road network, BPR congestion, and the
population-level commute assignment.

Run with:  python -m pytest tests/test_vehicles.py -q
       or:  python tests/test_vehicles.py
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.vehicles import (
    VEHICLES, FOOT, CAR, BUS, TrafficParams, Trip, RoadNetwork,
    choose_commute, work_vehicle_for, assign_traffic,
    build_commute_trips, congestion_report,
)
from asphodel.world import synthesize_city, SynthCitySpec
from asphodel.citizen import (
    default_catalog, default_cities, resolve_world, spawn_population_in_world,
)


CATALOG = default_catalog()


# --------------------------------------------------------------------------- #
# vehicle catalogue
# --------------------------------------------------------------------------- #
def test_vehicle_catalogue_invariants():
    assert FOOT.pcu == 0.0 and not FOOT.motorized
    assert CAR.pcu == 1.0 and CAR.motorized
    assert BUS.occupancy > CAR.occupancy
    for spec in VEHICLES.values():
        assert spec.free_flow_kph > 0 and spec.speed_mps() > 0


def test_work_vehicle_mapping():
    assert work_vehicle_for("truck_driver") == "truck"
    assert work_vehicle_for("paramedic") == "ambulance"
    assert work_vehicle_for("office_worker") is None


# --------------------------------------------------------------------------- #
# mode choice
# --------------------------------------------------------------------------- #
def test_driving_job_uses_work_vehicle():
    rng = np.random.default_rng(0)
    mode, veh = choose_commute(rng, "bus_driver", 3000, 40, True)
    assert veh == "bus"
    mode, veh = choose_commute(rng, "truck_driver", 8000, 40, False)
    assert veh == "truck" and mode == "drive_work"


def test_underage_never_drives_a_car():
    for s in range(50):
        rng = np.random.default_rng(s)
        mode, veh = choose_commute(rng, "student", 4000, 14, True)
        assert veh not in ("car", "motorcycle")


def test_mode_choice_is_deterministic():
    a = choose_commute(np.random.default_rng(3), "office_worker", 5000, 35, True)
    b = choose_commute(np.random.default_rng(3), "office_worker", 5000, 35, True)
    assert a == b


def test_distance_shifts_mode_distribution():
    """Short trips favour walking/cycling; long trips favour driving/transit."""
    short = Counter()
    long = Counter()
    for s in range(300):
        short[choose_commute(np.random.default_rng(s), "office_worker", 500, 35, True)[1]] += 1
        long[choose_commute(np.random.default_rng(s), "office_worker", 12000, 35, True)[1]] += 1
    walk_bike_short = short["foot"] + short["bicycle"]
    car_long = long["car"]
    assert walk_bike_short > short["car"]
    assert car_long > long["foot"] + long["bicycle"]


# --------------------------------------------------------------------------- #
# road network + assignment
# --------------------------------------------------------------------------- #
def _road(seed=0):
    sm = synthesize_city(SynthCitySpec(blocks_x=4, blocks_y=4), seed=seed)
    return sm, RoadNetwork.from_street_map(sm)


def test_shortest_path_routes_between_nodes():
    sm, road = _road()
    nodes = list(road.nodes)
    edges, length = road.shortest_path(nodes[0], nodes[-1])
    assert edges and math.isfinite(length) and length > 0
    # Zero-length self route.
    assert road.shortest_path(nodes[0], nodes[0]) == ([], 0.0)


def test_congestion_increases_travel_time():
    sm, road = _road()
    nodes = list(road.nodes)
    o, d = nodes[0], nodes[-1]
    # One car vs many cars on the same OD pair: shared edges congest.
    light = assign_traffic([Trip(0, o, d, "car")], road)
    heavy = assign_traffic([Trip(i, o, d, "car") for i in range(2000)], road)
    assert heavy.max_voc() > light.max_voc()
    assert heavy.trip_seconds[0] > light.trip_seconds[0]   # BPR slows the route


def test_non_motorized_trip_ignores_car_jams():
    sm, road = _road()
    nodes = list(road.nodes)
    o, d = nodes[0], nodes[-1]
    trips = [Trip(0, o, d, "foot")] + [Trip(i, o, d, "car") for i in range(1, 1500)]
    res = assign_traffic(trips, road)
    # The walker contributes no PCU and their time is distance/own speed.
    edges, length = road.shortest_path(o, d)
    assert abs(res.trip_seconds[0] - length / FOOT.speed_mps()) < 1e-6


def test_assignment_is_deterministic():
    sm, road = _road()
    nodes = list(road.nodes)
    trips = [Trip(i, nodes[0], nodes[-1], "car") for i in range(100)]
    a = assign_traffic(trips, road)
    b = assign_traffic(trips, road)
    assert a.edge_volume == b.edge_volume and a.trip_seconds == b.trip_seconds


# --------------------------------------------------------------------------- #
# population-level commute
# --------------------------------------------------------------------------- #
def test_congestion_report_on_world():
    cw = resolve_world(default_cities()["harbor"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=300, seed=1)
    rep = congestion_report(cw, pop)
    assert rep["commuters"] > 0
    assert rep["motorized"] <= rep["commuters"]
    assert rep["total_pcu"] > 0 and rep["loaded_edges"] > 0
    assert rep["mean_commute_min"] > 0
    # Every commuter trip references real buildings -> real street nodes.
    trips = build_commute_trips(cw, pop)
    assert all(t.origin in cw.street_map.nodes for t in trips)


def test_more_commuters_raise_network_load():
    cw = resolve_world(default_cities()["capital"], seed=0)
    small = spawn_population_in_world(cw, CATALOG, n=120, seed=0)
    large = spawn_population_in_world(cw, CATALOG, n=900, seed=0)
    r_small = congestion_report(cw, small)
    r_large = congestion_report(cw, large)
    assert r_large["total_pcu"] > r_small["total_pcu"]
    assert r_large["max_voc"] >= r_small["max_voc"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

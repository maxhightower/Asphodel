"""Parking anchor selection on the canonical world (ASPHODEL_EMBODIED_MOBILITY_V1 §13).

A parked car is never faked at the door: the chosen anchor is a compiled
PARKING_ANCHOR/DRIVEWAY_ANCHOR that is reachable from a car-legal street, is
not inside a footprint, does not block an entrance and does not overlap another
parked car — and the choice is deterministic. When nothing is valid the answer
is None, not a spot invented at the destination.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.embodied import load_entrances
from asphodel.embodied.parking import (ENTRANCE_CLEARANCE_M, MAX_CANDIDATES,
                                       PARKING_KINDS, SEARCH_RADIUS_M,
                                       VEHICLE_CLEARANCE_M, ParkingIndex,
                                       _point_in_poly, choose_parking)
from asphodel.embodied.pathing import MAX_CONNECTOR_M
from asphodel.embodiment import CitySpatialContext
from asphodel.mobility import Mode

CITY = "houston"
WORK_BUILDING = 4517


@pytest.fixture(scope="module")
def city():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    ctx = CitySpatialContext.from_bundle_dir(d)
    entrances, anchors = load_entrances(d)
    index = ParkingIndex(d, anchors, entrances)

    import numpy as np

    def polys_near(xy, r):
        cents = ctx.building_centroids
        d2 = (cents[:, 0] - xy[0]) ** 2 + (cents[:, 1] - xy[1]) ** 2
        ii = np.nonzero(d2 <= (r + 60.0) ** 2)[0]
        return [ctx.building_polys[int(i)] for i in ii if ctx.building_polys[int(i)]]

    return {"dir": d, "ctx": ctx, "graph": ctx.street_graph, "entrances": entrances,
            "anchors": anchors, "index": index, "polys": polys_near,
            "dest": entrances[WORK_BUILDING]}


@pytest.fixture()
def fresh(city):
    """The shared index with occupancy reset (module fixture stays cheap)."""
    city["index"].occupied = {}
    city["index"].occupied_xy = {}
    return city


def _choose(c, **kw):
    return choose_parking(c["index"], c["graph"], c["dest"], c["polys"], **kw)


# --------------------------------------------------------------------------- #
def test_index_holds_only_parking_anchors(city):
    idx = city["index"]
    assert len(idx.rows) > 100
    assert {kind for _, kind, _ in idx.rows} <= set(PARKING_KINDS)
    # rows are sorted for a deterministic window scan
    assert idx._xs == sorted(idx._xs)
    cands = idx.candidates_near(city["dest"], SEARCH_RADIUS_M)
    assert 0 < len(cands) <= MAX_CANDIDATES
    assert all(math.dist(xy, city["dest"]) <= SEARCH_RADIUS_M for _, _, xy in cands)
    # nearest-first, ties by row index
    keys = [(round(math.dist(xy, city["dest"]), 6), i) for i, _, xy in cands]
    assert keys == sorted(keys)


def test_chosen_parking_is_valid(fresh):
    c = _choose(fresh)
    assert c is not None, "no valid parking near the work entrance"
    assert c.kind in PARKING_KINDS
    assert c.node_id == f"park:{c.index}"

    # reachable from a car-legal street
    assert c.access.connector_m <= MAX_CONNECTOR_M
    assert c.access.connector_m <= 60.0
    assert fresh["graph"].segments[c.access.segment_id].allows(Mode.CAR)

    # not inside a building footprint
    for poly in fresh["polys"](c.xy, 40.0):
        assert not _point_in_poly(c.xy, poly), "parked inside a building"

    # does not block an entrance
    for e in fresh["index"].entrances_near(c.xy, 50.0):
        assert math.dist(e, c.xy) >= ENTRANCE_CLEARANCE_M

    # does not overlap a statically placed (chunk) vehicle
    for p in fresh["index"].static_vehicles_near(c.xy, 50.0):
        assert math.dist(p, c.xy) >= VEHICLE_CLEARANCE_M

    assert c.distance_to_entrance <= SEARCH_RADIUS_M
    assert c.to_dict()["node"] == c.node_id


def test_choice_is_deterministic(fresh):
    a = _choose(fresh)
    b = _choose(fresh)
    assert a is not None and b is not None
    assert a.index == b.index
    assert a.to_dict() == b.to_dict()


def test_occupying_moves_the_next_car_and_releasing_restores(fresh):
    first = _choose(fresh)
    assert first is not None
    fresh["index"].occupy(first.index, "veh:A", first.xy)
    second = _choose(fresh, exclude_vehicle="veh:B")
    assert second is not None
    assert second.index != first.index, "two cars must not take the same anchor"
    assert second.rejected.get("occupied", 0) >= 1        # the census explains why
    assert math.dist(second.xy, first.xy) >= VEHICLE_CLEARANCE_M

    # the car that already holds the anchor keeps it (exclude_vehicle)
    mine = _choose(fresh, exclude_vehicle="veh:A")
    assert mine is not None and mine.index == first.index

    fresh["index"].release("veh:A")
    assert fresh["index"].occupied == {} and fresh["index"].occupied_xy == {}
    again = _choose(fresh)
    assert again is not None and again.index == first.index


def test_live_parked_vehicle_clearance(fresh):
    first = _choose(fresh)
    assert first is not None
    # a live vehicle standing on the spot (not registered against its anchor row)
    fresh["index"].occupy(-1, "veh:ghost", first.xy)
    nxt = _choose(fresh)
    assert nxt is not None and nxt.index != first.index
    assert nxt.rejected.get("overlaps_live_vehicle", 0) >= 1
    assert math.dist(nxt.xy, first.xy) >= VEHICLE_CLEARANCE_M


def test_all_candidates_occupied_returns_none(fresh):
    idx = fresh["index"]
    cands = idx.candidates_near(fresh["dest"], SEARCH_RADIUS_M)
    assert cands
    for n, (i, _kind, xy) in enumerate(cands):
        idx.occupy(i, f"veh:full{n}", xy)
    assert _choose(fresh) is None, "a full street must not invent a space"
    # the census is what a caller inspects on the last valid choice; with
    # everything taken, the rejection reason is uniformly 'occupied'.
    idx.release("veh:full0")
    back = _choose(fresh)
    assert back is not None
    assert back.index == cands[0][0]
    assert sum(back.rejected.values()) == 0


def test_unreachable_destination_has_no_parking(fresh):
    far = choose_parking(fresh["index"], fresh["graph"], (1.0e6, 1.0e6), fresh["polys"])
    assert far is None

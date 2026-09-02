"""Package E: vehicle de-overlap removes intersecting vehicles but keeps valid
dense parking (side-by-side stalls) and non-vehicle props."""
from __future__ import annotations

from asphodel.world_source.detail import dedupe_vehicles
from asphodel.world_source.records import Placement


def _veh(kind, x, z, rot=0.0):
    return Placement(kind, x, z, rot, 0, "vehicle")


def _n_vehicles(pl):
    return sum(1 for p in pl if p.cat == "vehicle")


def test_stacked_vehicles_deduped():
    out = dedupe_vehicles([_veh("sedan", 0, 0), _veh("sedan", 0.3, 0.2)])
    assert _n_vehicles(out) == 1


def test_far_vehicles_kept():
    out = dedupe_vehicles([_veh("sedan", 0, 0), _veh("suv", 20, 0)])
    assert _n_vehicles(out) == 2


def test_side_by_side_parking_kept():
    # two sedans nose-in, adjacent along their WIDTH axis (2.0 m wide) at 2.6 m
    # stall spacing — should NOT be treated as overlapping.
    out = dedupe_vehicles([_veh("sedan", 0, 0, 0.0), _veh("sedan", 2.6, 0, 0.0)])
    assert _n_vehicles(out) == 2


def test_overlapping_wide_vehicles_deduped():
    # box_trucks (2.5 m wide) only 1.5 m apart clearly intersect -> drop one.
    out = dedupe_vehicles([_veh("box_truck", 0, 0, 0.0), _veh("box_truck", 1.5, 0, 0.0)])
    assert _n_vehicles(out) == 1


def test_lengthwise_adjacent_deduped():
    # two sedans end-to-end 2.6 m apart (length 4.6 m) intersect -> drop one.
    out = dedupe_vehicles([_veh("sedan", 0, 0, 0.0), _veh("sedan", 0, 2.6, 0.0)])
    assert _n_vehicles(out) == 1


def test_non_vehicles_untouched():
    props = [Placement("mailbox", 0, 0, 0, 0, "prop"),
             Placement("tree_round", 0.1, 0.1, 0, 0, "tree")]
    out = dedupe_vehicles(props + [_veh("sedan", 5, 5)])
    assert len(out) == 3
    assert sum(1 for p in out if p.cat == "prop") == 1
    assert sum(1 for p in out if p.cat == "tree") == 1


def test_deterministic():
    a = [_veh("sedan", i * 0.5, 0) for i in range(10)]
    r1 = dedupe_vehicles(list(a))
    r2 = dedupe_vehicles(list(reversed(a)))
    assert _n_vehicles(r1) == _n_vehicles(r2)

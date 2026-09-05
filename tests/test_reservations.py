"""The occupancy / reservation ledger (ASPHODEL_SMART_OBJECTS_WORK_V1 §10).

One ledger per world, four invariants (S8):

* an exclusive object has at most one holder — a second hold is refused and
  changes nothing;
* a shared object holds up to ``capacity`` citizens and no more;
* a citizen holds at most one exclusive object: taking a second releases the
  first (nobody sits on two chairs);
* every hold survives save/load and is released explicitly.

No world, no bundle: the ledger is exercised against real
:class:`asphodel.smart.objects.SmartObject` instances built from the kind table.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.smart import OBJECT_KINDS, ReservationLedger
from asphodel.smart.objects import SmartObject


def _obj(object_id: str, kind: str = "checkout", room_id: int = 0) -> SmartObject:
    spec = OBJECT_KINDS[kind]
    return SmartObject(object_id, kind, 1, room_id, 0.0, 0.0, 0.0,
                       frozenset(spec["caps"]), tuple(spec["aff"]), bool(spec["exclusive"]),
                       int(spec["capacity"]), dict(spec["state"]))


@pytest.fixture
def led():
    return ReservationLedger()


@pytest.fixture
def station():
    return _obj("so:1:1", "checkout")


@pytest.fixture
def shelf():
    return _obj("so:1:2", "gondola")          # shared, capacity 3


# --------------------------------------------------------------------------- #
# exclusive objects (S8)
# --------------------------------------------------------------------------- #
def test_an_empty_ledger_holds_nothing(led, station):
    assert led.holders_of(station.object_id) == []
    assert led.held_by(7) == []
    assert led.is_free(station, True) is True
    assert led.free_capacity(station) == 1
    assert led.to_state() == {"holders": {}, "since": [], "exclusive_of": {}}


def test_an_exclusive_object_has_exactly_one_holder(led, station):
    assert led.hold(station, 7, 100.0) is True
    assert led.holders_of(station.object_id) == [7]
    assert led.exclusive_of[7] == station.object_id
    assert led.is_free(station, True) is False
    assert led.free_capacity(station) == 0


def test_a_second_citizen_cannot_take_a_held_exclusive_object(led, station):
    led.hold(station, 7, 100.0)
    before = led.to_state()
    assert led.hold(station, 9, 101.0) is False
    assert led.holders_of(station.object_id) == [7]
    assert led.held_by(9) == []
    assert 9 not in led.exclusive_of
    assert led.to_state() == before, "a refused hold must change nothing"


def test_re_holding_your_own_object_is_idempotent(led, station):
    assert led.hold(station, 7, 100.0) is True
    assert led.hold(station, 7, 200.0) is True
    assert led.holders_of(station.object_id) == [7]
    assert led.since[(station.object_id, 7)] == 100.0, "the original hold time is kept"


def test_the_object_is_free_again_after_a_release(led, station):
    led.hold(station, 7, 100.0)
    assert led.release(7, station.object_id) == [station.object_id]
    assert led.holders_of(station.object_id) == []
    assert led.exclusive_of.get(7) is None
    assert (station.object_id, 7) not in led.since
    assert led.hold(station, 9, 150.0) is True
    assert led.holders_of(station.object_id) == [9]


# --------------------------------------------------------------------------- #
# shared objects
# --------------------------------------------------------------------------- #
def test_a_shared_object_admits_up_to_its_capacity(led, shelf):
    assert shelf.capacity == 3 and shelf.exclusive is False
    for i, cid in enumerate((1, 2, 3)):
        assert led.hold(shelf, cid, 10.0 + i) is True
        assert led.free_capacity(shelf) == 3 - (i + 1)
    assert led.holders_of(shelf.object_id) == [1, 2, 3]
    assert led.is_free(shelf, False) is False
    assert led.hold(shelf, 4, 20.0) is False
    assert led.holders_of(shelf.object_id) == [1, 2, 3]


def test_a_freed_slot_on_a_shared_object_is_reusable(led, shelf):
    for cid in (1, 2, 3):
        led.hold(shelf, cid, 10.0)
    led.release(2, shelf.object_id)
    assert led.holders_of(shelf.object_id) == [1, 3]
    assert led.hold(shelf, 4, 30.0) is True
    assert led.holders_of(shelf.object_id) == [1, 3, 4]


def test_a_shared_object_taken_exclusively_admits_nobody_else(led, shelf):
    """A cleaner needs the whole shelf: an exclusive hold on a shared object
    blocks the pool while it lasts."""
    assert led.hold(shelf, 7, 10.0, exclusive=True) is True
    assert led.exclusive_of[7] == shelf.object_id
    assert led.hold(shelf, 8, 11.0, exclusive=True) is False
    assert led.hold(shelf, 8, 11.0, exclusive=False) is True, \
        "a shared hold still fits under capacity"
    assert led.holders_of(shelf.object_id) == [7, 8]


def test_a_shared_hold_does_not_claim_the_citizens_exclusive_slot(led, shelf, station):
    assert led.hold(shelf, 7, 10.0) is True
    assert 7 not in led.exclusive_of
    assert led.hold(station, 7, 11.0) is True
    assert led.exclusive_of[7] == station.object_id
    assert sorted(led.held_by(7)) == sorted([shelf.object_id, station.object_id])


# --------------------------------------------------------------------------- #
# one exclusive object per citizen
# --------------------------------------------------------------------------- #
def test_a_second_exclusive_hold_releases_the_first(led):
    a, b = _obj("so:1:1"), _obj("so:1:2")
    led.hold(a, 7, 100.0)
    assert led.hold(b, 7, 200.0) is True
    assert led.holders_of(a.object_id) == [], "the first station was not released"
    assert led.holders_of(b.object_id) == [7]
    assert led.exclusive_of[7] == b.object_id
    assert led.held_by(7) == [b.object_id]


def test_no_citizen_ever_holds_two_exclusive_objects(led):
    objs = [_obj(f"so:1:{i}") for i in range(6)]
    for i, o in enumerate(objs):
        led.hold(o, 7, float(i))
        excl = [oid for oid in led.held_by(7)
                if any(x.object_id == oid and x.exclusive for x in objs)]
        assert len(excl) == 1, excl
    assert sum(len(h) for h in led.holders.values()) == 1


def test_held_by_is_sorted_and_release_all_empties_it(led, station, shelf):
    led.hold(shelf, 7, 1.0)
    led.hold(station, 7, 2.0)
    assert led.held_by(7) == sorted([shelf.object_id, station.object_id])
    released = led.release(7)
    assert sorted(released) == sorted([shelf.object_id, station.object_id])
    assert led.held_by(7) == []
    assert 7 not in led.exclusive_of
    assert led.holders == {}


def test_releasing_something_you_do_not_hold_is_a_no_op(led, station):
    led.hold(station, 7, 1.0)
    assert led.release(9, station.object_id) == []
    assert led.holders_of(station.object_id) == [7]
    assert led.release(9) == []


def test_release_object_evicts_every_holder(led, shelf):
    for cid in (1, 2, 3):
        led.hold(shelf, cid, 5.0)
    assert led.release_object(shelf.object_id) == [1, 2, 3]
    assert led.holders_of(shelf.object_id) == []
    assert all(c not in led.exclusive_of for c in (1, 2, 3))
    assert led.release_object(shelf.object_id) == []


def test_release_object_of_an_exclusive_station_clears_the_exclusive_slot(led, station):
    led.hold(station, 7, 5.0)
    assert led.release_object(station.object_id) == [7]
    assert led.exclusive_of.get(7) is None
    assert led.holders == {}


def test_an_emptied_object_leaves_no_empty_list_behind(led, station):
    led.hold(station, 7, 1.0)
    led.release(7, station.object_id)
    assert station.object_id not in led.holders
    assert led.to_state()["holders"] == {}


# --------------------------------------------------------------------------- #
# persistence + determinism
# --------------------------------------------------------------------------- #
def _populate(led):
    st = _obj("so:1:1")
    sh = _obj("so:1:2", "gondola")
    seat = _obj("so:1:3", "chair")
    led.hold(st, 7, 100.0)
    led.hold(sh, 7, 101.0)
    led.hold(sh, 8, 102.0)
    led.hold(seat, 9, 103.0)
    return led


def test_to_state_round_trips_through_from_state(led):
    _populate(led)
    st = led.to_state()
    back = ReservationLedger.from_state(st)
    assert back.to_state() == st
    assert back.holders == led.holders
    assert back.since == led.since
    assert back.exclusive_of == led.exclusive_of
    assert back.held_by(7) == led.held_by(7)


def test_to_state_is_json_shaped_and_sorted(led):
    import json
    _populate(led)
    st = led.to_state()
    assert json.loads(json.dumps(st)) == st
    assert list(st["holders"]) == sorted(st["holders"])
    assert st["since"] == sorted(st["since"])
    assert all(isinstance(k, str) for k in st["exclusive_of"])
    assert st["exclusive_of"]["7"] == "so:1:1"


def test_from_state_of_an_empty_dict_is_an_empty_ledger():
    led = ReservationLedger.from_state({})
    assert led.holders == {} and led.since == {} and led.exclusive_of == {}
    assert led.to_state() == {"holders": {}, "since": [], "exclusive_of": {}}


def test_a_restored_ledger_enforces_the_same_invariants(led):
    _populate(led)
    back = ReservationLedger.from_state(led.to_state())
    st = _obj("so:1:1")
    assert back.hold(st, 42, 200.0) is False, "the restored exclusive hold was forgotten"
    sh = _obj("so:1:2", "gondola")
    assert back.hold(sh, 42, 200.0) is True and back.hold(sh, 43, 201.0) is False


def test_the_ledger_is_deterministic_for_the_same_operation_sequence():
    def run():
        led = ReservationLedger()
        objs = {i: _obj(f"so:1:{i}", "checkout" if i % 2 else "gondola") for i in range(6)}
        for step in range(40):
            o = objs[step % 6]
            cid = (step * 7) % 5
            if step % 3 == 2:
                led.release(cid, o.object_id)
            else:
                led.hold(o, cid, float(step))
        return led.to_state()
    assert run() == run()
    assert run()["holders"], "the sequence left nothing held"

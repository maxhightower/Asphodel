"""The job / task grammar and deterministic employment
(ASPHODEL_SMART_OBJECTS_WORK_V1 §5, §7) — pure unit tests, no world.

* ``role_for_occupation`` is a data table, not code;
* employment is a pure function of (seed, citizen, occupation, workplace
  objects): the same inputs always give the same role and station, different
  citizens get different stations while stations last, and the citizen after
  the last till gets the next role its workplace can support (S4);
* task durations are deterministic and inside the grammar's declared bounds;
* every role's grammar is satisfiable: each task names an affordance some
  object kind actually offers, and each role's ``required_caps`` are carried
  together by at least one kind.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import interiors
from asphodel.smart import OBJECT_KINDS, ROLES, SmartObjectRegistry, employment_for, \
    role_for_occupation
from asphodel.smart.jobs import _DEFAULT_ROLES, _OCCUPATION_ROLES, Employment, task_duration

SEED = 7
FOOTPRINT = [[0, 0], [30, 0], [30, 20], [0, 20]]


@pytest.fixture(scope="module")
def shop():
    d = interiors.build_interior(1234, SEED, FOOTPRINT, arch_hint="retail")
    return SmartObjectRegistry(d.building_id, d)


@pytest.fixture(scope="module")
def office():
    d = interiors.build_interior(1235, SEED, FOOTPRINT, arch_hint="office")
    return SmartObjectRegistry(d.building_id, d)


@pytest.fixture(scope="module")
def house():
    d = interiors.build_interior(1236, SEED, FOOTPRINT, arch_hint="house")
    return SmartObjectRegistry(d.building_id, d)


# --------------------------------------------------------------------------- #
# the occupation -> role table
# --------------------------------------------------------------------------- #
def test_role_for_occupation_reads_the_table():
    assert role_for_occupation("grocery_clerk")[0] == "cashier"
    assert role_for_occupation("office_worker")[0] == "desk_worker"
    assert role_for_occupation("cleaner") == ("cleaner",)
    assert role_for_occupation("warehouse_worker")[0] == "stocker"


def test_an_unknown_or_empty_occupation_falls_back_to_the_default_ladder():
    for occ in ("astronaut", "", None):
        assert role_for_occupation(occ) == _DEFAULT_ROLES
    assert set(_DEFAULT_ROLES) <= set(ROLES)


def test_every_occupation_maps_only_to_roles_that_exist():
    for occ, roles in _OCCUPATION_ROLES.items():
        assert roles, occ
        for r in roles:
            assert r in ROLES, (occ, r)
        assert len(set(roles)) == len(roles), occ


# --------------------------------------------------------------------------- #
# the role grammar
# --------------------------------------------------------------------------- #
def test_every_task_names_an_affordance_some_object_kind_offers():
    offered = {a.name for spec in OBJECT_KINDS.values() for a in spec["aff"]}
    for name, role in ROLES.items():
        assert role.tasks, name
        for t in role.tasks:
            assert t.affordance in offered, (name, t.task_id, t.affordance)


def test_every_task_target_is_reachable_by_capability():
    """A task's caps must be carried, together with its affordance, by at least
    one object kind — otherwise the selector can never find a target."""
    for name, role in ROLES.items():
        for t in role.tasks:
            ok = [k for k, spec in OBJECT_KINDS.items()
                  if t.affordance in {a.name for a in spec["aff"]}
                  and set(t.caps) <= set(spec["caps"])]
            assert ok, (name, t.task_id, t.affordance, t.caps)


def test_every_role_requires_capabilities_one_kind_can_satisfy():
    for name, role in ROLES.items():
        if not role.required_caps:
            continue
        ok = [k for k, spec in OBJECT_KINDS.items() if set(role.required_caps) <= set(spec["caps"])]
        assert ok, (name, role.required_caps)


def test_the_role_grammar_is_well_formed():
    known_selectors = {"assigned", "any_free", "dirtiest", "depleted", "supplies", "goods",
                       "seat", "wait_zone"}
    known_holds = {"exclusive", "shared", "none"}
    known_pre = {"", "break_due", "customer_waiting", "has_supplies", "needs_supplies",
                 "has_goods", "needs_goods"}
    for name, role in ROLES.items():
        assert role.name == name
        assert role.workplace_zones, name
        assert role.break_after_s > 0 and role.break_s > 0
        ids = [t.task_id for t in role.tasks]
        assert len(set(ids)) == len(ids), name
        for t in role.tasks:
            assert t.selector in known_selectors, (name, t.task_id, t.selector)
            assert t.hold in known_holds, (name, t.task_id, t.hold)
            assert t.precondition in known_pre, (name, t.task_id, t.precondition)
            lo, hi = t.duration_s
            assert 0 < lo <= hi, (name, t.task_id, t.duration_s)
            assert 0.0 <= t.priority <= 1.0, (name, t.task_id)


def test_the_three_certified_archetypes_and_the_stocker_exist():
    assert {"cashier", "desk_worker", "cleaner", "stocker"} <= set(ROLES)
    assert ROLES["cashier"].required_caps == ("station", "transact")
    assert ROLES["desk_worker"].required_caps == ("station", "desk_work")
    assert ROLES["cleaner"].required_caps == ()
    assert ROLES["stocker"].required_caps == ("shelf", "stock")


def test_every_role_can_take_a_break_at_the_highest_priority():
    for name, role in ROLES.items():
        breaks = [t for t in role.tasks if t.precondition == "break_due"]
        assert len(breaks) == 1, name
        assert breaks[0].priority == max(t.priority for t in role.tasks), name
        assert breaks[0].effect == "rest"


def test_a_cleaner_must_fetch_supplies_before_it_can_clean():
    tasks = {t.task_id: t for t in ROLES["cleaner"].tasks}
    assert tasks["fetch_supplies"].carry == "supplies"
    assert tasks["clean_object"].precondition == "has_supplies"
    assert tasks["fetch_supplies"].priority > tasks["clean_object"].priority
    assert tasks["clean_object"].effect == "clean"


def test_a_stocker_must_fetch_goods_before_it_can_restock():
    tasks = {t.task_id: t for t in ROLES["stocker"].tasks}
    assert tasks["fetch_goods"].carry == "goods"
    assert tasks["restock_shelf"].precondition == "has_goods"
    assert tasks["restock_shelf"].priority > tasks["face_shelf"].priority


# --------------------------------------------------------------------------- #
# employment (S4)
# --------------------------------------------------------------------------- #
def test_employment_is_a_pure_function_of_its_inputs(shop):
    a = employment_for(SEED, 129, "grocery_clerk", 6059, shop, {})
    b = employment_for(SEED, 129, "grocery_clerk", 6059, shop, {})
    assert a.to_dict() == b.to_dict()
    assert a.role == "cashier" and a.assigned_object is not None
    assert shop.get(a.assigned_object).has("station", "transact")
    assert a.citizen_id == 129 and a.workplace_id == 6059 and a.occupation == "grocery_clerk"


def test_a_different_seed_can_move_the_station_but_never_the_role(shop):
    roles = set()
    for seed in range(12):
        e = employment_for(seed, 129, "grocery_clerk", 6059, shop, {})
        roles.add(e.role)
        assert shop.get(e.assigned_object) is not None
    assert roles == {"cashier"}


def test_different_citizens_take_different_stations_while_stations_last(shop):
    """S4: assignment is exclusive — a station belongs to one citizen."""
    stations = shop.with_caps("station", "transact")
    assert len(stations) >= 3
    taken = {}
    emps = []
    for cid in range(len(stations)):
        e = employment_for(SEED, cid, "grocery_clerk", 6059, shop, taken)
        assert e is not None and e.role == "cashier", cid
        emps.append(e)
    assigned = [e.assigned_object for e in emps]
    assert len(set(assigned)) == len(assigned), assigned
    assert set(assigned) == {o.object_id for o in stations}
    assert taken == {e.assigned_object: e.citizen_id for e in emps}


def test_the_citizen_after_the_last_till_gets_the_next_role_it_can_do(shop):
    """S4: a fourth clerk at a two-till shop stocks shelves instead."""
    stations = shop.with_caps("station", "transact")
    taken = {}
    for cid in range(len(stations)):
        employment_for(SEED, cid, "grocery_clerk", 6059, shop, taken)
    overflow = employment_for(SEED, 900, "grocery_clerk", 6059, shop, taken)
    assert overflow is not None
    assert overflow.role != "cashier"
    assert overflow.role in role_for_occupation("grocery_clerk")
    assert overflow.role == "stocker" and overflow.assigned_object is None
    # and the roles keep falling back in the table's order
    assert role_for_occupation("grocery_clerk").index(overflow.role) == 1


def test_a_workplace_without_the_required_objects_skips_the_role(office, house):
    """An office has no till: a grocery clerk there is not a cashier."""
    e = employment_for(SEED, 5, "grocery_clerk", 4587, office, {})
    assert e is not None and e.role != "cashier"
    assert e.role in role_for_occupation("grocery_clerk")
    # a house has no till either: the clerk falls further down the same ladder
    h = employment_for(SEED, 5, "grocery_clerk", 999, house, {})
    assert h is not None and h.role != "cashier" and h.assigned_object is None
    assert h.role in role_for_occupation("grocery_clerk")


class _BareRegistry:
    """A workplace whose interior offers no usable object at all."""
    building_id = 42

    def with_caps(self, *caps):
        return []

    def get(self, object_id):
        return None


def test_a_workplace_with_no_usable_object_still_supports_the_cleaner():
    e = employment_for(SEED, 5, "grocery_clerk", 42, _BareRegistry(), {})
    assert e is not None and e.role == "cleaner" and e.assigned_object is None
    assert ROLES["cleaner"].required_caps == ()


def test_desk_workers_take_distinct_workstations_then_share_the_pool(office):
    desks = office.with_caps("station", "desk_work")
    assert len(desks) >= 2
    taken = {}
    assigned = []
    for cid in range(len(desks)):
        e = employment_for(SEED, cid, "office_worker", 4587, office, taken)
        assert e.role == "desk_worker"
        assigned.append(e.assigned_object)
    assert len(set(assigned)) == len(assigned) == len(desks)
    # once every desk is spoken for the role still applies: the worker selects a
    # free desk on the day instead of owning one.
    extra = employment_for(SEED, 900, "office_worker", 4587, office, taken)
    assert extra.role == "desk_worker" and extra.assigned_object is None


def test_a_cleaner_is_employed_anywhere_and_owns_no_station(shop, office, house):
    for reg, bid in ((shop, 6059), (office, 4587), (house, 999)):
        e = employment_for(SEED, 120, "cleaner", bid, reg, {})
        assert e.role == "cleaner" and e.assigned_object is None
        assert e.workplace_id == bid


def test_employment_to_dict_is_the_wire_shape(shop):
    e = employment_for(SEED, 129, "grocery_clerk", 6059, shop, {})
    d = e.to_dict()
    assert set(d) == {"citizen_id", "workplace_id", "role", "assigned_object", "occupation"}
    assert Employment(**d).to_dict() == d


def test_the_whole_assignment_pass_is_reproducible(shop):
    def run():
        taken = {}
        return [employment_for(SEED, cid, "grocery_clerk", 6059, shop, taken).to_dict()
                for cid in range(20)]
    a, b = run(), run()
    assert a == b
    assert len({r["assigned_object"] for r in a if r["assigned_object"]}) == \
        len(shop.with_caps("station", "transact"))


# --------------------------------------------------------------------------- #
# task durations
# --------------------------------------------------------------------------- #
def test_task_duration_is_deterministic_and_within_the_declared_bounds():
    for name, role in ROLES.items():
        for t in role.tasks:
            lo, hi = t.duration_s
            for cid in (7, 129, 4242):
                for instance in range(5):
                    d = task_duration(SEED, cid, t, instance)
                    assert d == task_duration(SEED, cid, t, instance), (name, t.task_id)
                    assert lo <= d <= hi, (name, t.task_id, d, t.duration_s)


def test_a_fixed_duration_task_has_no_spread():
    t = [x for x in ROLES["cashier"].tasks if x.task_id == "take_break"][0]
    assert t.duration_s[0] == t.duration_s[1]
    assert {task_duration(SEED, c, t, i) for c in range(5) for i in range(5)} == {t.duration_s[0]}


def test_durations_vary_between_citizens_and_instances():
    t = [x for x in ROLES["cashier"].tasks if x.task_id == "man_register"][0]
    per_citizen = {task_duration(SEED, cid, t, 0) for cid in range(40)}
    per_instance = {task_duration(SEED, 129, t, i) for i in range(40)}
    assert len(per_citizen) > 20, per_citizen
    assert len(per_instance) > 20, per_instance

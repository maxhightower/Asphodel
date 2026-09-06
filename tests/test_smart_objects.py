"""Smart objects, the registry and the room graph (ASPHODEL_SMART_OBJECTS_WORK_V1
§3, §4, §9) — pure unit tests, no world, no bundle.

Everything here is a function of ``(world_seed, building_id, footprint)`` through
:func:`asphodel.interiors.build_interior`, so a synthetic rectangular footprint is
enough to hold the layer to its contract:

* behaviour is keyed on **capabilities**, never on a name (S1 composition);
* object identity is stable across two independent builds (S1);
* every object lives in a real room, inside that room's rectangle (S3);
* a room's semantic **zone** comes from the interior room kind (S2);
* a route between two rooms is a chain of real doorway points (S9);
* a fresh registry costs zero persistent bytes (no state deltas) and its
  mutable state round-trips.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import interiors
from asphodel.smart import OBJECT_KINDS, RoomGraph, SmartObjectRegistry, zone_of_room_kind
from asphodel.smart.objects import (MAX_OBJECTS_PER_ROOM, MAX_PER_KIND_PER_ROOM, REACH_M,
                                    SmartObject)
from asphodel.smart.rooms import _ZONES

SEED = 7
FOOTPRINT = [[0, 0], [30, 0], [30, 20], [0, 20]]
BIG = [[0, 0], [200, 0], [200, 150], [0, 150]]
HINTS = ("retail", "office", "house")
BID = {"retail": 1234, "office": 1235, "house": 1236}


def _descriptor(hint, footprint=FOOTPRINT, bid=None):
    return interiors.build_interior(BID[hint] if bid is None else bid, SEED, footprint,
                                    arch_hint=hint)


@pytest.fixture(scope="module")
def built():
    """One registry + room graph per archetype (small footprint), plus a large
    footprint whose rooms are big enough to hit the per-room object caps."""
    out = {}
    for hint in HINTS:
        d = _descriptor(hint)
        out[hint] = {"desc": d, "reg": SmartObjectRegistry(d.building_id, d),
                     "graph": RoomGraph(d)}
    big = {}
    for hint in HINTS:
        for bid in (11, 12, 13):
            d = interiors.build_interior(bid, SEED, BIG, arch_hint=hint)
            big[(hint, bid)] = {"desc": d, "reg": SmartObjectRegistry(bid, d),
                                "graph": RoomGraph(d)}
    out["big"] = big
    return out


# --------------------------------------------------------------------------- #
# OBJECT_KINDS: composition, not names
# --------------------------------------------------------------------------- #
def test_a_checkout_is_an_exclusive_station_that_transacts():
    spec = OBJECT_KINDS["checkout"]
    assert {"station", "transact"} <= set(spec["caps"])
    assert spec["exclusive"] is True and spec["capacity"] == 1
    names = {a.name for a in spec["aff"]}
    assert {"occupy_station", "transact"} <= names
    assert "working" in spec["state"] and spec["state"]["working"] is True


def test_a_gondola_is_a_shared_shelf_with_capacity():
    spec = OBJECT_KINDS["gondola"]
    assert {"shelf", "stock", "browse"} <= set(spec["caps"])
    assert spec["exclusive"] is False and spec["capacity"] > 1
    assert {"restock", "browse"} <= {a.name for a in spec["aff"]}
    assert spec["state"]["stock"] > 0


def test_other_kinds_compose_the_same_station_capability():
    """A cubicle and a desk are stations too — same capability, different name."""
    for kind in ("cubicle", "desk", "teacher_desk", "workbench", "machine", "exam_table"):
        assert "station" in OBJECT_KINDS[kind]["caps"], kind
        assert OBJECT_KINDS[kind]["exclusive"] is True, kind
        assert OBJECT_KINDS[kind]["capacity"] == 1, kind
    for kind in ("cubicle", "desk", "teacher_desk"):
        assert "desk_work" in OBJECT_KINDS[kind]["caps"], kind


def test_every_kind_spec_is_internally_consistent():
    for kind, spec in OBJECT_KINDS.items():
        assert spec["caps"], kind
        assert isinstance(spec["capacity"], int) and spec["capacity"] >= 1, kind
        if spec["exclusive"]:
            # an exclusive object is whole-object: one holder, never a pool
            assert spec["capacity"] == 1, kind
        assert len({a.name for a in spec["aff"]}) == len(spec["aff"]), kind
        for a in spec["aff"]:
            assert a.duration_s > 0, (kind, a.name)
            for key, _value in a.effects:
                assert key in spec["state"], (kind, a.name, key)


def test_an_affordance_that_promises_clean_touches_the_dirty_flag():
    for kind, spec in OBJECT_KINDS.items():
        for a in spec["aff"]:
            if a.name == "clean":
                assert ("dirty", False) in a.effects, kind
                assert spec["state"].get("dirty") is False, kind


# --------------------------------------------------------------------------- #
# registry: identity (S1), rooms (S3), capabilities
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("hint", HINTS)
def test_the_registry_is_not_empty_for_any_archetype(built, hint):
    reg = built[hint]["reg"]
    assert len(reg) > 0
    assert len(reg.objects) == len(reg)
    assert sum(len(v) for v in reg.by_room.values()) == len(reg)


@pytest.mark.parametrize("hint", HINTS)
def test_object_ids_are_stable_across_two_independent_builds(built, hint):
    """S1: identity is a pure function of (seed, building, gen version)."""
    d2 = _descriptor(hint)
    reg2 = SmartObjectRegistry(d2.building_id, d2)
    a = {o.object_id: (o.kind, o.room_id, round(o.x, 6), round(o.y, 6), round(o.facing, 6),
                       sorted(o.caps), o.exclusive, o.capacity, o.source, o.source_id)
         for o in built[hint]["reg"].objects.values()}
    b = {o.object_id: (o.kind, o.room_id, round(o.x, 6), round(o.y, 6), round(o.facing, 6),
                       sorted(o.caps), o.exclusive, o.capacity, o.source, o.source_id)
         for o in reg2.objects.values()}
    assert a == b
    assert a, "an empty registry proves nothing"


@pytest.mark.parametrize("hint", HINTS)
def test_object_ids_carry_the_building_and_are_unique(built, hint):
    reg = built[hint]["reg"]
    bid = built[hint]["desc"].building_id
    for oid, o in reg.objects.items():
        assert oid == o.object_id
        assert oid.startswith(f"so:{bid}:"), oid
        assert o.building_id == bid
    assert len(set(reg.objects)) == len(reg.objects)


@pytest.mark.parametrize("hint", HINTS)
def test_every_object_sits_in_a_real_room_rectangle(built, hint):
    """S3: an object's room_id is a room of the descriptor and its pose is
    inside that room's world-metre rectangle."""
    d, reg = built[hint]["desc"], built[hint]["reg"]
    rooms = {r.room_id: r for r in d.rooms}
    for o in reg.objects.values():
        assert o.room_id in rooms, (o.object_id, o.room_id)
        r = rooms[o.room_id]
        assert r.x0 - 1e-6 <= o.x <= r.x1 + 1e-6, (o.object_id, o.x, r.x0, r.x1)
        assert r.y0 - 1e-6 <= o.y <= r.y1 + 1e-6, (o.object_id, o.y, r.y0, r.y1)
        assert o.object_id in reg.by_room[o.room_id]


def test_every_object_of_every_archetype_and_size_sits_in_its_room(built):
    n = 0
    for (hint, bid), rec in built["big"].items():
        rooms = {r.room_id: r for r in rec["desc"].rooms}
        for o in rec["reg"].objects.values():
            r = rooms[o.room_id]
            assert r.x0 - 1e-6 <= o.x <= r.x1 + 1e-6 and r.y0 - 1e-6 <= o.y <= r.y1 + 1e-6, \
                (hint, bid, o.object_id)
            n += 1
    assert n > 500, n


@pytest.mark.parametrize("hint", HINTS)
def test_capabilities_and_capacity_come_from_the_kind_table(built, hint):
    for o in built[hint]["reg"].objects.values():
        spec = OBJECT_KINDS.get(o.kind)
        if spec is None:
            # an undecorated presentation piece: a prop with no affordances
            assert o.caps == frozenset({"prop"}) and o.affordances == ()
            assert o.state == {} and o.capacity == 1 and o.exclusive is True
            continue
        assert o.caps == frozenset(spec["caps"])
        assert o.exclusive is bool(spec["exclusive"])
        assert o.capacity == int(spec["capacity"])
        assert [a.name for a in o.affordances] == [a.name for a in spec["aff"]]
        assert o.state == dict(spec["state"])
        assert o.state is not spec["state"], "objects must not share the template dict"


def test_a_retail_interior_knows_its_registers_and_shelves(built):
    reg = built["retail"]["reg"]
    stations = reg.with_caps("station", "transact")
    shelves = reg.with_caps("shelf")
    assert stations, "a retail interior with no till has nothing to work at"
    assert shelves
    assert all(o.has("station") and o.has("transact") for o in stations)
    assert [o.object_id for o in stations] == sorted(o.object_id for o in stations)
    assert all(o.affordance("transact") is not None for o in stations)
    assert reg.with_affordance("occupy_station")


def test_an_office_interior_knows_its_workstations(built):
    reg = built["office"]["reg"]
    desks = reg.with_caps("station", "desk_work")
    assert desks
    assert not reg.with_caps("station", "transact"), "an office is not a shop"
    assert all(o.affordance("desk_work") is not None for o in desks)


def test_a_house_interior_offers_non_work_affordances(built):
    reg = built["house"]["reg"]
    assert reg.with_affordance("sit") or reg.with_affordance("eat")
    assert not reg.with_caps("station", "transact")


def test_has_and_available_and_affordance_lookup(built):
    reg = built["retail"]["reg"]
    o = reg.with_caps("station", "transact")[0]
    assert o.has("station") and o.has("station", "transact") and not o.has("bed")
    assert o.affordance("transact") is not None and o.affordance("nope") is None
    assert o.available() is True
    o.state["working"] = False
    assert o.available() is False
    o.state["working"] = True
    o.state["closed"] = True
    assert o.available() is False
    del o.state["closed"]
    assert o.available() is True


def test_the_interaction_point_is_reach_metres_in_front_of_the_object(built):
    for hint in HINTS:
        for o in built[hint]["reg"].objects.values():
            ux, uy = o.use_xy
            assert math.isclose(math.hypot(ux - o.x, uy - o.y), REACH_M, rel_tol=1e-9)
            assert math.isclose(ux, o.x + math.cos(o.facing) * REACH_M, rel_tol=1e-9)
            assert math.isclose(uy, o.y + math.sin(o.facing) * REACH_M, rel_tol=1e-9)


def test_in_room_and_counts_agree_with_the_object_table(built):
    reg = built["retail"]["reg"]
    total = 0
    for rid in reg.by_room:
        objs = reg.in_room(rid)
        total += len(objs)
        assert all(o.room_id == rid for o in objs)
    assert total == len(reg)
    counts = reg.counts()
    assert sum(counts.values()) == len(reg)
    for kind, n in counts.items():
        assert n == sum(1 for o in reg.objects.values() if o.kind == kind)


def test_to_row_is_a_json_shaped_projection(built):
    o = built["retail"]["reg"].with_caps("station", "transact")[0]
    row = o.to_row()
    assert row["object_id"] == o.object_id and row["kind"] == o.kind
    assert row["caps"] == sorted(o.caps) and row["exclusive"] is o.exclusive
    assert row["affordances"] == [a.name for a in o.affordances]
    assert row["state"] == o.state and row["state"] is not o.state
    assert row["building_id"] == o.building_id and row["room_id"] == o.room_id


# --------------------------------------------------------------------------- #
# per-room bounds
# --------------------------------------------------------------------------- #
def test_the_decor_derived_objects_of_a_room_are_bounded(built):
    """The interaction layer keeps a bounded, deterministic subset of a room's
    presentation furniture (a huge hall is not thousands of smart objects)."""
    seen_at_cap = 0
    for (hint, bid), rec in built["big"].items():
        per_room, per_kind = {}, {}
        for o in rec["reg"].objects.values():
            if o.source != "decor":
                continue
            per_room[o.room_id] = per_room.get(o.room_id, 0) + 1
            per_kind[(o.room_id, o.kind)] = per_kind.get((o.room_id, o.kind), 0) + 1
        assert not per_room or max(per_room.values()) <= MAX_OBJECTS_PER_ROOM, (hint, bid)
        assert not per_kind or max(per_kind.values()) <= MAX_PER_KIND_PER_ROOM, (hint, bid)
        if per_room and max(per_room.values()) == MAX_OBJECTS_PER_ROOM:
            seen_at_cap += 1
    assert seen_at_cap, "no room reached the cap: the bound was never exercised"


def test_a_rooms_object_count_never_exceeds_the_cap_plus_its_fixtures(built):
    """Container fixtures are authoritative (1:1 with real containers) and are
    never dropped, so a room holds at most cap + its fixture count."""
    for (hint, bid), rec in built["big"].items():
        fixtures = {}
        for f in rec["desc"].fixtures:
            fixtures[f.room_id] = fixtures.get(f.room_id, 0) + 1
        for rid, oids in rec["reg"].by_room.items():
            assert len(oids) <= MAX_OBJECTS_PER_ROOM + fixtures.get(rid, 0), (hint, bid, rid)


def test_dropping_a_capped_decor_piece_does_not_shift_the_ids_that_follow(built):
    """Ids are the generation index, so the same piece keeps the same id whether
    or not its neighbours were kept."""
    for (hint, bid), rec in built["big"].items():
        d2 = interiors.build_interior(bid, SEED, BIG, arch_hint=hint)
        reg2 = SmartObjectRegistry(bid, d2)
        assert sorted(reg2.objects) == sorted(rec["reg"].objects)
        ks = sorted(int(oid.split(":")[2]) for oid in reg2.objects)
        assert len(set(ks)) == len(ks)


# --------------------------------------------------------------------------- #
# mutable state: deltas only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("hint", HINTS)
def test_a_fresh_registry_has_no_state_deltas(hint):
    d = _descriptor(hint)
    assert SmartObjectRegistry(d.building_id, d).state_deltas() == {}


def test_state_deltas_round_trip_through_apply(built):
    d = _descriptor("retail")
    reg = SmartObjectRegistry(d.building_id, d)
    station = reg.with_caps("station", "transact")[0]
    shelf = reg.with_caps("shelf", "stock")[0]
    station.state["working"] = False
    station.state["served"] = 12
    shelf.state["stock"] = 3
    deltas = reg.state_deltas()
    assert set(deltas) == {station.object_id, shelf.object_id}
    assert deltas[station.object_id]["served"] == 12

    fresh = SmartObjectRegistry(d.building_id, _descriptor("retail"))
    assert fresh.state_deltas() == {}
    fresh.apply_state_deltas(deltas)
    assert fresh.state_deltas() == deltas
    assert fresh.get(station.object_id).state == station.state
    assert fresh.get(shelf.object_id).state == shelf.state
    assert fresh.get(station.object_id).available() is False


def test_applying_a_delta_for_an_unknown_object_is_ignored():
    d = _descriptor("retail")
    reg = SmartObjectRegistry(d.building_id, d)
    reg.apply_state_deltas({"so:999999:0": {"working": False}})
    assert reg.state_deltas() == {}
    assert reg.get("so:999999:0") is None


def test_restoring_the_generated_value_clears_the_delta():
    d = _descriptor("retail")
    reg = SmartObjectRegistry(d.building_id, d)
    o = reg.with_caps("station", "transact")[0]
    o.state["working"] = False
    assert o.object_id in reg.state_deltas()
    o.state["working"] = True
    assert reg.state_deltas() == {}


# --------------------------------------------------------------------------- #
# RoomGraph: zones (S2) and doorway routing (S9)
# --------------------------------------------------------------------------- #
def test_zone_of_room_kind_is_the_published_table():
    assert zone_of_room_kind("shop_floor") == "sales_floor"
    assert zone_of_room_kind("back_room") == "employee_area"
    assert zone_of_room_kind("storeroom") == "stock_room"
    assert zone_of_room_kind("open_office") == "workspace"
    assert zone_of_room_kind("bedroom") == "bedroom"
    assert zone_of_room_kind("no_such_kind") == "room"
    for kind, zone in _ZONES.items():
        assert zone_of_room_kind(kind) == zone


@pytest.mark.parametrize("hint", HINTS)
def test_every_room_has_a_zone(built, hint):
    d, g = built[hint]["desc"], built[hint]["graph"]
    assert set(g.rooms) == {r.room_id for r in d.rooms}
    for r in d.rooms:
        assert g.zones[r.room_id] == zone_of_room_kind(r.kind)
        assert g.zone(r.room_id) == g.zones[r.room_id]
    assert g.zone(-99) == "room"


def test_retail_and_office_rooms_get_the_zones_their_roles_look_for(built):
    zones = set(built["retail"]["graph"].zones.values())
    assert "sales_floor" in zones
    assert "workspace" in set(built["office"]["graph"].zones.values())
    assert {"living_room", "kitchen"} & set(built["house"]["graph"].zones.values())


def test_rooms_of_zone_is_sorted_and_partitions_the_rooms(built):
    for (hint, bid), rec in built["big"].items():
        g = rec["graph"]
        seen = []
        for zone in sorted(set(g.zones.values())):
            rooms = g.rooms_of_zone(zone)
            assert rooms == sorted(rooms)
            assert all(g.zone(r) == zone for r in rooms)
            seen.extend(rooms)
        assert sorted(seen) == sorted(g.rooms)
        assert g.rooms_of_zone("not_a_zone") == []


def test_room_of_finds_the_room_containing_a_point(built):
    for (hint, bid), rec in built["big"].items():
        g = rec["graph"]
        for rid, r in g.rooms.items():
            assert g.room_of(r.center()) == rid
            assert g.room_of((r.x0 + 0.25, r.y0 + 0.25)) == rid
            assert g.room_of((r.x1 - 0.25, r.y1 - 0.25)) == rid
        # a point far outside still resolves to the nearest room, never -1
        assert g.room_of((99999.0, 99999.0)) in g.rooms


def test_the_entrance_is_a_real_point_of_the_entrance_room(built):
    for (hint, bid), rec in built["big"].items():
        d, g = rec["desc"], rec["graph"]
        e = d.entrances[0]
        assert g.entrance_room == e.room_id
        assert g.entrance_xy == (e.x, e.y)
        assert g.inside_xy != g.entrance_xy
        assert g.room_of(g.inside_xy) in g.rooms


def test_a_route_inside_one_room_is_just_the_target(built):
    g = built["retail"]["graph"]
    r = g.rooms[sorted(g.rooms)[0]]
    a = (r.x0 + 1.0, r.y0 + 1.0)
    b = (r.x1 - 1.0, r.y1 - 1.0)
    assert g.route(a, b) == [b]


def test_a_route_between_rooms_passes_through_doorway_points_and_ends_at_the_target(built):
    checked = 0
    for (hint, bid), rec in built["big"].items():
        d, g = rec["desc"], rec["graph"]
        if len(g.rooms) < 2:
            continue
        doors = {(round(dw.x, 6), round(dw.y, 6)) for dw in d.doorways}
        rids = sorted(g.rooms)
        for a_id in rids:
            for b_id in rids:
                if a_id == b_id:
                    continue
                a, b = g.rooms[a_id].center(), g.rooms[b_id].center()
                path = g.route(a, b)
                assert path[-1] == b
                assert len(path) >= 2, (hint, bid, a_id, b_id)
                for p in path[:-1]:
                    assert (round(p[0], 6), round(p[1], 6)) in doors, (hint, bid, p)
                # each doorway hop actually changes room
                rooms_walked = [g.room_of(p) for p in path]
                assert rooms_walked[-1] == b_id
                checked += 1
    assert checked, "no multi-room interior was generated to route through"


def test_routing_is_deterministic_and_symmetric_in_length(built):
    for (hint, bid), rec in built["big"].items():
        g = rec["graph"]
        rids = sorted(g.rooms)
        if len(rids) < 2:
            continue
        a, b = g.rooms[rids[0]].center(), g.rooms[rids[-1]].center()
        assert g.route(a, b) == g.route(a, b)
        assert len(g.route(a, b)) == len(g.route(b, a))


def test_the_doorway_graph_is_symmetric_and_connected(built):
    for (hint, bid), rec in built["big"].items():
        g = rec["graph"]
        for rid, nbrs in g.adj.items():
            for n, xy in nbrs:
                assert rid in [m for m, _ in g.adj[n]], (rid, n)
                assert len(xy) == 2
        # BFS from the entrance room reaches every room
        seen, stack = {g.entrance_room}, [g.entrance_room]
        while stack:
            cur = stack.pop()
            for n, _ in g.adj.get(cur, []):
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        assert seen == set(g.rooms), (hint, bid, sorted(set(g.rooms) - seen))


def test_rows_describe_every_room_for_the_wire(built):
    g = built["office"]["graph"]
    rows = g.rows()
    assert [r["room_id"] for r in rows] == sorted(g.rooms)
    for row in rows:
        r = g.rooms[row["room_id"]]
        assert row["zone"] == g.zone(row["room_id"]) and row["kind"] == r.kind
        assert row["x0"] <= row["x1"] and row["y0"] <= row["y1"]
        assert row["doors"] == sorted(n for n, _ in g.adj[row["room_id"]])

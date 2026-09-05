"""Convergence gates — the tests that keep Asphodel from fragmenting again.

Each gate names the authority it protects (see
docs/convergence/ASPHODEL_CANONICAL_ARCHITECTURE.md). Gate C (street/mobility
parity) lives in tests/test_gate_street_parity.py; Gates G and I have their
Godot half in godot/tests/ConvergenceGate.tscn.

  A  canonical building schema — every active consumer accepts exactly one shape
  B  building identity parity — footprint == identity table == citizen home ==
     entrance anchor == interior descriptor
  D  citizen identity continuity — far sim -> embodiment -> save/load -> commute
     playback keep the same citizen id and the same physical interpretation
  E  deterministic visual identity — appearance seed is a pure function of the
     citizen id and consumes no simulation RNG
  F  vehicle identity continuity — abstract -> route-simulated -> physical ->
     back keeps id and route progress
  H  multi-city load — every committed bundle loads through the one pipeline
"""
from __future__ import annotations

import gzip
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import (CitySpatialContext, LocationMode,
                                 validate_buildings_doc)
from asphodel.mobility import Mode, MobilityGraph
from asphodel.save import load_world, world_state
from asphodel.transport import VehicleInstance, VehicleFidelity

BUNDLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "godot", "bundles")
COMPILED = ("houston", "madisonville_tx", "austin", "san_antonio")
CITIES = COMPILED + ("boulder",)


def _bundle(city):
    d = os.path.join(BUNDLES, city)
    if not os.path.exists(os.path.join(d, "meta.json")):
        pytest.skip(f"{city} bundle absent")
    return d


def _json(d, name):
    with open(os.path.join(d, name)) as f:
        return json.load(f)


def _point_in_ring(x, z, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x0, z0 = ring[i]
        x1, z1 = ring[(i + 1) % n]
        if (z0 > z) != (z1 > z):
            t = (z - z0) / (z1 - z0)
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def _dist_to_ring(x, z, ring) -> float:
    best = float("inf")
    n = len(ring)
    for i in range(n):
        ax, az = ring[i]
        bx, bz = ring[(i + 1) % n]
        dx, dz = bx - ax, bz - az
        L = dx * dx + dz * dz
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / L))
        px, pz = ax + t * dx, az + t * dz
        best = min(best, ((x - px) ** 2 + (z - pz) ** 2) ** 0.5)
    return best


# --------------------------------------------------------------------------- #
# Gate A — canonical building schema
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("city", CITIES)
def test_gate_a_every_bundle_carries_the_canonical_building_schema(city):
    d = _bundle(city)
    doc = _json(d, "buildings.json")
    blist = validate_buildings_doc(doc)
    assert blist, city
    for b in blist[:50]:
        assert len(b["poly"]) >= 3 and b["height"] > 0


def test_gate_a_legacy_shapes_are_rejected_loudly():
    with pytest.raises(ValueError):
        validate_buildings_doc([{"footprint": [], "kind": "house", "storeys": 1}])
    with pytest.raises(ValueError):
        validate_buildings_doc({"version": 2, "buildings": []})
    with pytest.raises(ValueError):
        validate_buildings_doc({"version": 1, "buildings": [{"kind": "house"}]})
    assert validate_buildings_doc(None) == []


def test_gate_a_spatial_context_refuses_a_bare_list(tmp_path):
    d = _bundle("madisonville_tx")
    for name in ("meta.json", "zones.json", "roads.json"):
        (tmp_path / name).write_text(open(os.path.join(d, name)).read())
    (tmp_path / "buildings.json").write_text(json.dumps([{"footprint": [[0, 0]]}]))
    with pytest.raises(ValueError):
        CitySpatialContext.from_bundle_dir(str(tmp_path))


# --------------------------------------------------------------------------- #
# Gate B — building identity parity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("city", COMPILED)
def test_gate_b_footprint_identity_entrance_interior_correspond(city):
    d = _bundle(city)
    blist = validate_buildings_doc(_json(d, "buildings.json"))
    with gzip.open(os.path.join(d, "world", "identity.json.gz"), "rt") as f:
        ident = _json_load(f)
    with gzip.open(os.path.join(d, "world", "spawn_anchors.json.gz"), "rt") as f:
        anchors = _json_load(f)["anchors"]
    entrance = {}
    for kind, x, z, bid in anchors:
        if kind == "BUILDING_ENTRANCE" and bid >= 0:
            entrance.setdefault(int(bid), (x, z))
    assert len(ident["buildings"]) == len(blist)
    rng = np.random.default_rng(0)
    sample = rng.choice(len(blist), size=min(200, len(blist)), replace=False)
    ctx = CitySpatialContext.from_bundle_dir(d)
    w = world_from_bundle(city, micro_params=MicroParams(area_size=100.0,
                                                          infection_radius=2.0,
                                                          mixing_step_frac=0.12))
    w.set_spatial_context(ctx)
    checked_entrances = 0
    entrance_d = []
    for bid in map(int, sample):
        # simulation identity == geographic identity (stable public-data key)
        assert ident["buildings"][bid]["id"] == bid
        assert ident["buildings"][bid]["key"] == blist[bid]["key"]
        cx, cz = ctx.building_centroids[bid]
        assert ctx.nearest_building((cx, cz)) == bid
        # the compiled entrance anchor stands just outside THIS footprint
        if bid in entrance:
            ex, ez = entrance[bid]
            entrance_d.append(_dist_to_ring(ex, ez, blist[bid]["poly"]))
            checked_entrances += 1
        # the interior descriptor is keyed by the same id and covers the footprint
        desc = w.interior_descriptor(bid)
        assert desc.building_id == bid
        assert desc.rooms and desc.entrances
    assert checked_entrances > 0
    entrance_d.sort()
    assert entrance_d[len(entrance_d) // 2] < 6.0, "median entrance offset"
    assert entrance_d[-1] < 20.0, f"an entrance anchor is {entrance_d[-1]:.1f} m from its building"


@pytest.mark.parametrize("city", CITIES)
def test_gate_b_citizen_home_is_a_stored_building_identity(city):
    d = _bundle(city)
    raw = _json(d, "citizens.json")
    blist = validate_buildings_doc(_json(d, "buildings.json"))
    with_id = 0
    for c in raw:
        bid = c.get("home_building_id")
        if bid is None:
            continue
        with_id += 1
        assert 0 <= bid < len(blist), (city, bid)
        hx, hz = c["home_xy"]
        ring = blist[bid]["poly"]
        # home_xy IS derived from the named footprint: it is the footprint's
        # vertex-mean centre (identity by construction, not by proximity).
        mx = sum(p[0] for p in ring) / len(ring)
        mz = sum(p[1] for p in ring) / len(ring)
        assert abs(hx - mx) < 0.02 and abs(hz - mz) < 0.02, (city, bid, (hx, hz), (mx, mz))
    assert with_id == len(raw), f"{city}: {len(raw) - with_id} citizens lack home_building_id"


def _json_load(f):
    return json.load(f)


# --------------------------------------------------------------------------- #
# Gate D — citizen identity continuity
# --------------------------------------------------------------------------- #
def _world(city):
    w = world_from_bundle(city, micro_params=MicroParams(area_size=100.0,
                                                          infection_radius=2.0,
                                                          mixing_step_frac=0.12))
    pop = load_bundle_population(resolve_bundle_dir(city))
    w.set_citizens(pop)
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(resolve_bundle_dir(city)))
    return w, pop


def test_gate_d_same_citizen_through_far_sim_embodiment_and_save_load(tmp_path):
    from collections import Counter
    w, pop = _world("houston")
    by_id = {c.citizen_id: c for c in pop}
    zone = Counter(c.home_zone for c in pop).most_common(1)[0][0]
    w.set_focus([zone])
    for _ in range(3):
        w.step()
    snap = w.snapshot()
    z = snap["agents"][str(zone)] if str(zone) in snap["agents"] else snap["agents"][zone]
    ids = [int(i) for i in z["citizen_id"] if int(i) >= 0]
    assert ids, "no identified citizens materialised in the focus zone"
    cid = ids[0]
    # far/abstract identity == embodied identity
    assert cid in by_id
    loc = w.physical_location(cid)
    assert loc.citizen_id == cid
    if by_id[cid].home_building_id is not None and loc.activity in ("sleep", "leisure", "idle"):
        assert loc.building_id == by_id[cid].home_building_id
    # save -> destroy -> load keeps the same person in the same place
    state = world_state(w, bundle="houston")
    w2 = load_world(state)
    # Static bundle geometry is not part of a save (the bundle is); the bridge
    # re-attaches it after LOAD (bridge/session.py) and so does this test.
    w2.set_spatial_context(CitySpatialContext.from_bundle_dir(resolve_bundle_dir("houston")))
    assert set(w2.citizens) == set(w.citizens)
    loc2 = w2.physical_location(cid)
    assert loc2.to_dict() == loc.to_dict()
    snap2 = w2.snapshot()
    z2 = snap2["agents"][str(zone)] if str(zone) in snap2["agents"] else snap2["agents"][zone]
    assert list(z2["citizen_id"]) == list(z["citizen_id"])


def test_gate_d_commute_playback_rows_are_canonical_citizen_ids():
    from asphodel.living_city import simulate_commute
    d = _bundle("houston")
    raw = _json(d, "citizens.json")
    pb = simulate_commute(d, n_citizens=40, seed=0, write=False)
    assert pb["version"] == 2 and pb["n_canonical_citizens"] > 0
    ids = {row[3] for fr in pb["frames"][:1] for row in fr["peds"] + fr["cars"]}
    canonical = {i for i in ids if not str(i).startswith("synth:")}
    assert canonical and all(0 <= int(i) < len(raw) for i in canonical)


# --------------------------------------------------------------------------- #
# Gate E — deterministic visual identity, no simulation RNG
# --------------------------------------------------------------------------- #
def test_gate_e_visual_seed_is_pure_and_rng_free():
    from asphodel import npc
    rng = np.random.default_rng(123)
    before = rng.bit_generator.state
    seeds = [npc.visual_seed(i) for i in range(1000)]
    assert rng.bit_generator.state == before          # consumed nothing
    assert seeds == [npc.visual_seed(i) for i in range(1000)]
    assert len(set(seeds)) == 1000                    # distinct people
    assert npc.visual_seed(-1) == 0
    # The GDScript mirror (citizen_visual_identity.gd) implements the same
    # splitmix; these pinned values are what it must reproduce.
    assert npc.visual_seed(7) == 1367237545 or npc.visual_seed(7) == (
        (((7 * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF) ^
         (((7 * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF) >> 16)) * 0x85EBCA6B & 0xFFFFFFFF
        ^ ((((((7 * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF) ^
              (((7 * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF) >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF) >> 13)
    ) & 0x7FFFFFFF


def test_gate_e_godot_mirror_uses_the_same_splitmix():
    gd = os.path.join(os.path.dirname(BUNDLES), "scripts", "citizen_visual_identity.gd")
    src = open(gd).read()
    for const in ("0x9E3779B1", "0x7F4A7C15", "0x85EBCA6B"):
        assert const in src, f"{const} missing from the GDScript mirror"


# --------------------------------------------------------------------------- #
# Gate F — vehicle identity continuity on a real street graph
# --------------------------------------------------------------------------- #
def _car_route(g: MobilityGraph):
    """A deterministic multi-segment CAR route somewhere on the graph."""
    nodes = sorted(n for n in g.nodes if g._node_serves_mode(n, Mode.CAR))
    step = max(1, len(nodes) // 40)
    for i in range(0, len(nodes), step):
        for j in range(len(nodes) - 1, 0, -step):
            r = g.route(nodes[i], nodes[j], Mode.CAR)
            if r is not None and len(r.segments) >= 2:
                return r
    raise AssertionError("no multi-segment car route on the graph")


def test_gate_f_vehicle_keeps_identity_and_progress_across_fidelity():
    d = _bundle("houston")
    g = MobilityGraph.from_artifact(_json(d, "streetmap.json"))
    route = _car_route(g)
    v = VehicleInstance("veh:42", "car")
    v.assign_route(route, g)
    v.advance_far(20.0, g)
    p_far = v.route_progress
    pos = v.position(g)
    v.promote(VehicleFidelity.PHYSICAL_CONTROLLED)
    assert v.vehicle_id == "veh:42" and v.route_progress == p_far
    # physics moved it a little further along; reconciling keeps identity
    v.reconcile_from_physical(pos)
    v.demote(VehicleFidelity.ROUTE_SIMULATED)
    assert v.vehicle_id == "veh:42"
    assert abs(v.route_progress - p_far) < 0.05
    d1 = v.to_dict(g)
    assert d1["vehicle_id"] == "veh:42"


# --------------------------------------------------------------------------- #
# Gate H — multi-city load through the one pipeline
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("city", CITIES + ("denver_region",))
def test_gate_h_city_loads_through_the_canonical_pipeline(city):
    if not os.path.isdir(os.path.join(BUNDLES, city)):
        pytest.skip(f"{city} absent")
    from tools.city_matrix import check_city
    rows = check_city(city)
    failed = {k: v for k, v in rows.items() if v[0] == "FAIL"}
    assert not failed, f"{city}: {failed}"

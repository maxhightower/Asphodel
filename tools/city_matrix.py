#!/usr/bin/env python3
"""Multi-city convergence matrix (Gate H, Python side).

Loads every representative bundle through the ONE canonical pipeline and prints
a capability matrix. Exit code 1 if any required capability fails for a city
that is expected to support it. The Godot half of the matrix is
``godot/tests/ConvergenceGate.tscn``.

    python tools/city_matrix.py            # all committed bundles
    python tools/city_matrix.py houston    # one city
"""
from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
BUNDLES = os.path.join(_ROOT, "godot", "bundles")

# Which capabilities each committed bundle is expected to have. A synthetic city
# has no compiled world/ stream (no Overture geometry) — that is recorded, not
# hidden. denver_region is a region-only proving ground (terrain + physics).
EXPECTED = {
    "houston":        {"compiled_world": True,  "city": True},
    "madisonville_tx": {"compiled_world": True,  "city": True},
    "austin":         {"compiled_world": True,  "city": True},
    "san_antonio":    {"compiled_world": True,  "city": True},
    "boulder":        {"compiled_world": False, "city": True},
    "denver_region":  {"compiled_world": False, "city": False},
}

CAPABILITIES = [
    "bundle_loads", "terrain_loads", "streetmap_loads", "roads_align",
    "buildings_load", "building_identity", "citizens_spawn",
    "vehicles_spawn", "collision_matrix", "world_starts",
]


def _load(bundle_dir, name):
    with open(os.path.join(bundle_dir, name)) as f:
        return json.load(f)


def _car_route(graph):
    """A deterministic multi-segment car route somewhere on the graph."""
    from asphodel.mobility import Mode
    nodes = sorted(n for n in graph.nodes if graph._node_serves_mode(n, Mode.CAR))
    step = max(1, len(nodes) // 40)
    for i in range(0, len(nodes), step):
        for j in range(len(nodes) - 1, 0, -step):
            r = graph.route(nodes[i], nodes[j], Mode.CAR)
            if r is not None and len(r.segments) >= 2:
                return r
    raise RuntimeError("no multi-segment car route on the graph")


def check_city(city: str) -> dict:
    """Return {capability: (status, detail)} with status PASS/FAIL/N/A."""
    from asphodel.bridge.worldfactory import world_from_bundle
    from asphodel.bundle_population import load_bundle_population
    from asphodel.embodiment import CitySpatialContext
    from asphodel.mobility import Mode, MobilityGraph
    from asphodel.physics import BODY_PROFILES

    d = os.path.join(BUNDLES, city)
    exp = EXPECTED.get(city, {"compiled_world": False, "city": True})
    out = {}

    def rec(cap, ok, detail=""):
        out[cap] = ("PASS" if ok else "FAIL", detail)

    def na(cap, detail=""):
        out[cap] = ("N/A", detail)

    # 1. bundle (macro tier products) + authoritative world
    if exp["city"]:
        try:
            meta = _load(d, "meta.json")
            zones = _load(d, "zones.json")
            _load(d, "timeline.json")
            rec("bundle_loads", True,
                f"{len(zones)} zones, source={meta.get('source', 'osm')}")
        except Exception as e:  # noqa: BLE001
            rec("bundle_loads", False, repr(e))
        try:
            t = time.time()
            w = world_from_bundle(city)
            w.step()
            rec("world_starts", True, f"World.step ok ({time.time() - t:.2f}s)")
        except Exception as e:  # noqa: BLE001
            rec("world_starts", False, repr(e))
            w = None
    else:
        na("bundle_loads", "region-only bundle")
        na("world_starts", "region-only bundle")
        w = None

    # 2. terrain
    try:
        r = _load(d, "region.json")
        assert r["version"] == 2, f"region version {r['version']!r}"
        hm = r["heightmap"]
        assert len(hm["heights"]) == hm["shape"][0]
        rec("terrain_loads", True,
            f"v2 {r['archetype']} relief={r['terrain_stats']['relief_span']:.0f}m "
            f"datum={r['city_plateau']['datum_elevation']}")
    except Exception as e:  # noqa: BLE001
        rec("terrain_loads", False, repr(e))

    # 3. street graph
    graph = None
    if not exp["city"]:
        na("streetmap_loads", "region-only bundle")
    else:
        try:
            art = _load(d, "streetmap.json")
            graph = MobilityGraph.from_artifact(art)
            st = graph.stats()
            r1 = _car_route(graph)
            rec("streetmap_loads", True,
                f"v{art.get('version')} {st['segments']} segs / {st['nodes']} nodes, "
                f"source={art.get('source', '?')}, car route={r1.distance:.0f}m")
        except Exception as e:  # noqa: BLE001
            rec("streetmap_loads", False, repr(e))

    # 4. roads align with the rendered world (compiled cities only)
    if exp["compiled_world"] and graph is not None:
        try:
            from tests.test_gate_street_parity import parity_fractions
            a, b = parity_fractions(d, graph, n=120)
            rec("roads_align", a >= 0.99 and b >= 0.99,
                f"streetmap->chunks {a:.3f}, chunks->streetmap {b:.3f}")
        except ImportError:
            na("roads_align", "parity test module absent")
        except Exception as e:  # noqa: BLE001
            rec("roads_align", False, repr(e))
    elif exp["compiled_world"]:
        rec("roads_align", False, "no graph")
    else:
        na("roads_align", "no compiled world/ (synthetic or region-only)")

    # 5. buildings + identity
    if exp["city"]:
        try:
            b = _load(d, "buildings.json")
            assert b["version"] == 1 and b["buildings"], "bad buildings.json"
            ctx = CitySpatialContext.from_bundle_dir(d)
            rec("buildings_load", True,
                f"{len(b['buildings'])} footprints, source={b.get('source')}")
            if exp["compiled_world"]:
                import gzip
                with gzip.open(os.path.join(d, "world", "identity.json.gz"), "rt") as f:
                    ident = json.load(f)
                ok = all(ident["buildings"][i]["id"] == i and
                         ident["buildings"][i]["key"] == b["buildings"][i]["key"]
                         for i in range(0, len(b["buildings"]),
                                        max(1, len(b["buildings"]) // 200)))
                rec("building_identity", ok,
                    "buildings.json index == world/identity id/key")
            else:
                na("building_identity", "no compiled identity table (synthetic)")
        except Exception as e:  # noqa: BLE001
            rec("buildings_load", False, repr(e))
            rec("building_identity", False, repr(e))
            ctx = None
    else:
        na("buildings_load", "region-only bundle")
        na("building_identity", "region-only bundle")
        ctx = None

    # 6. citizens: canonical population registers and embodies
    if exp["city"] and w is not None:
        try:
            pop = load_bundle_population(d)
            w.set_citizens(pop)
            if ctx is not None:
                w.set_spatial_context(ctx)
            loc = w.physical_location(pop[0].citizen_id)
            rec("citizens_spawn", loc is not None and len(pop) > 0,
                f"{len(pop)} citizens, citizen 0 at ({loc.x:.0f},{loc.y:.0f}) "
                f"mode={loc.mode} bid={loc.building_id}")
        except Exception as e:  # noqa: BLE001
            rec("citizens_spawn", False, repr(e))
    else:
        na("citizens_spawn", "region-only bundle")

    # 7. vehicles: identity-carrying VehicleInstances route on the street graph
    if graph is not None and exp["city"]:
        try:
            from asphodel.transport import VehicleInstance
            route = _car_route(graph)
            v = VehicleInstance("veh:matrix", "car")
            v.assign_route(route, graph)
            v.advance_far(30.0, graph)
            rec("vehicles_spawn", route is not None and v.route_progress > 0.0,
                f"progress={v.route_progress:.3f} over {route.distance:.0f}m")
        except Exception as e:  # noqa: BLE001
            rec("vehicles_spawn", False, repr(e))
    else:
        na("vehicles_spawn", "no street graph / region-only")

    # 8. collision matrix
    try:
        ph = _load(d, "physics.json")
        ok = set(ph["body_profiles"]) == set(BODY_PROFILES) and \
            all(ph["body_profiles"][k]["layer"] == BODY_PROFILES[k].layer
                for k in BODY_PROFILES)
        rec("collision_matrix", ok, f"{len(ph['collision_matrix'])} pairs")
    except Exception as e:  # noqa: BLE001
        rec("collision_matrix", False, repr(e))
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cities = argv or [c for c in EXPECTED if os.path.isdir(os.path.join(BUNDLES, c))]
    rows = {c: check_city(c) for c in cities}
    w = max(len(c) for c in CAPABILITIES) + 2
    print("capability".ljust(w) + "".join(c.ljust(16) for c in cities))
    fail = 0
    for cap in CAPABILITIES:
        line = cap.ljust(w)
        for c in cities:
            st, _ = rows[c].get(cap, ("?", ""))
            line += st.ljust(16)
            if st == "FAIL":
                fail += 1
        print(line)
    print()
    for c in cities:
        for cap in CAPABILITIES:
            st, detail = rows[c].get(cap, ("?", ""))
            if detail:
                print(f"  {c:16s} {cap:18s} {st:5s} {detail}")
    print(f"\nCITY_MATRIX: {'PASS' if fail == 0 else 'FAIL'} ({fail} failing cells)")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

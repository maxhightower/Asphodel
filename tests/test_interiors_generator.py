"""Walk-in interiors — Package 2 (deterministic generator) certification.

Geometry correctness: deterministic hash, valid doorways, room reachability,
furniture within bounds, fixtures->containers, footprint tolerance.
"""

from __future__ import annotations

import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import interiors, items
from asphodel.interiors import build_interior
from asphodel.embodiment import CitySpatialContext
from asphodel.bridge.worldfactory import resolve_bundle_dir


BUNDLE = "houston"


def _ctx():
    return CitySpatialContext.from_bundle_dir(resolve_bundle_dir(BUNDLE))


def _desc(ctx, bid, seed=1):
    return build_interior(bid, seed, ctx.building_poly(bid),
                          height=ctx.building_height(bid),
                          road_xy=ctx.nearest_road_xy(ctx.building_centroids[bid]))


# a representative sample of buildings across archetypes
def _sample(ctx, n=60):
    return [_desc(ctx, b) for b in range(0, min(n * 4, len(ctx.building_polys)), 4)][:n]


def test_deterministic_hash_over_sample():
    ctx = _ctx()
    for bid in range(0, 120, 4):
        a = _desc(ctx, bid).geometry_hash()
        b = _desc(ctx, bid).geometry_hash()
        assert a == b, f"building {bid} nondeterministic"


def test_rooms_reachable_from_entrance():
    ctx = _ctx()
    for d in _sample(ctx):
        # build adjacency from doorways + entrances
        adj = {r.room_id: set() for r in d.rooms}
        for door in d.doorways:
            if door.room_a in adj and door.room_b in adj:
                adj[door.room_a].add(door.room_b)
                adj[door.room_b].add(door.room_a)
        start = d.entrances[0].room_id
        seen = {start}
        q = deque([start])
        while q:
            cur = q.popleft()
            for nb in adj.get(cur, ()):
                if nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        assert seen == {r.room_id for r in d.rooms}, \
            f"building {d.building_id}: unreachable rooms {set(r.room_id for r in d.rooms) - seen}"


def test_furniture_within_room_bounds():
    ctx = _ctx()
    for d in _sample(ctx):
        rooms = {r.room_id: r for r in d.rooms}
        for f in d.fixtures:
            r = rooms[f.room_id]
            assert r.x0 - 1e-6 <= f.x <= r.x1 + 1e-6, f"fixture x out of room {d.building_id}"
            assert r.y0 - 1e-6 <= f.y <= r.y1 + 1e-6, f"fixture y out of room {d.building_id}"


def test_fixtures_map_to_valid_containers():
    ctx = _ctx()
    for d in _sample(ctx):
        n = items.n_containers(1, d.building_id)
        assert len(d.fixtures) == n
        cidx = sorted(f.container_index for f in d.fixtures)
        assert cidx == list(range(n))            # exactly the authoritative container ids


def test_doorways_are_valid():
    ctx = _ctx()
    for d in _sample(ctx):
        ids = {r.room_id for r in d.rooms}
        for door in d.doorways:
            assert door.room_a in ids and door.room_b in ids
            assert door.room_a != door.room_b, "degenerate doorway (room to itself)"
            assert door.width > 0


def test_rooms_within_hull_and_footprint_tolerance():
    ctx = _ctx()
    TOL = interiors.WALL_MARGIN + 1.0        # rooms may reach the inset hull edge
    for d in _sample(ctx):
        hx0, hy0 = d.hull[0]
        hx1, hy1 = d.hull[2]
        for r in d.rooms:
            assert r.x0 >= hx0 - 1e-6 and r.x1 <= hx1 + 1e-6
            assert r.y0 >= hy0 - 1e-6 and r.y1 <= hy1 + 1e-6
        # hull is within the footprint AABB (+ tolerance for the wall inset)
        poly = ctx.building_poly(d.building_id)
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        assert hx0 >= min(xs) - TOL and hx1 <= max(xs) + TOL
        assert hy0 >= min(ys) - TOL and hy1 <= max(ys) + TOL


def test_repeated_reload_same_layout():
    ctx = _ctx()
    for bid in (0, 17, 100, 250):
        layouts = {_desc(ctx, bid).geometry_hash() for _ in range(3)}
        assert len(layouts) == 1


def test_archetypes_present():
    ctx = _ctx()
    kinds = {_desc(ctx, b).archetype for b in range(0, 400, 3)}
    # the generator should produce more than one archetype across a real city
    assert len(kinds) >= 2, f"only saw archetypes {kinds}"


if __name__ == "__main__":
    import types
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            fn()
            print("ok", name)
    print("interior generator certified")

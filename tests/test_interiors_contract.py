"""Walk-in interiors — Package 1 (authority contract) certification.

Proves the immutable-vs-persistent split, deterministic regeneration, stable
building->room->fixture->container identity, and RNG isolation from the epidemic.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel import interiors, items
from asphodel.interiors import build_interior, INTERIOR_GEN_VERSION
from asphodel.embodiment import CitySpatialContext
from asphodel.bridge.worldfactory import world_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.save import save_world, load_world_file


BUNDLE = "houston"


def _ctx():
    return CitySpatialContext.from_bundle_dir(resolve_bundle_dir(BUNDLE))


def _desc(ctx, bid, seed=1):
    return build_interior(bid, seed, ctx.building_poly(bid),
                          height=ctx.building_height(bid),
                          road_xy=ctx.nearest_road_xy(ctx.building_centroids[bid]))


# 1. same building + seed => identical descriptor
def test_1_same_building_seed_identical():
    ctx = _ctx()
    a = _desc(ctx, 42)
    b = _desc(ctx, 42)
    assert a.geometry_hash() == b.geometry_hash()
    assert a.to_dict() == b.to_dict()


# 2. different building id => independently deterministic
def test_2_different_building_independent():
    ctx = _ctx()
    h42 = _desc(ctx, 42).geometry_hash()
    h43 = _desc(ctx, 43).geometry_hash()
    assert h42 != h43
    # each is independently reproducible
    assert _desc(ctx, 43).geometry_hash() == h43


# 3. unload/reload => identical immutable layout (regeneration is the "reload")
def test_3_regeneration_identical_layout():
    ctx = _ctx()
    first = _desc(ctx, 100)
    # simulate unload then re-enter: rebuild from scratch
    again = _desc(ctx, 100)
    assert [r.to_dict() for r in first.rooms] == [r.to_dict() for r in again.rooms]
    assert [d.to_dict() for d in first.doorways] == [d.to_dict() for d in again.doorways]


# 4. container ids remain stable across regeneration
def test_4_container_ids_stable():
    ctx = _ctx()
    a = _desc(ctx, 7)
    b = _desc(ctx, 7)
    amap = {f.fixture_id: f.container_index for f in a.fixtures}
    bmap = {f.fixture_id: f.container_index for f in b.fixtures}
    assert amap == bmap
    # fixtures anchor to the real authoritative container count for the building
    assert len(a.fixtures) == items.n_containers(1, 7)
    # and container indices are exactly 0..n-1 (they ARE the authoritative ids)
    assert sorted(amap.values()) == list(range(len(a.fixtures)))


def _bundle_world():
    w = world_from_bundle(BUNDLE, seed=1,
                          micro_params=MicroParams(area_size=100.0,
                                                   infection_radius=2.0,
                                                   mixing_step_frac=0.12))
    w.set_citizens(load_bundle_population(resolve_bundle_dir(BUNDLE)))
    w.set_spatial_context(_ctx())
    return w


def _stocked_fixture(w, max_b=400):
    """A (building, fixture, container_index, kind) whose fixture's container has loot."""
    s = w.ensure_survival()
    for b in range(max_b):
        st = w.interior_state(b)
        for fx in st["fixtures"]:
            ci = fx["container_index"]
            contents = s.container_contents(b, ci)
            if contents:
                return b, fx["fixture_id"], ci, contents[0].kind
    raise AssertionError("no stocked fixture found")


# 5. touched-container delta reapplies correctly through interior_state
def test_5_touched_delta_reflected_in_interior_state():
    w = _bundle_world()
    s = w.ensure_survival()
    b, fid, ci, kind = _stocked_fixture(w)
    # before: fixture not searched
    st0 = w.interior_state(b)
    fx0 = next(f for f in st0["fixture_state"] if f["fixture_id"] == fid)
    assert not fx0["searched"]
    # take everything of that kind + drain the container
    for c in s.container_contents(b, ci):
        s.take_item(b, ci, c.kind, c.quantity)
    st1 = w.interior_state(b)
    fx1 = next(f for f in st1["fixture_state"] if f["fixture_id"] == fid)
    assert fx1["searched"] and fx1["empty"]


# 6. untouched building adds no persistent save payload
def test_6_untouched_building_zero_payload(tmp_path):
    w = _bundle_world()
    s = w.ensure_survival()
    # merely viewing interiors must not create deltas
    for b in range(50):
        w.interior_state(b)
    assert len(s._taken) == 0, "viewing interiors created container deltas"
    assert len(s.dropped) == 0
    # a save with only viewed (untouched) interiors carries no container delta
    p = str(tmp_path / "untouched.json")
    save_world(w, p, bundle=BUNDLE, player_citizen=0)
    reloaded = load_world_file(p)
    assert reloaded.survival is not None
    assert len(reloaded.survival._taken) == 0


# 7. save/load preserves changed interior delta state
def test_7_saveload_preserves_delta(tmp_path):
    w = _bundle_world()
    s = w.ensure_survival()
    b, fid, ci, kind = _stocked_fixture(w)
    for c in s.container_contents(b, ci):
        s.take_item(b, ci, c.kind, c.quantity)
    # indoor drop bound to the building
    s._add_to_inventory("bandage", 1)
    s.drop_item("bandage", 1, 1.0, 2.0, zone=-1, building_id=b)
    p = str(tmp_path / "delta.json")
    save_world(w, p, bundle=BUNDLE, player_citizen=0)

    reloaded = load_world_file(p)
    reloaded.set_spatial_context(_ctx())
    st = reloaded.interior_state(b)
    fx = next(f for f in st["fixture_state"] if f["fixture_id"] == fid)
    assert fx["searched"] and fx["empty"], "container delta lost on reload"
    assert any(it["kind"] == "bandage" for it in st["dropped_here"]), "indoor drop lost"


# 8. generation is RNG-isolated from the epidemic trajectory
def test_8_generation_rng_isolated():
    wa = _bundle_world()
    wb = world_from_bundle(BUNDLE, seed=1,
                           micro_params=MicroParams(area_size=100.0,
                                                    infection_radius=2.0,
                                                    mixing_step_frac=0.12))
    wb.set_citizens(load_bundle_population(resolve_bundle_dir(BUNDLE)))
    # focus something so agents exist
    from collections import Counter
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    z = Counter(c.home_zone for c in pop if c.home_zone is not None).most_common(1)[0][0]
    wa.set_focus([z]); wb.set_focus([z])

    def totals(w):
        s = w.sim
        return [round(float(getattr(s, n).sum()), 9)
                for n in ("S", "E", "Ia", "Is", "R", "D")]

    for _ in range(30):
        wa.step()
        # generate a bunch of interiors every tick on wa only
        for b in range(0, 60, 7):
            wa.interior_descriptor(b)
        wb.step()
    assert totals(wa) == totals(wb), "interior generation perturbed the epidemic"


if __name__ == "__main__":
    import pathlib
    import tempfile
    import types
    import inspect
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            if "tmp_path" in inspect.signature(fn).parameters:
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print("ok", name)
    print("interior authority contract certified")

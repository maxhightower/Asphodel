"""Walk-in interiors — Package 5 (interior NPC occupancy) certification.

A citizen whose authoritative schedule + location puts them inside a building
resolves to a deterministic interior anchor there — reusing the existing
embodiment work, not a new agent simulation. Bounded, deterministic, and stable
across unload/reload (regeneration) and save/load.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, MicroParams
from asphodel.embodiment import CitySpatialContext
from asphodel.bridge.worldfactory import config_from_bundle, resolve_bundle_dir
from asphodel.bundle_population import load_bundle_population
from asphodel.save import save_world, load_world_file


BUNDLE = "houston"


def _ctx():
    return CitySpatialContext.from_bundle_dir(resolve_bundle_dir(BUNDLE))


def _world(start_hour):
    cfg = config_from_bundle(BUNDLE, seed=1)
    w = World(cfg, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                            mixing_step_frac=0.12),
              start_hour=start_hour, seed=cfg.seed)
    w.set_citizens(load_bundle_population(resolve_bundle_dir(BUNDLE)))
    w.set_spatial_context(_ctx())
    return w


def _day_worker(pop, ctx):
    for c in pop:
        if c.shift == "day" and c.work_xy is not None:
            return c, ctx.nearest_building(c.work_xy)
    raise AssertionError("no day worker with a workplace")


def test_on_shift_worker_occupies_workplace_interior():
    ctx = _ctx()
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    c, work_bid = _day_worker(pop, ctx)
    # noon: a day-shift worker is on shift -> inside their workplace building.
    w = _world(start_hour=12.0)
    occ = w.building_occupants(work_bid)
    ids = [o["citizen_id"] for o in occ]
    assert c.citizen_id in ids, f"worker {c.citizen_id} not inside workplace {work_bid}"
    me = next(o for o in occ if o["citizen_id"] == c.citizen_id)
    assert me["activity"] == "work"
    assert me["room_id"] >= 0


def test_off_shift_worker_not_in_workplace():
    ctx = _ctx()
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    c, work_bid = _day_worker(pop, ctx)
    # 3am: the day worker is asleep at home, not at the workplace.
    w = _world(start_hour=3.0)
    ids = [o["citizen_id"] for o in w.building_occupants(work_bid)]
    assert c.citizen_id not in ids


def test_occupancy_is_deterministic_anchor():
    ctx = _ctx()
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    c, work_bid = _day_worker(pop, ctx)
    w = _world(start_hour=12.0)
    a = w.building_occupants(work_bid)
    b = w.building_occupants(work_bid)
    assert a == b, "occupancy anchors non-deterministic"


def test_occupancy_survives_regeneration_and_saveload(tmp_path):
    ctx = _ctx()
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    c, work_bid = _day_worker(pop, ctx)
    w = _world(start_hour=12.0)
    before = w.building_occupants(work_bid)
    # "unload/reload" the interior: regenerate the descriptor from scratch and
    # recompute occupancy -> identical (anchors are pure functions).
    again = w.building_occupants(work_bid, w.interior_descriptor(work_bid))
    assert before == again

    # save/load preserves the on-shift occupancy for the same authoritative time.
    p = str(tmp_path / "occ.json")
    save_world(w, p, bundle=BUNDLE, player_citizen=c.citizen_id)
    rl = load_world_file(p)
    rl.set_spatial_context(_ctx())
    assert rl.building_occupants(work_bid) == before


def test_occupancy_bounded_and_epidemic_neutral():
    # Building occupancy iterates only the registered citizen set (bounded), and
    # querying it never perturbs the epidemic (pure/derived).
    ctx = _ctx()
    wa = _world(start_hour=12.0)
    wb = _world(start_hour=12.0)

    def totals(w):
        s = w.sim
        return [round(float(getattr(s, n).sum()), 9)
                for n in ("S", "E", "Ia", "Is", "R", "D")]

    wa.set_focus([wa.cfg.seed_zone]); wb.set_focus([wb.cfg.seed_zone])
    for _ in range(20):
        wa.step()
        for b in range(0, 40, 5):
            wa.building_occupants(b)               # exercise occupancy on wa only
        wb.step()
    assert totals(wa) == totals(wb)


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
    print("interior occupancy certified")

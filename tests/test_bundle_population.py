"""BW1 tests: real bundle -> authoritative World population.

Covers: loading each committed city bundle, deterministic citizen construction,
valid ids, coordinate->zone mapping (boundary/center/out-of-bounds), deterministic
schedule reconstruction, player-citizen resolution, malformed handling, and
identical START_WORLD -> identical population assignment.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bundle_population import (load_bundle_population, zone_centers,
                                        zone_of_xy, reconstruct_schedule)
from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.bridge import WorldSession, PROTOCOL_VERSION
from asphodel.bridge.protocol import Command, ErrorCode


CITIES = ["houston", "san_antonio", "austin", "madisonville_tx"]


def _bundle(city):
    return resolve_bundle_dir(city)


# --------------------------------------------------------------------------- #
# load every committed city
# --------------------------------------------------------------------------- #
def test_every_bundle_loads_valid_citizens():
    for city in CITIES:
        d = _bundle(city)
        pop = load_bundle_population(d)
        assert len(pop) > 0
        zones = json.load(open(os.path.join(d, "zones.json")))
        n_zones = len(zones)
        ids = [c.citizen_id for c in pop]
        assert ids == list(range(len(pop)))                 # unique, contiguous
        for c in pop:
            assert c.home_zone is None or 0 <= c.home_zone < n_zones
            assert c.work_zone is None or 0 <= c.work_zone < n_zones
            assert len(c.schedule) > 0


def test_population_is_deterministic():
    d = _bundle("houston")
    a = load_bundle_population(d)
    b = load_bundle_population(d)
    for x, y in zip(a, b):
        assert x.citizen_id == y.citizen_id
        assert x.home_zone == y.home_zone and x.work_zone == y.work_zone
        assert [(e.start_hour, e.activity) for e in x.schedule] == \
               [(e.start_hour, e.activity) for e in y.schedule]


# --------------------------------------------------------------------------- #
# coordinate -> zone
# --------------------------------------------------------------------------- #
def _centers(city):
    zones = json.load(open(os.path.join(_bundle(city), "zones.json")))
    return zones, zone_centers(zones)


def test_center_coordinate_maps_to_its_own_zone():
    zones, (ids, centers) = _centers("houston")
    for z in zones[:20]:
        cx, cz = z["center_xy"]
        assert zone_of_xy(cx, cz, ids, centers) == z["id"]


def test_boundary_and_out_of_bounds_are_deterministic():
    zones, (ids, centers) = _centers("madisonville_tx")
    # a point far outside the map clamps to some real zone, deterministically
    z1 = zone_of_xy(1e9, 1e9, ids, centers)
    z2 = zone_of_xy(1e9, 1e9, ids, centers)
    assert z1 == z2 and 0 <= z1 < len(zones)
    # a boundary midpoint between two centres resolves the same way each call
    a, b = centers[0], centers[1]
    mid = (a + b) / 2.0
    assert zone_of_xy(mid[0], mid[1], ids, centers) == \
           zone_of_xy(mid[0], mid[1], ids, centers)


# --------------------------------------------------------------------------- #
# schedule reconstruction
# --------------------------------------------------------------------------- #
def test_schedule_reconstruction_deterministic_and_shift_aware():
    day = reconstruct_schedule("day", citizen_id=42)
    day2 = reconstruct_schedule("day", citizen_id=42)
    night = reconstruct_schedule("night", citizen_id=42)
    none = reconstruct_schedule("none", citizen_id=42, work_n=None)
    assert [(e.start_hour, e.activity) for e in day] == \
           [(e.start_hour, e.activity) for e in day2]           # deterministic
    assert any(e.activity == "work" for e in day)               # day has work
    assert any(e.activity == "work" for e in night)             # night has work
    assert all(e.activity != "work" for e in none)              # none has none
    # schedules cover a valid ordering
    for sched in (day, night, none):
        for e in sched:
            assert e.end_hour > e.start_hour


# --------------------------------------------------------------------------- #
# malformed handling
# --------------------------------------------------------------------------- #
def test_missing_citizens_file_raises(tmp_path):
    # a directory with zones/meta but no citizens.json
    d = _bundle("houston")
    import shutil
    dst = tmp_path / "bundle"
    dst.mkdir()
    for f in ("zones.json", "meta.json"):
        shutil.copy(os.path.join(d, f), dst / f)
    try:
        load_bundle_population(str(dst))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


# --------------------------------------------------------------------------- #
# START_WORLD integration
# --------------------------------------------------------------------------- #
def test_start_world_populates_real_citizens():
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = s.handle({"cmd": Command.START_WORLD, "bundle": "houston", "seed": 1,
                  "player_citizen_id": 5})
    assert r["ok"]
    n_bundle = len(json.load(open(os.path.join(_bundle("houston"), "citizens.json"))))
    assert n_bundle >= 60
    assert r["n_citizens"] == n_bundle
    assert r["player_home_zone"] is not None
    assert len(s.world.citizens) == n_bundle
    # the player's home zone is focused, so it promotes with the resident embodied
    s.handle({"cmd": Command.ADVANCE, "ticks": 2})
    assert r["player_home_zone"] in s.world.promoted


def test_unknown_player_citizen_rejected():
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = s.handle({"cmd": Command.START_WORLD, "bundle": "madisonville_tx",
                  "player_citizen_id": 99999})
    assert not r["ok"] and r["error"]["code"] == ErrorCode.BAD_ARGUMENT


def test_identical_start_world_identical_population():
    def pop_fingerprint():
        s = WorldSession()
        s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
        s.handle({"cmd": Command.START_WORLD, "bundle": "austin", "seed": 3})
        return sorted((c.citizen_id, c.home_zone, c.work_zone)
                      for c in s.world.citizens.values())
    assert pop_fingerprint() == pop_fingerprint()


def test_citizens_false_gives_bare_world():
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    r = s.handle({"cmd": Command.START_WORLD, "bundle": "houston",
                  "citizens": False})
    assert r["ok"] and r["n_citizens"] == 0
    assert len(s.world.citizens) == 0


if __name__ == "__main__":
    import types
    import inspect
    import pathlib
    import tempfile
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            if "tmp_path" in inspect.signature(fn).parameters:
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print("ok", name)
    print("all BW1 tests passed")

"""The outbreak is LOD-independent (§9 + ASPHODEL_EMBODIED_MOBILITY_V1 §17).

The disease is not a presentation effect: with the player 20 km away — the
index case never leaves ROUTE_SIMULATED, never gets a body — citizen 42 still
becomes symptomatic, collapses, dies and rises, because the HealthRecord and
the executor are the authority and the band is not.

Then the player walks up to the corpse/undead: the promotion to PHYSICAL must
change nothing except the band — same position, same health, same citizen id in
the ``near`` list — and a demote/promote cycle must be idempotent.

One nuance the rows expose: ``EmbodimentState.UNDEAD`` is the *idle* pose of an
undead body (``TripExecutor._in_place``); while it is walking a hunt/roam leg
the executor reports ``on_foot``, exactly like a living pedestrian. The stable
undead markers on the wire are therefore ``override`` and ``health``, and that
is what these tests hold the runtime to.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodied.executor import EmbodimentState
from asphodel.embodiment import CitySpatialContext
from asphodel.lod.entity import LODBand
from asphodel.outbreak.health import HealthState

CITY = "houston"
INDEX = 42
START_HOUR = 5.0
END_HOUR = 11.0
FAR = (200000.0, 200000.0)      # 200 km away: nothing is near the player
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


@pytest.fixture(scope="module")
def far_run():
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)
    # The ABSTRACT overflow tier (a budget, not a distance band) is covered by
    # tests/test_embodied_lod.py; here every citizen stays simulated so the
    # question is only physical-vs-route.
    w.mobility.max_active = len(w.mobility.execs) + 1
    ob = w.enable_outbreak("classic_zombie", index_case=INDEX)
    w.mobility.set_focus_xy(FAR)
    bands = []
    for _ in range(int((END_HOUR - START_HOUR) * 60)):
        w.advance_seconds(60.0, focus_xy=FAR)
        bands.append(w.mobility.bands[INDEX])
    return {"world": w, "ob": ob, "bands": bands}


def _row(w, cid):
    snap = w.mobility_snapshot(include_routes=False)
    return snap, next(r for r in snap["citizens"] if r["citizen_id"] == cid)


def _focus(w, xy):
    """Move the player and settle the LOD bands without advancing time."""
    w.mobility.set_focus_xy(xy)
    w.mobility.advance(0.0, w.current_hour())


def test_the_whole_chain_runs_with_the_player_far_away(far_run):
    ob = far_run["ob"]
    kinds = [e["event"] for e in ob.events if e.get("citizen_id") == INDEX]
    for kind in ("SYMPTOM_ONSET", "INCAPACITATED", "DEATH", "REANIMATION"):
        assert kind in kinds, kinds
    assert ob.records[INDEX].state is HealthState.UNDEAD


def test_the_index_case_never_had_a_body(far_run):
    assert far_run["bands"], "no band was sampled"
    assert all(b is not LODBand.PHYSICAL for b in far_run["bands"]), \
        sorted({b.name for b in far_run["bands"]})
    w = far_run["world"]
    assert w.mobility.execs[INDEX].has_body is False
    assert w.mobility.snapshot(include_routes=False)["near"] == []


def test_promotion_to_physical_changes_nothing_but_the_band(far_run):
    w, ob = far_run["world"], far_run["ob"]
    ex = w.mobility.execs[INDEX]
    rec_before = ob.records[INDEX].to_state()
    pos_before = tuple(ex.pos)
    _snap, row_before = _row(w, INDEX)
    assert row_before["band"] == "route_simulated"

    _focus(w, pos_before)

    snap, row = _row(w, INDEX)
    assert w.mobility.bands[INDEX] is LODBand.PHYSICAL
    assert row["band"] == "physical"
    assert ex.has_body is True
    assert f"cit:{INDEX}" in snap["near"]
    assert tuple(ex.pos) == pos_before                     # no jump on promotion
    assert (row["x"], row["y"]) == (row_before["x"], row_before["y"])
    assert row["health"] == "undead"
    assert row["override"] == "undead"
    assert row["state"] in (EmbodimentState.UNDEAD.value, EmbodimentState.ON_FOOT.value)
    assert row["vehicle_id"] is None
    assert ob.records[INDEX].to_state() == rec_before       # promotion is not medicine


def test_demote_and_promote_again_is_idempotent(far_run):
    w, ob = far_run["world"], far_run["ob"]
    ex = w.mobility.execs[INDEX]
    pos = tuple(ex.pos)
    rec = ob.records[INDEX].to_state()
    _snap, row0 = _row(w, INDEX)

    _focus(w, FAR)
    assert w.mobility.bands[INDEX] is not LODBand.PHYSICAL
    assert ex.has_body is False
    assert tuple(ex.pos) == pos
    assert ob.records[INDEX].to_state() == rec

    _focus(w, pos)
    snap, row1 = _row(w, INDEX)
    assert w.mobility.bands[INDEX] is LODBand.PHYSICAL
    assert f"cit:{INDEX}" in snap["near"]
    assert tuple(ex.pos) == pos
    assert row1 == row0
    assert ob.records[INDEX].to_state() == rec


def test_health_survives_a_band_cycle_for_every_recorded_citizen(far_run):
    w, ob = far_run["world"], far_run["ob"]
    before = {c: r.to_state() for c, r in ob.records.items()}
    positions = {c: tuple(w.mobility.execs[c].pos) for c in ob.records}
    for xy in (FAR, positions[INDEX], FAR, positions[INDEX]):
        _focus(w, xy)
        assert {c: r.to_state() for c, r in ob.records.items()} == before
        assert {c: tuple(w.mobility.execs[c].pos) for c in ob.records} == positions
    assert ob.snapshot(max_events=0)["counts"] == \
        far_run["ob"].snapshot(max_events=0)["counts"]


def test_a_corpse_is_promotable_too(far_run):
    """Every corpse/undead in the run can be walked up to, and reports itself."""
    w, ob = far_run["world"], far_run["ob"]
    dead = [c for c, r in sorted(ob.records.items())
            if r.state in (HealthState.CORPSE, HealthState.DEAD, HealthState.UNDEAD)]
    assert dead, "the run produced no bodies"
    for cid in dead:
        ex = w.mobility.execs[cid]
        pos = tuple(ex.pos)
        _focus(w, pos)
        snap, row = _row(w, cid)
        assert f"cit:{cid}" in snap["near"]
        assert tuple(ex.pos) == pos
        assert row["health"] == ob.records[cid].state.value
        assert row["override"] in ("corpse", "undead")
        if ob.records[cid].state is HealthState.CORPSE:
            assert math.hypot(row["x"] - ob.records[cid].corpse_xy[0],
                              row["y"] - ob.records[cid].corpse_xy[1]) < 0.05
    _focus(w, FAR)

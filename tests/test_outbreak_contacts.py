"""Contact model: exposure comes from where the bodies actually are (§5).

The Houston world is the substrate — a synthetic MobilityRuntime would prove
nothing about co-occupancy, because co-occupancy IS the executors' real
situation. Index case 42 is seeded at 05:00 and the world is advanced to
~10:30; every exposure in that window must be explained by a contact context
that the executors physically satisfied at that moment:

* the event's ``context`` is ``building:<bid>`` / ``vehicle:<vid>`` /
  ``proximity`` / ``bite`` and nothing else;
* for a building exposure both bodies were inside that building then, and the
  event's ``building_id`` is the victim's;
* the transmission chain is consistent (``victim.lineage == source.lineage +
  [source]``);
* nobody who was never co-located with an infectious citizen is infected; and
* a citizen is infected exactly once — ``HealthRecord.infect`` is never called
  twice for the same citizen.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.bridge.worldfactory import resolve_bundle_dir, world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.embodiment import CitySpatialContext
from asphodel.outbreak.health import HealthRecord, HealthState

CITY = "houston"
INDEX = 42
WORK = 2318                 # citizen 42's workplace
START_HOUR = 5.0
END_HOUR = 10.5             # ~10:30
MICRO = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
VALID_PREFIXES = ("building:", "vehicle:")
VALID_CONTEXTS = ("proximity", "bite", "index_case")


def _bundle_dir():
    d = resolve_bundle_dir(CITY)
    if not os.path.exists(os.path.join(d, "world", "world_meta.json")):
        pytest.skip("houston compiled world absent")
    return d


@pytest.fixture(scope="module")
def run():
    """Advance the seeded world minute by minute, recording the physical
    situation of both parties at the minute each exposure happened."""
    d = _bundle_dir()
    w = world_from_bundle(CITY, micro_params=MICRO)
    w.start_hour = START_HOUR
    w.set_citizens(load_bundle_population(d))
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w.enable_mobility(bundle_dir=d)

    infect_calls: Counter = Counter()
    original = HealthRecord.infect

    def spy(self, *a, **kw):
        infect_calls[self.citizen_id] += 1
        return original(self, *a, **kw)

    HealthRecord.infect = spy
    try:
        ob = w.enable_outbreak("classic_zombie", index_case=INDEX)
        seen = 0
        witnessed = []          # (event, {cid: situation}) for every exposure
        co_located: dict = {}   # cid -> set of infectious citizens ever shared a place with
        for _ in range(int((END_HOUR - START_HOUR) * 60)):
            w.advance_seconds(60.0)
            new = [e for e in ob.events if e["seq"] > seen and e["event"] == "EXPOSURE"]
            if ob.events:
                seen = ob.events[-1]["seq"]
            for e in new:
                who = {}
                for cid in (e["citizen_id"], e.get("source_citizen")):
                    if cid is None:
                        continue
                    ex = w.mobility.execs[cid]
                    who[cid] = {"pos": tuple(ex.pos), "inside": bool(ex.inside),
                                "building_id": int(ex.building_id), "vehicle_id": ex.vehicle_id,
                                "override": ex.override}
                witnessed.append((e, who))
            # co-location bookkeeping: who could possibly have met an infectious body
            infectious = [c for c, r in ob.records.items()
                          if r.infectious_weight(ob.pathogen, ob.now_s) > 0.0]
            for cid, ex in w.mobility.execs.items():
                for s in infectious:
                    if s == cid:
                        continue
                    sx = w.mobility.execs[s]
                    same_b = ex.inside and sx.inside and ex.building_id == sx.building_id >= 0
                    same_v = bool(ex.vehicle_id) and ex.vehicle_id == sx.vehicle_id
                    near = (not ex.inside and not sx.inside
                            and (ex.pos[0] - sx.pos[0]) ** 2 + (ex.pos[1] - sx.pos[1]) ** 2
                            <= (5.0 * ob.pathogen.proximity_radius_m) ** 2)
                    if same_b or same_v or near:
                        co_located.setdefault(cid, set()).add(s)
    finally:
        HealthRecord.infect = original
    return {"world": w, "ob": ob, "witnessed": witnessed, "co_located": co_located,
            "infect_calls": infect_calls,
            "records": {c: r.to_state() for c, r in ob.records.items()}}


def test_the_index_case_is_the_only_seeded_infection(run):
    ob = run["ob"]
    seeded = [e for e in ob.events if e["event"] == "EXPOSURE" and e["context"] == "index_case"]
    assert [e["citizen_id"] for e in seeded] == [INDEX]
    rec = ob.records[INDEX]
    assert rec.source_citizen is None and rec.lineage == [] and rec.asymptomatic is False


def test_every_exposure_has_a_physically_meaningful_context(run):
    exposures = [e for e, _ in run["witnessed"]]
    assert exposures, "no exposure happened in the window"
    for e in exposures:
        ctx = e["context"]
        assert ctx.startswith(VALID_PREFIXES) or ctx in VALID_CONTEXTS, e
        if e.get("source_citizen") is None:
            assert ctx == "index_case", e
        else:
            assert ctx != "index_case", e


def test_building_exposures_had_both_bodies_inside_that_building(run):
    checked = 0
    for e, who in run["witnessed"]:
        src = e.get("source_citizen")
        if src is None or not e["context"].startswith("building:"):
            continue
        bid = int(e["context"].split(":", 1)[1])
        victim, source = who[e["citizen_id"]], who[src]
        assert e["building_id"] == bid == victim["building_id"], e
        assert victim["inside"] and source["inside"], (e, who)
        assert source["building_id"] == bid, (e, who)
        assert (e["x"], e["y"]) == (round(victim["pos"][0], 1), round(victim["pos"][1], 1))
        checked += 1
    assert checked >= 2, "expected co-occupancy transmission inside the workplace"


def test_workplace_transmission_is_the_source_registered_workplace(run):
    mob = run["world"].mobility
    for e, _ in run["witnessed"]:
        src = e.get("source_citizen")
        if src is None or not e["context"].startswith("building:"):
            continue
        bid = int(e["context"].split(":", 1)[1])
        # the source is physically there because it is where they work
        assert int(mob.records[src].work_building_id) == bid
    chain = [e for e, _ in run["witnessed"] if e["context"] == f"building:{WORK}"]
    assert chain, f"expected the workplace {WORK} chain"
    assert all(v["citizen_id"] in run["ob"].workers_by_building[WORK] for v in chain)


def test_vehicle_and_proximity_contexts_are_self_consistent(run):
    for e, who in run["witnessed"]:
        src = e.get("source_citizen")
        if src is None:
            continue
        ctx = e["context"]
        if ctx.startswith("vehicle:"):
            vid = ctx.split(":", 1)[1]
            assert who[e["citizen_id"]]["vehicle_id"] == who[src]["vehicle_id"] == vid, (e, who)
        elif ctx == "proximity":
            a, b = who[e["citizen_id"]]["pos"], who[src]["pos"]
            assert not who[e["citizen_id"]]["inside"] and not who[src]["inside"], (e, who)
            d = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            assert d <= 20.0, (e, who, d)      # both bodies keep moving after the tick
        elif ctx == "bite":
            assert who[src]["override"] == "undead", (e, who)


def test_lineage_chains_are_consistent(run):
    ob = run["ob"]
    for cid, rec in sorted(ob.records.items()):
        if rec.state == HealthState.SUSCEPTIBLE:
            continue
        src = rec.source_citizen
        if src is None:
            assert rec.lineage == []
            continue
        assert rec.lineage == list(ob.records[src].lineage) + [src], (cid, rec.lineage)
        assert cid not in rec.lineage                       # never its own ancestor
        assert rec.lineage[0] == INDEX                      # every chain starts at the index case
        assert len(set(rec.lineage)) == len(rec.lineage)


def test_infection_only_where_bodies_met(run):
    ob, co = run["ob"], run["co_located"]
    infected = [c for c, r in ob.records.items()
                if r.state != HealthState.SUSCEPTIBLE and c != INDEX]
    assert infected, "no secondary infection in the window"
    for cid in infected:
        assert ob.records[cid].source_citizen in co.get(cid, set()), (cid, ob.records[cid].source_citizen)


def test_a_citizen_who_never_met_an_infectious_body_stays_susceptible(run):
    ob, co = run["ob"], run["co_located"]
    never = [c for c in sorted(run["world"].mobility.execs) if not co.get(c)]
    assert never, "expected citizens who never shared a place with an infectious body"
    for cid in never:
        rec = ob.records.get(cid)
        assert rec is None or rec.state == HealthState.SUSCEPTIBLE, (cid, rec)
    # ... and one concrete far-away citizen, by name
    far = never[0]
    assert far != INDEX
    assert ob.snapshot()["counts"]["susceptible"] > 0


def test_nobody_is_infected_twice(run):
    calls = run["infect_calls"]
    assert calls, "the infect() spy saw nothing"
    assert max(calls.values()) == 1, [c for c, n in calls.items() if n > 1]
    infected_events = Counter(e["citizen_id"] for e in run["ob"].events if e["event"] == "INFECTED")
    assert infected_events and max(infected_events.values()) == 1
    assert set(calls) == set(infected_events)


def test_only_susceptible_citizens_can_be_exposed(run):
    """An exposure is only ever recorded against a citizen with no prior record."""
    ob = run["ob"]
    first_seen: dict = {}
    for e in ob.events:
        if e["event"] != "EXPOSURE":
            continue
        cid = e["citizen_id"]
        assert cid not in first_seen, f"citizen {cid} exposed twice"
        first_seen[cid] = e["seq"]
    for cid, rec in ob.records.items():
        if rec.state != HealthState.SUSCEPTIBLE:
            assert cid in first_seen

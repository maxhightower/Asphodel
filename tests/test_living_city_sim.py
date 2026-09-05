"""Tests for the living-city commute driver (§19/§25) and the mobility loader."""
from __future__ import annotations

import json
import os

import pytest

from asphodel.mobility import Mode, MobilityGraph
from asphodel.living_city import simulate_commute, AT_HOME, EN_ROUTE, AT_WORK

BULE = os.path.join(os.path.dirname(__file__), os.pardir, "godot", "bundles", "boulder")


def _has_mobility():
    return os.path.exists(os.path.join(BULE, "streetmap.json"))


@pytest.mark.skipif(not _has_mobility(), reason="boulder bundle not present")
def test_mobility_from_artifact_is_routable():
    with open(os.path.join(BULE, "streetmap.json")) as f:
        g = MobilityGraph.from_artifact(json.load(f))
    assert g.stats()["nodes"] > 100 and g.stats()["directed_edges"] > 0
    # A route between two nodes on the connected grid exists.
    nodes = list(g.nodes)
    r = g.route(nodes[0], nodes[len(nodes) // 2], Mode.CAR)
    assert r is not None


@pytest.mark.skipif(not _has_mobility(), reason="boulder bundle not present")
def test_commute_progresses_home_to_work():
    pb = simulate_commute(BULE, n_citizens=120, seed=5)
    assert pb["n_citizens"] > 50 and pb["n_cars"] > 0
    frames = pb["frames"]

    def counts(fr):
        c = {AT_HOME: 0, EN_ROUTE: 0, AT_WORK: 0}
        for row in fr["peds"] + fr["cars"]:
            c[int(row[2])] += 1
        return c

    first, last = counts(frames[0]), counts(frames[-1])
    assert first[AT_HOME] > first[AT_WORK]      # morning: mostly still home
    assert last[AT_WORK] > last[AT_HOME]        # by 9am: mostly at work
    # somebody is en route during the peak
    assert max(counts(fr)[EN_ROUTE] for fr in frames) > 5


@pytest.mark.skipif(not _has_mobility(), reason="boulder bundle not present")
def test_commute_positions_move():
    pb = simulate_commute(BULE, n_citizens=120, seed=5)
    # An agent's recorded position changes between an early and a later frame.
    early = pb["frames"][2]["cars"] + pb["frames"][2]["peds"]
    late = pb["frames"][len(pb["frames"]) // 2]["cars"] + pb["frames"][len(pb["frames"]) // 2]["peds"]
    moved = sum(1 for a, b in zip(early, late)
                if (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 > 1.0)
    assert moved > 10


@pytest.mark.skipif(not _has_mobility(), reason="boulder bundle not present")
def test_commute_congestion_emerges():
    pb = simulate_commute(BULE, n_citizens=150, seed=3)
    max_cong = max((c[1] for fr in pb["frames"] for c in fr["congestion"]), default=1.0)
    assert max_cong > 1.0                        # jams form where trips converge

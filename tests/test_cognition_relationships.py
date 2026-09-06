"""Bounded persistent relationships (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §9, §10).

Pure-Python. A relationship is the OWNER's directional view of another
citizen along six dimensions, each bounded in [0, 1] and moved only by the
deterministic rule table:

* repeated events SATURATE (approach 1 or 0, never leave the range);
* A's view of B is not B's view of A;
* household priors are stronger than workplace priors, and priors never
  lower an existing value;
* discharging an obligation (``reciprocated``) lowers it;
* being attacked raises fear and hostility and destroys trust;
* a false warning costs the warner trust;
* to_state/from_state round trips byte-identically.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.cognition.relationships import (DIMS, PRIORS, RULES, Relationship,
                                              RelationshipGraph, _sat)


def _dump(g) -> str:
    return json.dumps(g.to_state(), sort_keys=True)


def _in_range(r) -> None:
    for d in DIMS:
        v = getattr(r, d)
        assert 0.0 <= v <= 1.0, (d, v)


# --------------------------------------------------------------------------- #
# bounds and saturation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule", sorted(RULES))
def test_every_rule_applied_a_hundred_times_stays_in_range(rule):
    g = RelationshipGraph()
    for i in range(100):
        g.apply(1, 2, rule, float(i))
        _in_range(g.get(1, 2))
    r = g.get(1, 2)
    assert r.interactions == 100
    assert r.last_t == 99.0


def test_a_positive_rule_saturates_towards_one_without_ever_reaching_it():
    g = RelationshipGraph()
    last = -1.0
    for i in range(200):
        g.apply(1, 2, "worked_beside", float(i))
        v = g.get(1, 2).familiarity
        assert v >= last, "familiarity went backwards on a positive rule"
        assert v < 1.0 + 1e-12
        last = v
    assert 0.99 < last <= 1.0, last
    # the step shrinks as it saturates: the 200th day adds less than the first
    g2 = RelationshipGraph()
    first = g2.apply(1, 2, "worked_beside", 0.0)[0]
    assert (first[2] - first[1]) > 0.05


def test_a_negative_rule_saturates_towards_zero():
    g = RelationshipGraph()
    for i in range(200):
        g.apply(1, 2, "false_warning", float(i))
    r = g.get(1, 2)
    assert 0.0 <= r.trust < 0.001, r.trust
    assert 0.0 <= r.affinity <= 1e-9


def test_the_saturating_step_is_the_documented_formula():
    assert _sat(0.0, 0.5) == pytest.approx(0.5)
    assert _sat(0.5, 0.5) == pytest.approx(0.75)
    assert _sat(0.5, -0.5) == pytest.approx(0.25)
    assert _sat(1.0, 0.9) == pytest.approx(1.0)
    assert _sat(0.0, -0.9) == pytest.approx(0.0)


def test_apply_reports_only_the_dimensions_that_actually_moved():
    g = RelationshipGraph()
    changes = g.apply(1, 2, "helped_by", 10.0)
    dims = {d for d, _, _ in changes}
    assert dims == {d for d, _ in RULES["helped_by"]}
    # affinity starts at 0.0 so a negative rule cannot move it
    g2 = RelationshipGraph()
    changes2 = g2.apply(1, 2, "abandoned_by", 10.0)
    assert {d for d, _, _ in changes2} == {"trust"}, changes2


def test_a_citizen_has_no_relationship_with_itself():
    g = RelationshipGraph()
    assert g.apply(1, 1, "helped_by", 0.0) == []
    assert g.rels == {}


# --------------------------------------------------------------------------- #
# directionality
# --------------------------------------------------------------------------- #
def test_the_view_is_directional():
    g = RelationshipGraph()
    g.apply(1, 2, "helped_by", 10.0)      # 1 was helped by 2
    g.apply(2, 1, "helped", 10.0)         # 2 helped 1
    a, b = g.get(1, 2), g.get(2, 1)
    assert a is not b
    assert a.obligation > 0.0 and b.obligation == 0.0
    assert a.trust > b.trust
    assert a.affinity > b.affinity
    assert g.get(2, 1).owner == 2 and g.get(2, 1).other == 1


def test_of_returns_only_the_owners_own_views_in_id_order():
    g = RelationshipGraph()
    for other in (5, 3, 4):
        g.apply(1, other, "met", 0.0)
    g.apply(2, 1, "met", 0.0)
    assert [r.other for r in g.of(1)] == [3, 4, 5]
    assert [r.other for r in g.of(2)] == [1]
    assert g.of(99) == []


def test_get_does_not_create_unless_asked():
    g = RelationshipGraph()
    assert g.get(1, 2) is None
    assert g.rels == {}
    r = g.get(1, 2, create=True)
    assert r is not None and r.trust == 0.3 and r.familiarity == 0.0


# --------------------------------------------------------------------------- #
# priors (§10)
# --------------------------------------------------------------------------- #
def test_a_household_prior_is_stronger_than_a_workplace_prior():
    g = RelationshipGraph()
    home = g.prior(1, 2, "household", 0.0)
    work = g.prior(1, 3, "workplace", 0.0)
    for dim in ("familiarity", "trust", "affinity"):
        assert getattr(home, dim) > getattr(work, dim), dim
    assert home.origin == "household" and work.origin == "workplace"
    assert PRIORS["household"]["familiarity"] > PRIORS["workplace"]["familiarity"]
    for r in (home, work):
        _in_range(r)
        assert r.fear == 0.0 and r.hostility == 0.0 and r.obligation == 0.0


def test_a_prior_is_applied_once_and_never_lowers_an_earned_value():
    g = RelationshipGraph()
    for i in range(40):
        g.apply(1, 2, "helped_by", float(i))
    earned = g.get(1, 2).trust
    assert earned > PRIORS["workplace"]["trust"]
    g.prior(1, 2, "workplace", 100.0)
    assert g.get(1, 2).trust == earned, "a prior overwrote experience"
    # a second prior call does not re-apply
    g.prior(1, 3, "workplace", 0.0)
    g.apply(1, 3, "false_warning", 1.0)
    lowered = g.get(1, 3).trust
    g.prior(1, 3, "household", 2.0)
    assert g.get(1, 3).trust == lowered
    assert g.get(1, 3).origin == "workplace"


# --------------------------------------------------------------------------- #
# the rules that carry the story
# --------------------------------------------------------------------------- #
def test_being_helped_creates_obligation_that_reciprocating_discharges():
    g = RelationshipGraph()
    g.apply(1, 2, "helped_by", 0.0)
    obliged = g.get(1, 2).obligation
    assert obliged > 0.4, obliged
    g.apply(1, 2, "reciprocated", 100.0)
    after = g.get(1, 2).obligation
    assert after < obliged, "reciprocating did not discharge the obligation"
    assert after == pytest.approx(obliged * 0.4)
    assert after >= 0.0
    # the warmth of having been helped survives the discharge
    assert g.get(1, 2).affinity > 0.0 and g.get(1, 2).trust > 0.3


def test_being_attacked_raises_fear_and_hostility_and_destroys_trust():
    g = RelationshipGraph()
    g.prior(1, 2, "household", 0.0)      # even a housemate
    before = g.get(1, 2).to_dict()
    assert before["trust"] == pytest.approx(0.70)
    g.apply(1, 2, "attacked_by", 10.0)
    r = g.get(1, 2)
    assert r.fear >= 0.9 and r.hostility >= 0.8
    assert r.trust < 0.1, r.trust
    assert r.affinity < before["affinity"]
    _in_range(r)
    # and the victim's view alone changed
    assert g.get(2, 1) is None


def test_a_false_warning_costs_the_warner_trust_and_affinity():
    g = RelationshipGraph()
    g.apply(1, 2, "warned_by", 0.0)
    warmed = g.get(1, 2)
    t0, a0 = warmed.trust, warmed.affinity
    g.apply(1, 2, "false_warning", 60.0)
    r = g.get(1, 2)
    assert r.trust < t0 and r.affinity < a0
    assert r.trust == pytest.approx(t0 * 0.65)
    _in_range(r)
    # a confirmed warning moves it the other way
    g2 = RelationshipGraph()
    g2.apply(1, 2, "warned_by", 0.0)
    t1 = g2.get(1, 2).trust
    g2.apply(1, 2, "warning_confirmed", 60.0)
    assert g2.get(1, 2).trust > t1


def test_hearing_about_a_threat_only_moves_fear_and_scales_with_confidence():
    g = RelationshipGraph()
    g.apply(1, 9, "told_threat", 0.0, scale=1.0)
    sure = g.get(1, 9)
    g.apply(2, 9, "told_threat", 0.0, scale=0.2)
    unsure = g.get(2, 9)
    assert sure.fear > unsure.fear > 0.0
    assert sure.hostility == 0.0 and sure.trust == 0.3


def test_seeing_a_threat_frightens_more_than_hearing_about_one():
    g = RelationshipGraph()
    g.apply(1, 9, "threat_seen", 0.0)
    g.apply(2, 9, "told_threat", 0.0)
    assert g.get(1, 9).fear > g.get(2, 9).fear


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def test_state_round_trips_byte_identically():
    g = RelationshipGraph()
    g.prior(1, 2, "household", 0.0)
    g.prior(2, 1, "household", 0.0)
    g.prior(1, 3, "workplace", 0.0)
    g.apply(1, 2, "helped_by", 30.0)
    g.apply(1, 3, "attacked_by", 40.0)
    g.apply(3, 1, "saw_help", 50.0)
    before = _dump(g)
    back = RelationshipGraph.from_state(json.loads(json.dumps(g.to_state())))
    assert _dump(back) == before
    assert sorted(back.rels) == sorted(g.rels)
    for k, r in g.rels.items():
        assert back.rels[k].to_dict() == r.to_dict()
    # a restored graph keeps applying rules onto the restored values
    back.apply(1, 2, "worked_beside", 60.0)
    assert back.get(1, 2).familiarity > g.get(1, 2).familiarity


def test_the_state_is_json_clean_and_sorted():
    g = RelationshipGraph()
    for a, b in ((3, 1), (1, 2), (2, 3), (1, 1)):
        g.apply(a, b, "met", 0.0)
    state = g.to_state()
    assert json.loads(json.dumps(state)) == state
    keys = [(r["owner"], r["other"]) for r in state["rels"]]
    assert keys == sorted(keys)
    assert (1, 1) not in keys


def test_a_relationship_row_is_rounded_and_complete():
    r = Relationship(1, 2, familiarity=0.123456789)
    d = r.to_dict()
    assert d["familiarity"] == 0.1235
    assert set(d) >= set(DIMS) | {"owner", "other", "interactions", "last_t", "origin"}
    assert Relationship.from_dict(d).to_dict() == d
    assert r.summary().startswith("trust=")     # trust 0.3 beats familiarity 0.12

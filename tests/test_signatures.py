"""
Signature-scenario tests: every job has its defining collapse predicament, and
it fires through the schedule (on shift -> fires; off shift -> doesn't).

Run with:  python -m pytest tests/test_signatures.py -q
       or:  python tests/test_signatures.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.citizen import (
    default_catalog, default_cities, spawn_population, spawn_citizen,
    resolve_collapse_situation, CitizenSpawnCatalog,
)
from asphodel.signatures import default_signatures


CATALOG = default_catalog()
CITY = default_cities()["generic"]
HOME_ANCHORED = {"child", "retiree", "unemployed", "homemaker"}
NEW_ROLES = {"window_washer", "train_conductor", "corrections_officer", "landscaper"}


def _block_midpoint(schedule, activity):
    for e in schedule:
        if e.activity == activity:
            mid = (e.start_hour + e.end_hour) / 2.0
            return mid % 24.0
    return None


# --------------------------------------------------------------------------- #
# coverage
# --------------------------------------------------------------------------- #
def test_every_occupation_has_a_signature():
    for o in CATALOG.occupations:
        assert o.signature is not None, f"{o.name} has no signature"
        assert o.signature.trigger in ("on_shift", "on_site", "anytime")
        assert o.signature.situation and o.signature.dilemma
        assert o.signature.tags, f"{o.name} signature has no tags"


def test_new_signature_roles_present():
    names = {o.name for o in CATALOG.occupations}
    assert NEW_ROLES <= names
    sigs = default_signatures()
    assert NEW_ROLES <= set(sigs)


# --------------------------------------------------------------------------- #
# firing through the schedule
# --------------------------------------------------------------------------- #
def test_signature_fires_when_on_shift():
    pop = spawn_population(CITY, CATALOG, n=200, seed=1)
    checked = 0
    for c in pop:
        sig = default_signatures().get(c.occupation)
        if sig is None or sig.trigger == "anytime":
            continue
        work_mid = _block_midpoint(c.schedule, "work")
        if work_mid is None:
            continue
        sit = resolve_collapse_situation(c, collapse_hour=work_mid, ambient_prob=0.0)
        assert sit.fired, f"{c.occupation} on shift did not fire"
        assert sit.on_duty and sit.tags
        # On-hand inventory is folded into the assets.
        assert any(a.startswith("on you:") for a in sit.assets)
        checked += 1
    assert checked > 10, "not enough on-shift cases exercised"


def test_signature_does_not_fire_off_shift():
    pop = spawn_population(CITY, CATALOG, n=200, seed=2)
    checked = 0
    for c in pop:
        sig = default_signatures().get(c.occupation)
        if sig is None or sig.trigger == "anytime":
            continue
        sleep_mid = _block_midpoint(c.schedule, "sleep")
        if sleep_mid is None:
            continue
        sit = resolve_collapse_situation(c, collapse_hour=sleep_mid, ambient_prob=0.0)
        assert not sit.fired
        assert sit.title == "Off-shift when it hit"
        checked += 1
    assert checked > 10


def test_home_anchored_signatures_fire_anytime():
    pop = spawn_population(CITY, CATALOG, n=300, seed=3)
    seen = set()
    for c in pop:
        if c.occupation not in HOME_ANCHORED:
            continue
        for hour in (2.0, 9.0, 14.0, 20.0):
            assert resolve_collapse_situation(c, collapse_hour=hour, ambient_prob=0.0).fired
        seen.add(c.occupation)
    assert seen, "no home-anchored citizens spawned"


def test_collapse_hour_shifts_who_fires():
    """A night-shift worker fires at night and is off-duty mid-afternoon."""
    pop = spawn_population(CITY, CATALOG, n=300, seed=4)
    night = next(c for c in pop
                 if c.shift == "night" and _block_midpoint(c.schedule, "work") is not None
                 and default_signatures()[c.occupation].trigger != "anytime")
    work_mid = _block_midpoint(night.schedule, "work")
    assert resolve_collapse_situation(night, collapse_hour=work_mid, ambient_prob=0.0).fired
    # 14:00 a night worker is asleep/off -> their signature should not fire.
    assert not resolve_collapse_situation(night, collapse_hour=14.0, ambient_prob=0.0).fired


# --------------------------------------------------------------------------- #
# determinism + serialisation
# --------------------------------------------------------------------------- #
def test_resolution_is_pure():
    c = spawn_citizen(CITY, CATALOG, seed=10)
    a = resolve_collapse_situation(c, 14.0)
    b = resolve_collapse_situation(c, 14.0)
    assert a == b


def test_signature_survives_yaml_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "catalog.yaml")
        CATALOG.to_yaml(path)
        back = CitizenSpawnCatalog.from_yaml(path)
    before = {o.name: o.signature for o in CATALOG.occupations}
    for o in back.occupations:
        assert o.signature is not None
        assert o.signature.name == before[o.name].name
        assert o.signature.tags == before[o.name].tags


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

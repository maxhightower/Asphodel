"""
Environmental-event tests: the place-driven hazard layer and how it slots into
resolve_collapse_situation alongside signatures / travel / aerial.

Run with:  python -m pytest tests/test_environments.py -q
       or:  python tests/test_environments.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.environments import (
    default_environment_events, select_environment_event, ENVIRONMENTS,
)
from asphodel.citizen import (
    default_catalog, default_cities, resolve_world,
    spawn_population_in_world, resolve_collapse_situation,
)


CATALOG = default_catalog()


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
def test_catalogue_well_formed():
    evs = default_environment_events()
    assert len(evs) >= 20
    for e in evs:
        assert e.situation and e.dilemma and e.tags
        assert e.environments and all(env in ENVIRONMENTS for env in e.environments)
        assert e.severity >= 1


def test_every_environment_has_at_least_one_event():
    rng = np.random.default_rng(0)
    for env in ENVIRONMENTS:
        ev = select_environment_event(rng, env)
        assert ev is not None, f"no event for environment {env}"
        assert env in ev.environments


def test_selection_is_deterministic():
    a = select_environment_event(np.random.default_rng(3), "industrial")
    b = select_environment_event(np.random.default_rng(3), "industrial")
    assert a.name == b.name


def test_unknown_environment_returns_none():
    assert select_environment_event(np.random.default_rng(0), "road") is None


# --------------------------------------------------------------------------- #
# integration with resolve_collapse_situation
# --------------------------------------------------------------------------- #
def test_environment_is_always_reported():
    cw = resolve_world(default_cities()["harbor"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=200, seed=0)
    for c in pop:
        for h in (2.0, 9.0, 14.0):
            sit = resolve_collapse_situation(c, h, world=cw)
            assert sit.environment, "environment not set"


def test_ambient_can_override_and_is_disable_able():
    cw = resolve_world(default_cities()["harbor"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=300, seed=0)
    # Forced on: at home, the residence's own hazard fires.
    fired_env = 0
    for c in pop:
        sit = resolve_collapse_situation(c, 3.0, world=cw, ambient_prob=1.0)
        if sit.kind == "environment":
            fired_env += 1
            assert sit.tags
    assert fired_env > 0
    # Disabled: a sleeping citizen is plainly off-duty, never an env event.
    for c in pop[:50]:
        sit = resolve_collapse_situation(c, 3.0, world=cw, ambient_prob=0.0,
                                         aerial_prob=0.0)
        assert sit.kind != "environment"


def test_environment_variety_across_population():
    """Across a harbor population and the day, many distinct environments and
    environment-events show up -- the layer is broad, not one-note."""
    cw = resolve_world(default_cities()["harbor"], seed=0)
    pop = spawn_population_in_world(cw, CATALOG, n=1500, seed=0)
    envs, titles = Counter(), Counter()
    for c in pop:
        for h in (7.7, 11.0, 14.0, 21.0):
            sit = resolve_collapse_situation(c, h, world=cw, ambient_prob=1.0)
            envs[sit.environment] += 1
            if sit.kind == "environment":
                titles[sit.title] += 1
    # Harbor surfaces waterfront, high-rise, medical, retail, residential, ...
    assert len({"residential", "retail", "waterfront", "high_rise"} & set(envs)) >= 3
    assert len(titles) >= 8


def test_resolution_with_ambient_is_deterministic():
    cw = resolve_world(default_cities()["capital"], seed=0)
    c = spawn_population_in_world(cw, CATALOG, n=10, seed=1)[0]
    a = resolve_collapse_situation(c, 3.0, world=cw, ambient_prob=1.0)
    b = resolve_collapse_situation(c, 3.0, world=cw, ambient_prob=1.0)
    assert a == b


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

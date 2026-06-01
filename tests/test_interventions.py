"""
Phase 8 tests: player interventions through the World facade, and the macro
field effects they drive.

Run with:  python -m pytest tests/test_interventions.py -q
       or:  python tests/test_interventions.py

Each intervention is checked for its intended *directional* effect against a
no-intervention baseline (the model is deterministic from config+seed).
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, Simulation, MicroParams


def _base_cfg(n_days=60.0):
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = 6
    cfg.model.graph.grid_cols = 6
    cfg.n_days = n_days
    return cfg


def _run_sim(cfg, mutate=None, n_days=None):
    """Run a bare Simulation, optionally mutating intervention state first."""
    sim = Simulation(cfg)
    if mutate is not None:
        mutate(sim)
    n = int(round((n_days or cfg.n_days) / cfg.dt))
    for _ in range(n):
        sim.step()
    return sim


# --------------------------------------------------------------------------- #
# cordon: sealing the seed zone contains the outbreak
# --------------------------------------------------------------------------- #
def test_cordon_contains_outbreak():
    cfg = _base_cfg(n_days=60.0)
    seed = cfg.model.graph.grid_rows // 2 * cfg.model.graph.grid_cols + cfg.model.graph.grid_cols // 2
    base = _run_sim(cfg)
    cordoned = _run_sim(cfg, mutate=lambda s: s.cordoned.__setitem__(s.seed_zone, True))

    def nonseed_attack(sim):
        ever = sim.R + sim.D + sim.E + sim.Ia + sim.Is
        mask = np.ones(sim.Z, dtype=bool)
        mask[sim.seed_zone] = False
        return float(ever[mask].sum())

    assert nonseed_attack(cordoned) < 0.05 * nonseed_attack(base), \
        (nonseed_attack(cordoned), nonseed_attack(base))


# --------------------------------------------------------------------------- #
# shelter order: mandated sheltering cuts transmission -> fewer deaths
# --------------------------------------------------------------------------- #
def test_shelter_order_reduces_deaths():
    cfg = _base_cfg(n_days=90.0)
    base = _run_sim(cfg)
    sheltered = _run_sim(cfg, mutate=lambda s: s.mandated_shelter.__setitem__(slice(None), 0.85))
    assert float(sheltered.D.sum()) < float(base.D.sum()), (sheltered.D.sum(), base.D.sum())


# --------------------------------------------------------------------------- #
# broadcast: bypasses authority lag -> belief rises earlier
# --------------------------------------------------------------------------- #
def test_broadcast_raises_belief_early():
    cfg = _base_cfg(n_days=10.0)
    base = _run_sim(cfg, n_days=10.0)
    bcast = _run_sim(cfg, mutate=lambda s: setattr(s, "broadcast_signal", 1.0), n_days=10.0)
    assert float(bcast.belief.mean()) > float(base.belief.mean()) + 0.1, \
        (bcast.belief.mean(), base.belief.mean())


# --------------------------------------------------------------------------- #
# staffing allocation: props up infrastructure -> fewer utility failures
# --------------------------------------------------------------------------- #
def test_staffing_allocation_prevents_infra_failure():
    cfg = _base_cfg(n_days=70.0)
    base = _run_sim(cfg)
    supported = _run_sim(cfg, mutate=lambda s: s.staffing_support.__setitem__(slice(None), 1.0))
    base_fail = int((~base.water_ok).sum())
    assert int((~supported.water_ok).sum()) < base_fail or base_fail == 0
    # With full support nothing should fail at the end.
    assert bool(supported.water_ok.all())


# --------------------------------------------------------------------------- #
# the World.intervene API: state is set and lifted
# --------------------------------------------------------------------------- #
def test_world_intervene_api():
    w = World(_base_cfg(), micro_params=MicroParams())
    w.intervene("cordon", zones=[3, 4])
    assert w.sim.cordoned[3] and w.sim.cordoned[4]
    w.intervene("lift_cordon", zones=3)
    assert not w.sim.cordoned[3] and w.sim.cordoned[4]

    w.intervene("shelter_order", zones=[5], strength=0.7)
    assert np.isclose(w.sim.mandated_shelter[5], 0.7)
    w.intervene("lift_shelter_order", zones=[5])
    assert np.isclose(w.sim.mandated_shelter[5], 0.0)

    w.intervene("broadcast", level=0.8)
    assert np.isclose(w.sim.broadcast_signal, 0.8)
    w.intervene("stop_broadcast")
    assert np.isclose(w.sim.broadcast_signal, 0.0)

    w.intervene("allocate_staffing", zones=None, amount=0.5)  # all zones
    assert np.allclose(w.sim.staffing_support, 0.5)

    try:
        w.intervene("nonsense")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown intervention should raise")


# --------------------------------------------------------------------------- #
# agent shelter couples to the live macro belief / shelter order
# --------------------------------------------------------------------------- #
def test_agent_shelter_couples_to_order():
    cfg = _base_cfg(n_days=10.0)
    seed = cfg.model.graph.grid_rows // 2 * cfg.model.graph.grid_cols + cfg.model.graph.grid_cols // 2
    w = World(cfg, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                            shelter_effectiveness=0.75), seed=0)
    w.set_focus([seed])
    w.intervene("shelter_order", zones=[seed], strength=0.6)
    w.step()
    zone = w.promoted[seed]
    # The promoted zone's agents must now reflect the mandated shelter fraction.
    assert zone.params.shelter_fraction >= 0.6 - 1e-9, zone.params.shelter_fraction
    assert int(zone.sheltered.sum()) > 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

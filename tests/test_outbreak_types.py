"""
Tests for the outbreak config *types*: the zombie pathogen archetypes and the
reanimation mechanic they drive.  Run with:  python -m pytest -q
(or  python tests/test_outbreak_types.py  for a dependency-free smoke run).

These assert that:
  * every archetype instantiates into a valid genome;
  * the reanimation pathway is inert by default (so ordinary diseases are
    unchanged) but produces a persistent undead reservoir when switched on;
  * mass is conserved once the undead (U) and pending-corpse (C) compartments
    are counted;
  * the transmission route actually changes how far infection rides the graph;
  * archetypes round-trip through YAML, including the terse ``archetype:`` form.
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import ScenarioConfig, PathogenGenome, GENOME_ARCHETYPES, run_scenario


# Simulation attribute names for every compartment including the undead
# pathway; mass is conserved across these.
ALL_COMPARTMENTS = ("S", "E", "Ia", "Is", "R", "D", "U", "C")
# The same compartments as the per-tick DataFrame names it.
FRAME_COMPARTMENTS = ("S", "E", "I_asymp", "I_symp", "R", "D", "U", "corpses")


def _total_people(sim) -> float:
    return float(sum(getattr(sim, n).sum() for n in ALL_COMPARTMENTS))


def _shambler_cfg(n_days: float = 120.0) -> ScenarioConfig:
    cfg = ScenarioConfig(name="shambler")
    cfg.genome = PathogenGenome.classic_shambler()
    cfg.n_days = n_days
    return cfg


# --- archetype library -----------------------------------------------------
def test_all_archetypes_instantiate():
    for name, factory in GENOME_ARCHETYPES.items():
        g = factory()
        assert isinstance(g, PathogenGenome)
        assert g.beta() > 0.0
        assert 0.0 <= g.effective_reanimation_fraction() <= 1.0
        assert g.transmission_route in PathogenGenome._ROUTE_MIXING
        # from_archetype must agree with the factory.
        assert PathogenGenome.from_archetype(name) == g


def test_unknown_archetype_raises():
    try:
        PathogenGenome.from_archetype("brain_slug")
    except ValueError as e:
        assert "brain_slug" in str(e)
    else:
        raise AssertionError("expected ValueError for an unknown archetype")


def test_turn_on_death_forces_full_reanimation():
    g = PathogenGenome.necro_latent()
    assert g.turn_on_death is True
    assert g.effective_reanimation_fraction() == 1.0
    # Even with a contradictory low fraction, turn_on_death wins.
    g2 = PathogenGenome(reanimation_fraction=0.1, turn_on_death=True)
    assert g2.effective_reanimation_fraction() == 1.0


def test_reanimation_fraction_clamped():
    assert PathogenGenome(reanimation_fraction=-0.5).effective_reanimation_fraction() == 0.0
    assert PathogenGenome(reanimation_fraction=2.0).effective_reanimation_fraction() == 1.0


def test_route_mixing_ordering():
    f = lambda r: PathogenGenome(transmission_route=r).route_mixing_multiplier()
    assert f("airborne") > f("contact") >= f("fluid") > f("bite")
    # An unknown route falls back to the neutral contact multiplier.
    assert PathogenGenome(transmission_route="telepathic").route_mixing_multiplier() == f("contact")


# --- reanimation dynamics --------------------------------------------------
def test_default_genome_has_no_undead():
    """An ordinary disease (the default) must leave the undead pathway inert."""
    res = run_scenario(ScenarioConfig(), record_belief=False)
    assert res.frame["U"].max() == 0.0
    assert res.frame["corpses"].max() == 0.0
    assert res.sim.U.sum() == 0.0 and res.sim.C.sum() == 0.0


def test_reanimating_strain_raises_undead():
    res = run_scenario(_shambler_cfg(), record_belief=False)
    assert res.frame["U"].iloc[-1] > 0.0
    assert res.sim.U.sum() > 0.0


def test_undead_reservoir_never_shrinks():
    """The undead don't recover -- U is a monotonically growing reservoir."""
    res = run_scenario(_shambler_cfg(), record_belief=False)
    assert np.all(np.diff(res.frame["U"].values) >= -1e-9)


def test_rage_virus_stays_finite():
    """The rage strain's seconds-to-turn periods make the per-tick E->I rate
    exceed 1; the engine must clamp rather than blow up into NaNs."""
    cfg = ScenarioConfig(name="rage")
    cfg.genome = PathogenGenome.rage_virus()
    cfg.n_days = 90.0
    res = run_scenario(cfg, record_belief=False)
    assert np.isfinite(res.frame[list(FRAME_COMPARTMENTS)].values).all()
    assert res.frame["U"].max() == 0.0    # no reanimation pathway for rage
    expected = cfg.model.graph.population_per_zone * res.graph.n_zones
    assert abs(_total_people(res.sim) - expected) < 1e-6 * expected


def test_mass_conservation_with_undead():
    cfg = _shambler_cfg()
    res = run_scenario(cfg, record_belief=False)
    expected = cfg.model.graph.population_per_zone * res.graph.n_zones
    assert abs(_total_people(res.sim) - expected) < 1e-6 * expected


def test_no_negative_compartments_with_undead():
    res = run_scenario(_shambler_cfg(), record_belief=False)
    for name in ALL_COMPARTMENTS:
        arr = getattr(res.sim, name)
        assert (arr >= -1e-9).all(), f"{name} went negative"


def test_reanimation_delay_passes_through_corpses():
    """A rise delay should park bodies in C before they surface as U."""
    cfg = ScenarioConfig(name="delayed")
    cfg.genome = PathogenGenome(
        R0=3.0, incubation_period=2.0, infectious_period=4.0,
        mortality_fraction=0.5, reanimation_fraction=1.0, reanimation_delay=5.0,
    )
    res = run_scenario(cfg, record_belief=False)
    assert res.frame["corpses"].max() > 0.0   # bodies waited before rising
    assert res.frame["U"].iloc[-1] > 0.0       # but they did eventually rise


# --- transmission route changes spread -------------------------------------
def test_airborne_spreads_further_than_bite():
    """Holding everything else equal, an airborne route should infect more of
    the grid by a fixed horizon than a purely local bite route."""
    base = ScenarioConfig(name="route")
    base.genome = PathogenGenome(R0=2.5, mortality_fraction=0.1)
    base.n_days = 60.0

    bite = copy.deepcopy(base); bite.genome.transmission_route = "bite"
    air = copy.deepcopy(base); air.genome.transmission_route = "airborne"

    rb = run_scenario(bite, record_belief=False)
    ra = run_scenario(air, record_belief=False)

    def ever_infected(res):
        last = res.frame.iloc[-1]
        return last["R"] + last["D"] + last["U"]

    assert ever_infected(ra) > ever_infected(rb)


# --- YAML round-tripping ---------------------------------------------------
def test_yaml_full_roundtrip_preserves_zombie_fields():
    cfg = _shambler_cfg()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.yaml")
        cfg.to_yaml(path)
        back = ScenarioConfig.from_yaml(path)
    assert back.genome == cfg.genome


def test_yaml_terse_archetype_forms():
    # A bare archetype name.
    cfg = ScenarioConfig.from_dict({"name": "x", "genome": "rage_virus"})
    assert cfg.genome == PathogenGenome.rage_virus()

    # An archetype with explicit field overrides.
    cfg2 = ScenarioConfig.from_dict(
        {"name": "y", "genome": {"archetype": "cordyceps", "R0": 9.9}}
    )
    assert cfg2.genome.R0 == 9.9
    # ...with the rest of the archetype intact.
    assert cfg2.genome.transmission_route == "airborne"
    assert cfg2.genome.reanimation_fraction == PathogenGenome.cordyceps().reanimation_fraction


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

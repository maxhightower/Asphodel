"""
Phase 4b tests: the Scenario object, consolidated metrics, and the engine.

Covers:

* Scenario YAML round-trips losslessly (composing the existing config objects);
* the consolidated ``metrics`` module reproduces the exact numbers the Phase 3a
  ``RunResult`` methods report (the consolidation changed no values);
* ``Scenario.to_scenario_config`` reproduces a plain macro run bit-for-bit;
* the engine's ensemble + sweep are deterministic and reproducible;
* the location ``population_scale`` threads through to the macro population.

Run with:  python -m pytest tests/test_scenario.py -q
       or:  python tests/test_scenario.py
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import (
    Scenario, ScenarioConfig, run_scenario, run_single, run_ensemble,
    build_sweep, run_sweep, get_location_profile,
)
from asphodel import metrics


# --------------------------------------------------------------------------- #
# Scenario YAML round-trip
# --------------------------------------------------------------------------- #
def test_scenario_yaml_round_trip():
    sc = Scenario()
    sc.metadata.name = "rt"
    sc.metadata.description = "round-trip test"
    sc.genome.incubation_period = 9.0
    sc.model_params.belief.w_social = 0.77
    sc.start_date = "2021-07-04"
    sc.location_profile = get_location_profile("houston")
    sc.micro_params.n_agents = 1234
    sc.flux_params.rate = 0.2
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sc.yaml")
        sc.to_yaml(path)
        back = Scenario.from_yaml(path)
    assert back.metadata.name == "rt"
    assert back.metadata.description == "round-trip test"
    assert back.genome.incubation_period == 9.0
    assert back.model_params.belief.w_social == 0.77
    assert back.start_date == "2021-07-04"
    assert back.start_date_obj.year == 2021
    assert back.location_profile.name == "houston"
    assert back.location_profile.climate_zone == "humid_subtropical"
    assert back.micro_params.n_agents == 1234
    assert back.flux_params.rate == 0.2


# --------------------------------------------------------------------------- #
# metrics consolidation changed no numbers
# --------------------------------------------------------------------------- #
def test_metrics_match_runresult_methods():
    res = run_scenario(ScenarioConfig(), record_belief=False)
    m = metrics.macro_metrics_from_result(res)
    assert m["silent_phase_days"] == res.panic_day(0.1)
    assert m["day_50pct_panic"] == res.panic_day(0.5)
    assert m["day_90pct_panic"] == res.panic_day(0.9)
    assert m["peak_infection_day"] == res.peak_infection_day()
    assert m["authority_alarm_day"] == res.authority_alarm_day()
    assert m["total_dead"] == float(res.frame["D"].iloc[-1])


# --------------------------------------------------------------------------- #
# Scenario lowers to an equivalent macro run
# --------------------------------------------------------------------------- #
def test_scenario_matches_plain_macro_run():
    sc = Scenario()
    res_engine = run_single(sc, record_belief=False)
    res_plain = run_scenario(ScenarioConfig(), record_belief=False)
    assert np.allclose(res_engine.frame.values, res_plain.frame.values)


def test_from_scenario_config_equivalent():
    cfg = ScenarioConfig()
    cfg.model.belief.w_social = 0.9
    sc = Scenario.from_scenario_config(cfg)
    res_engine = run_single(sc, record_belief=False)
    res_plain = run_scenario(cfg, record_belief=False)
    assert np.allclose(res_engine.frame.values, res_plain.frame.values)


# --------------------------------------------------------------------------- #
# engine determinism / reproducibility
# --------------------------------------------------------------------------- #
def test_sweep_is_deterministic_and_tidy():
    base = Scenario()
    base.metadata.name = "wsweep"
    axes = {"model_params.belief.w_social": [0.6, 0.8, 1.0]}
    df1 = run_sweep(build_sweep(base, axes), seeds=[0, 1])
    df2 = run_sweep(build_sweep(base, axes), seeds=[0, 1])
    # tidy: one row per (scenario, seed); axis + metric columns present.
    assert len(df1) == 3 * 2
    assert "w_social" in df1.columns
    assert "silent_phase_days" in df1.columns
    assert "seed" in df1.columns
    # reproducible
    assert df1.equals(df2)


def test_ensemble_summary_shape():
    sc = Scenario()
    ens = run_ensemble(sc, seeds=[0, 1, 2])
    assert len(ens.per_run_metrics) == 3
    s = ens.summary["silent_phase_days"]
    assert "mean" in s and "median" in s and "p50" in s
    # events are off by default, so all seeds are identical (std == 0).
    assert s["std"] == 0.0


# --------------------------------------------------------------------------- #
# location population scale threads through
# --------------------------------------------------------------------------- #
def test_location_population_scale():
    sc = Scenario()
    sc.location_profile = get_location_profile("houston")
    sc.location_profile.population_scale = 2.0
    cfg = sc.to_scenario_config()
    assert cfg.model.graph.population_per_zone == 2.0 * sc.model_params.graph.population_per_zone


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

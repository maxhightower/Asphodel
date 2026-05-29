"""
The macro single-zone reference: the trusted ground truth the micro tier must
reproduce.

We do NOT reimplement the disease model -- we reuse the existing macro
``Simulation`` (model.py) configured as a single passive, closed zone:

* a 1x1 zone graph with zero inter-zone mobility (no flux out),
* infrastructure / authority / events disabled,
* behaviour neutralised (no sheltering, no fleeing),

so the macro update reduces to the pure single-zone SEIR difference equations
``new_E = beta * S * (Ia+Is)/living * dt`` with the genome's transition rates --
exactly the dynamics the proximity-based micro tier is calibrated against.
Belief is still integrated but is fully decoupled from infection in this
configuration, so it cannot perturb the curve.
"""

from __future__ import annotations

import copy

import numpy as np

from .config import (
    ScenarioConfig, PathogenGenome, ModelParams, GraphParams,
)
from .runner import run_scenario
from .micro import STATE_NAMES


def passive_macro_config(genome: PathogenGenome, n_agents: int, dt: float,
                         n_days: float, seed_exposed: int = 10) -> ScenarioConfig:
    """Build a ScenarioConfig for a single passive closed zone of ``n_agents``."""
    cfg = ScenarioConfig()
    cfg.name = "macro_passive"
    cfg.genome = copy.deepcopy(genome)
    cfg.dt = dt
    cfg.n_days = n_days
    cfg.seed_exposed = float(seed_exposed)
    cfg.seed_zone = 0

    g = GraphParams(grid_rows=1, grid_cols=1,
                    population_per_zone=float(n_agents), mobility=0.0)
    m = ModelParams(graph=g)
    # Disable every coupling that could change the transmission rate.
    m.infrastructure.enabled = False
    m.authority.enabled = False
    m.events.enabled = False
    m.behavior.max_shelter = 0.0          # nobody shelters -> beta unmodified
    m.behavior.max_flee_rate = 0.0        # single zone anyway, but be explicit
    m.belief.floor = 0.0
    cfg.model = m
    return cfg


def run_macro_reference(genome: PathogenGenome, n_agents: int, dt: float,
                        n_days: float, seed_exposed: int = 10) -> dict:
    """Run the passive single-zone macro and return per-tick compartment series
    on the same schema as ``micro.run_micro`` (day + one array per compartment)."""
    cfg = passive_macro_config(genome, n_agents, dt, n_days, seed_exposed)
    res = run_scenario(cfg, record_belief=False)
    df = res.frame
    # model.py column names: S, E, I_asymp, I_symp, R, D (+ day).
    colmap = {"S": "S", "E": "E", "Ia": "I_asymp", "Is": "I_symp",
              "R": "R", "D": "D"}
    out = {"day": np.concatenate([[0.0], df["day"].to_numpy()])}
    # Prepend the initial condition (tick 0) so it aligns with the micro series.
    n0 = float(n_agents)
    init = {"S": n0 - seed_exposed, "E": float(seed_exposed),
            "Ia": 0.0, "Is": 0.0, "R": 0.0, "D": 0.0}
    for name in STATE_NAMES:
        col = df[colmap[name]].to_numpy()
        out[name] = np.concatenate([[init[name]], col])
    return out

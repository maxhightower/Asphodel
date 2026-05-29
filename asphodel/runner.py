"""
Scenario runner: advance a Simulation for the configured horizon, collect the
per-tick aggregate records and per-zone belief snapshots, and export to CSV.

Also provides a small multi-seed helper so experiments can compare runs.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import os

import numpy as np
import pandas as pd

from .config import ScenarioConfig
from .model import Simulation


class RunResult:
    """Everything produced by one run of one scenario."""

    def __init__(self, config: ScenarioConfig, sim: Simulation,
                 frame: pd.DataFrame, belief_history: np.ndarray):
        self.config = config
        self.seed = config.seed
        self.sim = sim
        self.frame = frame                    # per-tick aggregate DataFrame
        self.belief_history = belief_history  # (n_ticks+1, Z) per-zone belief
        self.graph = sim.graph
        self.events_log = sim.events_log

    # -- derived metrics used by FINDINGS / experiments ----------------------
    def panic_day(self, threshold_zones: float = 0.5) -> float | None:
        """Day at which the fraction of zones in panic first crosses
        `threshold_zones` (the social tipping point).  None if it never does."""
        n_zones = self.graph.n_zones
        crossed = self.frame["n_panic"] >= threshold_zones * n_zones
        if not crossed.any():
            return None
        return float(self.frame.loc[crossed, "day"].iloc[0])

    def peak_infection_day(self) -> float:
        infectious = self.frame["I_asymp"] + self.frame["I_symp"]
        return float(self.frame["day"].iloc[int(infectious.values.argmax())])

    def authority_alarm_day(self, threshold: float = 0.5) -> float | None:
        crossed = self.frame["official_signal"] >= threshold
        if not crossed.any():
            return None
        return float(self.frame.loc[crossed, "day"].iloc[0])

    def to_csv(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.frame.to_csv(path, index=False)


def run_scenario(config: ScenarioConfig, record_belief: bool = True) -> RunResult:
    """Run one scenario end-to-end and return a RunResult."""
    sim = Simulation(config)
    rows = []
    n_ticks = config.n_ticks

    belief_hist = None
    if record_belief:
        belief_hist = np.empty((n_ticks + 1, sim.Z), dtype=float)
        belief_hist[0] = sim.belief.copy()

    for _ in range(n_ticks):
        rec = sim.step()
        rows.append(asdict(rec))
        if record_belief:
            belief_hist[sim.tick] = sim.belief.copy()

    frame = pd.DataFrame(rows)
    return RunResult(config, sim, frame, belief_hist)


def run_multi_seed(config: ScenarioConfig, seeds: list[int]) -> list[RunResult]:
    """Run the same scenario across several seeds for comparison."""
    results = []
    for s in seeds:
        results.append(run_scenario(replace(config, seed=s)))
    return results

"""Asphodel belief-cascade prototype (Phase 3a): a headless metapopulation
SEIR + belief-field simulation over an abstract zone graph.

The research question this package exists to answer: does a believable
Day -1 -> Day 0 -> collapse arc *emerge* from the belief dynamics, and can we
control it?
"""

from .config import (
    ScenarioConfig,
    PathogenGenome,
    ModelParams,
    GraphParams,
    BeliefParams,
    BehaviorParams,
    InfrastructureParams,
    AuthorityParams,
    EventParams,
)
from .graph import ZoneGraph
from .model import Simulation, TickRecord
from .runner import run_scenario, run_multi_seed, RunResult

__all__ = [
    "ScenarioConfig",
    "PathogenGenome",
    "ModelParams",
    "GraphParams",
    "BeliefParams",
    "BehaviorParams",
    "InfrastructureParams",
    "AuthorityParams",
    "EventParams",
    "ZoneGraph",
    "Simulation",
    "TickRecord",
    "run_scenario",
    "run_multi_seed",
    "RunResult",
]

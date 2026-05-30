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
from .config import MicroParams, HandoffParams
from .graph import ZoneGraph
from .model import Simulation, TickRecord
from .runner import run_scenario, run_multi_seed, RunResult

# --- Phase 4a: macro <-> micro (agent) tier --------------------------------
from .micro import AgentZone, run_micro, run_micro_ensemble, STATE_NAMES
from .macro_ref import run_macro_reference, passive_macro_config
from .calibration import calibrate, agreement_metrics, passes
from .handoff import promote, demote, round_trip, largest_remainder_counts

# --- Phase 4b: scenario engine, consolidated metrics, inter-zone flux -------
from . import metrics
from .scenario import (
    Scenario, ScenarioMetadata, LocationProfile, FluxParams, TerminationParams,
    get_location_profile, LOCATION_PROFILES,
)
from .episodes import (
    run_episodes, macro_episode, micro_episode,
    EpisodeResult, EpisodesResult,
)
from .engine import (
    run_single, run_ensemble, run_sweep, build_sweep, set_path,
    EnsembleResult, export_table, dump_sweep_spec,
)
from .flux import MicroFluxBlock, promote_block

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
    "MicroParams",
    "HandoffParams",
    "ZoneGraph",
    "Simulation",
    "TickRecord",
    "run_scenario",
    "run_multi_seed",
    "RunResult",
    # Phase 4a
    "AgentZone",
    "run_micro",
    "run_micro_ensemble",
    "STATE_NAMES",
    "run_macro_reference",
    "passive_macro_config",
    "calibrate",
    "agreement_metrics",
    "passes",
    "promote",
    "demote",
    "round_trip",
    "largest_remainder_counts",
    # Phase 4b
    "metrics",
    "Scenario",
    "ScenarioMetadata",
    "LocationProfile",
    "FluxParams",
    "TerminationParams",
    "get_location_profile",
    "LOCATION_PROFILES",
    "run_episodes",
    "macro_episode",
    "micro_episode",
    "EpisodeResult",
    "EpisodesResult",
    "run_single",
    "run_ensemble",
    "run_sweep",
    "build_sweep",
    "set_path",
    "EnsembleResult",
    "export_table",
    "dump_sweep_spec",
    "MicroFluxBlock",
    "promote_block",
]

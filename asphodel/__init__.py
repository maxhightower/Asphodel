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

# --- Phase 5: orchestrator (the engine facade) -----------------------------
from .orchestrator import World, WorldTick

# --- Phase 11 / M2: NPC identity + schedule activity -----------------------
from . import npc
from .npc import ACTIVITY_NAMES, activity_code, activity_name, activity_at_hour

# --- Citizen spawn: the possibility space a player can be dropped into ------
from .citizen import (
    AgeBand,
    Occupation,
    District,
    ScheduleEntry,
    SpawnParams,
    CitizenSpawnCatalog,
    CityProfile,
    CitizenProfile,
    spawn_citizen,
    spawn_population,
    default_catalog,
    default_cities,
    # World-resolved spawn (real buildings on a real street map)
    CityWorld,
    resolve_world,
    spawn_citizen_in_world,
    spawn_population_in_world,
    # Signature scenarios (the collapse-moment predicament per occupation)
    CollapseSituation,
    resolve_collapse_situation,
)
from .signatures import SignatureScenario, default_signatures
from .travel_events import (
    TravelEvent, default_travel_events, select_travel_event,
    default_aerial_events, select_aerial_event,
)
from .environments import (
    EnvironmentEvent, default_environment_events, select_environment_event,
    ENVIRONMENTS,
)

# --- Vehicles & traffic: travel modes, road network, congestion -------------
from .vehicles import (
    VehicleSpec,
    VEHICLES,
    TrafficParams,
    Trip,
    RoadNetwork,
    TrafficResult,
    choose_commute,
    work_vehicle_for,
    assign_traffic,
    build_commute_trips,
    congestion_report,
)

# --- Game time: real seconds <-> in-game clock <-> sim ticks, PZ-style pacing -
from .gametime import (
    TimeScale,
    default_timescale,
    schedule_playback,
    block_real_seconds,
)

# --- The spatial world a city resolves into (streets + buildings + interiors) -
from .world import (
    Building,
    Interior,
    Room,
    StreetMap,
    OSMSource,
    SynthCitySpec,
    InteriorParams,
    load_osm,
    synthesize_city,
    generate_interior,
    category_from_osm_tags,
)

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
    # Phase 5
    "World",
    "WorldTick",
    # Citizen spawn
    "AgeBand",
    "Occupation",
    "District",
    "ScheduleEntry",
    "SpawnParams",
    "CitizenSpawnCatalog",
    "CityProfile",
    "CitizenProfile",
    "spawn_citizen",
    "spawn_population",
    "default_catalog",
    "default_cities",
    "CityWorld",
    "resolve_world",
    "spawn_citizen_in_world",
    "spawn_population_in_world",
    # Signature scenarios
    "SignatureScenario",
    "default_signatures",
    "CollapseSituation",
    "resolve_collapse_situation",
    "TravelEvent",
    "default_travel_events",
    "select_travel_event",
    "default_aerial_events",
    "select_aerial_event",
    "EnvironmentEvent",
    "default_environment_events",
    "select_environment_event",
    "ENVIRONMENTS",
    # Vehicles & traffic
    "VehicleSpec",
    "VEHICLES",
    "TrafficParams",
    "Trip",
    "RoadNetwork",
    "TrafficResult",
    "choose_commute",
    "work_vehicle_for",
    "assign_traffic",
    "build_commute_trips",
    "congestion_report",
    # Game time
    "TimeScale",
    "default_timescale",
    "schedule_playback",
    "block_real_seconds",
    # World layer
    "Building",
    "Interior",
    "Room",
    "StreetMap",
    "OSMSource",
    "SynthCitySpec",
    "InteriorParams",
    "load_osm",
    "synthesize_city",
    "generate_interior",
    "category_from_osm_tags",
]

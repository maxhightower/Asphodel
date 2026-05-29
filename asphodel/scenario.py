"""
The Scenario object (Phase 4b): a full run expressed as data.

A *scenario* is the identity discussed in the design --
``(genome x start_date x location x params x seed)`` -- made real as a single
round-trippable config object.  It does **not** invent a parallel config system:
it *composes* the existing Phase 3a / 4a dataclasses

    PathogenGenome, ModelParams (incl. GraphParams = the zone graph),
    MicroParams, HandoffParams

and adds the run-level fields the engine and later phases need:

    * ``start_date``      -- an in-world calendar date for the outbreak start.
                             Carried + recorded this phase (a scenario axis);
                             it does not yet drive weather/disasters.  Plumbed
                             now so the events phase plugs in without reshaping.
    * ``location_profile``-- a named location (``generic`` / stub ``houston``)
                             holding location-level parameters (population scale
                             + climatology placeholders), threaded through now,
                             full behaviour later.
    * ``flux_params``     -- Phase 4b inter-zone micro flux settings (rate &
                             direction derived from the macro mobility weights).
    * ``metadata``        -- name / description / notes.
    * ``seed`` + run settings (``dt``, ``n_days``, ``seed_zone``,
      ``seed_exposed``) -- the same run settings the macro engine already takes.

The bridge to the frozen macro engine is :meth:`Scenario.to_scenario_config`,
which builds the existing :class:`ScenarioConfig` that ``run_scenario`` consumes
**unchanged** -- so wrapping a scenario costs nothing in the validated core.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional

import yaml

from .config import (
    PathogenGenome, ModelParams, GraphParams, BeliefParams, BehaviorParams,
    InfrastructureParams, AuthorityParams, EventParams,
    MicroParams, HandoffParams, ScenarioConfig,
)


# --------------------------------------------------------------------------- #
# new run-level config objects
# --------------------------------------------------------------------------- #
@dataclass
class LocationProfile:
    """A named location with location-level parameters.

    For Phase 4b this carries only ``population_scale`` (a multiplier on the
    per-zone population) plus placeholders for the climatology hooks the events
    phase will use.  ``climate_zone`` / ``latitude`` / ``longitude`` are recorded
    but do not yet drive any dynamics -- they are the documented extension point
    so start_date x location can later select weather/disaster behaviour.
    """

    name: str = "generic"
    population_scale: float = 1.0          # multiplies population_per_zone
    # --- climatology hooks (recorded only this phase; events phase consumes) --
    climate_zone: Optional[str] = None     # e.g. "humid_subtropical" (houston)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    notes: str = ""


# A tiny registry of starter profiles.  "generic" is the neutral default;
# "houston" is the stub the brief asks for (values are placeholders -- only
# population_scale bites this phase).
LOCATION_PROFILES: dict[str, LocationProfile] = {
    "generic": LocationProfile(name="generic", population_scale=1.0),
    "houston": LocationProfile(
        name="houston", population_scale=1.0,
        climate_zone="humid_subtropical", latitude=29.76, longitude=-95.37,
        notes="Stub profile: climatology hooks recorded, not yet active "
              "(reserved for the events phase: hurricanes, heat, freezes).",
    ),
}


def get_location_profile(name: str) -> LocationProfile:
    """Look up a starter profile by name (falls back to a generic named copy)."""
    if name in LOCATION_PROFILES:
        # return a copy so callers can't mutate the registry
        return LocationProfile(**asdict(LOCATION_PROFILES[name]))
    return LocationProfile(name=name)


@dataclass
class FluxParams:
    """Inter-zone micro-flux settings (Phase 4b).

    When several adjacent zones are promoted to the agent tier simultaneously,
    agents migrate between them.  The migration is layered *on top of* the
    unchanged single-zone ``AgentZone`` dynamics, so with ``rate == 0`` (or a
    single promoted zone) the behaviour is bit-identical to Phase 4a.

    * **Direction** always follows the macro mobility weights
      (``ZoneGraph.mix``), so a migrating agent picks its destination neighbour
      with exactly the macro's relative mixing probabilities.
    * **Magnitude** (the per-day rate an agent leaves its zone) defaults to the
      macro ``GraphParams.mobility`` so micro inter-zone movement reproduces the
      macro mobility in expectation; set ``rate`` to override explicitly.
    """

    rate: Optional[float] = None       # per-day per-agent emigration rate;
    #                                    None => use GraphParams.mobility
    enabled: bool = True               # master switch for inter-zone flux


@dataclass
class ScenarioMetadata:
    """Human-facing identity of a scenario."""

    name: str = "scenario"
    description: str = ""
    notes: str = ""


# --------------------------------------------------------------------------- #
# the Scenario
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    """A full run as data: genome x start_date x location x params x seed.

    Composes the existing config dataclasses (no reimplementation) and adds the
    run-level fields.  Round-trips to YAML the same way ``ScenarioConfig`` does.
    """

    metadata: ScenarioMetadata = field(default_factory=ScenarioMetadata)

    # --- the disease and the macro coefficients (reused verbatim) -----------
    genome: PathogenGenome = field(default_factory=PathogenGenome)
    model_params: ModelParams = field(default_factory=ModelParams)

    # --- micro / handoff / flux (only bite for promoted-zone scenarios) -----
    micro_params: MicroParams = field(default_factory=MicroParams)
    handoff_params: HandoffParams = field(default_factory=HandoffParams)
    flux_params: FluxParams = field(default_factory=FluxParams)

    # --- the new scenario axes (carried/recorded this phase) ----------------
    start_date: str = "2020-01-01"     # in-world ISO calendar date (YYYY-MM-DD)
    location_profile: LocationProfile = field(default_factory=LocationProfile)

    # --- run settings (same meaning as ScenarioConfig) ----------------------
    seed: int = 0
    dt: float = 0.25
    n_days: float = 120.0
    seed_zone: Optional[int] = None
    seed_exposed: float = 50.0

    # ----------------------------------------------------------------- derived
    @property
    def n_ticks(self) -> int:
        return int(round(self.n_days / self.dt))

    @property
    def start_date_obj(self) -> date:
        """The start date parsed to a ``datetime.date`` (raises if malformed)."""
        return date.fromisoformat(self.start_date)

    def effective_population_per_zone(self) -> float:
        """Per-zone population after applying the location's population scale."""
        return (self.model_params.graph.population_per_zone
                * self.location_profile.population_scale)

    # ------------------------------------------------------- macro-engine bridge
    def to_scenario_config(self) -> ScenarioConfig:
        """Build the frozen-engine :class:`ScenarioConfig` this scenario means.

        The location's ``population_scale`` is folded into the per-zone
        population here (the only place a location parameter currently bites);
        everything else is passed straight through.  The macro engine therefore
        never has to know scenarios exist."""
        import copy
        model = copy.deepcopy(self.model_params)
        model.graph.population_per_zone = self.effective_population_per_zone()
        return ScenarioConfig(
            name=self.metadata.name,
            genome=copy.deepcopy(self.genome),
            model=model,
            dt=self.dt,
            n_days=self.n_days,
            seed=self.seed,
            seed_zone=self.seed_zone,
            seed_exposed=self.seed_exposed,
        )

    @classmethod
    def from_scenario_config(cls, cfg: ScenarioConfig, **overrides) -> "Scenario":
        """Lift an existing macro ``ScenarioConfig`` into a ``Scenario``.

        Lets the Phase 3a scenario YAMLs (and bespoke configs) be re-expressed
        as scenarios with default new fields; ``overrides`` may set any new
        run-level field (e.g. ``start_date``, ``location_profile``)."""
        import copy
        sc = cls(
            metadata=ScenarioMetadata(name=cfg.name),
            genome=copy.deepcopy(cfg.genome),
            model_params=copy.deepcopy(cfg.model),
            seed=cfg.seed,
            dt=cfg.dt,
            n_days=cfg.n_days,
            seed_zone=cfg.seed_zone,
            seed_exposed=cfg.seed_exposed,
        )
        for k, v in overrides.items():
            setattr(sc, k, v)
        return sc

    # -- YAML round-tripping (mirrors ScenarioConfig.to_yaml/from_yaml) ------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_yaml(self, path: str) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str) -> "Scenario":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Scenario":
        data = dict(data)
        metadata = ScenarioMetadata(**data.pop("metadata", {}) or {})
        genome = PathogenGenome(**data.pop("genome", {}) or {})
        model = _model_params_from_dict(data.pop("model_params", {}) or {})
        micro = MicroParams(**data.pop("micro_params", {}) or {})
        handoff = HandoffParams(**data.pop("handoff_params", {}) or {})
        flux = FluxParams(**data.pop("flux_params", {}) or {})
        loc = LocationProfile(**data.pop("location_profile", {}) or {})
        return cls(metadata=metadata, genome=genome, model_params=model,
                   micro_params=micro, handoff_params=handoff, flux_params=flux,
                   location_profile=loc, **data)


def _model_params_from_dict(d: dict) -> ModelParams:
    """Reconstruct a ModelParams from its nested-dict form (same logic as
    ScenarioConfig.from_dict, kept local so Scenario owns its parsing)."""
    return ModelParams(
        graph=GraphParams(**d.get("graph", {}) or {}),
        belief=BeliefParams(**d.get("belief", {}) or {}),
        behavior=BehaviorParams(**d.get("behavior", {}) or {}),
        infrastructure=InfrastructureParams(**d.get("infrastructure", {}) or {}),
        authority=AuthorityParams(**d.get("authority", {}) or {}),
        events=EventParams(**d.get("events", {}) or {}),
    )

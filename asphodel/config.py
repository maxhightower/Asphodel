"""
Configuration objects for the Asphodel belief-cascade prototype.

Everything that tunes the model lives here as plain dataclasses so the update
loop never hardcodes a coefficient.  A full scenario is three things bundled
together:

    ScenarioConfig
        ├── PathogenGenome   – the disease ("data, not code")
        ├── ModelParams      – graph, belief, behavior, infrastructure, authority
        └── run settings     – ticks, dt, seed, outbreak seeding

Configs round-trip to/from YAML so experiments can be described as files.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import yaml


# ---------------------------------------------------------------------------
# Pathogen genome
# ---------------------------------------------------------------------------
@dataclass
class PathogenGenome:
    """The disease, expressed as data.

    All time-valued fields are in *days*.  The compartment structure of the
    SEIR model is fixed (S, E, I_asymptomatic, I_symptomatic, R, D) but the
    rates between compartments are derived entirely from these numbers, so a
    new "genome" produces qualitatively different dynamics with no code change.
    """

    R0: float = 3.0                    # basic reproduction number
    incubation_period: float = 5.0     # mean time S->infectious (E duration).
    #                                    THE key dial: long incubation => long
    #                                    silent spread => the "Day -1" effect.
    infectious_period: float = 7.0     # mean time spent infectious before R/D
    asymptomatic_fraction: float = 0.4  # fraction that never become *visibly*
    #                                     symptomatic (invisible to belief)
    symptom_onset_delay: float = 2.0   # time infectious-but-hidden (I_a) before
    #                                    becoming visibly symptomatic (I_s)
    mortality_fraction: float = 0.02   # fraction of symptomatic cases that die

    def beta(self) -> float:
        """Transmission rate derived from R0 and the infectious period.

        For an SEIR model the basic reproduction number is R0 = beta /
        gamma, where gamma = 1 / infectious_period, so beta = R0 / infectious
        period.  This is the per-day rate at which one infectious person
        generates new exposures in a fully susceptible population.
        """
        return self.R0 / self.infectious_period


# ---------------------------------------------------------------------------
# Model parameters
# ---------------------------------------------------------------------------
@dataclass
class GraphParams:
    """Zone graph topology and inter-zone mobility.

    Topology is swappable via ``topology``: the disease + belief fields ride
    whatever weighted graph this produces, so changing it tests whether the
    cascade is a slow *diffusion wave* (grid) or a *synchronized tip*
    (small-world / hub commute).  Grid geometry (rows x cols) is always kept for
    visualisation; non-grid topologies just add long-range edges on top.
    """

    grid_rows: int = 8
    grid_cols: int = 8
    population_per_zone: float = 5000.0
    mobility: float = 0.15             # fraction of within-zone contact that is
    #                                    actually with neighbouring zones
    #                                    (carries infection along the graph)

    # -- topology -----------------------------------------------------------
    topology: str = "grid"             # "grid" | "small_world" | "commute"
    rewire_prob: float = 0.1           # small_world: P(rewire each grid edge to
    #                                    a random distant zone), Watts-Strogatz
    topology_seed: int = 0             # deterministic RNG for topology building
    n_hubs: int = 0                    # commute: number of high-population hubs
    #                                    every zone connects to (hub-and-spoke)
    hub_pop_multiplier: float = 5.0    # commute: hub population vs base


@dataclass
class BeliefParams:
    """The heart of the prototype: perceived-danger field dynamics.

    `belief` in each zone is in [0, 1] and is pulled toward a target that
    combines three (+1 infrastructure) input channels, each weighted.  It then
    moves toward that target with inertia, an asymmetric rise/decay rate, a
    per-tick step cap (propagation-speed cap) and a floor.
    """

    # Channel weights (the target is a weighted sum, then clamped to [0,1]).
    w_observation: float = 1.6   # local visible situation (I_symptomatic + D)
    w_social: float = 0.65       # pull toward neighbours' belief -> the cascade
    w_official: float = 0.5      # the authority's broadcast signal
    w_infrastructure: float = 0.4  # local services failing

    # Observation channel saturation: visible fraction at which the observation
    # signal reaches 0.5 (smaller => more sensitive to early visible cases).
    obs_half_saturation: float = 0.02
    # How strongly cumulative deaths feed the observation channel.  At 1.0 the
    # dead are remembered forever, which *ratchets* belief (it cannot fade while
    # bodies accumulate).  Lower it toward 0 to key belief on the *current*
    # symptomatic prevalence only -- which lets belief fade and can produce the
    # oscillation failure mode.
    obs_deaths_weight: float = 1.0

    # Inertia / dynamics.
    rise_rate: float = 0.9       # per-day rate of approach when target > belief
    decay_rate: float = 0.12     # per-day rate when target < belief (slow fade)
    max_step: float = 0.12       # propagation-speed cap: max |delta| per tick
    floor: float = 0.0           # belief never falls below this

    panic_threshold: float = 0.5  # a zone is "in panic" above this (reporting)


@dataclass
class BehaviorParams:
    """Belief -> aggregate behaviour multipliers (no individual agents)."""

    # Sheltering reduces within-zone contact (lowers effective beta).
    shelter_belief_low: float = 0.35   # belief at which sheltering begins
    shelter_belief_high: float = 0.7   # belief at which sheltering saturates
    max_shelter: float = 0.85          # max fraction of zone that shelters
    shelter_effectiveness: float = 0.75  # how much sheltering cuts contact

    # Fleeing moves population out along edges toward lower-belief zones.
    flee_belief_low: float = 0.5
    flee_belief_high: float = 0.85
    max_flee_rate: float = 0.06        # max fraction of pop leaving per day


@dataclass
class InfrastructureParams:
    """One coupled cascade: staffing -> power -> water -> belief / movement."""

    enabled: bool = True
    power_staffing_threshold: float = 0.45  # power fails below this staffing
    water_staffing_threshold: float = 0.35  # water fails below this staffing
    infra_alarm_power: float = 0.3     # belief-channel signal when power fails
    infra_alarm_water: float = 0.6     # belief-channel signal when water fails
    forced_flee_no_water: float = 0.04  # extra forced outflow/day with no water


@dataclass
class AuthorityParams:
    """A single global actor producing the lagged official signal."""

    enabled: bool = True
    observation_lag_days: float = 6.0   # authority sees a delayed world
    alarm_threshold: float = 0.008      # visible-fraction at which it reacts
    signal_rate: float = 0.5            # per-day rate the official signal moves
    # The authority only counts *visible* burden (symptomatic + dead), so in a
    # long-incubation scenario it necessarily reacts late -- emergent, not
    # scripted.


@dataclass
class EventParams:
    """Stretch goal: stochastic exogenous shocks + emergent transport hazard."""

    enabled: bool = False
    # Exogenous regional shock (Poisson process, prob ~ rate*dt per tick).
    shock_rate: float = 0.01           # expected shocks per day
    shock_belief_bump: float = 0.25    # belief added in struck region
    shock_infra_damage: float = 0.3    # staffing knocked out in struck region
    shock_radius: int = 1              # grid radius affected

    # Emergent transport hazard (logged numbers, no visuals).
    incident_coeff: float = 8.0        # incident rate ~ coeff * (outflow_frac)^2
    operator_incap_coeff: float = 1.0  # scales with infected fraction of fleers


@dataclass
class ModelParams:
    graph: GraphParams = field(default_factory=GraphParams)
    belief: BeliefParams = field(default_factory=BeliefParams)
    behavior: BehaviorParams = field(default_factory=BehaviorParams)
    infrastructure: InfrastructureParams = field(default_factory=InfrastructureParams)
    authority: AuthorityParams = field(default_factory=AuthorityParams)
    events: EventParams = field(default_factory=EventParams)


# ---------------------------------------------------------------------------
# Full scenario
# ---------------------------------------------------------------------------
@dataclass
class ScenarioConfig:
    name: str = "baseline"
    genome: PathogenGenome = field(default_factory=PathogenGenome)
    model: ModelParams = field(default_factory=ModelParams)

    # Run settings.
    dt: float = 0.25                   # tick length in days
    n_days: float = 120.0              # simulated horizon
    seed: int = 0                      # RNG seed (logged for reproducibility)

    # Outbreak seeding: how many initial exposed, and in which zone(s).
    seed_zone: Optional[int] = None    # None => centre of the grid
    seed_zones: Optional[list] = None  # multi-seed study: list of zone indices.
    #                                    Overrides seed_zone; seed_exposed is
    #                                    split evenly across the listed zones.
    seed_exposed: float = 50.0         # total initial E injected (across seeds)

    @property
    def n_ticks(self) -> int:
        return int(round(self.n_days / self.dt))

    # -- YAML round-tripping -------------------------------------------------
    def to_yaml(self, path: str) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(asdict(self), f, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str) -> "ScenarioConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "ScenarioConfig":
        data = dict(data)
        genome = PathogenGenome(**data.pop("genome", {}))
        model_d = data.pop("model", {}) or {}
        model = ModelParams(
            graph=GraphParams(**model_d.get("graph", {})),
            belief=BeliefParams(**model_d.get("belief", {})),
            behavior=BehaviorParams(**model_d.get("behavior", {})),
            infrastructure=InfrastructureParams(**model_d.get("infrastructure", {})),
            authority=AuthorityParams(**model_d.get("authority", {})),
            events=EventParams(**model_d.get("events", {})),
        )
        return cls(genome=genome, model=model, **data)


# ===========================================================================
# Phase 4a: macro <-> micro (agent) tier configuration
# ===========================================================================
# These dataclasses live alongside the genome but are independent of the macro
# ScenarioConfig above.  They configure the *single-zone agent simulation* that
# promotes one macro zone into discrete people moving in continuous 2D space,
# and the macro<->micro handoff.  The disease genome is reused unchanged -- the
# only thing that needs calibrating between the tiers is the transmission step.
@dataclass
class MicroParams:
    """Tunable parameters of the single-zone agent (micro) tier.

    The micro tier promotes one zone into ``n_agents`` discrete people wandering
    a continuous ``area_size`` x ``area_size`` square (a torus, so density is
    uniform and edge effects vanish).  Transmission is proximity-based: a
    susceptible within ``infection_radius`` of an infectious agent accrues
    infection hazard.  Every parameter here is exposed so experiments can sweep
    it; the per-contact ``contact_prob`` in particular is the calibration knob
    derived from the genome (see ``calibration.py``).
    """

    # Population & geometry.
    n_agents: int = 1000               # discrete people in the zone (the N sweep
    #                                    moves this; ~500-2000 is the useful band)
    area_size: float = 100.0           # side length L of the square zone (metres)

    # Proximity transmission.
    infection_radius: float = 2.0      # r: contact distance (metres).  Fixed as a
    #                                    modelling choice; contact_prob is then
    #                                    derived from the genome to hit macro beta.
    contact_prob: Optional[float] = None  # p: per-day infection hazard from ONE
    #                                    infectious agent within r.  None => derive
    #                                    analytically from the genome each tick.
    rel_infectious_asymp: float = 1.0  # infectiousness of I_a relative to I_s.
    #                                    The macro treats them equally (=1.0).

    # Movement / mixing (continuous random walk on the torus).
    well_mixed: bool = False           # if True, re-randomise all positions each
    #                                    tick (perfect mixing -> exact mass action;
    #                                    the idealised validation case).
    mixing_step_frac: float = 0.12     # per-tick Gaussian step std as a fraction
    #                                    of L (per axis).  Larger => better mixing,
    #                                    closer to the well-mixed mean field.

    # Calibration correction (empirical residual; 1.0 = pure analytic).
    contact_prob_correction: float = 1.0

    # Optional simple shelter behaviour (the forward-looking "active" check).
    # Applied consistently with the macro behaviour layer: a fraction of agents
    # shelter, cutting their contact by shelter_effectiveness.  Off by default so
    # calibration happens in the passive condition.
    shelter_fraction: float = 0.0
    shelter_effectiveness: float = 0.75


@dataclass
class HandoffParams:
    """Promotion/demotion triggers for the macro<->micro boundary.

    Hysteresis is built in (promote and demote thresholds differ) so the
    interface is correct for the later multi-zone game even though a single-zone
    test never thrashes across it.  Triggers are expressed as a zone infectious
    fraction here; in the full game a player-proximity / visibility term would
    dominate (noted as the extension point).
    """

    promote_threshold: float = 0.005   # promote a zone to agents above this
    #                                    infectious fraction (or player nearby)
    demote_threshold: float = 0.002    # demote back to macro below this
    #                                    (< promote_threshold => hysteresis)

"""Outbreak pathogen grammar (ASPHODEL_OUTBREAK_V1 §4).

A bounded, data-driven description of how an individual citizen's disease
progresses and spreads. This is the per-citizen counterpart of the macro
:class:`asphodel.config.PathogenGenome` (which stays the FAR statistical
tier's authority and is untouched). Structure and the archetype names
(classic_shambler, rage_virus, cordyceps, necro_latent) carry forward from
the donor branch ``claude/outbreak-config-types-A8fTw``; the donor's values
are in days, kept verbatim in :func:`classic_shambler`; the V1 certification
archetype :func:`classic_zombie` is the same shape compressed to hours so a
one-day trace can exhibit every transition.

All durations are game **seconds**. Every per-citizen draw is a pure function
of ``(world_seed, citizen_id, purpose)`` (see :mod:`.health`), so save/load
never re-rolls an outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Optional

H = 3600.0
D = 86400.0


@dataclass(frozen=True)
class OutbreakPathogen:
    name: str = "classic_zombie"
    archetype: str = "classic"
    # --- transmission (hazard rates per game hour per infectious contact) ----
    transmission_route: str = "bite"          # bite | contact | fluid | airborne (label + mixing)
    building_rate_per_h: float = 0.5           # co-occupants of one building (symptomatic source)
    vehicle_rate_per_h: float = 1.0            # shared vehicle
    proximity_rate_per_h: float = 0.6          # NEAR: within proximity_radius_m outdoors
    proximity_radius_m: float = 2.5
    presymptomatic_factor: float = 0.6         # infectiousness before symptoms (last presymptomatic_s)
    presymptomatic_s: float = 2.0 * H
    bite_probability: float = 0.85             # per undead attack contact
    undead_infectious: float = 1.2             # relative weight of an undead source (co-occupancy)
    # --- progression (means; per-citizen jitter in [1-jitter, 1+jitter]) -----
    incubation_s: float = 4.0 * H              # exposure -> symptom onset
    symptomatic_s: float = 0.1 * H             # symptom onset -> incapacitation (a rapid collapse)
    incapacitated_s: float = 0.5 * H           # incapacitation -> death (if fatal)
    jitter: float = 0.4
    asymptomatic_fraction: float = 0.05        # never symptomatic; recover
    mortality_fraction: float = 0.95           # of symptomatic cases
    recovery_s: float = 8.0 * H                # symptomatic survivors recover after this
    # --- death / reanimation -------------------------------------------------
    reanimation_fraction: float = 0.9          # of infected deaths
    reanimation_delay_s: float = 20.0 * 60.0   # corpse -> undead (mean)
    turn_on_death: bool = False                # ordinary (uninfected) death also rises
    # --- undead behaviour -----------------------------------------------------
    undead_speed: float = 0.9                  # m/s (a shambler)
    undead_sense_m: float = 60.0               # target acquisition radius outdoors
    attack_reach_m: float = 1.6
    attack_cooldown_s: float = 6.0
    # --- disruption thresholds ------------------------------------------------
    workplace_disruption_fraction: float = 0.5  # of registered workers incapacitated/dead/undead

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OutbreakPathogen":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def classic_zombie() -> OutbreakPathogen:
    """V1 canonical certification pathogen (hours-scale classic zombie)."""
    return OutbreakPathogen()


def classic_shambler() -> OutbreakPathogen:
    """Donor archetype, values in days as the donor wrote them."""
    return OutbreakPathogen(
        name="classic_shambler", archetype="classic", transmission_route="bite",
        incubation_s=1.5 * D, symptomatic_s=3.0 * D, incapacitated_s=1.0 * D,
        presymptomatic_s=0.5 * D, asymptomatic_fraction=0.05, mortality_fraction=0.95,
        reanimation_fraction=0.9, reanimation_delay_s=0.25 * D, undead_infectious=1.2,
        building_rate_per_h=0.08, vehicle_rate_per_h=0.25, proximity_rate_per_h=0.15)


def rage_virus() -> OutbreakPathogen:
    return OutbreakPathogen(
        name="rage_virus", archetype="rage", transmission_route="fluid",
        incubation_s=0.02 * D, symptomatic_s=0.01 * D, incapacitated_s=14.0 * D,
        presymptomatic_s=0.0, asymptomatic_fraction=0.0, mortality_fraction=0.99,
        reanimation_fraction=0.0, undead_speed=3.5, bite_probability=0.95,
        building_rate_per_h=1.5, vehicle_rate_per_h=2.0, proximity_rate_per_h=2.0)


def cordyceps() -> OutbreakPathogen:
    return OutbreakPathogen(
        name="cordyceps", archetype="fungal", transmission_route="airborne",
        incubation_s=8.0 * D, symptomatic_s=4.0 * D, incapacitated_s=8.0 * D,
        presymptomatic_s=4.0 * D, asymptomatic_fraction=0.45, mortality_fraction=0.98,
        reanimation_fraction=0.6, reanimation_delay_s=2.0 * D, undead_infectious=1.5,
        building_rate_per_h=0.2, vehicle_rate_per_h=0.4, proximity_rate_per_h=0.1)


def necro_latent() -> OutbreakPathogen:
    return OutbreakPathogen(
        name="necro_latent", archetype="latent", transmission_route="bite",
        incubation_s=2.0 * D, symptomatic_s=1.0 * D, incapacitated_s=4.0 * D,
        presymptomatic_s=1.0 * D, asymptomatic_fraction=0.1, mortality_fraction=0.9,
        reanimation_fraction=1.0, reanimation_delay_s=0.5 * D, turn_on_death=True,
        undead_infectious=1.0, building_rate_per_h=0.1)


ARCHETYPES: Dict[str, callable] = {
    "classic_zombie": classic_zombie,
    "classic_shambler": classic_shambler,
    "rage_virus": rage_virus,
    "cordyceps": cordyceps,
    "necro_latent": necro_latent,
}


def pathogen_by_name(name: str) -> OutbreakPathogen:
    if name not in ARCHETYPES:
        raise KeyError(f"unknown outbreak pathogen {name!r}; known: {sorted(ARCHETYPES)}")
    return ARCHETYPES[name]()

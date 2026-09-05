"""Canonical per-citizen health state (ASPHODEL_OUTBREAK_V1 §3).

One :class:`HealthRecord` per registered citizen is THE health authority. It
is not a presentation flag: the runtime reads it to invalidate plans, freeze
executors, create corpses and raise the undead. Every biological outcome is
decided ONCE, at the moment it becomes determinable, from a deterministic
draw ``roll(world_seed, citizen_id, purpose)`` and stored as a timestamp or
boolean — so a save/load, an LOD change or a re-run never re-rolls it.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Tuple

from ..world_source.detrand import hash64
from .pathogen import OutbreakPathogen

Vec2 = Tuple[float, float]


class HealthState(str, Enum):
    SUSCEPTIBLE = "susceptible"
    EXPOSED = "exposed"            # exposure event happened; infection decided (see infected)
    INCUBATING = "incubating"      # infected, not yet symptomatic (may be infectious late)
    SYMPTOMATIC = "symptomatic"
    INCAPACITATED = "incapacitated"
    DEAD = "dead"                  # dead, will never rise
    CORPSE = "corpse"              # dead, awaiting reanimation at reanimate_t
    UNDEAD = "undead"
    RECOVERED = "recovered"


ALIVE = {HealthState.SUSCEPTIBLE, HealthState.EXPOSED, HealthState.INCUBATING,
         HealthState.SYMPTOMATIC, HealthState.INCAPACITATED, HealthState.RECOVERED}
INFECTED = {HealthState.EXPOSED, HealthState.INCUBATING, HealthState.SYMPTOMATIC,
            HealthState.INCAPACITATED, HealthState.CORPSE, HealthState.UNDEAD}


def roll(world_seed: int, citizen_id: int, purpose: str, extra: int = 0) -> float:
    """Deterministic uniform in [0, 1) for one (citizen, purpose)."""
    return (hash64(int(world_seed), "outbreak", int(citizen_id), purpose, int(extra)) & 0xFFFFFFFFFFFF) / float(1 << 48)


def jittered(mean: float, jitter: float, u: float) -> float:
    return mean * (1.0 - jitter + 2.0 * jitter * u)


@dataclass
class HealthRecord:
    citizen_id: int
    state: HealthState = HealthState.SUSCEPTIBLE
    pathogen: Optional[str] = None
    source_citizen: Optional[int] = None
    exposure_context: Optional[str] = None      # building:<bid> | vehicle:<vid> | proximity | bite | index_case
    exposure_location: Optional[List[float]] = None
    exposure_t: Optional[float] = None
    infection_t: Optional[float] = None         # == exposure_t when the exposure took
    infectious_from_t: Optional[float] = None
    symptom_t: Optional[float] = None
    incapacitation_t: Optional[float] = None
    death_t: Optional[float] = None
    recovery_t: Optional[float] = None
    fatal: Optional[bool] = None
    asymptomatic: Optional[bool] = None
    will_reanimate: Optional[bool] = None
    reanimate_t: Optional[float] = None
    corpse_xy: Optional[List[float]] = None
    corpse_building_id: int = -1
    corpse_vehicle_id: Optional[str] = None
    undead_since_t: Optional[float] = None
    attacks: int = 0                             # attacks delivered as undead
    bitten_by: Optional[int] = None
    lineage: List[int] = field(default_factory=list)   # source chain, index case first
    exposures_resisted: int = 0                  # contact rolls that did not take

    # -- derived ---------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.state in ALIVE

    @property
    def infected(self) -> bool:
        return self.state in INFECTED

    def infectious_weight(self, p: OutbreakPathogen, now_s: float) -> float:
        """Relative infectiousness of this citizen as a contact source now."""
        if self.state == HealthState.UNDEAD:
            return p.undead_infectious
        if self.state in (HealthState.SYMPTOMATIC, HealthState.INCAPACITATED):
            return 1.0
        if self.state == HealthState.INCUBATING and self.infectious_from_t is not None \
                and now_s >= self.infectious_from_t:
            return p.presymptomatic_factor
        return 0.0

    # -- transitions (all timestamps decided here, once) ------------------------
    def infect(self, p: OutbreakPathogen, seed: int, now_s: float, source: Optional[int],
               context: str, location: Optional[Vec2], lineage: List[int]) -> None:
        cid = self.citizen_id
        self.state = HealthState.INCUBATING
        self.pathogen = p.name
        self.source_citizen = source
        self.exposure_context = context
        self.exposure_location = None if location is None else [round(location[0], 2), round(location[1], 2)]
        self.exposure_t = now_s
        self.infection_t = now_s
        self.lineage = list(lineage) + ([source] if source is not None else [])
        self.asymptomatic = roll(seed, cid, "asymptomatic") < p.asymptomatic_fraction
        inc = jittered(p.incubation_s, p.jitter, roll(seed, cid, "incubation"))
        if self.asymptomatic:
            self.symptom_t = None
            self.recovery_t = now_s + inc + jittered(p.recovery_s, p.jitter, roll(seed, cid, "recovery"))
            self.infectious_from_t = now_s + max(0.0, inc - p.presymptomatic_s)
            self.fatal = False
            return
        self.symptom_t = now_s + inc
        self.infectious_from_t = self.symptom_t - p.presymptomatic_s
        self.fatal = roll(seed, cid, "mortality") < p.mortality_fraction
        sym = jittered(p.symptomatic_s, p.jitter, roll(seed, cid, "symptomatic"))
        if self.fatal:
            self.incapacitation_t = self.symptom_t + sym
            self.death_t = self.incapacitation_t + jittered(p.incapacitated_s, p.jitter,
                                                            roll(seed, cid, "incapacitated"))
            self.will_reanimate = roll(seed, cid, "reanimation") < p.reanimation_fraction
            if self.will_reanimate:
                self.reanimate_t = self.death_t + jittered(p.reanimation_delay_s, p.jitter,
                                                           roll(seed, cid, "reanimation_delay"))
        else:
            self.recovery_t = self.symptom_t + jittered(p.recovery_s, p.jitter, roll(seed, cid, "recovery"))

    def next_transition(self, now_s: float) -> Optional[Tuple[str, float]]:
        """The next scheduled biological transition (name, t) or None."""
        s = self.state
        if s == HealthState.INCUBATING:
            if self.symptom_t is not None:
                return ("symptom_onset", self.symptom_t)
            if self.recovery_t is not None:
                return ("recovery", self.recovery_t)
        elif s == HealthState.SYMPTOMATIC:
            if self.fatal and self.incapacitation_t is not None:
                return ("incapacitation", self.incapacitation_t)
            if self.recovery_t is not None:
                return ("recovery", self.recovery_t)
        elif s == HealthState.INCAPACITATED:
            if self.death_t is not None:
                return ("death", self.death_t)
        elif s == HealthState.CORPSE:
            if self.reanimate_t is not None:
                return ("reanimation", self.reanimate_t)
        return None

    def to_state(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_state(cls, d: dict) -> "HealthRecord":
        d = dict(d)
        d["state"] = HealthState(d["state"])
        d["lineage"] = list(d.get("lineage") or [])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

"""
Episode mode (run-to-termination) for both tiers.

A *episode* is one full run advanced until the epidemic reaches its absorbing
state rather than a fixed ``n_days`` horizon.  Because infected individuals
mostly **recover** (resolve to R) and only a small ``mortality_fraction`` die,
the meaningful end state is **burnout** -- no *active* infection left
(``E + Ia + Is`` below a threshold) or every susceptible already infected
(``S`` exhausted) -- whichever comes first, with a safety cap.  See
:class:`asphodel.scenario.TerminationParams`.

Both tiers are supported, reusing the **frozen** dynamics verbatim:

* macro -- drives :class:`asphodel.model.Simulation` (``model.py`` untouched),
* micro -- drives :class:`asphodel.micro.AgentZone` (``micro.py`` untouched).

The macro tier is deterministic (events off), so its episodes are identical
across seeds (a distribution only appears with the events layer on).  The micro
tier is stochastic, so N episodes give a genuine distribution -- including
stochastic die-out episodes where the outbreak never takes off.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from .scenario import Scenario, TerminationParams
from .model import Simulation
from .micro import AgentZone, STATE_NAMES
from .calibration import calibrate_analytic
from . import metrics


# Terminal reasons (also the keys of the reasons breakdown).
BURNOUT = "burnout"
SUSCEPTIBLES_EXHAUSTED = "susceptibles_exhausted"
MAX_DAYS = "max_days"


@dataclass
class EpisodeResult:
    """One run to termination."""

    tier: str                  # "macro" | "micro"
    seed: int
    duration_days: float       # in-world day at termination
    n_ticks: int
    terminal_reason: str
    final_state: dict          # {S, R, D, attack_rate, total_dead, peak_*}
    outcome_metrics: dict      # tier-appropriate outcome metrics


@dataclass
class EpisodesResult:
    """A batch of episodes for one scenario/tier."""

    scenario: Scenario
    tier: str
    seeds: list[int]
    episodes: list[EpisodeResult]
    summary: dict              # {metric: distribution-summary} over episodes
    reasons: dict              # {terminal_reason: count}

    def frame(self) -> pd.DataFrame:
        """One row per episode (seed, duration, reason, + final/outcome scalars)."""
        rows = []
        for ep in self.episodes:
            row = {"seed": ep.seed, "tier": ep.tier,
                   "duration_days": ep.duration_days,
                   "terminal_reason": ep.terminal_reason}
            row.update(ep.final_state)
            rows.append(row)
        return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# termination predicate (shared by both tiers)
# --------------------------------------------------------------------------- #
def _terminal_reason(active: float, susceptible: float, day: float,
                     ignited: bool, term: TerminationParams) -> Optional[str]:
    """Return the terminal reason if the run should stop now, else None."""
    if day >= term.max_days:
        return MAX_DAYS
    if term.mode == "fixed":
        return None
    # Susceptibles exhausted is a terminal condition in every non-fixed mode.
    if susceptible < term.min_susceptible:
        return SUSCEPTIBLES_EXHAUSTED
    if term.mode == "susceptibles":
        return None
    # burnout: no active infection left (only after the epidemic has ignited and
    # past the warmup, so the seeded macro run doesn't stop at t=0).
    if ignited and day >= term.warmup_days and active < term.min_active:
        return BURNOUT
    return None


# --------------------------------------------------------------------------- #
# macro tier
# --------------------------------------------------------------------------- #
def macro_episode(scenario: Scenario, seed: int,
                  term: Optional[TerminationParams] = None) -> EpisodeResult:
    """Run the macro tier of ``scenario`` to termination (one episode)."""
    term = term or scenario.termination
    cfg = scenario.to_scenario_config()
    cfg.seed = seed
    sim = Simulation(cfg)

    rows = []
    ignited = False
    ignite_level = max(2.0 * scenario.seed_exposed, term.min_active * 10.0)
    reason = MAX_DAYS
    # "fixed" mode just runs the scenario's n_days horizon (no early stop);
    # the other modes run to termination, capped by max_days for safety.
    cap_days = scenario.n_days if term.mode == "fixed" else term.max_days
    max_ticks = int(round(cap_days / scenario.dt))
    for _ in range(max_ticks):
        rec = sim.step()
        rows.append(asdict(rec))
        active = rec.E + rec.I_asymp + rec.I_symp
        if active > ignite_level:
            ignited = True
        r = _terminal_reason(active, rec.S, rec.day, ignited, term)
        if r is not None:
            reason = r
            break

    frame = pd.DataFrame(rows)
    n_zones = sim.graph.n_zones
    om = metrics.macro_metrics(frame, n_zones)
    final = _final_state_from_frame(frame)
    return EpisodeResult(
        tier="macro", seed=seed,
        duration_days=float(frame["day"].iloc[-1]),
        n_ticks=len(frame), terminal_reason=reason,
        final_state=final, outcome_metrics=om,
    )


def _final_state_from_frame(frame: pd.DataFrame) -> dict:
    last = frame.iloc[-1]
    total = float(sum(last[c] for c in ("S", "E", "I_asymp", "I_symp", "R", "D")))
    infectious = (frame["I_asymp"] + frame["I_symp"]).to_numpy()
    peak_i = int(infectious.argmax())
    return {
        "S": float(last["S"]), "R": float(last["R"]), "D": float(last["D"]),
        "attack_rate": (total - float(last["S"])) / total if total > 0 else 0.0,
        "total_dead": float(last["D"]),
        "peak_infectious": float(infectious.max()),
        "peak_infectious_day": float(frame["day"].iloc[peak_i]),
    }


# --------------------------------------------------------------------------- #
# micro tier
# --------------------------------------------------------------------------- #
def micro_episode(scenario: Scenario, seed: int,
                  term: Optional[TerminationParams] = None,
                  seed_exposed: int = 10) -> EpisodeResult:
    """Run the micro (agent) tier to termination (one episode).

    The micro params are analytically calibrated from the genome (so transmission
    matches the macro beta), then a single :class:`AgentZone` is advanced until
    no active infection remains, susceptibles are exhausted, or the cap is hit.
    Because the agent tier is stochastic, each seed is a different realisation --
    some take off, some go extinct early."""
    term = term or scenario.termination
    g = scenario.genome
    params = calibrate_analytic(g, scenario.micro_params)
    dt = scenario.dt

    zone = AgentZone(g, params, dt, seed=seed)
    zone.seed_infection(seed_exposed)
    n_total = zone.n

    peak_infectious = 0
    peak_day = 0.0
    ignited = False
    ignite_level = max(2.0 * seed_exposed, term.min_active * 10.0)
    reason = MAX_DAYS
    cap_days = scenario.n_days if term.mode == "fixed" else term.max_days
    max_ticks = int(round(cap_days / dt))
    day = 0.0
    for k in range(1, max_ticks + 1):
        zone.step()
        day = k * dt
        c = zone.counts()
        active = c["E"] + c["Ia"] + c["Is"]
        infectious = c["Ia"] + c["Is"]
        if infectious > peak_infectious:
            peak_infectious, peak_day = infectious, day
        if active > ignite_level:
            ignited = True
        # micro is integer-exact: an early die-out (active==0) is a legitimate
        # terminal episode, so the warmup gate is relaxed for exact extinction.
        exact_extinct = (active == 0)
        r = _terminal_reason(active, c["S"], day,
                             ignited or exact_extinct, term)
        if r is not None:
            reason = r
            break

    c = zone.counts()
    attack = (n_total - c["S"]) / n_total if n_total > 0 else 0.0
    final = {
        "S": float(c["S"]), "R": float(c["R"]), "D": float(c["D"]),
        "attack_rate": float(attack), "total_dead": float(c["D"]),
        "peak_infectious": float(peak_infectious),
        "peak_infectious_day": float(peak_day),
        "took_off": bool(attack > 0.05),   # distinguish takeoff vs die-out
    }
    om = {"attack_rate": float(attack), "total_dead": float(c["D"]),
          "peak_infectious": float(peak_infectious),
          "peak_infectious_day": float(peak_day),
          "duration_days": float(day)}
    return EpisodeResult(
        tier="micro", seed=seed, duration_days=float(day),
        n_ticks=zone.tick, terminal_reason=reason,
        final_state=final, outcome_metrics=om,
    )


# --------------------------------------------------------------------------- #
# the episode batch runner
# --------------------------------------------------------------------------- #
def run_episodes(scenario: Scenario, n_episodes: int, tier: str = "micro",
                 termination: Optional[TerminationParams] = None,
                 seeds: Optional[Sequence[int]] = None,
                 seed_exposed: int = 10) -> EpisodesResult:
    """Run ``n_episodes`` independent runs-to-termination and summarise them.

    ``tier`` is ``"macro"`` or ``"micro"``.  ``seeds`` defaults to
    ``range(n_episodes)``.  Returns the per-episode results, the distribution of
    their outcome metrics + duration, and a breakdown of terminal reasons."""
    term = termination or scenario.termination
    seeds = list(seeds) if seeds is not None else list(range(n_episodes))

    eps: list[EpisodeResult] = []
    for s in seeds:
        if tier == "macro":
            eps.append(macro_episode(scenario, s, term))
        elif tier == "micro":
            eps.append(micro_episode(scenario, s, term, seed_exposed=seed_exposed))
        else:
            raise ValueError(f"unknown tier {tier!r} (expected 'macro'|'micro')")

    # Distribution over episodes: outcome metrics + duration.
    per_run = []
    for ep in eps:
        m = dict(ep.outcome_metrics)
        m["duration_days"] = ep.duration_days
        per_run.append(m)
    summary = metrics.summarize_metrics(per_run)

    reasons: dict[str, int] = {}
    for ep in eps:
        reasons[ep.terminal_reason] = reasons.get(ep.terminal_reason, 0) + 1

    return EpisodesResult(scenario=scenario, tier=tier, seeds=seeds,
                          episodes=eps, summary=summary, reasons=reasons)

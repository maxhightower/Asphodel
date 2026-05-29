"""
The macro <-> micro handoff: promotion and demotion as three messages.

Design principle (from the brief): *while a zone is promoted, the agents are the
truth, and the macro counts are derived from them each tick* -- there is no
parallel macro integration running alongside to drift against, so conservation
is automatic.

The three messages:

1. **Spawn manifest** (macro -> micro, on promotion): given a zone's macro
   compartment counts, instantiate N agents whose state distribution matches
   those counts.  ``AgentZone.from_counts`` does the spawning; this module owns
   the float->integer allocation (largest-remainder) so the total is conserved
   exactly.

2. **Derived update** (micro -> macro, every macro tick): recount the live
   agents by state and *overwrite* the macro compartment counts.  Inter-zone
   flux is stubbed to zero for the single-zone prototype (the documented
   extension point).

3. **Merge** (micro -> demotion): the zone resumes macro integration seeded from
   the last agent-derived counts.

Hysteresis (``HandoffParams``) is threaded through so the interface is correct
for the later multi-zone game, even though a single-zone test never thrashes.
"""

from __future__ import annotations

import copy

import numpy as np

from .config import PathogenGenome, MicroParams, HandoffParams
from .micro import AgentZone, STATE_NAMES
from .macro_ref import passive_macro_config
from .model import Simulation


# --------------------------------------------------------------------------- #
# float compartment counts <-> integer agent manifest
# --------------------------------------------------------------------------- #
def largest_remainder_counts(float_counts: dict[str, float]) -> dict[str, int]:
    """Round a dict of float compartment counts to integers that sum to the
    rounded total, preserving each compartment as closely as possible.

    Guarantees ``sum(result) == round(sum(float_counts))`` so spawning conserves
    the total population exactly (no people created or destroyed).
    """
    names = list(STATE_NAMES)
    vals = np.array([float_counts[n] for n in names], dtype=float)
    total = int(round(vals.sum()))
    floors = np.floor(vals).astype(int)
    remainder = total - int(floors.sum())
    if remainder > 0:
        # Hand the leftover units to the largest fractional parts.
        frac = vals - floors
        order = np.argsort(-frac)
        for i in range(remainder):
            floors[order[i % len(order)]] += 1
    elif remainder < 0:
        # Too many (can happen if values were rounded up); remove from smallest
        # fractional parts that still have a positive count.
        frac = vals - np.floor(vals)
        order = np.argsort(frac)
        k = 0
        while remainder < 0 and k < 10 * len(order):
            i = order[k % len(order)]
            if floors[i] > 0:
                floors[i] -= 1
                remainder += 1
            k += 1
    return {n: int(floors[idx]) for idx, n in enumerate(names)}


def macro_zone_counts(sim: Simulation, zone: int = 0) -> dict[str, float]:
    """Read one zone's macro compartment counts (floats) from a Simulation."""
    return {
        "S": float(sim.S[zone]), "E": float(sim.E[zone]),
        "Ia": float(sim.Ia[zone]), "Is": float(sim.Is[zone]),
        "R": float(sim.R[zone]), "D": float(sim.D[zone]),
    }


def write_macro_zone_counts(sim: Simulation, counts: dict[str, float],
                            zone: int = 0) -> None:
    """Overwrite one zone's macro compartment counts (the derived update)."""
    sim.S[zone] = counts["S"]; sim.E[zone] = counts["E"]
    sim.Ia[zone] = counts["Ia"]; sim.Is[zone] = counts["Is"]
    sim.R[zone] = counts["R"]; sim.D[zone] = counts["D"]


# --------------------------------------------------------------------------- #
# message 1: spawn manifest (macro -> micro)
# --------------------------------------------------------------------------- #
def promote(macro_counts: dict[str, float], genome: PathogenGenome,
            params: MicroParams, dt: float, seed: int = 0) -> AgentZone:
    """Spawn an AgentZone from macro compartment counts (conserving the total).

    NOTE (TODO, deferred per brief): the full spawn manifest would use visibility
    weights / a time-of-day density field / a tracked-vs-ephemeral NPC split.
    Here we spawn a straightforward representative closed population.
    """
    int_counts = largest_remainder_counts(macro_counts)
    return AgentZone.from_counts(int_counts, genome, params, dt, seed=seed)


# --------------------------------------------------------------------------- #
# message 3: merge / demote (micro -> macro)
# --------------------------------------------------------------------------- #
def demote(zone: AgentZone, dt: float, n_days_remaining: float,
           seed: int = 0) -> tuple[Simulation, dict[str, float]]:
    """Resume macro integration seeded from the agents' final counts.

    Returns a fresh passive-macro Simulation primed with the agent-derived
    counts (no outbreak re-seeding) plus the seed counts, ready to ``.step()``.
    """
    counts = zone.counts()
    n_total = sum(counts.values())
    cfg = passive_macro_config(zone.genome, n_total, dt,
                               n_days_remaining, seed_exposed=0)
    cfg.seed = seed
    sim = Simulation(cfg)
    # Overwrite the freshly-seeded state with the agent-derived counts.
    write_macro_zone_counts(sim, {k: float(v) for k, v in counts.items()})
    return sim, {k: float(v) for k, v in counts.items()}


# --------------------------------------------------------------------------- #
# trigger logic (hysteresis) -- not exercised by the single-zone test, but the
# interface is here so the multi-zone game inherits it correctly.
# --------------------------------------------------------------------------- #
def should_promote(infectious_fraction: float, currently_micro: bool,
                   h: HandoffParams) -> bool:
    if currently_micro:
        return True
    return infectious_fraction >= h.promote_threshold


def should_demote(infectious_fraction: float, currently_micro: bool,
                  h: HandoffParams) -> bool:
    if not currently_micro:
        return False
    return infectious_fraction < h.demote_threshold


# --------------------------------------------------------------------------- #
# full round trip: macro -> promote -> agents -> demote -> macro
# --------------------------------------------------------------------------- #
def round_trip(genome: PathogenGenome, params: MicroParams, dt: float,
               macro_days_before: float, micro_days: float,
               macro_days_after: float, seed: int = 0,
               seed_exposed: int = 10) -> dict:
    """Run a zone through macro -> promote -> agents -> demote -> macro and
    return the stitched compartment series plus the counts at each seam (for the
    conservation + continuity test).
    """
    n = params.n_agents

    # --- Phase A: macro (passive, closed) ------------------------------------
    cfgA = passive_macro_config(genome, n, dt, macro_days_before, seed_exposed)
    cfgA.seed = seed
    simA = Simulation(cfgA)
    seriesA = {name: [] for name in STATE_NAMES}
    daysA = []
    nA = int(round(macro_days_before / dt))
    for k in range(nA):
        simA.step()
        c = macro_zone_counts(simA)
        for name in STATE_NAMES:
            seriesA[name].append(c[name])
        daysA.append(simA.tick * dt)
    counts_before_promote = macro_zone_counts(simA)

    # --- Promote (message 1: spawn manifest) ---------------------------------
    zone = promote(counts_before_promote, genome, params, dt, seed=seed)
    counts_after_promote = {k: float(v) for k, v in zone.counts().items()}

    # --- Phase B: agents are the truth; derive macro counts each tick --------
    seriesB = {name: [] for name in STATE_NAMES}
    daysB = []
    nB = int(round(micro_days / dt))
    t0 = macro_days_before
    for k in range(nB):
        zone.step()
        c = zone.counts()
        for name in STATE_NAMES:
            seriesB[name].append(float(c[name]))
        daysB.append(t0 + (k + 1) * dt)
    counts_before_demote = {k: float(v) for k, v in zone.counts().items()}

    # --- Demote (message 3: merge) -------------------------------------------
    simC, counts_after_demote = demote(zone, dt, macro_days_after, seed=seed)

    # --- Phase C: macro resumes from the agent-derived state -----------------
    seriesC = {name: [] for name in STATE_NAMES}
    daysC = []
    nC = int(round(macro_days_after / dt))
    t1 = macro_days_before + micro_days
    for k in range(nC):
        simC.step()
        c = macro_zone_counts(simC)
        for name in STATE_NAMES:
            seriesC[name].append(c[name])
        daysC.append(t1 + (k + 1) * dt)

    # Stitch the three phases (with the initial condition prepended).
    init = {"S": float(n - seed_exposed), "E": float(seed_exposed),
            "Ia": 0.0, "Is": 0.0, "R": 0.0, "D": 0.0}
    stitched = {"day": np.array([0.0] + daysA + daysB + daysC)}
    for name in STATE_NAMES:
        stitched[name] = np.array(
            [init[name]] + seriesA[name] + seriesB[name] + seriesC[name])

    return {
        "series": stitched,
        "counts_before_promote": counts_before_promote,
        "counts_after_promote": counts_after_promote,
        "counts_before_demote": counts_before_demote,
        "counts_after_demote": counts_after_demote,
        "n_total": n,
        "seam_promote_day": macro_days_before,
        "seam_demote_day": macro_days_before + micro_days,
    }


def total_people(counts: dict) -> float:
    return float(sum(counts[name] for name in STATE_NAMES))

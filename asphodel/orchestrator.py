"""
The orchestrator: ``World`` -- the single engine facade the front-end renders.

``World`` runs the whole-map macro :class:`~asphodel.model.Simulation` and a set
of *promoted* zones resolved into agents (:class:`~asphodel.micro.AgentZone`),
flipping zones between the two tiers at runtime and exchanging people across the
boundary.  See ``ARCHITECTURE.md`` for the contract and the per-tick algorithm;
the short version:

* The **macro float array is the authoritative, exactly-conserved population
  ledger.**  A promoted zone's agents are its integer realisation, used for
  internal dynamics and rendering.
* Each tick the macro steps with the promoted zones' *internal* SEIR frozen
  (agents own it) while still applying inter-zone **flux** (belief-driven
  fleeing) to them and letting them drive the belief/infra fields.  The agents
  then supply the internal compartment change, which is written back and
  realised on the agent population.  Population is conserved exactly.

The disease genome, calibration and handoff messages are all reused unchanged;
this module only orchestrates them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from .config import ScenarioConfig, MicroParams, HandoffParams
from .model import Simulation, TickRecord
from .micro import AgentZone, STATE_NAMES
from .handoff import promote, macro_zone_counts, largest_remainder_counts, should_promote, should_demote


# Reference agent density (agents per unit area) at which the micro tier was
# calibrated: the validated N=1000 / L=100 case -> 1000 / 100^2 = 0.1.
DEFAULT_REF_DENSITY = 1000.0 / (100.0 ** 2)


@dataclass
class WorldTick:
    """Per-tick summary returned by :meth:`World.step`."""

    tick: int
    day: float
    n_promoted: int
    promoted: list[int]
    total_pop: float
    # Aggregate compartment totals (authoritative, computed after write-back).
    S: float
    E: float
    Ia: float
    Is: float
    R: float
    D: float
    # The macro field-level record (belief, infra, authority, outflow, events).
    macro: TickRecord


class World:
    """The engine facade: macro grid + dynamically promoted agent zones."""

    def __init__(self, config: ScenarioConfig,
                 micro_params: MicroParams | None = None,
                 handoff: HandoffParams | None = None,
                 ref_density: float | None = None,
                 max_live_zones: int | None = None,
                 max_live_agents: int | None = None,
                 seed: int = 0):
        self.cfg = config

        # Real-time budget caps on the live bubble (None => unbounded).  When a
        # cap would be exceeded, player-focused zones are always kept and the
        # remaining budget goes to the highest-infectious zones; the rest stay
        # macro.  This is how the frame budget sizes the live bubble.
        self.max_live_zones = max_live_zones
        self.max_live_agents = max_live_agents
        self.sim = Simulation(config)
        self.Z = self.sim.Z
        self.dt = config.dt

        self.micro_params = micro_params or MicroParams()
        self.handoff = handoff or HandoffParams()
        if ref_density is not None:
            self.ref_density = ref_density
        elif self.micro_params.area_size > 0:
            self.ref_density = self.micro_params.n_agents / (self.micro_params.area_size ** 2)
        else:
            self.ref_density = DEFAULT_REF_DENSITY

        self._seed = seed
        self._promo_counter = 0          # bumps each promotion -> fresh agent RNG

        self.promoted: dict[int, AgentZone] = {}   # zone index -> agent zone
        self.focus: set[int] = set()               # player-forced promotions

    # ------------------------------------------------------------------ inputs
    def set_focus(self, zones) -> None:
        """Set the player-focus set: these zones are force-promoted (camera)."""
        self.focus = set(int(z) for z in zones)

    # --------------------------------------------------------------- read state
    def infectious_fraction(self) -> np.ndarray:
        """Per-zone infectious fraction (Ia+Is)/living, from the macro ledger."""
        living = self.sim.living()
        safe = np.where(living > 0, living, 1.0)
        return (self.sim.Ia + self.sim.Is) / safe

    def promoted_zones(self) -> list[int]:
        return sorted(self.promoted)

    # --------------------------------------------------------------- one tick
    def step(self) -> WorldTick:
        # --- 1. membership: decide the promoted set (hysteresis + focus) -----
        self._update_membership()
        frozen = list(self.promoted)

        # Macro float counts of promoted zones *before* the macro step.
        pre = {z: macro_zone_counts(self.sim, z) for z in frozen}

        # --- 2. macro step with promoted internals frozen --------------------
        rec = self.sim.step(frozen_internal=frozen)

        # --- 3+4. agent internal step, then write-back & realise flux --------
        for z, zone in self.promoted.items():
            # Inter-zone flux the macro applied to this zone this tick (float).
            post_flux = macro_zone_counts(self.sim, z)

            agent_pre = zone.counts()
            zone.step()
            agent_post = zone.counts()

            # New ledger = flux'd counts + the agents' internal compartment
            # change (which sums to zero, so the global total is conserved).
            new_float = {}
            for name in STATE_NAMES:
                delta = agent_post[name] - agent_pre[name]
                new_float[name] = post_flux[name] + delta
            self._write_zone(z, new_float)

            # Realise the result on the agent population (mainly the flux).
            zone.reconcile_to_counts(largest_remainder_counts(new_float))

        # --- 5. authoritative aggregate (after write-back) -------------------
        totals = {name: float(getattr(self.sim, _attr(name)).sum())
                  for name in STATE_NAMES}
        total_pop = sum(totals.values())

        return WorldTick(
            tick=self.sim.tick, day=self.sim.tick * self.dt,
            n_promoted=len(self.promoted), promoted=sorted(self.promoted),
            total_pop=total_pop, macro=rec, **totals,
        )

    def run(self, n_days: float) -> list[WorldTick]:
        n = int(round(n_days / self.dt))
        return [self.step() for _ in range(n)]

    # --------------------------------------------------------------- rendering
    def snapshot(self) -> dict:
        """Everything the renderer needs this frame (no live engine refs)."""
        sim = self.sim
        living = sim.living()
        safe = np.where(living > 0, living, 1.0)
        inf_frac = (sim.Ia + sim.Is) / safe
        zones = []
        for z in range(self.Z):
            zones.append({
                "zone": z,
                "belief": float(sim.belief[z]),
                "S": float(sim.S[z]), "E": float(sim.E[z]),
                "Ia": float(sim.Ia[z]), "Is": float(sim.Is[z]),
                "R": float(sim.R[z]), "D": float(sim.D[z]),
                "infectious_fraction": float(inf_frac[z]),
                "power_ok": bool(sim.power_ok[z]),
                "water_ok": bool(sim.water_ok[z]),
                "promoted": z in self.promoted,
            })
        agents = {}
        for z, zone in self.promoted.items():
            agents[z] = {
                "positions": zone.pos.copy(),
                "state": zone.state.copy(),
                "area_size": zone.L,
            }
        return {
            "day": sim.tick * self.dt, "tick": sim.tick,
            "rows": sim.graph.rows, "cols": sim.graph.cols,
            "official_signal": float(sim.official_signal),
            "authority_perceived": float(sim.authority_perceived),
            "zones": zones, "agents": agents,
        }

    # ------------------------------------------------------------- internals
    def _update_membership(self) -> None:
        frac = self.infectious_fraction()
        h = self.handoff

        # 1. Desired set from focus + infectious-fraction hysteresis.
        desired: set[int] = set()
        for z in range(self.Z):
            currently = z in self.promoted
            if z in self.focus:
                want = True
            elif currently:
                want = not should_demote(float(frac[z]), True, h)
            else:
                want = should_promote(float(frac[z]), False, h)
            if want:
                desired.add(z)

        # 2. Apply the real-time budget caps, if any.
        desired = self._apply_budget(desired, frac)

        # 3. Reconcile current -> desired.
        for z in sorted(desired - set(self.promoted)):
            self._promote_zone(z)
        for z in sorted(set(self.promoted) - desired):
            self._demote_zone(z)

    def _apply_budget(self, desired: set[int], frac: np.ndarray) -> set[int]:
        """Trim ``desired`` to the live-bubble caps, keeping the most important.

        Player-focused zones are always kept (the camera is non-negotiable);
        the remaining budget is filled by descending infectious fraction.  A
        zone's agent cost is its current macro living count.
        """
        if self.max_live_zones is None and self.max_live_agents is None:
            return desired

        living = self.sim.living()
        # Focus zones first (kept regardless), then the rest by infectiousness.
        forced = [z for z in desired if z in self.focus]
        rest = sorted((z for z in desired if z not in self.focus),
                      key=lambda z: float(frac[z]), reverse=True)

        kept = list(forced)
        agents = sum(float(living[z]) for z in forced)
        for z in rest:
            if self.max_live_zones is not None and len(kept) >= self.max_live_zones:
                break
            cost = float(living[z])
            if (self.max_live_agents is not None
                    and agents + cost > self.max_live_agents and kept):
                continue
            kept.append(z)
            agents += cost
        return set(kept)

    def _promote_zone(self, z: int) -> None:
        counts = macro_zone_counts(self.sim, z)
        living = sum(v for k, v in counts.items() if k != "D")
        if living < 1.0:
            return  # nothing meaningful to resolve into agents
        # Size the torus so the agents sit at the calibrated reference density,
        # keeping the analytic genome->contact_prob relation valid at any N.
        area = float(np.sqrt(max(living, 1.0) / self.ref_density))
        params = replace(self.micro_params, area_size=area)
        self._promo_counter += 1
        seed = self._seed * 100003 + z * 101 + self._promo_counter
        self.promoted[z] = promote(counts, self.cfg.genome, params, self.dt, seed=seed)

    def _demote_zone(self, z: int) -> None:
        # The macro ledger already holds this zone's latest agent-derived counts
        # (written every tick), so demotion just stops freezing it -- the macro
        # resumes its own internal integration next tick.  No merge needed.
        self.promoted.pop(z, None)

    def _write_zone(self, z: int, counts: dict[str, float]) -> None:
        for name in STATE_NAMES:
            getattr(self.sim, _attr(name))[z] = counts[name]


def _attr(name: str) -> str:
    """Map a STATE_NAMES entry to the Simulation array attribute name."""
    return name  # S,E,Ia,Is,R,D match the Simulation attribute names exactly

"""
The simulation engine: coupled SEIR + belief + behaviour + infrastructure +
authority fields over the zone graph, advanced by explicit difference
equations at a fixed `dt`.

Design notes
------------
* Every rate is multiplied by ``dt`` so the qualitative dynamics are
  tick-rate independent (halving dt and doubling ticks gives the same arc).
* State lives in flat numpy arrays of length ``Z`` (zones); the update is
  vectorised, so 64 zones over thousands of ticks runs in well under a second.
* The disease compartments are S, E, I_a (infectious, not yet visible),
  I_s (visibly symptomatic), R, D.  Belief keys off *visible* burden only,
  which is what opens the silent "Day -1" gap.

The single most important coupling loop is:

    belief -> behaviour (shelter/flee) -> infection + movement
          -> visible burden -> observation -> belief ...

plus social contagion of belief between zones (the cascade) and a lagged
official signal from the authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque

import numpy as np

from .config import ScenarioConfig
from .graph import ZoneGraph


def smoothstep(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Smooth 0->1 ramp between lo and hi (clamped, C1-continuous)."""
    if hi <= lo:
        return (np.asarray(x) >= hi).astype(float)
    t = np.clip((np.asarray(x) - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


@dataclass
class TickRecord:
    """Per-tick aggregate snapshot (one row of the output CSV)."""

    tick: int
    day: float
    S: float
    E: float
    I_asymp: float
    I_symp: float
    R: float
    D: float
    belief_mean: float
    belief_max: float
    n_panic: int                 # zones above the panic threshold
    official_signal: float
    authority_perceived: float
    n_power_fail: int
    n_water_fail: int
    total_outflow: float         # people moving between zones this tick
    expected_incidents: float    # emergent transport-hazard expectation
    n_events: int                # exogenous shocks fired this tick


class Simulation:
    """Holds all field state and advances it one tick at a time."""

    def __init__(self, config: ScenarioConfig):
        self.cfg = config
        self.graph = ZoneGraph(config.model.graph)
        self.rng = np.random.default_rng(config.seed)

        Z = self.graph.n_zones
        self.Z = Z
        self.dt = config.dt

        # --- Infection compartments (people) -------------------------------
        pop_vec = config.model.graph.population
        if pop_vec is not None:
            if len(pop_vec) != Z:
                raise ValueError(
                    f"graph.population has {len(pop_vec)} entries but grid has {Z} zones"
                )
            self.N0 = np.asarray(pop_vec, dtype=float)  # per-zone population
        else:
            pop = config.model.graph.population_per_zone
            self.N0 = np.full(Z, pop, dtype=float)      # uniform population
        self.S = self.N0.copy()
        # Safe denominator for per-zone rates: zones with zero population (common
        # when zones come from real OSM geography -- water, parks, rural edges)
        # would otherwise produce 0/0 NaNs that propagate through belief
        # contagion. For populated zones this equals N0, so dynamics are
        # unchanged; empty zones divide by 1.0 and stay inert.
        self.N0_safe = np.where(self.N0 > 0, self.N0, 1.0)
        self.E = np.zeros(Z)
        self.Ia = np.zeros(Z)                          # infectious, not visible
        self.Is = np.zeros(Z)                          # visibly symptomatic
        self.R = np.zeros(Z)
        self.D = np.zeros(Z)

        # --- Belief & infrastructure fields --------------------------------
        self.belief = np.full(Z, config.model.belief.floor, dtype=float)
        self.staffing = np.ones(Z)                     # [0,1]
        self.power_ok = np.ones(Z, dtype=bool)
        self.water_ok = np.ones(Z, dtype=bool)

        # --- Authority state -----------------------------------------------
        self.official_signal = 0.0
        self.authority_perceived = 0.0
        lag_ticks = max(1, int(round(config.model.authority.observation_lag_days / self.dt)))
        # Buffer of past *visible* burden fractions; the authority reads the
        # oldest entry, so its view of the world is `lag_ticks` behind.
        self._authority_buffer: deque[float] = deque([0.0] * lag_ticks, maxlen=lag_ticks)

        # --- Seed the outbreak in one zone ---------------------------------
        seed_zone = config.seed_zone
        if seed_zone is None:
            seed_zone = self.graph.center_zone()
        self.seed_zone = seed_zone
        injected = min(config.seed_exposed, self.S[seed_zone])
        self.S[seed_zone] -= injected
        self.E[seed_zone] += injected

        self.tick = 0
        self.events_log: list[dict] = []   # exogenous shock log

    # ------------------------------------------------------------------ misc
    def living(self) -> np.ndarray:
        """Living population per zone (everyone except the dead)."""
        return self.S + self.E + self.Ia + self.Is + self.R

    # -------------------------------------------------------- behaviour fields
    def _shelter_fraction(self) -> np.ndarray:
        b = self.cfg.model.behavior
        return b.max_shelter * smoothstep(self.belief, b.shelter_belief_low, b.shelter_belief_high)

    def _flee_fraction(self) -> np.ndarray:
        b = self.cfg.model.behavior
        return b.max_flee_rate * smoothstep(self.belief, b.flee_belief_low, b.flee_belief_high)

    # --------------------------------------------------------------- one tick
    def step(self) -> TickRecord:
        dt = self.dt
        g = self.cfg.genome
        m = self.cfg.model

        living = self.living()
        safe_living = np.where(living > 0, living, 1.0)  # avoid /0

        # === 1. Behaviour multipliers from current belief ==================
        shelter = self._shelter_fraction()             # fraction sheltering
        flee_rate = self._flee_fraction()              # outflow rate/day

        # === 2. Infrastructure cascade (staffing -> power -> water) ========
        infra = m.infrastructure
        if infra.enabled:
            # Workforce present = living, not visibly sick, not sheltering.
            available = np.clip(living - self.Is, 0.0, None) * (1.0 - shelter)
            # Empty zones have no workforce *and* no infrastructure to fail, so
            # treat them as fully staffed (1.0) rather than 0/0 -> a false alarm.
            self.staffing = np.where(
                self.N0 > 0, np.clip(available / self.N0_safe, 0.0, 1.0), 1.0
            )
            self.power_ok = self.staffing >= infra.power_staffing_threshold
            # Water depends on staffing *and* power being up.
            self.water_ok = self.power_ok & (self.staffing >= infra.water_staffing_threshold)
            infra_alarm = (
                (~self.power_ok) * infra.infra_alarm_power
                + (~self.water_ok) * infra.infra_alarm_water
            )
            infra_alarm = np.clip(infra_alarm, 0.0, 1.0)
            forced_flee = (~self.water_ok) * infra.forced_flee_no_water
        else:
            infra_alarm = np.zeros(self.Z)
            forced_flee = np.zeros(self.Z)

        # === 3. Infection dynamics (SEIR metapopulation) ===================
        # Effective transmission rate, reduced by sheltering.
        beta = g.beta() * (1.0 - m.behavior.shelter_effectiveness * shelter)

        # Infectious fraction seen locally, then mixed with neighbours so the
        # disease is carried along mobility edges.
        infectious_frac = (self.Ia + self.Is) / safe_living
        mixed_infectious = (
            (1.0 - m.graph.mobility) * infectious_frac
            + m.graph.mobility * (self.graph.mix @ infectious_frac)
        )

        sigma = 1.0 / g.incubation_period          # E -> I_a
        omega = 1.0 / g.symptom_onset_delay        # I_a -> I_s (visible)
        gamma = 1.0 / g.infectious_period          # infectious -> R/D
        a = g.asymptomatic_fraction

        new_E = beta * self.S * mixed_infectious * dt
        new_E = np.minimum(new_E, self.S)          # cannot expose more than S

        leave_E = sigma * self.E * dt              # E -> I_a
        # Competing exits from I_a: the symptomatic-bound become visible (omega)
        # while the permanently-asymptomatic recover directly (gamma).
        Ia_to_Is = omega * (1.0 - a) * self.Ia * dt
        Ia_recover = gamma * a * self.Ia * dt
        Ia_out = np.minimum(Ia_to_Is + Ia_recover, self.Ia)
        # Re-split if clamped (keeps mass conserved without going negative).
        scale = np.where((Ia_to_Is + Ia_recover) > 0,
                         Ia_out / np.where((Ia_to_Is + Ia_recover) > 0, Ia_to_Is + Ia_recover, 1.0),
                         0.0)
        Ia_to_Is *= scale
        Ia_recover *= scale

        leave_Is = np.minimum(gamma * self.Is * dt, self.Is)   # I_s -> R/D
        Is_death = g.mortality_fraction * leave_Is
        Is_recover = leave_Is - Is_death

        # Apply compartment updates (explicit Euler).
        self.S = self.S - new_E
        self.E = self.E + new_E - leave_E
        self.Ia = self.Ia + leave_E - Ia_to_Is - Ia_recover
        self.Is = self.Is + Ia_to_Is - leave_Is
        self.R = self.R + Ia_recover + Is_recover
        self.D = self.D + Is_death

        # === 4. Population movement (fleeing) ==============================
        total_flee_rate = np.clip(flee_rate + forced_flee, 0.0, 1.0 / dt)
        total_outflow = self._apply_fleeing(total_flee_rate * dt)

        # === 5. Authority (lagged official signal) =========================
        self._update_authority()

        # === 6. Belief field update ========================================
        self._update_belief(infra_alarm)

        # === 7. Stochastic / emergent events (stretch) =====================
        n_events, expected_incidents = self._apply_events(total_outflow)

        # === 8. Record =====================================================
        self.tick += 1
        b = m.belief
        rec = TickRecord(
            tick=self.tick,
            day=self.tick * dt,
            S=float(self.S.sum()),
            E=float(self.E.sum()),
            I_asymp=float(self.Ia.sum()),
            I_symp=float(self.Is.sum()),
            R=float(self.R.sum()),
            D=float(self.D.sum()),
            belief_mean=float(self.belief.mean()),
            belief_max=float(self.belief.max()),
            n_panic=int((self.belief > b.panic_threshold).sum()),
            official_signal=float(self.official_signal),
            authority_perceived=float(self.authority_perceived),
            n_power_fail=int((~self.power_ok).sum()) if infra.enabled else 0,
            n_water_fail=int((~self.water_ok).sum()) if infra.enabled else 0,
            total_outflow=float(total_outflow.sum()),
            expected_incidents=float(expected_incidents),
            n_events=n_events,
        )
        return rec

    # --------------------------------------------------------------- helpers
    def _apply_fleeing(self, frac_leaving: np.ndarray) -> np.ndarray:
        """Move a fraction of each zone's living population to safer neighbours.

        People flee toward neighbours with *lower* belief.  All living
        compartments move in proportion (so the infected flee too -- this is
        what feeds the operator-incapacitation hazard).  Returns the per-zone
        outflow (people who left).
        """
        living = self.living()
        outflow = frac_leaving * living
        outflow = np.minimum(outflow, living)
        if outflow.sum() <= 0:
            return np.zeros(self.Z)

        # Destination weights: prefer safer (lower-belief) neighbours.
        safety = (1.0 - self.belief)[None, :] * (self.graph.weights > 0)
        row_sums = safety.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            dest = np.where(row_sums > 0, safety / row_sums, 0.0)

        # Compartment shares of each leaving population.
        safe_living = np.where(living > 0, living, 1.0)
        for comp_name in ("S", "E", "Ia", "Is", "R"):
            comp = getattr(self, comp_name)
            leaving = outflow * comp / safe_living           # people of this comp leaving
            arriving = dest.T @ leaving                       # redistribute to dests
            setattr(self, comp_name, comp - leaving + arriving)
        return outflow

    def _update_authority(self) -> None:
        auth = self.cfg.model.authority
        # True visible burden right now (symptomatic + dead) as a fraction.
        total_pop = self.N0.sum()
        visible_now = float((self.Is.sum() + self.D.sum()) / total_pop)
        self._authority_buffer.append(visible_now)
        if not auth.enabled:
            self.authority_perceived = 0.0
            self.official_signal = 0.0
            return
        # The authority perceives the *oldest* buffered value (lagged).
        self.authority_perceived = self._authority_buffer[0]
        # Official signal ramps toward 1 once perceived burden crosses alarm.
        target = 1.0 if self.authority_perceived >= auth.alarm_threshold else 0.0
        self.official_signal += auth.signal_rate * (target - self.official_signal) * self.dt
        self.official_signal = float(np.clip(self.official_signal, 0.0, 1.0))

    def _update_belief(self, infra_alarm: np.ndarray) -> None:
        bp = self.cfg.model.belief

        # Channel 1: direct observation of *visible* burden (saturating).
        # Cumulative deaths are weighted separately so they can be made to
        # "ratchet" belief (weight 1) or be forgotten (weight 0 -> oscillation).
        visible_frac = (self.Is + bp.obs_deaths_weight * self.D) / self.N0_safe
        obs = visible_frac / (visible_frac + bp.obs_half_saturation)

        # Channel 2: social contagion -- mobility-weighted neighbour belief.
        neighbor_belief = self.graph.mix @ self.belief

        # Channel 3: official signal (global broadcast).
        official = self.official_signal

        # Combine into a target in [0,1].
        target = (
            bp.w_observation * obs
            + bp.w_social * neighbor_belief
            + bp.w_official * official
            + bp.w_infrastructure * infra_alarm
        )
        target = np.clip(target, 0.0, 1.0)

        # Move toward target with inertia, asymmetric rise/decay, and a cap.
        delta = target - self.belief
        rate = np.where(delta >= 0.0, bp.rise_rate, bp.decay_rate)
        step = rate * delta * self.dt
        step = np.clip(step, -bp.max_step, bp.max_step)   # propagation-speed cap
        self.belief = np.clip(self.belief + step, bp.floor, 1.0)

    def _apply_events(self, outflow: np.ndarray) -> tuple[int, float]:
        ev = self.cfg.model.events
        if not ev.enabled:
            return 0, 0.0

        n_events = 0
        # --- Exogenous regional shock (Poisson, prob ~ rate*dt per tick) ---
        if self.rng.random() < ev.shock_rate * self.dt:
            n_events = 1
            center = int(self.rng.integers(self.Z))
            r0, c0 = self.graph.coords(center)
            struck = []
            for r in range(self.rows_cols()[0]):
                for c in range(self.rows_cols()[1]):
                    if abs(r - r0) + abs(c - c0) <= ev.shock_radius:
                        struck.append(self.graph.index(r, c))
            struck = np.array(struck, dtype=int)
            self.belief[struck] = np.clip(self.belief[struck] + ev.shock_belief_bump, 0.0, 1.0)
            self.staffing[struck] = np.clip(self.staffing[struck] - ev.shock_infra_damage, 0.0, 1.0)
            self.events_log.append({
                "tick": self.tick, "day": self.tick * self.dt,
                "type": "regional_shock", "center": center,
                "zones": struck.tolist(),
            })

        # --- Emergent transport hazard (logged expectation, no visuals) ----
        # Incident rate is superlinear in simultaneous outflow (panic-congestion
        # placeholder); operator incapacitation scales with the infected
        # fraction among those fleeing (infection directly causing incidents).
        outflow_frac = outflow / self.N0_safe
        congestion = ev.incident_coeff * np.sum(outflow_frac ** 2)
        living = self.living()
        infected_frac_present = (self.Ia + self.Is) / np.where(living > 0, living, 1.0)
        # Fleers carry the same infected fraction as their zone.
        operator_incap = ev.operator_incap_coeff * np.sum(
            (outflow / self.N0.sum()) * infected_frac_present
        )
        expected_incidents = float(congestion + operator_incap)
        return n_events, expected_incidents

    def rows_cols(self) -> tuple[int, int]:
        return self.graph.rows, self.graph.cols

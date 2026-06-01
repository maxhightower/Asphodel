"""
The micro (agent) tier: one macro zone promoted into discrete people moving in
continuous 2D space, transmitting by physical proximity instead of by the
macro's mass-action term.

Design (matches the Phase-4a brief)
-----------------------------------
* ``n_agents`` people wander a continuous ``L x L`` square.  The square is a
  **torus** (positions wrap), so agent density is spatially uniform and there
  are no edge effects -- this makes the analytic proximity<->beta relation exact
  (modulo finite-N and discretisation), which is what we want for calibration.
* Each agent carries an integer **epidemic state** drawn from the *same*
  compartment set as the macro model: S, E, I_a, I_s, R, D.
* **Transmission is proximity-based**: a susceptible within ``infection_radius``
  r of an infectious agent (I_a or I_s) accrues infection hazard.  This is the
  micro analogue of the macro's beta*S*I/N term.
* **Every non-infection transition reuses the macro genome rates** applied
  per-agent with exactly the macro's per-tick probabilities, so that -- by
  construction -- the only thing that can differ between the tiers in
  expectation is the transmission step.  Mean over many seeds of the agent
  compartment flows equals the macro Euler update for everything except
  infection.

Neighbour search uses a uniform grid (spatial hash) with cell size = r, so the
proximity check is O(n_agents) rather than O(n_agents^2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import PathogenGenome, MicroParams

# Integer state codes (kept module-level so callers can build manifests).
S, E, IA, IS, R, D = 0, 1, 2, 3, 4, 5
STATE_NAMES = ("S", "E", "Ia", "Is", "R", "D")
N_STATES = 6


def analytic_contact_prob(beta: float, living: float, params: MicroParams) -> float:
    """Per-day, per-infectious-neighbour hazard ``p`` that reproduces macro beta.

    Derivation (well-mixed torus of area A = L^2 with ``living`` agents):
    the expected number of infectious agents within radius r of a given
    susceptible is ``n_inf * pi r^2 / A``.  If each contributes hazard p, the
    force of infection is ``lambda = p * n_inf * pi r^2 / A``.  The macro force
    is ``beta * n_inf / living``.  Equating:

        p * pi r^2 / A = beta / living   =>   p = beta * A / (living * pi r^2)

    ``living`` is the current count of non-dead agents (recovered/susceptible
    all still occupy the area), so the relation tracks the macro's N = living
    exactly as deaths accrue.
    """
    A = params.area_size ** 2
    r = params.infection_radius
    living = max(living, 1.0)
    return beta * A / (living * np.pi * r * r) * params.contact_prob_correction


class AgentZone:
    """A single zone resolved into discrete agents in continuous 2D space."""

    def __init__(self, genome: PathogenGenome, params: MicroParams,
                 dt: float, seed: int = 0):
        self.genome = genome
        self.params = params
        self.dt = dt
        self.rng = np.random.default_rng(seed)
        self.seed = seed

        n = params.n_agents
        self.n = n
        self.L = params.area_size
        self.r = params.infection_radius

        # Positions (uniform on the torus) and epidemic state.
        self.pos = self.rng.uniform(0.0, self.L, size=(n, 2))
        self.state = np.full(n, S, dtype=np.int8)

        # Which agents shelter (fixed subset) for the optional active check.
        self.sheltered = np.zeros(n, dtype=bool)
        if params.shelter_fraction > 0:
            k = int(round(params.shelter_fraction * n))
            idx = self.rng.choice(n, size=k, replace=False)
            self.sheltered[idx] = True

        self.tick = 0

    # ----------------------------------------------------------- spawn / counts
    @classmethod
    def from_counts(cls, counts: dict[str, int], genome: PathogenGenome,
                    params: MicroParams, dt: float, seed: int = 0) -> "AgentZone":
        """Spawn manifest: instantiate agents whose state distribution matches a
        set of (integer) macro compartment counts."""
        zone = cls.__new__(cls)
        zone.genome = genome
        zone.params = params
        zone.dt = dt
        zone.rng = np.random.default_rng(seed)
        zone.seed = seed
        n = int(sum(counts[name] for name in STATE_NAMES))
        zone.n = n
        zone.L = params.area_size
        zone.r = params.infection_radius
        zone.pos = zone.rng.uniform(0.0, zone.L, size=(n, 2))
        zone.state = np.empty(n, dtype=np.int8)
        i = 0
        for code, name in enumerate(STATE_NAMES):
            c = int(counts[name])
            zone.state[i:i + c] = code
            i += c
        # Shuffle so state isn't spatially correlated with spawn order.
        perm = zone.rng.permutation(n)
        zone.state = zone.state[perm]
        zone.sheltered = np.zeros(n, dtype=bool)
        if params.shelter_fraction > 0:
            k = int(round(params.shelter_fraction * n))
            idx = zone.rng.choice(n, size=k, replace=False)
            zone.sheltered[idx] = True
        zone.tick = 0
        return zone

    def counts(self) -> dict[str, int]:
        """Derived update: recount live agents by state."""
        bc = np.bincount(self.state, minlength=N_STATES)
        return {name: int(bc[code]) for code, name in enumerate(STATE_NAMES)}

    def living_count(self) -> int:
        return int(self.n - np.count_nonzero(self.state == D))

    # ------------------------------------------------------- inter-zone flux
    def add_agents(self, counts: dict[str, int]) -> None:
        """Spawn arriving agents (inter-zone flux in).

        ``counts`` gives how many agents to add per compartment.  Arrivals are
        placed at uniform-random torus positions and inherit the optional
        shelter flag with the configured probability, so density stays uniform.
        """
        new_states = []
        for code, name in enumerate(STATE_NAMES):
            new_states.extend([code] * int(counts.get(name, 0)))
        if not new_states:
            return
        k = len(new_states)
        new_state = np.array(new_states, dtype=np.int8)
        new_pos = self.rng.uniform(0.0, self.L, size=(k, 2))
        new_shelter = np.zeros(k, dtype=bool)
        if self.params.shelter_fraction > 0:
            new_shelter = self.rng.random(k) < self.params.shelter_fraction
        self.state = np.concatenate([self.state, new_state])
        self.pos = np.concatenate([self.pos, new_pos])
        self.sheltered = np.concatenate([self.sheltered, new_shelter])
        self.n += k

    def remove_agents(self, counts: dict[str, int]) -> None:
        """Despawn departing agents (inter-zone flux out).

        Removes up to ``counts[name]`` randomly-chosen agents from each
        compartment (clamped to those present).  Returns nothing; the caller
        tracks the macro-side ledger.
        """
        drop = np.zeros(self.n, dtype=bool)
        for code, name in enumerate(STATE_NAMES):
            want = int(counts.get(name, 0))
            if want <= 0:
                continue
            members = np.where(self.state == code)[0]
            if members.size == 0:
                continue
            k = min(want, members.size)
            chosen = self.rng.choice(members, size=k, replace=False)
            drop[chosen] = True
        if not drop.any():
            return
        keep = ~drop
        self.state = self.state[keep]
        self.pos = self.pos[keep]
        self.sheltered = self.sheltered[keep]
        self.n = int(self.state.size)

    def reconcile_to_counts(self, target: dict[str, int]) -> None:
        """Add/remove agents so each compartment matches ``target`` exactly.

        Used by the orchestrator to realise a promoted zone's post-tick counts
        (internal agent dynamics + inter-zone flux) on the agent population, so
        next tick the agents remain a faithful realisation of the macro ledger.
        """
        cur = self.counts()
        add: dict[str, int] = {}
        rem: dict[str, int] = {}
        for name in STATE_NAMES:
            diff = int(target.get(name, 0)) - cur[name]
            if diff > 0:
                add[name] = diff
            elif diff < 0:
                rem[name] = -diff
        if rem:
            self.remove_agents(rem)
        if add:
            self.add_agents(add)

    def seed_infection(self, n_exposed: int) -> None:
        """Inject ``n_exposed`` initial E among the susceptibles (outbreak seed)."""
        sus = np.where(self.state == S)[0]
        k = min(n_exposed, sus.size)
        chosen = self.rng.choice(sus, size=k, replace=False)
        self.state[chosen] = E

    # --------------------------------------------------------------- one tick
    def _move(self) -> None:
        p = self.params
        if p.well_mixed:
            self.pos = self.rng.uniform(0.0, self.L, size=(self.n, 2))
            return
        step = p.mixing_step_frac * self.L
        self.pos += self.rng.normal(0.0, step, size=(self.n, 2))
        self.pos %= self.L  # torus wrap

    def _infectious_weight(self) -> np.ndarray:
        """Per-agent infectiousness weight (I_s = 1, I_a = rel, else 0)."""
        w = np.zeros(self.n, dtype=float)
        w[self.state == IS] = 1.0
        w[self.state == IA] = self.params.rel_infectious_asymp
        # Sheltered infectious agents emit less (consistent with macro shelter).
        if self.params.shelter_fraction > 0:
            cut = 1.0 - self.params.shelter_effectiveness
            w[self.sheltered] *= cut
        return w

    def _neighbour_infectious_load(self, inf_w: np.ndarray) -> np.ndarray:
        """For every susceptible, the sum of infectious weights within radius r
        on the torus.

        Vectorised over the *emitters* (infectious agents) only: the pairwise
        susceptible-vs-infectious torus distance is computed with numpy
        broadcasting and thresholded at r.  Because only infectious agents emit
        and only susceptibles can be infected, the (K x M) block is small for
        almost the whole arc (M is tiny early, K is tiny late), so this is both
        exact (true circular radius) and fast.
        """
        L, r = self.L, self.r
        emit = inf_w > 0
        sus = self.state == S
        load = np.zeros(self.n, dtype=float)
        if not emit.any() or not sus.any():
            return load

        P = self.pos[emit]          # (M, 2) emitter positions
        w = inf_w[emit]             # (M,)   emitter weights
        Q = self.pos[sus]           # (K, 2) susceptible positions

        dx = np.abs(Q[:, 0:1] - P[None, :, 0])
        dx = np.minimum(dx, L - dx)          # torus wrap on x
        dy = np.abs(Q[:, 1:2] - P[None, :, 1])
        dy = np.minimum(dy, L - dy)          # torus wrap on y
        within = (dx * dx + dy * dy) <= r * r
        load[sus] = (within * w[None, :]).sum(axis=1)
        return load

    def step(self) -> None:
        g, p, dt = self.genome, self.params, self.dt
        rng = self.rng

        self._move()

        # --- Proximity transmission (the only calibrated step) -------------
        if p.contact_prob is not None:
            contact_p = p.contact_prob
        else:
            contact_p = analytic_contact_prob(g.beta(), self.living_count(), p)

        inf_w = self._infectious_weight()
        if inf_w.any():
            load = self._neighbour_infectious_load(inf_w)
            # dt-independent hazard: prob = 1 - exp(-p * load * dt).
            prob = 1.0 - np.exp(-contact_p * load * dt)
            sus = self.state == S
            draw = rng.random(self.n) < prob
            self.state[sus & draw] = E

        # --- Non-infection transitions: per-agent draws with the EXACT macro
        #     per-tick probabilities, so expectations match the macro update. --
        sigma = 1.0 / g.incubation_period
        omega = 1.0 / g.symptom_onset_delay
        gamma = 1.0 / g.infectious_period
        a = g.asymptomatic_fraction

        # E -> I_a
        e_idx = np.where(self.state == E)[0]
        if e_idx.size:
            move = rng.random(e_idx.size) < sigma * dt
            self.state[e_idx[move]] = IA

        # I_a -> I_s (rate omega*(1-a)) competing with I_a -> R (rate gamma*a),
        # exactly mirroring the macro's aggregate Ia exits applied per agent.
        ia_idx = np.where(self.state == IA)[0]
        if ia_idx.size:
            u = rng.random(ia_idx.size)
            p_to_is = omega * (1.0 - a) * dt
            p_to_r = gamma * a * dt
            to_is = u < p_to_is
            to_r = (u >= p_to_is) & (u < p_to_is + p_to_r)
            self.state[ia_idx[to_is]] = IS
            self.state[ia_idx[to_r]] = R

        # I_s -> R / D (rate gamma; a mortality_fraction of leavers die).
        is_idx = np.where(self.state == IS)[0]
        if is_idx.size:
            leave = rng.random(is_idx.size) < gamma * dt
            leavers = is_idx[leave]
            if leavers.size:
                die = rng.random(leavers.size) < g.mortality_fraction
                self.state[leavers[die]] = D
                self.state[leavers[~die]] = R

        self.tick += 1


def run_micro(genome: PathogenGenome, params: MicroParams, dt: float,
              n_days: float, seed: int = 0, seed_exposed: int = 10) -> dict:
    """Run one micro realisation; return per-tick compartment counts.

    Returns a dict with arrays ``day`` and one array per compartment name, each
    of length n_ticks+1 (including the initial state).
    """
    n_ticks = int(round(n_days / dt))
    zone = AgentZone(genome, params, dt, seed=seed)
    zone.seed_infection(seed_exposed)

    series = {name: np.empty(n_ticks + 1, dtype=float) for name in STATE_NAMES}
    days = np.empty(n_ticks + 1, dtype=float)

    def record(k):
        c = zone.counts()
        for name in STATE_NAMES:
            series[name][k] = c[name]
        days[k] = k * dt

    record(0)
    for k in range(1, n_ticks + 1):
        zone.step()
        record(k)

    out = {"day": days}
    out.update(series)
    return out


def run_micro_ensemble(genome: PathogenGenome, params: MicroParams, dt: float,
                       n_days: float, seeds: list[int],
                       seed_exposed: int = 10) -> dict:
    """Run many seeds and return mean + std bands per compartment.

    The ``seeds`` list is the (reproducible) suite for the expectation estimate;
    it is logged in the returned dict.
    """
    runs = [run_micro(genome, params, dt, n_days, seed=s, seed_exposed=seed_exposed)
            for s in seeds]
    days = runs[0]["day"]
    agg = {"day": days, "seeds": list(seeds), "n_seeds": len(seeds)}
    for name in STATE_NAMES:
        stack = np.vstack([r[name] for r in runs])   # (n_seeds, n_ticks+1)
        agg[name + "_mean"] = stack.mean(axis=0)
        agg[name + "_std"] = stack.std(axis=0, ddof=1) if len(seeds) > 1 else np.zeros_like(days)
        agg[name + "_all"] = stack
    return agg

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
from . import npc
from . import embodiment
from .affordances import advertise
from .roster import Roster


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
                 start_hour: float = 0.0,
                 max_roster: int = 64,
                 proximity_ticks: int = 8,
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

        # --- Phase 11 / M2: citizen identity + schedule activity ---------------
        # The in-game clock the citizen schedule runs on. Purely presentational:
        # advancing the hour updates activity *labels*, never the epidemic.
        self.start_hour = float(start_hour)
        # citizen_id -> CitizenProfile (or dict); zone -> sorted eligible ids.
        self.citizens: dict[int, object] = {}
        self._zone_citizens: dict[int, list[int]] = {}
        self._schedules: dict[int, list] = {}      # citizen_id -> schedule
        # Package 2: per-citizen spatial anchors (home/work coords + zones) and
        # the static city geometry used to resolve authoritative physical
        # locations. `spatial_ctx` is optional bundle geometry; without it,
        # embodiment falls back to zone-centre / synthetic anchors (still
        # deterministic, still calibration-neutral).
        self._spatial: dict[int, tuple] = {}       # cid -> (home_xy,work_xy,hz,wz)
        self.spatial_ctx = None
        # Package 3: the authoritative survival-resource runtime (player state,
        # container world-delta store, dropped items). Created on demand so a
        # bare epidemiological world carries no survival cost. Its needs tick is
        # advanced with the world but is entirely separate from the epidemic.
        self.survival = None

        # --- M3 / SP2: reactive affordances ------------------------------------
        # Optional per-citizen environment/hazard tags the affordance layer reads,
        # and the set of citizens currently inside an authored signature moment
        # (whose reaction is FORCED to `signature`, the Oblivion guard). Both are
        # book-keeping only: reactions are pure `chosen_action` labels and never
        # touch the epidemic (the certified belief-driven shelter channel is
        # unchanged), so SP2 is bit-identical to SP1.
        self._citizen_tags: dict[int, list] = {}
        self._signature_citizens: set[int] = set()
        self.reactions_enabled = True

        # --- M4 / SP3: bounded persistent named roster + uprezzing -------------
        # The few citizens the player engages persist across promote/demote; the
        # rest are anonymous fill. Promotion is event-driven (interaction / focus
        # proximity / signature-in-view); eviction is LRU-by-interaction. The bound
        # is hard, so persistence cost is independent of city size.
        self.roster = Roster(max_roster=max_roster)
        self.proximity_ticks = int(proximity_ticks)
        self._proximity: dict[int, int] = {}   # citizen_id -> consecutive ticks in focus

    # ------------------------------------------------------------------ inputs
    def set_focus(self, zones) -> None:
        """Set the player-focus set: these zones are force-promoted (camera)."""
        self.focus = set(int(z) for z in zones)

    def set_citizens(self, citizens) -> None:
        """Register the citizen population that promoted agents may embody (M2).

        ``citizens`` is an iterable of :class:`~asphodel.citizen.CitizenProfile`
        (or dicts with the same fields). Each contributes an identity assignable
        to a promoted agent slot in its ``home_zone``. This is a pure book-keeping
        step: it registers *who could be embodied where*, and never touches macro
        compartments, the RNG, or any promoted zone that already exists.

        Assignment itself happens at promotion (deterministically, RNG-free), so
        a world with citizens registered is epidemiologically identical to one
        without — the identity layer is calibration-neutral by construction.
        """
        self.citizens = {}
        self._zone_citizens = {}
        self._schedules = {}
        self._spatial = {}
        for c in citizens:
            cid, home_zone, schedule = _citizen_fields(c)
            if cid is None or home_zone is None:
                continue
            self.citizens[cid] = c
            self._schedules[cid] = schedule
            self._spatial[cid] = _citizen_spatial_fields(c, home_zone)
            self._zone_citizens.setdefault(int(home_zone), []).append(cid)
        # Deterministic assignment order within a zone: ascending citizen id.
        for z in self._zone_citizens:
            self._zone_citizens[z].sort()

    def current_hour(self) -> float:
        """The in-game hour [0,24) at the current authoritative tick."""
        return npc.hour_of_day(self.sim.tick, self.dt, self.start_hour)

    # ------------------------------------------------------- Package 2: embodiment
    def set_spatial_context(self, ctx) -> None:
        """Attach the static city geometry (a :class:`embodiment.CitySpatialContext`)
        used to resolve authoritative physical locations. Optional and purely a
        read source — attaching or omitting it never changes the epidemic."""
        self.spatial_ctx = ctx

    def ensure_survival(self):
        """Return the authoritative :class:`~asphodel.survival.Survival` runtime,
        creating it (seeded by the world seed) on first use."""
        if self.survival is None:
            from .survival import Survival
            self.survival = Survival(world_seed=self._seed)
        return self.survival

    def interior_descriptor(self, building_id: int, gen_version: int | None = None):
        """The authoritative, deterministic interior for a building (immutable base
        geometry). Regenerable from (world seed, building_id, gen_version) + the
        real footprint; introduces no new authoritative state — its fixtures anchor
        to the *existing* containers (building_id, container_index)."""
        from . import interiors
        gv = interiors.INTERIOR_GEN_VERSION if gen_version is None else int(gen_version)
        ctx = self.spatial_ctx
        poly = ctx.building_poly(building_id) if ctx is not None else None
        height = ctx.building_height(building_id) if ctx is not None else 6.0
        road_xy = None
        arch_hint = None
        if ctx is not None and 0 <= building_id < ctx.building_centroids.shape[0]:
            road_xy = ctx.nearest_road_xy(ctx.building_centroids[building_id])
            if hasattr(ctx, "building_arch"):
                arch_hint = ctx.building_arch(building_id)
        return interiors.build_interior(
            building_id, self._seed, poly, height=height, road_xy=road_xy,
            gen_version=gv, arch_hint=arch_hint)

    def interior_state(self, building_id: int, gen_version: int | None = None) -> dict:
        """Interior descriptor + the per-fixture *persistent delta* overlay (which
        fixtures' containers have been searched / are now empty), so a renderer can
        show looted furniture without owning any authority."""
        desc = self.interior_descriptor(building_id, gen_version)
        surv = self.survival
        fixture_state = []
        for f in desc.fixtures:
            searched = empty = False
            if surv is not None:
                key = surv._ckey(building_id, f.container_index)
                searched = key in surv._taken
                empty = len(surv.container_contents(building_id, f.container_index)) == 0
            fixture_state.append({
                "fixture_id": f.fixture_id,
                "container_index": f.container_index,
                "searched": bool(searched), "empty": bool(empty),
            })
        out = desc.to_dict()
        out["fixture_state"] = fixture_state
        # indoor dropped items belonging to this building (see survival.drop_item)
        if surv is not None:
            out["dropped_here"] = [dict(it) for it in surv.dropped
                                   if int(it.get("building_id", -1)) == int(building_id)]
        # Package 5: schedule-aware NPC occupancy — identified citizens whose
        # authoritative physical location resolves *inside* this building, each at
        # a deterministic interior anchor.
        out["occupants"] = self.building_occupants(building_id, desc)
        return out

    def building_occupants(self, building_id: int, descriptor=None) -> list:
        """Identified citizens authoritatively inside ``building_id`` right now,
        each placed at a deterministic interior anchor (Package 5).

        Schedule-aware and calibration-neutral: a citizen counts as an occupant
        only when their *authoritative* physical location (schedule + reaction)
        puts them at this building. Bounded by the registered citizen set; the
        anchor is a pure function, so occupancy is deterministic and survives
        save/load and building unload/reload.
        """
        from . import interiors
        if descriptor is None:
            descriptor = self.interior_descriptor(building_id)
        occ = []
        for cid in self.citizens:
            loc = self.physical_location(cid)
            if loc is None:
                continue
            if loc.mode == embodiment.LocationMode.BUILDING and loc.building_id == int(building_id):
                anchor = interiors.occupant_anchor(descriptor, cid)
                occ.append({
                    "citizen_id": int(cid), "room_id": anchor["room_id"],
                    "x": anchor["x"], "y": anchor["y"],
                    "activity": loc.activity, "action": loc.action,
                    "in_roster": bool(self.roster.contains(cid)),
                })
        occ.sort(key=lambda o: o["citizen_id"])
        return occ

    def _citizen_action(self, cid: int) -> str:
        """The behaviour label to embody for a citizen: its live ``chosen_action``
        if embodied in a promoted zone, else its persisted roster action, else the
        routine default."""
        for zone in self.promoted.values():
            hit = np.where(zone.citizen_id == cid)[0]
            if hit.size:
                return npc.action_name(int(zone.chosen_action[hit[0]]))
        rec = self.roster.get(cid)
        if rec is not None:
            return npc.action_name(int(rec.chosen_action))
        return "continue_schedule"

    def physical_location(self, cid: int):
        """The one canonical :class:`embodiment.PhysicalLocation` for a citizen at
        the current in-game hour, or ``None`` if the citizen is unregistered.

        Pure/derived: reads schedule + spatial anchors + current action + static
        geometry; consumes no RNG and mutates nothing, so it is calibration-neutral
        and deterministic under save/load and promote/demote churn.
        """
        cid = int(cid)
        if cid not in self.citizens:
            return None
        home_xy, work_xy, home_zone, work_zone = self._spatial.get(
            cid, (None, None, None, None))
        # Report the zone the macro currently associates with the citizen (home
        # zone is the stable authoritative association).
        return embodiment.resolve_physical_location(
            citizen_id=cid, schedule=self._schedules.get(cid, []),
            hour=self.current_hour(), home_xy=home_xy, work_xy=work_xy,
            home_zone=home_zone, work_zone=work_zone,
            action=self._citizen_action(cid), zone=home_zone,
            ctx=self.spatial_ctx)

    def set_citizen_tags(self, tags_by_id: dict) -> None:
        """Register per-citizen environment/hazard tags the affordance layer reads
        (e.g. ``{cid: ["fire"]}``). Optional; absent -> only the belief-scaled
        baseline affordances apply."""
        self._citizen_tags = {int(k): list(v) for k, v in tags_by_id.items()}

    def set_signature_citizens(self, ids) -> None:
        """Mark citizens currently inside an authored signature moment. Their
        reaction is forced to ``signature`` and the utility pick is skipped — the
        designed-content-wins guard. Player interventions win the same way,
        implicitly, because they drive the belief field the reactions read."""
        self._signature_citizens = set(int(i) for i in ids)

    def intervene(self, action: str, zones=None, **params) -> None:
        """Apply a player intervention to the world state.

        Actions (``zones`` is an index, an iterable, or None = all zones;
        ignored for the global broadcast):

        * ``broadcast`` (level=1.0) / ``stop_broadcast`` -- drive the official
          belief channel directly (an emergency address), bypassing the
          authority's lag.
        * ``cordon`` / ``lift_cordon`` -- seal zones: no inter-zone infection
          mixing and no fleeing in or out (quarantine).
        * ``shelter_order`` (strength=0.85) / ``lift_shelter_order`` -- impose a
          floor on the sheltering fraction (cuts transmission), regardless of
          belief.
        * ``allocate_staffing`` (amount=0.4) / ``clear_staffing`` -- add a
          staffing bonus that props up power/water against the infra cascade.
        """
        sim = self.sim
        if action == "broadcast":
            sim.broadcast_signal = float(params.get("level", 1.0))
            return
        if action == "stop_broadcast":
            sim.broadcast_signal = 0.0
            return

        z = self._zone_selector(zones)
        if action == "cordon":
            sim.cordoned[z] = True
        elif action == "lift_cordon":
            sim.cordoned[z] = False
        elif action == "shelter_order":
            sim.mandated_shelter[z] = float(params.get("strength", 0.85))
        elif action == "lift_shelter_order":
            sim.mandated_shelter[z] = 0.0
        elif action == "allocate_staffing":
            sim.staffing_support[z] = float(params.get("amount", 0.4))
        elif action == "clear_staffing":
            sim.staffing_support[z] = 0.0
        else:
            raise ValueError(f"unknown intervention {action!r}")

    @staticmethod
    def _zone_selector(zones):
        if zones is None:
            return slice(None)
        if isinstance(zones, (int, np.integer)):
            return [int(zones)]
        return [int(z) for z in zones]

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
        # Couple each promoted zone's agent sheltering to the live macro belief
        # (and any player shelter order), so the tiers stay behaviourally
        # consistent under interventions.
        shelter_vec = self.sim._shelter_fraction()
        for z, zone in self.promoted.items():
            zone.set_shelter_fraction(float(shelter_vec[z]))

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

        # --- 4b. refresh citizen activity labels for the new in-game hour -----
        # Pure label update (no RNG, no movement, no compartment change), so it
        # cannot perturb the epidemic. Done after flux reconciliation so newly
        # arrived/removed agents are accounted for.
        if self.citizens:
            for z, zone in self.promoted.items():
                self._update_zone_activity(z, zone)
                if self.reactions_enabled:
                    self._update_zone_reactions(z, zone)
            self._update_roster_promotion()

        # --- 4c. advance survival needs (Package 3) --------------------------
        # Pure, RNG-free, epidemic-independent: raises hunger/thirst, bleeds
        # health when a need is maxed. Never touches the sim, so it cannot perturb
        # the certified trajectory; it advances in lockstep so resources matter.
        if self.survival is not None:
            self.survival.on_tick(self.dt)

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
                "cordoned": bool(sim.cordoned[z]),
                "shelter_order": float(sim.mandated_shelter[z]),
            })
        agents = {}
        for z, zone in self.promoted.items():
            # Renderer-facing state must be JSON-serializable: convert the numpy
            # position/state arrays to plain nested lists here so json.dumps(
            # world.snapshot()) succeeds regardless of how many zones are
            # promoted. (A binary protocol may later replace this, but the
            # serialization contract -- snapshot() is always json.dumps-able --
            # must hold.)
            agents[z] = {
                "positions": zone.pos.tolist(),
                "state": zone.state.tolist(),
                # M2: citizen identity + schedule activity, aligned with the
                # position/state arrays above. citizen_id == -1 is anonymous fill;
                # activity is an int8 code (see asphodel.npc.ACTIVITY_NAMES).
                "citizen_id": zone.citizen_id.tolist(),
                "activity": zone.activity.tolist(),
                # M3: reactive action label per agent (see npc.ACTION_NAMES).
                "chosen_action": zone.chosen_action.tolist(),
                # M4: which agents are persistent named-roster members.
                "named": [bool(self.roster.contains(int(c))) for c in zone.citizen_id],
                "area_size": zone.L,
            }
            # Package 2: authoritative physical embodiment, aligned per agent.
            # Identified citizens resolve to real world-space (building/road/route)
            # in the same frame Godot renders; anonymous fill is placed in a clearly
            # documented *approximate* mode (torus mapped into the zone cell). The
            # renderer draws identified citizens at world_xy; interpolation between
            # authoritative updates is a presentation choice, never truth.
            agents[z]["embodiment"] = self._zone_embodiment(z, zone)
        out = {
            "day": sim.tick * self.dt, "tick": sim.tick,
            "hour": self.current_hour(),
            "rows": sim.graph.rows, "cols": sim.graph.cols,
            "official_signal": float(sim.official_signal),
            "authority_perceived": float(sim.authority_perceived),
            "zones": zones, "agents": agents,
            "activity_names": list(npc.ACTIVITY_NAMES),
            "action_names": list(npc.ACTION_NAMES),
        }
        if self.citizens:
            out["activity_occupancy"] = self.activity_occupancy()
        if len(self.roster) > 0:
            out["roster"] = [
                {"citizen_id": r.citizen_id,
                 "last_interaction_tick": r.last_interaction_tick,
                 "interactions": r.interactions}
                for r in self.roster.members()
            ]
        # Package 3: authoritative survival state (player + dropped world items).
        if self.survival is not None:
            out["survival"] = self.survival.snapshot()
        return out

    def _zone_embodiment(self, z: int, zone: AgentZone) -> dict:
        """Per-agent authoritative physical embodiment for a promoted zone.

        Returns arrays aligned with ``positions``/``citizen_id``. Identified
        citizens are resolved to real world-space (deterministic, RNG-free);
        anonymous fill gets an approximate world position (documented) so the
        renderer can still place it. ``authoritative`` marks which entries are
        real (identified) vs approximate.
        """
        hour = self.current_hour()
        ctx = self.spatial_ctx
        n = zone.n
        world_xy = [None] * n
        mode = ["outdoors"] * n
        building_id = [-1] * n
        movement = ["stationary"] * n
        authoritative = [False] * n
        for slot in range(n):
            cid = int(zone.citizen_id[slot])
            if cid >= 0 and cid in self.citizens:
                home_xy, work_xy, hz, wz = self._spatial.get(
                    cid, (None, None, None, None))
                loc = embodiment.resolve_physical_location(
                    citizen_id=cid, schedule=self._schedules.get(cid, []),
                    hour=hour, home_xy=home_xy, work_xy=work_xy,
                    home_zone=hz, work_zone=wz,
                    action=npc.action_name(int(zone.chosen_action[slot])),
                    zone=z, ctx=ctx)
                world_xy[slot] = [loc.x, loc.y]
                mode[slot] = loc.mode
                building_id[slot] = loc.building_id
                movement[slot] = loc.movement
                authoritative[slot] = True
            else:
                # Anonymous statistical fill: approximate placement only.
                approx = (ctx.approx_world_xy(z, zone.pos[slot], zone.L)
                          if ctx is not None else None)
                if approx is not None:
                    world_xy[slot] = [float(approx[0]), float(approx[1])]
                else:
                    world_xy[slot] = [float(zone.pos[slot][0]), float(zone.pos[slot][1])]
        return {"world_xy": world_xy, "mode": mode, "building_id": building_id,
                "movement": movement, "authoritative": authoritative,
                "schema_version": embodiment.LOCATION_SCHEMA_VERSION}

    def activity_occupancy(self) -> dict:
        """Per-promoted-zone counts of agents by activity (identity certification).

        ``{zone: {activity_name: count}}`` over identified agents — a measurable
        notion of whether the city has a plausible daily rhythm before anything is
        rendered.
        """
        occ: dict[int, dict] = {}
        for z, zone in self.promoted.items():
            ids = zone.identified_slots()
            if ids.size == 0:
                continue
            counts = {name: 0 for name in npc.ACTIVITY_NAMES}
            acts = zone.activity[ids]
            for code in range(npc.N_ACTIVITIES):
                counts[npc.ACTIVITY_NAMES[code]] = int((acts == code).sum())
            occ[z] = counts
        return occ

    def reaction_occupancy(self) -> dict:
        """Per-promoted-zone counts of identified agents by reactive action.

        ``{zone: {action_name: count}}`` — the measurable signal that citizens
        depart from routine as the world departs from calm.
        """
        occ: dict[int, dict] = {}
        for z, zone in self.promoted.items():
            ids = zone.identified_slots()
            if ids.size == 0:
                continue
            acts = zone.chosen_action[ids]
            counts = {name: 0 for name in npc.ACTION_NAMES}
            for code in range(npc.N_ACTIONS):
                counts[npc.ACTION_NAMES[code]] = int((acts == code).sum())
            occ[z] = counts
        return occ

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

        Player-focused zones are always kept (the camera is non-negotiable) and
        may push the live agent count *over* ``max_live_agents`` -- that is an
        intentional, design-required exception. Every *non-focused* automatic
        promotion, however, is a hard cap: it is admitted only if it fits wholly
        within the remaining budget. A single non-focused candidate that alone
        exceeds ``max_live_agents`` is therefore never promoted, and once forced
        focus zones have consumed the budget no automatic zone is added.

        A zone's agent cost is its current macro living count. The remaining
        budget after focus is filled by descending infectious fraction (the
        zones where agent resolution matters most).
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
            # Hard non-focus cap: no escape hatch for the first candidate. If a
            # single zone would blow the agent budget, it stays macro.
            if (self.max_live_agents is not None
                    and agents + cost > self.max_live_agents):
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
        zone = promote(counts, self.cfg.genome, params, self.dt, seed=seed)
        self._assign_citizens(z, zone)
        self._restore_roster(z, zone)
        self._update_zone_activity(z, zone)
        if self.reactions_enabled:
            self._update_zone_reactions(z, zone)
        self.promoted[z] = zone

    def _assign_citizens(self, z: int, zone: AgentZone) -> None:
        """Deterministically embody eligible citizens on this zone's agent slots.

        RNG-free (uses no ``zone.rng`` draw) and state-free (touches only the
        citizen_id label array), so promotion with citizens registered produces
        the identical epidemic to promotion without them. Eligible citizens are
        this zone's residents in ascending-id order; they fill the first slots,
        the rest stay anonymous (citizen_id == -1).
        """
        eligible = self._zone_citizens.get(z)
        if not eligible:
            return
        # Roster members of this zone are embodied FIRST (they are the ones that
        # must reappear on re-promote), then other residents. Both sub-lists are
        # already ascending-id, so the order is fully deterministic.
        rostered = [c for c in eligible if self.roster.contains(c)]
        others = [c for c in eligible if not self.roster.contains(c)]
        ordered = rostered + others
        k = min(len(ordered), zone.n)
        if k <= 0:
            return
        zone.assign_identities(np.arange(k, dtype=np.int64),
                               np.asarray(ordered[:k], dtype=np.int64))

    def _restore_roster(self, z: int, zone: AgentZone) -> None:
        """Stamp persisted state onto embodied roster members (uprezzing restore).

        Runs after `_assign_citizens`, so a rostered resident is already on a
        slot; here we restore its checkpointed action label. Conservation-safe:
        only labels change, never compartment counts.
        """
        if len(self.roster) == 0:
            return
        for slot in zone.identified_slots():
            cid = int(zone.citizen_id[slot])
            rec = self.roster.get(cid)
            if rec is not None:
                zone.restore_citizen(int(slot), rec)

    def _update_roster_promotion(self) -> None:
        """Event-driven, deterministic roster promotion each tick.

        Two triggers besides the explicit `interact_with`:
        * **signature-in-view** — a signature citizen embodied in a *focused* zone
          is promoted at once (the Nemesis "did something memorable" rule);
        * **sustained focus proximity** — a citizen embodied in a focused zone for
          `proximity_ticks` consecutive ticks is promoted (simply being among
          people long enough names some). Counters reset when a citizen leaves
          focus, so "sustained" means consecutive. Iteration is ascending-id, so
          promotion order (and thus any eviction) is deterministic.
        """
        tick = int(self.sim.tick)
        # Who is embodied in a focused, promoted zone right now?
        in_focus: set[int] = set()
        for z in sorted(self.focus):
            zone = self.promoted.get(z)
            if zone is None:
                continue
            for cid in sorted(int(c) for c in zone.citizen_id[zone.identified_slots()]):
                in_focus.add(cid)
                if cid in self._signature_citizens:
                    self.roster.promote(cid, self.citizens.get(cid), tick)
                    continue
                n = self._proximity.get(cid, 0) + 1
                self._proximity[cid] = n
                if n >= self.proximity_ticks:
                    self.roster.promote(cid, self.citizens.get(cid), tick)
        # Reset proximity for citizens no longer in focus (consecutive-only).
        for cid in list(self._proximity):
            if cid not in in_focus:
                del self._proximity[cid]

    def interact_with(self, citizen_id: int) -> bool:
        """Event-driven promotion: the player profiled/talked to this citizen.

        The primary roster trigger (the Nemesis/Census "you engaged it" rule).
        Returns True if a new roster member was added. If the citizen is currently
        embodied in a promoted zone, its live action label is captured at once.
        """
        cid = int(citizen_id)
        profile = self.citizens.get(cid)
        added = self.roster.promote(cid, profile, int(self.sim.tick))
        for zone in self.promoted.values():
            hit = np.where(zone.citizen_id == cid)[0]
            if hit.size:
                self.roster.set_state(cid,
                                      chosen_action=int(zone.chosen_action[hit[0]]))
                break
        return added

    def _update_zone_activity(self, z: int, zone: AgentZone) -> None:
        """Refresh the zone's activity label array from citizen schedules + hour.

        Pure label update: no RNG, no movement, no compartment change. Anonymous
        agents stay IDLE. This is the M2 "activity is a logical label, not
        physical clustering" rule made literal.
        """
        ids = zone.identified_slots()
        if ids.size == 0:
            return
        hour = self.current_hour()
        acts = zone.activity
        for slot in ids:
            cid = int(zone.citizen_id[slot])
            sched = self._schedules.get(cid)
            acts[slot] = npc.activity_at_hour(sched, hour) if sched else npc.IDLE

    def _update_zone_reactions(self, z: int, zone: AgentZone) -> None:
        """Compute each identified agent's reactive ``chosen_action`` for the live
        belief field (M3 / SP2).

        Pure label update: uses a per-citizen seeded RNG (never ``zone.rng``),
        touches neither ``pos``/``state`` nor the sheltered set, so it cannot
        perturb the epidemic. Signature citizens are forced to ``signature``
        (designed content wins). Anonymous agents keep ``continue_schedule``.
        """
        ids = zone.identified_slots()
        if ids.size == 0:
            return
        belief_z = float(self.sim.belief[z])
        needs = npc.default_needs(safety=belief_z)
        tick = int(self.sim.tick)
        act_arr = zone.chosen_action
        for slot in ids:
            cid = int(zone.citizen_id[slot])
            if cid in self._signature_citizens:
                act_arr[slot] = npc.SIGNATURE
                continue
            tags = self._citizen_tags.get(cid)
            ads = advertise(tags, belief_z)
            # Per-citizen deterministic stream: keyed by (citizen, tick, world
            # seed); explicitly NOT AgentZone.rng, so the curve stays identical.
            rng = np.random.default_rng([cid, tick, self._seed])
            act_arr[slot] = npc.action_code(npc.choose_action(ads, needs, rng))

    def _demote_zone(self, z: int) -> None:
        # M4 uprezzing: before dropping the agent zone, checkpoint any rostered
        # members' live action label so re-promote restores them faithfully. The
        # macro ledger already holds this zone's latest agent-derived counts, so
        # demotion otherwise just stops freezing it -- no population merge needed,
        # and the checkpoint changes no compartment count (conservation holds).
        zone = self.promoted.get(z)
        if zone is not None and len(self.roster) > 0:
            for slot in zone.identified_slots():
                cid = int(zone.citizen_id[slot])
                if self.roster.contains(cid):
                    # tick=None: leaving is not an interaction (LRU stays honest).
                    self.roster.set_state(
                        cid, chosen_action=int(zone.chosen_action[slot]), tick=None)
        self.promoted.pop(z, None)

    def _write_zone(self, z: int, counts: dict[str, float]) -> None:
        for name in STATE_NAMES:
            getattr(self.sim, _attr(name))[z] = counts[name]


def _attr(name: str) -> str:
    """Map a STATE_NAMES entry to the Simulation array attribute name."""
    return name  # S,E,Ia,Is,R,D match the Simulation attribute names exactly


def _citizen_fields(c):
    """Extract (citizen_id, home_zone, schedule) from a CitizenProfile or dict.

    Accepts a :class:`~asphodel.citizen.CitizenProfile` (attribute access) or a
    plain dict (e.g. a row from a baked ``citizens.json``). Returns
    ``(None, None, [])`` when identity/home cannot be resolved.
    """
    if isinstance(c, dict):
        cid = c.get("citizen_id")
        home = c.get("home_zone")
        schedule = c.get("schedule", []) or []
    else:
        cid = getattr(c, "citizen_id", None)
        home = getattr(c, "home_zone", None)
        schedule = getattr(c, "schedule", []) or []
    if cid is None:
        return None, None, []
    return int(cid), (None if home is None else int(home)), schedule


def _citizen_spatial_fields(c, home_zone):
    """Extract (home_xy, work_xy, home_zone, work_zone) from a CitizenProfile or
    dict. Coordinates are the real bundle map frame (metres) when present; missing
    coordinates fall back to zone-centre resolution at embodiment time."""
    def _get(name):
        if isinstance(c, dict):
            return c.get(name)
        return getattr(c, name, None)

    def _xy(v):
        if v is None:
            return None
        try:
            return (float(v[0]), float(v[1]))
        except (TypeError, ValueError, IndexError):
            return None

    wz = _get("work_zone")
    return (_xy(_get("home_xy")), _xy(_get("work_xy")),
            (None if home_zone is None else int(home_zone)),
            (None if wz is None else int(wz)))

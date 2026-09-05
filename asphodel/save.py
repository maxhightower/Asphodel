"""Deterministic, versioned save/load for the authoritative world (M5).

The whole authoritative runtime — macro simulation, promoted agent zones, the
named roster, orchestrator book-keeping, and the game identity — is captured into
an **explicit JSON-serializable schema** (never an opaque pickle), so a world can
be saved, the process destroyed, and the world reloaded and continued **bit-for-
bit identically** to an uninterrupted run.

The three load-bearing rules:

* **Explicit schema, explicit version.** Every save carries ``save_version``. A
  future/incompatible version is *rejected*, never silently misread.
* **Every RNG stream is captured.** The macro ``Simulation.rng`` and each
  ``AgentZone.rng`` bit-generator state are saved and restored exactly, which is
  what makes continuation deterministic.
* **JSON-safe.** numpy arrays become lists, the authority lag buffer becomes a
  list, RNG states are plain dicts (with big ints, which JSON handles).

Godot requests save/load over the bridge; Python performs the authoritative
serialization here.
"""

from __future__ import annotations

import json

import numpy as np

from .config import ScenarioConfig, MicroParams, PathogenGenome, HandoffParams
from .orchestrator import World
from .micro import AgentZone
from .roster import Roster, RosterRecord
from .citizen import ScheduleEntry


# v1: authoritative world (macro + agents + roster + citizens).
# v2: + Package 3 survival runtime (player state, container deltas, dropped items).
#     v1 saves are accepted via an explicit migration (survival starts empty).
SAVE_VERSION = 2
_READABLE_VERSIONS = (1, 2)


class SaveError(Exception):
    """Raised when a save cannot be read/validated (corrupt or incompatible)."""


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _arr(a) -> list:
    return np.asarray(a).tolist()


def _rng_state(rng) -> dict:
    return rng.bit_generator.state


def _set_rng_state(rng, state) -> None:
    rng.bit_generator.state = state


# --------------------------------------------------------------------------- #
# Simulation (macro)
# --------------------------------------------------------------------------- #
_SIM_ARRAYS = ("S", "E", "Ia", "Is", "R", "D", "belief", "staffing",
               "power_ok", "water_ok", "cordoned", "mandated_shelter",
               "staffing_support")
_SIM_SCALARS = ("broadcast_signal", "official_signal", "authority_perceived", "tick")


def sim_state(sim) -> dict:
    return {
        "arrays": {name: _arr(getattr(sim, name)) for name in _SIM_ARRAYS},
        "scalars": {name: _num(getattr(sim, name)) for name in _SIM_SCALARS},
        "authority_buffer": [float(x) for x in sim._authority_buffer],
        "events_log": list(sim.events_log),
        "rng": _rng_state(sim.rng),
    }


def restore_sim(sim, state) -> None:
    for name in _SIM_ARRAYS:
        ref = getattr(sim, name)
        setattr(sim, name, np.asarray(state["arrays"][name], dtype=ref.dtype))
    for name in _SIM_SCALARS:
        cur = getattr(sim, name)
        setattr(sim, name, type(cur)(state["scalars"][name]))
    sim._authority_buffer.clear()
    sim._authority_buffer.extend(float(x) for x in state["authority_buffer"])
    sim.events_log = list(state["events_log"])
    _set_rng_state(sim.rng, state["rng"])


def _num(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    return float(v)


# --------------------------------------------------------------------------- #
# AgentZone (micro)
# --------------------------------------------------------------------------- #
def agentzone_state(zone: AgentZone) -> dict:
    from dataclasses import asdict
    return {
        "n": int(zone.n),
        "L": float(zone.L),
        "r": float(zone.r),
        "dt": float(zone.dt),
        "seed": int(zone.seed),
        "tick": int(zone.tick),
        "params": asdict(zone.params),
        "pos": _arr(zone.pos),
        "state": _arr(zone.state),
        "sheltered": _arr(zone.sheltered),
        "citizen_id": _arr(zone.citizen_id),
        "activity": _arr(zone.activity),
        "chosen_action": _arr(zone.chosen_action),
        "rng": _rng_state(zone.rng),
    }


def restore_agentzone(genome: PathogenGenome, state: dict) -> AgentZone:
    zone = AgentZone.__new__(AgentZone)
    zone.genome = genome
    zone.params = MicroParams(**state["params"])
    zone.dt = float(state["dt"])
    zone.seed = int(state["seed"])
    zone.rng = np.random.default_rng(zone.seed)
    _set_rng_state(zone.rng, state["rng"])
    zone.n = int(state["n"])
    zone.L = float(state["L"])
    zone.r = float(state["r"])
    zone.pos = np.asarray(state["pos"], dtype=float)
    zone.state = np.asarray(state["state"], dtype=np.int8)
    zone.sheltered = np.asarray(state["sheltered"], dtype=bool)
    zone.citizen_id = np.asarray(state["citizen_id"], dtype=np.int64)
    zone.activity = np.asarray(state["activity"], dtype=np.int8)
    zone.chosen_action = np.asarray(state["chosen_action"], dtype=np.int8)
    zone.tick = int(state["tick"])
    return zone


# --------------------------------------------------------------------------- #
# Roster (NPC layer)
# --------------------------------------------------------------------------- #
def roster_state(roster: Roster) -> dict:
    return {
        "max_roster": int(roster.max_roster),
        "members": [
            {"citizen_id": r.citizen_id, "needs": r.needs,
             "chosen_action": r.chosen_action, "schedule_cursor": r.schedule_cursor,
             "last_interaction_tick": r.last_interaction_tick,
             "promoted_tick": r.promoted_tick, "interactions": r.interactions}
            for r in roster.members()
        ],
    }


def restore_roster(state: dict, profiles: dict) -> Roster:
    roster = Roster(max_roster=int(state["max_roster"]))
    for m in state["members"]:
        cid = int(m["citizen_id"])
        rec = RosterRecord(
            citizen_id=cid, profile=profiles.get(cid),
            needs=dict(m.get("needs", {})),
            chosen_action=int(m.get("chosen_action", 0)),
            schedule_cursor=int(m.get("schedule_cursor", 0)),
            last_interaction_tick=int(m.get("last_interaction_tick", 0)),
            promoted_tick=int(m.get("promoted_tick", 0)),
            interactions=int(m.get("interactions", 0)))
        roster._members[cid] = rec
    return roster


# --------------------------------------------------------------------------- #
# Citizen registration (compact; keeps the save self-contained)
# --------------------------------------------------------------------------- #
class _CitizenLite:
    """A minimal restored citizen: enough for identity assignment, activity, and
    (Package 2) authoritative physical embodiment (home/work coords + zones)."""

    __slots__ = ("citizen_id", "home_zone", "work_zone", "schedule",
                 "home_xy", "work_xy", "home_building_id", "work_building_id")

    def __init__(self, citizen_id, home_zone, schedule,
                 work_zone=None, home_xy=None, work_xy=None,
                 home_building_id=None, work_building_id=None):
        self.citizen_id = citizen_id
        self.home_zone = home_zone
        self.work_zone = work_zone
        self.schedule = schedule
        self.home_xy = home_xy
        self.work_xy = work_xy
        self.home_building_id = home_building_id
        self.work_building_id = work_building_id


def _xy_or_none(prof, name):
    v = getattr(prof, name, None) if not isinstance(prof, dict) else prof.get(name)
    if v is None:
        return None
    try:
        return [float(v[0]), float(v[1])]
    except (TypeError, ValueError, IndexError):
        return None


def _citizen_records(world: World) -> list:
    out = []
    for cid, prof in world.citizens.items():
        sched = world._schedules.get(cid, [])
        home_xy, work_xy, hz, wz = world._spatial.get(cid, (None, None, None, None))
        hb, wb = world._buildings.get(cid, (None, None))
        out.append({
            "citizen_id": int(cid),
            "home_building_id": (None if hb is None else int(hb)),
            "work_building_id": (None if wb is None else int(wb)),
            "home_zone": (None if hz is None else int(hz)),
            "work_zone": (None if wz is None else int(wz)),
            "home_xy": (None if home_xy is None else [float(home_xy[0]), float(home_xy[1])]),
            "work_xy": (None if work_xy is None else [float(work_xy[0]), float(work_xy[1])]),
            "schedule": [[float(e.start_hour), float(e.end_hour), e.activity,
                          getattr(e, "location", ""), getattr(e, "task", "")]
                         for e in sched],
        })
    return out


def _restore_citizens(records: list) -> list:
    out = []
    for r in records:
        sched = [ScheduleEntry(start_hour=s[0], end_hour=s[1], activity=s[2],
                               location=s[3] if len(s) > 3 else "",
                               task=s[4] if len(s) > 4 else "")
                 for s in r.get("schedule", [])]
        hx = r.get("home_xy")
        wx = r.get("work_xy")
        out.append(_CitizenLite(
            int(r["citizen_id"]), r.get("home_zone"), sched,
            work_zone=r.get("work_zone"),
            home_xy=(tuple(hx) if hx else None),
            work_xy=(tuple(wx) if wx else None),
            home_building_id=r.get("home_building_id"),
            work_building_id=r.get("work_building_id")))
    return out


# --------------------------------------------------------------------------- #
# World (the whole authoritative runtime)
# --------------------------------------------------------------------------- #
def world_state(world: World, *, bundle: str | None = None,
                player_citizen: int | None = None) -> dict:
    """Capture the entire authoritative world into a versioned schema dict."""
    from dataclasses import asdict
    return {
        "save_version": SAVE_VERSION,
        "game_identity": {
            "bundle": bundle,
            "player_citizen": player_citizen,
            "name": world.cfg.name,
        },
        "config": asdict(world.cfg),
        "world": {
            "seed": int(world._seed),
            "promo_counter": int(world._promo_counter),
            "start_hour": float(world.start_hour),
            "max_live_zones": world.max_live_zones,
            "max_live_agents": world.max_live_agents,
            "ref_density": float(world.ref_density),
            "focus": sorted(int(z) for z in world.focus),
            "reactions_enabled": bool(world.reactions_enabled),
            "proximity_ticks": int(world.proximity_ticks),
            "proximity": {str(k): int(v) for k, v in world._proximity.items()},
            "signature_citizens": sorted(int(c) for c in world._signature_citizens),
            "citizen_tags": {str(k): list(v) for k, v in world._citizen_tags.items()},
            "micro_params": asdict(world.micro_params),
            "handoff": asdict(world.handoff),
        },
        "sim": sim_state(world.sim),
        "promoted": {str(z): agentzone_state(zone)
                     for z, zone in world.promoted.items()},
        "roster": roster_state(world.roster),
        "citizens": _citizen_records(world),
        # Package 3: survival runtime (None when the world has no survival loop).
        "survival": (world.survival.to_state() if world.survival is not None
                     else None),
    }


def load_world(state: dict) -> World:
    """Reconstruct an authoritative World from a save-schema dict."""
    _validate(state)
    cfg = ScenarioConfig.from_dict(state["config"])
    w = state["world"]
    world = World(
        cfg,
        micro_params=MicroParams(**w["micro_params"]),
        handoff=HandoffParams(**w["handoff"]),
        ref_density=w["ref_density"],
        max_live_zones=w["max_live_zones"],
        max_live_agents=w["max_live_agents"],
        start_hour=w["start_hour"],
        max_roster=int(state["roster"]["max_roster"]),
        proximity_ticks=int(w["proximity_ticks"]),
        seed=int(w["seed"]),
    )
    # Macro simulation state (arrays, scalars, rng, authority buffer, tick).
    restore_sim(world.sim, state["sim"])
    # Orchestrator book-keeping.
    world._promo_counter = int(w["promo_counter"])
    world.focus = set(int(z) for z in w["focus"])
    world.reactions_enabled = bool(w["reactions_enabled"])
    world._proximity = {int(k): int(v) for k, v in w["proximity"].items()}
    world._signature_citizens = set(int(c) for c in w["signature_citizens"])
    world._citizen_tags = {int(k): list(v) for k, v in w["citizen_tags"].items()}
    # Citizen registration (rebuilds citizens / schedules / zone index).
    if state.get("citizens"):
        world.set_citizens(_restore_citizens(state["citizens"]))
    # Roster (linked to restored profiles).
    world.roster = restore_roster(state["roster"], world.citizens)
    # Promoted agent zones (full identity + rng).
    world.promoted = {}
    for z_str, zstate in state["promoted"].items():
        world.promoted[int(z_str)] = restore_agentzone(cfg.genome, zstate)
    # Package 3: survival runtime. Present in v2 saves; a v1 save (or an explicit
    # null) migrates to "no survival loop yet" — not silently misread, just absent.
    surv = state.get("survival")
    if surv:
        from .survival import Survival
        world.survival = Survival.from_state(surv)
    return world


# --------------------------------------------------------------------------- #
# file I/O + validation
# --------------------------------------------------------------------------- #
def save_world(world: World, path: str, *, bundle: str | None = None,
               player_citizen: int | None = None) -> None:
    state = world_state(world, bundle=bundle, player_citizen=player_citizen)
    with open(path, "w") as f:
        json.dump(state, f)


def load_world_file(path: str) -> World:
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        raise SaveError(f"cannot read save file: {e}") from e
    return load_world(state)


def _validate(state) -> None:
    if not isinstance(state, dict):
        raise SaveError("save is not an object")
    v = state.get("save_version")
    if v is None:
        raise SaveError("save is missing 'save_version'")
    if int(v) not in _READABLE_VERSIONS:
        raise SaveError(
            f"incompatible save_version {v} (this build reads {_READABLE_VERSIONS}); "
            f"no migration path is defined")
    for key in ("config", "world", "sim", "promoted", "roster"):
        if key not in state:
            raise SaveError(f"save is missing required section '{key}'")

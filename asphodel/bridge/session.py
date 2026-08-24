"""The authoritative command processor (M1).

:class:`WorldSession` owns one :class:`~asphodel.orchestrator.World` and turns a
protocol *request dict* into a *response dict*. It is deliberately transport-free
so it can be driven directly in tests and wrapped by any framing
(:mod:`asphodel.bridge.server` puts it on a socket).

Invariants this class enforces (M1 exit gate):

* **The world advances only, and exactly, on ``ADVANCE``.** No other command
  steps the simulation; ``SNAPSHOT``/``SET_FOCUS``/``INTERVENE`` never advance.
* **Pause freezes advancement.** ``ADVANCE`` while paused is refused (there is no
  hidden Python free-running behind a paused client).
* **Malformed input never crashes the session** -- it returns an error envelope.
* **Determinism** is inherited from ``World``: the same command stream against the
  same ``(bundle, seed, budget)`` yields the same authoritative trajectory,
  because the only nondeterminism-free entry point (``ADVANCE``) is a pure
  function of prior state.
"""

from __future__ import annotations

from dataclasses import replace

from ..config import MicroParams
from ..micro import STATE_NAMES
from . import protocol as P
from .protocol import Command, ErrorCode
from .worldfactory import world_from_bundle, bundle_summary


class WorldSession:
    """Owns the authoritative world and processes protocol requests."""

    def __init__(self) -> None:
        self.world = None
        self.paused = False
        self.should_stop = False
        self.hello_ok = False
        self.bundle = None
        self.seed = None
        self.player_citizen = None

    # ------------------------------------------------------------------ dispatch
    def handle(self, msg) -> dict:
        """Process one request dict, return one response dict. Never raises."""
        if not isinstance(msg, dict):
            return P.error_response(ErrorCode.MALFORMED,
                                    "request must be a JSON object")
        cmd = msg.get("cmd")
        rid = msg.get("id")
        if not isinstance(rid, int):
            rid = None
        if cmd is None:
            return P.error_response(ErrorCode.MALFORMED, "missing 'cmd'", id=rid)
        if cmd not in Command.ALL:
            return P.error_response(ErrorCode.UNKNOWN_COMMAND,
                                    f"unknown command {cmd!r}", cmd=cmd, id=rid)

        handler = getattr(self, f"_cmd_{cmd.lower()}")
        try:
            return handler(msg, rid)
        except _NoWorld as e:
            return P.error_response(ErrorCode.NOT_STARTED, str(e), cmd=cmd, id=rid)
        except _BadArg as e:
            return P.error_response(ErrorCode.BAD_ARGUMENT, str(e), cmd=cmd, id=rid)
        except Exception as e:  # engine blew up -- surface, do not crash the loop
            return P.error_response(ErrorCode.INTERNAL,
                                    f"{type(e).__name__}: {e}", cmd=cmd, id=rid)

    # ------------------------------------------------------------------ commands
    def _cmd_hello(self, msg, rid) -> dict:
        cv = msg.get("protocol_version")
        if not isinstance(cv, int):
            return P.error_response(ErrorCode.MALFORMED,
                                    "HELLO requires integer 'protocol_version'",
                                    cmd=Command.HELLO, id=rid)
        if not P.is_compatible(cv):
            return P.error_response(
                ErrorCode.VERSION_MISMATCH,
                f"client protocol {cv} != server {P.PROTOCOL_VERSION}",
                cmd=Command.HELLO, id=rid)
        self.hello_ok = True
        return P.response(Command.HELLO, id=rid,
                          server="asphodel-bridge",
                          commands=sorted(Command.ALL),
                          started=self.world is not None)

    def _cmd_start_world(self, msg, rid) -> dict:
        if self.world is not None:
            return P.error_response(ErrorCode.ALREADY_STARTED,
                                    "a world is already started; SHUTDOWN first",
                                    cmd=Command.START_WORLD, id=rid)
        bundle = msg.get("bundle")
        if not isinstance(bundle, str) or not bundle:
            raise _BadArg("START_WORLD requires a string 'bundle'")
        seed = _opt_int(msg.get("seed"), "seed")
        max_live_zones = _opt_int(msg.get("max_live_zones"), "max_live_zones")
        max_live_agents = _opt_int(msg.get("max_live_agents"), "max_live_agents")
        micro = _micro_from(msg.get("micro"))
        focus = msg.get("focus")
        # Accept both `player_citizen` and the client's `player_citizen_id`.
        player_citizen = _opt_int(
            msg.get("player_citizen", msg.get("player_citizen_id")), "player_citizen")
        # Real bundles populate World with their own citizens by default; pass
        # citizens:false for a bare epidemiological world (e.g. protocol tests).
        want_citizens = msg.get("citizens", True)

        world = world_from_bundle(
            bundle, seed=seed, micro_params=micro,
            max_live_zones=max_live_zones, max_live_agents=max_live_agents)

        n_citizens = 0
        player_home_zone = None
        if want_citizens:
            from ..bundle_population import load_bundle_population
            from ..embodiment import CitySpatialContext
            from .worldfactory import resolve_bundle_dir
            bundle_dir = resolve_bundle_dir(bundle)
            population = load_bundle_population(bundle_dir)
            world.set_citizens(population)
            # Package 2: attach the bundle's static geometry so identified
            # citizens (and the player) resolve to real buildings/roads. Purely a
            # read source — never perturbs the epidemic.
            try:
                world.set_spatial_context(
                    CitySpatialContext.from_bundle_dir(bundle_dir))
            except Exception:
                pass  # embodiment falls back to zone-centre anchors
            n_citizens = len(population)
            if player_citizen is not None:
                for c in population:
                    if c.citizen_id == player_citizen:
                        player_home_zone = c.home_zone
                        break
                if player_home_zone is None:
                    raise _BadArg(
                        f"player_citizen {player_citizen} not in bundle population "
                        f"(0..{n_citizens - 1})")

        # Focus: explicit request wins; otherwise the player's home zone so their
        # neighbourhood resolves to agents on entry.
        if focus is not None:
            world.set_focus(_zone_list(focus))
        elif player_home_zone is not None:
            world.set_focus([player_home_zone])

        self.world = world
        self.paused = False
        self.bundle = bundle
        self.seed = int(world.cfg.seed)
        self.player_citizen = player_citizen
        return P.response(Command.START_WORLD, id=rid,
                          bundle=bundle_summary(bundle),
                          seed=self.seed,
                          player_citizen=player_citizen,
                          player_home_zone=player_home_zone,
                          seed_zone=int(world.cfg.seed_zone),
                          n_citizens=n_citizens,
                          **self._summary())

    def _cmd_set_focus(self, msg, rid) -> dict:
        self._require_world(Command.SET_FOCUS)
        zones = _zone_list(msg.get("zones", []))
        self.world.set_focus(zones)
        return P.response(Command.SET_FOCUS, id=rid, focus=sorted(zones))

    def _cmd_advance(self, msg, rid) -> dict:
        self._require_world(Command.ADVANCE)
        if self.paused:
            return P.error_response(ErrorCode.PAUSED,
                                    "world is paused; RESUME before ADVANCE",
                                    cmd=Command.ADVANCE, id=rid)
        ticks = msg.get("ticks", 1)
        if not isinstance(ticks, int) or ticks < 0:
            raise _BadArg("ADVANCE 'ticks' must be a non-negative integer")
        for _ in range(ticks):
            self.world.step()
        out = dict(self._summary(), advanced=ticks)
        if msg.get("snapshot"):
            snap = self.world.snapshot()
            self._inject_player_location(snap)
            out["world"] = snap
        return P.response(Command.ADVANCE, id=rid, **out)

    def _cmd_intervene(self, msg, rid) -> dict:
        self._require_world(Command.INTERVENE)
        action = msg.get("action")
        if not isinstance(action, str) or not action:
            raise _BadArg("INTERVENE requires a string 'action'")
        zones = msg.get("zones")
        zsel = _zone_list(zones) if zones is not None else None
        params = {k: v for k, v in msg.items()
                  if k not in ("cmd", "id", "action", "zones")}
        try:
            self.world.intervene(action, zones=zsel, **params)
        except ValueError as e:
            raise _BadArg(str(e))
        return P.response(Command.INTERVENE, id=rid, action=action,
                          zones=(sorted(zsel) if zsel is not None else None))

    def _cmd_interact_with(self, msg, rid) -> dict:
        self._require_world(Command.INTERACT_WITH)
        cid = msg.get("citizen_id")
        if not isinstance(cid, int) or isinstance(cid, bool):
            raise _BadArg("INTERACT_WITH requires an integer 'citizen_id'")
        added = self.world.interact_with(cid)
        return P.response(Command.INTERACT_WITH, id=rid, citizen_id=cid,
                          added=bool(added),
                          in_roster=self.world.roster.contains(cid))

    def _cmd_pause(self, msg, rid) -> dict:
        self._require_world(Command.PAUSE)
        self.paused = True
        return P.response(Command.PAUSE, id=rid, **self._summary())

    def _cmd_resume(self, msg, rid) -> dict:
        self._require_world(Command.RESUME)
        self.paused = False
        return P.response(Command.RESUME, id=rid, **self._summary())

    def _cmd_snapshot(self, msg, rid) -> dict:
        self._require_world(Command.SNAPSHOT)
        snap = self.world.snapshot()
        self._inject_player_location(snap)
        return P.response(Command.SNAPSHOT, id=rid, world=snap)

    def _inject_player_location(self, snap: dict) -> None:
        """Add the player's one authoritative physical location to a snapshot dict
        (Package 2), so the client can place the player coherently with their
        schedule. No-op when no player citizen is set."""
        if self.player_citizen is None or self.world is None:
            return
        loc = self.world.physical_location(self.player_citizen)
        if loc is not None:
            snap["player_location"] = loc.to_dict()

    def _cmd_save(self, msg, rid) -> dict:
        self._require_world(Command.SAVE)
        path = msg.get("path")
        if not isinstance(path, str) or not path:
            raise _BadArg("SAVE requires a string 'path'")
        from ..save import save_world
        save_world(self.world, path, bundle=self.bundle,
                   player_citizen=self.player_citizen)
        return P.response(Command.SAVE, id=rid, path=path, **self._summary())

    def _cmd_load(self, msg, rid) -> dict:
        path = msg.get("path")
        if not isinstance(path, str) or not path:
            raise _BadArg("LOAD requires a string 'path'")
        from ..save import load_world_file, SaveError
        import json as _json
        try:
            world = load_world_file(path)
        except SaveError as e:
            raise _BadArg(str(e))
        self.world = world
        self.paused = False
        # Restore game identity + re-attach the bundle's static geometry so
        # embodiment (Package 2) resolves real buildings/roads after reload.
        try:
            with open(path) as f:
                gi = _json.load(f).get("game_identity", {})
            self.bundle = gi.get("bundle")
            self.player_citizen = gi.get("player_citizen")
            if self.bundle:
                from ..embodiment import CitySpatialContext
                from .worldfactory import resolve_bundle_dir
                world.set_spatial_context(
                    CitySpatialContext.from_bundle_dir(resolve_bundle_dir(self.bundle)))
        except Exception:
            pass
        return P.response(Command.LOAD, id=rid, path=path, **self._summary())

    def _cmd_shutdown(self, msg, rid) -> dict:
        self.should_stop = True
        return P.response(Command.SHUTDOWN, id=rid, bye=True)

    # ------------------------------------------------------------------ helpers
    def _require_world(self, cmd) -> None:
        if self.world is None:
            raise _NoWorld(cmd)

    def _summary(self) -> dict:
        """Cheap authoritative aggregate (no per-zone payload, no advancement)."""
        sim = self.world.sim
        totals = {name: float(getattr(sim, name).sum()) for name in STATE_NAMES}
        return {
            "tick": int(sim.tick),
            "day": float(sim.tick * self.world.dt),
            "paused": self.paused,
            "n_promoted": len(self.world.promoted),
            "promoted": self.world.promoted_zones(),
            "totals": totals,
            "total_pop": float(sum(totals.values())),
        }


# _NoWorld is raised inside handlers and converted to a NOT_STARTED error by the
# dispatcher's generic path -- but we want a specific code, so catch it there.
class _BadArg(Exception):
    pass


class _NoWorld(Exception):
    def __init__(self, cmd):
        self.cmd = cmd
        super().__init__(f"{cmd} requires a started world")


# ------------------------------------------------------------------ arg parsing
def _opt_int(v, name):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise _BadArg(f"{name!r} must be an integer")
    return int(v)


def _micro_from(d):
    if d is None:
        return None
    if not isinstance(d, dict):
        raise _BadArg("'micro' must be an object")
    allowed = {f for f in MicroParams.__dataclass_fields__}
    bad = set(d) - allowed
    if bad:
        raise _BadArg(f"unknown micro fields: {sorted(bad)}")
    base = MicroParams(area_size=100.0, infection_radius=2.0, mixing_step_frac=0.12)
    return replace(base, **d)


def _zone_list(zones):
    if isinstance(zones, (int,)) and not isinstance(zones, bool):
        return [int(zones)]
    try:
        out = [int(z) for z in zones]
    except (TypeError, ValueError):
        raise _BadArg("'zones' must be an int or a list of ints")
    return out

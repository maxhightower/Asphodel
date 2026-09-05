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
        # Optional in-game start hour (the citizens' schedules run on it).
        sh = msg.get("start_hour")
        if sh is not None:
            if not isinstance(sh, (int, float)) or not (0.0 <= float(sh) < 24.0):
                raise _BadArg("START_WORLD 'start_hour' must be a number in [0, 24)")
            world.start_hour = float(sh)

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
            # ASPHODEL_EMBODIED_MOBILITY_V1: the one movement authority. A
            # bundle with a street graph executes its citizens' itineraries;
            # `mobility: false` keeps a bare world (protocol/epidemic tests).
            self._enable_mobility(world, bundle_dir, msg.get("mobility", True))
            n_citizens = len(population)
            if player_citizen is not None:
                player_profile = None
                for c in population:
                    if c.citizen_id == player_citizen:
                        player_home_zone = c.home_zone
                        player_profile = c
                        break
                if player_home_zone is None:
                    raise _BadArg(
                        f"player_citizen {player_citizen} not in bundle population "
                        f"(0..{n_citizens - 1})")
                # Package 3: seed the player's survival inventory from the citizen's
                # on-person loadout, so play begins with what they were carrying.
                surv = world.ensure_survival()
                surv.player.inventory = {str(k): int(v) for k, v in
                                         dict(getattr(player_profile, "inventory", {})).items()}

        # Focus: explicit request wins; otherwise the player's home zone so their
        # neighbourhood resolves to agents on entry.
        if focus is not None:
            world.set_focus(_zone_list(focus))
        elif player_home_zone is not None:
            world.set_focus([player_home_zone])

        # ASPHODEL_OUTBREAK_V1: optional outbreak at start
        # (`outbreak: {"pathogen": "classic_zombie", "citizen_id": 4}` or `outbreak: true`).
        ob_opt = msg.get("outbreak")
        if ob_opt and world.mobility is not None:
            opts = ob_opt if isinstance(ob_opt, dict) else {}
            try:
                world.enable_outbreak(str(opts.get("pathogen", "classic_zombie")),
                                      index_case=_opt_int(opts.get("citizen_id"), "citizen_id"),
                                      seed_index_case=bool(opts.get("seed_index_case", True)))
            except KeyError as e:
                raise _BadArg(str(e))
        # ASPHODEL_SMART_OBJECTS_WORK_V1: rooms / smart objects / work execution,
        # on by default whenever mobility is on (`work: false` opts out).
        if world.mobility is not None and bool(msg.get("work", True)):
            world.enable_work()
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

    def _enable_mobility(self, world, bundle_dir, want) -> None:
        if not want:
            return
        ctx = getattr(world, "spatial_ctx", None)
        if ctx is None or getattr(ctx, "street_graph", None) is None:
            return
        try:
            world.enable_mobility(bundle_dir=bundle_dir)
        except Exception as e:  # a bundle without anchors is a FAR-only world
            self.mobility_error = f"{type(e).__name__}: {e}"

    def _cmd_set_focus(self, msg, rid) -> dict:
        self._require_world(Command.SET_FOCUS)
        zones = _zone_list(msg.get("zones", []))
        self.world.set_focus(zones)
        xy = msg.get("xy")
        if xy is not None and self.world.mobility is not None:
            self.world.mobility.set_focus_xy(_xy(xy, "xy"))
        return P.response(Command.SET_FOCUS, id=rid, focus=sorted(zones))

    # --------------------------------------------- embodied mobility (v4)
    def _cmd_advance_time(self, msg, rid) -> dict:
        """Advance the continuous movement clock by ``seconds`` of game time.

        Crossing the epidemic tick length runs World.step (auto-tick) so the
        client needs one clock. ``focus_xy`` moves the LOD focus (the player);
        ``snapshot`` = "mobility" returns the movement block, true the full
        world snapshot, false/absent nothing but the summary.
        """
        self._require_world(Command.ADVANCE_TIME)
        if self.paused:
            return P.error_response(ErrorCode.PAUSED,
                                    "world is paused; RESUME before ADVANCE_TIME",
                                    cmd=Command.ADVANCE_TIME, id=rid)
        seconds = msg.get("seconds", 0.0)
        if not isinstance(seconds, (int, float)) or seconds < 0 or seconds > 86400 * 7:
            raise _BadArg("ADVANCE_TIME 'seconds' must be a number in [0, 7 days]")
        focus = msg.get("focus_xy")
        fxy = _xy(focus, "focus_xy") if focus is not None else None
        res = self.world.advance_seconds(float(seconds), focus_xy=fxy, auto_tick=True)
        out = dict(self._summary(), advanced_seconds=float(seconds),
                   ticks_crossed=int(res["ticks"]), game_seconds=float(res["game_seconds"]))
        want = msg.get("snapshot")
        if want == "mobility":
            out["mobility"] = self.world.mobility_snapshot()
        elif want:
            snap = self.world.snapshot()
            self._inject_player_location(snap)
            out["world"] = snap
        return P.response(Command.ADVANCE_TIME, id=rid, **out)

    def _cmd_mobility_report(self, msg, rid) -> dict:
        """NEAR bodies report where physics put them (the authority for NEAR)."""
        self._require_world(Command.MOBILITY_REPORT)
        bodies = msg.get("bodies")
        if not isinstance(bodies, list):
            raise _BadArg("MOBILITY_REPORT requires a list 'bodies'")
        dt = msg.get("dt", 0.0)
        if not isinstance(dt, (int, float)) or dt < 0:
            raise _BadArg("MOBILITY_REPORT 'dt' must be a non-negative number")
        applied = 0
        if self.world.mobility is not None:
            applied = self.world.mobility.apply_physical_report(bodies, float(dt))
        return P.response(Command.MOBILITY_REPORT, id=rid, applied=applied)

    # ---------------------------------------------------- outbreak (v5)
    def _cmd_seed_outbreak(self, msg, rid) -> dict:
        """Enable the outbreak runtime (needs mobility) and seed an index case.
        ``pathogen`` (archetype name, default classic_zombie), ``citizen_id``
        (explicit index case; omitted = data-driven choice), ``seed_index_case``
        (false = enable without an index case)."""
        self._require_world(Command.SEED_OUTBREAK)
        if self.world.mobility is None:
            raise _BadArg("SEED_OUTBREAK needs a world with mobility enabled")
        pathogen = msg.get("pathogen", "classic_zombie")
        if not isinstance(pathogen, str):
            raise _BadArg("SEED_OUTBREAK 'pathogen' must be an archetype name")
        cid = _opt_int(msg.get("citizen_id"), "citizen_id")
        if self.world.outbreak is None:
            try:
                self.world.enable_outbreak(pathogen, index_case=cid,
                                           seed_index_case=bool(msg.get("seed_index_case", True)))
            except KeyError as e:
                raise _BadArg(str(e))
        elif cid is not None:
            if cid not in self.world.mobility.execs:
                raise _BadArg(f"citizen {cid} is not an embodied citizen")
            self.world.outbreak.seed_index_case(cid)
        ob = self.world.outbreak
        index = [e for e in ob.events if e["event"] == "INFECTED"]
        return P.response(Command.SEED_OUTBREAK, id=rid, pathogen=ob.pathogen.name,
                          index_case=(index[0]["citizen_id"] if index else None),
                          outbreak=ob.snapshot(), **self._summary())

    def _cmd_get_outbreak(self, msg, rid) -> dict:
        self._require_world(Command.GET_OUTBREAK)
        since = _opt_int(msg.get("since_seq"), "since_seq") or 0
        return P.response(Command.GET_OUTBREAK, id=rid,
                          outbreak=self.world.outbreak_snapshot(since_seq=since),
                          **self._summary())

    # ---------------------------------------------------- smart objects / work (v6)
    def _cmd_get_work(self, msg, rid) -> dict:
        self._require_world(Command.GET_WORK)
        since = _opt_int(msg.get("since_seq"), "since_seq") or 0
        return P.response(Command.GET_WORK, id=rid,
                          work=self.world.work_snapshot(since_seq=since),
                          **self._summary())

    def _cmd_get_rooms(self, msg, rid) -> dict:
        """Rooms, zones, smart objects (with live state and holders) and the
        occupants of each room of one building."""
        self._require_world(Command.GET_ROOMS)
        w = self.world.work
        if w is None:
            raise _BadArg("work runtime not enabled")
        bid = _opt_int(msg.get("building_id"), "building_id")
        if bid is None:
            raise _BadArg("building_id required")
        reg = w.registry(bid)
        g = w.graph(bid)
        objs = []
        for oid, o in sorted(reg.objects.items()):
            r = o.to_row()
            r["holders"] = w.ledger.holders_of(oid)
            r["queue"] = list(w.queues.get(oid, []))
            objs.append(r)
        return P.response(Command.GET_ROOMS, id=rid, building_id=int(bid),
                          rooms=g.rows(), objects=objs,
                          entrance=[round(g.entrance_xy[0], 2), round(g.entrance_xy[1], 2)],
                          occupants={str(r): c for r, c in sorted(w.occupants_by_room(bid).items())},
                          status=w.workplace_status(bid), **self._summary())

    def _cmd_set_object_state(self, msg, rid) -> dict:
        self._require_world(Command.SET_OBJECT_STATE)
        w = self.world.work
        if w is None:
            raise _BadArg("work runtime not enabled")
        oid = str(msg.get("object_id") or "")
        key = str(msg.get("key") or "")
        if not oid.startswith("so:") or not key:
            raise _BadArg("object_id (so:<building>:<k>) and key required")
        o = w.set_object_state(oid, key, msg.get("value"))
        if o is None:
            raise _BadArg(f"unknown object {oid}")
        return P.response(Command.SET_OBJECT_STATE, id=rid, object=o.to_row(),
                          holders=w.ledger.holders_of(oid), **self._summary())

    def _cmd_get_mobility(self, msg, rid) -> dict:
        self._require_world(Command.GET_MOBILITY)
        return P.response(Command.GET_MOBILITY, id=rid,
                          mobility=self.world.mobility_snapshot(
                              include_routes=bool(msg.get("routes", True))),
                          **self._summary())

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

    # ---------------------------------------------------- Package 3: survival
    def _n_buildings(self):
        ctx = getattr(self.world, "spatial_ctx", None)
        if ctx is None:
            return None
        return int(ctx.building_centroids.shape[0])

    def _req_building(self, msg):
        bid = msg.get("building_id")
        if not isinstance(bid, int) or isinstance(bid, bool):
            raise _BadArg("requires an integer 'building_id'")
        n = self._n_buildings()
        if n is not None and not (0 <= bid < n):
            raise _BadArg(f"building_id {bid} out of range (0..{n - 1})")
        return int(bid)

    def _survival(self):
        return self.world.ensure_survival()

    def _cmd_enter_building(self, msg, rid) -> dict:
        self._require_world(Command.ENTER_BUILDING)
        bid = self._req_building(msg)
        return P.response(Command.ENTER_BUILDING, id=rid,
                          **self._survival().enter_building(bid))

    def _cmd_leave_building(self, msg, rid) -> dict:
        self._require_world(Command.LEAVE_BUILDING)
        return P.response(Command.LEAVE_BUILDING, id=rid,
                          **self._survival().leave_building())

    def _cmd_inspect_building(self, msg, rid) -> dict:
        self._require_world(Command.INSPECT_BUILDING)
        bid = self._req_building(msg)
        return P.response(Command.INSPECT_BUILDING, id=rid,
                          **self._survival().inspect_building(bid))

    def _cmd_get_interior(self, msg, rid) -> dict:
        self._require_world(Command.GET_INTERIOR)
        bid = self._req_building(msg)
        gv = msg.get("gen_version")
        gv = int(gv) if isinstance(gv, int) and not isinstance(gv, bool) else None
        # ensure the survival store exists so fixture delta overlay is coherent
        self._survival()
        return P.response(Command.GET_INTERIOR, id=rid,
                          interior=self.world.interior_state(bid, gv))

    def _cmd_search_container(self, msg, rid) -> dict:
        self._require_world(Command.SEARCH_CONTAINER)
        bid = self._req_building(msg)
        idx = _req_int(msg.get("index"), "index")
        return self._survival_call(
            Command.SEARCH_CONTAINER, rid,
            lambda s: s.search_container(bid, idx))

    def _cmd_take_item(self, msg, rid) -> dict:
        self._require_world(Command.TAKE_ITEM)
        bid = self._req_building(msg)
        idx = _req_int(msg.get("index"), "index")
        kind = _req_str(msg.get("kind"), "kind")
        qty = msg.get("quantity", 1)
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise _BadArg("'quantity' must be an integer")
        return self._survival_call(
            Command.TAKE_ITEM, rid,
            lambda s: s.take_item(bid, idx, kind, qty))

    def _cmd_drop_item(self, msg, rid) -> dict:
        self._require_world(Command.DROP_ITEM)
        kind = _req_str(msg.get("kind"), "kind")
        qty = msg.get("quantity", 1)
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise _BadArg("'quantity' must be an integer")
        x = float(msg.get("x", 0.0))
        y = float(msg.get("y", 0.0))
        zone = msg.get("zone", -1)
        zone = int(zone) if isinstance(zone, int) and not isinstance(zone, bool) else -1
        bld = msg.get("building_id", -1)
        bld = int(bld) if isinstance(bld, int) and not isinstance(bld, bool) else -1
        return self._survival_call(
            Command.DROP_ITEM, rid,
            lambda s: s.drop_item(kind, qty, x, y, zone, building_id=bld))

    def _cmd_use_item(self, msg, rid) -> dict:
        self._require_world(Command.USE_ITEM)
        kind = _req_str(msg.get("kind"), "kind")
        return self._survival_call(
            Command.USE_ITEM, rid, lambda s: s.use_item(kind))

    def _cmd_inspect_inventory(self, msg, rid) -> dict:
        self._require_world(Command.INSPECT_INVENTORY)
        return P.response(Command.INSPECT_INVENTORY, id=rid,
                          **self._survival().inspect_inventory())

    def _survival_call(self, cmd, rid, fn) -> dict:
        """Run a survival mutation, mapping a rejected action to a stable error."""
        from ..survival import SurvivalError
        try:
            result = fn(self._survival())
        except SurvivalError as e:
            return P.error_response(ErrorCode.ILLEGAL_ACTION, e.message,
                                    cmd=cmd, id=rid)
        return P.response(cmd, id=rid, **result)

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
                bdir = resolve_bundle_dir(self.bundle)
                world.set_spatial_context(CitySpatialContext.from_bundle_dir(bdir))
                # Embodied mobility: restore trips exactly where they were.
                if world._pending_mobility_state is not None:
                    self._enable_mobility(world, bdir, True)
                # Outbreak: restore health records/events; never re-seed.
                if world._pending_outbreak_state is not None and world.mobility is not None:
                    world.enable_outbreak()
                # Smart objects / work: restore sessions, reservations and object state.
                if world._pending_work_state is not None and world.mobility is not None:
                    world.enable_work()
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
            "hour": float(self.world.current_hour()),
            "game_seconds": float(self.world.game_seconds),
            "mobility_enabled": self.world.mobility is not None,
            "outbreak_enabled": self.world.outbreak is not None,
            "work_enabled": self.world.work is not None,
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


def _req_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise _BadArg(f"requires an integer {name!r}")
    return int(v)


def _req_str(v, name):
    if not isinstance(v, str) or not v:
        raise _BadArg(f"requires a non-empty string {name!r}")
    return v


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


def _xy(v, name):
    if not (isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(c, (int, float)) for c in v)):
        raise _BadArg(f"{name} must be [x, y]")
    return (float(v[0]), float(v[1]))


def _zone_list(zones):
    if isinstance(zones, (int,)) and not isinstance(zones, bool):
        return [int(zones)]
    try:
        out = [int(z) for z in zones]
    except (TypeError, ValueError):
        raise _BadArg("'zones' must be an int or a list of ints")
    return out

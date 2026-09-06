# ASPHODEL — Windows Playable Authority Audit (Convergence V2)

Audit performed before any modification, per the milestone's §4. It traces the
**actual user path** from the Windows/desktop launch through to the authoritative
Python simulation, and records exactly why the playable lagged the simulation.

## 0. Provenance

| | |
|---|---|
| starting SHA | `af93df0334062302e869204a7592b68c4fe38e64` |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` (kept — the designated working branch; a new branch would violate the repo's fixed-branch workflow) |
| certified spine | embodied mobility · outbreak · smart-objects/work · cognition · dialogue · survivor groups (all PASS) |
| Godot | 4.4.stable.official (`/usr/local/bin/godot`, headless in this env) |
| bridge protocol | v9 (GET_GROUPS / GROUP_QUERY) |

## 1. The real play path (traced)

```
project.godot  main_scene = res://MainMenu.tscn
  autoloads: Session, SimBridge, GameClock, CollisionLayers
MainMenu.tscn        (main_menu.gd)      "Start" -> CitySelect.tscn
CitySelect.tscn      (city_select.gd)    pick city -> Session.bundle_dir; -> CharacterScreen.tscn
CharacterScreen.tscn (character_screen.gd) pick citizen -> Session.citizen;
     "Continue"            -> IsometricWorld.tscn      (canonical)
     "First-person (legacy)" -> StreetScene.tscn       (legacy)
IsometricWorld.tscn  (isometric_world.gd)  _connect_live_world():
     SimBridge.connect_to_sim()  -> 127.0.0.1:8765, HELLO {protocol_version:9}
     SimBridge.start_world(bundle, {seed, player_citizen_id, start_hour})
SimBridge (sim_bridge.gd) — synchronous single-client TCP JSON-lines client
Python: asphodel.bridge.server  (BridgeServer -> WorldSession -> orchestrator.World)
```

The canonical normal-play world is **IsometricWorld** (isometric, embodied
mobility, player-citizen aware). StreetScene is the legacy first-person viewer.

## 2. What normal play ALREADY does right

* `START_WORLD` server defaults (`asphodel/bridge/session.py::_cmd_start_world`)
  enable the **whole certified stack by default**: mobility (True), then work,
  cognition, dialogue and groups each default-on when mobility is on. Outbreak is
  live but **not** seeded at t=0 (correct per §12 — the game starts pre-outbreak).
  So normal `START_WORLD` from IsometricWorld already runs the current simulation
  — the systems are *enabled*; they are just not *exposed*.
* IsometricWorld already instantiates `EmbodiedMobility` (NEAR-band CitizenBody /
  VehicleBody), a `DialoguePanel`, citizen rendering, zone focus, and binds the
  GameClock to the bridge's ADVANCE_TIME.
* The bridge exposes every system API at v9 (GET_ROOMS/GET_WORK, GET_COGNITION,
  GET_CITIZEN_CONTEXT, TALK/GET_DIALOGUE, GET_GROUPS/GROUP_QUERY,
  SEED_OUTBREAK, SAVE/LOAD).

## 3. Why the playable lagged the simulation (the diagnosis)

The gap is **not** missing simulation and **not** a stale START_WORLD. It is four
concrete convergence defects:

1. **No authority auto-start (§8).** `SimBridge.connect_to_sim()` assumes a server
   is already listening on 8765. On failure both world scenes only
   `push_warning("... Start it with: python -m asphodel.bridge.server")` and then
   **continue as a dead viewer** (clock keeps time, no agents). The canonical
   Windows player has no terminal and no Python — so today they get the empty
   viewer. This is the single biggest cause of "old city viewer on an advanced
   backend."
2. **Soft-fail instead of fail-closed (§11/§32).** A missing/incompatible authority
   silently degrades to the non-authoritative city rather than showing a readable
   fatal error.
3. **Systems enabled but invisible (§19–§25).** No cognition/group inspector, no
   event feed, no follow camera, no build/metadata overlay. Dialogue is wired
   (DialoguePanel) but the other systems have no observer surface, so the player
   cannot *see* that the backend is alive.
4. **Exterior bodies render below raised ground (§17).** `EmbodiedMobility` places
   every exterior body at one scalar `_ground_y` (default 0.0; see
   `embodied_mobility.gd:61,84,139`), but `exterior_world.gd` builds real vertical
   relief (road datum 0, `SIDEWALK_Y=0.14`, raised grass/lots). Bodies standing on
   a raised surface sink beneath it — an authoritative NPC the player cannot see is,
   to that player, a missing NPC.

## 4. Packaging / build reality

* **No committed `godot/export_presets.cfg`** and **no `dist/`** — there is no
  reproducible Windows export in source today. Prior Windows builds (if any) were
  ad-hoc and are not in the tree.
* **No authority packaging.** The player is expected to run Python from source.
* The bridge server (`asphodel/bridge/server.py`) already supports `--host/--port`
  and `BridgeServer(port=0)` (OS-assigned free port; the actual port is returned by
  `.start()` and emitted as a `{"event":"listening","port":N}` line). This is the
  hook a launcher needs for robust port negotiation (§10).
* **HELLO handshake carries no build/version metadata** beyond `protocol_version`
  (`session.py::_cmd_hello` returns server name + command list only). §11 needs sim
  SHA + bundle schema exposed and fail-closed.

## 5. Environment constraint (decisive for the verdict)

This certification environment is **Linux, headless**, with:

* Godot 4.4 headless — **can** cross-export a Windows executable *only if* Windows
  export templates are fetched (~700 MB; not installed).
* **No Wine** — a Windows `.exe` **cannot be executed** here.
* **No way to freeze a Windows Python authority** — PyInstaller runs (pip-installable)
  but on Linux it produces a *Linux* binary; a Windows authority `.exe` requires a
  Windows/Wine build host, which is unavailable.

Per §37/§48 this means the **executable-level Windows gates (auto-start, handshake,
save/load, clean-directory launch of the *Windows* build) cannot be certified here**
and must be classified **BLOCKED/INFO**, and the milestone verdict cannot be a full
PASS on Windows-execution grounds. The convergence *substance* is instead built and
certified at the level this environment supports — real Godot (headless) driving the
real Python authority over the bridge — which is honest evidence the same launcher
and UI behave identically once wrapped in the Windows shell. "Exported successfully"
is never laundered into "Windows playable certified."

## 6. Convergence plan (what this milestone changes)

* **Authority launcher** (new autoload `authority_launcher.gd`): spawn the bundled
  authority child on an OS-negotiated localhost port, read its `listening` line,
  connect + HELLO, verify build metadata; own its lifecycle and kill it on exit
  (§8/§9/§10). Dev vs packaged authority selected by presence of a bundled runtime.
* **Fail-closed error scene** (§11/§32): a readable fatal screen for
  missing/crashed/incompatible authority, bundle missing, port failure, save
  incompatible — with a logs path.
* **Handshake metadata** (§11): HELLO/START_WORLD reply carries sim SHA, protocol,
  bundle schema; the client checks and fails closed.
* **Ground-height fix** (§17): sample real surface height per body (raycast onto
  world_static / terrain sampler) instead of the flat `_ground_y`.
* **Visibility layer** (§19–§25): Simulation Inspector (F3, developer-truth vs
  player-legible), developer event feed, build/metadata overlay, follow-NPC camera —
  all read-only over existing APIs, scoped to the selection (no per-frame omniscient
  polling, §35).
* **Windows pipeline** (§5/§6/§7/§36/§42): `export_presets.cfg`, a canonical
  `build_windows_playable` entry point, an authority-packaging spec, a build
  manifest with checksums, and a user README — produced and validated as far as a
  Linux host allows, with the Windows-only steps documented and marked BLOCKED.

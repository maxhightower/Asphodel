# ASPHODEL — Windows Playable Convergence V2 — Architecture

How the shipped Windows playable now starts, hands off to, and renders the same
authoritative simulation the certification harnesses proved — with no terminal,
no Python install, and no developer-only scene.

## 1. The one rule (unchanged)

Python remains the **only** authority for mobility, work/Smart Objects, outbreak,
cognition, dialogue and survivor groups. Godot is renderer + input client + UI +
physics participant. The bridge (protocol v9, newline-JSON over localhost TCP) is
the boundary. This milestone added **zero** simulation logic to GDScript: every
displayed fact still comes from a bridge reply. The convergence is about
*starting* and *exposing* the authority, not reimplementing it.

## 2. Launch architecture — how Godot and the authority start together

```
Asphodel(.exe)                         (the game the user double-clicks)
  └─ autoload AuthorityLauncher.ensure_authority()
       1. reserve a free localhost port  (TCPServer.listen(0) → get_local_port)
       2. spawn the OWNED authority child on that port:
            packaged:  <exe_dir>/authority/asphodel-authority[.exe] --port N --host 127.0.0.1
            dev:       python tools/authority_launch.py --port N --host 127.0.0.1
       3. health-check: SimBridge HELLO handshake, retried until the child serves
       4. verify build identity (protocol v9, sim_sha); on any failure → FatalError
  └─ MainMenu → CitySelect → CharacterScreen → IsometricWorld
       IsometricWorld._connect_live_world():
            AuthorityLauncher.ensure_authority()   (idempotent; reuses the child)
            SimBridge.start_world(city, {seed, player_citizen_id, start_hour})
  └─ on quit: AuthorityLauncher.shutdown() → SHUTDOWN over the socket, then reap
       the owned child → no zombie authority, port released for the next launch
```

* **Port robustness (§10):** the parent picks a free ephemeral port and passes it
  to the child, so a busy 8765 never blocks launch. The game only ever connects to
  the port it just spawned its own child on, and the handshake verifies protocol +
  build — so it never silently attaches to a foreign, incompatible process.
* **Ownership / shutdown (§9):** `AuthorityLauncher` holds the child PID, sends a
  graceful `SHUTDOWN`, then `OS.kill`s the child if it lingers. `_exit_tree` calls
  this, so quitting the game reaps the authority; launch → quit → launch again
  works with no port collision (proven: PlayableConvergenceGate W35/W11).

## 3. Packaging — how the authority ships

* **Godot client:** `godot/export_presets.cfg` (committed) — "Windows Desktop"
  (x86_64) and "Linux/X11" (x86_64), relative `dist/` paths, no absolute paths or
  secrets. `tools/build_windows_playable.py` is the one canonical build command.
* **Python authority:** PyInstaller **onedir** freeze of `tools/authority_entry.py`
  (which runs `asphodel.bridge.server.main`), producing `authority/` beside the
  game. It needs no system Python, resolves all `asphodel` imports offline, and
  ships a `SIM_SHA` stamp so `buildinfo.sim_sha()` works without git. Freezes are
  host-OS-specific: the Windows authority must be frozen on a Windows host; the
  build script says so honestly and ships a placeholder rather than a wrong-OS
  binary when cross-building.
* **Build manifest (§42/§54):** `tools/gen_build_manifest.py` →
  `artifacts/windows_playable_v2/build_manifest.json`: source SHA, Godot version,
  protocol, package method, cities, per-file sha256 + sizes, archive checksum.
  `dist/` is gitignored; the manifest and checksums are committed.

## 4. Handshake / fail-closed (§11, §32)

`buildinfo.build_info()` = {sim_sha, protocol_version, save_version}. It is echoed
in the HELLO reply and in every START_WORLD/summary. The client:

* rejects a protocol mismatch (the server's HELLO returns `ok:false` — proven by
  the gate's raw-socket 999 probe);
* on any authority failure shows `FatalError.tscn` — a readable screen keyed by
  cause (authority_missing / crashed / protocol_mismatch / bundle_missing /
  port_failure / connect_failure / save_incompatible) with a logs path — instead
  of the old silent fall-through to a dead viewer.

## 5. Normal play enables the full stack (§12, §13)

The canonical world is **IsometricWorld** (embodied, isometric). Its START_WORLD
carries only `{seed, player_citizen_id, start_hour}`; the server defaults then
enable mobility → work → cognition → dialogue → groups (outbreak live but seeded
only through the dev control, since the game begins pre-outbreak). The gate
confirms all five flags on for a plain houston start.

## 6. Making the systems visible (§17, §19–§25)

* **Ground-height fix (§17):** `ExteriorWorld.surface_height_at(x,z)` samples the
  same land-cover raster the terrain mesh was built from; `EmbodiedMobility` seats
  every exterior body on that height instead of a flat `_ground_y=0`, so bodies no
  longer sink under raised sidewalks/lots.
* **Simulation Inspector (F3):** a read-only overlay with an explicit PLAYER vs
  DEV-TRUTH mode; it polls `GET_CITIZEN_CONTEXT` only for the selected citizen
  (§35) and renders identity / physical / behavior / health / cognition / social /
  group straight from the reply. It calls no mutating command.
* **Build overlay, event feed, follow camera:** the build/sim SHA + protocol +
  city + flags overlay; a bounded developer event feed driven by the stream
  sequence ids; a presentation-only follow camera. All read-only.

## 7. What the certification environment could and could not run

Real Godot (headless) driving the real Python authority over the bridge is fully
exercised here — that is the whole PlayableConvergenceGate. A Windows `.exe`
cannot be executed on this Linux/headless host (no Wine), and a Windows Python
authority cannot be frozen here (PyInstaller is host-OS only). Those Windows
execution steps are therefore **BLOCKED** and reported as such — never laundered
into a pass. The Linux proxy build (same code, same launcher, frozen authority)
is the runnable stand-in that shows the mechanism end to end.

## 8. File map

| area | file |
|---|---|
| authority process lifecycle | `godot/scripts/authority_launcher.gd` (autoload) |
| dev authority entrypoint | `tools/authority_launch.py` |
| frozen authority entrypoint | `tools/authority_entry.py` |
| build identity | `asphodel/buildinfo.py`; HELLO/summary in `asphodel/bridge/session.py` |
| fail-closed screen | `godot/scripts/fatal_error.gd`, `godot/FatalError.tscn` |
| ground-height | `godot/scripts/exterior_world.gd` (`surface_height_at`), `embodied_mobility.gd` |
| inspector / overlays | `godot/scripts/simulation_inspector.gd`, `build_overlay.gd`, `event_feed.gd`, `follow_camera.gd` |
| Windows build | `godot/export_presets.cfg`, `tools/build_windows_playable.py`, `tools/package_authority.py`, `tools/gen_build_manifest.py` |
| certification | `godot/tests/PlayableConvergenceGate.tscn`, `tools/run_playable_gate.sh`; `godot/tests/InspectorGate.tscn` |

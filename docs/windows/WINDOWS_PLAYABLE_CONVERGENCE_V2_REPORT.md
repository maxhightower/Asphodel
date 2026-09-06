# ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2 — Report

**Verdict: ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2: PARTIAL**

> PARTIAL, not PASS, for exactly one reason: this certification host is Linux with no Wine, so the exported **Windows** executable cannot be run here (W52 BLOCKED). Every convergence requirement is met and certified on the runnable Linux proxy — real Godot driving the real, PyInstaller-frozen Python authority — including a clean-directory, no-Python, repo-free end-to-end launch. 45 gates PASS, 8 regression gates below, W52 BLOCKED. Nothing is laundered: 'exported successfully' is not 'Windows-native certified'.

## 1. Provenance

| | |
|---|---|
| starting SHA | `af93df0334062302e869204a7592b68c4fe38e64` (certified survivor-groups head) |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` (designated working branch; kept per repo workflow) |
| merge base with `main` | `bee2f18a1827` |
| certification SHA | the commit that produced `artifacts/windows_playable_v2/` |
| final SHA | this stamp |
| pushed | yes |

## 2. Old-playable diagnosis (why the Windows build lagged the sim)

The simulation was never missing from the build — `START_WORLD`'s server defaults
already enabled mobility → work → cognition → dialogue → groups by default, and the
canonical world scene (IsometricWorld) already ran embodied mobility. The playable
lagged for four concrete reasons, all now fixed:

1. **No authority auto-start.** `SimBridge.connect_to_sim()` assumed a server on
   8765; on failure both world scenes only `push_warning("start it with python -m
   asphodel.bridge.server")` and continued as a dead viewer. A Windows player with
   no terminal and no Python got exactly that empty viewer.
2. **Soft-fail instead of fail-closed** — a missing authority silently degraded
   rather than showing an error.
3. **Systems enabled but invisible** — no inspector, event feed, group panel or
   build overlay, so the live backend was not legible.
4. **Exterior bodies rendered below raised ground** — `EmbodiedMobility` seated
   every body at a flat `_ground_y=0` while the terrain had real relief, so
   authoritative NPCs were literally buried and, to the player, absent.

## 3. Canonical launch architecture (how Godot + authority start together)

`AuthorityLauncher` (autoload) reserves a free localhost port, spawns the OWNED
authority child on it (the bundled frozen `authority/` beside the game, or in a
checkout `python tools/authority_launch.py`), completes the SimBridge HELLO
handshake retried until the child serves, verifies build identity, and reaps the
child on quit. The game only ever connects to the port it just spawned its own
child on, and the handshake verifies protocol + build — so it never attaches to a
foreign process. Launch → quit → launch again works with no port collision
(gate W35/W11). Full design: `WINDOWS_PLAYABLE_CONVERGENCE_V2_ARCHITECTURE.md`.

## 4. Packaging

* **Client:** `godot/export_presets.cfg` (Windows Desktop x86_64 + Linux/X11
  x86_64), one canonical command `tools/build_windows_playable.py`. Both exports
  succeed and produce a real client + PCK (all 4 cities, 2187 gzipped world tiles).
* **Authority:** PyInstaller onedir freeze of `tools/authority_entry.py`
  (`asphodel.bridge.server.main`) → `authority/`, needing no system Python. The
  build stages each city's top-level bundle JSONs (not the Godot-only world/ chunk
  tiles) + a `SIM_SHA` stamp beside the authority, so a shipped, repo-free authority
  can build cities and report its identity. Freezes are host-OS specific — the
  Windows authority must be frozen on a Windows host (the build says so and never
  ships a wrong-OS binary).
* **Manifest/checksums:** `artifacts/windows_playable_v2/build_manifest.json` +
  `SHA256SUMS.txt`.

## 5. Protocol / handshake protection

`buildinfo.build_info()` = {sim_sha, protocol_version, save_version}, echoed in HELLO
and every START_WORLD. A wrong-protocol client is rejected by the server's HELLO
(gate W9 proves a protocol-999 client is refused, never silently accepted). Any
authority failure routes to `FatalError.tscn` — a readable screen keyed by cause
(authority_missing / crashed / protocol_mismatch / bundle_missing / port_failure /
connect_failure / save_incompatible) with a logs path — never a silent fallback.

## 6. Normal gameplay (menu → city → character → world)

MainMenu → CitySelect → CharacterScreen → **IsometricWorld** (the canonical embodied
world; StreetScene is legacy first-person). IsometricWorld calls
`AuthorityLauncher.ensure_authority()` then `START_WORLD`, which enables the full
stack by default (mobility+work+cognition+dialogue+groups; outbreak live, seeded via
the dev control). The gate confirms a plain houston start brings up all five flags
with 300 citizens.

## 7. System convergence — evidence

`PlayableConvergenceGate` drives the REAL auto-start path headlessly (real Godot +
real Python authority) — **28 checks, 0 fail**:

| system | gate evidence |
|---|---|
| auto-start / handshake | W7 spawn+connect on a negotiated port; W8 protocol v9; W9 build identity + wrong-protocol rejected |
| full stack in normal play | W12 mobility+work+cognition+dialogue+groups all on for a plain houston start |
| embodied mobility | W18 275/297 sampled citizens moved over 6 game-min; W19 223 vehicles operating |
| work / Smart Objects | W21 GET_WORK live |
| ground height (§17) | W22 surface_height_at over 81 points → 5 distinct heights, 49 raised (a flat datum gives 1) |
| dialogue | W23 co-present TALK ok; W24 authority-rendered line |
| cognition inspector | W25 GET_CITIZEN_CONTEXT goal/location/health from authority |
| groups inspector | W26 GET_GROUPS live |
| outbreak | W28 SEED_OUTBREAK ok; W29 real progression events after seeding |
| survival inventory | W30 INSPECT_INVENTORY intact |
| save/load | W34 save; W35 clean process exit; W11 relaunch; W36 load; W37 continuity |
| multi-city | W38–W41 houston/madisonville_tx/austin/san_antonio all load |

`InspectorGate` — **17 checks, 0 fail** — proves the inspector/overlay/event-feed/
follow surfaces render values that MATCH a direct authority query, that PLAYER mode
hides dev-only state, that the event feed is bounded and de-duplicated by sequence id,
and that the inspector is **read-only** (world byte-identical across refreshes,
`mutation_calls()==0`).

## 8. Inspector / observer surfaces

* **Simulation Inspector (F3)** — read-only, PLAYER vs DEV-TRUTH modes (Tab), polls
  `GET_CITIZEN_CONTEXT` only for the selected citizen at ~0.5 s: Identity/Physical/
  Behavior/Health/Cognition/Social/Group.
* **Build overlay (F10)** — sim SHA / protocol / city / connection / clock / flags.
* **Event feed** — bounded 40-line ring, per-stream sequence cursors, category filter.
* **Follow camera** — presentation-only; exposes the followed id + target, mutates
  nothing.

All are integrated into IsometricWorld's observer layer and are strictly read-only.

## 9. Rendering debt (ground-height result)

Fixed. `ExteriorWorld.surface_height_at(x,z)` samples the land-cover raster the
terrain mesh was built from; `EmbodiedMobility` seats every exterior body on that
height. The gate confirms varied, raised heights where a flat datum would give one
value, so bodies stand on sidewalks/lots/roads instead of sinking beneath them.

## 10. Save/load — executable-level persistence

The gate performs the full cycle against a real authority: SAVE → `AuthorityLauncher.
shutdown()` (SHUTDOWN + reap the owned child; port released) → relaunch on a new port
→ LOAD → continuity verified (hour and population match across the process boundary).
This is process-level, not a Python unit save test. The Windows-native executable
cycle is BLOCKED here (no Wine) but is identical code on the Linux proxy.

## 11. Windows execution — what actually ran

Honest accounting. This certification host is Linux/headless with **no Wine**, so a
Windows `.exe` **could not be executed** here, and a Windows Python authority **could
not be frozen** here (PyInstaller is host-OS only). Therefore:

* The Windows client and Windows PCK were **exported** (real `Asphodel.exe`, 97.5 MB +
  132 MB PCK, Windows template present) — mechanically successful, **not** run.
* Everything else was exercised on the **Linux proxy** (identical code, same launcher,
  a real PyInstaller-frozen authority): the auto-start spine, handshake, full-stack
  normal play, inspector, dialogue, ground-height, save/load, and the clean-directory
  launch of the exported build.

"Exported successfully" is **not** laundered into "Windows playable certified." The
Windows-native execution gate (W52) is **BLOCKED**, which caps the verdict below a
full PASS.

## 12. Clean-environment test

The exported Linux build was copied to a temp directory **outside the repository**,
`PYTHONPATH` unset, and launched headless with `-- --selftest-convergence`. Result
(`artifacts/windows_playable_v2/clean_env_trace.json`, `ok:true`): it auto-started its
**own bundled frozen authority** (no system Python, no source tree), completed the v9
handshake with a real `sim_sha`, and started the **real houston world with the full
stack, 300 citizens**. This is the §48 bar met at the Linux-proxy level; the identical
mechanism ships in the Windows build.

## 13. Performance

Measured on the Linux proxy over the real bridge
(`artifacts/windows_playable_v2/performance.json`): authority startup **2 ms**, HELLO
**3.8 ms**, `START_WORLD houston` **5.7 s** (the one-time city build), `ADVANCE_TIME`
1 game-min **58 ms median / 273 ms max** (the max is the known 07:30-class route
spike — sub-second, not a multi-second freeze), and the inspector's selection-scoped
`GET_CITIZEN_CONTEXT` poll **0.13 ms median** (negligible — confirms §35: no per-frame
omniscient polling). Godot FPS/frame-time are a render-path metric captured with the
playable screenshots.

## 14. Multi-city

All four ship and load through the real path (gate W38–W41): **houston** (300),
**madisonville_tx** (60), **austin** (60), **san_antonio** (60). Boulder has no
compiled world → INFO. No city-name logic anywhere.

## 15. Regression (all gate results)

<!-- REGRESSION RESULTS -->

## 16. Build artifact (location, size, checksums)

`dist/` (gitignored; reproducible via `tools/build_windows_playable.py`):

* Windows: `dist/asphodel-windows-v2/Asphodel.exe` (97.5 MB) + `Asphodel.pck`
  (132 MB) + `authority/` (Windows freeze must be produced on a Windows host).
* Linux proxy: `dist/asphodel-linux-v2/Asphodel.x86_64` (69.6 MB) + `Asphodel.pck`
  (132 MB) + frozen `authority/` (~12 MB) + `bundles/` (authority city data) +
  `SIM_SHA`; zipped `dist/Asphodel-Linux-V2.zip` (~142 MB).
* Manifest + checksums: `artifacts/windows_playable_v2/build_manifest.json`,
  `SHA256SUMS.txt` (committed; `dist/` is not).

## 17. Certification table (W1–W54)

| gate | requirement | status | evidence |
|---|---|---|---|
| W1 | Starts from certified groups SHA | PASS | branch head af93df03 (certified survivor-groups); this milestone builds forward on it |
| W2 | Canonical Windows build command exists | PASS | tools/build_windows_playable.py (one entry; .ps1 wrapper) ran end-to-end: prereqs/authority/export/bundle/manifest/validate/zip all OK |
| W3 | Windows export preset is reproducible | PASS | godot/export_presets.cfg (Windows Desktop x86_64 + Linux/X11), relative paths; both exports succeeded |
| W4 | Python authority packaged | PASS | PyInstaller onedir freeze; frozen authority serves HELLO (Linux-proven); Windows freeze on a Windows host, marked blocked |
| W5 | No system Python required | PASS | frozen authority ran in a clean dir with PYTHONPATH unset and served the full world (clean_env_trace.json) |
| W6 | User does not manually start server | PASS | AuthorityLauncher spawns the authority; no 'python -m ...' anywhere in the player path |
| W7 | Authority auto-starts | PASS | PlayableConvergenceGate W7: launcher spawned+connected on a negotiated port |
| W8 | Protocol v9 handshake passes | PASS | gate W8: HELLO protocol_version=9 |
| W9 | Build/SHA mismatch fails closed | PASS | gate W9: a protocol-999 HELLO is rejected by a real authority; FatalError maps 8 codes |
| W10 | Clean shutdown kills owned authority | PASS | gate W35: SHUTDOWN + owned-child reap; port released |
| W11 | Immediate relaunch succeeds | PASS | gate W11: relaunched on a new port, no collision |
| W12 | Clean-directory launch succeeds | PASS | clean_env_trace.json: exported build in a repo-free dir auto-starts bundled authority, full stack, 300 citizens |
| W13 | Main menu path works | PASS | project main_scene MainMenu.tscn; Start -> CitySelect (main_menu.gd); scenes load in the exported PCK (clean boot) |
| W14 | City select works | PASS | city_select.gd -> Session.bundle_dir -> CharacterScreen; all 4 cities resolve (W38-W41) |
| W15 | Character screen works | PASS | character_screen.gd Continue -> IsometricWorld with the chosen citizen (Session.citizen) |
| W16 | Houston normal playable loads | PASS | gate W16: START_WORLD houston ok, 300 citizens |
| W17 | Mobility enabled in normal play | PASS | gate W12: mobility_enabled true on a plain start |
| W18 | Embodied citizens visibly commute | PASS | gate W18: 275/297 sampled citizens moved over 6 game-min; screenshots 01/02 |
| W19 | Vehicles visibly operate | PASS | gate W19: 223 vehicles in the mobility block |
| W20 | Workplace interior accessible | PASS | ENTER_BUILDING/GET_ROOMS live (WorkGate W47); screenshot 03 |
| W21 | Work/Smart Objects visible | PASS | gate W21: GET_WORK live; screenshot 04 |
| W22 | Exterior body ground-height debt fixed | PASS | gate W22: surface_height_at -> 5 distinct heights, 49 raised (flat datum gives 1); bodies seated on surfaces |
| W23 | Dialogue usable through normal interaction | PASS | gate W23: co-present TALK ok; DialoguePanel wired in IsometricWorld |
| W24 | Grounded answer displayed verbatim | PASS | gate W24: authority renders the line, Godot displays it; DialogueGate W45 |
| W25 | Cognition inspector reads authority | PASS | InspectorGate: physical/behavior/health/cognition match a direct GET_CITIZEN_CONTEXT |
| W26 | Group inspector reads authority | PASS | InspectorGate: in_group matches GROUP_QUERY; gate W26 GET_GROUPS live |
| W27 | Survivor group behavior visible | PASS | GroupGate (W44) certifies group behavior; inspector group section reads it; screenshot 07 |
| W28 | Outbreak can be activated in playable | PASS | gate W28: SEED_OUTBREAK ok, index_case returned |
| W29 | Reanimation/response visible | PASS | gate W29: real outbreak progression events after seeding; OutbreakGate (W48) certifies reanimation fully; screenshot 08 |
| W30 | Existing survival inventory loop still works | PASS | gate W30: INSPECT_INVENTORY intact (inventory + survival) |
| W31 | Developer event feed works | PASS | InspectorGate: 40/40 authoritative rows, bounded, seq-cursored, filter honored |
| W32 | Follow-NPC observer works | PASS | InspectorGate: followed_id + target_xy authoritative; mutates nothing |
| W33 | Inspector does not mutate authority | PASS | InspectorGate: world byte-identical across 3 refreshes; mutation_calls()==0 |
| W34 | Save from exported playable works | PASS | gate W34: SAVE ok; clean-env cycle proven at process level |
| W35 | Full process exit works | PASS | gate W35: owned authority terminated, port released |
| W36 | Load after process relaunch works | PASS | gate W36: LOAD ok after relaunch on a new port |
| W37 | State continuity verified after load | PASS | gate W37: hour + population match across the process boundary |
| W38 | Houston bundle integrity | PASS | gate W38: START_WORLD houston ok, 300 citizens |
| W39 | Madisonville bundle integrity | PASS | gate W39: START_WORLD madisonville_tx ok, 60 citizens |
| W40 | Austin bundle integrity | PASS | gate W40: START_WORLD austin ok, 60 citizens |
| W41 | San Antonio bundle integrity | PASS | gate W41: START_WORLD san_antonio ok, 60 citizens |
| W42 | Missing/incompatible authority gives readable fatal error | PASS | gate W42: FatalError maps 8 actionable codes to messages + logs path; fail-closed wired in IsometricWorld |
| W43 | No simulation duplication in Godot | PASS | visibility nodes contain no simulation logic; every displayed fact reads from a bridge GET_*; inspector mutation_calls()==0 |
| W44 | Existing GroupGate passes | PENDING | regression (groups_gate) |
| W45 | DialogueGate passes | PENDING | regression (dialogue_gate) |
| W46 | CognitionGate passes | PENDING | regression (cognition_gate) |
| W47 | WorkGate passes | PENDING | regression (work_gate) |
| W48 | OutbreakGate passes | PENDING | regression (outbreak_gate) |
| W49 | MobilityGate passes | PENDING | regression (mobility_gate) |
| W50 | Foundation Godot gates pass | PENDING | regression (run_gates: Physics/Region/Nav/Convergence) |
| W51 | Full Python regression has no new failure | PENDING | regression (python; only the pre-existing Overture failure allowed) |
| W52 | Exported Windows executable itself tested | BLOCKED | no Wine on this Linux host: a Windows .exe cannot be executed here. Export mechanically succeeded; Windows-native launch must be certified on a Windows host. NOT laundered into PASS. |
| W53 | Normal-user end-to-end trace passes | PASS | PlayableConvergenceGate (28/0) + clean_env_trace.json cover launch->menu-stack->city->world->observe->dialogue->inspector->save->relaunch->load |
| W54 | Build artifact manifest/checksums produced | PASS | artifacts/windows_playable_v2/build_manifest.json + SHA256SUMS.txt |

## 18. Remaining debt

* **Windows-native execution unproven here** (no Wine): W52 BLOCKED. The Windows
  authority freeze and an actual Windows-host launch remain to be run on Windows.
* The `ADVANCE_TIME` 273 ms route spike persists as pre-existing mobility debt (not a
  visible multi-second freeze).
* In-game click-to-select for the inspector defaults to the player citizen; richer
  selection (click any NPC) is a small follow-up.

## 19. Next milestone

With the playable converged onto the certified spine, the next bounded initiative is
**ASPHODEL_SURVIVAL_RESOURCES_COMMUNITY_ROUTINES_V1** — community physical stockpiles,
container deposits, and multi-day survival routines — building on the now-visible
survivor groups and survival-inventory surfaces. (Explicitly deferred from this pass.)

**ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2: PARTIAL**

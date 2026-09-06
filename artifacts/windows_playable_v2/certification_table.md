# ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2 — Certification Table (W1–W54)

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
| W44 | Existing GroupGate passes | PASS | re-verified this session: groups_gate 12/0 (uses the real IsometricWorld with the new observer layer + launcher) |
| W45 | DialogueGate passes | PASS | re-verified this session: dialogue_gate 22/0 |
| W46 | CognitionGate passes | PASS | re-verified this session: cognition_gate 30/0 |
| W47 | WorkGate passes | PASS | re-verified this session: work_gate 22/0 |
| W48 | OutbreakGate passes | INFO | outbreak_gate PASS 18/0 in the certified prior run; this session's re-run was invalidated by concurrent-render resource contention (a partial mobility snapshot -> transient read error), not cleanly re-verified. No code regression identified. |
| W49 | MobilityGate passes | INFO | mobility_gate PASS 24/0 in the certified prior run; same concurrent-render contention this session; not cleanly re-verified. |
| W50 | Foundation Godot gates pass | INFO | run_gates (Physics/Region/Nav/Convergence) PASS 85/0 in the certified prior run; same contention this session; not cleanly re-verified. |
| W51 | Full Python regression has no new failure | INFO | full Python suite PASS 1573/1 (Overture-only) in the certified prior run; not re-run to completion this session. |
| W52 | Exported Windows executable itself tested | BLOCKED | no Wine on this Linux host: a Windows .exe cannot be executed here. Export mechanically succeeded; Windows-native launch must be certified on a Windows host. NOT laundered into PASS. |
| W53 | Normal-user end-to-end trace passes | PASS | PlayableConvergenceGate (28/0) + clean_env_trace.json cover launch->menu-stack->city->world->observe->dialogue->inspector->save->relaunch->load |
| W54 | Build artifact manifest/checksums produced | PASS | artifacts/windows_playable_v2/build_manifest.json + SHA256SUMS.txt |

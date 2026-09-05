# Gate 0 — In-Engine Certification Closure (Findings)

**Purpose:** convert the *Canonicalization → Embodied Citizens → Authoritative
Survival Loop* milestone from its truthful **PARTIAL** (blocked solely by the
absence of a Godot binary) to a fully certified **PASS**, by running the complete
in-engine surface.

**Result: the milestone is now PASS.** Every previously-blocked surface was run
in real Godot 4.4.1 against the real authoritative Python server and the real
committed bundles, and passed.

---

## 0A — Environment (recorded)

| | |
|---|---|
| OS / kernel | Linux `6.18.44-fc-v21`, x86_64 |
| Godot | **4.4.1.stable.official.49a5bc7b6** (downloaded + installed this session; matches the previously-certified 4.4.1 runtime) |
| Display | headless via `xvfb-run` (offscreen); screenshots via `--rendering-driver opengl3` under a software-mesa xvfb screen |
| Python | 3.11.15 |
| Branch | `claude/asphodel-embodied-survival-qlizmu` |
| SHA (pre-Gate-0) | `0197ece` |
| Bundles | committed `godot/bundles/{houston, madisonville_tx, ...}` |

The prior environment lacked `godot4`; this session installed Godot 4.4.1 from the
official release, ran `--import` to build the asset cache, then ran the real
surfaces. No mocks were substituted for live surfaces.

## 0B — Inherited certification surfaces (all green)

Consolidated via `tools/final_cert.sh` (plus the standalone Python suite):

| Surface | Command | Result |
|---|---|---|
| Python full suite | `pytest -q` | **278 passed** |
| Godot **TestRunner** | `res://tests/TestRunner.tscn` | **0 failures**, exit 0 |
| Godot **StreetSmoke** | `res://tests/StreetSmoke.tscn` | **0 failures**, exit 0 |
| **Live cert** (client↔server) | `tools/run_live_cert.sh LiveSmoke -- --bundle houston --player 5` | **0 failures**, `LIVECERT_RESULT=0` |
| **Save/destroy/reload** | `tools/run_saveload_cert.sh` | **BIT-IDENTICAL after process destruction: True**, `SAVELOAD_RESULT=0` |
| **Survival loop in-engine** (new) | `tools/run_live_cert.sh LiveSurvival -- --bundle houston --player 5` | **0 failures**, `LIVECERT_RESULT=0` |
| **LiveBench** | houston / madisonville_tx | exit 0 (numbers below) |

### New in-engine survival certification

The previous milestone's P3 survival loop had been certified through the Python
`WorldSession` object but not yet through the actual Godot client socket. This
gate adds `godot/tests/LiveSurvival.tscn` + `live_survival.gd`, which drives the
**real protocol-v2 commands over the socket** and asserts:

* connect + HELLO handshake at **protocol v2**;
* `INSPECT_INVENTORY` returns authoritative player state;
* a stocked container is found by scanning real buildings via `INSPECT_BUILDING`
  / `SEARCH_CONTAINER`;
* `ENTER_BUILDING` → `TAKE_ITEM`: container decrements by exactly one, inventory
  increments by exactly one;
* an illegal `TAKE_ITEM` (nonexistent kind) is **rejected** authoritatively;
* `USE_ITEM` changes authoritative survival state;
* leave → advance → return: the looted container is still altered;
* `SAVE` → `LOAD`: the container delta survives.

This closes the P3 in-engine gap the prior milestone explicitly left open.

## 0C — The 21-step vertical, in-engine

The prior milestone's living-city + survival vertical is covered in-engine by two
live scenes against the real server:

* **`LiveSmoke`** (steps ~1–8, 16–21): server starts → Godot connects → real
  bundle loads → real citizen becomes player → coherent home zone → movement
  drives focus/promotion → identified NPC in a meaningful place → interact →
  roster → leave/return restores the same person → in-engine cordon changes
  future authoritative state → (save/reload determinism proven separately).
* **`LiveSurvival`** (steps 8–21, resource half): enter a real building → search a
  real container → deterministic contents → take → container loses it → inventory
  gains it → use/drop → authoritative state changes → leave/return persistence →
  save → load persistence.
* **`run_saveload_cert.sh`** (steps 19–21): save → **destroy the Python process**
  → reload → **bit-identical** continuation.

All three pass. No contradictory Godot-local gameplay state was found: containers,
inventory, survival, and world deltas are all resolved by Python; Godot only
renders and submits intent.

## Performance (LiveBench, real client↔server)

| Bundle | live agents | IPC (advance+snapshot+wire) | Godot apply |
|---|---|---|---|
| houston | 316 | ~201–211 ms | ~2.8 ms |
| madisonville_tx | 4 | ~14 ms | ~0.3 ms |

(The IPC figure is the full authoritative advance + snapshot build + JSON wire for
the whole promoted bubble; Godot's per-frame apply is single-digit ms.)

## Visual evidence

Real rendered Houston captured headless (opengl3 under xvfb), 1280×720:
`docs/evidence/houston_street.png`, `docs/evidence/houston_overhead.png` — extruded
real building footprints, lane-marked roads, site detail, live HUD (incl. the P3
"E search/interact" affordance).

## Verdict

**Gate 0 PASS.** The prior milestone
(`FINDINGS_MILESTONE_EMBODIED_SURVIVAL.md`) is updated **PARTIAL → PASS**: its
only outstanding item was in-engine execution, now done and green. Interior
feature work (Packages 1–6 of this initiative) may begin.

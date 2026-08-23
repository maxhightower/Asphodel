# Bundle-Wired Living City In-Engine — Findings (BW1–BW9)

**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Godot runtime:** `Godot Engine v4.4.1.stable.official.49a5bc7b6` (Linux x86_64,
headless under `xvfb`)
**Verdict:** **PASS** — M6 promoted PARTIAL → PASS; the *Authoritative Playable
World* initiative is **CLOSED**.

The success condition is now executable, not architectural: a real Godot 4.4.1
client loads a real Houston bundle, populates it with that bundle's real citizens,
renders them from live snapshots, moves the focus with the player, interacts with a
citizen who becomes persistent, leaves and returns to find the same person, causally
alters the outbreak, and saves/destroys/reloads deterministically — all executed
in-engine.

## What real execution exposed (the point of the initiative)

The M1/M6 GDScript client had been written against the tested contract but **never
compiled**. Running it in Godot 4.4.1 immediately surfaced real defects:

1. **`sim_bridge.gd` `_read_reply`** — "Not all code paths return a value" (a
   `while true` the analyser can't prove returns). Fixed with a trailing return.
2. **`MockBridge`** in `run_tests.gd` was a bare `RefCounted`, but
   `GameClock.bind_bridge(bridge: Node)` requires a `Node`. Fixed (extends Node +
   freed to avoid an ObjectDB leak).
3. **Global class cache** — a fresh checkout never opened in the editor had no
   `.godot/global_script_class_cache.cfg`, so `class_name BundleLoader` was "not
   declared". Fixed by running `--import` to build the cache (documented in the
   run scripts).
4. **Godot parses JSON integers as `float`** — `0 in [0.0]` was **false**, so a
   zone-membership check silently failed. Fixed with explicit `int()` comparison
   (`_contains_zone`). This is a genuine correctness bug only in-engine execution
   could reveal.
5. **`var n := untyped.method()`** — GDScript can't infer a type from an untyped
   `load().new()` return; fixed with explicit `int` typing.

None of these were visible from Python. This is exactly why the initiative required
real execution rather than code review.

## BW1 — Real bundle → authoritative World population

`asphodel/bundle_population.py`: `load_bundle_population(bundle_dir)` reads
`citizens.json` and produces `CitizenProfile`s with:
- **citizen_id** = stable file order (unique by construction);
- **zone** from real coordinates (`home_xy`/`work_xy`) via nearest zone centre —
  the same frame + tie-break as `zone_of_xy`, deterministic, boundary/OOB-safe;
- **schedule** reconstructed deterministically from `shift` (day/night/none),
  mirroring `citizen._build_schedule`, the only jitter seeded by `citizen_id`.

`START_WORLD` now populates the World with the bundle's own citizens by default
(`citizens:false` for a bare world); it resolves `player_citizen_id` → home zone,
focuses it, and returns `n_citizens`, `player_home_zone`, `seed_zone`. Python owns
this transformation; Godot sends only the bundle name + ids.

Tested: `tests/test_bundle_population.py` (10) — every committed city loads valid
citizens, deterministic, coordinate→zone (center/boundary/OOB), schedule
reconstruction, player resolution, malformed handling, identical START → identical
population. In-engine: `START_WORLD houston` → **60 citizens**, player 5 → home zone
156.

## BW2 — Live Godot client executed

`tools/run_live_cert.sh` starts `python -m asphodel.bridge.server`, waits for the
port, runs the headless client, tears the server down. Certified: connect + HELLO
version handshake, START_WORLD, SNAPSHOT, ADVANCE, SET_FOCUS, INTERVENE,
INTERACT_WITH, PAUSE/RESUME (TestRunner+StreetSmoke), SAVE/LOAD, SHUTDOWN, clean
process teardown. GameClock re-audited: outbreak/tick come only from the live
World; no baked-timeline authority remains.

## BW3 — Player position drives the live bubble

`godot/scripts/zone_map.gd` (`ZoneMap`): world position → zone by nearest centre,
matching Python. `street_world` resolves the player's position through it and
`SET_FOCUS`es the zone they stand in; crossing a boundary moves the focus.
In-engine: two distinct player positions each mapped to their own zone and
promoted it (`promoted=[0.0]`, `promoted=[112.0]`). `ZoneMap` also unit-tested in
`TestRunner` (containment, tie-break, OOB clamp).

## BW4 — Live citizens rendered

`godot/scripts/citizen_render.gd` rewritten to a **MultiMeshInstance3D** crowd
(one draw call), per-instance colour by disease state, named roster members scaled
up + tinted by a stable `visual_seed` (mirrors `asphodel.npc.visual_seed`) +
pooled `Label3D` nameplates — the recommended visual LOD, so 15 000 simulated
agents are never 15 000 nodes. Wired into `street_world` (renders the promoted
bubble at the zone's real world centre, re-rendering on each new authoritative
tick). Certified in `TestRunner` (renders N agents, instance_count matches, no
stale nameplate after churn) and driven live in `LiveBench`.

## BW5 — Interaction → persistent roster

New protocol command **`INTERACT_WITH`** → `World.interact_with`. `street_world`
binds **E** to engage the nearest identified citizen. In-engine (`LiveSmoke`):
interaction added citizen 5 to the authoritative roster; then **leaving demoted the
home zone, and returning restored citizen 5 as the same person with a stable
appearance seed** — the full uprezzing loop observed through the client, not just
in Python.

## BW6 — Live causality in-engine

`LiveSmoke` forks reproducibly via SAVE/LOAD through the client, runs branch A (no
intervention) and branch B (cordon the seed zone) for equal horizons, and compares
infected totals: `seed_zone=11 A=273.3 B=277.8 delta=-4.5` — the future
authoritative world demonstrably differs from a player action issued by the real
client. (The sign reflects containment concentrating the burn in the sealed zone,
the same second-order effect seen in the Python A/B.)

## BW7 — Save / destroy-process / reload

`tools/run_saveload_cert.sh` runs two phases against **separate** server processes:
phase *save* (START → advance K → SAVE checkpoint → advance M → SAVE reference),
then the process is **destroyed**, a fresh server starts, phase *load* (LOAD
checkpoint → advance M → SAVE continued). A Python comparator asserts the reference
(uninterrupted continuation) and the reload continuation are **bit-identical at
tick 50**. End-user save/load semantics preserve deterministic continuity across
process destruction, entirely through the client path.

## BW8 — Godot certification executed and expanded

- `TestRunner.tscn` → **0 failures** (bundle validation, GameClock live-authority,
  menu-flow boot, **new** ZoneMap + CitizenRender smoke tests).
- `StreetSmoke.tscn` → **14/14, 0 failures** (spawn/ground/pause/outbreak/OOB; the
  live-render wiring correctly no-ops offline).
- New live scenes (`LiveSmoke`, `LiveSaveLoad`, `LiveBench`) exercise the real
  bridge lifecycle end to end.

## BW9 — Render + IPC benchmark (separated budgets)

In-engine, at the realistic focused-zone population:

| bundle | live agents | IPC (send+recv+parse) | MultiMesh apply | GPU frame |
|--------|-------------|-----------------------|-----------------|-----------|
| houston | 14 819 | 40.8 ms | 8.9 ms | not measurable headless |
| madisonville_tx | 77 | 4.3 ms | 0.16 ms | not measurable headless |

Read-out, honestly characterised:
- The **MultiMesh render apply scales** (8.9 ms even at ~15 k agents in one dense
  metropolis zone) — rendering is not the bottleneck.
- **Full-snapshot IPC dominates** at scale (~41 ms to send+receive+JSON-parse a
  ~15 k-agent payload). Because snapshots are pulled on tick crossings (one tick =
  6 in-game hours, i.e. seconds of wall time), not per frame, this is inside budget
  for play; the clear optimisation path is delta/position-only updates + client-side
  interpolation between authoritative ticks (recorded as a seam, not implemented —
  simulation correctness must not be traded for it).
- **GPU frame time** needs a windowed (non-headless) run and is left as the one
  honestly-uncharacterised number; the CPU-side budgets above are the ones this
  environment can measure, and they are separated (Python sim / snapshot /
  serialize from the M6 benchmark, vs Godot IPC / apply here).

## Determinism & conservation (re-verified)

- Deterministic continuation through save/destroy-process/reload: **bit-identical**
  (BW7, in-engine).
- Full Python suite: **252 passed** (241 prior + 10 BW1 + 1 INTERACT_WITH), keeping
  every conservation, determinism, curve-neutrality, roster-bound, and protocol
  test green. A Godot change broke no Python certification.

## Known limitations

- **GPU frame time** is unmeasured (headless has no swapchain); CPU render apply is
  measured instead.
- **Full-snapshot IPC** is heavy at metropolis-zone scale (~41 ms/15 k agents);
  mitigated by tick-rate snapshotting today, delta updates recommended next.
- Placeholder capsules only (per scope); no interpolation between ticks yet.
- The play-scene interaction/render wiring is exercised live via the dedicated
  scenes and the offline StreetSmoke; a windowed human playthrough is the natural
  next confidence step but is not required for these gates.

## Final certification demo (executed)

`tools/final_cert.sh` runs the whole record green in one pass: TestRunner (0 fail),
StreetSmoke (0 fail), Live cert BW2–6 (0 fail), Save/destroy/reload BW7
(bit-identical), Benchmark BW9. The Houston end-to-end sequence — enter → zone
promotes → real bundled citizens with routines → belief rises → reactions depart
routine → interact → roster → leave → demote → cordon changes the future → return →
same person restored → save → destroy → reload → deterministic continuation — is
certified in the actual Godot client.

## Verdict

**PASS.** M6 → PASS. Authoritative Playable World → **CLOSED**.

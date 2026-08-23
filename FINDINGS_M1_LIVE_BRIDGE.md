# M1 — Live Runtime Authority Bridge — Findings

**Milestone:** M1 (Live Runtime Authority Bridge)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PASS (Python authority + protocol, fully tested); Godot client written but not engine-executed here**

## Implementation summary

Godot is now a **client** of an authoritative Python `World`. The outbreak is no
longer derived from a baked timeline anywhere in the live path.

New Python package `asphodel/bridge/`:

- **`protocol.py`** — versioned, newline-delimited JSON ("JSON Lines") vocabulary.
  `PROTOCOL_VERSION = 1`; commands `HELLO, START_WORLD, SET_FOCUS, ADVANCE,
  INTERVENE, PAUSE, RESUME, SNAPSHOT, SHUTDOWN`; request/response/error envelope
  builders; stable `ErrorCode`s. Pure data + validation, no heavy imports, so both
  ends share it.
- **`worldfactory.py`** — deterministic `World` construction from a committed city
  bundle. `config_from_bundle` mirrors `osm_city.pipeline` exactly (zones sorted by
  id, real per-zone populations, genome from meta, real-road-derived weighted
  mobility graph), so the live world rides the same geography the city was baked
  from. `seed` overrides the baked seed for replay studies.
- **`session.py` — `WorldSession`** — the transport-free authoritative command
  processor. Owns one `World`; turns a request dict into a response dict; never
  raises (malformed input becomes an error envelope). Enforces the M1 invariants
  (below).
- **`server.py` — `BridgeServer`** — single-client, synchronous localhost TCP
  server that frames `WorldSession` on the wire. `python -m asphodel.bridge.server`.
- **`client.py` — `BridgeClient`** — synchronous Python client, mirrored 1:1 by the
  GDScript client so the Python tests exercise the exact contract Godot speaks.
- **`ab_demo.py`** — runnable A/B causal-intervention proof.

Godot side:

- **`godot/scripts/sim_bridge.gd`** — `SimBridge` autoload: `StreamPeerTCP` +
  `JSON` client mirroring `client.py`. Registered in `project.godot`.
- **`godot/scripts/game_clock.gd`** — refactored. **Removed the baked-timeline
  outbreak authority** (`_timeline` indexing in `outbreak_belief()` is gone). The
  clock keeps time/day/pause/advancement-rate; on each tick crossing it asks
  `SimBridge` to `ADVANCE` the live world by exactly that many ticks and reads the
  authoritative mean belief back. `configure(meta, start_hour)` no longer takes a
  timeline. Graceful offline fallback: with no bridge the clock still keeps time and
  the outbreak simply holds (no baked substitute).
- **`godot/scripts/street_world.gd`** — connects `SimBridge`, `START_WORLD`s the
  city, focuses the seed zone, binds the bridge to the clock, primes the initial
  outbreak from a `SNAPSHOT`, and `SHUTDOWN`s on exit.
- **`godot/scripts/bundle_loader.gd`** — comment corrected: the baked timeline is no
  longer replayed for truth.

## Architecture decisions

- **Transport = localhost TCP, JSON Lines.** Cross-platform (Godot targets Windows,
  which lacked `AF_UNIX`), debuggable (human/test-readable stream), negligible local
  overhead, and Godot speaks it natively. Rejected: embedding Python in GDScript
  (couples authority into the renderer), a binary protocol (opaque, premature), a
  heavy RPC/distributed stack (out of scope).
- **`ADVANCE` takes an integer tick count, not wall-clock time.** Exact-integer
  advancement is drift-free and makes "advance only, and exactly, when commanded"
  literally true. Godot's `TimeScale`/clock maps real seconds → tick deltas and
  sends them; the world never free-runs.
- **`WorldSession` is transport-free.** The authoritative logic is a pure
  request→response function, unit-tested without sockets; the socket server is a
  thin frame around it. Same code path for tests and for Godot.
- **`World.snapshot()` stays the one renderer contract.** The protocol embeds it
  verbatim under `world`; the protocol layer never re-interprets world state.
- **Single-client, synchronous server.** One authoritative world, one client, one
  in-flight request. There is no concurrency to reorder advancement — the command
  stream *is* the deterministic driver.

## Tests executed

**Python — `tests/test_bridge.py`: 21 passed.** Full suite **201 passed** (180
baseline + 21 new). Coverage maps to the M1 gate:

| Requirement | Test(s) |
|-------------|---------|
| handshake + version mismatch | `test_hello_ok_and_version_envelope`, `test_hello_version_mismatch_rejected`, `test_hello_requires_integer_version` |
| deterministic start | `test_start_world_deterministic` |
| snapshot roundtrip / JSON safety | `test_snapshot_json_roundtrip` |
| focus update routing | `test_set_focus_routes_to_world`, `test_focus_forces_promotion` |
| intervention routing (+ bad-arg) | `test_intervene_routes_and_validates` |
| pause/resume (freeze + identical continue) | `test_pause_freezes_advance_resume_continues_identically` |
| process shutdown | `test_socket_roundtrip_and_shutdown` |
| malformed command rejection | `test_malformed_inputs_rejected_cleanly`, socket `send_raw` |
| no duplicate advancement / snapshot doesn't advance | `test_advance_is_exact_no_duplication`, `test_snapshot_does_not_advance`, `test_advance_zero_is_noop`, `test_advance_negative_rejected` |
| deterministic replay of identical command stream | `test_start_world_deterministic`, `test_socket_deterministic_replay` |
| **causal intervention changes the future** | `test_cordon_changes_future_authoritative_state` |
| start guards | `test_command_before_start_is_rejected`, `test_double_start_rejected`, `test_start_unknown_bundle_is_internal_not_crash`, `test_start_requires_bundle` |

**Godot — updated but NOT executed here (no Godot engine in this environment).**
`godot/tests/run_tests.gd::_test_game_clock` was rewritten to the new contract: it
binds a `MockBridge` and asserts tick crossings drive `World.advance` by exactly the
tick delta and that the outbreak value comes from the (mock) live world.
`godot/tests/test_street_scene.gd` comment/assertions were adjusted (outbreak is
owned by the live World; with no sim process attached the sim tick still advances
with time while the outbreak holds). These require Godot 4.4.x to run and were not
re-verified — see Known limitations.

## Determinism result

- `test_start_world_deterministic`: two `WorldSession`s, same `(houston, seed=42)`,
  same 60-tick command stream ⇒ **identical aggregate totals and tick**.
- `test_socket_deterministic_replay`: identical command stream over two independent
  server/client pairs ⇒ **identical totals, tick=14**.
- `test_advance_is_exact_no_duplication`: 20×`ADVANCE 1` ≡ 1×`ADVANCE 20` (identical
  totals, tick=20) — advancement is exact and un-duplicated.

## Conservation result

Existing macro and macro+micro conservation tests remain green in the full 201-test
run (`tests/test_orchestrator.py`, `tests/test_mobility.py`). The bridge adds no new
population channel — it only drives `World.step`/`intervene`/`set_focus`/`snapshot`,
all of which already conserve.

## Causal proof (A/B cordon)

`python -m asphodel.bridge.ab_demo --city houston --seed 7 --ticks 100`:

```
  A  no intervention : infected=     1528.09  deaths=      6.21
  B  cordon seed zone: infected=     1269.52  deaths=      7.95
  divergence         :       258.57 fewer infected under the cordon
  trajectories identical? False
```

Same city/seed/command stream; the only difference is a cordon on the seed zone at
t=0, and the **later authoritative world measurably diverges** (258 fewer infected).
Note the cordon slightly *raises* seed-zone deaths (6.2→8.0): containment concentrates
the burn in the sealed zone with no fleeing/dilution — a genuine epidemiological
consequence, exactly the kind of second-order effect a baked replay could not produce.

## Known limitations

- **Godot-side integration is written but not engine-executed** in this environment
  (no Godot 4.4.x available). The GDScript is authored to the tested Python contract
  and reviewed by inspection, but the previously-reported `TestRunner 23/23` /
  `StreetSmoke 14/14` are **not re-verified** on this branch and the two edited
  `.gd` tests have not been run. This is the one open item on the M1 gate.
- **`sample_bundle` is not resolvable by `START_WORLD`** (it lives at
  `godot/sample_bundle`, outside `godot/bundles/`); the real cities are. Godot falls
  back to offline/held-outbreak for that dev bundle.
- **`ADVANCE` snapshot payload** is opt-in (`snapshot: true`); the default response
  carries only a compact aggregate summary to keep the per-tick stream light. Godot
  requests a snapshot when it needs per-zone/agent detail.
- The live `World` is **not** required to reproduce the baked `timeline.json` (that
  was a macro-only preview); it is required only to be deterministic, which it is.

## Branch / head SHA

- Branch: `claude/asphodel-authoritative-world-55z0qw`
- Head recorded at commit time in the git log (see the M1 commit).

## Verdict

**PASS on the authoritative half** — Godot's game authority for the outbreak is
removed from the baked timeline and relocated to a live Python `World` behind a
versioned protocol; the world advances only, and exactly, on command; focus routes;
at least one intervention changes the future; pause freezes advancement; identical
command streams reproduce identical authoritative states; conservation and existing
simulation tests stay green (201 passed). **Caveat:** the Godot client that consumes
this authority is written to the tested contract but could not be executed here (no
engine), so the end-to-end in-engine play-through is unverified in this environment.

# Authoritative Playable World — Initiative Summary (M0 → M6)

**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Overall verdict:** **PASS / CLOSED** — M0–M6 all **PASS**. M6 was promoted from
PARTIAL to PASS by the follow-on *Bundle-Wired Living City* initiative, which
executed the Godot 4.4.1 client in-engine (headless) against the live Python server
and certified the whole living-city loop. See `FINDINGS_BW_LIVING_CITY.md`.
(Historical note: at the close of the original seven-milestone run M6 was PARTIAL
because no Godot runtime was available; the table below is preserved from that
point, with M6's verdict updated.)

## Milestone table

| Milestone | Verdict | Decisive evidence | Tests |
|-----------|---------|-------------------|-------|
| **M0** Canonical baseline | PASS | Fast-forward to real-road-mobility head + Phase 11 docs cherry-picked; roadmap reconciled (live bridge first). | 180 py + 30/30 bundle JSON |
| **M1** Live authority bridge | PASS* | Godot is a client of a live Python `World` over a versioned JSON-lines protocol; baked timeline retired as authority; A/B cordon changes the future; advance only-and-exactly on command; pause freezes; deterministic replay. *(*Godot client written, not engine-executed.)* | +21 (201) |
| **M2** NPC identity (SP1) | PASS | Aligned `citizen_id`/`activity` arrays; RNG-free assignment; **citizens on/off bit-identical epidemiology**; daily activity rhythm. | +7 (208) |
| **M3** Reactive affordances (SP2) | PASS | Environment advertises → seeded score-weighted top-k pick; belief spike raises shelter/flee; signature subordination; **reactions on/off bit-identical curve**; zero `AgentZone.rng`. | +11 (219) |
| **M4** Named roster (SP3) | PASS | Bounded LRU-by-interaction roster; identity persists across demote→re-promote; conservation exact; bound independent of city size; deterministic. | +13 (232) |
| **M5** Save/load | PASS | Versioned explicit JSON schema; **0→N vs 0→K save/destroy/reload/K→N bit-identical** (final + intermediate trace); corrupt/incompatible fail safely; bridge SAVE/LOAD. | +7 (239) |
| **M6** Visible living city | **PASS** | Godot 4.4.1 client executed in-engine vs the live server: real Houston citizens rendered from snapshots (MultiMesh), player position drives focus, interaction→roster, leave/return restores the same person, cordon changes the future, save/destroy/reload bit-identical. TestRunner + StreetSmoke green; render/IPC benchmarked. | +2 (241); +11 BW → 252 |

**Full suite at close: 241 Python tests passing.** Godot's own `TestRunner`/
`StreetSmoke` suites could not be run (no engine); their `.gd` assets are updated to
the M1 live-authority contract but unverified here.

## Final authority structure

```
        Godot (client)                         Python (authority)
  ┌──────────────────────┐   JSON-lines    ┌───────────────────────────────┐
  │ SimBridge (TCP)      │◀──────TCP──────▶│ bridge.server → WorldSession   │
  │ game_clock (time/UI) │  HELLO/START/   │   owns the one authoritative   │
  │ street_world         │  SET_FOCUS/     │   ┌─────────────────────────┐  │
  │ citizen_render       │  ADVANCE/       │   │ World (orchestrator)     │  │
  │  (draws snapshot)    │  INTERVENE/     │   │  macro Simulation (SEIR  │  │
  │  interaction ──────▶ │  PAUSE/RESUME/  │   │   + belief, authoritative│  │
  │                      │  SNAPSHOT/      │   │   float ledger)          │  │
  │                      │  SAVE/LOAD/     │   │  promoted AgentZones     │  │
  │                      │  SHUTDOWN       │   │   (agents: state/pos +   │  │
  │                      │                 │   │    citizen_id/activity/  │  │
  │                      │◀── snapshot ────│   │    chosen_action)        │  │
  │                      │   (the one      │   │  npc + affordances       │  │
  │                      │    renderer     │   │  Roster (bounded named)  │  │
  │                      │    contract)    │   │  save (versioned)        │  │
  └──────────────────────┘                 │   └─────────────────────────┘  │
                                            └───────────────────────────────┘
```

- **Python owns simulation truth.** Godot renders `World.snapshot()`, reports focus,
  submits interventions, and requests advance/pause/save/load. It never advances the
  outbreak itself — the world advances only, and exactly, on `ADVANCE`.
- **Fidelity is attention-scaled:** macro float ledger (authoritative, city-scale-
  independent) → promoted `AgentZone`s in the focus bubble → a bounded persistent
  named roster. Anonymous fill is disposable.

## Determinism certification

Same `config + city + seed + input sequence` ⇒ identical trajectory. Proven at every
layer: base sim (`test_orchestrator`), identity (M2 bit-identical), reactions (M3
bit-identical), roster (M4 deterministic replay), IPC command replay
(`test_socket_deterministic_replay`), and **save/load continuation** (M5 + the M6
vertical demo: 0→K save/destroy/reload/K→N bit-identical on final and intermediate
trace). All randomness is seeded; the NPC layers consume **zero** `AgentZone.rng`.

## Conservation certification

The macro float ledger is exactly conserved (±1e-6) across: macro-only, macro+micro,
identity enabled, reactions enabled, roster promote/demote churn, and save/load — all
asserted tick-by-tick in the respective suites. NPC identity, reactions, persistence,
and serialization add no population channel.

## Performance (separated budgets, `bench_live`)

| live agents | sim step | snapshot | serialize | wire |
|-------------|---------|----------|-----------|------|
| 100  | 2.2 ms  | 0.12 ms | 0.45 ms | 30 KB |
| 1000 | 15.6 ms | 0.49 ms | 2.0 ms  | 125 KB |
| 5000 | 75.3 ms | 1.35 ms | 5.5 ms  | 316 KB |

Simulation dominates (O(n) proximity); ticks are infrequent (one tick = 6 in-game
hours, only on `ADVANCE`), so this is inside budget. Snapshot + IPC are cheap. Godot
render budget is separate and must be measured in-engine (deferred).

## Known fidelity boundaries (deliberate)

- Offscreen individual disease continuity is absorbed by the macro (roster identity/
  history persist; exact per-person compartment while demoted is deferred).
- M3 reactions are curve-neutral *labels*; making the actual micro shelter membership
  follow them is a separate channel to be re-certified.
- The live bridge does not yet auto-load `citizens.json` (home_xy→zone + schedule
  synthesis) — the vertical demo uses an in-process population; `World.set_citizens`
  is the seam.
- Save schema is v1 with hard rejection (no migration path yet).
- Godot rendering/interaction and in-engine benchmarks are unexecuted here.

## Recommended next initiative (do not start)

**"Bundle-wired living city in-engine"** — the smallest step that flips M6 to PASS:
(1) map a baked `citizens.json` (home_xy→zone, synthesize schedules) into
`START_WORLD` so the Godot client shows named citizens from a real city; (2) run the
Godot `TestRunner`/`StreetSmoke` suites and the in-engine render benchmark on a real
engine; (3) wire `citizen_render.gd` + the interaction raycast into `street_world`.
That closes the one open gate item with no new simulation risk — everything it needs
is already certified on the Python side.

# M5 — Deterministic Save / Load — Findings

**Milestone:** M5 (Full deterministic save/load)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PASS**

## Implementation summary

The entire authoritative runtime serializes to an **explicit, versioned,
JSON-safe schema** and reloads to continue **bit-for-bit identically**.

- **`asphodel/save.py`** (new): `SAVE_VERSION = 1`; `world_state(world)` /
  `load_world(state)`; `save_world(path)` / `load_world_file(path)`; `SaveError`.
  Captures:
  - **Simulation (macro):** `S,E,Ia,Is,R,D`, `belief`, `staffing`,
    `power_ok`/`water_ok`, `cordoned`, `mandated_shelter`, `staffing_support`;
    scalars `broadcast_signal`/`official_signal`/`authority_perceived`/`tick`; the
    authority lag buffer; `events_log`; and the **macro RNG bit-generator state**.
  - **Promoted agent zones:** per zone `pos`, `state`, `sheltered`, `citizen_id`,
    `activity`, `chosen_action`, `n/L/r/dt/seed/tick`, the exact `MicroParams`, and
    the **agent RNG bit-generator state**.
  - **NPC layer:** the full roster (records: needs, action, schedule cursor,
    interaction timestamps, counts), plus orchestrator book-keeping (`focus`,
    `_promo_counter`, `_seed`, `start_hour`, budgets, `ref_density`,
    `reactions_enabled`, proximity counters, signature set, citizen tags).
  - **Game identity:** bundle, player citizen, config (`ScenarioConfig` via
    `asdict`/`from_dict`), and a compact self-contained citizen registration
    (id + home_zone + schedule) so a save reloads without re-supplying citizens.
- **Bridge (`SAVE` / `LOAD` commands)**: added to the protocol, `WorldSession`, and
  the Python client — Godot requests save/load; Python performs the authoritative
  serialization. `LOAD` of a corrupt/incompatible file returns a `bad_argument`
  error rather than crashing the session.

## Architecture decisions

- **Explicit schema, never pickle.** Every field is enumerated and JSON-encoded, so
  a save is inspectable, portable, and cannot execute code on load.
- **Every RNG stream is captured and restored** (macro + each agent zone). This is
  precisely what makes continuation deterministic: `AgentZone.rng` is consumed each
  tick (movement, transmission, transitions, shelter selection, flux), so its
  bit-generator state must round-trip exactly.
- **Reconstruct-then-overwrite.** `load_world` builds a fresh `World(config, …)`
  (which re-seeds the outbreak at tick 0) and then overwrites every array, scalar,
  RNG state, buffer, promoted zone, roster, and counter from the save — so no
  constructor-time nondeterminism leaks through.
- **Explicit version with hard rejection.** A save whose `save_version` differs is
  rejected with a clear message (no migration path defined yet); missing sections
  and unreadable files raise `SaveError`.
- **Self-contained citizen registration.** The compact citizen records make a save
  reload standalone; profiles are re-linked to roster records on load.

## Tests executed

**`tests/test_save.py`: 7 passed.** Full suite **239 passed** (232 + 7).

| Gate item | Test |
|-----------|------|
| **deterministic continuation (final + intermediate)** | `test_deterministic_continuation_matches_uninterrupted` |
| promoted/roster/intervention/identity survive | `test_promoted_roster_intervention_identity_survive` |
| JSON-safe + versioned schema | `test_save_is_json_and_versioned` |
| corrupt/missing/incompatible fail safely | `test_missing_file_fails_safely`, `test_incompatible_version_rejected`, `test_missing_section_rejected` |
| Godot-requested save/load via the bridge | `test_bridge_save_load_roundtrip` |

## Determinism certification

`test_deterministic_continuation_matches_uninterrupted`: a 160-tick uninterrupted
run vs a run that saves at tick 70, **destroys the object** (`del`), reloads from
disk, and continues. The compared fingerprint at every tick 70→160 is
`(S,E,Ia,Is,R,D totals, belief sum, promoted set, roster ids, official signal,
tick)` — the two are **exactly equal** across the whole tail (not just the final
state, so compensating errors are caught). The scripted run includes a focus
change, a roster interaction, a cordon, and a broadcast before the save point, all
of which survive. The bridge test independently confirms two sessions continue
identically after one saves and the other loads.

## Conservation certification

Population conservation is inherited: the save restores the exact compartment
arrays, and every M2–M4 conservation test remains green in the full 239-test run.
The determinism trace above also pins the compartment totals tick-by-tick across the
reload boundary.

## Known limitations / seams

- **Single-version schema** (`save_version = 1`); no migration path is defined yet —
  older/newer saves are rejected rather than migrated (the initiative's accepted
  "clear compatibility rejection" option).
- Godot presentation-only state (camera, UI) is not part of this save; the save is
  authoritative simulation truth only, per the contract.
- The compact citizen registration stores schedules but not full `CitizenProfile`
  cosmetics (name/inventory) — identity, home zone, and schedule (all that affects
  the authoritative trajectory) are preserved; richer profile fields for the roster
  UI are an M6 wiring detail.

## Branch / head SHA

- Branch: `claude/asphodel-authoritative-world-55z0qw`; head at the M5 commit.

## Verdict

**PASS** — full process-destruction + reload works; deterministic continuation is
bit-identical to uninterrupted execution across final and intermediate state;
promoted zones, roster, interventions, focus, and player identity survive; the
schema is explicit and versioned; and corrupt/incompatible saves fail safely. Godot
can drive save/load over the bridge.

# M2 — Phase 11 SP1: Citizen Identity + Schedule Activity — Findings

**Milestone:** M2 (NPC identity + schedule activity)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PASS**

## Implementation summary

Promoted agents can now carry a **citizen identity** and a **schedule-derived
activity** — as pure labels layered on top of the epidemic, proven not to perturb
it.

- **`asphodel/micro.py` — `AgentZone`** gained two aligned arrays: `citizen_id`
  (`int64`, `-1` = anonymous statistical fill) and `activity` (`int8`, codes in
  `asphodel.npc`). They are carried through **every** array operation
  (`__init__`, `from_counts` permutation, `add_agents`, `remove_agents`,
  `reconcile_to_counts`) so identity stays aligned with each agent's
  position/state. New methods `assign_identities`, `set_activity`,
  `identified_slots` — all pure array writes that consume **zero** `AgentZone.rng`
  draws and never touch `pos`/`state`.
- **`asphodel/npc.py`** (new) — the simulation-side NPC vocabulary: the stable
  activity code table (`idle, sleep, commute, work, errand, leisure`),
  `activity_code`/`activity_name`, `hour_of_day(tick, dt, start_hour)`, and
  `activity_at_hour(schedule, hour)` (reusing the citizen module's
  past-midnight-aware block lookup). `micro.py` stays ignorant of
  `CitizenProfile`.
- **`asphodel/orchestrator.py` — `World`**: `set_citizens(...)` registers the
  population (indexes residents per home zone, ascending-id); a `start_hour` and
  `current_hour()` give the in-game clock the schedule runs on. At promotion,
  `_assign_citizens` deterministically embodies a zone's residents on the first
  agent slots (RNG-free), the rest anonymous; each tick `_update_zone_activity`
  refreshes the activity labels for the new hour. `snapshot()` now exposes
  `citizen_id`, `activity`, `hour`, `activity_names`, and an
  `activity_occupancy` block; `activity_occupancy()` reports per-zone activity
  counts.

## Architecture decisions

- **Activity is a logical label, not physical clustering** (SP1's load-bearing
  decision, preserved). Assigning identity/activity never moves an agent or
  changes density, so the calibrated proximity-transmission model is untouched.
- **Identity assignment is RNG-free and state-free**, so a world with citizens
  registered is *bit-identical* epidemiologically to one without. This is what
  makes the identity layer certifiably calibration-neutral (invariant E).
- **`micro.py` holds only int arrays**; all schedule/citizen knowledge lives in
  `npc.py` + `World`, keeping the hot micro tier ignorant of rich objects.
- **Deterministic embodiment order** (ascending citizen id, first slots) so
  replay is exact.

## Tests executed

**`tests/test_npc_identity.py`: 7 passed.** Full suite **208 passed** (201 + 7).

| Gate item | Test |
|-----------|------|
| identity assignment consumes zero RNG draws | `test_assign_identities_consumes_zero_rng` (compares `rng.bit_generator.state` before/after) |
| arrays stay aligned under add/remove/reconcile | `test_identity_stays_aligned_through_mutations` (position→id fingerprint) |
| promoted agents carry identity; snapshot exposes it | `test_promoted_agents_carry_identity_and_snapshot_exposes_it` |
| schedule activity updates correctly (daily rhythm) | `test_activity_follows_schedule_across_the_day` (sweeps hours, ≥3 distinct activities) |
| **citizens-disabled vs enabled bit-identical** | `test_citizens_disabled_vs_enabled_is_bit_identical` (exact tuple equality, no tolerance) |
| deterministic replay with citizens | `test_deterministic_replay_with_citizens` |
| conservation unaffected | `test_population_conserved_with_citizens` |

## Determinism result

`test_deterministic_replay_with_citizens`: two identical citizen-enabled worlds
produce identical 160-tick compartment trajectories.

## Conservation result

`test_population_conserved_with_citizens`: `total_pop` stays within `1e-6` of the
16 000-person initial total across the full run; deaths accrue (non-trivial run).

## Calibration certification (SP1 = zero curve change)

`test_citizens_disabled_vs_enabled_is_bit_identical` asserts the two full
compartment trajectories (`S,E,Ia,Is,R,D` per tick, 160 ticks) are **exactly
equal** as Python tuples — no tolerance. Manual smoke on a 4×4 city confirmed the
same, with 50 citizens embodied per zone and the remainder anonymous, and activity
occupancy tracking the schedule (`hour 8 → commute:50`). SP1 causes **zero**
epidemic change, as required.

## Known limitations / seams

- **The live bridge does not yet auto-load a bundle's `citizens.json`.** The baked
  `citizens.json` rows carry `home_xy`/`spawn_xy` but not `home_zone`,
  `citizen_id`, or `schedule`, so feeding them to `World.set_citizens` needs a
  `home_xy → zone` mapping and schedule synthesis. `World.set_citizens` is the
  ready seam; wiring the baked population (with generated schedules) into
  `START_WORLD` is deferred to the rendering milestone (M6) where the population
  becomes visible. M2 certifies the identity/activity engine itself.
- Identity currently rides flux: an embodied resident removed by fleeing
  (`remove_agents`) loses its slot, and new arrivals are anonymous. Persistence
  across promote/demote is **M4's** job (SP3), explicitly out of scope here.
- Activity is presentation/label only in M2; it becomes a behavioural input in
  **M3** (SP2).

## Branch / head SHA

- Branch: `claude/asphodel-authoritative-world-55z0qw`
- Head recorded at the M2 commit (see git log).

## Verdict

**PASS** — promoted agents carry citizen identities; schedule activity updates
correctly; the aligned arrays survive every mutation; snapshots expose
identity/activity; the citizens-disabled vs citizens-enabled outbreak trajectory
is bit-identical; deterministic replay and conservation hold. No RNG or
compartment leak was found — the layer is calibration-neutral by construction and
by test.

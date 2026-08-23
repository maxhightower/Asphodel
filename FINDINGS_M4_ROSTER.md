# M4 — Phase 11 SP3: Bounded Named Roster + Uprezzing — Findings

**Milestone:** M4 (Bounded named roster + uprezzing)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PASS**

## Implementation summary

The few citizens the player engages now **persist** across the promote→demote→
re-promote churn, bounded by a hard cap, while everyone else stays anonymous fill.

- **`asphodel/roster.py`** (new): `RosterRecord` (citizen id, profile ref, needs,
  chosen_action, schedule_cursor, last_interaction_tick, promoted_tick,
  interactions) and `Roster` — a hard-bounded store with idempotent event-driven
  `promote`, LRU-by-interaction `_evict_one` (ties → lowest citizen id), `interact`,
  `set_state`, `checkpoint`/`restore_record`. No RNG, no wall-clock — a pure
  function of `(interaction history, tick)`.
- **`asphodel/micro.py` — `AgentZone.restore_citizen(slot, record)`**: stamps a
  restored identity + action label onto an existing slot **without** touching its
  compartment, position, or RNG (conservation-safe).
- **`asphodel/orchestrator.py` — `World`**: holds a `Roster` (`max_roster=64`
  default, configurable). `interact_with(cid)` is the primary event trigger;
  `_update_roster_promotion` adds **signature-in-view** and **sustained focus
  proximity** triggers (deterministic, ascending-id). `_assign_citizens` now
  embodies roster members **first** so they reappear on re-promote;
  `_restore_roster` stamps their persisted state; `_demote_zone` checkpoints
  rostered members' live action before dropping the zone (LRU untouched — leaving
  is not an interaction). `snapshot()` gains a top-level `roster` list and a per-
  agent `named` flag.

## Architecture decisions

- **Persistent state lives in the `Roster`, not on the agent arrays.** The agent's
  `chosen_action` is a *live* reactive label (recomputed every tick from belief), so
  it is not durable state; identity, needs, and interaction history persist in the
  `RosterRecord`. On re-promote, identity is restored (the person reappears) and the
  record persists intact; the live reactive label is recomputed. The checkpointed
  action is restored onto the slot and survives only when reactions are off (a
  save/load and no-reaction concern) — verified in isolation.
- **Disease state across a demote interval is absorbed by the macro** (the SP3 §4
  decision). A restored member reuses an already-counted anonymous slot, so its
  disease state is whatever that slot was sampled as. Identity/history persist;
  exact offscreen disease continuity is explicitly deferred. This is what keeps
  conservation exact with no special-casing.
- **Roster members embodied first at promotion**, so a re-promoted zone always shows
  the people you know (up to capacity), deterministically.
- **Hard bound, LRU-by-interaction eviction, all deterministic** — persistence cost
  is independent of city size and session length.

## Tests executed

**`tests/test_npc_roster.py`: 13 passed.** Full suite **232 passed** (219 + 13).

| Gate item | Test |
|-----------|------|
| bound never exceeded | `test_bound_never_exceeded` |
| LRU-by-interaction eviction + tie-break | `test_lru_by_interaction_eviction`, `test_eviction_tie_break_lowest_id` |
| checkpoint/restore roundtrip | `test_checkpoint_restore_roundtrip` |
| idempotent promotion | `test_promotion_is_idempotent` |
| event-driven promotion (interaction / proximity / signature) | `test_interact_with_promotes`, `test_focus_proximity_promotes_after_sustained_presence`, `test_signature_in_view_promotes` |
| **identity persists across demote→re-promote** | `test_identity_persists_across_demote_and_repromote` |
| checkpointed action restored (reactions off) | `test_checkpointed_action_restored_when_reactions_off` |
| conservation + bound across churn | `test_conservation_and_bound_across_churn` |
| deterministic replay | `test_deterministic_roster_replay` |
| bound independent of city size | `test_bound_independent_of_city_size` |

## Determinism result

`test_deterministic_roster_replay`: two identical runs with the same scripted
`interact_with`/`set_focus` calls at the same ticks produce identical roster-id
sequences at every tick.

## Conservation result

`test_conservation_and_bound_across_churn`: across an 80-day run with focus changes,
interactions, and repeated demote/re-promote, `total_pop` stays within `1e-6` of the
initial 16 000 (16-zone) / 64 000 (64-zone) total at **every** tick, and
`len(roster) <= max_roster` holds at every tick. Restore relabels slots, never
counts — the macro remains authoritative.

## Scalability result

`test_bound_independent_of_city_size`: a 16-zone and a 64-zone city, same seed and
same interactions, reach the **same** peak roster size — persistence memory does not
grow with the map.

## Proof demo (uprezzing)

Meet citizen X (`interact_with(3)`) in focused zone 5 → X is rostered → leave (focus
cleared) → zone 5 demotes → run while demoted → return (`set_focus([5])`) →
re-promote → `citizen_id == 3` is present again, and X's `RosterRecord` (needs,
history) is unchanged across the interval. Bound and conservation hold throughout.

## Known limitations / seams

- **Offscreen individual disease continuity is deferred** (macro absorbs it): a
  restored member's disease state is re-sampled from the zone's live compartment
  distribution, not carried forward. This is the deliberate SP3 fidelity boundary
  (the DF "historical figures keep ticking off-site" upgrade is future work).
- `max_roster=64` is the starting value and is fully configurable; it was not tuned
  against a rendering budget here (that is an M6 benchmark).
- Roster social graph / relationships / dialogue are explicitly out of scope.

## Branch / head SHA

- Branch: `claude/asphodel-authoritative-world-55z0qw`; head at the M4 commit.

## Verdict

**PASS** — player-relevant citizens persist; demote/re-promote restores identity;
the roster hard cap always holds and is city-size-independent; eviction is
deterministic LRU-by-interaction; the macro population stays authoritative with
conservation exact across the churn; and deterministic replay is intact.

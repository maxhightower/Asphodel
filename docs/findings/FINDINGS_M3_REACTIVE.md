# M3 — Phase 11 SP2: Reactive Affordances — Findings

**Milestone:** M3 (Reactive affordances)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PASS**

## Implementation summary

Identified citizens now **react** to the live world — shelter / flee / seek — via a
tiny advertised-affordance utility model, subordinate to designed content and
provably neutral to the epidemic curve.

- **`asphodel/npc.py`**: the need vector `NEEDS = (safety, fatigue, hunger,
  social)`; `choose_action(advertisements, needs, rng, top_k=2)` — scores each
  advertised `(action, utility)` by `utility × the need it serves`, then draws
  among the top-k **weighted by score** (see Decisions); action codes
  `continue_schedule/shelter/flee/seek/signature` with `action_code`/`action_name`;
  `default_needs(safety)`.
- **`asphodel/affordances.py`** (new): `advertise(environment_tags, belief)` — a
  pure projection of place tags + live belief into `[(action, utility)]`. Hazard
  tags (`fire/flood/structural/hazmat/crowd`) advertise `flee`; refuge/supply tags
  advertise `shelter`/`seek`; a belief-scaled `shelter` and inverse-belief
  `continue_schedule` baseline is always present. No content, no numpy, no RNG.
- **`asphodel/micro.py` — `AgentZone`**: a `chosen_action` (`int8`) array threaded
  through create/permute/add/remove exactly like the SP1 arrays.
- **`asphodel/orchestrator.py` — `World`**: each tick, for every identified agent
  in a promoted zone, `_update_zone_reactions` builds the need vector (`safety` ←
  live zone belief), advertises the agent's place, and picks an action with a
  **per-citizen seeded RNG** (`default_rng([cid, tick, seed])`, never
  `AgentZone.rng`). `set_citizen_tags` / `set_signature_citizens` register hazard
  tags and authored-moment membership; `reactions_enabled` toggles the layer;
  `snapshot()` emits `chosen_action` + `action_names`; `reaction_occupancy()`
  reports per-zone action counts.

## Architecture decisions

- **Label-only, provably curve-neutral (the key call).** The SP2 plan proposed
  replacing the micro shelter selection with a rank-based (RNG-free) selection to
  keep the *count* identical. Investigation showed that is **not** curve-safe:
  which agents shelter changes micro transmission (sheltered infectious agents emit
  less), and dropping the existing `set_shelter_fraction` RNG draw also shifts the
  disease stream. So M3 instead keeps the certified belief-driven shelter channel
  **exactly as-is** and treats reactions as **pure `chosen_action` labels**. Result:
  the epidemic curve is **bit-identical** with reactions on or off — the strongest
  form of the gate's "does not accidentally change aggregate dynamics". Making the
  *actual* micro shelter membership follow the reactive labels is a distinct
  certified channel, deferred (see Known limitations).
- **Score-weighted top-k, not uniform top-k.** The plan's `rng.integers(k)` (uniform
  among top-k) makes a 2-affordance choice a 50/50 coin flip regardless of belief —
  its own example test would be flaky. Weighting the top-k draw by score keeps the
  anti-robotic stochasticity (ties stay random) while letting a rising `safety` need
  materially shift the mix. This is what makes the belief-response gate pass.
- **Environment advertises, agent picks** (The Sims inversion): affordances come
  from data (`affordances.py` tag table + belief), not a hard-coded per-agent menu.
- **Designed content wins** (the Oblivion guard): a citizen in a signature moment is
  forced to `signature`; player interventions win implicitly because they drive the
  belief field the reactions read.
- **Determinism**: per-citizen seeded stream keyed by `(citizen_id, tick, seed)`,
  never `AgentZone.rng`.

## Tests executed

**`tests/test_npc_reactive.py`: 11 passed.** Full suite **219 passed** (208 + 11).

| Gate item | Test |
|-----------|------|
| chooser prefers stronger affordance (weighted) | `test_high_safety_need_prefers_shelter_when_offered` |
| chooser deterministic in seed | `test_chooser_deterministic_in_seed` |
| empty → continue_schedule | `test_empty_advertisements_falls_back_to_schedule` |
| tag projection (fire→flee; calm→routine) | `test_fire_place_advertises_flee_and_shelter`, `test_calm_place_favours_routine` |
| **reactions ON vs OFF bit-identical curve** | `test_reactions_on_vs_off_is_bit_identical` |
| belief spike raises shelter/flee | `test_belief_spike_raises_shelter_and_flee` |
| hazard makes flee appear | `test_hazard_makes_flee_appear_under_spike` |
| signature subordination | `test_signature_moment_overrides_utility` |
| determinism of chosen_action | `test_chosen_action_deterministic_across_runs` |
| zero AgentZone.rng, zero state change | `test_reactions_consume_zero_zone_rng` |

## Determinism result

`test_chosen_action_deterministic_across_runs`: two identical citizen runs (with a
broadcast spike) produce identical `(citizen_id, chosen_action)` sequences.
`test_reactions_consume_zero_zone_rng`: a reaction refresh leaves
`zone.rng.bit_generator.state` and `zone.state` untouched.

## Calibration certification (SP2 = zero unintended curve change)

`test_reactions_on_vs_off_is_bit_identical`: full 160-tick `S,E,Ia,Is,R,D`
trajectory is **exactly equal** with the reactive layer enabled vs disabled, on a
16-zone city with 800 embodied citizens. Reactions are labels; they route through no
causal channel. Certified neutral.

## Belief-response evidence

Focus zone, 60 citizens, 12 ticks (from the smoke run):

```
calm       : shelter/flee share 0.00   {continue_schedule:60}
broadcast  : shelter/flee share 0.98   {continue_schedule:1,  shelter:59}
broadcast+fire tag: share 1.00         {shelter:33, flee:27}
```

Routine dominates when calm; a broadcast-driven belief spike flips the zone to
sheltering; a `fire` hazard tag makes fleeing appear alongside it.

## Known limitations / seams

- **Reactions do not (yet) change *which* agents actually shelter in the micro
  model.** To keep the curve provably identical, the transmission-affecting shelter
  set stays the certified belief-driven random selection; `chosen_action` reflects
  reactive *intent* and may not be the identical set of agents. Making the actual
  micro shelter membership follow the labels is a separate channel that must be
  explicitly re-certified (it perturbs the curve in expectation-neutral but not
  bit-identical ways); deferred by design.
- Affordance tags are a small starter table; per-agent *place* resolution
  (signature/environment lookup per tick) is stubbed via `set_citizen_tags`. Full
  per-place advertising is a data-wiring task for M6.
- Reactions run only for identified agents; anonymous fill keeps routine (correct —
  they have no needs).

## Branch / head SHA

- Branch: `claude/asphodel-authoritative-world-55z0qw`; head at the M3 commit.

## Verdict

**PASS** — citizens reactively depart from routine as belief rises; the environment
advertises and the agent picks (seeded, weighted top-k; no planner/behaviour tree);
signature/player authority wins over generic reactions; every reaction is
deterministic and consumes zero `AgentZone.rng`; and the reactive layer is
bit-identical in the epidemic curve to SP1. Performance is a cheap per-identified-
agent loop, well inside the live-bubble budget.

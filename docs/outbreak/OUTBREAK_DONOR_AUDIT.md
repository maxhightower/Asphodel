# Outbreak Donor Audit — `claude/outbreak-config-types-A8fTw` (`bc34bfe`)

**Status:** reference audit for `ASPHODEL_OUTBREAK_V1`. Read-only. The donor
branch was **not** checked out, merged, or applied; every citation below comes
from `git show bc34bfe` / `git show origin/claude/outbreak-config-types-A8fTw:<path>`.

**Donor commit:** `bc34bfe7b2d7dd915068c6ef233ebc12aababe29`, "Add zombie
outbreak archetypes and a reanimation pathway", 2026-06-01, parent `a06f865`.
9 files, +475 / −17.

**Baseline being judged against:** `claude/asphodel-embodied-mobility-v1-6gl4a8`
@ `18e32d5` — macro `Simulation` (S, E, Ia, Is, R, D per zone, per `dt`-day
tick), `AgentZone` (int8 state codes 0..5, torus positions, proximity
transmission), and the embodied runtime (`asphodel/embodied/`: one
`TripExecutor` per persistent citizen, `EmbodimentState`, `building_id`,
`vehicle_id`, continuous positions, driven by `World.advance_seconds` in 1 s
substeps).

**Target of the new milestone:** the outbreak must operate on *individual
persistent citizens* executed by `asphodel/embodied` on the continuous movement
clock, with deterministic seeded rolls, save/load that never re-rolls, and the
state set `susceptible / exposed / incubating / symptomatic / incapacitated /
dead / corpse / undead`.

The donor predates all of that by three months. It is a **macro-tier field
model**. Its *parameters and semantics* are the valuable payload; almost none
of its *code* survives contact with the individual-citizen target.

---

## 1. What the donor commit actually adds

### 1.1 `asphodel/config.py` (+176 / −2)

Line numbers are in the donor's `config.py` as it stands on that branch.

**`PathogenGenome` gains five defaulted-off fields** (donor L61–L79):

| field | default | donor comment / unit |
|---|---|---|
| `reanimation_fraction: float` | `0.0` | fraction of *deaths* that rise instead of staying down; `0` ⇒ an ordinary disease |
| `reanimation_delay: float` | `0.0` | **mean days** a corpse lies before rising; `0` ⇒ rises the instant it falls |
| `turn_on_death: bool` | `False` | universal-latent strain: everyone who dies reanimates *regardless of cause*; overrides `reanimation_fraction` to 1 |
| `undead_infectious: float` | `1.0` | infectiousness of a risen undead **relative to a living symptomatic case** |
| `transmission_route: str` | `"contact"` | one of `contact` / `bite` / `airborne` / `fluid` |

**`_ROUTE_MIXING`** (donor L81–L86) — an *unannotated* class attribute (so it
is not a dataclass field and `asdict()` skips it):
`contact 1.0`, `bite 0.35`, `fluid 0.7`, `airborne 1.8`. These multiply the
inter-zone mobility fraction.

**Three helper methods:**

* `effective_reanimation_fraction()` (L98–L106) — `turn_on_death` ⇒ `1.0`, else
  `reanimation_fraction` clamped to `[0, 1]`.
* `reanimates()` (L108–L110) — `effective_reanimation_fraction() > 0`.
* `route_mixing_multiplier()` (L112–L114) — `_ROUTE_MIXING.get(route, 1.0)`;
  an unknown route silently falls back to the neutral `contact` value.

**Four archetype classmethods** (L117–L180) + `from_archetype(name)`
(L182–L195, raises `ValueError` listing the valid names) + the module-level
**`GENOME_ARCHETYPES`** registry (L200) mapping the four names to the factories.
Exported from `asphodel/__init__.py`.

**`ScenarioConfig` terse genome parsing** — `from_dict` (L378) now delegates to
the new `_genome_from(spec)` staticmethod (L393), which accepts three YAML
forms: a bare archetype name (`genome: rage_virus`), a mapping with an
`archetype:` key plus field overrides (applied via `dataclasses.replace`), or
the existing plain field mapping. `to_yaml` is untouched and still writes the
full explicit mapping.

### 1.2 `asphodel/model.py` (+60 / −17) — the macro undead pathway

* `TickRecord` gains `U: float` (risen undead) and `corpses: float` (dead
  awaiting the rise) — donor L56–L57. These become two new columns in the
  per-tick DataFrame/CSV emitted by `runner.py`.
* `Simulation.__init__` gains two per-zone arrays: `self.U` (risen, infectious,
  never recovers) and `self.C` (corpse latency pool) — donor L92–L94.
* **Force of infection** (L219): `infectious = Ia + Is + undead_infectious * U`.
  The undead are a *standing* transmission source that never drains, which is
  exactly the qualitative difference from a burn-out disease.
* **Route-scaled mixing** (L225):
  `mob = min(mobility * route_mixing_multiplier(), 1.0) * (~cordoned)` — a bite
  strain barely crosses zones, an airborne one reaches far past the source.
* **Numerical clamp** (donor diff on `leave_E`): `leave_E = min(sigma*E*dt, E)`.
  Needed because `rage_virus` has `incubation_period = 0.02 d` so
  `sigma*dt = 12.5 ≫ 1` at `dt = 0.25`, which otherwise drains E negative and
  produces NaNs.
* **Reanimation block** (L272–L287): `rising = effective_reanimation_fraction() *
  Is_death`; `perm_death = Is_death − rising`. With `reanimation_delay > 0`
  bodies go to `C` and drain into `U` at rate `1/delay` per day
  (`min(C/delay*dt, C)`); with delay `0` they rise the same tick.
* **Compartment update** (L295–L297): `D += perm_death`, `C += to_corpses −
  rise_from_corpses`, `U += rise_now + rise_from_corpses`.
* **Belief / authority coupling**: undead count as *visible burden* in both the
  authority perception (L377: `Is + U + D`) and the belief observation channel
  (L397: `Is + U + obs_deaths_weight*D`).
* Explicitly inert when `reanimation_fraction == 0` **and** the route is
  `contact` (multiplier 1.0), so ordinary genomes are byte-for-byte unchanged.

### 1.3 `run.py`, scenarios, exports

* `--archetype {classic_shambler|rage_virus|cordyceps|necro_latent}` and
  `--route {contact|bite|airborne|fluid}` CLI flags, applied *before* the
  explicit `--r0` / `--incubation` overrides so those still win.
* A `final undead (risen)` report line gated on `genome.reanimates()`.
* Four scenario YAMLs (`scenarios/classic_shambler.yaml`, `rage_virus.yaml`,
  `cordyceps.yaml`, `necro_latent.yaml`), each `genome: {archetype: <name>}`,
  `dt: 0.25`, `seed: 0`, `seed_exposed: 50.0`, `n_days` 90–150.
* `GENOME_ARCHETYPES` added to `asphodel/__init__.py`'s imports and `__all__`.

### 1.4 `tests/test_outbreak_types.py` (+201, new)

15 tests: archetype instantiation and `from_archetype` agreement (L49),
unknown-archetype `ValueError` (L60), `turn_on_death` override (L69), fraction
clamping (L78), route-multiplier ordering `airborne > contact ≥ fluid > bite`
plus unknown-route fallback (L83), default genome raises no undead (L91),
reanimating strain does raise undead (L99), **U is monotone non-decreasing**
(L105), rage strain stays finite (L111), **mass conservation over
`S+E+Ia+Is+R+D+U+C`** (L124), no negative compartments (L131), corpses transit
`C` before `U` under a delay (L138), airborne infects more of the grid than
bite by a fixed horizon (L151), YAML full round-trip preserves the zombie
fields (L172), terse archetype YAML forms (L181).

### 1.5 What the donor does *not* contain

No agent/micro-tier changes (`micro.py`, `handoff.py` untouched), no save
schema, no snapshot wire, no renderer palette, no bite mechanic between two
*individuals*, no corpse as a world object, no per-citizen state, no
determinism story beyond the macro `dt` loop. Its "bite" is a scalar mixing
multiplier, not a contact event.

---

## 2. Disposition, concept by concept

| # | Concept | Disposition | Where it lands / why |
|---|---|---|---|
| 1 | `reanimation_fraction`, `reanimation_delay`, `turn_on_death`, `undead_infectious` genome fields | **REUSE** | Copy nearly verbatim into the current `asphodel/config.py::PathogenGenome` (after `mortality_fraction`, L45). Pure data, defaulted off, unit-compatible. `reanimation_delay` is in days — the embodied tier will convert with `* 86400` to the movement clock's seconds. |
| 2 | `effective_reanimation_fraction()`, `reanimates()` | **REUSE** | Verbatim on `PathogenGenome`. They are total functions of the genome with no tier assumptions, and the per-citizen roll wants exactly this number as `p(rise)`. |
| 3 | The four archetype classmethods + `GENOME_ARCHETYPES` + `from_archetype` | **REUSE** (values), **REWRITE** (shape) | The *numbers* carry forward unchanged (§3). The registry should keep its name and API so `run.py --archetype` and scenario YAMLs keep working, but `ASPHODEL_OUTBREAK_V1` will need per-citizen fields the donor never had (bite probability per contact-second, incapacitation window, corpse persistence). Recommend keeping the four factories and *extending* them rather than re-deriving them. |
| 4 | Terse YAML genome form (`_genome_from`, bare name / `archetype:` + overrides) | **REUSE** | Verbatim into `ScenarioConfig.from_dict`. It is a strict superset of today's parser (`PathogenGenome(**genome)` — current L244), and `to_yaml` still writes the explicit mapping, so round-trips are unaffected. This is the cheapest, lowest-risk piece of the donor. |
| 5 | `transmission_route` **as an enum of named routes** | **REUSE** | The label is the right vocabulary and belongs on the genome. |
| 6 | `_ROUTE_MIXING` + `route_mixing_multiplier()` **as an inter-zone mobility scalar** | **REWRITE** | The concept ("how far the pathogen rides") is right; the implementation targets the macro zone graph's `mobility` fraction, which is not where an individual-citizen outbreak transmits. In `ASPHODEL_OUTBREAK_V1` "route" must become a *contact predicate* on the embodied tier: `bite` ⇒ only `ON_FOOT`/`APPROACHING_VEHICLE` citizens within a bite radius of an `undead`; `airborne` ⇒ a per-building/per-vehicle enclosed-space hazard (`building_id`, `vehicle_id` are already the natural containers); `fluid`/`contact` ⇒ proximity with a shorter radius than airborne. Keep `_ROUTE_MIXING` **only** as the macro-tier fallback for unpromoted zones, and move it to a module-level constant (an annotated class attribute would become a dataclass field and break `asdict` round-trips). |
| 7 | Macro `U` compartment | **REWRITE** | Correct as the *aggregate* view, wrong as the authority. In the new milestone the undead are individuals with a `TripExecutor`, a position and (per the target state set) no schedule. `U` should survive as a derived per-zone count written by the same ledger path as `_write_zone` / `STATE_NAMES`, not as an independently integrated field. Note the concrete hazard: `orchestrator.py:826` computes `living = sum(v for k, v in counts.items() if k != "D")` — adding `U`/`corpse` to `STATE_NAMES` without touching that line makes the undead count as *living* in the promotion budget. |
| 8 | Macro `C` (corpse latency pool) with `1/delay` exponential drain | **REWRITE** | The pool semantics are wrong for individuals: an exponential drain is memoryless, so a given corpse has no rise *time*, and reloading a save re-draws it. The new tier needs a per-citizen `rise_at_seconds` stamped once, at death, from a seeded per-citizen stream (`np.random.default_rng([citizen_id, tick, world_seed])` — the pattern already used in `orchestrator._update_zone_reactions`, L968), serialized in the save, and compared against `World.game_seconds`. That satisfies "save/load without re-rolling". |
| 9 | Undead feed the force of infection (`undead_infectious * U`) | **REWRITE** | The *weight* is reusable data; the summation is macro. Per-citizen it becomes the infectiousness weight of an `undead` emitter in the proximity/contact test, exactly analogous to `micro.py::_infectious_weight` (which already weights `Is = 1.0`, `Ia = rel_infectious_asymp`). |
| 10 | Undead as *visible burden* into belief + authority | **REUSE** (concept), **REWRITE** (code) | Keep it: a horde in the street is maximally visible and should ratchet belief and the authority alarm. But the current `_update_belief` / `_update_authority` read per-zone arrays, so the per-zone undead count must be produced by the ledger first. One line each, once `U` exists as a per-zone count. |
| 11 | `leave_E` clamp (`min(sigma*E*dt, E)`) | **REUSE** | A genuine bug fix independent of zombies: any genome with `incubation_period < dt` drains E negative today. Copy verbatim into the current `model.py`. It is a no-op for every existing scenario (baseline incubation 5.0 d ≫ dt 0.25 d), so it changes no committed result. |
| 12 | `mob = min(mobility * multiplier, 1.0)` clamp | **REUSE** (as part of #6's macro fallback) | Correct and necessary once any multiplier exceeds 1 (airborne 1.8 × mobility 0.15 = 0.27, but an OSM bundle with higher mobility could exceed 1). |
| 13 | Ordinary-disease compatibility ("inert when `reanimation_fraction == 0`") | **REUSE** — as a *requirement*, not code | This is the donor's best design decision and the milestone should inherit it as an explicit invariant with a test: a default genome must produce a bit-identical run and a bit-identical save to the pre-outbreak build. |
| 14 | `TickRecord.U` / `TickRecord.corpses` | **REWRITE** | Right idea, but adding fields to `TickRecord` silently widens the runner's CSV (`runner.py:71` `asdict(rec)`) and every downstream reader (`viz.py`, `experiments.py`, `macro_ref.py`, the bridge snapshot). Land it deliberately with the wire/schema bump, not as a side effect. |
| 15 | `run.py --archetype` / `--route` flags, undead report line | **REUSE** | Verbatim; `run.py` has not diverged in the relevant region. |
| 16 | The four scenario YAMLs | **REUSE** | Verbatim, with `n_days` re-tuned once the per-citizen tier exists. They are the cheapest regression fixtures for the terse YAML parser. |
| 17 | `GENOME_ARCHETYPES` export from `asphodel/__init__.py` | **REUSE** | Verbatim. |
| 18 | `rage_virus` as an archetype **without** reanimation | **REUSE** | Valuable as the control case: it exercises every new field at its off value and proves the pathway is genuinely inert. |
| 19 | The donor's *state vocabulary* (`U`, `C` as compartments) | **REJECT** | The milestone's canonical state set is `susceptible / exposed / incubating / symptomatic / incapacitated / dead / corpse / undead` — eight per-citizen states. The donor has neither `incubating` as distinct from `exposed` nor `incapacitated` at all, and it conflates `dead` with `corpse` (a `D` that will never rise vs. a body that will). Do not adopt `U`/`C` as the names or the model; adopt the eight-state enum and derive `U`/`corpse` counts from it. |
| 20 | The donor's belief/authority edits as an *authority* on visibility | **REJECT** | `_update_belief` is already the current authority for belief and the donor's version is a stale fork of it (it predates the `populated` mask, the `N0_safe` denominator and the intervention fields). Re-apply the *idea* (#10) to today's code; never port the donor's hunk. |
| 21 | Donor `run.py` / `model.py` / `config.py` **hunks** as patches | **REJECT** | The donor's parent `a06f865` is ~126 commits behind. `model.py` alone has since gained promoted-zone freezing (`internal_mask`), player interventions (`cordoned`, `mandated_shelter`, `staffing_support`, `broadcast_signal`), the empty-zone `N0_safe`/`populated` handling and the `Ia` re-split clamp. `git apply` would conflict or, worse, silently drop those. Re-type the ~40 lines against the current file. (`config.py` is the exception: the genome region has *not* diverged — see §5.) |
| 22 | Anything modelling *contact between two named people* | **REJECT — absent** | The donor has none. This is the entire substance of `ASPHODEL_OUTBREAK_V1` and must be written from scratch against `TripExecutor` (positions, `EmbodimentState`, `building_id`, `vehicle_id`) on `World.advance_seconds`. The donor is not a starting point for it. |

### Summary judgement

The donor is worth **one file's worth of copy-paste** (`config.py`: fields,
helpers, archetypes, terse YAML — roughly 130 of its 176 added lines), **one
bug fix** (the `leave_E` clamp), **a parameter table** (§3), **a test list**
(§4) and **one design invariant** (defaulted-off ⇒ ordinary diseases
unchanged). Its engine work (`model.py`) is a coarse, memoryless,
compartment-flow sketch of a mechanic the new milestone must implement per
citizen with stamped, saved, seeded timers. Treat `model.py` as *prior art
describing the intended aggregate behaviour* — a useful oracle for
"does the per-citizen tier aggregate to something like this?" — not as code.

---

## 3. Canonical classic-zombie parameters to carry forward

From `PathogenGenome.classic_shambler()` (donor `config.py` L118–L131).
**All time values are in days**; the donor's macro tick is `dt = 0.25 d` (6 h).
Fractions are dimensionless; `undead_infectious` is a *relative* weight.

| donor field | value | donor unit / meaning | how `ASPHODEL_OUTBREAK_V1` should read it |
|---|---|---|---|
| `R0` | `2.2` | basic reproduction number | Macro-tier calibration target only. Per-citizen transmission must be *derived* to reproduce it (the `calibration.py::analytic_contact_prob` path already does this for the micro tier); do not hand-set a bite probability that contradicts it. |
| `incubation_period` | `1.0` | mean days from exposure to infectious (E→Ia) | The `exposed → incubating` dwell: 86 400 game-seconds mean. |
| `symptom_onset_delay` | `0.5` | mean days infectious-but-hidden before visibly symptomatic (Ia→Is) | `incubating → symptomatic`: 43 200 s. |
| `infectious_period` | `4.0` | mean days infectious before resolving to R or D | `symptomatic → incapacitated → dead`: 345 600 s total. The milestone's new `incapacitated` state should be carved out of the *tail* of this window (the donor has no split), e.g. the last ~25 %. |
| `asymptomatic_fraction` | `0.05` | fraction that never becomes visibly symptomatic | 5 % skip `symptomatic` and recover. |
| `mortality_fraction` | `0.95` | fraction of **symptomatic** cases that die | 95 % of symptomatic citizens reach `dead`/`corpse`; 5 % recover. |
| `reanimation_fraction` | `0.9` | fraction of **deaths** that rise | `p(corpse → undead) = 0.9`; the other 10 % stay `dead` permanently. Roll **once, at death**, from the per-citizen seeded stream; persist the outcome. |
| `reanimation_delay` | `0.25` | **mean days** a corpse lies before rising | 21 600 game-seconds (6 h). Stamp `rise_at_s = death_s + draw` once and save it — do **not** re-draw a memoryless `1/delay` rate each tick as the donor does. |
| `undead_infectious` | `1.2` | infectiousness of a risen undead **relative to a living symptomatic case** | The undead emitter weight, 1.2× a symptomatic citizen; and the undead **never** recover, so they are a permanent reservoir. |
| `transmission_route` | `"bite"` | close-quarters route | Macro fallback multiplier `0.35` on inter-zone mobility (donor `_ROUTE_MIXING`, L81–L86). Per-citizen it is the contact predicate: only an on-foot, non-`INSIDE_BUILDING`, non-`IN_VEHICLE` citizen within bite range of an `undead` is exposed. |
| `turn_on_death` | `False` | not a latent-universal strain | The classic shambler only turns those it kills. (`necro_latent` is the `True` variant.) |

Contrast values worth carrying as the other three canonical strains
(donor L134–L180): `rage_virus` — `R0 6.5`, `incubation 0.02 d`,
`infectious 14.0 d`, `asymp 0.0`, `onset 0.01 d`, `mortality 0.99`,
**no reanimation**, `fluid`; `cordyceps` — `R0 2.8`, `incubation 8.0 d`,
`infectious 12.0 d`, `asymp 0.45`, `onset 4.0 d`, `mortality 0.98`,
`reanimation 0.6 / delay 2.0 d`, `undead_infectious 1.5`, `airborne`;
`necro_latent` — `R0 2.0`, `incubation 2.0 d`, `infectious 5.0 d`,
`asymp 0.1`, `onset 1.0 d`, `mortality 0.9`, `reanimation 1.0 / delay 0.5 d`,
`turn_on_death True`, `undead_infectious 1.0`, `bite`.

---

## 4. Donor test ideas worth re-expressing

1. **The pathway is inert by default** (donor `test_default_genome_has_no_undead`,
   L91). Re-express as the stronger milestone invariant: with a default genome,
   a fixed `advance_seconds` sequence produces a *bit-identical* tick series
   **and** a bit-identical `save.world_state` to the pre-outbreak build. No
   citizen ever leaves `susceptible`/`exposed`/…/`dead` for `corpse`/`undead`.
2. **Person conservation** (`test_mass_conservation_with_undead`, L124). Re-express
   over the individual roster: every registered citizen is in exactly one of the
   eight states at every substep, the multiset size is invariant, and the derived
   per-zone counts written back to the macro ledger sum to the same total. This
   is the direct analogue of the existing `handoff.py::round_trip` conservation
   check.
3. **No negative / no impossible state** (`test_no_negative_compartments_with_undead`,
   L131). Per-citizen: every state transition is legal under the state machine
   (no `dead → symptomatic`, no `undead → recovered`), asserted from the
   transition log the way `TripExecutor.state_log` already records embodiment
   transitions.
4. **The undead reservoir never shrinks** (`test_undead_reservoir_never_shrinks`,
   L105). The count of `undead` citizens is monotone non-decreasing absent player
   intervention — the property that distinguishes an outbreak from a disease.
   Worth keeping as a headline behavioural test.
5. **Corpses transit the latency before rising** (`test_reanimation_delay_passes_through_corpses`,
   L138). Re-express with the stamped timer: a citizen that dies at `t` is
   `corpse` for the whole of `[t, rise_at_s)` and `undead` from `rise_at_s`, with
   the stamp visible in the snapshot.
6. **Numerical/edge stability of an extreme strain** (`test_rage_virus_stays_finite`,
   L111). Re-express as: a strain whose dwell times are shorter than one 1 s
   movement substep still transitions exactly once per citizen per stage and
   never skips a state or fires twice.
7. **Route changes reach** (`test_airborne_spreads_further_than_bite`, L151).
   Re-express on the embodied tier: with the same seed and the same schedule day,
   an `airborne` genome infects citizens in more distinct buildings than a `bite`
   genome, whose infections cluster along shared street contacts.
8. **YAML/archetype round-trip** (`test_yaml_full_roundtrip_preserves_zombie_fields`
   L172, `test_yaml_terse_archetype_forms` L181, `test_all_archetypes_instantiate`
   L49, `test_unknown_archetype_raises` L60, `test_turn_on_death_forces_full_reanimation`
   L69, `test_reanimation_fraction_clamped` L78). These test pure config and can be
   **taken almost verbatim** — they are the one part of the donor's suite that
   still compiles against the intended new `config.py`.
9. **New, not in the donor — the determinism/save tests the milestone actually
   needs:** (a) the reanimation roll and the rise timestamp are stamped once and
   survive `save_world` / `load_world_file` unchanged; (b) a run split into two
   `advance_seconds` halves across a save/load boundary yields the same infection
   set as an unbroken run; (c) the outbreak consumes **no** `AgentZone.rng` and
   **no** `MobilityRuntime` draws, so movement stays bit-identical with the
   outbreak on and off (the same guarantee `_update_zone_reactions` already
   documents).

---

## 5. Can the genome/archetype additions merge into the *current* `config.py`?

**Yes — the config half is safe today. The `model.py` half is not, and should
not be attempted as a patch.**

### Field compatibility, concretely

* **The genome region has not diverged.** Current `PathogenGenome`
  (`asphodel/config.py` L26–L55) is textually identical to the donor's parent:
  six fields plus `beta()`. The donor's five new fields are appended after
  `mortality_fraction` and every one has a default, so:
  * `ScenarioConfig.from_dict` (current L244, `PathogenGenome(**data.pop("genome", {}))`)
    keeps working unchanged for every existing config — an old six-key `genome`
    mapping simply takes the new defaults. Replacing it with the donor's
    `_genome_from` is a strict superset.
  * `asdict()`/`to_yaml` (current L233) round-trips the new fields as plain
    `float` / `bool` / `str`, all YAML-safe scalars.
* **`meta.json` genome blocks are forward-compatible.** Every bundle
  (`godot/bundles/*/meta.json`, `godot/sample_bundle/meta.json`) writes exactly
  the six current keys — e.g. Houston: `R0 3.0`, `incubation_period 5.0`,
  `infectious_period 7.0`, `asymptomatic_fraction 0.4`, `symptom_onset_delay 2.0`,
  `mortality_fraction 0.02`. Those load unchanged into the extended genome
  (defaults ⇒ no reanimation, `contact` route ⇒ multiplier 1.0 ⇒ identical
  dynamics). **No bundle rebake is required.**
* **`_ROUTE_MIXING` must stay unannotated** (verified: an unannotated class
  attribute is not a dataclass field, so `asdict()` omits it and `to_yaml`
  stays clean). Safer still: move it to a module-level `_ROUTE_MIXING` constant
  so a future annotation cannot accidentally turn it into a serialized field.
* **The one real compatibility direction to mind is backwards:** once a save or
  scenario YAML is *written* by the extended build, its `genome` block carries
  eleven keys, and an older build's `PathogenGenome(**genome)` raises
  `TypeError`. `save.py::world_state` embeds `asdict(world.cfg)` wholesale and
  the genome block has no version of its own — so the milestone should bump
  `SAVE_VERSION` (and add the new version to `_READABLE_VERSIONS`) at the same
  time, rather than relying on the unversioned genome dict.
* `run.py`'s `--archetype`/`--route` flags and the four scenario YAMLs drop in
  with no other change.

### What would break if the `model.py` half came along

Adding `U`/`C` to the macro engine **without** the rest of the milestone
silently loses the undead at every tier boundary — which is exactly the
`REQUIRES_ARCHITECTURAL_DECISION` recorded in
`docs/convergence/ASPHODEL_BRANCH_DISPOSITION.md` (L47). Concretely, in today's
tree:

* `micro.py` L37–L39: `S, E, IA, IS, R, D = 0..5`, `STATE_NAMES` of length 6,
  `state` as `int8`. A promoted zone has nowhere to put an undead, so
  `handoff.promote` → `AgentZone` → `demote` round-trips would **delete** the
  `U`/`C` mass.
* `orchestrator.py` L554 / L582 / L995 (`_write_zone` over `STATE_NAMES`) —
  the promoted-zone ledger only reads and writes the six names.
* `orchestrator.py:826` — `living = sum(v for k, v in counts.items() if k != "D")`
  would count undead and corpses as *living* in the agent budget.
* `orchestrator.py` L609 — the snapshot's per-zone block enumerates
  `"R"`, `"D"` explicitly; the bridge wire and
  `godot/scripts/citizen_render.gd` L37–L38 (`STATE_COLOR`, indices matching
  `STATE_NAMES`) both assume six states.
* `save.py::agentzone_state` / `restore_agentzone` (L108, L128) serialize the
  int8 state array against those six codes; `SAVE_VERSION` / `_READABLE_VERSIONS`
  (L370–L376) would need a bump.
* `runner.py:71` (`asdict(rec)`) widens the output frame by two columns for
  every consumer (`viz.py`, `experiments.py`, `macro_ref.py`, calibration).

**Recommended split.** Land the donor's `config.py` payload (fields, helpers,
archetypes, `GENOME_ARCHETYPES`, terse YAML, plus the `leave_E` clamp and the
`mob` clamp in `model.py`) as a small, provably-inert first change — it touches
nothing that reads state codes and leaves every existing run byte-identical.
Then build the per-citizen eight-state outbreak on `asphodel/embodied` as the
real milestone, and only afterwards decide whether the macro tier needs its own
`U`/`C` fields at all, or whether per-zone undead counts derived from the
individual roster are sufficient (they probably are — the macro tier is a
ledger of the promoted truth, not an independent authority).

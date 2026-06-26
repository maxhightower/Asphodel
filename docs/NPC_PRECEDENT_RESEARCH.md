# How other games build large NPC populations — and what it says about our plan

*A comparative, source-checked evaluation of the five NPC approaches considered for
Asphodel, against shipped precedent. Companion to
[`PROJECT_ZOMBOID_LESSONS.md`](PROJECT_ZOMBOID_LESSONS.md).*

> **Provenance note.** The claims below split into two buckets, kept deliberately
> separate:
> - **[VERIFIED]** — survived a multi-source, adversarial fact-check (3-vote, kill on
>   2/3 refute). Only four precedents produced verified claims: **Cities: Skylines II,
>   Factorio, Oblivion/Radiant AI, GTA V**. Sources are cited inline.
> - **[DOMAIN]** — well-known architecture from the games industry used to fill gaps the
>   fact-check did **not** cover (The Sims' SmartObjects, Shadow of Mordor's Nemesis,
>   Crusader Kings pops, Watch Dogs: Legion, Dwarf Fortress, RimWorld). Treat these as
>   informed context, not independently re-verified here. The honest coverage gap is
>   itself a finding — see §4.

---

## 1. The comparison set at a glance

| Game / system | How it handles a large population | Speaks to our approach |
|---|---|---|
| **Cities: Skylines II** *[VERIFIED]* | Citizens are *individual simulated agents* with a persistent **"Lifepath"** identity (move-in/birth → age → death), discrete life-event milestones (graduate, promotion, illness, job loss, crime) as event transitions, an **activity menu** (work/school/shop/sleep/study) selected by need/state rather than random walk, and per-citizen state you can follow in a journal UI. CS1's ~65k agent cap was removed. | #1, #2, #3, #4 — closest single precedent |
| **Factorio** *[VERIFIED]* | Hard **deterministic lockstep** ("must remain fully deterministic or a desync happens"). Cuts per-entity cost by **faking smooth motion and only updating periodically**. Interdependent entities must be updated together on one thread. | #5, #1/#2 |
| **Oblivion "Radiant AI"** *[VERIFIED]* | Gave NPCs autonomous goal/need-seeking. Unconstrained, it **broke designed content** (addict NPCs drank the dealer's whole supply, then killed the quest-critical dealer). Bethesda deliberately **toned it down** pre-release. | #3 (cautionary), #4 |
| **GTA V** *[VERIFIED]* | Living-crowd feel is an **engineered illusion**: spatially-weighted spawning (archetypes by zone) + ambient dialogue pools + soundscaping. Ambient peds **despawn** by proximity — they are not persistently simulated. | #4 (the anonymous-crowd half) |
| **The Sims** *[DOMAIN]* | **SmartObjects**: each Sim has a handful of need axes; *objects advertise* weighted "I can satisfy need X by Y" utilities, and the Sim picks the highest-scoring advertisement. Utility AI, data-driven by the environment. | #3 — the canonical precedent |
| **Shadow of Mordor — Nemesis** *[DOMAIN]* | A **bounded roster** of persistent, named, individually-tracked orcs (rivalries, promotions, memory of you) layered over an otherwise anonymous, disposable crowd. | #4 — the canonical precedent |
| **Crusader Kings / Paradox** *[DOMAIN]* | **Named characters as rich data** simulated alongside abstract **"pops"** (homogeneous population blocks). Two explicit tiers: individuals where it matters, statistics everywhere else. | #1, #4 |
| **Watch Dogs: Legion** *[DOMAIN]* | A **census** system procedurally fabricates a schedule/identity for every citizen on demand from a relational backbone, rather than storing millions of full agents. | #2, #4 |
| **Dwarf Fortress** *[DOMAIN]* | The world runs as **abstracted "world-activation" math** (historical figures, populations) until you embark, where a region is promoted to **full tile-and-creature simulation** — then demoted back to math when you leave. | #1 — the canonical promote/demote precedent |
| **RimWorld** *[DOMAIN]* | Deliberately **caps the colony small** (full-fidelity needs/mood AI per colonist) and pushes drama through an **AI Storyteller** that pAces events, rather than scaling agent count. | #1 (the cap), #3 |

---

## 2. Verdict on each considered approach

### #1 — LOD-for-behavior (statistical macro / cheap schedule micro / full near player)
**Strongly validated.** This is mainstream, not novel. CS2 ships per-citizen agents with
explicitly different fidelities of attention *[VERIFIED]*; Factorio's "fake smooth motion,
update periodically" is literally behavioral LOD on cheap entities *[VERIFIED]*; Dwarf
Fortress's embark = promote-to-full / leave = demote-to-math is the exact macro↔micro
pattern Asphodel already implements for epidemiology *[DOMAIN]*; Crusader Kings' named
characters + abstract pops is the same two-tier split *[DOMAIN]*.
**Risk flagged:** CS2 shipped to criticism that some of its "simulated" behavior was buggy
or more abstracted in practice than marketed. Lesson: *advertise the tier honestly.* "Every
citizen is an agent" is defensible; "every citizen is full-fidelity every tick" is a trap.
**→ Keep. It's the consensus architecture.**

### #2 — Schedule-driven agents as the cheap default
**Validated.** CS2's activity menu (work/school/shop/sleep) is exactly "follow a daily
timetable, deflected by state" *[VERIFIED]*. Watch Dogs: Legion fabricates a per-citizen
schedule as the backbone of a believable populace *[DOMAIN]*. The schedule-driven NPC lineage
(Ultima VII → Gothic → Radiant AI) proves daily routines are what *read* as "alive"
*[DOMAIN]*.
**Risk flagged:** the same lineage shows routines break at seams — an NPC's schedule sends
it somewhere now blocked/dangerous and it gets stuck or does something absurd. Asphodel's
mitigation is built-in: the **belief field overrides the schedule** (shelter/flee), so
"world is now dangerous" is a first-class deflection, not an edge case.
**→ Keep. This is the single highest believability-per-line-of-code lever.**

### #3 — Small utility/needs menu, deliberately avoiding behavior trees / GOAP
**Validated *with one concrete refinement.*** The Sims is the canonical proof that a tiny
utility/needs model produces convincing autonomous life *[DOMAIN]*, and CS2's need/state
action selection is a shipped modern instance *[VERIFIED]*. Oblivion is the **load-bearing
cautionary tale** *[VERIFIED]*: a *powerful, unconstrained* autonomous AI layered over
designed content is a known failure mode — it broke quests and had to be reined in. That is
direct evidence **for** keeping our reactive layer small, bounded, and subordinate to
structure, and **against** reaching for GOAP/behavior-tree generality.

> **Refinement worth adopting — invert the menu (Sims SmartObjects).** Our plan has the
> *agent* score a fixed internal menu. The Sims instead has the **environment advertise**
> utilities to the agent ("this building offers shelter +0.6"; "this exit offers escape").
> That inversion is strictly better *for Asphodel specifically*, because we already model
> the environment as data — `signatures.py`, `environments.py`, `travel_events.py` are
> exactly "places/roles advertising what they afford." Letting buildings/roads/roles
> advertise their affordances (a) keeps the per-agent loop trivial (sum advertisements,
> pick max), (b) makes the action space **data-driven and moddable** (our house rule), and
> (c) means adding a new hazard or refuge is one data entry, not an agent-code change. This
> is the most actionable new idea the research surfaced.

**→ Keep, but build it as advertised affordances, not an agent-internal switch. Cap its
authority — it never overrides a designed signature moment, it only fills the gaps.**

### #4 — Bounded persistent named roster + anonymous statistical crowd
**Validated, though on substitute evidence.** GTA V proves the anonymous half directly: a
convincing crowd needs **no** persistent per-individual simulation — spawn + despawn +
archetype texture is enough *[VERIFIED]*. The persistent-named half rests on *[DOMAIN]*
precedent (Shadow of Mordor's Nemesis roster; Crusader Kings' named-characters-vs-pops;
Watch Dogs' census), which the fact-check did **not** independently confirm — flagged
honestly as a gap (§4). Oblivion adds indirect support: bounding the set of fully-autonomous
agents bounds the surface area for emergent content-breakage *[VERIFIED]*.
**Risk flagged:** the hard problem is *promotion churn* — who gets "named" and does that
choice stay reproducible as the player moves and zones promote/demote? Tie roster
membership to deterministic, stable criteria (player proximity + interaction history),
never to spawn order or wall-clock.
**→ Keep. It is the principled cap that stops us re-entering PZ's "simulate everyone" swamp.**

### #5 — Strict determinism (per-agent RNG keyed by citizen id; behavior pure in (id, state, tick))
**Validated as a hard requirement, not a nicety.** Factorio treats full determinism as
non-negotiable — any divergence is a desync *[VERIFIED]*. Asphodel already lives by this
(reproducible from `(config + seed)`, `SeedSequence`-derived per-citizen RNG in
`citizen.py`).
**Risk flagged — the most important technical caution in the whole study:** Factorio found
determinism + **interdependence forces co-update** (entities sharing state must tick
together on one thread) *[VERIFIED]*. This bears directly on our **promote/demote handoff**:
an agent's behavior reads the live belief field and the agent feeds visible burden back —
those are interdependent, so the order of (macro field update ↔ agent decision ↔ reconcile)
must be **fixed and identical every run**, or determinism silently breaks at exactly the
seam Phase 5 already guards for population. Extend the existing conservation-invariant test
to also assert *decision reproducibility* across a promote→demote→re-promote cycle.
**Also flagged:** Factorio's optimization study found **parallelism is not a free win**
(~9.5% overall from heavy optimization; one multithreading attempt raised CPU 0.5%→15% for
*no* speedup) *[VERIFIED]*. Implication: don't reach for threads to scale agents. Reducing
**update frequency** (behavioral LOD, #1/#2) and tightening **data layout** will pay off
more than parallelism. (The stronger "always memory-bandwidth-bound" claim was *refuted* —
treat it as case-dependent.)
**→ Keep, and make decision-order part of the determinism contract + test.**

---

## 3. The strongest evidence-based recommendation

**Do first — the identity↔agent bridge with schedule-following (#1 + #2).** Every shipped
precedent that produces a believable populace cheaply does this, and it's the seam the rest
hangs off. Concretely: a promoted zone spawns *citizens* (carrying `citizen.py` identity +
schedule), and their default behavior is "execute today's timetable," already deflected by
the belief field for shelter/flee. Biggest believability gain, lowest risk, no new AI
paradigm.

**Do second — the reactive layer as advertised affordances (#3, the Sims inversion).** Have
environments/roles/roads advertise utilities; agents sum-and-pick. Keep it subordinate to
signature moments. This is the one place the research changed the plan.

**Cap with the bounded named roster (#4)** and **make decision-order deterministic (#5)**
from the start — both are cheap to design in now and expensive to retrofit.

**Avoid, on direct evidence:**
- **A powerful, unconstrained autonomous AI** that can override designed content — Oblivion
  *[VERIFIED]*. Our deliberate avoidance of GOAP/behavior trees is the *correct* call; the
  research strengthens it.
- **Persisting the whole crowd** — GTA V proves the anonymous mass can be statistical/
  disposable *[VERIFIED]*; spending a persistence budget on every citizen is the PZ swamp.
- **Reaching for multithreading to scale agents** — Factorio *[VERIFIED]*; cut update
  frequency and fix data layout instead.

---

## 4. Honest caveats on this research

1. **Coverage is uneven.** Only 4 of 12 requested precedents produced *verified* claims
   (CS2, Factorio, Oblivion, GTA V). The purpose-built precedents for our approaches —
   **The Sims' SmartObjects (#3)**, **Nemesis / CK pops / Watch Dogs census (#4)**, and
   **Dwarf Fortress's promote/demote (#1)** — appeared in search but their best sources were
   rated low-reliability or dropped on budget, so they are cited here as *[DOMAIN]* context,
   not settled findings. The conclusions for #3 and #4 therefore lean partly on substitute
   evidence (CS2/Oblivion for #3; GTA V for #4). A focused second pass on those four
   primary sources (the Sims GMTK/Forrester talks, the Nemesis GDC talk, the DF "Simulation
   Principles" chapter, the WD:Legion "Census" GDC talk) would convert them from *[DOMAIN]*
   to *[VERIFIED]*.
2. **CS2 marketing vs. reality.** The strongest CS2 evidence is a developer feature page;
   well-corroborated for "citizens are individual agents," weaker for "full-fidelity per
   tick" — which is exactly the line Asphodel should not over-claim either.
3. **Secondary sources.** The Oblivion and GTA V findings rest on games-journalism/blog
   sources (multiply corroborated, developer-attributed, but not primary).
4. **Three claims were refuted** and are excluded: a universal "memory-bandwidth-bound"
   generalization, Radiant AI as a clean utility/satisfaction architecture, and GTA
   archetypes implying a templated non-persistent crowd.

### Sources (verified-claim corpus)
- [Cities: Skylines II — Citizen Simulation & Lifepath (Paradox)](https://www.paradoxinteractive.com/games/cities-skylines-ii/features/citizen-simulation-lifepath)
- [Factorio FFF-421 — optimization & determinism (factorio.com)](https://www.factorio.com/blog/post/fff-421)
- [Oblivion's NPCs nearly killed it — Radiant AI (The Escapist)](https://www.escapistmagazine.com/oblivion-npcs-brought-their-world-to-life-then-they-nearly-killed-it/)
- [Breaking down GTA V's pedestrian dialogue system (Game Developer)](https://www.gamedeveloper.com/design/breaking-down-gta-v-s-pedestrian-dialogue-system-an-analysis-with-speculative-examples)

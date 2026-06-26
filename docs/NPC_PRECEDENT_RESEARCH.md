# How other games build large NPC populations — and what it says about our plan

*A comparative, source-checked evaluation of the five NPC approaches considered for
Asphodel, against shipped precedent. Companion to
[`PROJECT_ZOMBOID_LESSONS.md`](PROJECT_ZOMBOID_LESSONS.md).*

> **Provenance note.** The claims below split into three buckets, kept deliberately
> separate:
> - **[VERIFIED]** — survived a multi-source, adversarial fact-check (3-vote, kill on
>   2/3 refute). Four precedents produced verified claims: **Cities: Skylines II,
>   Factorio, Oblivion/Radiant AI, GTA V**. Sources are cited inline.
> - **[SEARCH-CORROBORATED]** — multiple independent search results return a *consistent*
>   architectural description attributable to named sources, but the primary/technical
>   source could **not** be deep-fetched for adversarial verification because this
>   session's egress policy blocked the content domains (see §4). Applies to **The Sims'
>   SmartObjects, Shadow of Mordor's Nemesis, Dwarf Fortress off-site sim, Watch Dogs:
>   Legion's Census**. Stronger than memory, weaker than [VERIFIED].
> - **[DOMAIN]** — well-known industry architecture used to fill remaining gaps
>   (Crusader Kings pops, RimWorld). Informed context, not independently re-checked here.

---

## 1. The comparison set at a glance

| Game / system | How it handles a large population | Speaks to our approach |
|---|---|---|
| **Cities: Skylines II** *[VERIFIED]* | Citizens are *individual simulated agents* with a persistent **"Lifepath"** identity (move-in/birth → age → death), discrete life-event milestones (graduate, promotion, illness, job loss, crime) as event transitions, an **activity menu** (work/school/shop/sleep/study) selected by need/state rather than random walk, and per-citizen state you can follow in a journal UI. CS1's ~65k agent cap was removed. | #1, #2, #3, #4 — closest single precedent |
| **Factorio** *[VERIFIED]* | Hard **deterministic lockstep** ("must remain fully deterministic or a desync happens"). Cuts per-entity cost by **faking smooth motion and only updating periodically**. Interdependent entities must be updated together on one thread. | #5, #1/#2 |
| **Oblivion "Radiant AI"** *[VERIFIED]* | Gave NPCs autonomous goal/need-seeking. Unconstrained, it **broke designed content** (addict NPCs drank the dealer's whole supply, then killed the quest-critical dealer). Bethesda deliberately **toned it down** pre-release. | #3 (cautionary), #4 |
| **GTA V** *[VERIFIED]* | Living-crowd feel is an **engineered illusion**: spatially-weighted spawning (archetypes by zone) + ambient dialogue pools + soundscaping. Ambient peds **despawn** by proximity — they are not persistently simulated. | #4 (the anonymous-crowd half) |
| **The Sims** *[SEARCH-CORROBORATED]* | **SmartObjects**: each Sim has ~six need axes; *objects advertise* weighted "I can change need X by Y" utilities (a bed advertises +energy, a toilet +bladder); the Sim scores advertisements × its current motive levels and picks **one of the top scorers at random** (not strict max — avoids robotic predictability). Behavior data lives in the *objects*. | #3 — the canonical precedent |
| **Shadow of Mordor — Nemesis** *[SEARCH-CORROBORATED]* | A **bounded roster** of persistent, named captains (memory, fears, scars, rivalries, hierarchy) over an otherwise **disposable, generic** orc crowd. Promotion into the roster is **event-driven** — the orc that lands the killing blow on the player gets named/promoted. | #4 — the canonical precedent |
| **Watch Dogs: Legion** *[SEARCH-CORROBORATED]* | A relational database (**"Census"**) procedurally generates each citizen's identity, schedule, and relationships on demand. NPCs **"uprez"** from background fodder when they matter and are **deleted once you pass them by and move far enough away** — persistence is reserved for the few you engage. | #1, #2, #4 |
| **Dwarf Fortress** *[SEARCH-CORROBORATED]* | The world is generated as you explore and **vanishes as you leave** — *except* historical figures and artifacts, whose **identity persists** off-site as abstracted bookkeeping. Fortress citizens become historical figures and are tracked even after they leave the site. | #1 — the canonical promote/demote precedent |
| **Crusader Kings / Paradox** *[DOMAIN]* | **Named characters as rich data** simulated alongside abstract **"pops"** (homogeneous population blocks). Two explicit tiers: individuals where it matters, statistics everywhere else. | #1, #4 |
| **RimWorld** *[DOMAIN]* | Deliberately **caps the colony small** (full-fidelity needs/mood AI per colonist) and pushes drama through an **AI Storyteller** that pAces events, rather than scaling agent count. | #1 (the cap), #3 |

---

## 2. Verdict on each considered approach

### #1 — LOD-for-behavior (statistical macro / cheap schedule micro / full near player)
**Strongly validated.** This is mainstream, not novel. CS2 ships per-citizen agents with
explicitly different fidelities of attention *[VERIFIED]*; Factorio's "fake smooth motion,
update periodically" is literally behavioral LOD on cheap entities *[VERIFIED]*; Dwarf
Fortress's embark = promote-to-full / leave = demote-to-math is the exact macro↔micro
pattern Asphodel already implements for epidemiology, and DF's rule that the world "vanishes
as you leave — *except* historical figures, whose identity persists" is exactly the
identity-across-the-boundary guarantee our promote/demote needs *[SEARCH-CORROBORATED]*;
Watch Dogs: Legion does the same with "uprezzing" (promote on demand) + proximity-deletion
*[SEARCH-CORROBORATED]*; Crusader Kings' named characters + abstract pops is the same
two-tier split *[DOMAIN]*.
**Risk flagged:** CS2 shipped to criticism that some of its "simulated" behavior was buggy
or more abstracted in practice than marketed. Lesson: *advertise the tier honestly.* "Every
citizen is an agent" is defensible; "every citizen is full-fidelity every tick" is a trap.
**→ Keep. It's the consensus architecture.**

### #2 — Schedule-driven agents as the cheap default
**Validated.** CS2's activity menu (work/school/shop/sleep) is exactly "follow a daily
timetable, deflected by state" *[VERIFIED]*. Watch Dogs: Legion fabricates a per-citizen
schedule as the backbone of a believable populace *[SEARCH-CORROBORATED]*. The schedule-driven NPC lineage
(Ultima VII → Gothic → Radiant AI) proves daily routines are what *read* as "alive"
*[DOMAIN]*.
**Risk flagged:** the same lineage shows routines break at seams — an NPC's schedule sends
it somewhere now blocked/dangerous and it gets stuck or does something absurd. Asphodel's
mitigation is built-in: the **belief field overrides the schedule** (shelter/flee), so
"world is now dangerous" is a first-class deflection, not an edge case.
**→ Keep. This is the single highest believability-per-line-of-code lever.**

### #3 — Small utility/needs menu, deliberately avoiding behavior trees / GOAP
**Validated *with two refinements.*** The Sims is the canonical proof that a tiny
utility/needs model produces convincing autonomous life: each Sim has ~six need axes, objects
*advertise* weighted utilities, and the Sim scores them × current motive levels
*[SEARCH-CORROBORATED]*. CS2's need/state action selection is a shipped modern instance
*[VERIFIED]*. Oblivion is the **load-bearing
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

> **Second refinement — pick randomly among the top scorers, not the strict max.** The Sims
> deliberately selects *one of the top-scoring* advertisements at random rather than always
> the single best, because pure argmax makes agents read as robotic and identical
> *[SEARCH-CORROBORATED]*. For Asphodel this is a free believability win **and** it composes
> with determinism (#5): the "random" pick is drawn from the agent's seeded RNG, so a crowd
> looks varied yet stays exactly reproducible. Use a softmax/top-k draw over advertised
> utilities, seeded per agent.

**→ Keep, but build it as advertised affordances with a seeded top-k pick, not an
agent-internal argmax switch. Cap its authority — it never overrides a designed signature
moment, it only fills the gaps.**

### #4 — Bounded persistent named roster + anonymous statistical crowd
**Validated — and the substitute-evidence gap is now largely closed.** GTA V proves the
anonymous half directly: a convincing crowd needs **no** persistent per-individual
simulation — spawn + despawn + archetype texture is enough *[VERIFIED]*. The persistent-named
half is now corroborated by both canonical precedents: **Nemesis** keeps a bounded roster of
named captains (memory, fears, scars, hierarchy) over a *disposable, generic* orc crowd, with
promotion **event-driven** (the orc that kills you gets named) *[SEARCH-CORROBORATED]*; and
**Watch Dogs: Legion's Census** "uprezzes" an NPC from background fodder only when it matters
and **deletes it once you move far enough away** — persistence reserved for the few you engage
*[SEARCH-CORROBORATED]*. Oblivion adds indirect support: bounding the set of fully-autonomous
agents bounds the surface area for emergent content-breakage *[VERIFIED]*.
**Risk flagged — and Nemesis/Census show the answer:** the hard problem is *promotion churn* —
who gets "named" and does that choice stay reproducible as the player moves and zones
promote/demote? Both precedents make promotion **event-driven and interaction-keyed** (you
killed it / you engaged it), not spawn-order- or timer-based. Mirror that: tie roster
membership to deterministic, stable criteria (player proximity + interaction history), never
to spawn order or wall-clock.
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

1. **The second pass was blocked by egress policy — corroborated, not adversarially
   verified.** A focused second research pass aimed at the four primary sources (Sims
   SmartObjects, Nemesis, Dwarf Fortress "Simulation Principles" PDF, WD:Legion "Census")
   **failed to fetch a single source**: this session's egress proxy returned `403 to CONNECT`
   ("destination host not allowed by organization egress policy") for every content domain —
   `robert.zubek.net`, `gameaipro.com`, `gamedeveloper.com`, `patentarcade.com`,
   `en.wikipedia.org`, etc. Per the proxy README, policy denials must be reported, not routed
   around. `WebSearch` (a separate sanctioned path) still works, so the four precedents were
   instead **upgraded from [DOMAIN] to [SEARCH-CORROBORATED]**: multiple independent search
   results returned consistent, source-attributed architectural descriptions. This is a real
   evidence upgrade, but it did **not** pass the 3-vote adversarial fact-check the [VERIFIED]
   tier requires (no primary text could be fetched to verify against). To reach [VERIFIED],
   re-run when the egress policy permits those domains, or supply the PDFs/transcripts
   directly into the session.
2. **Still genuinely thin:** the exact *bounded-roster size* and promotion economics
   (how many named characters, how aggressively demoted) are not pinned down from primary
   sources for any precedent — treat the roster cap as a tuning parameter to be set
   empirically, not inherited.
3. **CS2 marketing vs. reality.** The strongest CS2 evidence is a developer feature page;
   well-corroborated for "citizens are individual agents," weaker for "full-fidelity per
   tick" — which is exactly the line Asphodel should not over-claim either.
4. **Secondary sources.** The Oblivion and GTA V findings rest on games-journalism/blog
   sources (multiply corroborated, developer-attributed, but not primary).
5. **Three claims were refuted** and are excluded: a universal "memory-bandwidth-bound"
   generalization, Radiant AI as a clean utility/satisfaction architecture, and GTA
   archetypes implying a templated non-persistent crowd.

### Sources — verified-claim corpus (adversarially fact-checked)
- [Cities: Skylines II — Citizen Simulation & Lifepath (Paradox)](https://www.paradoxinteractive.com/games/cities-skylines-ii/features/citizen-simulation-lifepath)
- [Factorio FFF-421 — optimization & determinism (factorio.com)](https://www.factorio.com/blog/post/fff-421)
- [Oblivion's NPCs nearly killed it — Radiant AI (The Escapist)](https://www.escapistmagazine.com/oblivion-npcs-brought-their-world-to-life-then-they-nearly-killed-it/)
- [Breaking down GTA V's pedestrian dialogue system (Game Developer)](https://www.gamedeveloper.com/design/breaking-down-gta-v-s-pedestrian-dialogue-system-an-analysis-with-speculative-examples)

### Sources — search-corroborated (consistent across multiple results; primary text egress-blocked this session)
- The Sims SmartObjects / needs-based AI — [Gaslamp Games "Smart Objects"](https://archive-gaslamp.dredmor.com/2015/04/15/smart-objects-or-everything-i-know-about-ai-i-stole-from-the-sims/), [GMTK "The Genius AI Behind The Sims"](https://gmtk.substack.com/p/the-genius-ai-behind-the-sims)
- Shadow of Mordor Nemesis — [GamesRadar "how it works"](https://www.gamesradar.com/shadow-mordor-nemesis-system-amazing-how-works/), [Shadow of War Wiki — Nemesis](https://shadowofwar.fandom.com/wiki/Nemesis)
- Watch Dogs: Legion Census — [Game Developer "how the play-as-anyone simulation works"](https://www.gamedeveloper.com/design/how-watch-dogs-legion-s-play-as-anyone-simulation-works), [PlayStation Lifestyle "Census relational database"](https://www.playstationlifestyle.net/2019/06/28/watch-dogs-legion-npcs/)
- Dwarf Fortress off-site simulation / identity persistence — [DF Wiki — Historical figure](https://dwarffortresswiki.org/index.php/DF2014:Historical_figure), [Dwarf Fortress — Wikipedia](https://en.wikipedia.org/wiki/Dwarf_Fortress)

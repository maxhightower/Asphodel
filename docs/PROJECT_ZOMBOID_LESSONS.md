# Lessons from Project Zomboid

*What 13+ years of The Indie Stone's development teaches a project like Asphodel — and
where our architecture should deliberately diverge.*

Project Zomboid (PZ) is the closest commercial sibling to what Asphodel is reaching
for: a systems-driven simulation of ordinary life in an ordinary town at the moment a
society-ending outbreak arrives. It launched as a paid pre-alpha in 2011, entered Steam
Early Access in December 2013, and is *still* in Early Access in 2026 — while becoming
one of the most successful indie survival games ever made. That long, public, painful,
and ultimately triumphant arc is a goldmine of lessons. This document pulls out the ones
that bear directly on the decisions Asphodel is making right now.

---

## 1. The headline cautionary tale: NPCs are a tar pit, and Asphodel walked straight at it

PZ's single most-requested and most-criticized feature — surviving NPCs — has been "the
next big thing" for over a *decade*. The Indie Stone, by their own admission, were
"naive to the challenges they'd face in AI." NPCs got entangled with a ground-up
animation-system rewrite (Build 41), and the combination slipped year after year because
the team refused to ship something disappointing. The community ran out of patience long
before the feature ran out of difficulty.

**Why this matters for us:** Asphodel's *entire premise* is the part PZ keeps failing to
ship. We are not building "a survival game with NPCs eventually." We are building the NPC
**population dynamics** as the core — a whole city of citizens with homes, jobs,
commutes, schedules, and a belief-driven collapse. That is enormously ambitious, and it
is exactly the swamp that swallowed PZ's roadmap.

**What we did right, and must keep doing:** the tiered macro↔micro architecture is the
correct structural answer to the NPC tar pit. PZ tries to simulate every NPC as a
full agent. Asphodel says: *most of the city is math* (the macro SEIR + belief field over
a zone graph), and zones are **promoted to discrete agents only inside a budget bubble**
around the player (`World(max_live_zones, max_live_agents)` in `orchestrator.py`). Phase 6
proved a 1000-agent live zone costs <1 ms/tick. This is how you get "a whole city of
people" without needing PZ's unsolved problem of "ten thousand smart agents at once." The
discipline to keep the expensive tier small and bounded is our main defense against PZ's
fate.

**The trap to avoid:** do not let "make the agents smarter" become an open-ended rewrite
that blocks everything else. PZ's NPCs were perpetually "almost ready." Define the
*minimum believable agent* and ship the loop around it; deepen agent AI as graded,
optional increments — never as a gate in front of a playable build.

---

## 2. Ship the smallest playable loop, then iterate in public

PZ was *playable and sold* in 2011 as a tech demo with a fraction of today's systems.
That early, ugly, incomplete build is what funded and sustained the next decade. The
Indie Stone's whole model is "release early, iterate forever, in front of the players."

**For Asphodel:** the README shows we are (correctly) building bottom-up through research
phases — belief cascade (Phase 3a), macro↔micro calibration (4a), the World orchestrator
(5), performance (6), topology (7), interventions (8), citizen spawn, OSM ingestion, the
Godot frontend. The risk in a phase-driven, research-first project is that the
*vertical slice a player can actually touch* keeps getting deferred behind "one more
simulation layer." 

**The lesson:** define the thinnest end-to-end experience — *spawn as one citizen → live
part of a normal day → watch the belief cascade tip → face your collapse situation* — and
treat **that loop** as the thing that must always run, even while the tiers underneath it
keep deepening. The ARK-style character screen + signature-scenario work is exactly this
instinct; protect it. A simulation nobody can play is a research project, not a game, and
PZ's success came from being playable for every one of its 13 years.

---

## 3. Back up your work, decentralize your bus-factor (the laptop theft)

In October 2011, burglars stole the developers' laptops containing a near-complete,
**externally un-backed-up** update. The only off-site backup predated the last release.
Months of work — and money — were lost, possibly irretrievably. The Indie Stone later
gave a talk literally titled *"How (not) to make a video game."*

**For Asphodel, this one is nearly free to get right and catastrophic to get wrong:**

- Everything lives in git and is pushed to a remote. Keep it that way. The determinism
  discipline the project already prizes — runs reproducible from `(config + seed)`,
  bundles "byte-deterministic from `(city, grid, total-pop, seed)`" — means the *outputs*
  are regenerable, but only if the **code and the scenario/config data** survive. Commit
  and push often; never let valuable work sit only on one machine.
- The same determinism is itself a backup strategy: because results are reproducible from
  inputs, we never need to archive gigabytes of output — just the seeds and configs. Lean
  into that.
- Bus-factor: document the architecture as we go (we do — `ARCHITECTURE.md`, the
  `FINDINGS_*` files, the design specs under `docs/superpowers/`). PZ's knowledge was
  concentrated in two people's heads and two people's laptops. Written findings per phase
  are the antidote.

---

## 4. Make it a simulation, not a script — emergence is the product

PZ's enduring appeal is that its stories *emerge*: you didn't script "player bleeds out
in a bathroom because they couldn't find bandages after a dog bite on day 4," the systems
produced it. Their mantra — **"This is how you died"** — sells a sandbox where the
narrative is a consequence of interacting systems, not authored beats.

**Asphodel is already deeply aligned with this**, and it's our biggest strength:

- The belief cascade is a genuine emergent phenomenon — `FINDINGS.md` reports that the
  `Day −1 → Day 0 → collapse` arc *emerges* from coupled fields and is *tunable*, not
  scripted. Phase 7's finding that "concentration, not randomness, synchronizes the
  panic" and Phase 8's that "propping up infrastructure can *increase* deaths by muting an
  alarm the population relied on" are exactly the kind of counter-intuitive systemic
  results that make a simulation worth playing and replaying.
- The signature-scenario system is emergence at the personal scale: the moment you face
  is a *function* of `(who you spawned as, what shift, when collapse lands, where you
  physically are, what road/building/environment you're in)` — a nurse asleep at home has
  her edge back at the hospital. That re-playability-from-systems is the PZ "this is how
  you died" feeling, generated rather than authored.

**The lesson to hold onto:** resist the temptation to hand-author "cool moments." Every
time we're tempted to script an event, ask whether it can instead *fall out of* the
existing taxonomy (signature / travel / aerial / environment / generic). The five-outcome
`CollapseSituation` unifier is the right pattern — keep adding to `default_*_events()`
data, not to bespoke code paths.

---

## 5. Data-driven and moddable from day one is a force multiplier

A huge fraction of PZ's longevity and content comes from its **mod community**. Because so
much of PZ is data and Lua, players extended it for years, which kept the game alive
between official builds and effectively multiplied the dev team.

**Asphodel already has the right instinct** — the README repeats "data, not code" as a
rule: the citizen catalog, city profiles, scenarios, signature scenarios, and environment
events are all YAML/data with deterministic samplers over them ("Add more by editing
`default_catalog()` / `cities/_catalog.yaml`; a job spawns in any city whose map hosts its
workplace category"). 

**The lesson:** keep the data/code seam clean and *eventually expose it*. The things that
should be data — occupations, items, city biases, event tables, scenario knobs — are
data. The payoff PZ proves is real: if a player can add an occupation, a city, or a
collapse event by editing a file, the content space grows without us. Treat the YAML
schemas as a quasi-public API and resist hard-coding content into samplers.

---

## 6. Don't distort the simulation to fit the game clock — warp the clock instead

PZ spent years tuning the relationship between real time, the in-game day, and how fast
things happen — day length, sleep, fast-forward, the pace of needs. Getting "a day" to
feel right while real systems tick underneath is genuinely hard, and PZ iterated on it
endlessly.

**Asphodel made a notably smart call here already.** `gametime.py` keeps the *epidemic's*
calibrated dynamics undistorted and instead **warps the player clock**: `collapse_warp`
pins the player's day 2 onto the simulation's panic tipping day, relaxing toward real-time
near the tip for tension, and `schedule_playback` fast-forwards downtime (PZ's skip key).
This is the right separation of concerns — the science stays honest, the *pacing* is a
presentation layer on top. Keep this firewall: gameplay-feel changes should live in the
time/presentation layer, never as fudge factors smuggled into the difference equations.

---

## 7. Performance is a feature, and you pay for it later if you defer it

PZ's biggest technical millstone was retrofitting systems (notably the animation rewrite,
and multiplayer) onto an engine that wasn't built for them, causing multi-year stalls.
Architecture decisions made early echoed for a decade.

**Asphodel is treating performance as a first-class, *measured* concern early** — Phase 6
replaced the O(n²) neighbour scan with a spatial hash (~600× faster at 10k agents,
*bit-identical* to the old result) and `asphodel.bench` produces a tick-cost + budget
table. That "make it fast but prove it's identical" discipline is exactly right. The
budget-capped live bubble means performance and design are co-designed rather than one
bolted onto the other.

**The lesson:** keep performance work tied to a benchmark and a correctness invariant, and
keep doing it *before* it's a crisis. The thing that sank PZ schedules was discovering
late that the foundation couldn't carry the feature. Our macro/micro boundary, spatial
hash, and budget caps are foundational bets — keep stress-testing them at the scale of a
real OSM city, not just toy grids, so we learn the limits while they're cheap to change.

---

## 8. Manage the roadmap and the community honestly

PZ's relationship with its players has been turbulent precisely *because* of NPCs:
roadmaps promised them, builds slipped, and "where are the NPCs" became a years-long sore
point. The Indie Stone's eventual stance — *we'd rather be late than ship something
disappointing* — is defensible but cost them goodwill because expectations weren't managed
tightly.

**The lesson for us, even pre-community:** be honest in our own docs about what is *done
and proven* versus *stubbed*. The README already does this well — it explicitly flags "the
OpenStreetMap ingestion is the one remaining seam," that single-pass traffic assignment is
"adequate... iterating to user-equilibrium is the documented next step," and that empty-cell
social contagion is "a deferred modelling question." That candor is exactly the muscle PZ
had to learn the hard way. Keep labeling the seams. When there is a community, the same
honesty about what's real vs. aspirational is what preserves trust through long
development.

---

## Summary — the five things to internalize

1. **The NPC swamp is real and we're standing in it.** Our tiered macro↔micro + budget
   bubble is the structural escape hatch PZ never built. Keep the expensive tier small,
   bounded, and never let "smarter agents" become a blocking rewrite.
2. **Always have a playable loop.** Phases deepen the simulation; a thin spawn→day→
   cascade→collapse-moment slice must always run. Don't disappear into research.
3. **Back up and decentralize.** Commit and push relentlessly; lean on determinism so
   inputs (seeds/configs) are the real asset. Document per phase. Remember the laptops.
4. **Emergence over authorship.** Our cascades and signature scenarios already produce
   "this is how you died" stories from systems. Add *data*, not scripted moments.
5. **Protect the foundations early** — performance with benchmarks + invariants, the
   data/code seam for modding, and the clock-warp firewall that keeps the science honest.
   PZ's worst delays came from foundations discovered too late.

---

### Sources

- [Project Zomboid — Wikipedia](https://en.wikipedia.org/wiki/Project_Zomboid)
- [The Indie Stone — PZwiki](https://pzwiki.net/wiki/The_Indie_Stone)
- [Project Zomboid's Chris Simpson talks about a decade of Zomboid, and Build 41 — NME](https://www.nme.com/features/gaming-features/project-zomboids-chris-simpson-talks-about-a-decade-of-zomboid-and-build-41-3129604)
- [Project Zomboid's new roadmap includes ambitious plans for NPCs — PC Gamer](https://www.pcgamer.com/project-zomboids-new-roadmap-includes-ambitious-plans-for-npcs/)
- [The Indie Stone is burgled, loses code for latest Project Zomboid update — Engadget](https://www.engadget.com/2011-10-16-the-indie-stone-is-burgled-loses-code-for-latest-project-zomboi.html)
- [Burglary Delivers Huge Setback to Indie Game Project Zomboid — Kotaku](https://kotaku.com/burglary-delivers-huge-setback-to-indie-game-project-zo-5850245)

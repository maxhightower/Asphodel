# FINDINGS — Asphodel Phase 8: Player interventions

**Question:** *Can a player act on the world through a small, clean intervention
API, and do the interventions produce sensible (and interestingly coupled)
outcomes against the belief/infection/infrastructure fields?*

**Answer: yes — and one of them backfires in a revealing way.** Four levers are
exposed through `World.intervene(...)`; each has its intended first-order effect,
and because everything is a coupled field, they also have honest second-order
consequences. The standout: **propping up infrastructure can *increase* the death
toll**, because keeping the lights on removes an alarm signal the population was
relying on to know it should shelter.

Reproduce: `python -c "from asphodel.experiments import intervention_demo;
intervention_demo()"`. Tests: `python tests/test_interventions.py`.

---

## 1. The intervention API

`World.intervene(action, zones=None, **params)` — `zones` is an index, an
iterable, or `None` (all zones); ignored for the global broadcast.

| Action | Effect on the world |
|---|---|
| `broadcast(level=1.0)` / `stop_broadcast` | Drives the official belief channel directly (an emergency address), **bypassing the authority's observation lag**. |
| `cordon` / `lift_cordon` | **Seals** zones: no inter-zone infection mixing and no fleeing in or out (quarantine). |
| `shelter_order(strength=0.85)` / `lift_shelter_order` | Imposes a **floor on the sheltering fraction** (cuts transmission) regardless of belief. |
| `allocate_staffing(amount=0.4)` / `clear_staffing` | Adds a **staffing bonus** that props power/water up against the infrastructure cascade. |

All four mutate plain macro fields (`cordoned`, `mandated_shelter`,
`staffing_support`, `broadcast_signal`) that the step loop already reads, so a
**promoted (agent) zone inherits them automatically**: agent sheltering is
re-coupled to the live macro belief + any shelter order every tick
(`AgentZone.set_shelter_fraction`), keeping the two tiers consistent under
player action.

---

## 2. Each lever vs doing nothing (applied at day 0)

Baseline scenario (6×6 grid, default genome), interventions applied at day 0:

| variant | final dead | silent until | fully panicked | tip sharpness | peak water-fail |
|---|---|---|---|---|---|
| **no intervention** | 570 | 27.0 | 54.0 | 27.0 d | 62 |
| cordon seed @0 | **37** | — | — | — | 1 |
| broadcast @0 | 44 | 1.5 | 1.5 | 0 d | 64 |
| shelter order @0 | 47 | 2.25 | 2.25 | 0 d | 64 |
| **staffing @0** | **629** | 31.2 | 65.5 | 34.2 d | 0 |
| cordon + shelter | **23** | 2.25 | 2.25 | 0 d | 64 |

Reading the table:

* **Cordon is the single most effective lever** for *deaths* (570 → 37): sealing
  the seed zone the moment the outbreak is known keeps the disease bottled up —
  the rest of the map never gets infected, and only the seed zone's services
  fail. The cost (off-table) is that everyone *inside* the cordon is sacrificed.
* **Broadcast and shelter order both collapse the silent phase to ~day 1–2** and
  cut deaths to ~45 — but at the price of an *instant, total* social tip
  (everyone panics at once, every zone's utilities fail). They trade an epidemic
  for a controlled social shutdown.
* **Cordon + shelter is the best combined outcome** (23 dead): contain the
  source *and* protect everyone else.

---

## 3. The infrastructure paradox (the model has an opinion)

`allocate_staffing` is the only intervention that makes things **worse** (570 →
629 dead). It does exactly what it says — peak water failures go 62 → **0** — but
that is precisely the problem. In the model, failing power/water is one of the
**belief alarm channels** (`w_infrastructure`): people partly *learn the
situation is serious by watching the lights go out*. Prop the infrastructure up
and you mute that signal; belief rises later and less, so **less sheltering
happens, the effective R0 stays higher, and more people die** — the tip even
*sharpens slightly later* (27 → 34 days) and the epidemic burns hotter.

This is not a bug; it is the "everything is a coupled field" premise paying off:
a well-meaning intervention that treats a *symptom* (infrastructure strain)
without the *driver* (perceived danger) can be counterproductive. For the game it
is exactly the kind of non-obvious tradeoff that makes the levers interesting —
keeping the city comfortable can keep it complacent.

---

## 4. Conclusion

The player can act on the world through four composable interventions, applied to
any subset of zones, that flow through both the macro field update and any live
agent zone. They behave sensibly individually, compose sensibly together
(cordon + shelter is the strongest combination), and at least one carries a
genuine emergent tradeoff. The simulation core is now player-driveable; the
remaining work before Godot is **save/load** (Phase 9), after which the front-end
only renders `snapshot()` and forwards input to `intervene()`.

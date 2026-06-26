# Phase 11 · Sub-project 2 — Reactive Layer via Advertised Affordances (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (TDD). Python only. Tests self-run (`python tests/test_<x>.py`); `python -m pytest -q` if pytest is present. `pip install -r requirements.txt` first (numpy/pyyaml). **Depends on SP1 being merged** (`citizen_id`/`activity` arrays, `asphodel/npc.py`, `World(citizens=…)`). Steps use checkbox (`- [ ]`) syntax.

**Goal:** When the world deviates from routine, agents **react** — shelter, flee, or seek safety — chosen by a tiny utility/needs model in which the **environment advertises** weighted affordances (The Sims' SmartObjects inversion). The reactive layer is **subordinate to designed signature moments** and **must not move the epidemic curve except through the already-calibrated shelter/flee channels**.

**Spec:** [`../specs/2026-06-26-npc-behavior-phase11-design.md`](../specs/2026-06-26-npc-behavior-phase11-design.md) §6
**Evidence:** [`../../NPC_PRECEDENT_RESEARCH.md`](../../NPC_PRECEDENT_RESEARCH.md) — The Sims (advertised utilities; **pick top-k at random, not argmax**), Oblivion (never let autonomous AI override designed content).

---

## The design decisions this plan locks in

1. **Environment advertises, agent picks (the Sims inversion).** The agent does *not* own a hard-coded menu. Places/roles expose `advertise(...) -> [(action, utility)]` sourced from existing **data tables** (`environments.py`, `signatures.py`, `travel_events.py`). Adding a hazard or refuge is one data entry — our house rule.

2. **Calibration-safe, same trick as SP1.** The aggregate **shelter fraction stays belief-driven and unchanged** (the orchestrator already sets it from live belief via `set_shelter_fraction`). The utility layer only chooses **which specific agents** fill that existing quota (the highest-`safety`-need ones) instead of a random subset, and assigns a per-agent **action label** for rendering. Same count sheltered ⇒ **epidemic curve byte-identical** to SP1. "Flee" likewise re-selects *which* agents are the belief-driven fleers; it never invents new movement. Pure-label actions (`continue_schedule`, `seek`) have no curve effect.

3. **Subordinate to designed content (the Oblivion guard).** Action set is exactly `{continue_schedule, shelter, flee, seek}`. The pick can **never** override an eligible signature moment (`signatures.py`) or a player `intervene(...)`. Reactive fills gaps; it does not author drama.

4. **Determinism.** The "random among top-k" draw uses a **per-citizen seeded** stream keyed by `citizen_id` (reuse `citizen.py`'s `SeedSequence` scheme), and **must not consume `AgentZone.rng`** — so the curve-identity guarantee from SP1 still holds. Anonymous agents (`citizen_id == −1`) do not react (they have no needs); they keep SP1 behavior.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `asphodel/affordances.py` | create | `advertise(context) -> list[(action, utility)]` adapters over `environments.py` / `signatures.py` / `travel_events.py`; the `ACTIONS` table. Pure data→tuples, no numpy. |
| `asphodel/npc.py` | modify | Need vector (`safety/fatigue/hunger/social`) helpers; `choose_action(advertisements, needs, rng)` — score = Σ(utility×need), seeded top-k draw. |
| `asphodel/micro.py` | modify | `AgentZone` gains a `chosen_action` (int8) array (threaded like SP1's arrays) and `set_sheltered_by_rank(frac, key)` — fill the existing shelter quota by a ranking key instead of at random. |
| `asphodel/orchestrator.py` | modify | Build per-agent needs (`safety` ← live belief), run `choose_action` for B2 agents, map results onto the shelter/flee quotas + `chosen_action`; expose in `snapshot()`. |
| `tests/test_npc_reactive.py` | create | Curve-identity, subordination, determinism, "belief spike ⇒ shelter/flee actions rise." |

**Scope guard — NOT in SP2:** persistence/roster (SP3); new physical movement; relationships. The reactive layer reads belief and re-labels/re-selects within existing quotas only.

---

## Task 1: The needs vector + action chooser (pure, TDD)

**Files:** modify `asphodel/npc.py`; create `tests/test_npc_reactive.py`

- [ ] **Step 1: Failing test for `choose_action`**

```python
"""SP2: advertised-affordance action selection (pure, seeded, top-k)."""
import numpy as np
from asphodel.npc import choose_action, NEEDS

def _rng(cid): return np.random.default_rng(cid)

def test_high_safety_need_prefers_shelter_when_offered():
    ads = [("continue_schedule", 0.3), ("shelter", 0.9), ("flee", 0.5)]
    needs = {"safety": 1.0, "fatigue": 0.0, "hunger": 0.0, "social": 0.0}
    # With safety dominant and shelter the top affordance, expect shelter most of the time.
    picks = [choose_action(ads, needs, _rng(i)) for i in range(200)]
    assert picks.count("shelter") > picks.count("flee")

def test_deterministic_in_seed():
    ads = [("shelter", 0.6), ("flee", 0.6), ("seek", 0.6)]
    needs = {n: 0.5 for n in NEEDS}
    assert choose_action(ads, needs, _rng(7)) == choose_action(ads, needs, _rng(7))

def test_empty_advertisements_falls_back_to_schedule():
    assert choose_action([], {n: 0.5 for n in NEEDS}, _rng(1)) == "continue_schedule"
```

- [ ] **Step 2: Implement in `asphodel/npc.py`**

```python
NEEDS = ("safety", "fatigue", "hunger", "social")

# Which need each action chiefly satisfies (for scoring).
_ACTION_NEED = {
    "continue_schedule": "fatigue",   # routine satisfies low-arousal needs
    "shelter": "safety",
    "flee": "safety",
    "seek": "hunger",
}

def choose_action(advertisements, needs, rng, top_k: int = 2):
    """Score each advertised (action, utility) by utility * the need it serves,
    then draw one of the top-k at random (Sims anti-robotic rule). Seeded by the
    caller's per-citizen rng -> deterministic. Empty -> 'continue_schedule'."""
    if not advertisements:
        return "continue_schedule"
    scored = sorted(
        ((u * float(needs.get(_ACTION_NEED.get(a, "safety"), 0.0)), a)
         for a, u in advertisements),
        reverse=True,
    )
    k = min(top_k, len(scored))
    return scored[int(rng.integers(k))][1]
```

- [ ] **Step 3: Pass** — `python tests/test_npc_reactive.py` (these three). Commit: `feat(npc): needs vector + seeded top-k action chooser`.

---

## Task 2: Affordance advertisers over the existing data tables

**Files:** create `asphodel/affordances.py`

- [ ] **Step 1: Read the real data tables first** — `asphodel/environments.py` (`default_environment_events()` and the `EnvironmentEvent`/event fields), `asphodel/signatures.py` (`SignatureScenario`: `assets`, `hazards`, `tags`, `location`), `asphodel/travel_events.py`. Note their actual field names; the sketch below assumes `tags`/`hazards`/`assets` lists — adapt to reality and report any change.

- [ ] **Step 2: Implement `advertise`**

```python
"""Map Asphodel's existing situation data (environments / signatures / travel)
into weighted affordances an agent can act on. Data -> [(action, utility)]; no
new content lives here, only a projection of what the tables already say."""
from __future__ import annotations

# Tag -> the affordance it implies and a base utility in [0,1].
_TAG_AFFORDANCE = {
    "fire": ("flee", 0.9), "flood": ("flee", 0.9), "structural": ("flee", 0.8),
    "hazmat": ("flee", 0.85), "crowd": ("flee", 0.5),
    "shelter": ("shelter", 0.7), "supplies": ("seek", 0.6),
    "keys_access": ("seek", 0.5), "tools": ("seek", 0.4),
}

def advertise_from_tags(tags) -> list[tuple[str, float]]:
    out = []
    for t in (tags or ()):
        if t in _TAG_AFFORDANCE:
            out.append(_TAG_AFFORDANCE[t])
    return out

def advertise(environment_tags=None, belief: float = 0.0) -> list[tuple[str, float]]:
    """Affordances offered to an agent in a place with these tags under this
    zone belief. Higher belief raises the standing 'shelter' offer (the safe
    default), so a tense-but-unhazardous place still invites sheltering."""
    ads = advertise_from_tags(environment_tags)
    ads.append(("shelter", 0.2 + 0.6 * float(belief)))   # always-available baseline
    ads.append(("continue_schedule", max(0.1, 1.0 - float(belief))))
    return ads
```

- [ ] **Step 3: Test the projection** — add to `tests/test_npc_reactive.py`: a high-belief place with a `fire` tag advertises both `flee` (high) and `shelter`; a calm place (belief 0, no tags) advertises `continue_schedule` highest. Commit: `feat(affordances): project environment/signature tags to advertised actions`.

---

## Task 3: Wire reactions into the orchestrator (curve-safe)

**Files:** modify `asphodel/micro.py`, `asphodel/orchestrator.py`

- [ ] **Step 1: `chosen_action` array on `AgentZone`** — add `self.chosen_action = np.zeros(self.n, dtype=np.int8)` in `__init__`/`from_counts` and thread it through `add_agents`/`remove_agents` exactly like SP1's `activity` array (arrivals → 0 = `continue_schedule`).

- [ ] **Step 2: Quota-preserving shelter selection** — add to `AgentZone`:

```python
    def set_sheltered_by_rank(self, frac: float, key: np.ndarray) -> None:
        """Shelter the SAME count as set_shelter_fraction(frac) would, but pick
        the highest-`key` agents instead of a random subset. Keeps the aggregate
        shelter fraction (and thus the calibrated beta reduction) identical while
        making *which* agents shelter meaningful. rng-free."""
        self.params = replace(self.params, shelter_fraction=float(np.clip(frac, 0, 1)))
        self.sheltered = np.zeros(self.n, dtype=bool)
        k = int(round(float(np.clip(frac, 0, 1)) * self.n))
        if k > 0:
            top = np.argpartition(-key, k - 1)[:k] if k < self.n else np.arange(self.n)
            self.sheltered[top] = True
```

- [ ] **Step 2a: Audit** — confirm `set_sheltered_by_rank` reproduces the *same `k`* as the existing `set_shelter_fraction` (same rounding), so the aggregate is identical. The only change is membership, not count.

- [ ] **Step 3: Build needs + choose actions in `World.step`** — in the promoted-zone loop, *replacing* the existing `zone.set_shelter_fraction(...)` call for citizen zones:

```python
        from .npc import choose_action, NEEDS
        from .affordances import advertise
        belief_z = float(self.sim.belief[z])           # live zone belief
        shelter_frac = float(shelter_vec[z])           # unchanged, belief-driven
        pop = getattr(zone, "_npc_pop", None)
        if pop:
            named = np.where(zone.citizen_id >= 0)[0]
            safety_key = np.zeros(zone.n)
            for slot in named:
                prof = pop[slot] if slot < len(pop) else None
                if prof is None:
                    continue
                needs = {"safety": belief_z, "fatigue": 0.3, "hunger": 0.2, "social": 0.2}
                tags = _situation_tags(prof, belief_z)         # see Step 4
                rng = _citizen_rng(prof.citizen_id, self.sim.tick)
                act = choose_action(advertise(tags, belief_z), needs, rng)
                zone.chosen_action[slot] = _ACTION_CODE[act]
                safety_key[slot] = belief_z if act in ("shelter", "flee") else 0.0
            zone.set_sheltered_by_rank(shelter_frac, safety_key)
        else:
            zone.set_shelter_fraction(shelter_frac)    # anonymous zone: unchanged
```

- [ ] **Step 4: Signature subordination + helpers** — `_situation_tags(prof, belief)` returns the environment/signature tags for the agent's current place (reuse `resolve_collapse_situation` / the signature's `tags` only when the agent is *not* in an active signature moment; if a signature is eligible, **force** `chosen_action = signature` and skip the utility pick — the Oblivion guard). `_citizen_rng(cid, tick)` derives a `SeedSequence(cid, tick)` generator (never `zone.rng`). Add `_ACTION_CODE`/`ACTIONS` to `npc.py`.

- [ ] **Step 5: snapshot** — emit `zone.chosen_action.tolist()` per promoted zone. Commit: `feat(npc): belief-driven advertised reactions, quota-preserving shelter`.

---

## Task 4: The gating invariants

**Files:** add to `tests/test_npc_reactive.py`

- [ ] **Step 1: Curve-identity (load-bearing)** — same construction as SP1 Task 4 Step 1, but now with SP2 active: a `World(citizens=…)` run with the reactive layer on must be **bit-identical in S/E/Ia/Is/R/D** to the SP1 baseline (reactions only re-select *which* agents shelter, never the count). If it diverges, `set_sheltered_by_rank`'s `k` differs from `set_shelter_fraction`'s, or something consumed `zone.rng` — fix the leak, don't loosen.

- [ ] **Step 2: Reaction responds to belief** — force a belief spike in the focus zone (via `intervene("broadcast", level=1.0)` or a seeded high-belief scenario); assert the share of agents with `chosen_action ∈ {shelter, flee}` rises materially vs a calm baseline.

- [ ] **Step 3: Subordination** — when an agent is in an eligible signature moment, its `chosen_action` is `signature` regardless of advertised utilities.

- [ ] **Step 4: Determinism** — two identical `citizens=` runs produce identical `chosen_action` sequences. Commit: `test(npc): reactive curve-identity + belief-response + subordination + determinism`.

---

## Task 5: Docs

- [ ] **Step 1:** README note: agents now react (shelter/flee/seek) to advertised affordances under live belief, subordinate to signatures, curve-neutral.
- [ ] **Step 2:** Append to `FINDINGS_PHASE11.md`: confirm curve-identity held with reactions on; paste a belief-vs-shelter-share curve. Commit: `docs: SP2 readout`.

---

## Done criteria (SP2)

- The environment advertises affordances from existing data tables; agents pick via seeded top-k (no argmax, no GOAP/behavior trees).
- The epidemic curve is **byte-identical** to SP1 (reactions re-select shelter membership within the unchanged belief-driven quota).
- A belief spike measurably raises shelter/flee action shares; signature moments always win; all runs deterministic.

**Next:** SP3 — bounded named roster + uprezzing (persist the few you engage across demote→re-promote; the part that makes `_demote_zone` stop discarding identity).

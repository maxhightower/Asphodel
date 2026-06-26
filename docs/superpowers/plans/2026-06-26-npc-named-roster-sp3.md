# Phase 11 · Sub-project 3 — Bounded Named Roster + Uprezzing (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (TDD). Python only. Tests self-run (`python tests/test_<x>.py`); `python -m pytest -q` if pytest is present. `pip install -r requirements.txt` first. **Depends on SP1 (identity arrays, `World(citizens=…)`) and SP2 (needs/`chosen_action`).** Steps use checkbox (`- [ ]`) syntax.

**Goal:** Persist a **bounded roster** of named citizens — the few the player actually engages — *across* the promote→demote→re-promote churn, so re-entering a place shows **the same people** with their identity, needs, and history intact. Everyone else stays an anonymous, disposable statistical fill. This is the principled cap that keeps persistence cost independent of city size — the escape from Project Zomboid's "simulate everyone" swamp.

**Spec:** [`../specs/2026-06-26-npc-behavior-phase11-design.md`](../specs/2026-06-26-npc-behavior-phase11-design.md) §7
**Evidence:** [`../../NPC_PRECEDENT_RESEARCH.md`](../../NPC_PRECEDENT_RESEARCH.md) — Nemesis (event-driven promotion, killing blow → named), Watch Dogs: Legion (**"uprezzing"**: promote on demand, delete when you move far enough away), Dwarf Fortress (the world vanishes as you leave **except historical figures**, whose identity persists off-site).

---

## The design decisions this plan locks in

1. **Two populations, hard cap.** A **named roster** of at most `max_roster` (e.g. 64) persistent records, plus an **anonymous crowd** that is spawned/despawned freely and never persisted. The roster size is a tuning knob (the research could not pin an exact number — see `FINDINGS_PHASE11.md`), and the bound holds regardless of city size or session length.

2. **Promotion is event-driven and interaction-keyed — NOT spawn-order or timer.** A citizen enters the roster when the player **interacts with / profiles** them, when they are **near the focus** for sustained time, or when they hit a **signature moment in view**. This is the Nemesis/Census rule and it is what keeps promotion *reproducible* under determinism (a pure function of interaction history + tick).

3. **Uprezzing: `_demote_zone` must stop discarding identity.** Today `_demote_zone` just `self.promoted.pop(z)` — the `AgentZone` and all identity vanish. SP3 changes it to **checkpoint roster members** (identity, needs, `chosen_action`, schedule cursor, last-interaction tick) into a `World`-level roster store before dropping the zone. On **re-promote**, roster members are **restored** onto agent slots; anonymous slots fill from counts as today.

4. **Disease state across a demote interval is intentionally absorbed by the macro.** While a zone is demoted it evolves as math; the macro does not track an individual's compartment. So on re-promote a roster member's **disease state is re-sampled from the zone's live compartment distribution** (conservation-exact: it occupies an already-counted slot). **Identity, needs, relationships, and history persist; exact disease continuity does not.** This keeps the population ledger exactly conserved (the Phase-5 guarantee) with no special-casing. *(Faithful upgrade, deferred: advance each roster member's individual disease state by the demoted zone's force-of-infection per tick — the DF "historical figures keep ticking off-site" model. Noted in §Open.)*

5. **Determinism + conservation are the two invariants.** Roster membership, eviction (LRU-by-interaction), and restore are pure functions of `(interaction history, tick)`; `Σ macro_float` is unchanged across any promote/demote/restore (re-promote overwrites slot *labels/needs*, not compartment counts).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `asphodel/roster.py` | create | `RosterRecord` (citizen_id, profile ref, needs, chosen_action, last_interaction_tick) + `Roster` (bounded store: `promote`, `evict`, `checkpoint`, `restore`, `interact`). Pure Python, deterministic. |
| `asphodel/orchestrator.py` | modify | Hold a `Roster`; event-driven promotion hooks (`interact_with`, focus-proximity, signature-in-view); `_demote_zone` checkpoints; `_promote_zone` restores; expose roster in `snapshot()`. |
| `asphodel/micro.py` | modify | `restore_citizen(slot, record)` — stamp a restored identity/needs/action onto a slot without touching its compartment (conservation-safe, rng-free). |
| `tests/test_npc_roster.py` | create | Persistence across demote→re-promote, bound, event-driven promotion, eviction, conservation, determinism. |

**Scope guard — NOT in SP3:** social graph / relationships / dialogue between roster members (the deep Nemesis layer); off-site individual disease ticking (the faithful upgrade in §Open); Godot rendering of named vs anonymous (Phase 12).

---

## Task 1: The bounded roster store (pure, TDD)

**Files:** create `asphodel/roster.py`, `tests/test_npc_roster.py`

- [ ] **Step 1: Failing test**

```python
"""SP3: bounded persistent named roster — promotion, bound, eviction, checkpoint."""
from asphodel.roster import Roster, RosterRecord

def test_bound_never_exceeded():
    r = Roster(max_roster=4)
    for cid in range(20):
        r.promote(cid, profile=None, tick=cid)
    assert len(r) <= 4

def test_lru_by_interaction_eviction():
    r = Roster(max_roster=2)
    r.promote(1, None, tick=0); r.promote(2, None, tick=1)
    r.interact(1, tick=5)                 # 1 is now more-recently engaged than 2
    r.promote(3, None, tick=6)            # full -> evict least-recently-interacted (2)
    assert r.contains(1) and r.contains(3) and not r.contains(2)

def test_checkpoint_restore_roundtrip():
    r = Roster(max_roster=4)
    r.promote(7, None, tick=0)
    r.set_state(7, needs={"safety": 0.8}, chosen_action=2, tick=3)
    rec = r.checkpoint(7)
    assert rec.citizen_id == 7 and rec.needs["safety"] == 0.8 and rec.chosen_action == 2
    # survives a demote interval and is retrievable unchanged
    assert r.restore_record(7) == rec

def test_promotion_is_idempotent():
    r = Roster(max_roster=4)
    r.promote(7, None, tick=0); r.promote(7, None, tick=1)
    assert len(r) == 1
```

- [ ] **Step 2: Implement `asphodel/roster.py`**

```python
"""A bounded, deterministic store of persistent named citizens. Promotion is
event-driven (interaction/proximity/signature), eviction is LRU-by-interaction.
No rng, no wall-clock -> reproducible from (interaction history, tick)."""
from __future__ import annotations
from dataclasses import dataclass, field, replace

@dataclass
class RosterRecord:
    citizen_id: int
    profile: object = None
    needs: dict = field(default_factory=dict)
    chosen_action: int = 0
    schedule_cursor: int = 0
    last_interaction_tick: int = 0

class Roster:
    def __init__(self, max_roster: int = 64):
        self.max_roster = int(max_roster)
        self._members: dict[int, RosterRecord] = {}

    def __len__(self): return len(self._members)
    def contains(self, cid: int) -> bool: return cid in self._members

    def promote(self, cid: int, profile, tick: int) -> None:
        if cid in self._members:
            self._members[cid].last_interaction_tick = tick
            return
        if len(self._members) >= self.max_roster:
            self._evict_one(tick)
        self._members[cid] = RosterRecord(cid, profile, last_interaction_tick=tick)

    def _evict_one(self, tick: int) -> None:
        # Deterministic: lowest last_interaction_tick, ties broken by lowest cid.
        victim = min(self._members.values(),
                     key=lambda r: (r.last_interaction_tick, r.citizen_id))
        del self._members[victim.citizen_id]

    def interact(self, cid: int, tick: int) -> None:
        if cid in self._members:
            self._members[cid].last_interaction_tick = tick

    def set_state(self, cid, needs=None, chosen_action=None, tick=None) -> None:
        rec = self._members.get(cid)
        if rec is None: return
        if needs is not None: rec.needs = dict(needs)
        if chosen_action is not None: rec.chosen_action = int(chosen_action)
        if tick is not None: rec.last_interaction_tick = tick

    def checkpoint(self, cid: int) -> RosterRecord:
        return replace(self._members[cid])           # a copy (survives demote)

    def restore_record(self, cid: int) -> RosterRecord:
        return self._members[cid]

    def members(self): return list(self._members.values())
```

- [ ] **Step 3: Pass** — `python tests/test_npc_roster.py`. Commit: `feat(roster): bounded deterministic named-citizen store`.

---

## Task 2: Uprezzing — checkpoint on demote, restore on promote

**Files:** modify `asphodel/orchestrator.py`, `asphodel/micro.py`

- [ ] **Step 1: Hold a `Roster` on `World`** — in `__init__`, `self.roster = Roster(max_roster=max_roster or 64)` (add a `max_roster` param, defaulted). When no `citizens` are supplied, the roster simply stays empty → existing behavior unchanged.

- [ ] **Step 2: `restore_citizen` on `AgentZone`** (conservation-safe, rng-free)

```python
    def restore_citizen(self, slot: int, record) -> None:
        """Stamp a restored identity onto an existing slot WITHOUT changing its
        compartment (the macro ledger already counts it). Restores identity,
        need-driven action label, etc. -- not disease state."""
        if 0 <= slot < self.n:
            self.citizen_id[slot] = int(record.citizen_id)
            self.chosen_action[slot] = int(getattr(record, "chosen_action", 0))
```

- [ ] **Step 3: Checkpoint in `_demote_zone`**

```python
    def _demote_zone(self, z: int) -> None:
        zone = self.promoted.get(z)
        if zone is not None:
            for slot in np.where(zone.citizen_id >= 0)[0]:
                cid = int(zone.citizen_id[slot])
                if self.roster.contains(cid):
                    self.roster.set_state(cid, chosen_action=int(zone.chosen_action[slot]),
                                          tick=self.sim.tick)
        self.promoted.pop(z, None)     # macro ledger already holds the counts
```

- [ ] **Step 4: Restore in `_promote_zone`** — after the existing identity assignment (SP1 Task 2 Step 2), restore any roster members whose home is this zone onto free slots:

```python
        zone = self.promoted[z]
        restored = 0
        for rec in self.roster.members():
            if restored >= zone.n: break
            if getattr(rec.profile, "home_zone", None) == z:
                # Occupy a slot currently anonymous, preserving its compartment.
                free = np.where(zone.citizen_id < 0)[0]
                if free.size:
                    zone.restore_citizen(int(free[0]), rec)
                    restored += 1
```

(Restored members reuse anonymous slots, so the compartment distribution — and `Σ macro_float` — is untouched. Disease state is whatever that slot was sampled as: the §4 decision.)

- [ ] **Step 5: Run existing tests** — `python tests/test_orchestrator.py` green (the `roster` is empty without `citizens`, so demote/promote behave as before). Commit: `feat(npc): uprezzing — checkpoint roster on demote, restore on re-promote`.

---

## Task 3: Event-driven promotion hooks

**Files:** modify `asphodel/orchestrator.py`

- [ ] **Step 1: Public `interact_with`** — `World.interact_with(citizen_id)` calls `self.roster.promote(cid, profile, self.sim.tick)` (look the profile up from `self.citizens`). This is what the front-end calls when the player profiles/talks to an NPC (the Census/Nemesis "you engaged it" trigger).

- [ ] **Step 2: Focus-proximity promotion** — each `step()`, for citizen agents in a **focused** zone (`self.focus`), promote the longest-present few into the roster (deterministic: by `citizen_id` order, bounded per tick) so simply standing among people eventually names some — capped by `max_roster`, so the bound still holds.

- [ ] **Step 3: Signature-in-view promotion** — when a focused-zone agent enters an eligible signature moment (from SP2's subordination check), `roster.promote` it (the Nemesis "did something memorable" trigger).

- [ ] **Step 4:** Commit: `feat(npc): event-driven roster promotion (interaction / focus / signature)`.

---

## Task 4: The gating invariants

**Files:** create the persistence/conservation tests in `tests/test_npc_roster.py`

- [ ] **Step 1: Persistence across demote→re-promote (load-bearing)** — promote a zone with citizens, `interact_with` a specific `citizen_id` (so it's rostered), step until the zone **demotes**, step while demoted, then force **re-promote** (via `set_focus`). Assert that `citizen_id` appears again among the zone's agents with its **identity and rostered need/action preserved**. (Disease state is *not* asserted — per §4.)

- [ ] **Step 2: Bound holds in a full run** — over a long run with churn, `len(world.roster) <= max_roster` at every tick, regardless of city size.

- [ ] **Step 3: Conservation** — `Σ` of the macro compartment totals is identical across a promote→demote→re-promote cycle vs a no-roster baseline (restore touches labels, not counts). Reuse the Phase-5 conservation assertion style.

- [ ] **Step 4: Determinism** — two identical runs (same seed, same scripted `interact_with` calls at the same ticks) produce identical roster membership and identical restored-agent identities. Commit: `test(npc): roster persistence + bound + conservation + determinism`.

---

## Task 5: snapshot + docs

- [ ] **Step 1: snapshot** — add a top-level `"roster"` list (citizen_id, name, last_interaction_tick) so the front-end can show "people you know," and a `named` boolean per agent in promoted zones.
- [ ] **Step 2:** README note: the player accumulates a bounded roster of named citizens that persist across leaving/returning; the rest of the city is anonymous fill.
- [ ] **Step 3:** Append to `FINDINGS_PHASE11.md`: confirm persistence + conservation + bound; record the chosen `max_roster` and why. Commit: `docs: SP3 readout + roster in snapshot`.

---

## Done criteria (SP3)

- A `Roster` caps named citizens at `max_roster` regardless of city size; promotion is event-driven and interaction-keyed; eviction is deterministic LRU-by-interaction.
- `_demote_zone` checkpoints roster members and `_promote_zone` restores them — re-entering a place shows the same people with identity/needs/history intact.
- Population is **exactly conserved** across the churn (restore relabels slots, never counts); all runs deterministic.

## Open / future

- **Faithful disease continuity:** advance each roster member's individual disease state by the demoted zone's force-of-infection while off-site (the DF "historical figures keep ticking" model), instead of re-sampling on re-promote. Costs O(roster) per tick; deferred.
- Social graph / memory / dialogue among roster members (the deep Nemesis layer).
- Godot rendering of named vs anonymous agents from `snapshot()` (Phase 12).

# Phase 11 · Sub-project 1 — Identity↔Agent Bridge + Schedule Activity (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (TDD). Python only — no Godot here. Tests are **self-running** (`python tests/test_<x>.py`) since `pytest` may be absent; if `pytest` is installed, `python -m pytest -q` also works. **This session's container has no numpy/pyyaml installed**, so the implementer must `pip install numpy pyyaml` (or `pip install -r requirements.txt`) before running anything. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make a promoted zone's agents carry a **citizen identity** and a **schedule-derived activity label**, so the city reads as people living a routine — *without changing the epidemic curve by a single bit*.

**Spec:** [`docs/superpowers/specs/2026-06-26-npc-behavior-phase11-design.md`](../specs/2026-06-26-npc-behavior-phase11-design.md)
**Evidence:** [`NPC_PRECEDENT_RESEARCH.md`](../../NPC_PRECEDENT_RESEARCH.md)

---

## The one design decision this plan locks in

Spec §5 floated "bias the agent's movement *target* on the torus (home region vs work region)." **We deliberately do NOT do that in SP1.** Physically concentrating agents changes local density, and the Phase 4a calibration (`analytic_contact_prob`, `p = β·A/(living·πr²)`) assumes **uniform density**. Concentrating commuters would silently shift transmission and break the validated macro↔micro agreement.

**Calibration-safe realization:** the schedule drives a *logical* **activity label** per agent (`sleep/commute/work/errand/leisure/idle`) used for **occupancy reporting, rendering, and as the hook SP2/SP3 extend** — while **physical position stays well-mixed exactly as today**. Transmission math is untouched.

**The determinism rule that makes this provable:** the identity/activity layer must consume **zero draws** from `AgentZone.rng` (the stream that drives positions and transmission). Identity is assigned by **deterministic slot order**, never via `zone.rng`. Therefore an orchestrator run *with* citizens produces a **bit-identical epidemic curve** to one without — which Task 4 asserts directly. This is both the correctness guarantee and the Factorio determinism-contract requirement (§8 of the spec) made concrete.

Shelter/flee — which legitimately *do* move the curve — keep flowing through the existing belief-driven `set_shelter_fraction` / macro flux, unchanged in SP1.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `asphodel/micro.py` | modify | `AgentZone` carries `citizen_id` (int64, −1 = anonymous) + `activity` (int8) arrays, threaded through every array mutation. Knows nothing about schedules — just int arrays. |
| `asphodel/orchestrator.py` | modify | `World` accepts an optional `citizens` map (zone → list[CitizenProfile]); identity-aware promote; per-tick schedule→activity; occupancy in `snapshot()`. |
| `asphodel/npc.py` | create | Small pure helpers: activity-name↔code tables, `activity_for(profile, hour)` (wraps `citizen._current_block`), `hour_of_day(day)`. Keeps `micro.py` decoupled from `citizen.py`. |
| `tests/test_npc_identity.py` | create | Array-alignment + RNG-neutrality (bit-identical curve) + schedule/occupancy + determinism. |

**Scope guard — NOT in SP1:** the utility/affordance reactive layer (SP2), the persistent named roster / uprezzing / checkpoint-restore across demote (SP3). In SP1 a `citizen_id` rides the arrays *best-effort* — inter-zone flux may still drop a citizen agent (realistic: people move). Guaranteed persistence is SP3.

---

## Task 1: Identity + activity arrays on `AgentZone`

**Files:** modify `asphodel/micro.py`; create `asphodel/npc.py`, `tests/test_npc_identity.py`

- [ ] **Step 1: Write the failing test (alignment + RNG-neutrality)**

Create `tests/test_npc_identity.py`:

```python
"""SP1: identity/activity arrays stay aligned and never perturb the RNG stream."""
from __future__ import annotations

import numpy as np

from asphodel.config import PathogenGenome, MicroParams
from asphodel.micro import AgentZone, STATE_NAMES

GENOME = PathogenGenome()
PARAMS = MicroParams()
DT = 0.25


def _counts(n_each=50):
    return {name: n_each for name in STATE_NAMES}


def test_identity_arrays_exist_and_align():
    z = AgentZone.from_counts(_counts(), GENOME, PARAMS, DT, seed=0)
    assert z.citizen_id.shape == (z.n,)
    assert z.activity.shape == (z.n,)
    assert z.citizen_id.dtype == np.int64 and z.activity.dtype == np.int8
    # Default: all anonymous.
    assert (z.citizen_id == -1).all()


def test_arrays_stay_aligned_through_mutations():
    z = AgentZone.from_counts(_counts(), GENOME, PARAMS, DT, seed=1)
    z.set_citizen_ids([(0, 1000), (1, 1001), (2, 1002)])   # slot -> citizen_id
    z.add_agents({"S": 7, "Ia": 3})
    z.remove_agents({"R": 5})
    z.reconcile_to_counts({n: 40 for n in STATE_NAMES})
    n = z.n
    for arr in (z.state, z.pos[:, 0], z.citizen_id, z.activity, z.sheltered):
        assert arr.shape[0] == n


def test_identity_does_not_perturb_transmission_stream():
    # Two zones, same seed: one stays anonymous, one gets citizen ids assigned.
    # Positions/states must evolve IDENTICALLY -> identity consumes no rng draws.
    a = AgentZone.from_counts(_counts(), GENOME, PARAMS, DT, seed=42)
    b = AgentZone.from_counts(_counts(), GENOME, PARAMS, DT, seed=42)
    b.set_citizen_ids([(i, 2000 + i) for i in range(b.n)])
    for _ in range(20):
        a.step(); b.step()
    assert np.array_equal(a.state, b.state)
    assert np.allclose(a.pos, b.pos)
```

- [ ] **Step 2: Run to verify it fails** — `python tests/test_npc_identity.py` → `AttributeError: 'AgentZone' object has no attribute 'citizen_id'`.

- [ ] **Step 3: Add the arrays to `AgentZone.__init__` and `from_counts`**

In `micro.py`, after `self.state = ...` in **both** `__init__` and `from_counts`, add aligned arrays (no `rng` use):

```python
        # Identity (SP1): -1 = anonymous statistical fill; >=0 = a citizen_id.
        self.citizen_id = np.full(self.n, -1, dtype=np.int64)
        # Activity label (SP1): schedule-derived, set per-tick by the orchestrator.
        self.activity = np.zeros(self.n, dtype=np.int8)  # 0 = idle/neutral
```

(In `from_counts`, `self.n` is `n`; add the two lines just before `zone.tick = 0`, using `zone.` prefix.)

- [ ] **Step 4: Thread the arrays through every mutation**

`AgentZone` mutates its parallel arrays in `add_agents`, `remove_agents`, and (in `from_counts`) the `perm` shuffle. Each place that reorders/masks/concatenates `state`+`pos`+`sheltered` must do the **same** to `citizen_id`+`activity`.

- In `add_agents`, after the `self.sheltered = np.concatenate([...])` line, append arrivals as anonymous (no `rng`):
```python
        self.citizen_id = np.concatenate([self.citizen_id, np.full(k, -1, dtype=np.int64)])
        self.activity = np.concatenate([self.activity, np.zeros(k, dtype=np.int8)])
```
- In `remove_agents`, after `self.sheltered = self.sheltered[keep]`:
```python
        self.citizen_id = self.citizen_id[keep]
        self.activity = self.activity[keep]
```
- In `from_counts`, the `perm` shuffle reorders `state` only (positions are i.i.d. uniform so order is irrelevant, and the identity arrays don't exist yet at that point — they're created in Step 3 *after* the shuffle, already aligned). **Confirm** the Step-3 lines sit *after* the `perm` block.
- **Audit `_move` / `step`** (`micro.py:247+`, `:373+`): if any path reorders the agent arrays in place (e.g. a `well_mixed` reshuffle), apply the same permutation to `citizen_id`/`activity`. If `_move` only updates `pos` values in place (no reordering), nothing to do. **Note in the commit which case held.**

- [ ] **Step 5: Add `set_citizen_ids` (deterministic, rng-free)**

```python
    def set_citizen_ids(self, pairs) -> None:
        """Assign citizen ids to slots: pairs = iterable of (slot_index, citizen_id).
        Deterministic and rng-free, so identity never perturbs the transmission
        stream (slots not listed stay anonymous, -1)."""
        for slot, cid in pairs:
            if 0 <= slot < self.n:
                self.citizen_id[slot] = int(cid)
```

- [ ] **Step 6: Create `asphodel/npc.py` (pure, no numpy-heavy logic)**

```python
"""SP1 NPC helpers: schedule -> activity label, kept separate so micro.py stays
identity-agnostic (it only ever sees int arrays) and citizen.py stays unaware of
agents."""
from __future__ import annotations

from .citizen import ScheduleEntry, _current_block

# Activity label <-> int8 code. 0 is the neutral default for anonymous agents.
ACTIVITIES = ("idle", "sleep", "commute", "work", "errand", "leisure")
_CODE = {name: i for i, name in enumerate(ACTIVITIES)}


def activity_code(name: str) -> int:
    return _CODE.get(name, 0)


def hour_of_day(day: float) -> float:
    """In-game hour in [0,24) from the sim's day axis (tick*dt). Independent of
    TimeScale's player-facing collapse warp -- occupancy is a sim-clock concept."""
    return (day * 24.0) % 24.0


def activity_for(schedule: list[ScheduleEntry], hour: float) -> int:
    """int8 activity code for a citizen's schedule at the given in-game hour."""
    block = _current_block(schedule, hour)
    return _CODE.get(block.activity, 0) if block is not None else 0
```

(If `_current_block` is not importable, expose a thin public wrapper in `citizen.py` and import that instead — do not duplicate the logic.)

- [ ] **Step 7: Run to verify the three tests pass** — `python tests/test_npc_identity.py` → all green. The `test_identity_does_not_perturb_transmission_stream` passing is the load-bearing result.

- [ ] **Step 8: Commit** — `feat(npc): identity + activity arrays on AgentZone (rng-neutral)`

---

## Task 2: Identity-aware promotion in the orchestrator

**Files:** modify `asphodel/orchestrator.py`

- [ ] **Step 1: Add an optional `citizens` map to `World.__init__`**

Add a parameter (keep it last, defaulted, so all existing call sites are unchanged):

```python
                 citizens: "dict[int, list] | None" = None,
```
and store it: `self.citizens = citizens or {}`  (zone index → list of `CitizenProfile` whose home resolves to that zone). When empty, SP1 is a pure no-op and every existing test passes byte-identically.

- [ ] **Step 2: Assign identities in `_promote_zone`**

At the end of `_promote_zone` (after `self.promoted[z] = promote(...)`), label as many agent slots as we have citizens, deterministically (no rng):

```python
        pop = self.citizens.get(z)
        if pop:
            zone = self.promoted[z]
            k = min(len(pop), zone.n)
            zone.set_citizen_ids((i, pop[i].citizen_id) for i in range(k))
            zone._npc_pop = pop   # slot i -> pop[i] for schedule lookup this episode
```

(Store `pop` on the zone so Task 3 can map slot→profile→schedule. Slots beyond `k`, and any flux arrivals, stay anonymous.)

- [ ] **Step 3: Per-tick schedule → activity, in `World.step`**

After the agent loop in `step()` (after the `for z, zone in self.promoted.items():` block, before the aggregate-totals section), add:

```python
        # Schedule -> activity label for citizen agents (rendering/occupancy only;
        # does NOT touch position or transmission -> curve unchanged).
        from .npc import activity_for, hour_of_day
        hour = hour_of_day(self.sim.tick * self.dt)
        for zone in self.promoted.values():
            pop = getattr(zone, "_npc_pop", None)
            if not pop:
                continue
            named = np.where(zone.citizen_id >= 0)[0]
            for slot in named:
                if slot < len(pop):
                    zone.activity[slot] = activity_for(pop[slot].schedule, hour)
```

(Vectorising the inner loop is a later optimization; correctness first. `named` is small — bounded by the citizen population per zone.)

- [ ] **Step 4: Run existing orchestrator tests unchanged** — `python tests/test_orchestrator.py` → all green (proves the `citizens=None` default path is untouched).

- [ ] **Step 5: Commit** — `feat(npc): identity-aware promotion + per-tick schedule activity`

---

## Task 3: Occupancy + agent identity in `snapshot()`

**Files:** modify `asphodel/orchestrator.py`

- [ ] **Step 1: Extend `snapshot()`**

In the per-promoted-zone agent block of `snapshot()` (where `positions`/`state` are emitted), add the identity + activity arrays and a per-zone occupancy histogram:

```python
            "citizen_id": zone.citizen_id.tolist(),
            "activity": zone.activity.tolist(),
```
and per promoted zone, an occupancy count by activity name:
```python
            "occupancy": _occupancy(zone),
```
with a module helper:
```python
def _occupancy(zone) -> dict:
    from .npc import ACTIVITIES
    import numpy as _np
    bc = _np.bincount(zone.activity, minlength=len(ACTIVITIES))
    return {ACTIVITIES[i]: int(bc[i]) for i in range(len(ACTIVITIES))}
```

- [ ] **Step 2: Commit** — `feat(npc): expose citizen_id/activity/occupancy in snapshot`

---

## Task 4: The two gating invariant tests

**Files:** add to `tests/test_npc_identity.py`

- [ ] **Step 1: Epidemiology-unchanged invariant (the load-bearing test)**

Two `World`s, same seed and config, one with a citizen population, one without; their per-tick aggregate compartment totals must be **bit-identical** over a full run. This proves the identity/activity layer is epidemiologically inert.

```python
def test_world_curve_identical_with_and_without_citizens():
    from asphodel.config import ScenarioConfig
    from asphodel.orchestrator import World
    from asphodel.citizen import default_cities, default_catalog, spawn_population

    cfg = ScenarioConfig()
    center = World(cfg, seed=3).sim.graph.center_zone()
    pop = spawn_population(default_cities()["generic"], default_catalog(), n=30, seed=3)

    plain = World(cfg, seed=3); plain.set_focus([center])
    withc = World(cfg, seed=3, citizens={center: pop}); withc.set_focus([center])

    for _ in range(120):
        a = plain.step(); b = withc.step()
        for f in ("S", "E", "Ia", "Is", "R", "D"):
            assert getattr(a, f) == getattr(b, f), f"{f} diverged at day {a.day}"
```

If this fails, the identity layer is consuming `rng` somewhere (Task 1 Step 4 audit missed a reorder, or an assignment used `zone.rng`). Fix the leak — do **not** loosen the assertion to a tolerance.

- [ ] **Step 2: Believability — occupancy tracks the clock**

```python
def test_activity_tracks_schedule_hour():
    from asphodel.config import ScenarioConfig
    from asphodel.orchestrator import World
    from asphodel.citizen import default_cities, default_catalog, spawn_population
    from asphodel.npc import ACTIVITIES

    cfg = ScenarioConfig()
    w = World(cfg, seed=5)
    center = w.sim.graph.center_zone()
    pop = spawn_population(default_cities()["generic"], default_catalog(), n=40, seed=5)
    w = World(cfg, seed=5, citizens={center: pop}); w.set_focus([center])

    seen = set()
    for _ in range(int(round(2.0 / cfg.dt))):   # ~2 in-game days
        w.step()
        occ = w.snapshot()["zones"][center].get("occupancy", {})
        seen.update(k for k, v in occ.items() if v > 0)
    # Over two days a normal population sleeps AND works (not just idle).
    assert "sleep" in seen and "work" in seen
```

- [ ] **Step 3: Determinism** — two `citizens=` runs from the same seed produce identical `snapshot()["zones"][center]["occupancy"]` sequences (assert equality of the collected lists).

- [ ] **Step 4: Run the whole file** — `python tests/test_npc_identity.py` → all green.

- [ ] **Step 5: Commit** — `test(npc): epidemiology-inert + believability + determinism invariants`

---

## Task 5: Docs

- [ ] **Step 1:** Add a short "Phase 11 (SP1)" note to `README.md` (after the citizen sections): agents now carry a citizen identity + schedule-derived activity; occupancy emerges; the epidemic curve is provably unchanged (identity is rng-neutral).
- [ ] **Step 2:** Create `FINDINGS_PHASE11.md` with the SP1 readout: confirm the with/without-citizens curve is bit-identical, and paste a sample two-day occupancy trace (sleep/commute/work shares by hour).
- [ ] **Step 3: Commit** — `docs: SP1 readout (FINDINGS_PHASE11) + README note`

---

## Done criteria (SP1)

- `AgentZone` carries `citizen_id` + `activity`, aligned through all mutations, assigned rng-free.
- A `World(citizens=…)` run is **bit-identical** in epidemic totals to one without — the epidemiology-inert invariant passes.
- Promoted-zone agents show schedule-correct occupancy (sleep at night, work by day); `snapshot()` exposes `citizen_id` / `activity` / `occupancy`.
- All existing tests still green; new invariants (inert / believability / determinism) green.

**Next:** SP2 — advertised-affordance reactive layer (environments/roles advertise utilities; seeded top-k pick; `safety` need driven by live belief; subordinate to signature moments). SP3 — bounded named roster + uprezzing (checkpoint/restore across demote, the part that needs `_demote_zone` to stop dropping identity).

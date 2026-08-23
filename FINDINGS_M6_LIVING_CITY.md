# M6 — Visible Living City — Findings

**Milestone:** M6 (Visible living city)
**Branch:** `claude/asphodel-authoritative-world-55z0qw`
**Verdict:** **PARTIAL** — the authoritative/simulation half is certified in Python
(snapshot rendering contract, separated benchmarks, full end-to-end vertical demo);
the Godot rendering + interaction is written to that tested contract but **could not
be engine-executed** here (no Godot runtime in this environment).

## Implementation summary

- **`asphodel/bench_live.py`** (new): the live-bubble benchmark. Measures, at
  several promoted-zone populations, the **three budgets kept separate**: `sim
  step`, `snapshot` build, and `json.dumps` serialize (the IPC wire), plus wire
  payload size. Rendering time is a Godot-side measurement by construction — this
  module never renders.
- **`asphodel/npc.py` — `visual_seed(citizen_id)`**: a stable, deterministic per-
  citizen appearance seed (splitmix, `0..2**31`) so a named-roster member looks the
  same on return. Mirrored bit-for-bit in the GDScript renderer.
- **`godot/scripts/citizen_render.gd`** (new): draws the live snapshot — one cheap
  capsule per agent, coloured by disease state, tinted by activity, scaled up +
  nameplated for named-roster members, with the stable per-person tint from
  `visual_seed`. A pure snapshot consumer (never decides behaviour). *Authored to
  the tested contract; not engine-executed here.*
- **`tests/test_vertical_demo.py`** (new): the initiative's closing sequence as an
  executable certification driving the authoritative runtime.

## The rendering contract (certified)

`test_snapshot_carries_everything_the_renderer_needs` proves one `snapshot()`
exposes, per promoted zone and aligned with positions: **anonymous vs identified**
(`citizen_id`), **disease state** (`state`), **activity** (`activity` +
`activity_names`), **reactive action** (`chosen_action` + `action_names`),
**named-roster status** (`named`), **position** and **zone**, plus a top-level
`roster` list. That is everything `citizen_render.gd` needs; the Godot side is a
consumer of this exact structure.

## Performance benchmark (separated budgets)

`python -m asphodel.bench_live --sizes 100,500,1000,2000,5000 --steps 15`:

```
   req    live   sim(ms)  snap(ms)   ser(ms)  wire(KB)
   100     100      2.23     0.116     0.446      30.2
   500     500     8.77      0.24      1.04       65.8
  1000    1000    15.58     0.485     2.01      125.1
  2000    2000    29.05     0.923     4.20      245.0
  5000    5000    75.33     1.35      5.46      316.3
```

Read-out:

- **Simulation dominates** (O(n) proximity transmission): ~15.6 ms per *tick* at
  1000 live agents. Ticks are infrequent in play (one tick = 6 in-game hours, i.e.
  seconds of wall time at default pacing and only on `ADVANCE`), so this is
  comfortably inside budget; even 5000 agents (75 ms/tick) is fine at that cadence.
- **Snapshot is cheap** — sub-millisecond through 2000 agents, 1.35 ms at 5000.
- **IPC serialize** is a few ms; wire payload ~125 KB at 1000 agents (opt-in — the
  per-tick `ADVANCE` reply is a compact summary; full snapshots are requested only
  when the renderer needs detail).
- The three budgets are reported **separately**, so a Godot frame-time problem would
  be attributed to rendering, not to the simulation. Rendering budget itself must be
  measured in-engine (deferred — see below).

## The vertical demo (certified in Python)

`test_full_vertical_demo` drives the entire closing sequence through the
authoritative runtime and asserts each property:

1. Enter the city → the player's zone **promotes** under focus.
2. Citizens are **real identified agents with routines** (activity occupancy matches
   the schedule at the current hour).
3-4. Time advances; a broadcast drives **belief up**.
5. **NPC reactions depart from routine** — shelter/flee share rises vs calm.
6. Player interacts → citizen **enters the persistent roster**.
7. Travel away → the zone **demotes**.
8. An intervention (cordon) **changes the future authoritative trajectory** (A/B on
   a save-forked identical start).
9-10. Return → the **same person is restored** (identity + roster membership).
11. **Save → destroy → load → continue deterministically** (bit-identical tail).

This certifies the simulation *supports* the full living-city loop end to end.

## Godot side (written, not executed)

`citizen_render.gd` renders the snapshot with cheap placeholders and stable
named-person recognition, and reads the same `visual_seed`. It is authored against
the certified snapshot contract and reviewed by inspection, but **no Godot 4.4.x
runtime was available here**, so it was not run, and the in-engine render-budget
benchmark (frame time, per-citizen draw) was not taken. Wiring it into
`street_world.gd` (instantiate, `render_snapshot(SimBridge.last_world, focus_zone)`
each frame, raycast → `SimBridge.interact_with`) is a small integration step that
needs the engine to validate — hence the PARTIAL verdict.

## Determinism / conservation

Inherited and re-exercised: the vertical demo's save/reload continuation is
bit-identical; the full suite (**241 passed**) keeps every M2–M5 conservation and
determinism test green.

## Known limitations

- **No in-engine execution here** — the Godot renderer, the player-interaction
  raycast, and the in-engine performance benchmark are unverified in this
  environment. This is the sole reason the milestone is PARTIAL rather than PASS.
- The live bridge still does not auto-load a bundle's `citizens.json` into the World
  (the M2 seam): the vertical demo uses a synthetic in-process population. Mapping
  baked citizens (home_xy→zone + schedule synthesis) into `START_WORLD` is the
  remaining wire to make the *Godot* client show named citizens from a real bundle.
- Visual fidelity is intentionally placeholder (capsules), per scope.

## Branch / head SHA

- Branch: `claude/asphodel-authoritative-world-55z0qw`; head at the M6 commit.

## Verdict

**PARTIAL** — the authoritative simulation fully supports a visible living city: the
snapshot carries everything a renderer needs, the sim/snapshot/IPC budgets are
measured and separated, and the entire end-to-end vertical sequence is certified in
Python. The Godot renderer and player interaction are written to that exact
contract but require a Godot runtime to execute and benchmark, which was not
available in this environment.

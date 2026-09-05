# Real-road zone mobility — findings & decisions

This milestone closes the P2 causal disconnect from the gameplay-integrity
repair: the epidemic's inter-zone movement now rides a **road-derived weighted
zone-mobility graph** instead of a generic 4-neighbour grid. The player,
citizens, city geometry, clock, outbreak **and now the physical mobility** all
describe the same city.

## Previous behaviour

`ZoneGraph` built its adjacency from a topology (`grid` / `small_world` /
`commute`) and exposed `weights` → `mix` (row-normalised). `model.py` used `mix`
for infection mixing and `belief_mix` (population-weighted `mix`) for social
belief; `_apply_fleeing` used `weights > 0` for destinations. The OSM pipeline
ran the sim on the **grid** and emitted roads only for rendering, so two grid
neighbours were equally adjacent to the epidemic whether or not a road (or a
river) lay between them.

## Architecture

Generic seam, no OSM in the engine:

```
OSM roads (StreetMap/polylines)
        ↓   asphodel/osm_city/mobility.py   (derivation, build time only)
generic sparse edge list  [[a, b, weight], ...]
        ↓   GraphParams.mobility_edges
ZoneGraph._explicit_weights  →  weights → mix / belief_mix / fleeing
        ↓
Simulation / World (infection movement + population flux)
```

`asphodel/graph.py` and `asphodel/model.py` know nothing about roads — they
consume a non-negative sparse weighted graph. All OSM logic lives in
`asphodel/osm_city/mobility.py`.

## Mobility contract

* **Representation:** `GraphParams.mobility_edges: Optional[list]` — a sparse,
  undirected `[[a, b, weight], ...]` over zone indices. `None` ⇒ fall back to the
  grid/small-world/commute topology (full backward compatibility).
* **Weights:** non-negative floats; negative rejected with `ValueError`.
  Built symmetric (`W[a,b] = W[b,a] = max` per pair); the derivation already
  sums parallel roads into one weight per pair. No self-edges.
* **Normalisation:** raw capacity weights; `ZoneGraph` row-normalises into `mix`
  as before, so only relative magnitudes matter. `GraphParams.mobility` (0.15)
  still scales the overall inter-zone fraction.
* **Disconnected / empty safe:** isolated zones get all-zero mix rows (already
  NaN-guarded); empty (zero-population) cells stay inert via the existing
  population-weighted `belief_mix` + belief-floor pinning, so a highway across
  empty land never manufactures belief.
* **Fallback:** an empty derived edge set ⇒ `None` ⇒ grid topology.

### Road → zone derivation

Walking each road polyline in the bundle's metre frame, every time it crosses
from zone A into zone B contributes that road class's capacity to the A–B edge;
segments are finely subsampled so a road spanning several cells produces an edge
for **each** real transition (never a phantom endpoint-to-endpoint edge).
Parallel/again-crossing roads **sum**.

Generic class capacities (not overfit): motorway 8 · trunk 6 · primary 4 ·
secondary 2.5 · tertiary 1.5 · residential 1.

A small **local-diffusion floor** (`0.1`) links grid-adjacent *populated* cells
so the epidemic doesn't fragment where only minor (un-fetched) streets connect
two neighbourhoods. It is tiny next to a real road (2.5–8), so roads still
dominate relative mobility; it is gated on population so empty cells are never
turned into conduits. Explicit and separately tested.

## Which systems use which graph

| System | Graph | Road-aware? |
|---|---|---|
| Infection mixing (`mix @ source_frac`) | `weights` → `mix` | **yes** |
| Population fleeing (destinations) | `weights > 0` + belief-safety | **yes** |
| Social belief contagion (`belief_mix @ belief`) | population-weighted `weights` | **yes** (belief is defined as *mobility*-weighted neighbour belief, so it rides the same physical graph; its population weighting and empty-cell floor are preserved) |
| Authority / infrastructure | global / per-zone (no graph) | n/a |

Belief intentionally shares the physical-mobility graph because the model
defines social contagion as mobility-weighted; its separate population-weighting
semantics are untouched.

## Real-city results

Derived from the committed bundles' own roads (offline, no re-fetch):

| City | zones | road edges | edges (+floor) | components | isolated | max edge wt | grid-adj pairs road-connected |
|---|---|---|---|---|---|---|---|
| Houston | 224 | 188 | 433 | 1 | 0 | 37.1 | 41% |
| Madisonville TX | 100 | 44 | 141 | 16 | 15 | 22.1 | 22% |
| San Antonio | 289 | — | 320 | 24 | 23 | 41.1 | — |
| Austin | 224 | — | 419 | 2 | 1 | 39.6 | — |

Road-class mix (crossings by class) confirms the graphs are the *cities'* own,
not a generic template:

* **Houston** — a dense metropolis: mostly **secondary** streets (337 crossings)
  laced with **motorway** freeways (66); one fully-connected component.
* **Madisonville** — a small highway town: crossings led by a through
  **motorway** (24) and **primary/trunk** routes, few secondary streets; the
  graph fragments into 16 components (rural pockets with no major road between
  them). This is real geography, not noise — a hamlet on a highway, not a grid.

## Correctness

* **Propagation is materially road-dependent** (`test_road_connection_changes_who_gets_infected`):
  on `A === B` (road) zone B is infected; on `A | B` (no edge) B stays fully
  susceptible while the seed zone A burns in both.
* **Population conserved exactly** with road mobility, macro-only and macro+micro
  (`test_macro_conservation_with_mobility`, `test_macro_micro_conservation_with_mobility`)
  — the fleeing flux stays zero-sum; promotion/demotion invariants hold.
* **Determinism:** same roads+zones ⇒ byte-identical edge list and timeline
  (`test_derivation_deterministic_on_real_bundle`, verified on re-bake).
* **Backward compatibility:** with no `mobility_edges`, `ZoneGraph` produces the
  exact prior grid weights (`test_grid_fallback_unchanged_without_edges`); the
  full pre-existing suite is unchanged.

## Performance

Per-tick cost is unchanged — the engine still does one `Z×Z` `mix` matmul; only
the weights differ. Derivation is a one-time build cost.

| Measurement (Houston, 224 zones) | value |
|---|---|
| mobility derivation (1088 roads) | ~9 ms (build time only) |
| macro sim, 60 in-game days | 108 ms (grid) → 99 ms (road) |
| orchestrator (macro+micro), 60 days | 6.6 s (grid) → 5.9 s (road) |

No regression (differences are within run-to-run noise).

## Bundle contract

`mobility.json` = `{"version": 1, "local_floor": 0.1, "edges": [[a,b,w], ...]}`
is persisted next to the four core files and summarised in `meta.mobility`, so
the real-city simulation is reproducible without re-querying OSM. Godot renders
the baked timeline (which already reflects the mobility) and does not infer its
own graph, so there is nothing to contradict. Older bundles without
`mobility.json` cleanly fall back to grid mobility. `rebake_mobility(dir)`
re-derives + re-runs a committed bundle offline.

## Known limitations

* **Capacity coefficients are generic**, not calibrated to real traffic volumes;
  the requirement was directional realism (roads change relative mobility), met.
* **Only major roads** (motorway/trunk/primary/secondary) are fetched, so the
  local floor stands in for minor-street diffusion; a fuller fetch would reduce
  reliance on the floor.
* **Sparse rural cities fragment** (Madisonville: 16 components). That is
  faithful to the geography, but means a seeded outbreak stays within its
  road-connected component. If cross-component seeding is desired later, seed
  per component or raise the floor.
* Mobility is **undirected and static** — no directional commute asymmetry or
  dynamic closures (explicitly out of scope this milestone).

## Next milestone

Live Python `World` → Godot runtime bridge + player causal interventions: Godot
becomes a client of `World.snapshot()` (already JSON-safe) rather than replaying
a baked timeline, so player actions (cordon, broadcast, shelter) feed back into
the authoritative simulation.

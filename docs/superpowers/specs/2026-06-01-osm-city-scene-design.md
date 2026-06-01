# Design — "Select a City" → OSM → Playable Scene

**Date:** 2026-06-01
**Status:** Approved (design); pending implementation plan
**Branch:** `claude/asphodel-belief-cascade-kvKKv`

## 1. Summary

A mechanic where the player names a real city; the game fetches OpenStreetMap
(OSM) data for it, tessellates it into a grid of simulation **zones** weighted by
real building density, runs the existing Asphodel belief-cascade simulation on
that geography, and renders a stylized low-poly 3D "block city" in Godot whose
zones tint toward panic as a **precomputed timeline** plays back.

The OSM city is **both** the visual world *and* the simulation structure: real
geography drives the zone graph the belief-cascade runs on.

## 2. Goals / Non-goals

**Goals**
- Type a city name in Godot → see a geo-anchored low-poly city built from OSM.
- Real building density → per-zone population feeding the existing sim.
- Major road network rendered as the visual/mobility skeleton.
- Deterministic, reproducible precomputed panic timeline with play/pause/scrub.
- Reuse the trusted Python sim almost verbatim; keep Godot a renderer/UI.

**Non-goals (explicit, deferred)**
- Individual real buildings (we use representative blocks scaled by density).
- Live/streaming sim or mid-run player intervention (timeline is precomputed).
- Real-neighborhood (admin-boundary) zones — we use a regular square grid.
- Hex topology (square grid reuses the existing `ZoneGraph` 4-neighbour model).
- Per-zone infection as a second visual layer (belief-tint only in v1).
- Inter-zone agent flux / micro (Phase 4a) integration.

## 3. Architecture

The **bundle** — a folder Python writes and Godot reads — is the single shared
contract that lets the three subsystems be built and tested independently.

```
┌─ GODOT ──────────────┐    invoke (subprocess)     ┌─ PYTHON (asphodel) ───────────────┐
│ City-select screen   │ ── python -m asphodel.osm ──▶│ 1. geocode name → bbox (Nominatim)│
│  (type a city name)  │     "Chicago" --out city/   │ 2. Overpass: major roads+buildings│
│        │             │                             │ 3. tessellate bbox → square grid  │
│        ▼             │                             │ 4. per-cell footprint → population │
│ load bundle ◀────────┼──────── writes bundle/ ─────│ 5. run belief-cascade (existing)   │
│  • Kenney blocks/zone│                             │ 6. bake timeline + geometry descr. │
│    (count/height∝pop)│                             └────────────────────────────────────┘
│  • road ribbons      │
│  • timeline playback │
│    play/pause/scrub  │
│    → tint by belief  │
└──────────────────────┘
```

**Bridge mechanism:** subprocess. Godot runs the Python pipeline as a child
process via `OS.create_process`, waits/polls, then reads the bundle directory.
No server, no ports, no live protocol (the precomputed-timeline model needs
none). Requires a Python interpreter available on the player's machine; the
Python path is configurable in Godot, defaulting to `python` on PATH.

## 4. Components & files

### Python — new package `asphodel/osm_city/`
- `geocode.py` — city name → bounding box via Nominatim
  (`https://nominatim.openstreetmap.org/search`), stdlib `urllib`. Sends a
  descriptive `User-Agent`; rate-limited to ≤1 req/s per Nominatim policy.
- `overpass.py` — bbox → major roads + building footprints via the Overpass API
  (`https://overpass-api.de/api/interpreter`). **Caches raw responses keyed by
  bbox** under a cache dir, enabling offline replay and network-free tests.
  Retry with backoff on timeout/429.
- `tessellate.py` — bbox → square grid. `rows`/`cols` derived from the bbox
  aspect ratio so cells stay approximately square. Aggregates building footprint
  area per cell → density → per-zone population (normalized to a configurable
  total population).
- `geometry.py` — equirectangular lat/lon → local-meter projection (no
  `pyproj`); per-zone representative block placements (count & height ∝ density,
  seeded jitter within the cell); road node lat/lon → projected XY polylines.
- `bundle.py` — assemble and write `meta.json`, `zones.json`, `roads.json`,
  `timeline.json`.
- `__main__.py` — orchestrator CLI:
  `python -m asphodel.osm_city "<city>" --out <dir> [--grid N] [--total-pop P]
  [--seed S] [--cache <dir>]`.

### Python — sim hook (existing modules, backward-compatible)
- `config.py`: add an optional per-zone `population` vector (a `list[float] |
  None`) to `GraphParams` (default `None` → current uniform behaviour).
- `graph.py`: add a constructor path that accepts explicit per-zone populations
  and (optionally) an explicit weight matrix, while the default grid path is
  unchanged.
- `model.py`: at the population-init site (`model.py:82`), use the per-zone
  vector when present, else `np.full(Z, population_per_zone)`. ~10 lines, all
  existing scenarios behave identically.

### Godot — new, under `godot/`
- `scripts/bundle_loader.gd` — parse a bundle folder into typed dictionaries.
- `scenes/CitySelect.tscn` + `city_select.gd` — text input + "Load" button;
  invokes the bridge; shows loading/errors.
- `scripts/python_bridge.gd` — `OS.create_process` the pipeline, poll for
  completion, surface errors; configurable interpreter path.
- `scenes/CityScene.tscn` + `city_builder.gd` — instance representative blocks
  (`MultiMeshInstance3D`, per-instance color for cheap tinting), build road
  meshes, frame the camera to the bbox.
- `scripts/timeline_player.gd` — hold the belief timeline; play/pause/scrub
  (slider) UI; each tick set per-zone instance color lerping normal→panic.

## 5. Bundle schema (the contract)

```jsonc
// meta.json
{ "name": "...", "query": "...", "bbox": [s, w, n, e],
  "center": [lat, lon], "projection": "equirectangular",
  "grid": { "rows": R, "cols": C, "cell_m": M },
  "dt": 0.25, "n_days": 120.0, "n_ticks": 480,
  "genome": { ... }, "seed": 0, "seed_zone": 137, "version": "1" }

// zones.json
[ { "id": 0, "row": 0, "col": 0, "center_xy": [x, z], "extent": [w, h],
    "population": 4231.0, "density": 0.73,
    "blocks": [ { "xy": [x, z], "height": 12.0, "footprint": 6.0 } ] } ]

// roads.json
{ "polylines": [ { "class": "primary", "points": [[x, z], ...] } ] }

// timeline.json
{ "field": "belief", "shape": [n_ticks_plus_1, Z], "data": [[...], ...] }
```

`timeline.data` comes directly from `RunResult.belief_history` (`(n_ticks+1,
Z)`). Zone array index == `timeline` column index == `zones[i].id`.

## 6. Key technical decisions

- **Projection.** Local equirectangular tangent plane centered at the bbox
  center: `x = (lon − lon0)·cos(lat0)·111320`, `z = (lat − lat0)·110540`
  (meters). Sub-meter accurate over city scale; no geo dependency.
- **Density → population.** Per cell, sum building footprint polygon areas
  (shoelace) × `building:levels` (default 1 when untagged), then normalize the
  per-cell shares to a configurable **total population** (`--total-pop`, default
  **500,000**). Sparse cells get low/zero population.
- **Grid resolution.** Configurable; **default 16×16**. The sim is vectorized
  and stays fast at this size. Cells derived to stay ~square from bbox aspect.
- **Outbreak seeding.** Default `seed_zone` = the densest populated cell (so the
  outbreak starts where people are). Overridable via CLI.
- **Determinism.** Cached OSM input + seeded block jitter + the deterministic
  sim ⇒ byte-identical bundle from identical `(query, grid, total-pop, seed)`.
- **Dependencies.** No new Python deps — stdlib `urllib` + `json` + existing
  `numpy`. Godot uses only built-in `OS`, `HTTPRequest` not required (subprocess
  bridge), `FileAccess`, `MultiMeshInstance3D`.

## 7. Error handling

| Condition | Behaviour |
|---|---|
| City not found (Nominatim empty) | Clear message + nonzero exit; Godot shows it. |
| Network down | Use cached OSM if present (offline); else error out. |
| Oversized bbox (e.g. "Texas") | Cap bbox area to a max; warn; clamp to centered region. |
| Overpass timeout / 429 | Retry with exponential backoff, then error. |
| Empty / no-building area | Zones with 0 population; warn; ensure the seed zone has population (fall back to grid center if densest cell is empty). |
| Malformed/partial bundle in Godot | Loader validates `meta.version` + required keys; refuses with a message. |

## 8. Build phases (one design, three milestones)

| Phase | Deliverable | Verifiable by |
|---|---|---|
| **1 — Pipeline** | `asphodel/osm_city/` + per-zone-population sim hook → writes a bundle. | Run on a city; inspect bundle JSON; sim runs on real densities; tests pass against fixture. |
| **2 — Scene gen** | Godot loads a bundle → block city + road ribbons + camera. | Open `CityScene` against a checked-in sample bundle; see the city; headless node-count test. |
| **3 — UX + playback** | City-select screen → invokes Python → loading → timeline play/pause/scrub tinting blocks by belief. | Type a city; watch the cascade play. |

Each phase is independently runnable. Phase 2 uses a checked-in sample bundle so
Godot is testable without Python or network.

## 9. Testing strategy

- **Phase 1 (Python):** `tests/test_osm_city.py` against a small **checked-in
  OSM fixture** (cached Nominatim + Overpass responses; no network in CI):
  - bundle schema & required keys
  - grid dims derived correctly from bbox aspect
  - per-zone population sums to the configured total (within rounding)
  - shoelace area correctness on known polygons
  - projection round-trip / known-distance sanity
  - determinism: identical inputs → identical bundle bytes
- **Phase 2 (Godot):** load a checked-in **sample bundle** headless
  (`godot --headless --script ...`) and assert zone/block/road node counts and
  that the camera frames the bbox.
- **Phase 3:** unit-test bridge command construction; manual smoke test (type a
  city → cascade plays). Optional GUT harness if we add Godot unit testing.

## 10. Open items / future stretches (not in scope)

- Per-zone infection as a second visual layer.
- Real-neighborhood (admin-boundary) zones with a grid fallback.
- Hex topology.
- Live streaming sim / mid-run intervention (would swap the subprocess bridge
  for the local-HTTP option).
- Placing real building meshes / road-aligned block placement.
- Weighting `ZoneGraph` mobility edges by the real road network between cells.

# Gameplay-integrity repair — findings & decisions

This milestone eliminated the contradictions where the first-person game, the
citizen, the city, the clock and the outbreak described different realities. The
guiding principle was **one authoritative world**: the same resolved city drives
the citizen, their coordinates, the geometry, the clock and the outbreak.

## What was confirmed and fixed

| Finding | Status | Fix |
|---|---|---|
| P0 first-person had no outbreak | fixed | `GameClock` autoload advances the baked belief timeline; StreetScene reddens sky/fog + HUD as belief rises |
| P0 spawn ignored the citizen | fixed | citizens carry `spawn_xy` (home/work/route by context); StreetScene spawns there with collision-safe placement |
| P0 citizens not from the real city | fixed | citizens spawned into the canonical `StreetMap` of the actual city (real buildings/roads/density), not shared abstract profiles |
| P1 signature contradicted context | fixed | signature resolved via `resolve_collapse_situation` at the citizen's spawn hour (a sleeping trucker is off-shift, not on the motorway) |
| P1 inventory not location-aware | fixed | possessions scoped `on_person`/`home`/`workplace`/`vehicle`; "On hand" is on-person only |
| P1 clock disconnected | fixed | single `GameClock` (day/hour/sim-tick/pause) drives spawn hour, outbreak, day/night |
| P1 constant time warp vs eased claim | fixed | `player_day_to_sim_day` is now an eased quadratic relaxing to real-time at the tip; `warp_at` exposes the instantaneous slope |
| P1 building footprint vs constant width | fixed | StreetScene uses each block's stored `footprint`; visual and collision boxes agree |
| P1 pause not authoritative | fixed | `GameClock.set_paused` sets `get_tree().paused`; player + clock are PAUSABLE, pause UI is WHEN_PAUSED |
| P1 snapshot not JSON-safe | fixed | `World.snapshot()` emits agent arrays via `.tolist()` |
| P1 `max_live_agents` soft cap | fixed | removed the first-candidate escape hatch; non-focus promotion is a hard cap, focus may exceed by design |
| P1/P2 empty cells relay belief | fixed | population-weighted belief mixing + empty cells pinned to the belief floor |
| P2 player could leave finite ground | fixed | fall-plane recovery respawns the player |
| P2 shallow bundle validation | fixed | `BundleLoader.validate` checks meta/zones/roads/timeline structure before scene change |

## Architecture decisions

* **One citizen model, two `StreetMap` builders.** `world_from_osm.py` builds the
  canonical `StreetMap` either from freshly parsed OSM (ingest time, real tag
  categories) or from a committed bundle's own blocks+roads (offline re-bake).
  Both feed the *same* `spawn_population_in_world` + flatten path, so there is no
  second, divergent citizen system.

* **Offline re-bake of committed bundles.** The committed bundles do not ship the
  raw OSM extract, so their citizens are re-baked from the bundle's rendered
  blocks. Building *category* (the only thing a bundle doesn't store) is drawn
  deterministically per block, biased by the block's real OSM-derived density.
  New bundles built through the pipeline get full-fidelity real categories.
  → Consequence: for the committed bundles the occupation *mix* difference
  between cities is driven by density geography rather than exact OSM land-use,
  so it is real but modest; scale, coordinates, commute distances and building
  counts differ strongly. Rebuilding a bundle from live OSM restores full
  category fidelity.

* **GameClock as the sole clock + pause + outbreak authority.** GDScript holds no
  simulation rules — it plays back the baked timeline. If the live Python→Godot
  bridge lands later, GameClock becomes a client of `World.snapshot()` without
  changing the scene contract.

## P2 — the road-topology causal disconnect (CLOSED in the follow-up milestone)

> **Update:** this disconnect is now closed. The epidemic rides a road-derived
> zone-mobility graph persisted in the bundle (`mobility.json`); see
> [`FINDINGS_ROAD_MOBILITY.md`](FINDINGS_ROAD_MOBILITY.md). The original
> writeup is kept below for context.

**Road topology is visually real but the epidemic runs on a square grid.** The
OSM pipeline runs the belief cascade on the tessellated grid (`ZoneGraph`, grid
mobility) and separately emits road polylines for rendering. Houston's real
highways/bridges/chokepoints therefore shape what you *see* and where citizens
*route* (the citizen `StreetMap` is road-routed), but they do **not** yet shape
inter-zone disease/belief *mobility* — that still diffuses on 4-neighbour grid
adjacency.

* The seam to close it exists: `StreetMap`/`RoadNetwork` already provides routed
  distances and per-segment structure; a future step can derive per-edge zone
  mobility weights from real-road connectivity and feed them into
  `GraphParams`/`ZoneGraph` (which already supports non-grid weight matrices).
* Guard against silent drift meanwhile: `tests/test_osm_city.py` asserts the
  timeline shape matches the zone grid, and citizen generation now consumes the
  same roads the renderer draws, so the rendered and simulated geographies come
  from one parse. Threading real-road weights into zone mobility is the
  recommended next milestone.

## Testing

* Python (`pytest`, executed): `tests/test_gameplay_integrity.py`,
  `tests/test_citizens_bake.py`, `tests/test_gametime.py`, plus the existing
  suite — all green.
* Godot (`godot/tests/`, **written, not executed** — no Godot binary in this
  environment): `run_tests.gd` (bundle validation + GameClock logic) and
  `test_street_scene.gd` (spawn/ground/pause/outbreak/out-of-bounds runtime
  smoke). See `godot/tests/README.md` to run them on a machine with Godot 4.4+.

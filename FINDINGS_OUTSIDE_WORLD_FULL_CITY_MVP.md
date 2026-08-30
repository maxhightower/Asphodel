# FINDINGS — Outside-World Full-City MVP

## Verdict

**OUTSIDE_WORLD_FULL_CITY_MVP: PASS**

Every gate in mission §27 that is measurable in this environment passes; the
full gate table with per-gate evidence is below. The entire existing playable
Houston extent (5.79 × 6.63 km, the committed bbox — untouched) is compiled
into a coherent procedural exterior world from commercially-clean public
data, with anchored spawns, streaming rendering, and deterministic rebuilds.

## Git state

| | |
|---|---|
| Source branch | `claude/asphodel-walk-in-interiors-v1-k9m2` |
| Source SHA | `12f698f5143279745c0c7cc62676512b3b972318` (certified Walk-In Interiors v1 tip, verified before branching) |
| Final branch | `claude/outside-world-full-city-mvp-tuh0de` |
| Status | clean (no uncommitted changes) |

Commits (small, per-package):

```
386e134 OW0+OW2: outside-world design contract, deterministic substrate, grammar tables
b960be9 OW1+OW2: Overture acquisition, provenance gate, normalizer, stable identity, compiler core
ba29591 OW3-OW8: full-city exterior compiler — all 12 certification gates pass for Houston
a50b97b OW9: chunked streaming exterior renderer + workplace categories + routed-commute clearing
fe277c7 OW10 (in progress): screenshot/perf harness extensions + first exterior evidence captures
c1951d2 OW10: remaining exterior evidence captures
(final)  OW10: performance + evidence sections, final regression (this commit)
```

## Data packet

All acquisition is reproducible via
`python -m asphodel.world_source acquire --city <city>` (S3 REST listing +
HTTP-Range GeoParquet reads with row-group bbox pruning; cache under
`data/raw/`, gitignored; checksums + provenance in
`geo/provenance/data_sources.json`). Release pinned: **Overture 2026-08-19.0**
(latest at build time; the pipeline supports latest-discovery or explicit
pinning).

Houston bbox (authoritative, read from the committed bundle meta —
`python -m asphodel.world_source bbox houston`):
W,S,E,N = `-95.4908972, 29.79371055, -95.4308972, 29.85371055`.

| type | rows (Houston) | bytes | license | sha256 (12) |
|---|---|---|---|---|
| building | 22,524 | 3,381,164 | ODbL | ec73ba722170 |
| building_part | 4 | 14,533 | ODbL | c917f6276cff |
| segment | 7,991 | 1,868,855 | ODbL | d13d34c1fceb |
| connector | 10,866 | 924,889 | ODbL | 1570de15de25 |
| land | 266 | 167,951 | ODbL | ee37dcf7b965 |
| land_cover | 114 | 2,791,627 | ODbL | 23d9f97ad037 |
| land_use | 431 | 195,153 | ODbL | 75869ec2c8db |
| water | 178 | 310,955 | ODbL | 03d9e510e857 |
| infrastructure | 3,934 | 474,018 | ODbL | ea90f7980eb0 |
| place | 5,358 | 1,245,533 | CDLA-Permissive-2.0 | 957f0759f0ba |

Total download 11.4 MB Houston + 2.9 MB Madisonville. All artifacts
`commercial_permitted=true`; the commercial gate
(`python -m asphodel.world_source gate`) fails closed on RESTRICTED/UNKNOWN
and passes with **0** unsafe entries. Attribution obligations ("© OpenStreetMap
contributors, Overture Maps Foundation" for ODbL themes; "Overture Maps
Foundation" for places) are carried in the manifest and in
`world_meta.json.attribution`. ODbL-derived geographic content lives only in
`world/` + `buildings.json`; no gameplay/narrative/loot data enters those
files (tested: the compiler writes only presentation files).

**Recorded acquisition failures (fail-closed, §35):** the build environment's
egress policy denies City of Houston COHGIS/ArcGIS, USGS 3DEP (tnmaccess),
and NLCD hosts. Each is recorded in the manifest as
`unreachable_egress_policy` with its documented fallback: parcels →
**derived parcel inference** (every parcel carries observation_class
DERIVED), terrain → **flat + semantic surfaces** (explicitly permitted for
this MVP by §6C), canopy → Overture base land_cover. No junk data was
substituted; nothing pretends to be surveyed truth.

## Architecture

- **Normalized world source** (`asphodel/world_source/normalize.py` →
  `schema.WorldSourceV1`): 11 layers, each feature carrying stable_key
  (Overture GERS), geometry in the exact committed bundle frame
  (equirectangular about the bbox centre, x=east/z=north metres),
  observation_class, license_family. Only fields Asphodel needs.
- **Source precedence** (§8): local GIS (unavailable this build) → Overture
  conflated → derived → procedural, per feature class. Where an observed
  building footprint conflicts with an inferred carriageway polygon
  (service/unknown-class stubs), the building wins (paint priority +
  certification rule); Overture building geometry is never degraded.
- **Stable identity** (`identity.py`): building stable_key = GERS id;
  `building_id` = index into the list sorted by quantized centroid
  (z, x, key). Same (city, release, compiler_version, seed) ⇒ same mapping
  (tested; full rebuild is byte-identical). Mapping persisted to
  `world/identity.json`. `buildings.json` is regenerated in this order
  (schema-compatible, plus additive `key`/`arch`/`cat` fields), and citizens
  are rebaked against it, so interiors/containers/occupancy —which hash on
  the integer building_id— stay aligned by construction. The audited legacy
  divergence (bundle-rebaked citizens living in decorative `zones[*].blocks`
  rather than real buildings) is retired for compiled cities.
- **Compiler** (OW-MVP-1…8): surfaces (2 m semantic raster per chunk, 10-type
  enum, no unclassified byte exists), street cross-sections (observed width
  when present, class tables otherwise; sidewalk/verge bands; markings;
  elevated decks), derived parcels (block polygonization → land-use overlay →
  Voronoi subdivision around footprints → frontage), building grammar
  (8 archetypes on observed footprints; 93% observed LiDAR heights;
  deterministic inference otherwise; street-facing entrances), parcel detail
  grammar (driveways, walkways, parking lots with stall layouts, dumpsters,
  yard props, fences, contextual vegetation, curb/lot/yard vehicles), spawn
  anchors (7 kinds, sanitized: none inside a footprint or off-map).
- **Determinism**: every placement draws from
  `hash64(seed, GENERATOR_VERSION, stable_key, purpose)` (splitmix64) — no
  global RNG, no iteration-order dependence; chunks are independently
  regenerable; gzip mtime=0 makes rebuilds byte-identical.
- **Streaming** (`godot/scripts/exterior_world.gd`): three tiers by chunk
  distance (T1 ≤1408 m ground+masses; T2 ≤800 m grammar+markings+collision;
  T3 ≤416 m MultiMesh props/vehicles/trees), hysteresis, ≤2 chunk-builds per
  update, LRU parse cache, no per-prop nodes. Chunk reload reproduces an
  identical debug hash; teardown leaks nothing (in-engine test).
- **Simulation neutrality**: the compiler writes only `buildings.json` +
  `world/`; `zones/timeline/mobility/meta/roads` are untouched (verified
  against git history — unchanged since commit `cc671fd`, long before this
  mission), so the epidemic trajectory is preserved exactly. Entering/leaving
  chunks never mutates authoritative state (renderer is read-only
  presentation; existing gameplay-integrity tests still pass).

## Exterior census (Houston, seed 0)

| | |
|---|---|
| Buildings | 22,525 (from 3,468 previously) — 92.8% observed heights |
| Parcels | 23,338 (DERIVED), 1,430 blocks |
| Road | 958.8 km cross-sectioned, 7,977 segments |
| Placements | 572,087 (465,893 props / 60,974 vehicles / 45,220 trees+bushes) |
| Spawn anchors | 83,859 |
| Chunks | 598 (23×26 @ 256 m), 13 MB gzipped |

Building archetypes: 17,691 detached residential · 1,456 multifamily ·
1,259 small commercial · 182 big box · 697 industrial · 522 civic ·
8 office high-rise · 710 generic (96.8% non-generic).

Surface census (2 m cells): 42% maintained grass, 19% building, 13% road,
12% parking, 4.6% rough vegetation, 3.4% sidewalk, 3.1% tree canopy,
2.9% other impervious, water/bare remainder. Zero cells outside the enum
(the encoding has no "free/unclassified" value at all).

Madisonville smoke build (generalization, §36): same generic generator, no
city-specific behavior (`grep`-verified: city names appear only in the
source-adapter/provenance layer), 2,940 buildings / 3,002 parcels /
151.8 km roads / 380 chunks — **all 12 certification gates pass** there too.

## Spawn certification

Full census in `godot/bundles/<city>/world/certification.json` (regenerated
by `--certify`).

- **All 60 committed Houston citizens**: valid spawns — on walkable surface,
  in bounds, never inside a footprint. Anchors: 54 building-entrance,
  5 pedestrian/walk, 1 routed-commute. **0 invalid, 0 crash-recovery
  fallbacks.** Same for Madisonville's 60.
- **1,000 deterministic sampled spawn contexts** across the full city:
  **0 invalid**.
- **Commutes are routed**: spawn point lies on the road-graph shortest path
  at the schedule fraction (straight-line interpolation is retired; tested
  to differ from the straight-line midpoint and to sit on the graph). Points
  where a road threads an observed footprint slide along the route.
- **Visually-empty urban metric** (§26): a sampled spawn in an urban parcel
  context is empty if within 50 m there are 0 buildings, <3 placements and
  <2% paved surface. Result: **0 / 888 urban samples (0.0% < 2% gate)**;
  mean 157 placements within 50 m of a sampled spawn. Open/park/vacant
  parcels are excluded by design — the generator knows why they are open.
- Godot-side: `_find_clear_spawn` now validates against the real building
  AABBs (index-aligned with authoritative building_id) instead of the
  legacy `_block_boxes` (which was empty on the real-buildings path — the
  audited hole); any correction emits a diagnostic. Certified data makes it
  a no-op.

## Regression

| Suite | Result |
|---|---|
| Python full suite | **445 passed, 0 failed** (299 at baseline; +146 new) |
| Godot TestRunner (headless) | 0 failures |
| Godot ExteriorStream (new) | 0 failures — streaming load/unload/reload identity + leak checks |
| Live bridge cert (LiveSmoke) | 0 failures on the compiled bundle (promote/demote, interact, cordon causality) |
| Walk-in interiors (LiveWalkIn/LiveInterior) | 0 failures — 25 enter/leave cycles, no node leak, container deltas persist |
| Survival (LiveSurvival) | 0 failures |
| Save/load (LiveSaveLoad, two-process) | reference == continued, **bit-identical** |
| Vertical demo (LiveVertical) | 0 failures |
| Epidemic neutrality | timeline/mobility/zones byte-untouched by the entire mission (git-verified) |
| Interior identity | interiors contract/generator/occupancy suites pass against the regenerated 22.5k-building stock; identity table persisted for future release diffs |

## Reproducible world build (§30)

```
python -m asphodel.world_source build \
  --city houston --city-name Houston \
  --release 2026-08-19.0 --seed 0 \
  --citizens 60 --download-missing --certify
```

Steps: read committed bbox → acquire missing public data (or `--offline`
from cached packets, checksum-verified) → commercial license gate (fails
closed) → normalize → identity → compile surfaces/streets/parcels/buildings/
detail/anchors → emit chunks + regenerate buildings.json → rebake citizens →
run the full certification harness (non-zero exit on any gate failure).
Cache policy: per provider/release/city/type parquet with sha256; CI tests
use fixtures, never the network. Full rebuild verified **byte-identical**
(601 files compared, 0 mismatches).

## Performance

Measured with `godot --headless --path godot res://tests/OwPerfBench.tscn --
--bundle houston` (new, `godot/tests/ow_perf_bench.gd` — a dense 7x7 focus
sweep around the origin, reading `ExteriorWorld.build_ms_stats()` /
`total_mm_instances()`, three runs, numbers stable across runs) and
`res://tests/StreetSmoke.tscn` for boot time (three runs on an otherwise idle
box; xvfb/GL contention from concurrent capture runs was seen to roughly
double these numbers, so the machine was quiesced first):

| metric | min | avg | max | n |
|---|---|---|---|---|
| T1 build (ground raster + building masses), ms/chunk | 2.51 | 9.70 | 22.19 | 102 |
| T2 build (grammar detail + road markings + collision), ms/chunk | 0.02 | 3.97 | 9.60 | 62 |
| T3 build (props/vehicles/trees MultiMesh), ms/chunk | 0.90 | 1.46 | 3.42 | 28 |

| metric | value |
|---|---|
| Resident chunks at steady state (dense 7x7 sweep around origin) | 96 |
| Resident scene-tree nodes | 3,205 |
| Total MultiMesh instances (props+vehicles+trees) | 5,903 |
| `OS.get_static_memory_usage()` before a fresh 3x3 T3 materialize | 22,189,150 B |
| same, after | 60,517,502 B (Δ 36.55 MB for 9 chunks' worth of T1-T3) |
| StreetScene boot: process launch → first ready assertion (headless, no bridge) | ~0.15 s |
| StreetScene boot: process launch → smoke-test done + quit | ~2.77 s (~3.18 s incl. engine teardown) |

The legacy path built the entire city (all buildings, all roads, the global
occupancy-grid scatter) eagerly at scene `_ready`; the compiled path builds
a bounded neighborhood and streams the rest. Steady-state resident node
count is bounded by tier radii (max observed in the streaming soak:
~1.9k nodes, returning to baseline after unload — no monotonic growth). The
per-chunk build costs above bound the worst case a player crossing several
tier boundaries per frame could trigger (`BUILD_BUDGET` caps this to 2
tier-builds/call regardless), so a T1 spike (~22ms max) is the number to
watch if streaming ever shows a frame hitch.

## Evidence

16 gameplay screenshots via the extended harness (`godot/tests/screenshot.gd`
+ `res://tests/Screenshot.tscn -- --bundle <city> --pos X,Z --yaw D --eye H
--citizen N`), captured under `xvfb-run` with a fresh Python bridge per run,
saved to `output/ow_screens/`. Coordinates were picked deterministically
from the compiled chunk JSON (parcel/building archetype + surface raster,
scratchpad `pick_coords.py`, not committed) — one representative spot per
certification context, nudged onto non-building ground with wall clearance.
Every honest visual read below is from actually looking at the PNG, not
inferring from the pick logic:

| file | context | reads as |
|---|---|---|
| `houston_residential.png` | detached-residential street | Reads well: single-family house facade, a second apartment-style block and street behind it, mowed yard, all lit and proportioned correctly. |
| `houston_multifamily.png` | multifamily | Camera sits in a tight interior courtyard corner — building fabric (windows, trim) is correct but the framing is too close-in to read as "multifamily block" at a glance; needs more standoff. |
| `houston_commercial.png` | small-commercial / arterial | A plain cream box wall with a dumpster and cars visible past it; recognizable as a small commercial building near a road, but the arterial road itself and any storefront glazing aren't in frame. |
| `houston_retail_parking.png` | big-box parking lot | Reads correctly after two rounds of coordinate tuning (see below): the store's long wall, light poles, and a row of parked cars are all in frame together — a legible big-box lot. |
| `houston_industrial.png` | industrial | Too close to the warehouse siding — the wall fills most of the frame with only a strip of grass and sky; industrial material reads (flat corrugated-style wall) but not the building as a whole. |
| `houston_downtown.png` | tallest-building context | Reads well: a genuine street canyon with the tallest tower in frame, parked cars, sidewalk markings — the best "downtown" feel in the set. |
| `houston_civic.png` | civic/school/medical | Tan civic-building wall with a rear yard/turf area and a low skyline of other buildings beyond; recognizable as an institutional building but framed from the back, not the entrance. |
| `houston_park.png` | park / open space | Weakest of the set: mostly a flat paved/turf boundary with houses on the distant horizon; the automated pick landed on the parcel's grass-vs-pavement seam rather than anywhere with trees/benches, so it reads as "edge of an open lot" more than "park." |
| `houston_highway.png` | elevated highway | Reads correctly as standing under an elevated deck — pillars, beam, lane stripes on the surface road below are all visible; the deck's underside has a visible repeating-texture/lightmap artifact worth a follow-up look. |
| `houston_vacant.png` | vacant/rough land | Reads as another paved lot (light poles, cars, a warehouse) rather than a rough/undeveloped parcel — plausible given the underlying data (this VACANT_OPEN parcel genuinely is bare pavement), but it doesn't visually differentiate from the retail-parking shot. |
| `houston_overhead.png` | overhead | Reads very well: full mixed-use area legible from above — road, parking lots, a spread of building footprints and colors, moving/parked traffic. |
| `houston_citizen7.png` | random spawn (citizen 7) | Reads well: sidewalk-level neighborhood view, multiple building types, streetlight, correct daylight. |
| `houston_citizen23.png` | random spawn (citizen 23) | Reads well: courtyard-style spawn between two building wings, trash bins, sidewalk — plausible apartment-complex spawn. |
| `houston_citizen41.png` | random spawn (citizen 41) | Reads well: fenced yard, parked car, small commercial-looking strip beyond — a believable street-level spawn. |
| `madisonville_tx_residential.png` | Madisonville residential | Same close-in framing issue as the Houston multifamily shot — right on top of a house wall; building material/color is correct for a smaller town but the shot needs more standoff. |
| `madisonville_tx_overhead.png` | Madisonville overhead | Reads very well: a retail strip along the highway frontage, dense parking, and open land beyond — clearly a smaller/lower-density city than Houston from the air alone. |

**Honest summary:** the overhead, downtown, retail-parking, and the three
random-citizen shots are unambiguous wins. Multifamily, industrial, civic,
and the Madisonville residential shot are technically correct (right
materials, right archetype) but stand too close to a single wall to read as
their category at a glance — a coordinate-picking issue (needs more
standoff biased away from every nearby building, not just the nearest one),
not a rendering bug. The park and vacant shots are the most honestly weak:
both landed on paved ground rather than the greenery/undeveloped texture a
human would pick for those categories, which is a limitation of picking by
raster-cell type alone from a script rather than a rendering defect.

## Gate table

```
OUTSIDE_WORLD_FULL_CITY_MVP
SOURCE_PROVENANCE_COMPLETE              PASS  (geo/provenance/data_sources.json, 23 entries)
COMMERCIAL_LICENSE_ALLOWLIST            PASS  (gate exit 0)
UNKNOWN_OR_RESTRICTED_SOURCE_USE           0
FULL_EXISTING_HOUSTON_EXTENT            PASS  (committed bbox, unmodified; 598/598 chunks)
DETERMINISTIC_WORLD_REBUILD             PASS  (byte-identical, 601 files)
STABLE_GEOGRAPHIC_IDENTITY              PASS  (GERS-founded ordering, identity.json, tests)
UNCLASSIFIED_GROUND                        0  (no unclassified byte exists; all cells in enum)
BUILDING_ON_ROAD_COLLISIONS                0  (street-class carriageways vs footprints)
NORMAL_INVALID_PLAYER_SPAWNS               0
VALID_PLAYER_SPAWN                      100%  (60/60 Houston, 60/60 Madisonville, 1000/1000 samples)
PARCEL_OR_CONTEXT_ASSIGNMENT          100.0%  (22,525/22,525; >=98% gate)
ROAD_CROSS_SECTION_COVERAGE           100.0%  (>=95% gate)
BUILDING_ARCHETYPE_COVERAGE            96.8%  (>=95% gate, non-generic)
CONTEXTUAL_PROPERTY_DETAIL             99.6%  (20,468/20,548 urban parcels; >=95% gate)
VISUALLY_EMPTY_URBAN_SPAWNS             0.0%  (<2% gate)
EPIDEMIC_TRAJECTORY_PRESERVED           PASS  (sim files byte-untouched)
SAVE_LOAD_DETERMINISM                   PASS  (two-process bit-identical)
INTERIOR_BUILDING_IDENTITY              PASS  (contract suites on regenerated stock + identity table)
SURVIVAL_RESOURCE_REGRESSION            PASS  (LiveSurvival + python suites)
CHUNK_LOAD_UNLOAD_IDENTITY              PASS  (debug-hash reproduces)
CHUNK_NODE_RESOURCE_LEAKS                  0  (teardown to baseline)
FULL_CITY_STREAMING                     PASS  (3-tier, bounded budget, whole extent addressable)
PYTHON_FULL_SUITE                       PASS  (445)
GODOT_TEST_RUNNER                       PASS
GODOT_LIVE_SMOKE                        PASS
```

## Known limitations

Being explicit — none of this is "solved realism":

- **Parcels are inferred, not surveyed** (Houston GIS unreachable from this
  environment): Voronoi-around-footprint subdivision produces plausible but
  wrong lot lines, especially on large blocks; every parcel is marked
  DERIVED. Re-running acquisition where COHGIS is reachable and adding a
  `HoustonParcelAdapter` is the designed upgrade path.
- **Terrain is flat** (3DEP unreachable; §6C fallback). Elevated freeways
  render as generic decks; no true grade separation.
- **Roofs, façades, and props are deliberately generic**: window rhythm is
  procedural, pitched roofs approximate non-rectangular footprints via the
  oriented bbox, repeated low-poly assets everywhere; no signage, no
  branding, no per-neighborhood architecture (by design and by §24).
- Road cross-sections are class-table approximations (observed widths used
  where Overture has them); no DOT lane geometry, turn lanes, or true
  signal placement; intersections have signal/sign props but no curb-return
  geometry.
- Static vehicles only; the pre-existing decorative traffic still runs off
  the legacy major-road file.
- `building_part` (4 features in bbox) is downloaded and normalized but not
  yet used for multi-mass rendering.
- Austin / San Antonio bundles remain on the legacy renderer until an
  Overture build is run for them (the path is the same one command).
- Interior/container identity is re-founded on the new stable keys: prior
  saves referencing old OSM-era building_ids are not migrated (there are no
  shipped saves; identity.json now exists precisely so future source-release
  migrations can be diffed).

## Next frontier (recommended, not implemented)

The smallest high-leverage follow-up: **acquire the real parcel layer**
(COHGIS from an environment where it is reachable) through the already-built
ArcGIS-shaped adapter seam, flipping parcels from DERIVED to OBSERVED —
frontages, driveways, fences and yard grammar all inherit accuracy from that
single layer. Second candidate: use `building_part` + Overture roof
attributes for multi-mass buildings downtown.

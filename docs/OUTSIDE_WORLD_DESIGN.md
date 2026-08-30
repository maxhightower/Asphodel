# Outside-World Full-City MVP — Design Contract

Status: authoritative design for the `world_source` pipeline (OW1–OW10).
Scope: exterior procedural presentation. Python owns authoritative simulation
truth; Godot renders compiled state and submits intent. Nothing in this
pipeline mutates simulation state.

## 0. Data reality (recorded, fail-closed)

Reachable from the build environment:

- Overture Maps S3 (`overturemaps-us-west-2.s3.amazonaws.com`) — REQUIRED
  source, release pinned `2026-08-19.0`.

Unreachable (egress policy denies CONNECT; recorded in
`geo/provenance/data_sources.json` as failed acquisitions with documented
fallbacks):

- City of Houston / COHGIS ArcGIS services → fallback: **derived parcel
  inference** from road network + buildings + land_use (observation_class
  DERIVED, never presented as surveyed parcels).
- USGS 3DEP DEM → fallback: **flat terrain** + semantic surface
  classification (per mission §6C this is an accepted MVP fallback).
- NLCD / tree canopy → fallback: Overture base land_cover + archetype
  inference.

## 1. Observation classes

Every compiled feature carries `observation_class`:

- `OBSERVED` — geometry/attribute taken from a public dataset.
- `DERIVED` — computed from observed data (frontage, entrance, parcel
  inference, lane count from class).
- `PROCEDURAL` — invented contextually (props, vehicles, individual trees,
  window rhythm).

## 2. WorldSourceV1 (normalized intermediate)

Produced by `asphodel/world_source/normalize.py` from raw Overture parquet;
consumed only by the compiler. In-memory dataclasses; on-disk debug dump
optional. Layers:

```
WorldSourceV1
  meta         city, bbox (W,S,E,N), origin lat0/lon0, release, versions
  roads        [Feature]  (Overture segment, class/subtype, width, names)
  connectors   [Feature]
  buildings    [Feature]  (footprint, height, levels, subtype, roof)
  building_parts [Feature]
  water        [Feature]
  land_use     [Feature]
  land_cover   [Feature]
  land         [Feature]
  infrastructure [Feature]
  places       [Feature]  (POI point, category, confidence)
```

`Feature = (stable_key, geometry_xz, properties, source, source_id,
observation_class, confidence, license_family)`.

Geometry is projected to the existing bundle frame at normalize time:
equirectangular about bbox center, x=east z=north metres
(`asphodel/osm_city/geometry.project` semantics, same constants).

## 3. Stable geographic identity (load-bearing)

Constraint: `building_id` is a de-facto contract — interiors, containers,
occupancy and Godot AABB lookup all key on the integer index of
`buildings.json["buildings"]` (see audit). Overture replaces the OSM
Overpass ordering, so identity is re-founded as:

- `stable_key`: Overture GERS id when present, else
  `d:<sha1(layer|round(cx,2)|round(cz,2)|round(area,1))[:16]>`.
- Deterministic ordering: buildings sorted by
  `(round(cz*10), round(cx*10), stable_key)`; `building_id` = index in that
  order. Same (city, release, compiler_version, seed) ⇒ same mapping
  (tested).
- `godot/bundles/<city>/world/identity.json` records
  `building_id -> {key, gers, centroid, area}` so future releases can diff.
- `buildings.json` is REGENERATED in this order (schema-compatible:
  `{poly, height}` + additive `key` field). Citizens are REBAKED against the
  new geometry (§20 of mission); epidemic trajectory is zone-level and
  preserved (tested).

The old `street_map_from_bundle` path (citizens from `zones[*].blocks`) is
retired for cities with compiled world data: citizen rebake consumes the
compiled building list itself, eliminating the audited blocks/buildings
divergence.

## 4. Compiled world bundle (Godot-consumable)

`godot/bundles/<city>/world/`:

- `world_meta.json` — version, seed, release, compiler_version, bbox,
  origin, chunk_size_m (256), chunk grid dims, feature counts, gate summary,
  attribution strings.
- `identity.json` — stable identity table (above).
- `spawn_anchors.json` — global anchor table (see §7).
- `chunks/c_<cx>_<cz>.json` — one per 256 m chunk, each independently
  regenerable and containing only presentation data:
  - `surface`: 2 m semantic raster, row-major RLE `[type,count,...]`,
    128×128 cells; types from the 10-value surface enum. `UNCLASSIFIED`
    does not exist in the enum — the base fill is always classified.
  - `roads`: segments clipped to chunk: polyline, class, cross-section
    (carriageway width, lane count, sidewalk/verge widths, markings flag,
    curb flag).
  - `parcels`: id, polygon, archetype, observation_class.
  - `buildings`: building_id, poly, height_m, floors, archetype, roof kind,
    entrance (edge index + t), feature list (garage/storefront/loading...).
  - `props`: `[kind, x, z, rot_deg, variant]` rows (compiled placements —
    Python owns placement so certification is engine-independent).
  - `vehicles`, `trees`, `bushes`: same row shape.
  - `anchors`: spawn anchors physically inside the chunk.

All placement randomness derives from
`hash64(world_seed, generator_version, stable_key/chunk, purpose_tag)` —
no global RNG, no order dependence.

## 5. Source precedence

Per feature class (mission §8): local GIS (unavailable this build) →
Overture conflated → derived → procedural. Encoded in
`asphodel/world_source/precedence.py` as explicit per-layer rules; the
manifest records which rule fired. Overture building geometry is never
degraded by an inferior source.

## 6. Surface semantics (OW-MVP-1)

Raster paint order (later wins): base land fill (ROUGH_VEGETATION default,
refined by land_cover/land_use) → water → parks/maintained grass →
parcel interiors by archetype → parking aprons → road corridors
(carriageway ROAD, flanking SIDEWALK/verge) → building footprints
(BUILDING). Gate: zero cells outside the enum; per-chunk counts summed for
census.

## 7. Spawn anchors (authoritative spatial concept)

Compiled kinds: `BUILDING_ENTRANCE`, `PEDESTRIAN_APPROACH`,
`SIDEWALK_ANCHOR`, `DRIVEWAY_ANCHOR`, `PARKING_ANCHOR`, `ROAD_ANCHOR`,
`INTERIOR_ANCHOR`. Every building gets an entrance anchor on its
street-facing facade, displaced to valid non-building ground. Citizen
baking (`osm_city/citizens.py`) is upgraded:

- home/work spawn → entrance anchor of the resolved building (or interior).
- commute spawn → position along the shortest road-graph route between
  home and work at the schedule fraction (straight-line interpolation
  retired), snapped to a ROAD/SIDEWALK anchor.
- errand → destination POI parcel entrance.
- Generic "clear patch" fallback exists only as crash recovery and logs a
  diagnostic; certification counts must be zero.

Godot `_find_clear_spawn` is replaced by anchor trust + real-footprint
point-in-AABB validation over the compiled building list.

## 8. Streaming (OW-MVP-9)

Tier 0 (always): world_meta, identity, chunk index, roads for map/mobility.
Tier 1 (far, r≤1280 m): chunk ground raster mesh + simple building masses.
Tier 2 (mid, r≤768 m): full building grammar, parking/parcel surfaces.
Tier 3 (near, r≤384 m): props, vehicles, trees, fences via MultiMesh.

Godot `exterior_world.gd` maintains a chunk cache keyed by (cx,cz,tier),
loads/unloads on player chunk crossing, MultiMesh/ArrayMesh batching only,
no per-prop nodes. Load/unload/reload determinism and node-leak tests via
headless harness.

## 9. Licensing separation

`world/` chunk data is derived from ODbL (Overture buildings/transport/base)
and CDLA-Permissive-2.0 (places): geographic database content + procedural
derivations only. No gameplay/narrative/loot data enters these files;
containers, interiors, citizens remain in Asphodel-proprietary files keyed
by building_id. Attribution strings carried in `world_meta.json` and
`geo/provenance/`. Commercial gate (`world_source.gate`) fails closed on
RESTRICTED/UNKNOWN sources.

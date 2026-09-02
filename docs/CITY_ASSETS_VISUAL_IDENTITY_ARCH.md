# Asphodel — City Assets + Visual Identity System

**Package A: Audit / Contract freeze.** This document is the architecture
gate the mission requires before any visual implementation. It records the
branch policy, the four Package-A censuses, the three frozen V1 contracts, and
the plan (with honest reality) for Packages B–L.

---

## 1. Branch policy (Section 0)

| item | value |
|---|---|
| Starting branch (session) | `claude/asphodel-isometric-presentation-v1-xwry9h` |
| Starting SHA | `cab278ead62a95f31175581bb59b10ee7578e74f` |
| Named outside-world MVP | `claude/outside-world-full-city-mvp-tuh0de` @ `da9ba66b566b1844c68d39509e874b6850bcec6a` |
| merge-base(iso, outside-world MVP) | `da9ba66…` |
| Outside-world MVP is ancestor of iso HEAD? | **YES** |
| iso ahead of MVP by | 5 commits (ISO presentation + exterior batches 1–5) |
| MVP ahead of iso by | 0 commits |
| Work branch created | `claude/city-assets-visual-identity-v1` (from `cab278e`) |

The current session branch already contains the entire outside-world/full-city
architecture (it descends directly from the MVP tip) **plus** the isometric
presentation layer and five exterior-polish batches. It is therefore the newest
authority and the correct base. The old June "block-city" work
(`claude/project-zomboid-lessons-*`, June) is not an ancestor and is not used.

Not merged (per instruction). No automatic merge.

---

## 2. Existing asset-kind census (Section 5 baseline)

**Exterior procedural meshes** (`godot/scripts/prop_meshes.gd`, 34 real kinds):
utility_pole, utility_cabinet, transformer_box, ac_condenser, rooftop_hvac,
fire_hydrant, streetlight, traffic_sign, traffic_signal, bollard, bench,
bus_shelter, parking_stop, mailbox, garbage_bin, recycling_bin, wood_fence,
chainlink_fence, dumpster, pallet, road_barrier, guardrail, sedan, suv, pickup,
van, box_truck, tree_oak, tree_round, tree_conical, tree_columnar, tree_palm,
bush_round, bush_low.

**Interior authoritative fixtures** (`asphodel/interiors.py`, searchable
containers): cabinet, fridge, shelf, dresser, desk, counter, crate — chosen per
archetype (house / retail / office / clinic / generic).

**Interior decor** (presentation only, no container, already 1:1-safe): sofa,
coffee_table, tv, armchair, bookshelf, counter, stove, table, chair, bed, rack,
display, stool — chosen per room kind (living / kitchen / bedroom / bathroom /
back_room / storeroom / open_office / break_room / exam / supply / office /
shop …).

These are the semantic footholds AssetCatalogV1 wraps; none are discarded.

## 3. VIS-0 — real building-appearance coverage (Section 13)

Measured directly from the **pinned Overture release `2026-08-19.0`**, building
theme (`theme=buildings/type=building`), re-acquired for this census via the
public Overture S3 bucket. Tool: `tools/appearance_census.py`; raw numbers:
`docs/VIS0_appearance_census.json`. **These are OBSERVED source-coverage
percentages — no inference.**

| city | buildings | height% | floors% | roof_shape% | roof_mat% | roof_col% | facade_mat% | facade_col% |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| madisonville_tx | 2940 | 67.9 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| houston | 22524 | 92.8 | 0.29 | 0.11 | 0.00 | 0.02 | 0.02 | 0.01 |
| austin | 29245 | 90.2 | 1.01 | 0.06 | 0.00 | 0.00 | 0.00 | 0.00 |
| san_antonio | 35658 | 98.8 | 0.14 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

**Exact source fields** present in the Overture building schema:
`height`, `min_height`, `num_floors`, `num_floors_underground`, `min_floor`,
`subtype`, `class`, `facade_color`, `facade_material`, `roof_material`,
`roof_shape`, `roof_direction`, `roof_orientation`, `roof_color`, `roof_height`,
`names`, `sources`. **License:** ODbL-1.0 (OSM-derived), family `ODBL`, recorded
in `geo/provenance/data_sources.json`.

**Headline reality (do not soften):**
- **Height is the only well-covered appearance attribute** (68–99%).
- **Facade colour, facade material, roof colour, roof material, roof shape are
  effectively absent (0.00–0.11%)** for all four Texas certification cities.
  Houston has the most and it is *9 buildings total* with any colour/material.
- Therefore Goal-2a ("colours/materials correspond to the real city when public
  data provides it") will **almost never trigger** for these cities. Any claim
  of "real-world matching" for facade/roof colour here would be false.

**Pipeline reality:** `world_source/normalize.py` currently reads only
`height`, `num_floors`, `subtype`, `class`, `roof_shape` and drops the
colour/material columns. `BuildingRecord` carries no appearance colour/material
at all. Package B plumbs the (rare) observed values through; Package C supplies
the ~100% that must be inferred.

## 4. Climate source audit (Section 18)

Preferred machine-readable public source: **NOAA / NCEI U.S. Climate Normals
(1991–2020)** — monthly and hourly normals per station (temperature, dewpoint,
wind speed/direction, sky-cover/cloud frequency where the hourly product
provides it, precipitation). US federal work product, **public domain / no
copyright** (license family `PUBLIC_DOMAIN`), commercially permissible.

Acquisition contract (mirrors the Overture layer, Package I):
- Pin the normals period (1991–2020) and product id; cache the per-station
  extract locally under `data/raw/climate/…`; record provenance.
- Map each city to its nearest suitable normals station via lat/lon from the
  bundle meta (no city-name table).
- **Fail closed:** if a station/record is unavailable, emit a documented
  PROCEDURAL climate fallback (latitude-band defaults) rather than fabricating
  "observed" normals. Never a runtime web dependency during gameplay.
- Reachability is **unverified from this environment** (only Overture S3 is
  confirmed reachable; `tnmaccess`, arcgis, etc. are blocked). Package I must
  probe NCEI and, if blocked, ship the PROCEDURAL fallback and report it
  honestly.

---

## 5. Frozen V1 contracts (`asphodel/city_visual/`)

Core rule (Section 2): `WORLD SEMANTICS → PLACEMENT GRAMMAR → SEMANTIC ASSET
REQUEST → ASSET FAMILY → VISUAL VARIANT`. Generator code requests semantic ids
only; it never names a `.glb`/procedural mesh directly.

### AssetCatalogV1 (`asset_catalog.py`, data `catalog_v1.yaml`)
- `AssetFamily`: semantic_id, category, placement, outdoor, dimensions
  (w/d/h m), clearance, collision (none/simple/mesh), interaction class
  (sit/sleep/cook/work_at_desk/stock_shelf/use_register/examine_patient/
  use_machine/store/search…), material_family, room/parcel/building/climate
  tags, seed_tag, lod_fallback, variants.
- `AssetVariant`: id, weight, `resource` (res:// authored asset **or** null),
  `procedural` (fallback kind), conditions.
- **V1 seed = 59 families** over the existing procedural meshes; every variant
  currently backed by a procedural fallback (no `.glb` authored yet).
- Validation: unique semantic ids, positive dimensions, every variant has a
  resource **or** procedural fallback, enum checks, `get()` on unknown id raises
  (fails visibly). Deterministic weighted `select(seed)` (stable per seed).

### BuildingAppearanceV1 (`building_appearance.py`)
- Every attribute is an `AppearanceValue{value, provenance}` with provenance in
  `OBSERVED / DERIVED / PROCEDURAL` (reuses Asphodel's existing philosophy).
- `facade{color,material}`, `roof{color,material,shape}`, `style_family`,
  `height_m`, `floors`. Canonical material families frozen here (Section 16):
  facade = brick/painted_brick/siding/stucco/concrete/stone/metal_panel/wood/
  glass_curtain/painted_masonry; roof = asphalt_shingle/standing_seam_metal/
  flat_membrane/tile/roof_generic.
- Validation: `#rrggbb` colours, material/shape enums, `style_family` may never
  be OBSERVED (always inferred).

### CityVisualProfileV1 (`city_profile.py`)
- `location{lat,lon,elev}`, `architecture{palette + material distributions,
  archetype_profiles}`, `climate{temp/dewpoint/cloud/wind/precip normals}`,
  `atmosphere{humidity/haze/visibility/cloudiness}`, `vegetation{regional_family,
  landcover_distribution}`, `sources[SourceRef]`.
- Derived from geography + public data; `appearance_class` may never be OBSERVED.
- Validation: lat/lon ranges, 0..1 atmosphere factors, distributions sum ~1.

Tests: `tests/test_city_visual_schemas.py` (14 tests incl. the Section 24
no-city-name-special-case static gate).

---

## 6. Plan for later packages (with reality)

- **B — Appearance truth:** read Overture facade/roof colour+material in
  `normalize.py`; add them (with provenance) to `BuildingRecord`, chunk JSON,
  and the renderer; snap observed colour onto a compatible material family.
  *Reality:* affects ~9 Houston buildings + generalizes to future data.
- **C — Appearance inference:** deterministic hierarchy (observed → nearby
  observed same-archetype → local distribution → city/archetype prior →
  archetype prior → fail-safe), spatially coherent, provenance-labelled
  DERIVED/PROCEDURAL. *This supplies ~100% of appearance for the cert cities.*
- **D — Asset catalog exterior vertical:** resolve placements through the
  catalog; add authored/richer variants; keep MultiMesh batching.
- **E — Vegetation V1:** regional families conditioned on
  climate/land-cover/parcel/surface (never on city name).
- **F/G — Interiors + workplaces:** decor layer stays separate from
  authoritative fixtures; room-conditioned layout; affordance metadata.
- **H — Signage / fictional business identity** (no real trademarks).
- **I — Climate profile** (NOAA NCEI, cached, fail-closed).
- **J/K — Solar / sky / cloud-field + shadows / atmosphere** driven by profile.
- **L — Condition overlays** (NORMAL→…→OVERRUN) last.

Persistence classes (Section 11) preserved: DECORATIVE (regenerated, no save),
AFFORDANCE (regenerated, function exposed, delta only if changed), AUTHORITATIVE
(searchable containers etc., persistent when changed). AssetCatalog interaction
class + the existing fixture/decor split already encode this distinction.

---

## 7. Shipped: Package H — Signage + business identity (Section 9)

`asphodel/city_visual/business_identity.py` (`BusinessIdentityV1`) generates a
**deterministic fictional business identity** for every non-residential building
(`business_id`, `category` from a 34-member taxonomy, `display_name`, a sign
`palette` primary/secondary/accent, `logo_glyph`, `sign_family`, `hours`). The
category is drawn from an archetype-weighted pool; palette hue is nudged by a
coarse spatial field so a strip shares a tone. Attached in the compiler
(`compile.py` → `assign_records`) onto `BuildingRecord.identity` and serialized
into the chunk building dict alongside `appearance` (`chunks.py`).

Hard rules honoured:
- **Provenance honesty:** an invented identity is always `PROCEDURAL`; nothing
  is ever labelled OBSERVED. Real public place names are *not* adopted in V1 (to
  stay clear of trademarks); the door is left open for later where licensing
  permits (Section 9).
- **No real trademarks:** names are built from generic surname/adjective/noun
  pools and rotated past a curated real-brand blocklist, so a random draw can
  never coincide with a real brand (test-guaranteed).
- **No city-name special cases:** identity is a pure function of
  `(stable_key, centroid, archetype, seed)`.
- **Determinism:** identity uses a stable FNV-1a string hash, never Python's
  randomized built-in `hash()`. Cross-`PYTHONHASHSEED` recompile of Houston is
  identity-identical (3378 identities, 0 mismatches). *This pass also fixed a
  latent Package-C bug: `appearance_infer.py` had keyed off built-in `hash()`,
  making inferred appearance non-deterministic across processes; it now uses the
  same stable hash.*

Rendering is **building-integrated** (`exterior_world.gd::_render_signage`), not
standalone MultiMesh props, so batching is untouched: storefronts get a fascia
band; other non-residential buildings a wall plaque; `pole_sign` categories a
raised parapet marquee; `monument_sign` categories a low ground monument placed
only where the frontage cell is a concrete apron (no road/lawn collision). Each
sign is tinted from the business palette with a cheap logo-glyph emblem. Sign
hardware is registered in the catalog as the `sign` category (fascia, wall,
pole, monument, hanging, roadside, directory, building-number) with no standalone
`render_kind` (realized by the building-integrated generator).

Tests: `tests/test_business_identity.py` (13, incl. the cross-`PYTHONHASHSEED`
determinism gate and the no-real-brand gate). The Godot `AssetCatalogSmoke`
no-magenta gate stays green.

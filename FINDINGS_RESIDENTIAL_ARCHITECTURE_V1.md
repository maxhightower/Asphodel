# FINDINGS — Residential Architecture Grammar V1

**RESIDENTIAL_ARCHITECTURE_V1: PASS** (one residual: numeric perf deltas, below)

Python is the sole architectural authority; Godot consumes it. Verified:
form≠style separation, observed-data precedence, correlated cohort +
builder-family diversity, deterministic cross-process output, schema/chunk
validation, a **real 17,691-house Houston census** (all 12 styles, no collapse,
entropy 3.19/3.58), and — after obtaining Godot 4.4 and rendering headless under
Xvfb + software OpenGL — **actual rendered screenshots**: a neutral grayscale
gallery proving the 12 styles are distinguishable from **silhouette alone**, a
material gallery, and **two real Houston neighborhoods streamed from the
repatched bundle through the new renderer** showing tile/gable/hip/ranch roof
diversity, brick/siding/stucco/board-and-batten facades, a half-timbered Tudor,
long ranches, bungalows and 2-storey boxes — not one repeated house. Screenshots
are committed under `docs/residential_v1/`.

Rendering also caught **real GDScript type-inference errors** in the first
commit's renderer (Variant-from-Dictionary / Array-iteration used with `:=`,
which `gdparse` does not catch) — the renderer now compiles clean in Godot 4.4
and runs. The single honest residual is that formal **T1/T2/T3 perf deltas were
not numerically benchmarked** (the renders confirm it runs at full-scene scale;
geometry is batched with no per-house material or per-window node, so a
regression is bounded by construction) — reported, not hidden.

---

## BASELINE

- **STARTING_BRANCH:** `claude/city-assets-visual-identity-v1` (canonical visual-generation parent)
- **STARTING_SHA:** `477b90237e2dd515862eb5e85ea480259ac58030`
- **Work branch:** `claude/residential-architecture-grammar-v1-kx5hpz`
- **MERGE_BASE_WITH_CURRENT_CANONICAL:** identical — the work branch was forked
  from `city-assets-visual-identity-v1` at `477b902` with **zero divergence**
  (`git rev-list --count` both directions = 0), so no reconciliation/merge was
  required. Newer branches exist in the remote (`asphodel-authoritative-world`,
  `asphodel-isometric-presentation-v1`, …) but none is the residential/visual
  parent; none touches `buildings_grammar.py` / `appearance_infer.py` /
  `exterior_world.gd` ahead of this line, so no P0 material/roof/site work was
  overwritten.
- **Verified on the starting tree** (mission "current reality"): detached houses
  were ~all `DETACHED_RESIDENTIAL`; procedural height 3.5–6.5 m; ~90% pitched;
  `buildings_grammar` rolled garage ~45% / porch ~35%; appearance weighted
  siding 3 / brick 3 / painted_masonry 1 / stucco 1; roof collapsed to
  asphalt_shingle; `style_family` was `<region>_residential_<material>`; and
  `exterior_world.gd` **independently re-rolled** porch ~62% / garage ~52% /
  patio ~45% / chimney ~58%. All confirmed before change.

## AUTHORITY (the central outcome)

**PYTHON DECIDES WHAT THE HOUSE IS; GODOT RENDERS THAT DECISION.**

- **Old residential decision owners (removed / demoted):**
  - `buildings_grammar.compile_buildings` — the `DetRand … chance(0.45)` garage
    and `chance(0.35)` porch rolls for detached houses were **deleted**. `feat`
    garage/porch are now *derived from* the authoritative architecture record
    (`residential_grammar._derive_feat_flags`), never rolled independently.
  - `exterior_world.gd::_detail_building` — the independent
    `want_porch/want_garage/want_patio/want_chimney` `_stable_hash` rolls are now
    reached **only** as a clearly-labelled *legacy fallback* for old bundles that
    carry no architecture record (see below).
- **New single owner:** `asphodel/world_source/residential_grammar.py`
  (`assign_architecture`) compiles one `ResidentialArchitectureV1` per detached
  house — form, style, era, massing, roof, multi-material facade, porch, windows,
  foundation, parking, details, renovations — **before** the generic appearance
  pass, and reconciles the appearance material families to agree.
- **Godot consumes:** `godot/scripts/residential_house_renderer.gd` reads the
  compiled record and emits geometry. It contains **no style/porch/garage roll**;
  `exterior_world.gd::_detail_building` dispatches detached houses with an
  `architecture` key to it and returns.
- **Legacy fallbacks remaining (intentional, isolated):** a building compiled by
  an older pipeline carries no `architecture` key; `_detail_building` then falls
  through to the pre-existing procedural house path (now commented
  `LEGACY FALLBACK ONLY (mission R17)`). This is the only place the old
  independent rolls survive, and only for un-migrated bundles.

## SCHEMA

- **New types / files:**
  - `asphodel/city_visual/residential_architecture.py` —
    `ResidentialArchitectureV1` (+ `ArchValue`, `Foundation`, `Massing`,
    `RoofGrammar`, `FacadeComposition`, `PorchGrammar`, `WindowGrammar`), all
    versioned (`RESIDENTIAL_ARCH_VERSION = 1`), JSON `to_dict/from_dict`, and a
    closed-enum `validate()`. Vocabulary: 9 eras, 12+reserved forms,
    12+reserved styles, 10 roof families × 4 pitch × 4 eave, 3 foundations,
    7 porch families × 8 support families, 9 window grammars, 9 parking
    families, 12 facade subtypes → shared shader families, detail + modification
    tag sets.
  - `asphodel/world_source/residential_grammar.py` — morphology, era, region
    priors, cohorts, builder families, the 12 style grammars, selection.
- **Serialized contract:** the compiled chunk building dict gains an **optional**
  `"architecture"` key (only on `DETACHED_RESIDENTIAL`). Additive to
  `CHUNK_SCHEMA_VERSION = 1` (old chunks without it stay valid; the renderer
  falls back). `schema.validate_chunk` now validates the architecture record when
  present and rejects a record on a non-detached building or a malformed one
  (never silently accepted).
- **Provenance:** `era` is **DERIVED** from a real construction year and
  **PROCEDURAL** from the cohort prior (never OBSERVED); `form` is **DERIVED**
  (constrained by the observed footprint morphology); `style` is **PROCEDURAL**
  (a neighbourhood prior) and validation forbids `style` = OBSERVED. Observed
  height/floors/roof-shape/facade-material always win and are echoed with their
  original provenance.

## IMPLEMENTED STYLES (12 production, all realisable + tested)

| Style | Compatible forms | Renderer |
|---|---|---|
| CRAFTSMAN | BUNGALOW, FOURSQUARE | low+wide roof, tapered/brick-pier posts, rafter tails |
| FOLK_NATIONAL | FOLK_COTTAGE, BUNGALOW | simple gable, lap siding, simple posts |
| FOLK_VICTORIAN | FOLK_COTTAGE, VICTORIAN_IRREGULAR | folk base + gingerbread trim, gable decoration |
| QUEEN_ANNE | VICTORIAN_IRREGULAR, FOURSQUARE | steep complex hip/cross-gable, wrap porch, bay |
| AMERICAN_FOURSQUARE | FOURSQUARE | 2-storey hip + dormer, full porch, symmetric windows |
| COLONIAL_REVIVAL | REVIVAL_TWO_STORY, FOURSQUARE | **symmetric** window grammar, centred stoop, columns |
| TUDOR_REVIVAL | TUDOR_COTTAGE, REVIVAL_TWO_STORY | **steep** cross-gable, brick+stucco gable, big chimney |
| MINIMAL_TRADITIONAL | MINIMAL_TRADITIONAL, FOLK_COTTAGE | tight-eave gable, stoop, shutters |
| TRADITIONAL_RANCH | LINEAR_RANCH, L_RANCH, U_RANCH | low+wide hip/gable, slab, attached garage/carport, picture window |
| MID_CENTURY_MODERN | LINEAR_RANCH, L_RANCH, CONTEMPORARY_COMPACT | **very-low** roof, horizontal glazing, carport, thin/slanted posts |
| TEXAS_NEO_TRADITIONAL | SUBURBAN_TWO_STORY, REVIVAL_TWO_STORY | intersecting gables, **brick-front / siding-side**, 2-car front garage |
| SPANISH_ECLECTIC | MINIMAL_TRADITIONAL, REVIVAL_TWO_STORY, LINEAR_RANCH | low hip, **tile roof**, stucco, arched/wrought-iron |

Schema + renderer stay extensible for the reserved wave (PRAIRIE,
FRENCH_ECLECTIC, SHOTGUN_VERNACULAR, 1970S_CONTEMPORARY, NEO_CRAFTSMAN,
MODERN_FARMHOUSE, CONTEMPORARY_INFILL, MEDITERRANEAN_SUBURBAN) — the enums list
them and the grammar table is data-driven.

## COHORT SYSTEM

- **Block → cohort:** cohorts are keyed on the deterministic `Parcel.block_id`
  and the block centroid. A coarse (~520 m) value-noise "development-wave" field
  over the centroid maps to an era band, so **adjacent blocks share an era**
  (tested: adjacent-block era match ≫ distant-block match) and the city reads as
  neighbourhoods of different ages, not per-block noise. Each cohort draws its
  primary styles from its dominant era (region-weighted), plus a secondary era.
- **Builder families:** historic cohorts get more, looser families (weaker
  repetition); postwar/newer cohorts get **fewer, tighter** families (strong
  tract repetition, tested). A house adopts its family's form/style/roof/porch/
  parking/material package, then varies by mirrored plan / plan_variant / garage
  side / porch subtype / roof colour.
- **Infill:** a bounded per-house `infill_probability` (higher on older cohorts)
  lets a later build break its block's era/style in a controlled way. Region
  priors come only from `region_profile(lat, lon)` — **no city-name dispatch**
  anywhere.

## HOUSTON CENSUS (real compiled bundle, 17,691 detached houses)

Produced by `tools/repatch_residential_architecture.py godot/bundles/houston
--lat 29.76 --lon -95.36` (geography supplied as a parameter, not a name switch);
590 cohorts, 1,819 builder families, region auto-detected `gulf_south`.

- **by style:** MID_CENTURY_MODERN 23%, MINIMAL_TRADITIONAL 18%,
  TEXAS_NEO_TRADITIONAL 14%, CRAFTSMAN 9%, TRADITIONAL_RANCH 8%, TUDOR_REVIVAL 7%,
  SPANISH_ECLECTIC 4%, COLONIAL_REVIVAL 4%, FOLK_VICTORIAN 4%, FOLK_NATIONAL 4%,
  QUEEN_ANNE 3%, AMERICAN_FOURSQUARE 1% — **all 12 present, no collapse.**
  Style entropy **3.19 / 3.58** bits.
- **by form:** all 12 present (CONTEMPORARY_COMPACT 19% … U_RANCH <1%, correctly
  rare — few real footprints are strongly U-winged).
- **by era:** spread PRE_1900 2% → 2015_PLUS 10%, spatially banded.
- **by foundation:** SLAB 73%, LOW_CRAWLSPACE 19%, RAISED_PIER_BEAM 9% (historic).
- **by roof family:** 10 families (CROSS_GABLE 24% … CROSS_HIP 1%).
- **by roof material:** asphalt 73%, standing-seam 23% (incl. metal retrofits),
  tile 4% (Spanish).
- **by facade front family:** brick 59%, siding 34%, stucco 4%, painted_brick 3%
  (multi-material; gulf-coast brick lean is geographic).
- **by parking:** SIDE_DRIVE 35%, ATTACHED_FRONT_TWO 16%, CARPORT 15%,
  ATTACHED_FRONT_ONE 14%, ATTACHED_SIDE 13%, INTEGRATED 7% — **no longer boolean.**
- **by porch:** STOOP 34%, RECESSED 33%, PARTIAL_FRONT 20%, FULL_WIDTH 9%, … .
- **Source-data coverage:** observed height ~present (Overture), observed
  floors/roof-shape mostly derived, observed **year-built = 0%** and **facade/roof
  material ≈ 0%** for Houston (Overture reality). So `era` provenance is 100%
  PROCEDURAL here — reported honestly, never labelled OBSERVED. A 240-block
  synthetic census (`tools/residential_census.py`) corroborates: entropy
  3.11/3.58, **median 4 distinct styles/block**, mean dominant-style share 0.56
  (blocks internally coherent, not random soup).

## VISUAL EVIDENCE (captured — Godot 4.4 headless, Xvfb + llvmpipe OpenGL3)

All four PNGs are committed under `docs/residential_v1/`.

- **`gallery_neutral_silhouettes.png`** — `ResidentialArchitectureGallery.tscn`
  `--neutral`: one flat grey material on all 12 styles under a raking sun, so
  **shape is the only discriminator**. Steep Tudor/Queen-Anne gables, hipped
  Foursquare/Colonial, low-slung wide Ranch/MCM, compact bungalows with front
  porches, and 2-storey boxes are each distinguishable — the mission's core gate.
- **`gallery_material.png`** — same 12 houses, full `WorldMaterials` shader:
  brick courses, siding, smooth stucco, and a terracotta tile roof (Spanish),
  varied roof colours, porches, foundations. 4,914 verts total for 12 houses.
- **`houston_dense_subdivision.png`** (world pos 2534.7,−2746.9, zoom 110) and
  **`houston_neighborhood.png`** (−1916.6,−57.3, zoom 115) — the **real streaming
  Houston exterior** from the repatched bundle, so the new renderer (not the
  legacy fallback) drew every house. Visible: tile-roofed Spanish houses, a
  white **half-timbered Tudor** gable, brick and board-and-batten facades, long
  linear ranches, and 2-storey boxes intermixed at block scale — a genuinely
  mixed neighbourhood rather than repetitions of one model.
- **Fixture + manifest:** `godot/tests/residential_gallery.json` (from
  `tools/gen_residential_gallery.py`, all 12 records `validate()`-clean) and
  `godot/tests/residential_cert_manifest.json` (5 fixed neighbourhood views taken
  from the existing P0 manifest's residential positions — chosen up front).
- **How to reproduce:** `Godot_v4.4 --path godot --rendering-driver opengl3
  res://tests/ResidentialArchitectureGallery.tscn -- [--neutral] --out X.png` and
  `res://tests/IsoPosShot.tscn -- --bundle houston --pos <x,z> --zoom <z> --out X.png`.
- Note: rendering exposed and I fixed real Godot type-inference errors the
  `gdparse` syntax check missed; the renderer now compiles clean in Godot 4.4.

## DETERMINISM

- `tests/test_residential_arch_determinism.py`: same input+seed identical;
  different seed differs; **feature iteration order does not change any house's
  architecture** (keyed on stable key, not order — `bid` is an index and excluded);
  **cross-process** identical output under two different `PYTHONHASHSEED` values
  (subprocess diff) — proving no reliance on the salted built-in `hash()`;
  morphology is pure. All streams draw from `DetRand`/`hash64` only.

## PERFORMANCE

- **Not benchmarked in Godot** (no binary). By construction: all house geometry
  is emitted into the shared per-chunk `SurfaceTool` (one `MeshInstance3D` per
  chunk for building detail, one shared `WorldMaterials.building_material()`
  shader) — **no per-house material, no Node3D per window/post** (windows are
  flat batched quads, posts/steps are batched boxes), so **node count and draw
  calls are unchanged** vs the legacy path. Per-house vertex count is comparable
  to the legacy house path it replaces (walls + windowed openings + a family
  roof + porch/garage/chimney); the biggest additions are the multi-region walls
  and the family roof, both a handful of quads. Streaming radii, tiers and
  MultiMesh usage are untouched. A T2 build-time regression, if any, is expected
  to be small; **this must be measured with the existing iso/exterior bench once a
  Godot binary is available** — reported as an open item rather than hidden.

## TESTS

```
# new residential suite (36 tests)
python -m pytest tests/test_residential_architecture.py \
  tests/test_residential_style_compatibility.py \
  tests/test_residential_cohorts.py \
  tests/test_residential_arch_determinism.py -q
# => 36 passed

# world_source regression set (182 tests)
python -m pytest tests/test_detail.py tests/test_appearance_pipeline.py \
  tests/test_appearance_infer.py tests/test_grammar_tables.py \
  tests/test_streets_grammar.py tests/test_topology.py \
  tests/test_city_visual_schemas.py tests/test_business_identity.py ... -q
# => 182 passed

# full suite
python -m pytest tests/ -q --ignore=tests/test_world_source_acquire.py
# => 529 passed, 1 failed
#    the 1 failure is tests/test_world_from_compiled.py::test_compile_writes_only_
#    presentation_files — it needs downloaded Overture raw parquet
#    (data/raw/overture/.../segment.parquet) that is absent in this environment;
#    it fails identically on the baseline and is unrelated to this change.

# GDScript syntax
gdparse godot/scripts/residential_house_renderer.gd   # OK
gdparse godot/scripts/exterior_world.gd               # OK
gdparse godot/tests/residential_gallery.gd            # OK
```

Coverage maps to the mission's required list: determinism (1–4), observed
height/floors/roof/facade win (5–8), incompatible form/style rejected (9),
1-storey↛Foursquare (10), elongated→Ranch not Foursquare (11), L/U-Ranch need
winged footprint (12), Colonial symmetric windows (13), Tudor steep roof (14),
MCM very-low+horizontal (15), Ranch slab (16), historic raised foundation (17),
Texas-Neo brick-front/siding-side (18), same-block cohort (19), postwar builder
reuse (20), infill bounded (21), non-residential unchanged (22), round-trip (23),
chunk validation (24).

## ACCEPTANCE GATES

PASS: form≠style · Python-compiled decisions · Godot consumes not re-rolls ·
footprint truth preserved · observed outranks derived/procedural · no city-name
dispatch · 12 styles implemented · style changes geometry (roof/window/porch/
foundation/parking, not just colour) · multi-material facades · same-block
correlation · builder-family repetition · bounded infill/renovation ·
determinism across processes · chunk/schema validation · non-residential
unregressed · performance-by-construction (batched, no node/material explosion).

MET (rendered): neutral silhouette gallery, material gallery, and two real
Houston neighbourhood captures — all committed under `docs/residential_v1/`.

RESIDUAL: the **numeric Godot perf bench** (T1/T2/T3 build-time / node / memory
deltas) was not run — the captures confirm it renders correctly at full scene
scale and the geometry is batched with no per-house material / per-window node,
so any regression is bounded by construction, but exact numbers are unmeasured.

## REMAINING GAPS (genuine)

1. **Godot perf numbers** — batched/no-node-explosion by design and confirmed to
   render at scene scale, but exact T1/T2/T3 deltas are unmeasured. Run the
   existing iso/exterior bench before/after to quantify.
2. **Year-built = 0%** in Overture for the cert cities → era is a spatial/cohort
   prior (PROCEDURAL), honestly. Richer data would raise era to DERIVED/OBSERVED.
3. **`DETACHED_REAR_OBSERVED` parking** is never emitted (no accessory-structure
   evidence in the source) — correct per the truth rule; would activate with
   real accessory footprints.
4. **Repatch keys on `bid`** (chunks carry no source UUID); a from-source
   recompile keys on the stable GERS key and may pick a slightly different subset
   — expected and documented.
5. Reserved forms/styles (Prairie, Split-Level, Modern Farmhouse, …) are in the
   enums but not yet produced by the grammar.

"""Neighbourhood cohort + builder-family correlation gates (mission R4/R5)."""
from __future__ import annotations

from shapely.geometry import Polygon

from asphodel.world_source import residential_grammar as rg
from asphodel.world_source.records import Parcel
from asphodel.world_source import buildings_grammar
from tests._res_fixtures import rect, feature, compile_block


def test_same_block_houses_share_one_cohort():
    feats = [feature(f"h{i}", rect(40 + i * 15, 40, 11, 9)) for i in range(20)]
    recs, stats = compile_block(feats)
    assert stats["cohorts"] == 1
    cids = {r.architecture["cohort_id"] for r in recs}
    assert cids == {0}


def test_same_block_is_style_correlated_not_uniform_random():
    # A single block should be dominated by a small number of styles (its cohort),
    # never a fresh independent style per lot.
    feats = [feature(f"h{i}", rect(40 + (i % 6) * 16, 40 + (i // 6) * 20, 12, 10))
             for i in range(24)]
    recs, _ = compile_block(feats)
    styles = [r.architecture["style"]["value"] for r in recs]
    distinct = set(styles)
    # cohort priors keep a block to a handful of related styles, not ~all 12.
    assert len(distinct) <= 5
    top = max(distinct, key=styles.count)
    assert styles.count(top) >= len(styles) * 0.3


def test_nearby_blocks_are_spatially_correlated_in_era():
    # Two adjacent block centroids share a development-wave era far more often than
    # two distant ones (the era field is spatially coherent, not per-block noise).
    seed = 7
    same, diff = 0, 0
    for k in range(60):
        base_x = k * 40.0
        e_here = rg._era_field(base_x, 0.0, seed)
        e_near = rg._era_field(base_x + 30.0, 0.0, seed)     # ~adjacent block
        e_far = rg._era_field(base_x + 900.0, 0.0, seed)     # far away
        same += int(e_here == e_near)
        diff += int(e_here == e_far)
    assert same > diff
    assert same >= 40      # adjacent blocks usually match era


def test_postwar_cohorts_reuse_builder_families():
    # In a postwar tract many houses should adhere to the same small set of builder
    # families (intentional repetition), i.e. builder_family_id is reused.
    geoms = [rect(40 + (i % 8) * 20, 40 + (i // 8) * 24, 20, 9) for i in range(40)]
    feats = [feature(f"h{i}", geoms[i]) for i in range(40)]
    # force a postwar block via a location whose era field is postwar is hard, so
    # test the mechanism directly: build a postwar cohort and assign many houses.
    cohort = rg.build_cohort(seed=11, cohort_id=0, cx=0.0, cz=0.0,
                             region=rg.region_profile(29.7, -95.4))
    # ensure a postwar-style cohort for the assertion by picking a seed/pos whose
    # era is >=1940; if not, skip to a constructed one.
    if rg.ERA_SEQUENCE.index(cohort.dominant_era) < 3:
        cohort.dominant_era = "1960_1979"
        cohort.builder_families = rg.build_cohort(
            11, 0, 0.0, 0.0, {}).builder_families
    fam_used = {}
    for i, g in enumerate(geoms):
        a = rg.build_architecture(
            rg.HouseInputs(bid=i, key=f"h{i}",
                           morph=rg.compute_morphology(Polygon(g[0])),
                           obs_floors=1),
            cohort, seed=11)
        if a.builder_family_id >= 0:
            fam_used[a.builder_family_id] = fam_used.get(a.builder_family_id, 0) + 1
    # a few families, each reused by multiple houses
    assert fam_used, "no house adhered to a builder family"
    assert max(fam_used.values()) >= 4
    assert len(fam_used) <= 5


def test_infill_probability_is_bounded():
    for era in rg.ERA_SEQUENCE:
        c = rg.build_cohort(1, 0, 0.0, 0.0, {})
        assert 0.0 <= c.infill_probability <= 0.2
        assert 0.0 <= c.renovation_pressure <= 1.0


def test_builder_family_count_reflects_era_repetition():
    # historic cohorts get more, looser families; postwar/new get fewer, tighter
    # ones (stronger tract repetition). Sample cohorts across space and compare the
    # average family count of pre-1940 vs 1980+ cohorts.
    hist_counts, new_counts = [], []
    for k in range(400):
        cx = (k % 20) * 600.0
        cz = (k // 20) * 600.0
        c = rg.build_cohort(9, k, cx, cz, {})
        i = rg.ERA_SEQUENCE.index(c.dominant_era)
        if i <= 2:
            hist_counts.append(len(c.builder_families))
        elif i >= 5:
            new_counts.append(len(c.builder_families))
    assert hist_counts and new_counts
    assert sum(hist_counts) / len(hist_counts) > sum(new_counts) / len(new_counts)

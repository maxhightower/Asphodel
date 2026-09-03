"""Shared synthetic fixtures for the residential-architecture test suite.

No compiled Houston bundle is available in CI, so these build footprints ->
BuildingRecords -> ResidentialArchitectureV1 through the real compile stages
(buildings_grammar + residential_grammar), which is exactly the authority path
the mission specifies.
"""
from __future__ import annotations

from shapely.geometry import Polygon

from asphodel.world_source import buildings_grammar, residential_grammar
from asphodel.world_source.records import Parcel
from asphodel.world_source.schema import Feature


def rect(cx, cz, w, d):
    return [[(cx - w / 2, cz - d / 2), (cx + w / 2, cz - d / 2),
             (cx + w / 2, cz + d / 2), (cx - w / 2, cz + d / 2)]]


def lshape(cx, cz, w, d):
    return [[(cx, cz), (cx + w, cz), (cx + w, cz + d * 0.5),
             (cx + w * 0.5, cz + d * 0.5), (cx + w * 0.5, cz + d), (cx, cz + d)]]


def ushape(cx, cz, w, d):
    # thin arms + a deep central notch so the footprint reads as strongly winged
    # (low rectangularity, high concavity) — a genuine U-plan.
    a = w * 0.22
    return [[(cx, cz), (cx + w, cz), (cx + w, cz + d), (cx + w - a, cz + d),
             (cx + w - a, cz + a), (cx + a, cz + a), (cx + a, cz + d), (cx, cz + d)]]


def feature(key, geom, props=None):
    p = dict(props or {})
    p.setdefault("subtype", "residential")
    p.setdefault("_area", Polygon(geom[0]).area)
    return Feature(stable_key=key, geometry=geom, geom_type="polygon",
                   properties=p, source="test", source_id=key)


def compile_block(features, seed=42, lat=29.76, lon=-95.36, block_poly=None):
    """Compile a set of house features that all sit in ONE block/parcel; returns
    (records, cohort_stats)."""
    bids = list(range(len(features)))
    if block_poly is None:
        block_poly = Polygon([(-20, -20), (400, -20), (400, 400), (-20, 400)])
    parcels = [Parcel(pid="p:0:blk", poly=block_poly, arch="RESIDENTIAL",
                      obs="DERIVED", block_id=0, building_bids=bids)]
    recs = buildings_grammar.compile_buildings(features, parcels, segments=[], seed=seed)
    props_by_bid = {i: f.properties for i, f in enumerate(features)}
    stats = residential_grammar.assign_architecture(
        recs, parcels, [block_poly], seed, lat=lat, lon=lon,
        props_by_bid=props_by_bid)
    return recs, stats


def make_cohort(style, form=None, era="1960_1979"):
    """A one-family cohort forced to a single style, for style-grammar tests."""
    g = residential_grammar.STYLE_GRAMMAR[style]
    form = form or g["forms"][0]
    fam = dict(id=0, style=style, form=form, story=g["story"][0],
               roof_family=g["roof"][0][0], porch_family=g["porch"][0][0],
               porch_support=g["supports"][0][0], parking=g["parking"][0][0],
               foundation=g["foundation"][0][0], package_idx=0, share=1.0)
    return residential_grammar.Cohort(
        cohort_id=0, dominant_era=era, secondary_era=era,
        primary_forms=(form,), primary_styles=[(style, 1)],
        secondary_styles=[(style, 1)], builder_families=[fam],
        infill_probability=0.0, renovation_pressure=0.0)


def house_inputs(key, geom, obs_floors=None, obs_year=None, bid=0):
    return residential_grammar.HouseInputs(
        bid=bid, key=key,
        morph=residential_grammar.compute_morphology(Polygon(geom[0])),
        obs_floors=obs_floors, obs_year=obs_year)

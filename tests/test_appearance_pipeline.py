"""Package B gate: observed building appearance survives acquisition -> grammar
-> chunk serialization end-to-end, unchanged and correctly provenanced, with no
renderer/compiler substitution."""
from __future__ import annotations

from asphodel.world_source import appearance as appear
from asphodel.world_source import buildings_grammar, chunks
from asphodel.world_source.chunkgrid import ChunkGrid, CHUNK_SIZE_M, CELLS_PER_CHUNK
from asphodel.world_source.schema import Feature


def _square(cx, cz, s=6.0):
    return [[(cx - s, cz - s), (cx + s, cz - s), (cx + s, cz + s), (cx - s, cz + s)]]


def _feature(key, cx, cz, props):
    p = dict(props)
    p.setdefault("_area", 144.0)
    return Feature(stable_key=key, geometry=_square(cx, cz), geom_type="polygon",
                   properties=p, source="test/buildings/building", source_id=key)


OBSERVED_PROPS = {
    "height_m": 6.0, "levels": 2,
    "facade_color": "#666666", "facade_material": "brick",
    "roof_color": "#0000FF", "roof_material": "concrete", "roof_shape": "gabled",
}


def test_bridge_marks_observed_and_normalizes():
    a = appear.build_appearance(0, OBSERVED_PROPS, "flat", 6.0, True).to_dict()
    assert a["facade"]["color"] == {"value": "#666666", "class": "OBSERVED"}
    assert a["facade"]["material"] == {"value": "brick", "class": "OBSERVED"}
    assert a["roof"]["color"] == {"value": "#0000ff", "class": "OBSERVED"}
    # concrete roof material normalizes to roof_generic, still OBSERVED
    assert a["roof"]["material"] == {"value": "roof_generic", "class": "OBSERVED"}
    assert a["roof"]["shape"] == {"value": "gabled", "class": "OBSERVED"}
    assert a["height_m"] == {"value": 6.0, "class": "OBSERVED"}


def test_absent_appearance_is_not_observed():
    a = appear.build_appearance(0, {"height_m": None}, "flat", None, False).to_dict()
    assert a["facade"]["color"]["value"] is None
    assert a["facade"]["color"]["class"] == "PROCEDURAL"
    assert a["roof"]["shape"]["class"] == "DERIVED"     # grammar-derived flat
    assert a["height_m"]["class"] == "DERIVED"


def test_observed_survives_grammar_to_chunk_unchanged():
    feats = [_feature("obs", 40.0, 40.0, OBSERVED_PROPS),
             _feature("bare", 80.0, 80.0, {"height_m": 4.0})]
    recs = buildings_grammar.compile_buildings(feats, parcels=[], segments=[], seed=7)
    assert len(recs) == 2
    obs = next(r for r in recs if r.key == "obs")
    assert obs.appearance["facade"]["color"] == {"value": "#666666", "class": "OBSERVED"}

    grid = ChunkGrid(min_x=0.0, min_z=0.0, max_x=CHUNK_SIZE_M, max_z=CHUNK_SIZE_M)
    rasters = {(0, 0): bytes(CELLS_PER_CHUNK * CELLS_PER_CHUNK)}
    out = chunks.build_chunks(grid, rasters, segments=[], parcels=[],
                              buildings=recs, placements=[], anchors=[])
    bdicts = out[(0, 0)]["buildings"]
    by_bid = {b["bid"]: b for b in bdicts}
    obs_b = by_bid[obs.bid]
    # observed values reach the chunk unchanged, still labelled OBSERVED
    assert obs_b["appearance"]["facade"]["color"] == {"value": "#666666", "class": "OBSERVED"}
    assert obs_b["appearance"]["roof"]["color"]["value"] == "#0000ff"
    # the bare building carries appearance too, but nothing claims OBSERVED colour
    bare = next(r for r in recs if r.key == "bare")
    bare_b = by_bid[bare.bid]
    assert bare_b["appearance"]["facade"]["color"]["value"] is None
    assert bare_b["appearance"]["facade"]["color"]["class"] != "OBSERVED"

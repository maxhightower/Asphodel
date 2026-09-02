"""Package D gate: every prop the grammar can place resolves through
AssetCatalogV1 to a supported procedural render kind (no unknown/magenta
fallback), and the Godot JSON twin matches the Python catalog."""
from __future__ import annotations

import json
import os

from asphodel.city_visual import AssetCatalogV1
from asphodel.world_source import grammar_tables as g

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Kinds PropMeshes has an explicit builder for (mirror of SUPPORTED_KINDS in
# godot/scripts/prop_meshes.gd; the Godot smoke test checks the GDScript side).
PROP_MESHES_SUPPORTED = {
    "mailbox", "garbage_bin", "recycling_bin", "fire_hydrant", "utility_pole",
    "streetlight", "traffic_sign", "traffic_signal", "guardrail", "bollard",
    "transformer_box", "utility_cabinet", "ac_condenser", "rooftop_hvac",
    "dumpster", "parking_stop", "bench", "bus_shelter", "wood_fence",
    "chainlink_fence", "pallet", "road_barrier",
    "sedan", "suv", "pickup", "van", "box_truck",
    "tree_round", "tree_oak", "tree_conical", "tree_columnar", "tree_palm",
    "tree_willow", "bush_round", "bush_low",
}


def _grammar_kinds():
    return (set(g.PROP_KINDS) | set(g.VEHICLE_KINDS) | set(g.TREE_KINDS)
            | set(g.BUSH_KINDS))


def test_catalog_covers_every_grammar_kind():
    cat = AssetCatalogV1.load()
    render_kinds = {f.render_kind for f in cat.families.values() if f.render_kind}
    missing = _grammar_kinds() - render_kinds
    assert not missing, f"grammar kinds absent from catalog: {sorted(missing)}"


def test_every_grammar_kind_has_a_propmeshes_builder():
    missing = _grammar_kinds() - PROP_MESHES_SUPPORTED
    assert not missing, f"grammar kinds with no PropMeshes builder: {sorted(missing)}"


def test_catalog_render_kinds_are_all_supported_or_interior():
    """Every outdoor family's render kind must have a PropMeshes builder; interior
    families (drawn by interior_builder, Package F) are exempt."""
    cat = AssetCatalogV1.load()
    offenders = []
    for f in cat.families.values():
        if f.outdoor and f.render_kind and f.render_kind not in PROP_MESHES_SUPPORTED:
            offenders.append(f.semantic_id)
    assert not offenders, f"outdoor families with unsupported render kind: {offenders}"


def test_render_variants_map_matches_families():
    cat = AssetCatalogV1.load()
    doc = json.load(open(os.path.join(REPO, "asphodel", "city_visual", "catalog_v1.json")))
    rv = doc["render_variants"]
    for f in cat.families.values():
        if f.render_kind:
            assert rv.get(f.render_kind, 0) >= len(f.variants), \
                f"render_variants[{f.render_kind}] < family {f.semantic_id} variants"


def test_godot_json_twin_matches_python_catalog():
    a = json.load(open(os.path.join(REPO, "asphodel", "city_visual", "catalog_v1.json")))
    b = json.load(open(os.path.join(REPO, "godot", "catalog_v1.json")))
    assert a == b, "godot/catalog_v1.json drifted from the Python catalog; rerun build_catalog_v1.py"


def test_street_families_have_multiple_variants():
    """The mission's intent: repeated street props should not be identical."""
    cat = AssetCatalogV1.load()
    for sid in ("mailbox_suburban", "garbage_bin", "streetlight", "bench",
                "fire_hydrant", "bollard", "dumpster", "utility_cabinet"):
        assert len(cat.get(sid).variants) >= 2, f"{sid} has no variety"

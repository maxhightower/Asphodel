#!/usr/bin/env python3
"""Generate asphodel/city_visual/catalog_v1.yaml from the current vocabulary.

Seeds AssetCatalogV1 with semantic families wrapping the existing procedural
mesh kinds (prop_meshes.gd) and interior fixture/decor kinds (interiors.py).
Every V1 variant is backed by a procedural fallback since no authored .glb
assets exist yet; later packages add `resource:` variants without changing the
contract. Run:  python tools/build_catalog_v1.py
"""
from __future__ import annotations

import os
import yaml

# (semantic_id, category, procedural_kind, dims(w,d,h), placement, outdoor,
#  collision, interaction, material_family, tags dict, extra_variants)
# tags dict keys: room/parcel/building/climate
F = []


def fam(sid, cat, proc, dims, placement="ground", outdoor=True, collision="simple",
        interaction="none", material=None, room=(), parcel=(), building=(),
        climate=(), variants=1, lod=None):
    w, d, h = dims
    vlist = []
    for i in range(variants):
        vlist.append({"id": f"{sid}_{i:02d}", "weight": 1.0, "resource": None,
                      "procedural": proc, "conditions": ["NORMAL"]})
    F.append({
        "semantic_id": sid, "category": cat, "placement": placement,
        "outdoor": outdoor, "dimensions": {"width_m": w, "depth_m": d, "height_m": h},
        "clearance": {}, "collision": collision, "interaction": interaction,
        "material_family": material, "room_tags": list(room),
        "parcel_tags": list(parcel), "building_tags": list(building),
        "climate_tags": list(climate), "seed_tag": sid,
        "lod_fallback": lod or proc, "variants": vlist,
    })


# ---- utility / infrastructure -------------------------------------------------
fam("utility_pole", "utility", "utility_pole", (0.4, 0.4, 8.0), interaction="none")
fam("utility_cabinet", "utility", "utility_cabinet", (0.9, 0.5, 1.3))
fam("transformer_box", "utility", "transformer_box", (1.2, 1.0, 1.1))
fam("electrical_meter", "utility", "utility_cabinet", (0.4, 0.2, 0.5))       # planned art; falls back
fam("telecom_box", "utility", "utility_cabinet", (0.8, 0.4, 1.0))
fam("ac_condenser", "utility", "ac_condenser", (0.9, 0.9, 0.8), building=("residential",))
fam("rooftop_hvac", "utility", "rooftop_hvac", (1.8, 1.4, 1.0), placement="roof",
    building=("commercial", "industrial"))
fam("fire_hydrant", "utility", "fire_hydrant", (0.3, 0.3, 0.8))

# ---- street furniture ---------------------------------------------------------
fam("streetlight", "street_furniture", "streetlight", (0.3, 0.3, 7.0))
fam("traffic_sign", "street_furniture", "traffic_sign", (0.6, 0.1, 2.4))
fam("traffic_signal", "street_furniture", "traffic_signal", (0.4, 0.4, 5.5))
fam("bollard", "street_furniture", "bollard", (0.2, 0.2, 0.9))
fam("bench", "street_furniture", "bench", (1.6, 0.5, 0.8), interaction="sit")
fam("bus_shelter", "street_furniture", "bus_shelter", (3.0, 1.2, 2.4))
fam("parking_stop", "street_furniture", "parking_stop", (1.8, 0.15, 0.15))
fam("parking_meter", "street_furniture", "bollard", (0.2, 0.2, 1.2))          # planned art
fam("bike_rack", "street_furniture", "bollard", (1.6, 0.1, 0.8))              # planned art
fam("trash_can_public", "street_furniture", "garbage_bin", (0.5, 0.5, 1.0))
fam("newspaper_box", "street_furniture", "utility_cabinet", (0.4, 0.5, 1.2))  # planned art

# ---- residential exterior -----------------------------------------------------
fam("mailbox_suburban", "residential", "mailbox", (0.4, 0.2, 1.2),
    parcel=("residential",))
fam("garbage_bin", "residential", "garbage_bin", (0.6, 0.6, 1.1), parcel=("residential",))
fam("recycling_bin", "residential", "recycling_bin", (0.6, 0.6, 1.1), parcel=("residential",))
fam("wood_fence", "residential", "wood_fence", (2.0, 0.2, 1.3), collision="simple",
    parcel=("residential",))
fam("chainlink_fence", "residential", "chainlink_fence", (2.0, 0.1, 1.8))

# ---- commercial / industrial exterior ----------------------------------------
fam("dumpster", "commercial_equipment", "dumpster", (1.8, 1.2, 1.4),
    building=("commercial", "industrial"))
fam("pallet", "commercial_equipment", "pallet", (1.2, 1.0, 0.15), building=("industrial",))
fam("road_barrier", "infrastructure", "road_barrier", (1.5, 0.5, 0.8))
fam("guardrail", "infrastructure", "guardrail", (2.0, 0.1, 0.7))

# ---- vehicles (5 baked colour variants each) ----------------------------------
for v in ("sedan", "suv", "pickup", "van", "box_truck"):
    dims = {"sedan": (2.0, 4.6, 1.5), "suv": (2.1, 4.8, 1.8),
            "pickup": (2.1, 5.4, 1.8), "van": (2.2, 5.2, 2.2),
            "box_truck": (2.5, 7.0, 3.2)}[v]
    fam(f"vehicle_{v}", "vehicle", v, dims, collision="mesh", variants=5)

# ---- vegetation (regional families; ages via scale at placement) --------------
fam("live_oak", "vegetation", "tree_oak", (12.0, 12.0, 10.0), collision="none",
    climate=("gulf", "south_central"), variants=5)
fam("street_tree_round", "vegetation", "tree_round", (6.0, 6.0, 7.0), collision="none",
    variants=5)
fam("conifer", "vegetation", "tree_conical", (4.0, 4.0, 9.0), collision="none",
    climate=("temperate",), variants=5)
fam("columnar_tree", "vegetation", "tree_columnar", (2.5, 2.5, 9.0), collision="none",
    variants=5)
fam("palm", "vegetation", "tree_palm", (5.0, 5.0, 9.0), collision="none",
    climate=("gulf", "subtropical"), variants=5)
fam("shrub_round", "vegetation", "bush_round", (1.4, 1.4, 1.2), collision="none",
    variants=5)
fam("shrub_low", "vegetation", "bush_low", (1.6, 1.6, 0.7), collision="none",
    variants=5)

# ---- interior authoritative fixtures (searchable containers) ------------------
fam("storage_cabinet", "furniture", "cabinet", (0.9, 0.5, 0.9), placement="floor",
    outdoor=False, interaction="search", room=("kitchen", "office", "supply"))
fam("refrigerator", "furniture", "fridge", (0.8, 0.7, 1.8), placement="floor",
    outdoor=False, interaction="search", room=("kitchen", "break_room"))
fam("shelf_unit", "furniture", "shelf", (1.0, 0.4, 1.8), placement="floor",
    outdoor=False, interaction="search", room=("storeroom", "back_room", "supply", "shop"))
fam("dresser", "furniture", "dresser", (1.1, 0.5, 0.8), placement="floor",
    outdoor=False, interaction="search", room=("bedroom",))
fam("desk", "furniture", "desk", (1.4, 0.7, 0.75), placement="floor", outdoor=False,
    interaction="work_at_desk", room=("office", "open_office", "bedroom"))
fam("counter", "furniture", "counter", (2.0, 0.6, 0.9), placement="floor", outdoor=False,
    interaction="search", room=("kitchen", "shop", "break_room"))
fam("crate", "furniture", "crate", (0.8, 0.8, 0.8), placement="floor", outdoor=False,
    interaction="search", room=("storeroom", "back_room", "supply"))

# ---- interior decorative furniture (no container) -----------------------------
fam("sofa", "furniture", "sofa", (2.0, 0.9, 0.8), placement="floor", outdoor=False,
    interaction="sit", room=("living",))
fam("armchair", "furniture", "armchair", (0.9, 0.9, 0.9), placement="floor",
    outdoor=False, interaction="sit", room=("living",))
fam("coffee_table", "furniture", "coffee_table", (1.1, 0.6, 0.4), placement="floor",
    outdoor=False, room=("living",))
fam("television", "furniture", "tv", (1.2, 0.1, 0.7), placement="floor", outdoor=False,
    room=("living", "break_room"))
fam("bookshelf", "furniture", "bookshelf", (1.0, 0.35, 1.9), placement="floor",
    outdoor=False, room=("living", "office"))
fam("bed_double", "furniture", "bed", (1.6, 2.0, 0.6), placement="floor", outdoor=False,
    interaction="sleep", room=("bedroom", "exam"))
fam("dining_table", "furniture", "table", (1.6, 0.9, 0.75), placement="floor",
    outdoor=False, room=("kitchen", "break_room"))
fam("chair_dining", "furniture", "chair", (0.45, 0.45, 0.9), placement="floor",
    outdoor=False, interaction="sit", room=("kitchen", "break_room", "office"))
fam("stove", "furniture", "stove", (0.75, 0.65, 0.9), placement="floor", outdoor=False,
    interaction="cook", room=("kitchen",))
fam("stool", "furniture", "stool", (0.4, 0.4, 0.8), placement="floor", outdoor=False,
    interaction="sit", room=("exam", "shop"))
fam("retail_rack", "commercial_equipment", "rack", (1.2, 0.5, 1.8), placement="floor",
    outdoor=False, interaction="stock_shelf", room=("shop",))
fam("retail_display", "commercial_equipment", "display", (1.0, 1.0, 1.0),
    placement="floor", outdoor=False, room=("shop",))


def main():
    out = os.path.join(os.path.dirname(__file__), "..", "asphodel", "city_visual",
                       "catalog_v1.yaml")
    doc = {"version": 1,
           "note": "AssetCatalogV1 seed: semantic families over existing procedural"
                   " meshes. V1 variants are procedural fallbacks; add resource:"
                   " authored assets in later packages.",
           "families": F}
    with open(out, "w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False, width=100)
    print(f"wrote {os.path.normpath(out)} with {len(F)} families")


if __name__ == "__main__":
    main()

"""Bake a population of spawnable citizens into a city bundle.

The citizens are generated from the **same resolved world the game renders**: a
canonical ``StreetMap`` reconstructed from the bundle's own blocks + roads (or,
at OSM-ingest time, from the parsed OSM buildings). So a Houston citizen lives
and works in Houston's actual building stock and geography -- not an abstract
"generic/capital/harbor/university" profile shared across every city -- and their
home/work coordinates are in the bundle's metre frame, ready for Godot to place
them physically.

Each record carries:

* authoritative spatial data (``home_xy`` / ``work_xy`` / ``spawn_xy`` +
  ``spawn_context``) so the player spawns at the citizen's real circumstance;
* a *context-resolved* collapse situation (via ``resolve_collapse_situation``),
  so the signature agrees with where the citizen actually is (a truck driver
  asleep at home is not "driving a loaded truck on the motorway"); and
* **scoped** possessions -- only genuine on-person items are "On hand"; the
  job's workplace/vehicle kit is held in its own scope, not the player's pocket.

Deterministic in ``seed``. No game-engine or network dependency.
"""
from __future__ import annotations

import json
import os

from ..citizen import (
    CityProfile, CityWorld, CitizenSpawnCatalog, default_catalog,
    spawn_population_in_world, resolve_collapse_situation, _current_block,
)
from ..world import StreetMap
from .world_from_osm import street_map_from_bundle, street_map_from_osm

# Retained for back-compat with callers/tests that still ask for the abstract
# archetype set; the *real-city* path below no longer uses it.
DEFAULT_PROFILES = ["generic", "capital", "harbor", "university"]

_FIRST = ["Maria", "James", "Aisha", "Wei", "Carlos", "Nadia", "Tom", "Priya",
          "Diego", "Sara", "Omar", "Grace", "Leo", "Hana", "Ruth", "Andre"]
_LAST = ["Reyes", "Okafor", "Nguyen", "Patel", "Johnson", "Khan", "Garcia",
         "Mensah", "Silva", "Brooks", "Costa", "Ahmed", "Rivera", "Park",
         "Cohen", "Diallo"]

# Item kinds that are genuinely carried on the person regardless of occupation.
# Everything else in an occupation's starting kit is workplace/vehicle gear and
# must NOT show up in the player's immediate "On hand" inventory.
_PERSONAL_ITEMS = {
    "phone", "wallet", "keys", "cash", "water_bottle", "snack", "face_mask",
    "transit_pass", "id_card", "id_badge", "badge", "id_tag", "name_tag",
    "reading_glasses", "medication", "sunglasses", "backpack", "shopping_bag",
}


def _name_for(citizen_id: int, tag: str) -> str:
    """Deterministic display name (Python's hash() is salted, so derive our own)."""
    base = citizen_id * 1000 + sum(ord(ch) for ch in tag)
    return f"{_FIRST[base % len(_FIRST)]} {_LAST[(base // len(_FIRST)) % len(_LAST)]}"


def _xy(pt):
    return None if pt is None else [round(float(pt[0]), 2), round(float(pt[1]), 2)]


def _scope_inventory(citizen) -> dict:
    """Partition a citizen's possessions into on-person / workplace / vehicle / home.

    Personal items are always on the person. Occupation kit is on-person only
    when the citizen is actually at work; while commuting it rides in the
    vehicle; otherwise it sits back at the workplace. "On hand" == on_person.
    """
    scopes = {"on_person": {}, "home": {}, "workplace": {}, "vehicle": {}}
    activity = citizen.current_activity
    for item, n in citizen.inventory.items():
        if item in _PERSONAL_ITEMS:
            scopes["on_person"][item] = n
        elif activity == "work":
            scopes["on_person"][item] = n          # holding your tools on shift
        elif activity == "commute":
            scopes["vehicle"][item] = n            # in transit with you
        else:
            scopes["workplace"][item] = n          # left at the job
    return scopes


def _commute_frac(citizen) -> float:
    block = _current_block(citizen.schedule, citizen.spawn_hour)
    frac = 0.5
    if block is not None and block.end_hour > block.start_hour:
        h = citizen.spawn_hour
        if block.end_hour > 24.0 and h < block.start_hour:
            h += 24.0
        frac = min(1.0, max(0.0, (h - block.start_hour)
                            / (block.end_hour - block.start_hour)))
    return frac


def _spawn_point(citizen, context: str, anchors=None):
    """The authoritative (x, z) the player enters the world at, per context.

    With compiled spawn anchors (cities carrying world/ data):
    * workplace/home -> the building's compiled BUILDING_ENTRANCE anchor
      (immediately outside the entrance on valid pedestrian ground);
    * commute -> the routed position along the road graph at the commute's
      schedule progress (straight-line interpolation retired);
    * errand -> the nearest pedestrian anchor to home.

    Without anchors (legacy cities), the historical behaviour is kept:
    building centroids and the straight-line commute approximation.
    Returns (xy_list_or_None, approx_bool, anchor_kind).
    """
    home, work = citizen.home_xy, citizen.work_xy
    if anchors is not None:
        if context == "workplace" and work is not None:
            ent = anchors.entrance(citizen.work_building_id)
            if ent is not None:
                return _xy(ent), False, "entrance"
            walk = anchors.nearest_walk_anchor(work)
            if walk is not None and (walk[0] - work[0]) ** 2 \
                    + (walk[1] - work[1]) ** 2 <= 200.0 ** 2:
                return _xy(walk), True, "walk"
            return _xy(work), True, "fallback"
        if context == "commute" and home is not None and work is not None:
            xy, approx = anchors.commute_point(home, work, _commute_frac(citizen))
            return _xy(xy), approx, ("route" if not approx else "fallback")
        if home is not None:
            ent = anchors.entrance(citizen.home_building_id)
            if context == "errand":
                walk = anchors.nearest_walk_anchor(ent or home)
                if walk is not None:
                    return _xy(walk), False, "walk"
            if ent is not None:
                return _xy(ent), False, "entrance"
            return _xy(home), True, "fallback"
        return None, True, "fallback"

    if context == "workplace" and work is not None:
        return _xy(work), False, "legacy"
    if context == "commute" and home is not None and work is not None:
        frac = _commute_frac(citizen)
        x = home[0] + (work[0] - home[0]) * frac
        z = home[1] + (work[1] - home[1]) * frac
        return _xy((x, z)), True, "legacy"         # straight-line approximation
    approx = context == "errand"
    return _xy(home), approx, "legacy"


def _flatten(tag: str, citizen, catalog: CitizenSpawnCatalog,
             world: CityWorld | None, anchors=None) -> dict:
    """Render one citizen to a JSON-ready dict, with a context-coherent situation."""
    # Resolve the collapse where the citizen actually is *now* (spawn_hour), with
    # the random aerial/ambient layers off so the character-screen signature is
    # the deterministic, context-true outcome.
    situ = resolve_collapse_situation(
        citizen, collapse_hour=citizen.spawn_hour, world=world,
        aerial_prob=0.0, ambient_prob=0.0)
    scopes = _scope_inventory(citizen)
    spawn_xy, spawn_approx, spawn_anchor = _spawn_point(
        citizen, situ.context, anchors=anchors)
    return {
        "profile": tag,
        "name": _name_for(citizen.citizen_id, tag),
        "age": int(citizen.age),
        "occupation": citizen.occupation,
        "shift": citizen.shift,
        "home_district": citizen.home_district,
        "work_district": citizen.work_district or "",
        "spawn_hour": round(float(citizen.spawn_hour), 2),
        "current_activity": citizen.current_activity,
        "current_location": citizen.current_location,
        # "On hand" is on-person only; other scopes are separate.
        "inventory": dict(scopes["on_person"]),
        "inventory_scopes": scopes,
        # Authoritative spatial data (bundle metre frame) + explicit building
        # identity (index into buildings.json == authoritative building_id), so
        # "which building is home" is stored, never re-derived by proximity.
        "home_xy": _xy(citizen.home_xy),
        "work_xy": _xy(citizen.work_xy),
        "home_building_id": (None if citizen.home_building_id is None
                             else int(citizen.home_building_id)),
        "work_building_id": (None if citizen.work_building_id is None
                             else int(citizen.work_building_id)),
        "spawn_xy": spawn_xy,
        "spawn_context": situ.context,             # home | workplace | commute | errand
        "spawn_approx": spawn_approx,
        "spawn_anchor": spawn_anchor,              # entrance|route|walk|legacy|fallback
        # Context-resolved collapse situation (agrees with activity/location).
        "signature_title": situ.title,
        "signature_location": situ.location,
        "signature_situation": situ.narrative,
        "signature_dilemma": situ.dilemma,
        "situation_kind": situ.kind,               # signature | travel | generic ...
        "on_duty": bool(situ.on_duty),
        "environment": situ.environment,
    }


# ===========================================================================
# Real-city citizen population (the canonical path Godot bundles use)
# ===========================================================================
def build_population_from_world(street_map: StreetMap, city_name: str,
                                n: int = 60, seed: int = 0,
                                catalog: CitizenSpawnCatalog | None = None,
                                anchors=None) -> list[dict]:
    """Spawn ``n`` citizens into a resolved ``StreetMap`` and flatten them.

    This is the single canonical baker: whether the ``StreetMap`` came from live
    OSM or from a committed bundle's blocks, citizens are real buildings of the
    actual city, with coherent situations and scoped possessions.
    """
    catalog = catalog or default_catalog()
    profile = CityProfile(name=city_name)
    world = CityWorld(profile=profile, street_map=street_map)
    pop = spawn_population_in_world(world, catalog, n=n, seed=seed)
    return [_flatten(city_name, c, catalog, world, anchors=anchors)
            for c in pop]


def build_population_from_compiled(bundle_dir: str, city_name: str,
                                   n: int = 60, seed: int = 0) -> list[dict]:
    """Bake citizens against a *compiled* world bundle (world/ data).

    The StreetMap comes from the regenerated buildings.json (index ==
    authoritative building_id) + full road graph, and spawns land on
    compiled spawn anchors: home/work at building entrances, commutes
    routed along the road graph.
    """
    from .world_from_compiled import SpawnAnchors, street_map_from_compiled
    sm = street_map_from_compiled(bundle_dir)
    anchors = SpawnAnchors(bundle_dir, sm)
    return build_population_from_world(sm, city_name, n=n, seed=seed,
                                       anchors=anchors)


def build_population_from_bundle(zones, roads, city_name: str,
                                 n: int = 60, seed: int = 0) -> list[dict]:
    """Rebuild the city's world from a committed bundle and spawn citizens offline."""
    sm = street_map_from_bundle(zones, roads, seed=seed)
    return build_population_from_world(sm, city_name, n=n, seed=seed)


def build_population_from_osm(bbox, buildings, roads, city_name: str,
                             n: int = 60, seed: int = 0) -> list[dict]:
    """Spawn citizens against freshly-parsed OSM buildings/roads (ingest time)."""
    sm = street_map_from_osm(bbox, buildings, roads, source=f"osm:{city_name}")
    return build_population_from_world(sm, city_name, n=n, seed=seed)


def write_citizens_from_bundle(bundle_dir: str, city_name: str,
                               n: int = 60, seed: int = 0) -> int:
    """(Re)bake real-city citizens and write citizens.json.

    Cities with compiled world data use the compiled path (real building
    stock + spawn anchors); legacy bundles keep the historical
    zones-blocks reconstruction.
    """
    from .world_from_compiled import has_compiled_world, street_map_from_compiled
    if has_compiled_world(bundle_dir):
        pop = build_population_from_compiled(bundle_dir, city_name, n=n,
                                             seed=seed)
        return _write(bundle_dir, pop)
    if os.path.exists(os.path.join(bundle_dir, "buildings.json")):
        # Canonical footprints without a compiled world/ stream (a synthetic
        # city): citizens still live in buildings.json entries, so their
        # home/work_building_id is the same identity Godot renders — never
        # the decorative zone blocks.
        sm = street_map_from_compiled(bundle_dir)
        pop = build_population_from_world(sm, city_name, n=n, seed=seed)
        return _write(bundle_dir, pop)
    with open(os.path.join(bundle_dir, "zones.json")) as f:
        zones = json.load(f)
    with open(os.path.join(bundle_dir, "roads.json")) as f:
        roads = json.load(f)
    pop = build_population_from_bundle(zones, roads, city_name, n=n, seed=seed)
    return _write(bundle_dir, pop)


def _write(bundle_dir: str, pop: list[dict]) -> int:
    os.makedirs(bundle_dir, exist_ok=True)
    path = os.path.join(bundle_dir, "citizens.json")
    with open(path, "w") as f:
        json.dump(pop, f, indent=2, sort_keys=True)
        f.write("\n")
    return len(pop)

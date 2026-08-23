"""Fetch + parse OSM data for a bbox via the Overpass API.

Uses `out geom;` so each way carries its node geometry inline (no separate node
resolution). Raw responses are cached by query hash for offline replay and fast
tests. Network access is injectable.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

from . import OSMError

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Asphodel/0.1 (research prototype; https://github.com/maxhightower/Asphodel)"

# Every drivable/walkable street class we bake into the bundle. Streets are the
# skeleton of the playable world, so residential + service roads matter as much
# as motorways.
_HIGHWAYS = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "living_street|service|pedestrian"
)


def build_query(bbox) -> str:
    """Overpass QL for streets + building footprints inside `bbox` (s,w,n,e)."""
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    return (
        "[out:json][timeout:120];"
        "("
        f'way["building"]({box});'
        f'way["highway"~"^({_HIGHWAYS})$"]({box});'
        ");"
        "out geom;"
    )


def _default_fetch(query: str) -> str:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8")


def _fetch_with_retry(query: str, fetch, retries: int) -> str:
    last = None
    for attempt in range(retries):
        try:
            return fetch(query)
        except Exception as exc:  # network/timeout/429 -> backoff and retry
            last = exc
            time.sleep(2 ** attempt)
    raise OSMError(f"Overpass request failed after {retries} attempts: {last}")


def fetch_osm(bbox, cache_dir=None, fetch=_default_fetch, retries: int = 3) -> dict:
    """Return the parsed Overpass JSON dict for `bbox`, using a disk cache if given."""
    query = build_query(bbox)
    path = None
    if cache_dir:
        key = hashlib.sha1(query.encode("utf-8")).hexdigest()
        path = os.path.join(cache_dir, f"{key}.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raw = _fetch_with_retry(query, fetch, retries)
    data = json.loads(raw)
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    return data


def _parse_levels(tags: dict) -> int:
    try:
        return max(1, int(float(tags.get("building:levels", 1))))
    except (TypeError, ValueError):
        return 1


def _parse_height_m(tags: dict):
    """Explicit building height in meters, or None (strips a trailing ' m')."""
    raw = tags.get("height", tags.get("building:height"))
    if raw is None:
        return None
    try:
        return max(2.5, float(str(raw).strip().removesuffix("m").strip()))
    except (TypeError, ValueError):
        return None


# building=* values mapped to the gameplay "kind" the interior generator keys
# off of. Anything unlisted falls through to amenity/shop or "generic".
_BUILDING_KINDS = {
    "house": "house", "detached": "house", "semidetached_house": "house",
    "bungalow": "house", "cabin": "house", "residential": "house",
    "apartments": "apartments", "dormitory": "apartments", "terrace": "apartments",
    "retail": "shop", "supermarket": "shop", "kiosk": "shop",
    "commercial": "commercial", "office": "office",
    "industrial": "industrial", "warehouse": "industrial",
    "school": "school", "university": "school", "kindergarten": "school",
    "hospital": "hospital",
    "church": "civic", "chapel": "civic", "cathedral": "civic",
    "civic": "civic", "public": "civic", "government": "civic",
    "garage": "garage", "garages": "garage", "carport": "garage",
    "shed": "garage", "barn": "garage", "hut": "garage",
    "hotel": "hotel",
}

_AMENITY_KINDS = {
    "restaurant": "restaurant", "fast_food": "restaurant", "cafe": "restaurant",
    "bar": "restaurant", "pub": "restaurant",
    "pharmacy": "pharmacy", "hospital": "hospital", "clinic": "hospital",
    "doctors": "hospital",
    "school": "school", "library": "civic", "townhall": "civic",
    "police": "civic", "fire_station": "civic", "place_of_worship": "civic",
    "bank": "office", "fuel": "shop",
}


def classify_building(tags: dict) -> str:
    """Gameplay kind for a building way, from its OSM tags."""
    if tags.get("amenity") in _AMENITY_KINDS:
        return _AMENITY_KINDS[tags["amenity"]]
    if "shop" in tags:
        return "shop"
    return _BUILDING_KINDS.get(tags.get("building", ""), "generic")


def parse_osm(data: dict):
    """Split Overpass elements into (buildings, roads).

    buildings: [{"ring": [(lat,lon),...], "levels": int, "kind": str,
                 "height_m": float|None, "name": str}]
    roads:     [{"class": str, "points": [(lat,lon),...]}]
    """
    buildings, roads = [], []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        pts = [(g["lat"], g["lon"]) for g in geom]
        tags = el.get("tags", {})
        if "building" in tags:
            buildings.append({
                "ring": pts,
                "levels": _parse_levels(tags),
                "kind": classify_building(tags),
                "height_m": _parse_height_m(tags),
                "name": tags.get("name", ""),
            })
        elif "highway" in tags:
            roads.append({"class": tags["highway"], "points": pts})
    return buildings, roads

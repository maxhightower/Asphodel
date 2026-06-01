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

_MAJOR_HIGHWAYS = "motorway|trunk|primary|secondary"


def build_query(bbox) -> str:
    """Overpass QL for major roads + building footprints inside `bbox` (s,w,n,e)."""
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    return (
        "[out:json][timeout:60];"
        "("
        f'way["building"]({box});'
        f'way["highway"~"^({_MAJOR_HIGHWAYS})$"]({box});'
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


def parse_osm(data: dict):
    """Split Overpass elements into (buildings, roads).

    buildings: [{"ring": [(lat,lon),...], "levels": int}]
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
            buildings.append({"ring": pts, "levels": _parse_levels(tags)})
        elif "highway" in tags:
            roads.append({"class": tags["highway"], "points": pts})
    return buildings, roads

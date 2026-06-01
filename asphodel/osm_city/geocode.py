"""City name -> bounding box via the Nominatim (OSM) geocoder.

Network access goes through an injectable `fetch(url) -> str` so tests run
offline. Oversized bounding boxes are capped (centered) so a query like "Texas"
can't ask Overpass for a whole state.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import CityNotFound

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Asphodel/0.1 (research prototype; https://github.com/maxhightower/Asphodel)"


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _cap_bbox(bbox, max_span_deg: float):
    """Clamp each span to `max_span_deg`, keeping the center fixed."""
    s, w, n, e = bbox
    lat_span = n - s
    lon_span = e - w
    if lat_span <= max_span_deg and lon_span <= max_span_deg:
        return bbox
    lat_c, lon_c = (s + n) / 2.0, (w + e) / 2.0
    lat_half = min(lat_span / 2.0, max_span_deg / 2.0)
    lon_half = min(lon_span / 2.0, max_span_deg / 2.0)
    return (lat_c - lat_half, lon_c - lon_half, lat_c + lat_half, lon_c + lon_half)


def geocode(query: str, fetch=_default_fetch, max_span_deg: float = 0.5):
    """Return a capped bbox `(south, west, north, east)` for `query`.

    Raises CityNotFound if Nominatim returns no match.
    """
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    raw = fetch(f"{NOMINATIM_URL}?{params}")
    data = json.loads(raw)
    if not data:
        raise CityNotFound(query)
    # Nominatim order: [south, north, west, east].
    south, north, west, east = (float(v) for v in data[0]["boundingbox"])
    return _cap_bbox((south, west, north, east), max_span_deg)

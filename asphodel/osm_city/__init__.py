"""OSM -> Asphodel city bundle pipeline (Phase 1).

Turns a city name into a bundle (zone graph + density-weighted population +
roads + a precomputed belief-cascade timeline) consumed by the Godot frontend.
All network I/O is injectable so the pipeline is testable offline.
"""


class OSMError(Exception):
    """Base error for the OSM city pipeline."""


class CityNotFound(OSMError):
    """Geocoding returned no match for the requested city."""

    def __init__(self, query: str):
        super().__init__(f"No city found for query: {query!r}")
        self.query = query

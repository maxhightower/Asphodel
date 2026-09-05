"""Authoritative geographic frame for Asphodel (AS-REGION-0, §2.1, §13).

There is exactly ONE geographic truth in Asphodel and it lives here. Every other
system — detailed city, regional terrain, mobility graph, physics realization —
derives its coordinates from a :class:`GeoReference`. Three coordinate frames are
defined and the conversions between them are the only sanctioned way to move a
position between systems:

    GEOGRAPHIC          REGIONAL (projected)        LOCAL (runtime / render)
    lat, lon, elev  <->  x east, z north metres  <->  x', z' after floating-origin
                         about the geo origin          rebasing

The projection is the same equirectangular model the city pipeline already uses
(:func:`asphodel.osm_city.geometry.project`); this module makes it invertible,
attaches an explicit origin/elevation/CRS, and adds the floating-origin machinery
a 100+ km regional world needs so Godot never has to hold enormous absolute
coordinates (§13).

Pure stdlib, deterministic, dependency-free — trivially unit-testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Tuple

# Kept identical to asphodel.osm_city.geometry so the detailed city and the
# regional terrain share one projection and align exactly (tested in §17.1).
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]


@dataclass(frozen=True)
class GeoReference:
    """The single authoritative geographic frame.

    ``origin_lat/lon`` is the projection tangent point (typically the detailed
    city's bbox centre). ``regional_origin`` is the offset, in regional projected
    metres, of that city origin *within* the wider regional projected space — it
    lets a regional bundle place several cities in one frame without re-projecting
    (for V1 it is (0, 0): the city origin *is* the regional origin).
    """

    origin_lat: float
    origin_lon: float
    origin_elevation: float = 0.0
    projected_crs: str = "equirectangular"
    regional_origin: Vec2 = (0.0, 0.0)

    # ---- geographic <-> regional projected -----------------------------------
    def project(self, lat: float, lon: float) -> Vec2:
        """(lat, lon) -> (x east, z north) regional projected metres."""
        x = (lon - self.origin_lon) * M_PER_DEG_LON * math.cos(
            math.radians(self.origin_lat)
        )
        z = (lat - self.origin_lat) * M_PER_DEG_LAT
        return (x + self.regional_origin[0], z + self.regional_origin[1])

    def unproject(self, x: float, z: float) -> Vec2:
        """(x, z) regional projected metres -> (lat, lon). Inverse of project()."""
        xr = x - self.regional_origin[0]
        zr = z - self.regional_origin[1]
        lon = self.origin_lon + xr / (
            M_PER_DEG_LON * math.cos(math.radians(self.origin_lat))
        )
        lat = self.origin_lat + zr / M_PER_DEG_LAT
        return (lat, lon)

    def project3(self, lat: float, lon: float, elevation: float) -> Vec3:
        """(lat, lon, elev) -> (x, y up, z) regional metres. y is height AMSL
        relative to the origin elevation."""
        x, z = self.project(lat, lon)
        return (x, elevation - self.origin_elevation, z)

    # ---- serialization -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "origin_lat": self.origin_lat,
            "origin_lon": self.origin_lon,
            "origin_elevation": self.origin_elevation,
            "projected_crs": self.projected_crs,
            "regional_origin": list(self.regional_origin),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GeoReference":
        ro = d.get("regional_origin", (0.0, 0.0))
        return cls(
            origin_lat=float(d["origin_lat"]),
            origin_lon=float(d["origin_lon"]),
            origin_elevation=float(d.get("origin_elevation", 0.0)),
            projected_crs=str(d.get("projected_crs", "equirectangular")),
            regional_origin=(float(ro[0]), float(ro[1])),
        )

    @classmethod
    def from_bundle_meta(cls, meta: dict) -> "GeoReference":
        """Build the frame a legacy city bundle implies.

        The bundle already projects roads/zones about ``center`` = [lat, lon];
        this recovers the exact same origin so new regional data lands in the
        same local metres the existing geometry already uses.
        """
        center = meta["center"]
        return cls(
            origin_lat=float(center[0]),
            origin_lon=float(center[1]),
            origin_elevation=float(meta.get("origin_elevation", 0.0)),
            projected_crs=str(meta.get("projection", "equirectangular")),
        )


@dataclass
class FloatingOrigin:
    """Keeps runtime/render coordinates small in a very large world (§13).

    Godot loses float precision past a few tens of km from the origin. We keep a
    running ``shift`` (the regional-space position that currently maps to render
    origin) and rebase it toward the focus (camera/player) whenever it drifts past
    ``threshold``. Rebasing changes render coordinates but NEVER changes an
    entity's semantic (regional/global) position — that invariant is the whole
    point and is asserted in the tests (§17.4).

    Rebasing is deterministic: the shift always snaps to a whole multiple of
    ``quantum`` so repeated runs from the same focus path produce identical
    shifts (no accumulated float drift), and chunk alignment is preserved.
    """

    shift: Vec3 = (0.0, 0.0, 0.0)
    threshold: float = 4000.0
    quantum: float = 1000.0
    rebase_count: int = 0

    def to_render(self, global_pos: Vec3) -> Vec3:
        """Regional/global position -> render position (small numbers)."""
        return (
            global_pos[0] - self.shift[0],
            global_pos[1] - self.shift[1],
            global_pos[2] - self.shift[2],
        )

    def to_global(self, render_pos: Vec3) -> Vec3:
        """Render position -> regional/global position (the semantic truth)."""
        return (
            render_pos[0] + self.shift[0],
            render_pos[1] + self.shift[1],
            render_pos[2] + self.shift[2],
        )

    def maybe_rebase(self, focus_global: Vec3) -> Vec3:
        """Rebase if the focus has drifted too far from the current render origin.

        Returns the delta applied to ``shift`` (0,0,0 if no rebase happened).
        Callers add this delta-subtraction to every live render transform so the
        world visually holds still while the numbers shrink.
        """
        render_focus = self.to_render(focus_global)
        if max(abs(render_focus[0]), abs(render_focus[2])) < self.threshold:
            return (0.0, 0.0, 0.0)
        # Snap the new shift to the quantum grid nearest the focus (deterministic).
        new_shift = (
            _snap(focus_global[0], self.quantum),
            0.0,  # keep vertical unshifted; terrain elevations stay modest
            _snap(focus_global[2], self.quantum),
        )
        delta = (
            new_shift[0] - self.shift[0],
            new_shift[1] - self.shift[1],
            new_shift[2] - self.shift[2],
        )
        self.shift = new_shift
        self.rebase_count += 1
        return delta


def _snap(v: float, q: float) -> float:
    return round(v / q) * q


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres — a truth check for the flat projection."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

"""Elevation providers + region archetypes (AS-REGION-0, §3.1, §3.5).

Design rules from the brief:

* External acquisition (real DEM tiles) happens OUTSIDE runtime. The game renders
  a compiled bundle with NO network. So the provider interface separates
  ``sample`` (cheap, offline, runtime-safe) from acquisition (an offline bake
  step). :class:`USGS3DEPProvider` is the real-DEM seam and deliberately refuses
  to hit the network at runtime.
* Geographic identity is data, not code. A flat coastal city and a mountain-front
  city differ because they carry different :class:`TerrainArchetype` values —
  there is no ``if city == "Denver"`` anywhere (§21 DON'T). Plains archetypes have
  NO mountain component, so flat cities do not get a fake mountain ring (§3.5).
* When real elevation is unavailable, the synthetic fallback still encodes the
  region's true macro form (base elevation, relief, mountain front, coastline)
  so terrain communicates geography — not generic noise everywhere.

All sampling is in the projected LOCAL-metre frame of a :class:`GeoReference`
(x east, z north), returning elevation in metres above mean sea level.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from ..geo import GeoReference
from . import noise


# --------------------------------------------------------------------------- #
# Region archetypes — the geographic identity, as data.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TerrainArchetype:
    """Macro geographic form of a region. Composed by the synthetic provider."""

    name: str
    base_elevation: float          # m AMSL at the geo origin
    plain_relief: float            # amplitude of gentle rolling relief (m)
    feature_km: float = 6.0        # horizontal scale of that relief (km)
    # Mountain front (None -> genuinely no mountains, e.g. a coastal plain):
    mountain_relief: float = 0.0   # additional ridged amplitude (m)
    mountain_dir: Optional[Sequence[float]] = None  # unit (x,z) the range rises toward
    mountain_onset_km: float = 20.0    # distance from origin where the front begins
    mountain_rampin_km: float = 30.0   # distance over which it ramps to full height
    mountain_km: float = 18.0          # horizontal scale of the ridges
    # Coastline (None -> landlocked):
    sea_level: Optional[float] = None      # m AMSL of the water plane
    coast_dir: Optional[Sequence[float]] = None  # unit (x,z) toward open water
    coast_onset_km: float = 30.0           # where land starts dropping to the sea
    coast_slope: float = 0.002             # m drop per m toward the coast
    # Land-cover hints (used by landcover.py):
    forest_fraction: float = 0.25
    arid: bool = False

    def relief_span(self) -> float:
        """Rough peak-to-trough relief this archetype can produce (for gating)."""
        return 2.0 * self.plain_relief + self.mountain_relief


# A small, extensible catalogue. Cities map to one of these by passing the name
# through at bake time (data-driven), never by hard-coded name dispatch in logic.
ARCHETYPES: dict[str, TerrainArchetype] = {
    # Gulf coastal plain: near sea level, almost no relief, ocean to the SE.
    "coastal_plain": TerrainArchetype(
        name="coastal_plain",
        base_elevation=15.0,
        plain_relief=6.0,
        feature_km=8.0,
        mountain_relief=0.0,
        mountain_dir=None,
        sea_level=0.0,
        coast_dir=(0.55, -0.83),   # south-south-east
        coast_onset_km=35.0,
        coast_slope=0.0006,
        forest_fraction=0.30,
    ),
    # High plains meeting a mountain front to the west (Front Range style).
    "mountain_front": TerrainArchetype(
        name="mountain_front",
        base_elevation=1600.0,
        plain_relief=35.0,
        feature_km=7.0,
        mountain_relief=1900.0,
        mountain_dir=(-1.0, 0.0),  # mountains rise to the west
        mountain_onset_km=14.0,
        mountain_rampin_km=26.0,
        mountain_km=16.0,
        sea_level=None,
        forest_fraction=0.45,
        arid=True,
    ),
    # A city built right against the mountain front (Boulder / the Flatirons):
    # the range rises within ~2 km of downtown, not tens of km away.
    "front_range_adjacent": TerrainArchetype(
        name="front_range_adjacent",
        base_elevation=1655.0,
        plain_relief=22.0,
        feature_km=5.0,
        mountain_relief=2600.0,
        mountain_dir=(-1.0, 0.0),   # mountains rise immediately to the west
        mountain_onset_km=1.0,
        mountain_rampin_km=4.0,
        mountain_km=5.0,
        sea_level=None,
        forest_fraction=0.50,
        arid=False,
    ),
    # Generic inland rolling country (default fallback).
    "rolling_inland": TerrainArchetype(
        name="rolling_inland",
        base_elevation=200.0,
        plain_relief=25.0,
        feature_km=6.0,
        forest_fraction=0.35,
    ),
}


def archetype_for(name: Optional[str]) -> TerrainArchetype:
    """Resolve an archetype by name, defaulting to rolling inland country."""
    if name and name in ARCHETYPES:
        return ARCHETYPES[name]
    return ARCHETYPES["rolling_inland"]


# --------------------------------------------------------------------------- #
# Provider interface + implementations.
# --------------------------------------------------------------------------- #
class ElevationProvider:
    """Samples elevation (m AMSL) at projected local-metre coordinates.

    ``sample(x, z)`` accepts scalars or numpy arrays and must be pure and offline.
    ``provenance()`` records where the data came from for the bundle manifest.
    """

    def sample(self, x, z):  # pragma: no cover - abstract
        raise NotImplementedError

    def provenance(self) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def metadata(self) -> dict:
        return self.provenance()


class SyntheticElevationProvider(ElevationProvider):
    """Deterministic archetype-driven terrain — the offline fallback (§3.1).

    Not "decorative noise": the archetype fixes base elevation, relief, an
    optional mountain front (only where one really exists), and an optional
    coastline, so the terrain reads as the real region's form. Detail comes from
    seed-stable fBm/ridged noise.
    """

    def __init__(self, georef: GeoReference, archetype: TerrainArchetype,
                 seed: int = 0):
        self.georef = georef
        self.arch = archetype
        self.seed = int(seed)

    def sample(self, x, z):
        x = np.asarray(x, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        a = self.arch
        elev = np.full(np.broadcast(x, z).shape, a.base_elevation, dtype=np.float64)

        # Gentle rolling relief everywhere.
        fscale = 1.0 / (a.feature_km * 1000.0)
        roll = noise.fbm(x * fscale, z * fscale, seed=self.seed, octaves=5)
        elev = elev + a.plain_relief * (roll - 0.5) * 2.0

        # Mountain front: only along the archetype's direction, ramped by distance.
        if a.mountain_relief > 0.0 and a.mountain_dir is not None:
            d = np.asarray(a.mountain_dir, dtype=np.float64)
            d = d / (np.linalg.norm(d) or 1.0)
            along = x * d[0] + z * d[1]  # metres toward the range
            onset = a.mountain_onset_km * 1000.0
            ramp = np.clip((along - onset) / (a.mountain_rampin_km * 1000.0), 0.0, 1.0)
            ramp = ramp * ramp * (3.0 - 2.0 * ramp)  # smoothstep in
            mscale = 1.0 / (a.mountain_km * 1000.0)
            ridge = noise.ridged(x * mscale, z * mscale, seed=self.seed + 77, octaves=6)
            elev = elev + a.mountain_relief * ramp * ridge

        # Coastline: land drops toward open water; below sea level becomes seabed.
        if a.sea_level is not None and a.coast_dir is not None:
            d = np.asarray(a.coast_dir, dtype=np.float64)
            d = d / (np.linalg.norm(d) or 1.0)
            toward = x * d[0] + z * d[1]
            onset = a.coast_onset_km * 1000.0
            drop = np.clip(toward - onset, 0.0, None) * a.coast_slope
            elev = elev - drop

        return elev if elev.shape else float(elev)

    def water_level(self) -> Optional[float]:
        return self.arch.sea_level

    def provenance(self) -> dict:
        return {
            "source": "synthetic",
            "archetype": self.arch.name,
            "seed": self.seed,
            "note": "offline deterministic fallback; encodes archetype macro-form",
        }


class CachedDEMProvider(ElevationProvider):
    """Serves a baked heightmap artifact (the runtime path once terrain is baked).

    ``heightmap`` is a 2-D array of elevations AMSL sampled on a regular grid over
    ``[x0, z0]`` (SW corner) with ``step_m`` spacing. Bilinear interpolation; edge
    clamped. This is what a compiled bundle ships — no network, no procedural cost.
    """

    def __init__(self, heightmap: np.ndarray, x0: float, z0: float, step_m: float,
                 provenance: Optional[dict] = None):
        self.h = np.asarray(heightmap, dtype=np.float64)
        self.x0 = float(x0)
        self.z0 = float(z0)
        self.step = float(step_m)
        self._prov = provenance or {"source": "cached_dem"}

    def sample(self, x, z):
        x = np.asarray(x, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        rows, cols = self.h.shape
        fx = np.clip((x - self.x0) / self.step, 0.0, cols - 1.0000001)
        fz = np.clip((z - self.z0) / self.step, 0.0, rows - 1.0000001)
        ix = np.floor(fx).astype(np.int64)
        iz = np.floor(fz).astype(np.int64)
        tx = fx - ix
        tz = fz - iz
        h00 = self.h[iz, ix]
        h10 = self.h[iz, ix + 1]
        h01 = self.h[iz + 1, ix]
        h11 = self.h[iz + 1, ix + 1]
        a = h00 + (h10 - h00) * tx
        b = h01 + (h11 - h01) * tx
        out = a + (b - a) * tz
        return out if out.shape else float(out)

    def provenance(self) -> dict:
        return dict(self._prov)


class USGS3DEPProvider(ElevationProvider):
    """Seam for real USGS 3DEP DEM ingestion (§3.1). ACQUISITION IS OFFLINE.

    At runtime this must never touch the network (the compiled game runs offline).
    A bake tool would call an ``acquire()`` step to download and cache tiles, then
    ship a :class:`CachedDEMProvider`. Sampling here without a prior offline
    acquisition raises loudly rather than silently faking data — the same
    "fail loud, don't stub silently" discipline as world.load_osm.
    """

    def __init__(self, georef: GeoReference, cache: Optional[CachedDEMProvider] = None):
        self.georef = georef
        self.cache = cache

    def acquire(self, *args, **kwargs):  # pragma: no cover - offline bake seam
        raise NotImplementedError(
            "USGS 3DEP acquisition is an offline bake step (network). "
            "Wire an ElevationProvider.acquire implementation that downloads and "
            "caches tiles, then serve them via CachedDEMProvider."
        )

    def sample(self, x, z):
        if self.cache is None:
            raise RuntimeError(
                "USGS3DEPProvider has no cached tiles; runtime is offline. "
                "Run the offline acquisition/bake first, then use CachedDEMProvider."
            )
        return self.cache.sample(x, z)

    def provenance(self) -> dict:
        if self.cache is not None:
            p = self.cache.provenance()
            p.setdefault("source", "usgs_3dep")
            return p
        return {"source": "usgs_3dep", "status": "not_acquired"}


class FallbackDEMProvider(ElevationProvider):
    """Try providers in order; use the first that samples without error (§3.1).

    The intended chain is ``USGS3DEP -> Cached -> Synthetic`` so a bundle degrades
    gracefully to the archetype fallback when no real DEM was acquired, and the
    game still renders offline.
    """

    def __init__(self, providers: Sequence[ElevationProvider]):
        if not providers:
            raise ValueError("FallbackDEMProvider needs at least one provider")
        self.providers = list(providers)
        self._active: Optional[ElevationProvider] = None

    def _pick(self) -> ElevationProvider:
        if self._active is not None:
            return self._active
        last_err: Optional[Exception] = None
        for p in self.providers:
            try:
                p.sample(0.0, 0.0)
                self._active = p
                return p
            except Exception as e:  # noqa: BLE001 - graceful degradation is the point
                last_err = e
        raise RuntimeError(f"no elevation provider usable: {last_err}")

    def sample(self, x, z):
        return self._pick().sample(x, z)

    def provenance(self) -> dict:
        p = self._pick().provenance()
        p["chain"] = [type(x).__name__ for x in self.providers]
        return p

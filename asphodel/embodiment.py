"""Physical citizen embodiment (Package 2): the authoritative spatial identity of
an *identified* citizen — where, in the same coordinate/building system Godot
renders, that person actually is.

The governing principle (from the milestone brief):

    A citizen must never simultaneously exist in contradictory locations. There
    must be **one canonical physical interpretation** of "where is citizen N".

That interpretation lives here. It is a **pure, deterministic, RNG-free function**
of a citizen's schedule, home/work coordinates, the in-game hour, and their
current behaviour label (``chosen_action``). It reads an optional
:class:`CitySpatialContext` (building centroids + road vertices + zone centres +
map bbox, loaded once from a committed bundle) to resolve real buildings, snap a
commuter onto a real road, and pick a valid shelter/flee destination.

Why this design keeps the certified invariants intact
-----------------------------------------------------
* **Calibration-neutral by construction.** Nothing here consumes an
  ``AgentZone.rng`` draw or mutates ``pos``/``state``/any compartment. Embodiment
  is *derived*, exactly like the M2 activity label — so the epidemic curve is
  bit-identical whether embodiment is computed or not (milestone embodiment test
  #7). The macro float ledger stays the population authority.
* **Deterministic.** Every "choice" (which shelter, which flee direction, how far
  along a commute) is a pure function of stable inputs (citizen id, coordinates,
  hour, action, static bundle geometry). Same city + citizen + seed + time ⇒ same
  authoritative physical location (test #1). It therefore survives
  promote→demote→re-promote and save/load automatically, because it is a function
  of state that already persists (tests #5, #6, #10).
* **Attention-scaled.** Only *identified* citizens (the bounded promoted/roster
  set) are resolved to this fidelity; anonymous statistical fill is never routed.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

from .citizen import _current_block


# Bump on any breaking change to the PhysicalLocation shape. The wire snapshot
# and any renderer key off this contract.
LOCATION_SCHEMA_VERSION = 1


class LocationMode:
    """How a citizen physically occupies space this instant (stable strings)."""

    OUTDOORS = "outdoors"     # in the open, not on a mapped road (parks, yards)
    STREET = "street"         # on / beside a real road segment
    BUILDING = "building"     # at a building footprint (home/work/shelter/errand)
    INTERIOR = "interior"     # inside a building's interior representation


class Movement:
    """The citizen's movement state this instant."""

    STATIONARY = "stationary"
    WALKING = "walking"       # moving on foot toward a destination
    COMMUTING = "commuting"   # travelling home<->work along the road network


@dataclass
class PhysicalLocation:
    """The one canonical physical interpretation of an embodied citizen.

    Coordinates ``x``/``y`` are **metres in the bundle/Godot map frame** — the
    same frame ``home_xy``/``work_xy`` and building polygons live in — so a
    renderer can place the citizen directly, no re-projection.
    """

    version: int
    citizen_id: int
    zone: int
    x: float
    y: float
    mode: str                       # LocationMode
    building_id: int                # -1 when not at a building
    activity: str                   # schedule activity ("work"/"sleep"/...)
    action: str                     # behaviour label ("continue_schedule"/"shelter"/...)
    movement: str                   # Movement
    destination_x: Optional[float] = None
    destination_y: Optional[float] = None
    route_frac: float = 0.0         # 0..1 progress along a commute block

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# City spatial context: static geometry loaded once from a committed bundle
# --------------------------------------------------------------------------- #
def _poly_centroid(poly: list) -> tuple[float, float]:
    """Area-weighted centroid of a simple polygon (falls back to vertex mean for
    degenerate/zero-area polys). Deterministic."""
    pts = np.asarray(poly, dtype=float)
    if pts.shape[0] < 3:
        return (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
    x = pts[:, 0]
    y = pts[:, 1]
    x1 = np.roll(x, -1)
    y1 = np.roll(y, -1)
    cross = x * y1 - x1 * y
    a = cross.sum() / 2.0
    if abs(a) < 1e-9:
        return (float(x.mean()), float(y.mean()))
    cx = ((x + x1) * cross).sum() / (6.0 * a)
    cy = ((y + y1) * cross).sum() / (6.0 * a)
    return (float(cx), float(cy))


BUILDINGS_SCHEMA_VERSION = 1


def validate_buildings_doc(doc, where: str = "buildings.json") -> list:
    """Return the building list of a CANONICAL ``buildings.json`` or raise.

    The one accepted shape (Gate A) is ``{"version": 1, "buildings": [{"poly":
    [[x, z], ...], "height": m, ...}, ...]}``; ``key``/``arch``/``cat`` are
    optional extras the compiled cities add. A bare list (the retired synth
    generator's output) or any other version fails loudly here instead of
    misplacing every citizen later. ``None`` (file absent) returns ``[]``.
    """
    if doc is None:
        return []
    if not isinstance(doc, dict):
        raise ValueError(f"{where}: not a canonical buildings document "
                         f"(expected an object, got {type(doc).__name__})")
    if doc.get("version") != BUILDINGS_SCHEMA_VERSION:
        raise ValueError(f"{where}: unsupported buildings schema version "
                         f"{doc.get('version')!r} (expected {BUILDINGS_SCHEMA_VERSION})")
    blist = doc.get("buildings")
    if not isinstance(blist, list):
        raise ValueError(f"{where}: 'buildings' is not a list")
    for i, b in enumerate(blist[:3] + blist[-1:] if blist else []):
        if not isinstance(b, dict) or not isinstance(b.get("poly"), list) \
                or "height" not in b:
            raise ValueError(f"{where}: building record {i} lacks poly/height")
    return blist


class CitySpatialContext:
    """Static, read-only geometry for one city bundle.

    Precomputes building centroids, a flat array of road vertices (for cheap
    nearest-road snapping without full pathfinding), zone centres, and the map
    bbox. All queries are pure and deterministic; nothing here is ever mutated by
    the simulation.
    """

    def __init__(self, *, building_centroids: np.ndarray, road_vertices: np.ndarray,
                 zone_ids: np.ndarray, zone_centers: np.ndarray,
                 bbox: Optional[tuple] = None, name: str = "", cell_m: float = 0.0,
                 building_polys: Optional[list] = None,
                 building_heights: Optional[list] = None,
                 building_archs: Optional[list] = None):
        self.name = name
        self.building_centroids = building_centroids       # (B, 2) or (0, 2)
        # Full footprint polygons + heights, index-aligned with building_centroids
        # (== building_id). Kept for interior generation (Package: walk-in
        # interiors); None-safe for older callers.
        self.building_polys = building_polys or []         # list[list[[x,y]]]
        self.building_heights = building_heights or []     # list[float]
        self.building_archs = building_archs or []         # list[str] exterior arch
        self.road_vertices = road_vertices                 # (V, 2) or (0, 2)
        self.zone_ids = zone_ids                           # (Z,)
        self.zone_centers = zone_centers                   # (Z, 2)
        self.bbox = bbox                                   # (xmin, ymin, xmax, ymax)
        self.cell_m = float(cell_m)                        # macro grid cell size (m)
        if bbox is not None:
            self.center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        elif zone_centers.size:
            self.center = (float(zone_centers[:, 0].mean()),
                           float(zone_centers[:, 1].mean()))
        else:
            self.center = (0.0, 0.0)

    # -- construction --------------------------------------------------------
    @classmethod
    def from_bundle_dir(cls, bundle_dir: str) -> "CitySpatialContext":
        """Load a bundle's static geometry (buildings, roads, zones, bbox)."""
        def _load(name):
            path = os.path.join(bundle_dir, name)
            if not os.path.exists(path):
                return None
            with open(path) as f:
                return json.load(f)

        buildings_doc = _load("buildings.json")
        blist = validate_buildings_doc(buildings_doc, os.path.join(bundle_dir, "buildings.json"))
        if blist:
            centroids = np.array([_poly_centroid(b["poly"]) for b in blist], dtype=float)
            building_polys = [[[float(p[0]), float(p[1])] for p in b.get("poly", [])]
                              for b in blist]
            building_heights = [float(b.get("height", 6.0)) for b in blist]
            building_archs = [str(b.get("arch", "")) for b in blist]
        else:
            centroids = np.zeros((0, 2), dtype=float)
            building_polys = []
            building_heights = []
            building_archs = []

        roads_doc = _load("roads.json") or {}
        verts = []
        for pl in roads_doc.get("polylines", []):
            # A polyline is either a bare list of [x,y] points, or a dict
            # {"class": ..., "points": [[x,y], ...]}.
            pts = pl.get("points", []) if isinstance(pl, dict) else pl
            for pt in pts:
                verts.append((float(pt[0]), float(pt[1])))
        road_vertices = (np.array(verts, dtype=float) if verts
                         else np.zeros((0, 2), dtype=float))

        zones = _load("zones.json") or []
        zs = sorted(zones, key=lambda z: int(z["id"]))
        zone_ids = np.array([int(z["id"]) for z in zs], dtype=np.int64)
        zone_centers = (np.array([[float(z["center_xy"][0]), float(z["center_xy"][1])]
                                  for z in zs], dtype=float)
                        if zs else np.zeros((0, 2), dtype=float))

        meta = _load("meta.json") or {}
        cell_m = float(meta.get("grid", {}).get("cell_m", 0.0)) if meta else 0.0
        bbox = None
        # bundle bbox is geographic (lat/lon); the sim frame is metres. Derive the
        # metric bbox from the geometry we actually have instead.
        allpts = [p for p in (centroids, road_vertices, zone_centers) if p.size]
        if allpts:
            stacked = np.vstack(allpts)
            bbox = (float(stacked[:, 0].min()), float(stacked[:, 1].min()),
                    float(stacked[:, 0].max()), float(stacked[:, 1].max()))

        return cls(building_centroids=centroids, road_vertices=road_vertices,
                   zone_ids=zone_ids, zone_centers=zone_centers, bbox=bbox,
                   cell_m=cell_m, name=meta.get("name", os.path.basename(bundle_dir)),
                   building_polys=building_polys, building_heights=building_heights,
                   building_archs=building_archs)

    def building_arch(self, building_id: int) -> Optional[str]:
        """Exterior building archetype (BUILDING_ARCHETYPES member) or None."""
        if 0 <= building_id < len(self.building_archs):
            return self.building_archs[building_id] or None
        return None

    def building_poly(self, building_id: int):
        """Footprint polygon (list of [x,y]) for a building, or None."""
        if 0 <= building_id < len(self.building_polys):
            return self.building_polys[building_id]
        return None

    def building_height(self, building_id: int) -> float:
        if 0 <= building_id < len(self.building_heights):
            return self.building_heights[building_id]
        return 6.0

    def approx_world_xy(self, zone: int, local_xy, L: float) -> Optional[tuple]:
        """Map a promoted zone's torus-local position into approximate world
        metres, for **anonymous statistical fill only** (documented approximate
        mode — never authoritative). Centres the L×L torus on the zone centre and
        scales it to the macro cell. Returns None when the zone has no centre."""
        c = self.zone_center(zone)
        if c is None or L <= 0:
            return None
        span = self.cell_m if self.cell_m > 0 else L
        sx = (float(local_xy[0]) / L - 0.5) * span
        sy = (float(local_xy[1]) / L - 0.5) * span
        return (c[0] + sx, c[1] + sy)

    # -- queries -------------------------------------------------------------
    def nearest_building(self, xy) -> int:
        """Index (stable building id) of the building centroid nearest ``xy``,
        or -1 if the bundle has no buildings. Ties -> lowest index (argmin)."""
        if self.building_centroids.shape[0] == 0:
            return -1
        d2 = ((self.building_centroids[:, 0] - xy[0]) ** 2
              + (self.building_centroids[:, 1] - xy[1]) ** 2)
        return int(np.argmin(d2))

    def building_xy(self, building_id: int) -> Optional[tuple]:
        if 0 <= building_id < self.building_centroids.shape[0]:
            c = self.building_centroids[building_id]
            return (float(c[0]), float(c[1]))
        return None

    def nearest_road_xy(self, xy) -> Optional[tuple]:
        """Nearest road vertex to ``xy`` (snaps a point onto the real road
        network). None if the bundle has no roads."""
        if self.road_vertices.shape[0] == 0:
            return None
        d2 = ((self.road_vertices[:, 0] - xy[0]) ** 2
              + (self.road_vertices[:, 1] - xy[1]) ** 2)
        v = self.road_vertices[int(np.argmin(d2))]
        return (float(v[0]), float(v[1]))

    def distance_to_road(self, xy) -> float:
        r = self.nearest_road_xy(xy)
        if r is None:
            return float("inf")
        return math.hypot(xy[0] - r[0], xy[1] - r[1])

    def zone_center(self, zone: int) -> Optional[tuple]:
        if zone is None:
            return None
        hit = np.where(self.zone_ids == int(zone))[0]
        if hit.size == 0:
            return None
        c = self.zone_centers[hit[0]]
        return (float(c[0]), float(c[1]))


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
# Activities that anchor the citizen at their home building.
_HOME_ACTIVITIES = {"sleep", "leisure", "idle", ""}


def _anchor_home(home_xy, home_zone, ctx):
    if home_xy is not None:
        return tuple(home_xy)
    if ctx is not None:
        c = ctx.zone_center(home_zone)
        if c is not None:
            return c
    # Last-resort synthetic anchor: stable per zone (never rng).
    z = int(home_zone) if home_zone is not None else 0
    return (float(z * 37 % 1000), float(z * 53 % 1000))


def _anchor_work(work_xy, work_zone, home_anchor, ctx):
    if work_xy is not None:
        return tuple(work_xy)
    if ctx is not None:
        c = ctx.zone_center(work_zone)
        if c is not None:
            return c
    return home_anchor


def _commute_point(home_anchor, work_anchor, frac, ctx):
    """A point along the home<->work commute at fraction ``frac``, snapped onto
    the real road network when a context is available (so a commuter is on a real
    road, not a synthetic straight-line coordinate)."""
    lx = home_anchor[0] + (work_anchor[0] - home_anchor[0]) * frac
    ly = home_anchor[1] + (work_anchor[1] - home_anchor[1]) * frac
    if ctx is not None:
        snapped = ctx.nearest_road_xy((lx, ly))
        if snapped is not None:
            return snapped
    return (lx, ly)


def _flee_point(current, ctx):
    """A deterministic outward/safety destination: push from the map centre
    through the current position out toward the map edge, clamped to the bbox."""
    if ctx is None or ctx.bbox is None:
        # No geometry: nudge outward from origin deterministically.
        norm = math.hypot(current[0], current[1]) or 1.0
        return (current[0] + current[0] / norm * 200.0,
                current[1] + current[1] / norm * 200.0)
    cx, cy = ctx.center
    vx, vy = current[0] - cx, current[1] - cy
    norm = math.hypot(vx, vy) or 1.0
    xmin, ymin, xmax, ymax = ctx.bbox
    # March outward until we hit the bbox edge.
    reach = max(xmax - xmin, ymax - ymin)
    tx = current[0] + vx / norm * reach
    ty = current[1] + vy / norm * reach
    return (min(max(tx, xmin), xmax), min(max(ty, ymin), ymax))


def resolve_physical_location(*, citizen_id: int, schedule: list, hour: float,
                              home_xy=None, work_xy=None,
                              home_zone=None, work_zone=None,
                              action: str = "continue_schedule",
                              zone: Optional[int] = None,
                              ctx: Optional[CitySpatialContext] = None,
                              commute_hours: float = 0.5,
                              home_building_id: Optional[int] = None,
                              work_building_id: Optional[int] = None
                              ) -> PhysicalLocation:
    """The one canonical physical location for a citizen at ``hour``.

    Pure and deterministic — no RNG, no side effects. ``action`` is the citizen's
    reactive behaviour label; ``shelter``/``flee`` make the reaction *physically
    consequential* (they move the citizen), while routine actions follow the
    schedule. ``zone`` is the reported macro zone (falls back to ``home_zone``).

    Building identity: when the citizen record carries ``home_building_id`` /
    ``work_building_id`` (buildings.json index == authoritative building_id)
    those ARE the home/work buildings; the nearest-footprint lookup is only the
    fallback for records baked before identity was stored (Gate B).
    """
    def _bid(explicit, anchor):
        if explicit is not None and ctx is not None \
                and 0 <= int(explicit) < ctx.building_centroids.shape[0]:
            return int(explicit)
        return ctx.nearest_building(anchor) if ctx is not None else -1

    block = _current_block(schedule, hour % 24.0) if schedule else None
    activity = block.activity if block is not None else "idle"

    home_anchor = _anchor_home(home_xy, home_zone, ctx)
    work_anchor = _anchor_work(work_xy, work_zone, home_anchor, ctx)
    report_zone = int(zone if zone is not None
                      else (home_zone if home_zone is not None else -1))

    # --- 1. schedule-derived base location -------------------------------
    building_id = -1
    destination = None
    route_frac = 0.0
    if activity == "work":
        x, y = work_anchor
        mode = LocationMode.BUILDING
        movement = Movement.STATIONARY
        building_id = _bid(work_building_id, work_anchor)
    elif activity == "commute":
        # Progress through the commute block (handle past-midnight wrap).
        if block is not None and block.end_hour > block.start_hour:
            h = hour % 24.0
            if block.end_hour > 24.0 and h < block.start_hour:
                h += 24.0
            route_frac = min(1.0, max(0.0, (h - block.start_hour)
                                      / (block.end_hour - block.start_hour)))
        else:
            route_frac = 0.5
        # Direction: a "commute" block whose destination is work runs home->work;
        # one whose destination is home runs work->home. We infer from the block's
        # location label when present, else assume morning outbound.
        loc = (block.location if block is not None else "") or ""
        outbound = not any(t in loc.lower() for t in ("home", "h"))  # heuristic
        a, b = (home_anchor, work_anchor) if outbound else (work_anchor, home_anchor)
        x, y = _commute_point(a, b, route_frac, ctx)
        mode = LocationMode.STREET
        movement = Movement.COMMUTING
        destination = b
    elif activity == "errand":
        # Errand: nearest building to home that is not home itself (a local shop),
        # falling back to home when no context.
        if ctx is not None:
            bid = ctx.nearest_building(home_anchor)
            bxy = ctx.building_xy(bid)
            x, y = bxy if bxy is not None else home_anchor
            building_id = bid
        else:
            x, y = home_anchor
        mode = LocationMode.BUILDING
        movement = Movement.STATIONARY
    else:  # sleep / leisure / idle -> home
        x, y = home_anchor
        mode = LocationMode.BUILDING
        movement = Movement.STATIONARY
        building_id = _bid(home_building_id, home_anchor)

    # --- 2. reaction makes the behaviour physically consequential --------
    act = (action or "continue_schedule").lower()
    if act == "shelter":
        # Shelter at the nearest valid building to the current position (home
        # counts as a valid shelter; shelter-in-place if already at one).
        if ctx is not None:
            bid = ctx.nearest_building((x, y))
            bxy = ctx.building_xy(bid)
            if bxy is not None:
                destination = bxy
                # If we are already essentially there, we *are* sheltering.
                if math.hypot(x - bxy[0], y - bxy[1]) < 1.0:
                    x, y = bxy
                    movement = Movement.STATIONARY
                else:
                    movement = Movement.WALKING
                building_id = bid
        else:
            destination = home_anchor
            movement = Movement.WALKING
        mode = LocationMode.BUILDING
    elif act == "flee":
        dest = _flee_point((x, y), ctx)
        destination = dest
        # Move a bounded step toward the flee destination (deterministic), snapped
        # to a road so fleers stream along real streets.
        fx = x + (dest[0] - x) * 0.5
        fy = y + (dest[1] - y) * 0.5
        if ctx is not None:
            snapped = ctx.nearest_road_xy((fx, fy))
            if snapped is not None:
                fx, fy = snapped
        x, y = fx, fy
        mode = LocationMode.STREET
        movement = Movement.WALKING
        building_id = -1

    return PhysicalLocation(
        version=LOCATION_SCHEMA_VERSION, citizen_id=int(citizen_id),
        zone=report_zone, x=float(x), y=float(y), mode=mode,
        building_id=int(building_id), activity=activity, action=act,
        movement=movement,
        destination_x=(None if destination is None else float(destination[0])),
        destination_y=(None if destination is None else float(destination[1])),
        route_frac=float(route_frac))

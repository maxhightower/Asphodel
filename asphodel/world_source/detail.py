"""OW-MVP-5,6,7,8,9: parcel-detail exterior compiler stage.

Consumes compiled parcels (parcels.py), buildings (BuildingRecord) and road
segments (RoadSegment) and produces the PROCEDURAL layer of the exterior
world: ground-surface patches inside each parcel, driveways/walkways,
parking lots + stalls, per-building yard props, fences, vegetation, and
spawn anchors. Curb-parked vehicles along residential streets are compiled
separately (`curb_vehicles`) since they are keyed on road segments, not
parcels.

Determinism: every random decision draws from `DetRand(seed, key, tag)`
where `key` is a stable feature identity (parcel.pid, building bid, or a
segment/sample index derived from arc-length position along a stable road
key) -- never a Python list index or set/dict iteration position. Two
compiles with the same (parcels, buildings, segments, seed) must yield
byte-identical Placement/SurfacePatch/Anchor lists (up to floating point
formatting), and callers must not rely on the *order* of the returned lists
being anything other than "stable across identical input" (it is, because
we iterate parcels/buildings in their given list order, which is itself
required upstream to be deterministic -- see parcels.py/records.py docs).

Spec-ambiguity resolutions (see also inline notes at point of use):

  * "front_half"/"rear_half" of a parcel: split the parcel polygon in two
    by the line through the parcel centroid perpendicular to front_dir
    (the outward normal of the chosen frontage edge). This is a simple,
    always-available substitute for a nonexistent "official" halving rule.
  * Parking lot candidate region: intersect the open area (parcel minus
    building footprints) with the appropriate half (front for
    retail/office/medical/school, rear/side otherwise), buffer(-2) to keep
    the lot off property lines, and require area > 120 m^2 (per spec) after
    that shrink -- else skip the lot for this parcel entirely.
  * Stall layout: rows step across the *unrotated* bounding box of the lot
    in a frame rotated by the dominant angle from
    `geomutil.largest_rectangle_side`, back-rotating stall centers into
    world space. Stalls whose center is not `lot.buffer(-1)`-contained are
    dropped (keeps stalls off the lot edge without a full polygon-clip
    layout engine).
  * Rooftop HVAC (BUILDING_FEATURES `rooftop_hvac`): per the task's own
    resolution, NOT placed as ground/roof Placements here -- the renderer
    draws these directly from the building's `feat` list. This module does
    nothing with that feature tag.
  * "Rear wall" of a building: the footprint edge whose outward normal is
    most anti-parallel to the entrance edge's outward normal (i.e. the far
    side from the entrance). "Side wall": a footprint edge that is neither
    the entrance edge nor the rear edge, chosen deterministically as the
    longest such edge.
  * Fence gaps: for RESIDENTIAL, edges belonging to the frontage set are
    skipped outright (no fence there) and additionally any fence panel
    whose midpoint falls within 2m of a driveway strip is dropped. For
    INDUSTRIAL, a single 8m gate gap is centered on the longest frontage
    edge (falls back to the first boundary edge when the parcel has no
    recorded frontage).
  * Vegetation "near building perimeter preferred for RESIDENTIAL" bushes:
    sample points are drawn along `footprint.buffer(1.5).exterior` using
    arc-length position from a DetRand stream, then rejected if outside the
    parcel's open area or too close to another placement.
  * Coarse-grid fallback (open area > 100_000 m2, i.e. very large PARK/
    VACANT_OPEN parcels): sample on a 15 m grid instead of full rejection
    sampling; a cell's tree/bush probability is
    `min(1.0, density_per_100m2 * (15*15) / 100.0)`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from .detrand import DetRand
from .geomutil import largest_rectangle_side, ring_edges
from .grammar_tables import (
    BUSH_KINDS,
    PARCEL_DETAIL_GRAMMAR,
    TREE_KINDS,
)
from .records import Anchor, Placement, SurfacePatch

# ---------------------------------------------------------------------------
# Tunables (kept local; nothing here is part of the grammar-table contract)
# ---------------------------------------------------------------------------
_WALKWAY_W = 1.2
_WALKWAY_MAX_LEN = 40.0
_DRIVEWAY_W = 3.0
_STALL_W = 2.6
_STALL_D = 5.5
_AISLE_W = 7.0
_MAX_STALLS_PER_LOT = 400
_MAX_FENCE_PANELS = 200
_FENCE_SPACING = 2.0
_TREE_CAP_DEFAULT = 60
_TREE_CAP_PARK = 400
_COARSE_GRID_THRESHOLD = 100_000.0
_COARSE_GRID_STEP = 15.0

_TREE_WEIGHTS = [("tree_round", 5), ("tree_conical", 3), ("tree_columnar", 2)]
_BUSH_WEIGHTS = [(k, 1) for k in BUSH_KINDS]


@dataclass
class DetailResult:
    placements: list = field(default_factory=list)
    patches: list = field(default_factory=list)
    anchors: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _bump(stats: dict, key: str, n=1) -> None:
    stats[key] = stats.get(key, 0) + n


def entrance_anchors(buildings) -> list:
    """One BUILDING_ENTRANCE anchor per building record.

    Kept separate from `compile_detail` (which must not duplicate these) so
    an orchestrator can build the anchor table for buildings that have no
    resolved parcel at all.
    """
    out = []
    for b in buildings:
        x, z = b.entrance_xy
        out.append(Anchor("BUILDING_ENTRANCE", x, z, b.bid))
    return out


# ---------------------------------------------------------------------------
# Small geometry helpers local to this stage
# ---------------------------------------------------------------------------

def _as_polys(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if isinstance(geom, Polygon):
        return [geom]
    # GeometryCollection etc: keep polygonal parts only
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def _safe_diff(a, b):
    try:
        return a.difference(b)
    except Exception:
        return a


def _safe_buffer(geom, d):
    try:
        return geom.buffer(d)
    except Exception:
        return geom


def _longest_edge(edges):
    best, best_len = None, -1.0
    for p0, p1 in edges:
        ln = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if ln > best_len:
            best_len, best = ln, (p0, p1)
    return best


def _front_edge_and_dir(parcel):
    """Longest frontage segment + outward unit normal, or (None, None)."""
    if not parcel.frontage:
        return None, None
    p0, p1 = _longest_edge(parcel.frontage)
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dz) or 1.0
    nx, nz = -dz / ln, dx / ln
    mx, mz = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    probe = Point(mx + nx * 0.5, mz + nz * 0.5)
    if parcel.poly.contains(probe):
        nx, nz = -nx, -nz
    return (p0, p1), (nx, nz)


def _split_front_rear(parcel_poly, front_dir):
    """Split parcel into (front_half, rear_half) via a line through the
    centroid perpendicular to front_dir. Falls back to (whole, whole) if
    front_dir is unknown."""
    if front_dir is None:
        return parcel_poly, parcel_poly
    cx, cz = parcel_poly.centroid.x, parcel_poly.centroid.y
    nx, nz = front_dir
    # line direction perpendicular to the normal
    dx, dz = -nz, nx
    span = max(parcel_poly.bounds[2] - parcel_poly.bounds[0],
               parcel_poly.bounds[3] - parcel_poly.bounds[1]) * 2.0 + 10.0
    a = (cx - dx * span, cz - dz * span)
    b = (cx + dx * span, cz + dz * span)
    cutter = LineString([a, b]).buffer(1e-6)
    try:
        pieces = _as_polys(_safe_diff(parcel_poly, cutter))
    except Exception:
        pieces = [parcel_poly]
    if len(pieces) < 2:
        return parcel_poly, parcel_poly
    def side(poly):
        px, pz = poly.centroid.x - cx, poly.centroid.y - cz
        return px * nx + pz * nz
    pieces.sort(key=side, reverse=True)
    return pieces[0], pieces[-1]


def _rear_and_side_edges(building_poly, entrance_edge_idx):
    """Return (rear_edge, side_edge) as ((x0,z0),(x1,z1)) tuples."""
    edges = list(ring_edges(building_poly))
    if not edges:
        return None, None
    entrance_edge_idx = entrance_edge_idx % len(edges)
    ent_p0, ent_p1 = edges[entrance_edge_idx]
    edx, edz = ent_p1[0] - ent_p0[0], ent_p1[1] - ent_p0[1]
    eln = math.hypot(edx, edz) or 1.0
    enx, enz = -edz / eln, edx / eln
    mx, mz = (ent_p0[0] + ent_p1[0]) / 2.0, (ent_p0[1] + ent_p1[1]) / 2.0
    if building_poly.contains(Point(mx + enx * 0.5, mz + enz * 0.5)):
        enx, enz = -enx, -enz

    best_rear, best_dot = None, 2.0
    best_side, best_side_len = None, -1.0
    for i, (p0, p1) in enumerate(edges):
        if i == entrance_edge_idx:
            continue
        dx, dz = p1[0] - p0[0], p1[1] - p0[1]
        ln = math.hypot(dx, dz) or 1.0
        nx, nz = -dz / ln, dx / ln
        mmx, mmz = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
        if building_poly.contains(Point(mmx + nx * 0.5, mmz + nz * 0.5)):
            nx, nz = -nx, -nz
        dot = nx * enx + nz * enz  # -1 == directly opposite (rear)
        if dot < best_dot:
            best_dot, best_rear = dot, (p0, p1)
        if ln > best_side_len:
            best_side_len, best_side = ln, (p0, p1)
    if best_side is best_rear:
        # pick the next-longest distinct edge for "side"
        best_side, best_side_len = None, -1.0
        for i, (p0, p1) in enumerate(edges):
            if i == entrance_edge_idx or (p0, p1) == best_rear:
                continue
            dx, dz = p1[0] - p0[0], p1[1] - p0[1]
            ln = math.hypot(dx, dz)
            if ln > best_side_len:
                best_side_len, best_side = ln, (p0, p1)
    return best_rear, best_side


def _edge_outward_point(building_poly, edge, offset):
    p0, p1 = edge
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dz) or 1.0
    nx, nz = -dz / ln, dx / ln
    mx, mz = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    if building_poly.contains(Point(mx + nx * 0.5, mz + nz * 0.5)):
        nx, nz = -nx, -nz
    return (mx + nx * offset, mz + nz * offset), math.degrees(math.atan2(dx, dz))


def _heading_deg(dx, dz):
    return math.degrees(math.atan2(dx, dz))


# ---------------------------------------------------------------------------
# Per-parcel pipeline steps
# ---------------------------------------------------------------------------

def _ground_surface(parcel, building_polys, g, patches):
    open_area = parcel.poly
    if building_polys:
        buf_union = unary_union([bp.buffer(0.5) for bp in building_polys])
        open_area = _safe_diff(open_area, buf_union)
    if open_area.is_empty:
        return open_area
    surface = g["lawn_surface"]
    if parcel.arch == "PARK":
        surface = "MAINTAINED_GRASS"
    elif parcel.arch == "VACANT_OPEN":
        surface = "ROUGH_VEGETATION"
    patches.append(SurfacePatch(open_area, surface, 40))
    return open_area


def _walkway(seed, parcel, b, front_edge, patches, anchors,
             placements, stats):
    p0, p1 = front_edge
    line = LineString([p0, p1])
    ex, ez = b.entrance_xy
    t = line.project(Point(ex, ez))
    fx, fz = line.interpolate(t).coords[0]
    length = math.hypot(fx - ex, fz - ez)
    if length <= 0:
        return None
    if length > _WALKWAY_MAX_LEN:
        scale = _WALKWAY_MAX_LEN / length
        fx = ex + (fx - ex) * scale
        fz = ez + (fz - ez) * scale
        length = _WALKWAY_MAX_LEN
    walk_line = LineString([(ex, ez), (fx, fz)])
    strip = walk_line.buffer(_WALKWAY_W / 2.0, cap_style=2)
    strip = strip.intersection(parcel.poly)
    if not strip.is_empty:
        patches.append(SurfacePatch(strip, "SIDEWALK", 50))
    mx, mz = (ex + fx) / 2.0, (ez + fz) / 2.0
    anchors.append(Anchor("PEDESTRIAN_APPROACH", mx, mz))
    _bump(stats, "walkways")
    return (fx - ex, fz - ez)


def _driveway(seed, parcel, b, front_edge, front_dir, g, rng_veh,
              placements, patches, anchors, stats):
    p0, p1 = front_edge
    fdx, fdz = p1[0] - p0[0], p1[1] - p0[1]
    fln = math.hypot(fdx, fdz) or 1.0
    fdx, fdz = fdx / fln, fdz / fln
    ex, ez = b.entrance_xy
    r = DetRand(seed, b.bid, "driveway_offset")
    lateral = r.uniform(3.0, 8.0) * (1 if r.chance(0.5) else -1)
    start = (ex + fdx * lateral, ez + fdz * lateral)
    # anchor the far end on the front edge line itself
    edge_line = LineString([p0, p1])
    t = edge_line.project(Point(*start))
    end = edge_line.interpolate(t).coords[0]
    drive_line = LineString([start, end])
    if drive_line.length <= 0.5:
        return
    strip = drive_line.buffer(_DRIVEWAY_W / 2.0, cap_style=2)
    strip = strip.intersection(parcel.poly)
    if strip.is_empty:
        return
    patches.append(SurfacePatch(strip, "OTHER_IMPERVIOUS", 50))
    mid = drive_line.interpolate(0.5, normalized=True).coords[0]
    anchors.append(Anchor("DRIVEWAY_ANCHOR", mid[0], mid[1]))
    _bump(stats, "driveways")
    if rng_veh.chance(g["parked_vehicle"]):
        kind = rng_veh.weighted_choice(g["vehicle_mix"])
        heading = _heading_deg(end[0] - start[0], end[1] - start[1])
        vx, vz = drive_line.interpolate(min(2.5, drive_line.length * 0.5)).coords[0]
        placements.append(Placement(kind, vx, vz, heading,
                                     rng_veh.randint(0, 4), "vehicle"))
        _bump(stats, "vehicles")
    return strip


# ---- parking lots -----------------------------------------------------

def _parking_lot(seed, parcel, open_area, building_polys, g, placements,
                  patches, anchors, stats, driveway_strips):
    if g["parking_demand"] <= 0 or open_area.is_empty or open_area.area <= 250:
        return
    front_edge, front_dir = _front_edge_and_dir(parcel)
    front_half, rear_half = _split_front_rear(parcel.poly, front_dir)
    prefers_front = parcel.arch in ("RETAIL", "OFFICE", "MEDICAL", "SCHOOL")
    half = front_half if prefers_front else rear_half
    candidate = open_area.intersection(half)
    if candidate.is_empty or candidate.area < 120:
        candidate = open_area
    target_area = min(open_area.area * g["parking_demand"], 6000.0)
    if parcel.arch == "MULTIFAMILY":
        target_area = min(target_area, 1500.0)
    lot = _safe_buffer(candidate, -2.0)
    lot = lot.simplify(0.5)
    if lot.is_empty or lot.area < 120:
        return
    lot_polys = sorted(_as_polys(lot), key=lambda p: p.area, reverse=True)
    if not lot_polys:
        return
    lot_poly = lot_polys[0]
    if lot_poly.area > target_area * 1.5 and target_area > 0:
        # keep the piece closest to the building cluster reasonably sized;
        # simplest robust cap: shrink further rather than attempt an exact
        # area-matching cut.
        shrink = -0.5
        tries = 0
        while lot_poly.area > target_area * 1.5 and tries < 6:
            shrunk = _safe_buffer(lot_poly, shrink)
            polys = sorted(_as_polys(shrunk), key=lambda p: p.area, reverse=True)
            if not polys or polys[0].area < 120:
                break
            lot_poly = polys[0]
            tries += 1

    surface_name = "PARKING"
    patches.append(SurfacePatch(lot_poly, surface_name, 55))
    if parcel.arch == "INDUSTRIAL":
        remainder = _safe_diff(open_area, lot_poly.buffer(0.1))
        if not remainder.is_empty:
            patches.append(SurfacePatch(remainder, "OTHER_IMPERVIOUS", 45))

    angle = largest_rectangle_side(lot_poly)
    theta = math.radians(angle)
    ux, uz = math.sin(theta), math.cos(theta)   # along dominant direction
    vx, vz = -uz, ux                              # perpendicular

    minx, minz, maxx, maxz = lot_poly.bounds
    corners = [(minx, minz), (minx, maxz), (maxx, minz), (maxx, maxz)]
    us = [cx_ * ux + cz_ * uz for cx_, cz_ in corners]
    vs = [cx_ * vx + cz_ * vz for cx_, cz_ in corners]
    u0, u1 = min(us), max(us)
    v0, v1 = min(vs), max(vs)

    prep_lot = prep(lot_poly.buffer(-1.0)) if lot_poly.buffer(-1.0).area > 0 else None
    rng_lot = DetRand(seed, parcel.pid, "parking_layout")
    stall_count = 0
    aisle_points = []
    row_v = v0 + _STALL_D / 2.0
    row_i = 0
    while row_v < v1 and stall_count < _MAX_STALLS_PER_LOT:
        col_u = u0 + _STALL_W / 2.0
        col_i = 0
        row_has_stall = False
        while col_u < u1 and stall_count < _MAX_STALLS_PER_LOT:
            cx_ = col_u * ux + row_v * vx
            cz_ = col_u * uz + row_v * vz
            pt = Point(cx_, cz_)
            if prep_lot is not None and prep_lot.contains(pt):
                stall_count += 1
                row_has_stall = True
                stall_seed_key = f"{parcel.pid}:stall:{row_i}:{col_i}"
                rng_stall = DetRand(seed, stall_seed_key, "stall")
                if rng_stall.chance(0.45):
                    kind = rng_stall.weighted_choice(g["vehicle_mix"])
                    jitter = rng_stall.uniform(-4.0, 4.0)
                    rot = angle + 90.0 + jitter
                    placements.append(Placement(
                        kind, cx_, cz_, rot, rng_stall.randint(0, 4), "vehicle"))
                    _bump(stats, "vehicles")
                if rng_stall.chance(0.3):
                    head_u = col_u
                    head_v = row_v - _STALL_D / 2.0 + 0.3
                    hx = head_u * ux + head_v * vx
                    hz = head_u * uz + head_v * vz
                    placements.append(Placement("parking_stop", hx, hz, angle,
                                                 0, "prop"))
                if stall_count % 8 == 0:
                    placements.append(Placement("streetlight", cx_, cz_, angle,
                                                 0, "prop"))
                _bump(stats, "stalls")
            col_u += _STALL_W
            col_i += 1
        if row_has_stall:
            aisle_pt = ((u0 + u1) / 2.0 * ux + row_v * vx,
                        (u0 + u1) / 2.0 * uz + row_v * vz)
            aisle_points.append(aisle_pt)
        row_v += _STALL_D + _AISLE_W
        row_i += 1

    c = lot_poly.centroid
    anchors.append(Anchor("PARKING_ANCHOR", c.x, c.y))
    for ax, az in aisle_points[:4]:
        anchors.append(Anchor("PARKING_ANCHOR", ax, az))

    # Dumpster at rear, offset from any building on this parcel.
    if building_polys and rng_lot.chance(g["dumpster"]):
        bp = building_polys[0]
        entrance_edge, _ = _front_edge_and_dir(parcel)
        edges = list(ring_edges(bp))
        if edges:
            rear_edge = _longest_edge(edges)
            (dx_, dz_), _hd = _edge_outward_point(bp, rear_edge, 3.0)
            placements.append(Placement("dumpster", dx_, dz_, angle,
                                         rng_lot.randint(0, 2), "prop"))
            _bump(stats, "props")


# ---- per-building yard props -------------------------------------------

def _mailbox_frontage(parcel_poly, ex, ez, dx, dz, min_d=5.0, max_d=13.0, inset=1.0):
    """Point on the ray from the entrance toward the street where a mailbox sits:
    just inside the parcel frontage, but clamped to a plausible front-yard depth."""
    d = max_d
    try:
        ray = LineString([(ex, ez), (ex + dx * (max_d + 4.0), ez + dz * (max_d + 4.0))])
        inter = ray.intersection(parcel_poly.exterior)
        pts = []
        for geom in getattr(inter, "geoms", [inter]):
            if geom.is_empty:
                continue
            if geom.geom_type == "Point":
                pts.append((geom.x, geom.y))
            elif hasattr(geom, "coords"):
                pts.extend(list(geom.coords))
        cand = [math.hypot(px - ex, pz - ez) for px, pz in pts]
        cand = [c for c in cand if c > 0.5]
        if cand:
            d = min(cand) - inset
    except Exception:
        pass
    d = max(min_d, min(max_d, d))
    return ex + dx * d, ez + dz * d


def _building_props(seed, parcel, b, front_dir, walkway_dir, drive_strip, g,
                     placements, stats):
    rear_edge, side_edge = _rear_and_side_edges(b.poly, b.entrance_edge)
    ex, ez = b.entrance_xy

    r_mail = DetRand(seed, b.bid, "mailbox")
    if r_mail.chance(g["mailbox"]):
        if walkway_dir is not None:
            dx, dz = walkway_dir
            ln = math.hypot(dx, dz) or 1.0
            dx, dz = dx / ln, dz / ln
        elif front_dir is not None:
            dx, dz = front_dir
        else:
            dx, dz = 0.0, 1.0
        # A mailbox belongs at the street frontage, not tucked against the door.
        # Cast toward the street and stop just short of the parcel boundary,
        # clamped to a sane front-yard depth (parcels here are block-level, so an
        # unclamped cast could shoot a mailbox clear across the block).
        mx, mz = _mailbox_frontage(parcel.poly, ex, ez, dx, dz)
        placements.append(Placement("mailbox", mx, mz,
                                     _heading_deg(dx, dz), 0, "prop"))
        _bump(stats, "props")

    r_bins = DetRand(seed, b.bid, "bins")
    if side_edge is not None and r_bins.chance(g["bins"]):
        (gx, gz), hd = _edge_outward_point(b.poly, side_edge, 0.8)
        placements.append(Placement("garbage_bin", gx, gz, hd,
                                     r_bins.randint(0, 2), "prop"))
        placements.append(Placement("recycling_bin", gx + 0.8, gz, hd,
                                     r_bins.randint(0, 2), "prop"))
        _bump(stats, "props", 2)

    r_ac = DetRand(seed, b.bid, "ac_condenser")
    if rear_edge is not None and r_ac.chance(g["ac_condenser"]):
        (ax, az), hd = _edge_outward_point(b.poly, rear_edge, 0.7)
        placements.append(Placement("ac_condenser", ax, az, hd, 0, "prop"))
        _bump(stats, "props")

    r_util = DetRand(seed, b.bid, "utility_cabinet")
    if side_edge is not None and r_util.chance(0.15):
        (ux_, uz_), hd = _edge_outward_point(b.poly, side_edge, 0.6)
        placements.append(Placement("utility_cabinet", ux_ + 1.0, uz_, hd,
                                     0, "prop"))
        _bump(stats, "props")

    r_sign = DetRand(seed, b.bid, "flagpole_or_sign")
    if parcel.arch in ("CIVIC", "SCHOOL") and r_sign.chance(g["flagpole_or_sign"]):
        if front_dir is not None:
            sx, sz = ex + front_dir[0] * 4.0, ez + front_dir[1] * 4.0
        else:
            sx, sz = ex, ez
        placements.append(Placement("traffic_sign", sx, sz, 0, 0, "prop"))
        _bump(stats, "props")

    if parcel.arch == "INDUSTRIAL":
        r_ind = DetRand(seed, b.bid, "industrial_yard")
        n_pallets = r_ind.randint(0, 4)
        for i in range(n_pallets):
            rp = DetRand(seed, f"{b.bid}:pallet:{i}", "pallet")
            if rear_edge is not None:
                (px, pz), hd = _edge_outward_point(b.poly, rear_edge,
                                                    2.0 + i * 1.5)
                placements.append(Placement("pallet", px, pz, hd, 0, "prop"))
                _bump(stats, "props")
        if r_ind.chance(0.4) and rear_edge is not None:
            (tx, tz), hd = _edge_outward_point(b.poly, rear_edge, 5.0)
            placements.append(Placement("transformer_box", tx, tz, hd, 0, "prop"))
            _bump(stats, "props")
        if r_ind.chance(0.5) and rear_edge is not None:
            (vx_, vz_), hd = _edge_outward_point(b.poly, rear_edge, 8.0)
            kind = r_ind.weighted_choice([("box_truck", 1), ("van", 1)])
            placements.append(Placement(kind, vx_, vz_, hd,
                                         r_ind.randint(0, 4), "vehicle"))
            _bump(stats, "vehicles")

    if "loading_dock" in b.feat and rear_edge is not None:
        r_ld = DetRand(seed, b.bid, "loading_dock")
        n = r_ld.randint(1, 3)
        for i in range(n):
            kind = "dumpster" if i == 0 else r_ld.weighted_choice(
                [("dumpster", 1), ("pallet", 2)])
            (lx, lz), hd = _edge_outward_point(b.poly, rear_edge, 2.5 + i * 2.0)
            placements.append(Placement(kind, lx, lz, hd, 0, "prop"))
            _bump(stats, "props")
        if r_ld.chance(0.35):
            (bx, bz), hd = _edge_outward_point(b.poly, rear_edge, 9.0)
            placements.append(Placement("box_truck", bx, bz, hd + 90.0,
                                         r_ld.randint(0, 4), "vehicle"))
            _bump(stats, "vehicles")


# ---- fences --------------------------------------------------------------

def _fences(seed, parcel, buildings, front_dir, driveway_strips, placements, stats):
    """Per-building yard fences.

    Older versions traced the whole parcel-boundary polygon; parcels here are
    block-level land-use shapes riddled with slivers and reflex notches, so that
    produced fences spiking diagonally across yards. Instead each building gets a
    tidy rectangular yard fence aligned to its own footprint (oriented bounding
    box, expanded by a small margin), fenced on the three non-street sides and open
    to the street. Residential yards pick a consistent style (picket / privacy /
    split-rail / iron) baked into the panel variant.
    """
    g = PARCEL_DETAIL_GRAMMAR[parcel.arch]
    if parcel.arch == "RESIDENTIAL":
        kind, residential = "wood_fence", True
    elif parcel.arch == "INDUSTRIAL":
        kind, residential = "chainlink_fence", False
    elif parcel.arch in ("SCHOOL", "CIVIC"):
        kind, residential = "wood_fence", True
    else:
        return

    for idx, bid in enumerate(parcel.building_bids):
        if not (0 <= bid < len(buildings)):
            continue
        b = buildings[bid]
        r = DetRand(seed, b.bid, "fence")
        if not r.chance(g["fence"]):
            continue
        drive = driveway_strips[idx] if idx < len(driveway_strips) else None
        _yard_fence(b, front_dir, kind, residential, drive, r, placements, stats)


def _yard_fence(b, front_dir, kind, residential, drive, r, placements, stats):
    try:
        coords = list(b.poly.minimum_rotated_rectangle.exterior.coords)[:-1]
    except Exception:
        return
    if len(coords) != 4:
        return
    cx, cz = b.poly.centroid.x, b.poly.centroid.y
    margin = r.uniform(1.5, 3.0)
    exp = []
    for (x, z) in coords:
        dx, dz = x - cx, z - cz
        d = math.hypot(dx, dz) or 1.0
        exp.append((x + dx / d * margin, z + dz / d * margin))
    edges = [(exp[i], exp[(i + 1) % 4]) for i in range(4)]
    # Skip the street-facing edge (max projection along front_dir) so the yard
    # opens toward the street; without a front_dir, skip the longest edge.
    skip_i = -1
    if front_dir is not None:
        best = -1e18
        for i, (a, c) in enumerate(edges):
            mx, mz = (a[0] + c[0]) * 0.5, (a[1] + c[1]) * 0.5
            proj = (mx - cx) * front_dir[0] + (mz - cz) * front_dir[1]
            if proj > best:
                best, skip_i = proj, i
    else:
        skip_i = max(range(4), key=lambda i: math.dist(edges[i][0], edges[i][1]))
    style = r.randint(0, 3) if (residential and kind == "wood_fence") else 0
    for i, (a, c) in enumerate(edges):
        if i == skip_i:
            continue
        _fence_run(a, c, kind, style, drive, placements, stats)


def _fence_run(p0, p1, kind, style, drive, placements, stats):
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dz)
    if ln < 1.0:
        return
    ux, uz = dx / ln, dz / ln
    heading = _heading_deg(dx, dz)
    n = min(_MAX_FENCE_PANELS, max(1, int(ln // _FENCE_SPACING)))
    for i in range(n):
        d = (i + 0.5) * _FENCE_SPACING
        if d >= ln:
            continue
        px, pz = p0[0] + ux * d, p0[1] + uz * d
        if drive is not None and drive.distance(Point(px, pz)) < 2.0:
            continue
        placements.append(Placement(kind, px, pz, heading, style, "prop"))
        _bump(stats, "fences_m", _FENCE_SPACING)


# ---- vegetation ------------------------------------------------------------

def _vegetation(seed, parcel, open_area, building_union, patch_avoid,
                 g, placements, stats):
    """building_union: raw (unprepared) shapely geometry -- distance() needs
    the real geometry, not a PreparedGeometry (which only accelerates
    contains/intersects-style predicates, not distance queries)."""
    if open_area.is_empty:
        return
    area = open_area.area
    tree_density = g["tree_density_per_100m2"]
    bush_density = g["bush_density_per_100m2"]
    cap = _TREE_CAP_PARK if parcel.arch == "PARK" else _TREE_CAP_DEFAULT
    if parcel.arch == "PARK":
        tree_density *= 1.5

    minx, minz, maxx, maxz = open_area.bounds
    open_prep = prep(open_area)

    def ok(x, z, min_building=2.5, min_patch=2.0):
        pt = Point(x, z)
        if not open_prep.contains(pt):
            return False
        if building_union is not None and building_union.distance(pt) < min_building:
            return False
        for patch in patch_avoid:
            if patch is not None and patch.distance(pt) < min_patch:
                return False
        return True

    n_trees = 0
    n_bushes = 0
    if area > _COARSE_GRID_THRESHOLD:
        step = _COARSE_GRID_STEP
        cell_area = step * step
        p_tree = min(1.0, tree_density * cell_area / 100.0)
        p_bush = min(1.0, bush_density * cell_area / 100.0)
        gx = minx + step / 2.0
        gi = 0
        while gx < maxx:
            gz = minz + step / 2.0
            gj = 0
            while gz < maxz:
                rc = DetRand(seed, f"{parcel.pid}:grid:{gi}:{gj}", "veg")
                if n_trees < cap and rc.chance(p_tree) and ok(gx, gz):
                    kind = rc.weighted_choice(_TREE_WEIGHTS)
                    placements.append(Placement(kind, gx, gz,
                                                 rc.uniform(0, 360),
                                                 rc.randint(0, 2), "tree"))
                    n_trees += 1
                    _bump(stats, "trees")
                elif rc.chance(p_bush) and ok(gx, gz, min_building=1.0, min_patch=1.0):
                    kind = rc.choice(BUSH_KINDS)
                    placements.append(Placement(kind, gx, gz,
                                                 rc.uniform(0, 360),
                                                 rc.randint(0, 2), "tree"))
                    n_bushes += 1
                    _bump(stats, "bushes")
                gz += step
                gj += 1
            gx += step
            gi += 1
        return

    target_trees = min(cap, int(area / 100.0 * tree_density))
    tries = target_trees * 3
    rt = DetRand(seed, parcel.pid, "trees")
    placed = 0
    attempt = 0
    while placed < target_trees and attempt < max(tries, 1):
        attempt += 1
        x = rt.uniform(minx, maxx)
        z = rt.uniform(minz, maxz)
        if ok(x, z):
            kind = rt.weighted_choice(_TREE_WEIGHTS)
            placements.append(Placement(kind, x, z, rt.uniform(0, 360),
                                         rt.randint(0, 2), "tree"))
            placed += 1
            _bump(stats, "trees")

    target_bushes = int(area / 100.0 * bush_density)
    rb = DetRand(seed, parcel.pid, "bushes")
    placed_b = 0
    attempt = 0
    tries_b = target_bushes * 3
    while placed_b < target_bushes and attempt < max(tries_b, 1):
        attempt += 1
        x = rb.uniform(minx, maxx)
        z = rb.uniform(minz, maxz)
        if ok(x, z, min_building=1.0, min_patch=1.0):
            kind = rb.choice(BUSH_KINDS)
            placements.append(Placement(kind, x, z, rb.uniform(0, 360),
                                         rb.randint(0, 2), "tree"))
            placed_b += 1
            _bump(stats, "bushes")


def _residential_perimeter_bushes(seed, parcel, building_polys, open_area,
                                   g, placements, stats):
    """Extra pass: bias some bushes to hug the building perimeter for
    RESIDENTIAL parcels, per spec. Additive to `_vegetation`'s general
    scatter (kept as a small separate top-up so the main scatter logic
    stays archetype-agnostic)."""
    if parcel.arch != "RESIDENTIAL" or not building_polys:
        return
    open_prep = prep(open_area) if not open_area.is_empty else None
    if open_prep is None:
        return
    for bpi, bp in enumerate(building_polys):
        ring = bp.buffer(1.5).exterior
        rlen = ring.length
        if rlen <= 0:
            continue
        # bpi is stable: building_polys derives from parcel.building_bids,
        # which is deterministically ordered (never a memory address).
        r = DetRand(seed, f"{parcel.pid}:{bpi}", "perimeter_bush")
        n = r.randint(0, 3)
        for i in range(n):
            d = r.uniform(0, rlen)
            pt = ring.interpolate(d)
            if open_prep.contains(pt):
                kind = r.choice(BUSH_KINDS)
                placements.append(Placement(kind, pt.x, pt.y,
                                             r.uniform(0, 360),
                                             r.randint(0, 2), "tree"))
                _bump(stats, "bushes")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def compile_detail(parcels, buildings, segments, seed) -> DetailResult:
    """Compile the PROCEDURAL parcel-detail layer for a whole bundle.

    parcels: list[Parcel] (records.Parcel).
    buildings: list[BuildingRecord], index == bid.
    segments: list[RoadSegment] (unused directly here except that curb-side
        vehicle scattering, `curb_vehicles`, is a sibling function consuming
        the same list -- kept out of this function's per-parcel loop since
        curb parking is keyed on road geometry, not parcel geometry).
    seed: world seed; combined with stable feature keys via DetRand.

    NOTE: does NOT emit BUILDING_ENTRANCE anchors -- see `entrance_anchors`.
    """
    placements: list = []
    patches: list = []
    anchors: list = []
    stats: dict = {}

    for parcel in parcels:
        g = PARCEL_DETAIL_GRAMMAR.get(parcel.arch, PARCEL_DETAIL_GRAMMAR["UNKNOWN"])
        building_polys = [buildings[bid].poly for bid in parcel.building_bids
                           if 0 <= bid < len(buildings)]
        patch_start = len(patches)
        open_area = _ground_surface(parcel, building_polys, g, patches)

        front_edge, front_dir = _front_edge_and_dir(parcel)
        driveway_strips = []

        for bid in parcel.building_bids:
            if not (0 <= bid < len(buildings)):
                continue
            b = buildings[bid]

            walkway_dir = None
            if front_edge is not None:
                r_walk = DetRand(seed, b.bid, "front_walkway")
                if r_walk.chance(g["front_walkway"]):
                    walkway_dir = _walkway(seed, parcel, b, front_edge,
                                            patches, anchors, placements, stats)

            drive_strip = None
            if front_edge is not None:
                r_drive = DetRand(seed, b.bid, "driveway")
                if r_drive.chance(g["driveway"]):
                    rng_veh = DetRand(seed, b.bid, "driveway_vehicle")
                    drive_strip = _driveway(seed, parcel, b, front_edge,
                                             front_dir, g, rng_veh,
                                             placements, patches, anchors,
                                             stats)
            driveway_strips.append(drive_strip)

            _building_props(seed, parcel, b, front_dir, walkway_dir,
                             drive_strip, g, placements, stats)

        if g["parking_demand"] > 0 and not open_area.is_empty and open_area.area > 250:
            _parking_lot(seed, parcel, open_area, building_polys, g,
                         placements, patches, anchors, stats, driveway_strips)

        _fences(seed, parcel, buildings, front_dir, driveway_strips, placements, stats)

        building_union = None
        if building_polys:
            bu = unary_union(building_polys)
            building_union = bu if not bu.is_empty else None
        patch_avoid = [p.poly for p in patches[patch_start:]
                       if p.surface in ("PARKING", "OTHER_IMPERVIOUS")]
        _vegetation(seed, parcel, open_area, building_union, patch_avoid,
                    g, placements, stats)
        _residential_perimeter_bushes(seed, parcel, building_polys, open_area,
                                       g, placements, stats)

    return DetailResult(placements=placements, patches=patches,
                         anchors=anchors, stats=stats)


# ---------------------------------------------------------------------------
# Curb-parked vehicles (residential streets)
# ---------------------------------------------------------------------------

_CURB_SPACING = 30.0
_CURB_PROB = 0.18
_CURB_CAP = 3000


def curb_vehicles(segments, parcels, seed) -> list:
    """Parallel-parked vehicles along residential-class road segments.

    Deterministic per (segment.key, sample index along that segment) -- not
    per list index, so re-ordering `segments` upstream cannot change any
    individual vehicle's fate, only the final list order (which is stable
    given a stable `segments` order).
    """
    out: list = []
    total = 0
    for seg in segments:
        if total >= _CURB_CAP:
            break
        if seg.cls != "residential" or seg.path_only or len(seg.pts) < 2:
            continue
        pts = seg.pts
        seg_len = sum(
            math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            for i in range(len(pts) - 1)
        )
        if seg_len <= 0:
            continue
        offset = max(seg.carriage_w / 2.0 - 1.2, 0.6)
        n_samples = max(1, int(seg_len // _CURB_SPACING))
        for i in range(n_samples):
            if total >= _CURB_CAP:
                break
            d = (i + 0.5) * _CURB_SPACING
            if d >= seg_len:
                continue
            r = DetRand(seed, seg.key, f"curb:{i}")
            if not r.chance(_CURB_PROB):
                continue
            x, z, heading = _point_along(pts, d)
            side = 1 if (i % 2 == 0) else -1
            rad = math.radians(heading)
            # unit normal to travel direction
            nx, nz = math.cos(rad), -math.sin(rad)
            px, pz = x + nx * offset * side, z + nz * offset * side
            kind = r.weighted_choice(
                [("sedan", 5), ("suv", 4), ("pickup", 2), ("van", 1)])
            out.append(Placement(kind, px, pz, heading, r.randint(0, 4),
                                  "vehicle"))
            total += 1
    return out


def _point_along(pts, dist):
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if acc + seg >= dist and seg > 0:
            t = (dist - acc) / seg
            x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
            z = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
            hd = math.degrees(math.atan2(pts[i + 1][0] - pts[i][0],
                                          pts[i + 1][1] - pts[i][1]))
            return x, z, hd
        acc += seg
    p0, p1 = pts[-2], pts[-1]
    hd = math.degrees(math.atan2(p1[0] - p0[0], p1[1] - p0[1]))
    return p1[0], p1[1], hd


# ---------------------------------------------------------------------------
# Vehicle de-overlap (Package E fix): curb / driveway / parking vehicles are
# placed by independent passes and can intersect (e.g. a wide van in a 2.6 m
# stall, or a curb car landing on a driveway car). Reject any vehicle whose
# oriented footprint intersects an already-accepted one. Deterministic: process
# in a stable spatial order, so the surviving set never depends on list order.
# ---------------------------------------------------------------------------

# (width_m, length_m) per vehicle kind, matching AssetCatalogV1 dimensions.
_VEHICLE_FOOTPRINT = {
    "sedan": (2.0, 4.6), "suv": (2.1, 4.8), "pickup": (2.1, 5.4),
    "van": (2.2, 5.2), "box_truck": (2.5, 7.0),
}
_DEDUP_CELL = 8.0  # spatial-hash cell >= longest vehicle


def _obb_axes(rot_deg):
    # Matches the renderer: length axis = Basis(UP, rad - 90 deg) * +X.
    th = math.radians(rot_deg) - math.pi / 2.0
    length_axis = (math.cos(th), -math.sin(th))
    width_axis = (-length_axis[1], length_axis[0])
    return length_axis, width_axis


def _obb_overlap(a, b):
    (ax, az, arot, ahl, ahw) = a
    (bx, bz, brot, bhl, bhw) = b
    al, aw = _obb_axes(arot)
    bl, bw = _obb_axes(brot)
    dx, dz = bx - ax, bz - az
    # SAT over the 4 face normals; a small negative slack lets bumpers kiss.
    for (axis, ra) in ((al, ahl), (aw, ahw)):
        pa = ra
        pb = (abs(bl[0] * axis[0] + bl[1] * axis[1]) * bhl
              + abs(bw[0] * axis[0] + bw[1] * axis[1]) * bhw)
        if abs(dx * axis[0] + dz * axis[1]) > pa + pb - 0.15:
            return False
    for (axis, rb) in ((bl, bhl), (bw, bhw)):
        pb = rb
        pa = (abs(al[0] * axis[0] + al[1] * axis[1]) * ahl
              + abs(aw[0] * axis[0] + aw[1] * axis[1]) * ahw)
        if abs(dx * axis[0] + dz * axis[1]) > pa + pb - 0.15:
            return False
    return True


def dedupe_vehicles(placements: list) -> list:
    """Return `placements` with intersecting vehicles removed (non-vehicles kept)."""
    vehicles = [p for p in placements if p.cat == "vehicle"]
    others = [p for p in placements if p.cat != "vehicle"]
    # stable order so acceptance is deterministic regardless of source ordering
    vehicles.sort(key=lambda p: (round(p.x, 2), round(p.z, 2), p.kind, p.variant))
    grid: dict = {}
    kept = []
    for p in vehicles:
        w, ln = _VEHICLE_FOOTPRINT.get(p.kind, (2.1, 4.8))
        box = (p.x, p.z, p.rot, ln / 2.0, w / 2.0)
        gx, gz = int(p.x // _DEDUP_CELL), int(p.z // _DEDUP_CELL)
        clash = False
        for ox in (-1, 0, 1):
            for oz in (-1, 0, 1):
                for other in grid.get((gx + ox, gz + oz), ()):
                    if _obb_overlap(box, other):
                        clash = True
                        break
                if clash:
                    break
            if clash:
                break
        if clash:
            continue
        kept.append(p)
        grid.setdefault((gx, gz), []).append(box)
    return others + kept

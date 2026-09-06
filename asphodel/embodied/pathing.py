"""Canonical projection: graph route -> physical path (ASPHODEL_EMBODIED_MOBILITY_V1 §11).

    MobilityGraph edges  ->  street polylines  ->  drive/walk path  ->  controller

Anchors (building entrances, parking anchors) are attached to the street graph
as **access nodes** joined to the junctions of the street they project onto by
**access connectors** whose polyline is the real street polyline from the
projection point to the junction, plus the short hop from the anchor to the
kerb. A route through an access node therefore follows rendered street
geometry everywhere except that hop (bounded by MAX_CONNECTOR_M), one-way
rules included. There is no invisible parallel road model: the physical path
of a leg is exactly ``route_polyline`` of its graph route.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..mobility import Direction, Mode, MobilityGraph, RoadSegment, Route
from ..transport.instances import _cumulative, point_at_distance, route_polyline

Vec2 = Tuple[float, float]

# An anchor farther than this from a usable street is not "at" the street; the
# caller must pick another anchor (§13 "reachable from the road").
MAX_CONNECTOR_M = 60.0


def _d(a: Vec2, b: Vec2) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass(frozen=True)
class AccessPoint:
    """Where an anchor touches the street network for a mode."""

    anchor_xy: Vec2            # the entrance / parking anchor itself
    segment_id: str            # street segment it projects onto
    on_street_xy: Vec2         # projection point ON the polyline
    along: float               # metres along the segment polyline (from polyline[0])
    connector_m: float         # anchor -> street distance
    mode: Mode

    def to_dict(self) -> dict:
        return {"anchor_xy": [round(self.anchor_xy[0], 2), round(self.anchor_xy[1], 2)],
                "segment_id": self.segment_id,
                "on_street_xy": [round(self.on_street_xy[0], 2), round(self.on_street_xy[1], 2)],
                "along": round(self.along, 2), "connector_m": round(self.connector_m, 2),
                "mode": self.mode.value}


def _along_polyline(pts: Sequence[Vec2], p: Vec2) -> float:
    """Distance along ``pts`` of the point nearest to ``p``."""
    cum = _cumulative(list(pts))
    best_d, best_along = math.inf, 0.0
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        abx, abz = b[0] - a[0], b[1] - a[1]
        l2 = abx * abx + abz * abz
        if l2 < 1e-12:
            continue
        t = max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * abz) / l2))
        proj = (a[0] + abx * t, a[1] + abz * t)
        dd = _d(proj, p)
        if dd < best_d:
            best_d, best_along = dd, cum[i - 1] + math.sqrt(l2) * t
    return best_along


def access_point(graph: MobilityGraph, anchor_xy: Vec2, mode: Mode,
                 max_connector_m: float = MAX_CONNECTOR_M) -> Optional[AccessPoint]:
    """Project an anchor onto the nearest street usable by ``mode``."""
    hit = graph.nearest_segment_point((float(anchor_xy[0]), float(anchor_xy[1])), mode)
    if hit is None:
        return None
    sid, pt, dist = hit
    if dist > max_connector_m:
        return None
    seg = graph.segments[sid]
    along = _along_polyline(seg.polyline, pt)
    return AccessPoint((float(anchor_xy[0]), float(anchor_xy[1])), sid,
                       (float(pt[0]), float(pt[1])), along, float(dist), mode)


def _sub_polyline(pts: List[Vec2], a: float, b: float) -> List[Vec2]:
    """Points of ``pts`` between distances ``a`` and ``b`` (either order)."""
    cum = _cumulative(pts)
    lo, hi = (a, b) if a <= b else (b, a)
    out: List[Vec2] = [point_at_distance(pts, cum, lo)]
    for i, c in enumerate(cum):
        if lo < c < hi:
            out.append(pts[i])
    out.append(point_at_distance(pts, cum, hi))
    if a > b:
        out.reverse()
    return out


def _endpoint_nodes(graph: MobilityGraph, sid: str) -> Tuple[str, str]:
    """(node at polyline[0], node at polyline[-1]) for a segment (cached)."""
    cache: Dict[str, Tuple[str, str]] = graph.__dict__.setdefault("_seg_ends", {})
    hit = cache.get(sid)
    if hit is not None:
        return hit
    if len(cache) == 0:
        # Build the whole map once: O(segments), then O(1) per lookup.
        for nid, adj in graph._adj.items():
            for (w, s2, fwd) in adj:
                a, b = cache.get(s2, (None, None))
                if fwd:
                    a, b = nid, w
                else:
                    a, b = w, nid
                cache[s2] = (a, b)
    hit = cache.get(sid)
    if hit is None:
        seg = graph.segments[sid]
        hit = (graph.nearest_node(seg.polyline[0]), graph.nearest_node(seg.polyline[-1]))
        cache[sid] = hit
    return hit


# --------------------------------------------------------------------------- #
# access nodes + connectors
# --------------------------------------------------------------------------- #
def attach_anchor(graph: MobilityGraph, key: str, anchor_xy: Vec2,
                  modes: Sequence[Mode], project_mode: Mode,
                  max_connector_m: float = MAX_CONNECTOR_M) -> Optional[Tuple[str, AccessPoint]]:
    """Attach an anchor to the street graph as a routable access node.

    Creates node ``key`` at ``anchor_xy`` and up to two connector segments
    ``conn:<key>:0`` / ``conn:<key>:1`` to the junctions of the street the
    anchor projects onto (for ``project_mode``). Each connector's polyline is
    ``[anchor, kerb projection] + street partial to the junction`` — real
    geometry — and inherits the street's class/speed. One-way streets yield
    one-way connectors so a car cannot leave a driveway against traffic.
    Pedestrians may always use a connector in both directions. Idempotent:
    re-attaching an existing key returns the existing node.

    Returns ``(node_id, access_point)`` or None when the anchor is not at a
    street usable by ``project_mode``.
    """
    if key in graph.nodes:
        ap = graph.__dict__.setdefault("_access_points", {}).get(key)
        if ap is not None:
            return key, ap
    ap = access_point(graph, anchor_xy, project_mode, max_connector_m)
    if ap is None:
        return None
    seg = graph.segments[ap.segment_id]
    n0, n1 = _endpoint_nodes(graph, ap.segment_id)
    pts = list(seg.polyline)
    graph.add_node(key, ap.anchor_xy)
    modes = set(modes) | {Mode.FOOT}
    street_modes = set(seg.allowed_modes) | {Mode.FOOT}
    conn_modes = modes & street_modes | {Mode.FOOT}

    def _conn(idx: int, node: str, partial: List[Vec2], legal_out: bool, legal_in: bool) -> None:
        poly = [ap.anchor_xy, ap.on_street_xy] + partial[1:]
        if legal_out and legal_in:
            d = Direction.BIDIRECTIONAL
        elif legal_out:
            d = Direction.FORWARD           # anchor -> junction only (departure)
        else:
            d = Direction.BACKWARD          # junction -> anchor only (arrival)
        cs = RoadSegment(id=f"conn:{key}:{idx}", polyline=poly,
                         road_class=seg.road_class, directionality=d,
                         speed_limit=seg.speed_limit, lanes=seg.lanes,
                         allowed_modes=set(conn_modes), sidewalks=True)
        # Pedestrians ignore one-way: give them a dedicated bidirectional twin
        # only when the vehicular connector is one-way.
        graph.add_segment(cs, key, node, index=False)
        if d != Direction.BIDIRECTIONAL:
            fs = RoadSegment(id=f"conn:{key}:{idx}f", polyline=list(poly),
                             road_class="footway", allowed_modes={Mode.FOOT},
                             sidewalks=True)
            graph.add_segment(fs, key, node, index=False)

    dirn = seg.directionality
    fwd_ok = dirn in (Direction.BIDIRECTIONAL, Direction.FORWARD)
    bwd_ok = dirn in (Direction.BIDIRECTIONAL, Direction.BACKWARD)
    # toward polyline end (n1): departure travels forward; arrival from n1 travels backward
    _conn(1, n1, _sub_polyline(pts, ap.along, seg.length), fwd_ok, bwd_ok)
    # toward polyline start (n0): departure travels backward; arrival from n0 forward
    if n0 != n1:
        _conn(0, n0, _sub_polyline(pts, ap.along, 0.0), bwd_ok, fwd_ok)
    graph.__dict__.setdefault("_access_points", {})[key] = ap
    return key, ap


def detach_anchor(graph: MobilityGraph, key: str) -> None:
    """Remove an access node and its connectors (inverse of attach_anchor)."""
    if key not in graph.nodes:
        return
    for sid in [s for s in graph.segments if s.startswith(f"conn:{key}:")]:
        del graph.segments[sid]
    for nid, adj in graph._adj.items():
        graph._adj[nid] = [t for t in adj if t[0] != key and not t[1].startswith(f"conn:{key}:")]
    graph._adj.pop(key, None)
    graph.nodes.pop(key, None)
    graph.__dict__.get("_access_points", {}).pop(key, None)


def _same_segment_legal(graph: MobilityGraph, a: AccessPoint, b: AccessPoint, mode: Mode) -> bool:
    """May ``mode`` travel along the street from kerb ``a`` to kerb ``b``?"""
    seg = graph.segments[a.segment_id]
    if mode == Mode.FOOT:
        return True
    fwd = b.along >= a.along
    d = seg.directionality
    return (d == Direction.BIDIRECTIONAL or (fwd and d == Direction.FORWARD)
            or ((not fwd) and d == Direction.BACKWARD))


# --------------------------------------------------------------------------- #
# physical path of a leg
# --------------------------------------------------------------------------- #
@dataclass
class PhysicalPath:
    """The executable geometry of one WALK/DRIVE leg: the route's polyline."""

    points: List[Vec2]
    cum: List[float] = field(default_factory=list)
    # (segment_id, start_dist, end_dist) along the path, in order.
    segments: List[Tuple[str, float, float]] = field(default_factory=list)
    route: Optional[Route] = None
    mode: Mode = Mode.FOOT

    def __post_init__(self):
        if not self.cum:
            self.cum = _cumulative(self.points)

    @classmethod
    def from_route(cls, graph: MobilityGraph, route: Route) -> "PhysicalPath":
        """The route's polyline, with one geometric simplification: two
        consecutive access connectors that meet at a junction but project onto
        the SAME street are replaced by the street's own polyline between the
        two kerb points (a driveway 7 m down the street from the front door is
        a 7 m walk, not a walk to the corner and back). Still real geometry."""
        pts: List[Vec2] = []
        segs: List[Tuple[str, float, float]] = []
        acc = 0.0
        aps: Dict[str, AccessPoint] = graph.__dict__.get("_access_points", {})
        i = 0
        seg_ids = list(route.segments)
        nodes = list(route.nodes)
        while i < len(seg_ids):
            sid = seg_ids[i]
            if (i + 1 < len(seg_ids) and sid.startswith("conn:") and seg_ids[i + 1].startswith("conn:")):
                a_key, b_key = nodes[i], nodes[i + 2]
                a, b = aps.get(a_key), aps.get(b_key)
                if a is not None and b is not None and a.segment_id == b.segment_id \
                        and _same_segment_legal(graph, a, b, route.mode):
                    street = list(graph.segments[a.segment_id].polyline)
                    poly = [a.anchor_xy, a.on_street_xy] + _sub_polyline(street, a.along, b.along)[1:-1] \
                        + [b.on_street_xy, b.anchor_xy]
                    L = _cumulative(poly)[-1]
                    if pts and _d(pts[-1], poly[0]) < 1e-6:
                        poly = poly[1:]
                    pts.extend(poly)
                    segs.append((a.segment_id, acc, acc + L))
                    acc += L
                    i += 2
                    continue
            seg = graph.segments[sid]
            pu = graph.nodes[nodes[i]]
            poly = list(seg.polyline)
            if _d(poly[0], pu) > _d(poly[-1], pu):
                poly.reverse()
            if pts and _d(pts[-1], poly[0]) < 1e-6:
                poly = poly[1:]
            pts.extend(poly)
            segs.append((sid, acc, acc + seg.length))
            acc += seg.length
            i += 1
        if not pts and nodes:
            pts = [graph.nodes[nodes[0]]]
        return cls(pts, segments=segs, route=route, mode=route.mode)

    def kerb_offset(self, d: float) -> "PhysicalPath":
        """The same path walked along the kerb: every point that lies on a real
        street segment is moved ``d`` metres to the right of the direction of
        travel; access connectors (front door, driveway, parking bay) keep
        their real geometry so the walk still ends at the door. Segment
        extents are rescaled to the new cumulative lengths so node bookkeeping
        (``node_before``, ``segment_at``) keeps working. Pure geometry: the
        same route always yields the same kerb path."""
        pts = self.points
        n = len(pts)
        if d == 0.0 or n < 2 or not self.segments:
            return self
        # which point indices lie on street (non-connector) segments
        on_street = [False] * n
        for sid, s0, s1 in self.segments:
            if sid.startswith("conn:"):
                continue
            for i, c in enumerate(self.cum):
                if s0 - 1e-6 <= c <= s1 + 1e-6:
                    on_street[i] = True
        # the leg's own end points are places the citizen must physically
        # reach (a door, a parked car, the node of the next leg): never moved
        on_street[0] = False
        on_street[n - 1] = False
        out: List[Vec2] = []
        for i, p in enumerate(pts):
            if not on_street[i]:
                out.append(p)
                continue
            # average of the unit directions into and out of this vertex
            dx = dy = 0.0
            if i > 0:
                ax, ay = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
                L = math.hypot(ax, ay)
                if L > 1e-9:
                    dx += ax / L
                    dy += ay / L
            if i < n - 1:
                bx, by = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
                L = math.hypot(bx, by)
                if L > 1e-9:
                    dx += bx / L
                    dy += by / L
            L = math.hypot(dx, dy)
            if L < 1e-9:
                out.append(p)
                continue
            nx, ny = dy / L, -dx / L          # right-hand normal of the travel direction
            out.append((p[0] + nx * d, p[1] + ny * d))
        new_cum = _cumulative(out)
        old_len = self.cum[-1] if self.cum else 0.0
        new_len = new_cum[-1] if new_cum else 0.0
        k = (new_len / old_len) if old_len > 1e-9 else 1.0
        segs = [(sid, s0 * k, s1 * k) for sid, s0, s1 in self.segments]
        return PhysicalPath(out, cum=new_cum, segments=segs, route=self.route, mode=self.mode)

    @property
    def length(self) -> float:
        return self.cum[-1] if self.cum else 0.0

    def point_at(self, dist: float) -> Vec2:
        return point_at_distance(self.points, self.cum, dist)

    def heading_at(self, dist: float) -> float:
        """Heading (radians, atan2(dz, dx)) of the path at ``dist``."""
        if len(self.points) < 2:
            return 0.0
        i = 1
        while i < len(self.cum) - 1 and self.cum[i] <= dist:
            i += 1
        a, b = self.points[i - 1], self.points[i]
        return math.atan2(b[1] - a[1], b[0] - a[0])

    def segment_at(self, dist: float) -> Optional[str]:
        for sid, s0, s1 in self.segments:
            if s0 - 1e-6 <= dist <= s1 + 1e-6:
                return sid
        return self.segments[-1][0] if self.segments else None

    def street_segments(self) -> List[str]:
        """Real street segments (connectors excluded)."""
        return [s for s, _, _ in self.segments if not s.startswith("conn:")]

    def to_dict(self) -> dict:
        return {"length": round(self.length, 1), "n_points": len(self.points),
                "segments": self.street_segments(),
                "n_connectors": sum(1 for s, _, _ in self.segments if s.startswith("conn:")),
                "mode": self.mode.value,
                "route_nodes": list(self.route.nodes) if self.route else []}

    def node_before(self, dist: float) -> Optional[str]:
        """The last graph node passed at ``dist`` along the path (the start node
        of the segment containing ``dist``), or None without a route."""
        if self.route is None or not self.route.nodes:
            return None
        k = 0
        for i, (_sid, s0, _s1) in enumerate(self.segments):
            if s0 <= dist + 1e-6:
                k = i
        if k < len(self.route.nodes):
            return self.route.nodes[k]
        return self.route.nodes[-1]

    def remaining_points(self, dist: float, max_points: int = 400) -> List[Vec2]:
        """The path ahead of ``dist`` (published to a NEAR body as waypoints)."""
        if dist <= 0:
            pts = list(self.points)
        else:
            pts = [self.point_at(dist)]
            for i, c in enumerate(self.cum):
                if c > dist:
                    pts.append(self.points[i])
        if len(pts) > max_points:
            pts = pts[:max_points]
        return pts

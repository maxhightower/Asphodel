"""Bake the canonical street graph (``streetmap.json``) — AS-NAV-0 §5, §17.

Authority boundary: the *rendered* city and the *routable* city must be the
same city. Both are derived here from one upstream source — the normalized
Overture transportation layers (``world_source.normalize``) — so a street a
player can see is a street an agent can drive. The exterior compiler
(``world_source.compile``) turns those same road Features into chunk ribbons;
this module turns them into graph nodes and edges. Neither invents geometry.

Two bakes live here:

``streetmap_from_world_source``
    The canonical one. Overture segments carry a ``connectors`` list — the
    GERS ids of the shared junction points, each with the fraction ``at``
    along the segment's linestring where it sits. Splitting every road at its
    connectors yields sub-segments whose endpoints are *shared node identities*
    across roads, which is exactly a routable graph: no snapping heuristic, no
    guessing which polyline ends meet.

``streetmap_from_polylines``
    The legacy fallback for a bundle with no Overture packet (the synthetic
    proving-ground cities). Endpoints are snapped on a grid, which recovers
    intersections only where the source polylines actually terminate.

Both emit schema version 2, which keeps each segment's FULL polyline in
``pts``. Version 1 discarded it and rebuilt every segment as a straight
2-point line, so Python lengths and Godot ribbons disagreed; v2 removes that
divergence by construction. Output is deterministic: every collection is
sorted before it is written, so identical inputs give a byte-identical file.
"""
from __future__ import annotations

import bisect
import collections
import math
from typing import Dict, List, Optional, Sequence, Tuple

from .segments import Direction, RoadSegment

Vec2 = Tuple[float, float]

STREETMAP_VERSION = 2

# Sub-segments shorter than this are dropped: two connectors landing on the
# same point produce a zero-length edge that carries no travel and only makes
# the graph noisier.
_MIN_SEGMENT_LENGTH_M = 0.01


def _cumulative(pts: Sequence[Vec2]) -> List[float]:
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return cum


def _point_at(pts: Sequence[Vec2], cum: Sequence[float], d: float) -> Vec2:
    """Interpolate the point ``d`` metres along a polyline (clamped)."""
    if d <= 0.0:
        return (pts[0][0], pts[0][1])
    if d >= cum[-1]:
        return (pts[-1][0], pts[-1][1])
    k = min(bisect.bisect_right(cum, d) - 1, len(pts) - 2)
    span = cum[k + 1] - cum[k]
    t = 0.0 if span <= 0.0 else (d - cum[k]) / span
    return (pts[k][0] + (pts[k + 1][0] - pts[k][0]) * t,
            pts[k][1] + (pts[k + 1][1] - pts[k][1]) * t)


def _slice(pts: Sequence[Vec2], cum: Sequence[float],
           d0: float, d1: float) -> List[Vec2]:
    """The sub-polyline between two arc-length offsets, endpoints included."""
    out = [_point_at(pts, cum, d0)]
    for p, c in zip(pts, cum):
        if d0 < c < d1:
            out.append((p[0], p[1]))
    out.append(_point_at(pts, cum, d1))
    return out


def _round_pts(pts: Sequence[Vec2]) -> List[List[float]]:
    """Round to centimetres and drop vertices the rounding made duplicates."""
    out: List[List[float]] = []
    for x, z in pts:
        q = [round(float(x), 2), round(float(z), 2)]
        if out and out[-1] == q:
            continue
        out.append(q)
    return out


def _direction(oneway: Optional[str]) -> Direction:
    if oneway == "forward":
        return Direction.FORWARD
    if oneway == "backward":
        return Direction.BACKWARD
    return Direction.BIDIRECTIONAL


def _segment_record(seg_id: str, u: str, v: str, road_class: str,
                    pts: List[List[float]], direction: Direction,
                    sidewalks: bool) -> dict:
    """One serialized segment. Class defaults come from ``_CLASS_DEFAULTS``."""
    seg = RoadSegment(id=seg_id, polyline=[(p[0], p[1]) for p in pts],
                      road_class=road_class, directionality=direction,
                      sidewalks=sidewalks)
    return {
        "id": seg_id,
        "u": u,
        "v": v,
        "class": road_class,
        "length": round(seg.length, 2),
        "directionality": direction.value,
        "modes": sorted(m.value for m in seg.allowed_modes),
        "speed_limit": seg.speed_limit,
        "lanes": seg.lanes,
        "pts": pts,
    }


def _artifact(nodes: Dict[str, List[float]], segs: List[dict],
              source_label: str, extra: Optional[dict] = None) -> dict:
    """Assemble the artifact with every collection in a deterministic order."""
    segs = sorted(segs, key=lambda s: s["id"])
    directed = 0
    oneway = 0
    classes: Dict[str, int] = collections.Counter()
    total_len = 0.0
    for s in segs:
        classes[s["class"]] += 1
        total_len += s["length"]
        if s["directionality"] == "bidirectional":
            directed += 2
        else:
            directed += 1
            oneway += 1
    stats = {
        "nodes": len(nodes),
        "segments": len(segs),
        "directed_edges": directed,
        "oneway_segments": oneway,
        "length_km": round(total_len / 1000.0, 3),
        "class_histogram": dict(sorted(classes.items())),
    }
    if extra:
        stats.update(extra)
    return {
        "version": STREETMAP_VERSION,
        "source": source_label,
        "frame": "bundle_metres",
        "nodes": {nid: nodes[nid] for nid in sorted(nodes)},
        "segments": segs,
        "stats": stats,
    }


# -- the canonical bake ------------------------------------------------------
def streetmap_from_world_source(ws, source_label: str) -> dict:
    """Split every normalized road at its connectors into a routable graph.

    ``ws`` is a :class:`world_source.schema.WorldSourceV1` whose road Features
    carry ``properties["connectors"]`` (``[[gers, at], ...]`` sorted by ``at``)
    and ``properties["oneway"]`` — see ``world_source.normalize``.

    Node identity is the connector's GERS id, so two roads meeting at a
    junction land on the *same* node without any distance heuristic. A road
    whose connector list omits an endpoint still gets one, keyed
    ``"<gers>@<k>"`` off the owning road, so no sub-segment is left dangling.
    Node position is the connector Feature's own position when the packet
    carries it, otherwise the point interpolated along the road.
    """
    conn_pos: Dict[str, Vec2] = {}
    for c in getattr(ws, "connectors", []):
        if c.geometry:
            x, z = c.geometry[0]
            conn_pos[c.stable_key] = (float(x), float(z))

    nodes: Dict[str, List[float]] = {}
    segs: List[dict] = []
    split_roads = 0

    for f in sorted(getattr(ws, "roads", []), key=lambda r: r.stable_key):
        if f.geom_type != "line" or len(f.geometry) < 2:
            continue
        pts = [(float(x), float(z)) for x, z in f.geometry]
        cum = _cumulative(pts)
        total = cum[-1]
        if total <= _MIN_SEGMENT_LENGTH_M:
            continue
        props = f.properties or {}
        gers = f.stable_key
        road_class = props.get("class") or "unknown"
        direction = _direction(props.get("oneway"))

        # Cut list: every connector plus both endpoints, de-duplicated by `at`.
        cuts: List[Tuple[float, Optional[str]]] = []
        for entry in props.get("connectors") or []:
            cid, at = entry[0], float(entry[1])
            at = min(1.0, max(0.0, at))
            if cuts and abs(cuts[-1][0] - at) <= 1e-12:
                continue                      # coincident connectors: keep the first
            cuts.append((at, cid))
        if not cuts or cuts[0][0] > 0.0:
            cuts.insert(0, (0.0, None))
        if cuts[-1][0] < 1.0:
            cuts.append((1.0, None))

        # Resolve node ids and positions for each cut.
        node_ids: List[str] = []
        for k, (at, cid) in enumerate(cuts):
            if cid is None:
                nid = f"{gers}@{k}"
                pos = _point_at(pts, cum, at * total)
            else:
                nid = cid
                pos = conn_pos.get(cid) or _point_at(pts, cum, at * total)
            node_ids.append(nid)
            if nid not in nodes:
                nodes[nid] = [round(pos[0], 2), round(pos[1], 2)]

        if len(cuts) > 2:
            split_roads += 1
        for k in range(len(cuts) - 1):
            u, v = node_ids[k], node_ids[k + 1]
            if u == v:
                continue                      # a loop back onto the same junction
            sub = _slice(pts, cum, cuts[k][0] * total, cuts[k + 1][0] * total)
            # Anchor the ends on the node positions so the polyline the sim
            # follows starts and ends exactly where the graph says it does.
            sub[0] = (nodes[u][0], nodes[u][1])
            sub[-1] = (nodes[v][0], nodes[v][1])
            rp = _round_pts(sub)
            if len(rp) < 2:
                continue
            rec = _segment_record(f"{gers}#{k}", u, v, road_class, rp,
                                  direction, sidewalks=False)
            if rec["length"] < _MIN_SEGMENT_LENGTH_M:
                continue
            segs.append(rec)

    # Nodes no road ended up using (a connector clipped away with its road)
    # would be unroutable dead weight — drop them.
    used = set()
    for s in segs:
        used.add(s["u"])
        used.add(s["v"])
    nodes = {nid: p for nid, p in nodes.items() if nid in used}

    return _artifact(nodes, segs, source_label,
                     {"source_roads": len(getattr(ws, "roads", [])),
                      "split_roads": split_roads})


# -- the legacy fallback -----------------------------------------------------
def streetmap_from_polylines(roads: dict, source_label: str,
                             snap: float = 3.0) -> dict:
    """Upgrade a bundle's legacy ``roads.json`` polylines into a v2 streetmap.

    Used only where no Overture packet exists (the synthetic proving grounds).
    Endpoints within ``snap`` metres collapse onto a shared node, which is the
    best a geometry-only source allows — mid-polyline crossings stay unlinked.
    Unlike the version-1 bake this keeps the full polyline in ``pts``.
    """
    nodes: Dict[str, List[float]] = {}
    segs: List[dict] = []

    def key(p: Vec2) -> str:
        return f"n_{round(p[0] / snap)}_{round(p[1] / snap)}"

    for i, pl in enumerate(roads.get("polylines", [])):
        pts = [(float(q[0]), float(q[1])) for q in pl["points"]]
        if len(pts) < 2:
            continue
        u, v = key(pts[0]), key(pts[-1])
        if u == v:
            continue
        if u not in nodes:
            nodes[u] = [round(pts[0][0], 2), round(pts[0][1], 2)]
        if v not in nodes:
            nodes[v] = [round(pts[-1][0], 2), round(pts[-1][1], 2)]
        # Anchor the ends on the (snapped) node positions so the polyline the
        # sim follows starts and ends exactly where the graph says it does.
        anchored = [(nodes[u][0], nodes[u][1])] + pts[1:-1] + \
                   [(nodes[v][0], nodes[v][1])]
        rp = _round_pts(anchored)
        if len(rp) < 2:
            continue
        direction = (Direction.FORWARD if pl.get("oneway")
                     else Direction.BIDIRECTIONAL)
        segs.append(_segment_record(f"seg{i}", u, v,
                                    pl.get("class", "residential"), rp,
                                    direction, sidewalks=True))

    used = set()
    for s in segs:
        used.add(s["u"])
        used.add(s["v"])
    nodes = {nid: p for nid, p in nodes.items() if nid in used}
    return _artifact(nodes, segs, source_label,
                     {"source_polylines": len(roads.get("polylines", []))})

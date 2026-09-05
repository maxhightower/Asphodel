"""MobilityGraph — the authoritative city mobility topology (AS-NAV-0, §5).

Directed, mode-aware routing over :class:`RoadSegment`s with runtime-mutable
costs. The graph says where an agent CAN go; it never decides where an agent
wants to go (that is the planner) and never moves an entity (that is physics).

Key capabilities:
  * directed traversal (one-way support) — §5.1
  * separate pedestrian vs vehicle routing via per-mode access — §5.2
  * building connectors from an entrance to the nearest road node — §5.3
  * mutable dynamic state (congestion, obstructions, closures) that reroutes — §5.4
  * an importer that upgrades legacy undirected polylines into this graph.
"""
from __future__ import annotations

import heapq
import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .bake import streetmap_from_polylines
from .segments import Direction, Mode, RoadSegment, polyline_length
from .obstructions import MobilityObstruction

Vec2 = Tuple[float, float]


def _ring_cells(cx0: int, cz0: int, r: int):
    """The cells exactly ``r`` steps (Chebyshev) from (cx0, cz0), in order."""
    if r == 0:
        yield (cx0, cz0)
        return
    for cx in range(cx0 - r, cx0 + r + 1):
        yield (cx, cz0 - r)
        yield (cx, cz0 + r)
    for cz in range(cz0 - r + 1, cz0 + r):
        yield (cx0 - r, cz)
        yield (cx0 + r, cz)


@dataclass(frozen=True)
class Route:
    """A computed path: node sequence, segment sequence, distance and time."""

    nodes: List[str]
    segments: List[str]
    distance: float          # metres
    cost: float              # seconds (current dynamic cost)
    mode: Mode

    @property
    def ok(self) -> bool:
        return len(self.nodes) >= 1


class MobilityGraph:
    def __init__(self):
        self.nodes: Dict[str, Vec2] = {}
        self.segments: Dict[str, RoadSegment] = {}
        # node -> list of (to_node, seg_id, forward_along_polyline)
        self._adj: Dict[str, List[Tuple[str, str, bool]]] = {}
        self._obstructions: Dict[str, MobilityObstruction] = {}
        # Which streetmap this graph came from (set by from_artifact/load).
        self.source: Optional[str] = None
        self.version: Optional[int] = None
        # Lazily built bucket index over segment polylines (nearest_segment_point).
        self._grid: Optional[Dict[Tuple[int, int], List[str]]] = None
        self._grid_cell: float = 0.0
        self._grid_span: int = 0

    # -- construction --------------------------------------------------------
    def add_node(self, node_id: str, xy: Vec2) -> str:
        self.nodes[node_id] = (float(xy[0]), float(xy[1]))
        self._adj.setdefault(node_id, [])
        return node_id

    def add_segment(self, seg: RoadSegment, u: str, v: str) -> None:
        if u not in self.nodes or v not in self.nodes:
            raise KeyError("segment endpoints must be added as nodes first")
        self.segments[seg.id] = seg
        self._grid = None                      # geometry changed: reindex on demand
        d = seg.directionality
        if d in (Direction.BIDIRECTIONAL, Direction.FORWARD):
            self._adj[u].append((v, seg.id, True))
        if d in (Direction.BIDIRECTIONAL, Direction.BACKWARD):
            self._adj[v].append((u, seg.id, False))

    # -- queries -------------------------------------------------------------
    def nearest_node(self, xy: Vec2, mode: Optional[Mode] = None) -> Optional[str]:
        """Nearest graph node, optionally one touching a segment the mode can use."""
        best, bestd = None, math.inf
        for nid, p in self.nodes.items():
            if mode is not None and not self._node_serves_mode(nid, mode):
                continue
            d = (p[0] - xy[0]) ** 2 + (p[1] - xy[1]) ** 2
            if d < bestd:
                best, bestd = nid, d
        return best

    # -- nearest point on the street network ---------------------------------
    _GRID_CELL_M = 64.0

    def _build_grid(self) -> None:
        """Bucket every segment polyline into a uniform grid (lazy, O(n))."""
        cell = self._GRID_CELL_M
        grid: Dict[Tuple[int, int], List[str]] = {}
        for sid, seg in self.segments.items():
            pl = seg.polyline
            for a, b in zip(pl, pl[1:]):
                # Stamp the cells the sub-segment's bounding box touches. Road
                # sub-segments are short relative to the cell, so this stays
                # near-constant work per edge.
                cx0 = int(math.floor(min(a[0], b[0]) / cell))
                cx1 = int(math.floor(max(a[0], b[0]) / cell))
                cz0 = int(math.floor(min(a[1], b[1]) / cell))
                cz1 = int(math.floor(max(a[1], b[1]) / cell))
                for cx in range(cx0, cx1 + 1):
                    for cz in range(cz0, cz1 + 1):
                        bucket = grid.setdefault((cx, cz), [])
                        if not bucket or bucket[-1] != sid:
                            bucket.append(sid)
        # De-duplicate and sort so ties break identically every run.
        self._grid = {k: sorted(set(v)) for k, v in grid.items()}
        self._grid_cell = cell
        if grid:
            xs = [k[0] for k in grid]
            zs = [k[1] for k in grid]
            self._grid_span = max(max(xs) - min(xs), max(zs) - min(zs)) + 2
        else:
            self._grid_span = 0

    @staticmethod
    def _project_on_polyline(pts: Sequence[Vec2], xy: Vec2
                             ) -> Tuple[Vec2, float]:
        """Closest point on a polyline to ``xy`` and its squared distance."""
        best: Vec2 = (pts[0][0], pts[0][1])
        bestd = math.inf
        px, pz = xy[0], xy[1]
        for a, b in zip(pts, pts[1:]):
            dx, dz = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dz * dz
            if L2 <= 0.0:
                t = 0.0
            else:
                t = ((px - a[0]) * dx + (pz - a[1]) * dz) / L2
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            qx, qz = a[0] + dx * t, a[1] + dz * t
            d = (qx - px) ** 2 + (qz - pz) ** 2
            if d < bestd:
                best, bestd = (qx, qz), d
        return best, bestd

    def nearest_segment_point(self, xy: Vec2, mode: Optional[Mode] = None
                              ) -> Optional[Tuple[str, Vec2, float]]:
        """Project ``xy`` onto the nearest segment polyline.

        Returns ``(segment_id, (x, z), distance)`` or ``None`` when nothing is
        reachable for ``mode``. This is the "where on the street am I" query —
        an agent leaving a building, a wreck landing on a carriageway, a
        parity check against the rendered ribbons — and is why v2 keeps the
        polyline: snapping to the nearest *node* would land you at a junction
        that can be hundreds of metres away.

        The bucket index is built on first use and reused afterwards; rings of
        cells are searched outward until the ring's own distance floor exceeds
        the best hit, so the answer is exact, not approximate.
        """
        if not self.segments:
            return None
        if self._grid is None:
            self._build_grid()
        cell = self._grid_cell
        cx0 = int(math.floor(xy[0] / cell))
        cz0 = int(math.floor(xy[1] / cell))
        best_sid: Optional[str] = None
        best_pt: Vec2 = (0.0, 0.0)
        bestd = math.inf
        seen = set()
        max_ring = self._grid_span
        for r in range(0, max_ring + 1):
            # A cell in ring r is at least (r-1)*cell away; once that floor
            # beats the best hit no further ring can improve it.
            if best_sid is not None and ((r - 1) * cell) ** 2 > bestd:
                break
            for cx, cz in _ring_cells(cx0, cz0, r):
                bucket = self._grid.get((cx, cz))
                if not bucket:
                    continue
                for sid in bucket:
                    if sid in seen:
                        continue
                    seen.add(sid)
                    seg = self.segments[sid]
                    if mode is not None and not seg.allows(mode):
                        continue
                    pt, d = self._project_on_polyline(seg.polyline, xy)
                    if d < bestd or (d == bestd and (
                            best_sid is None or sid < best_sid)):
                        best_sid, best_pt, bestd = sid, pt, d
        if best_sid is None:
            # Query far outside the indexed extent (or every near segment is
            # closed to the mode): one exact scan beats an unbounded expansion.
            for sid in sorted(self.segments):
                seg = self.segments[sid]
                if mode is not None and not seg.allows(mode):
                    continue
                pt, d = self._project_on_polyline(seg.polyline, xy)
                if d < bestd:
                    best_sid, best_pt, bestd = sid, pt, d
        if best_sid is None:
            return None
        return best_sid, best_pt, math.sqrt(bestd)

    def _node_serves_mode(self, nid: str, mode: Mode) -> bool:
        for _, sid, _ in self._adj.get(nid, []):
            if self.segments[sid].allows(mode):
                return True
        return False

    def route(self, origin: str, dest: str, mode: Mode) -> Optional[Route]:
        """Least-time route for ``mode`` under CURRENT dynamic costs (Dijkstra).

        Returns ``None`` if no path exists for the mode (e.g. everything is
        closed). Edges whose cost is infinite (closed to the mode) are skipped,
        so closures and obstructions reroute automatically.
        """
        if origin not in self.nodes or dest not in self.nodes:
            return None
        if origin == dest:
            return Route([origin], [], 0.0, 0.0, mode)
        dist: Dict[str, float] = {origin: 0.0}
        prev: Dict[str, Tuple[str, str]] = {}
        pq: List[Tuple[float, str]] = [(0.0, origin)]
        visited = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            if u == dest:
                break
            for (w, sid, _fwd) in self._adj.get(u, []):
                seg = self.segments[sid]
                c = seg.traverse_cost(mode)
                if not math.isfinite(c):
                    continue
                nd = d + c
                if nd < dist.get(w, math.inf):
                    dist[w] = nd
                    prev[w] = (u, sid)
                    heapq.heappush(pq, (nd, w))
        if dest not in dist:
            return None
        # Reconstruct.
        nodes = [dest]
        seg_ids: List[str] = []
        cur = dest
        while cur != origin:
            pu, psid = prev[cur]
            seg_ids.append(psid)
            nodes.append(pu)
            cur = pu
        nodes.reverse()
        seg_ids.reverse()
        distance = sum(self.segments[s].length for s in seg_ids)
        return Route(nodes, seg_ids, distance, dist[dest], mode)

    # -- dynamic state (§5.4, §10) ------------------------------------------
    def apply_obstruction(self, obs: MobilityObstruction) -> None:
        if obs.affected_segment not in self.segments:
            raise KeyError(f"no segment {obs.affected_segment!r} to obstruct")
        self._obstructions[obs.id] = obs
        self._recompute_segment(obs.affected_segment)

    def clear_obstruction(self, obs_id: str) -> None:
        obs = self._obstructions.pop(obs_id, None)
        if obs is not None:
            self._recompute_segment(obs.affected_segment)

    def set_congestion(self, seg_id: str, factor: float) -> None:
        self.segments[seg_id].dynamic_state.congestion = max(1.0, factor)

    def _recompute_segment(self, seg_id: str) -> None:
        seg = self.segments[seg_id]
        ds = seg.dynamic_state
        active = [o for o in self._obstructions.values()
                  if o.affected_segment == seg_id]
        ds.blocked_fraction = min(1.0, sum(o.blocked_fraction() for o in active))
        closed = set()
        for o in active:
            closed |= o.closed_modes()
        ds.closed_modes = closed
        ds.obstruction_ids = {o.id for o in active}

    # -- building connectors (§5.3) -----------------------------------------
    def attach_building(self, building_id: str, entrance_xy: Vec2,
                        modes: Sequence[Mode] = (Mode.FOOT,),
                        connector_class: str = "connector") -> Optional[str]:
        """Add an entrance node connected to the nearest road node.

        Returns the new entrance node id, or None if the graph is empty. The
        connector is a short bidirectional segment; pedestrians (and, for a
        driveway, vehicles) can therefore route building -> road and back.
        """
        target = self.nearest_node(entrance_xy)
        if target is None:
            return None
        ent_id = f"bldg:{building_id}"
        self.add_node(ent_id, entrance_xy)
        seg = RoadSegment(
            id=f"conn:{building_id}",
            polyline=[entrance_xy, self.nodes[target]],
            road_class=connector_class,
            allowed_modes=set(modes),
        )
        self.add_segment(seg, ent_id, target)
        return ent_id

    # -- load a baked mobility artifact -------------------------------------
    @classmethod
    def from_artifact(cls, art: dict) -> "MobilityGraph":
        """Rebuild the graph from a bundle's ``streetmap.json``.

        Two schema versions are accepted, and only two — an unrecognised or
        missing ``version`` raises rather than silently loading a graph whose
        geometry means something else (fail loudly at the artifact boundary):

        * **1** — legacy: no per-segment geometry, so each segment is rebuilt
          as the straight line between its two nodes. Lengths here can differ
          from what the renderer draws; that divergence is why v2 exists.
        * **2** — canonical: ``pts`` carries the segment's own polyline,
          already oriented ``u -> v``, so Python and the client measure the
          same street.
        """
        version = art.get("version")
        if version is None:
            raise ValueError(
                "streetmap artifact has no 'version' field; expected 1 or 2. "
                "Re-bake it with asphodel.mobility.bake.")
        version = str(version)
        if version not in ("1", "2"):
            raise ValueError(
                f"unsupported streetmap version {version!r}; this build reads "
                "version 1 (legacy 2-point) or 2 (polyline). Re-bake it with "
                "asphodel.mobility.bake.")

        g = cls()
        g.source = art.get("source")
        g.version = int(version)
        for nid, xy in art["nodes"].items():
            g.add_node(nid, (float(xy[0]), float(xy[1])))
        for s in art["segments"]:
            u, v = s["u"], s["v"]
            if u is None or v is None:
                continue
            modes = {Mode(m) for m in s.get("modes", [])} or None
            pts = s.get("pts") if version == "2" else None
            if pts:
                polyline = [(float(p[0]), float(p[1])) for p in pts]
            else:
                polyline = [g.nodes[u], g.nodes[v]]
            seg = RoadSegment(
                id=s["id"],
                polyline=polyline,
                road_class=s.get("class", "residential"),
                directionality=Direction(s.get("directionality", "bidirectional")),
                allowed_modes=modes,
                speed_limit=s.get("speed_limit"),
                lanes=s.get("lanes"),
            )
            g.add_segment(seg, u, v)
        return g

    @classmethod
    def load(cls, bundle_dir: str) -> "MobilityGraph":
        """Load a bundle's mobility graph, preferring the baked streetmap.

        ``streetmap.json`` is authoritative when present. A bundle that has
        never been baked (or one whose packet we cannot reach) falls back to
        upgrading its legacy ``roads.json`` polylines in memory, so the sim
        still runs — degraded, and it says so via ``graph.source``.
        """
        path = os.path.join(bundle_dir, "streetmap.json")
        if os.path.exists(path):
            with open(path) as f:
                art = json.load(f)
            g = cls.from_artifact(art)
            g.source = art.get("source") or f"streetmap.json v{g.version}"
            return g

        roads_path = os.path.join(bundle_dir, "roads.json")
        if not os.path.exists(roads_path):
            raise FileNotFoundError(
                f"{bundle_dir} has neither streetmap.json nor roads.json")
        with open(roads_path) as f:
            roads = json.load(f)
        art = streetmap_from_polylines(roads, "roads.json (fallback)")
        g = cls.from_artifact(art)
        g.source = art["source"]
        return g

    # -- import from legacy polylines ---------------------------------------
    @classmethod
    def from_polylines(cls, polylines: Sequence[dict], snap: float = 2.0
                       ) -> "MobilityGraph":
        """Upgrade legacy roads.json polylines into a routable directed graph.

        Each polyline becomes one segment between its snapped endpoints; endpoints
        within ``snap`` metres collapse to a shared node, so crossing roads form
        intersections. Bridges the audit gap that bundle roads were non-routable.
        """
        g = cls()

        def key(p: Vec2) -> str:
            return f"n_{round(p[0] / snap)}_{round(p[1] / snap)}"

        for i, pl in enumerate(polylines):
            pts = [tuple(map(float, q)) for q in pl["points"]]
            if len(pts) < 2:
                continue
            u, v = key(pts[0]), key(pts[-1])
            if u == v:
                continue
            if u not in g.nodes:
                g.add_node(u, pts[0])
            if v not in g.nodes:
                g.add_node(v, pts[-1])
            rc = pl.get("class", "residential")
            direction = Direction.FORWARD if pl.get("oneway") else Direction.BIDIRECTIONAL
            seg = RoadSegment(id=f"seg{i}", polyline=pts, road_class=rc,
                              directionality=direction)
            g.add_segment(seg, u, v)
        return g

    # -- introspection -------------------------------------------------------
    def stats(self) -> dict:
        directed_edges = sum(len(v) for v in self._adj.values())
        return {
            "nodes": len(self.nodes),
            "segments": len(self.segments),
            "directed_edges": directed_edges,
            "obstructions": len(self._obstructions),
        }

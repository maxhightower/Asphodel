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
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .segments import Direction, Mode, RoadSegment, polyline_length
from .obstructions import MobilityObstruction

Vec2 = Tuple[float, float]


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

    # -- construction --------------------------------------------------------
    def add_node(self, node_id: str, xy: Vec2) -> str:
        self.nodes[node_id] = (float(xy[0]), float(xy[1]))
        self._adj.setdefault(node_id, [])
        return node_id

    def add_segment(self, seg: RoadSegment, u: str, v: str) -> None:
        if u not in self.nodes or v not in self.nodes:
            raise KeyError("segment endpoints must be added as nodes first")
        self.segments[seg.id] = seg
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

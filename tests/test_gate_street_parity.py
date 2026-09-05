"""Gate C — street/mobility parity between the routable and the rendered city.

The whole point of baking ``streetmap.json`` from the same Overture packet the
exterior compiler consumes is that the two artifacts describe ONE city: every
street an agent can route over is a street the client draws, and every street
the client draws is one an agent can route over. This gate measures that in
both directions against the compiled chunks, in bundle metres.

Chunk geometry note (verified against ``world/world_meta.json``): a chunk's
``roads[*]["pts"]`` are ABSOLUTE bundle metres, not offsets from the chunk
``origin`` — the origin is ``bounds_m`` plus ``chunk_size_m`` steps and the
road points bracket it.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import random
from typing import Dict, List, Optional, Tuple

import pytest

from asphodel.mobility import MobilityGraph

BUNDLES = os.path.join(os.path.dirname(__file__), os.pardir, "godot", "bundles")

TOLERANCE_M = 4.0
SAMPLES = 300
REQUIRED_FRACTION = 0.99


def _bundle_ready(city: str) -> bool:
    root = os.path.join(BUNDLES, city)
    return (os.path.exists(os.path.join(root, "streetmap.json"))
            and os.path.exists(os.path.join(root, "world", "world_meta.json"))
            and os.path.isdir(os.path.join(root, "world", "chunks")))


class _ChunkGrid:
    """The compiled chunk grid, with lazily loaded (and cached) chunk roads."""

    def __init__(self, bundle_dir: str):
        self.root = os.path.join(bundle_dir, "world")
        with open(os.path.join(self.root, "world_meta.json")) as f:
            meta = json.load(f)
        self.min_x, self.min_z, self.max_x, self.max_z = meta["bounds_m"]
        self.size = float(meta["chunk_size_m"])
        self.cols = int(meta["chunk_grid"]["cols"])
        self.rows = int(meta["chunk_grid"]["rows"])
        self._cache: Dict[Tuple[int, int], List[List[List[float]]]] = {}

    def chunk_of(self, x: float, z: float) -> Tuple[int, int]:
        cx = int(math.floor((x - self.min_x) / self.size))
        cz = int(math.floor((z - self.min_z) / self.size))
        cx = max(0, min(self.cols - 1, cx))
        cz = max(0, min(self.rows - 1, cz))
        return cx, cz

    def origin(self, cx: int, cz: int) -> Tuple[float, float]:
        return self.min_x + cx * self.size, self.min_z + cz * self.size

    def contains(self, x: float, z: float) -> bool:
        """Is this point inside the compiled chunk grid (i.e. rendered at all)?"""
        return (self.min_x <= x <= self.min_x + self.cols * self.size
                and self.min_z <= z <= self.min_z + self.rows * self.size)

    def roads(self, cx: int, cz: int) -> List[List[List[float]]]:
        key = (cx, cz)
        if key not in self._cache:
            path = os.path.join(self.root, "chunks", f"c_{cx}_{cz}.json.gz")
            pts: List[List[List[float]]] = []
            if os.path.exists(path):
                with gzip.open(path, "rt") as f:
                    chunk = json.load(f)
                pts = [r["pts"] for r in chunk.get("roads", [])
                       if len(r.get("pts", [])) >= 2]
            self._cache[key] = pts
        return self._cache[key]

    def existing_keys(self) -> List[Tuple[int, int]]:
        out = []
        for name in sorted(os.listdir(os.path.join(self.root, "chunks"))):
            if not name.startswith("c_") or not name.endswith(".json.gz"):
                continue
            cx, cz = name[2:-8].split("_")
            out.append((int(cx), int(cz)))
        return out


def _midpoint(pts) -> Tuple[float, float]:
    """The point half-way along a polyline by arc length."""
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    half = cum[-1] / 2.0
    if cum[-1] <= 0.0:
        return (float(pts[0][0]), float(pts[0][1]))
    for k in range(len(pts) - 1):
        if cum[k + 1] >= half:
            span = cum[k + 1] - cum[k]
            t = 0.0 if span <= 0 else (half - cum[k]) / span
            return (pts[k][0] + (pts[k + 1][0] - pts[k][0]) * t,
                    pts[k][1] + (pts[k + 1][1] - pts[k][1]) * t)
    return (float(pts[-1][0]), float(pts[-1][1]))


def _dist_to_polyline(pts, q) -> float:
    return math.sqrt(MobilityGraph._project_on_polyline(
        [(float(p[0]), float(p[1])) for p in pts], q)[1])


def parity_fractions(bundle_dir: str, graph: MobilityGraph,
                     n: int = SAMPLES, seed: int = 0) -> Tuple[float, float]:
    """Measure street/mobility parity in both directions.

    Returns ``(streetmap_to_chunks, chunks_to_streetmap)`` — the fraction of
    ``n`` deterministically sampled streetmap segment midpoints that lie within
    ``TOLERANCE_M`` of a rendered chunk road polyline, and the fraction of
    ``n`` sampled chunk road midpoints that lie within ``TOLERANCE_M`` of a
    streetmap segment. Both are in [0, 1]; 1.0 means the two artifacts describe
    the same streets everywhere they were sampled.

    Only streetmap segments whose midpoint falls INSIDE the compiled chunk grid
    are sampled. The raw Overture packet is downloaded on a slightly larger bbox
    than the bundle covers, so ~3% of baked segments sit past the last chunk and
    were never rendered; scoring them would measure the download bbox, not
    parity. ``out_of_extent_fraction`` reports that share separately.
    """
    grid = _ChunkGrid(bundle_dir)

    # -- streetmap -> chunks -------------------------------------------------
    rng = random.Random(seed)
    mids = {sid: _midpoint(graph.segments[sid].polyline)
            for sid in sorted(graph.segments)}
    seg_ids = [sid for sid, m in mids.items() if grid.contains(m[0], m[1])]
    picks = (seg_ids if len(seg_ids) <= n
             else rng.sample(seg_ids, n))
    hits = 0
    for sid in picks:
        mid = mids[sid]
        cx, cz = grid.chunk_of(mid[0], mid[1])
        best = min((_dist_to_polyline(r, mid) for r in grid.roads(cx, cz)),
                   default=math.inf)
        if best <= TOLERANCE_M:
            hits += 1
    fwd = hits / float(len(picks)) if picks else 0.0

    # -- chunks -> streetmap -------------------------------------------------
    rng = random.Random(seed)
    keys = grid.existing_keys()
    rev_hits = 0
    rev_total = 0
    tried = 0
    # Walk chunks in a deterministic shuffled order, taking one road sub-segment
    # from each until n samples are collected, so the samples spread over the map.
    order = list(keys)
    rng.shuffle(order)
    while rev_total < n and tried < 20 * n and order:
        key = order[tried % len(order)]
        tried += 1
        roads = grid.roads(*key)
        if not roads:
            continue
        road = roads[rng.randrange(len(roads))]
        k = rng.randrange(len(road) - 1)
        a, b = road[k], road[k + 1]
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        hit = graph.nearest_segment_point(mid)
        rev_total += 1
        if hit is not None and hit[2] <= TOLERANCE_M:
            rev_hits += 1
    rev = rev_hits / float(rev_total) if rev_total else 0.0
    return fwd, rev


def out_of_extent_fraction(bundle_dir: str, graph: MobilityGraph) -> float:
    """Share of baked segments whose midpoint the compiler never rendered."""
    grid = _ChunkGrid(bundle_dir)
    if not graph.segments:
        return 0.0
    out = 0
    for seg in graph.segments.values():
        m = _midpoint(seg.polyline)
        if not grid.contains(m[0], m[1]):
            out += 1
    return out / float(len(graph.segments))


def _graph(city: str) -> MobilityGraph:
    return MobilityGraph.load(os.path.join(BUNDLES, city))


@pytest.mark.parametrize("city", ["houston", "madisonville_tx"])
def test_chunk_road_points_are_absolute_bundle_metres(city):
    """The premise the gate rests on: chunk road pts are NOT chunk-local."""
    if not _bundle_ready(city):
        pytest.skip(f"{city} bundle/world not baked in this tree")
    grid = _ChunkGrid(os.path.join(BUNDLES, city))
    checked = 0
    for cx, cz in grid.existing_keys():
        roads = grid.roads(cx, cz)
        if not roads:
            continue
        ox, oz = grid.origin(cx, cz)
        pad = 32.0
        for road in roads:
            for x, z in road:
                assert ox - pad <= x <= ox + grid.size + pad
                assert oz - pad <= z <= oz + grid.size + pad
        checked += 1
        if checked >= 12:
            break
    assert checked > 0


@pytest.mark.parametrize("city", ["houston", "madisonville_tx"])
def test_gate_c_streetmap_segments_are_rendered_streets(city):
    if not _bundle_ready(city):
        pytest.skip(f"{city} bundle/world not baked in this tree")
    g = _graph(city)
    fwd, rev = parity_fractions(os.path.join(BUNDLES, city), g,
                                n=SAMPLES, seed=0)
    print(f"\n[gate-c {city}] streetmap->chunks {fwd * 100:.2f}%  "
          f"chunks->streetmap {rev * 100:.2f}%  (n={SAMPLES}, tol={TOLERANCE_M} m)")
    assert fwd >= REQUIRED_FRACTION, (
        f"{city}: only {fwd * 100:.2f}% of streetmap midpoints are within "
        f"{TOLERANCE_M} m of a rendered chunk road")


@pytest.mark.parametrize("city", ["houston", "madisonville_tx"])
def test_gate_c_rendered_streets_are_routable(city):
    if not _bundle_ready(city):
        pytest.skip(f"{city} bundle/world not baked in this tree")
    g = _graph(city)
    fwd, rev = parity_fractions(os.path.join(BUNDLES, city), g,
                                n=SAMPLES, seed=0)
    print(f"\n[gate-c {city}] streetmap->chunks {fwd * 100:.2f}%  "
          f"chunks->streetmap {rev * 100:.2f}%  (n={SAMPLES}, tol={TOLERANCE_M} m)")
    assert rev >= REQUIRED_FRACTION, (
        f"{city}: only {rev * 100:.2f}% of rendered chunk road midpoints are "
        f"within {TOLERANCE_M} m of a routable streetmap segment")


@pytest.mark.parametrize("city", ["houston", "madisonville_tx"])
def test_baked_streetmap_is_the_overture_bake(city):
    """A bundle with a packet must not be running on the legacy fallback."""
    if not _bundle_ready(city):
        pytest.skip(f"{city} bundle/world not baked in this tree")
    g = _graph(city)
    assert g.version == 2
    assert g.source and "overture" in g.source
    # The packet's download bbox overhangs the compiled world a little; that
    # overhang must stay a rounding error, not a second unrendered city.
    out = out_of_extent_fraction(os.path.join(BUNDLES, city), g)
    print(f"\n[gate-c {city}] segments outside the compiled extent: "
          f"{out * 100:.2f}%")
    assert out < 0.05

"""
The spatial world a city resolves into: a street graph + categorised building
footprints + procedural interiors.

This is the layer that turns a ``CityProfile`` (which only says *which* city and
how to source it) into an actual populated map that NPCs live in.  The end-goal
pipeline is:

    choose a city  ->  populate from OpenStreetMap  ->  procedural interiors
                   ->  NPCs spawn into real buildings and route on real streets

and this module owns everything except the NPC spawn itself (which lives in
``citizen.py`` and consumes a ``CityWorld``).

Two sources, one shape
----------------------
A ``StreetMap`` can come from either:

* **OpenStreetMap** (``load_osm``) -- the real thing: street ways become the
  graph, building footprints become ``Building``s, and OSM tags
  (``amenity`` / ``shop`` / ``landuse`` / ``building`` ...) are mapped to the
  same workplace categories the occupations use.  This is a lazily-imported
  adapter seam so the package has no hard GIS dependency.
* **Procedural synthesis** (``synthesize_city``) -- a deterministic, dependency
  -light stand-in that builds a gridded street network and zoned building stock
  from a seed.  It lets the world "populate" and the whole pipeline run + be
  tested offline, and it doubles as the procedural-generation path for areas
  OSM doesn't cover.

Both produce the identical ``StreetMap`` / ``Building`` types, so everything
downstream (interiors, NPC spawn, routing) is source-agnostic.

Coordinates are a local planar metre frame (x east, y north); an OSM loader is
expected to project lon/lat into such a frame.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np


# ===========================================================================
# Building categories  <->  OSM tags  <->  occupation workplace keys
# ===========================================================================
# These category keys are exactly the ``Occupation.workplace`` keys used by the
# spawn catalog, so a building "hosts" an occupation iff its category matches.
RESIDENTIAL = "residential"
COMMERCIAL = "commercial"
MEDICAL = "medical"
EDUCATION = "education"
CIVIC = "civic"
INDUSTRIAL = "industrial"
TRANSIT = "transit"

ALL_CATEGORIES = (RESIDENTIAL, COMMERCIAL, MEDICAL, EDUCATION, CIVIC,
                  INDUSTRIAL, TRANSIT)

# Road-structure classes carried per street segment.  They drive both the
# traffic chokepoints (bridges/tunnels have less capacity, highways more) and
# the location-aware travel events (caught on a flyover / in a tunnel / ...).
# Surface is the default for any untagged segment.
SURFACE = "surface"
HIGHWAY = "highway"
BRIDGE = "bridge"
TUNNEL = "tunnel"
RAMP = "ramp"
ROAD_STRUCTURES = (SURFACE, HIGHWAY, BRIDGE, TUNNEL, RAMP)


def structure_from_osm_tags(tags: dict) -> str:
    """Map an OSM way's tags to a road structure (for the real-city loader)."""
    if tags.get("tunnel") in ("yes", "building_passage") or tags.get("covered") == "yes":
        return TUNNEL
    if tags.get("bridge") in ("yes", "viaduct", "aqueduct"):
        return BRIDGE
    hw = tags.get("highway", "")
    if hw in ("motorway_link", "trunk_link", "primary_link", "secondary_link"):
        return RAMP
    if hw in ("motorway", "trunk"):
        return HIGHWAY
    return SURFACE


# Rough usable floor area per occupant, per category (m^2).  Drives capacity,
# which in turn weights how likely a citizen lives / works in a given building.
AREA_PER_OCCUPANT = {
    RESIDENTIAL: 45.0, COMMERCIAL: 20.0, MEDICAL: 30.0, EDUCATION: 15.0,
    CIVIC: 25.0, INDUSTRIAL: 60.0, TRANSIT: 80.0,
}

# Typical building heights (levels) per category, for the synth generator.
LEVELS_RANGE = {
    RESIDENTIAL: (1, 5), COMMERCIAL: (1, 12), MEDICAL: (2, 8),
    EDUCATION: (1, 4), CIVIC: (1, 6), INDUSTRIAL: (1, 2), TRANSIT: (1, 2),
}


def category_from_osm_tags(tags: dict) -> Optional[str]:
    """Map a building/feature's OSM tags to one of our categories (or None).

    Deliberately small but representative -- the precedence below resolves the
    common ambiguities (a hospital tagged both ``building=yes`` and
    ``amenity=hospital`` is medical, not residential).  Extend the tables as the
    real OSM ingestion matures.
    """
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    office = tags.get("office", "")
    landuse = tags.get("landuse", "")
    building = tags.get("building", "")
    healthcare = tags.get("healthcare", "")
    public_transport = tags.get("public_transport", "")
    railway = tags.get("railway", "")

    # Most specific first.
    if amenity in {"hospital", "clinic", "doctors", "pharmacy"} or healthcare:
        return MEDICAL
    if amenity in {"school", "university", "college", "kindergarten", "library"} \
            or building in {"school", "university", "college"}:
        return EDUCATION
    if amenity in {"police", "fire_station", "townhall", "courthouse", "prison"} \
            or office == "government" or building in {"civic", "government"}:
        return CIVIC
    if amenity in {"bus_station", "ferry_terminal"} \
            or public_transport in {"station", "stop_position"} \
            or railway in {"station", "halt"} or building in {"train_station"}:
        return TRANSIT
    if landuse in {"industrial", "port", "depot"} \
            or building in {"industrial", "warehouse", "factory"}:
        return INDUSTRIAL
    if shop or office or amenity in {"restaurant", "cafe", "bar", "fast_food",
                                     "marketplace", "bank"} \
            or building in {"retail", "commercial", "office", "supermarket"} \
            or landuse in {"retail", "commercial"}:
        return COMMERCIAL
    if building in {"house", "apartments", "residential", "detached", "terrace",
                    "dormitory", "bungalow"} or landuse == "residential":
        return RESIDENTIAL
    if "building" in tags:
        # A real but unrecognised building footprint: default to residential
        # (the common case for generically-tagged buildings in OSM).
        return RESIDENTIAL
    return None


# ===========================================================================
# Buildings, interiors, the street map
# ===========================================================================
@dataclass
class Room:
    """One procedurally-generated room on a building floor (local metres)."""

    name: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class Interior:
    """A building's procedural interior: rooms per floor plus entrance points."""

    levels: list[list[Room]] = field(default_factory=list)   # rooms per floor
    entrances: list[tuple[float, float]] = field(default_factory=list)

    @property
    def room_count(self) -> int:
        return sum(len(floor) for floor in self.levels)


@dataclass
class Building:
    """A categorised building footprint -- a place a citizen can live or work."""

    id: int
    category: str                       # one of ALL_CATEGORIES
    footprint: list[tuple[float, float]]  # polygon ring, local metres
    centroid: tuple[float, float]
    area: float                         # footprint area (m^2)
    levels: int                         # number of floors
    neighborhood: str                   # emergent "district" label
    street_node: int                    # nearest street-graph node id
    name: str = ""                      # address / POI name when known
    interior: Optional[Interior] = None  # filled lazily by generate_interior

    @property
    def is_residential(self) -> bool:
        return self.category == RESIDENTIAL

    @property
    def workplaces(self) -> list[str]:
        """Workplace categories this building hosts (empty for housing)."""
        return [] if self.category == RESIDENTIAL else [self.category]

    @property
    def capacity(self) -> int:
        """How many occupants the building holds -- the spawn weight."""
        dens = AREA_PER_OCCUPANT.get(self.category, 40.0)
        return max(1, int(round(self.area * self.levels / dens)))

    def label(self) -> str:
        return self.name or f"{self.category}#{self.id}"


@dataclass
class StreetMap:
    """A street graph plus the building stock that hangs off it.

    The graph is generic (works for both synthesised grids and OSM ways): nodes
    are points, edges carry a length, and ``route_length`` is Dijkstra over edge
    lengths so journey costs are real walking distances, not Euclidean cheats.
    """

    nodes: dict[int, tuple[float, float]]          # node id -> (x, y) metres
    edges: list[tuple[int, int, float]]            # (u, v, length)
    buildings: list[Building]
    bbox: tuple[float, float, float, float]        # (xmin, ymin, xmax, ymax)
    source: str = "synthetic"                      # "osm:<place>" or "synthetic"
    # Per-segment attributes, keyed by the canonical (min,max) node pair; the
    # only attribute used today is {"structure": <SURFACE|HIGHWAY|...>}.
    edge_attrs: dict[tuple[int, int], dict] = field(default_factory=dict)

    def edge_structure(self, u: int, v: int) -> str:
        key = (u, v) if u <= v else (v, u)
        return self.edge_attrs.get(key, {}).get("structure", SURFACE)

    # -- adjacency (built lazily for routing) --------------------------------
    def _adjacency(self) -> dict[int, list[tuple[int, float]]]:
        adj = getattr(self, "_adj_cache", None)
        if adj is None:
            adj = {n: [] for n in self.nodes}
            for u, v, w in self.edges:
                adj[u].append((v, w))
                adj[v].append((u, w))
            self._adj_cache = adj
        return adj

    def nearest_node(self, xy: tuple[float, float]) -> int:
        x, y = xy
        return min(self.nodes,
                   key=lambda n: (self.nodes[n][0] - x) ** 2
                   + (self.nodes[n][1] - y) ** 2)

    def route_length(self, a_node: int, b_node: int) -> float:
        """Shortest street-distance between two nodes (inf if disconnected)."""
        if a_node == b_node:
            return 0.0
        adj = self._adjacency()
        dist = {a_node: 0.0}
        pq = [(0.0, a_node)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b_node:
                return d
            if d > dist.get(u, math.inf):
                continue
            for v, w in adj[u]:
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        return math.inf

    # -- queries over the building stock -------------------------------------
    def residential_buildings(self) -> list[Building]:
        return [b for b in self.buildings if b.is_residential]

    def buildings_hosting(self, category: str) -> list[Building]:
        return [b for b in self.buildings if category in b.workplaces]

    def categories_present(self) -> set[str]:
        return {b.category for b in self.buildings}

    def category_capacity(self) -> dict[str, float]:
        """Total occupant capacity per building category (cached).

        This is the city's real *building-stock composition*: a downtown thick
        with offices has a large ``commercial`` capacity, an industrial port a
        large ``industrial`` one. The citizen spawner weights occupation
        prevalence by it, so different cities yield materially different
        populations rather than one generic mix.
        """
        cache = getattr(self, "_cat_cap_cache", None)
        if cache is None:
            cache = {}
            for b in self.buildings:
                cache[b.category] = cache.get(b.category, 0.0) + float(b.capacity)
            self._cat_cap_cache = cache
        return cache

    def by_id(self) -> dict[int, Building]:
        return {b.id: b for b in self.buildings}


# ===========================================================================
# Source 1: OpenStreetMap  (lazily-imported adapter seam)
# ===========================================================================
@dataclass
class OSMSource:
    """How to source a real city from OpenStreetMap.

    Exactly one locator should be set.  ``network`` must be enabled for live
    Overpass/`osmnx` fetches; ``pbf_path`` reads a local extract offline.
    """

    place: str = ""                     # e.g. "Trondheim, Norway"
    bbox: Optional[tuple[float, float, float, float]] = None  # (S, W, N, E)
    pbf_path: str = ""                  # local .osm.pbf extract
    network_type: str = "walk"          # street graph type for routing
    network: bool = False               # allow live network fetch


def load_osm(source: OSMSource) -> StreetMap:
    """Build a ``StreetMap`` from OpenStreetMap.

    This is the integration seam for real-city ingestion.  It lazily imports a
    GIS toolchain (``osmnx`` / ``pyrosm`` + ``shapely``) so the rest of Asphodel
    stays dependency-light; the expected steps are documented inline.  Until the
    toolchain is wired, it raises a clear, actionable error rather than failing
    obscurely -- callers that just want a runnable world use ``synthesize_city``.
    """
    try:
        import osmnx as ox  # noqa: F401  (the intended toolchain)
    except Exception as exc:  # pragma: no cover - exercised only with OSM installed
        raise RuntimeError(
            "load_osm needs a GIS toolchain (osmnx + shapely) and, for live "
            "fetches, network access. Install it and set OSMSource.network=True "
            "or OSMSource.pbf_path=<extract>. For an offline runnable world use "
            "synthesize_city(...)."
        ) from exc

    # Intended implementation (kept as the spec for the seam):
    #   1. graph = ox.graph_from_place/from_bbox(..., network_type=source...)
    #      -> project to a local metre CRS -> StreetMap.nodes / .edges (length=)
    #   2. gdf   = ox.features_from_*(..., tags={"building": True, ...})
    #      -> for each footprint: category_from_osm_tags(tags); skip None;
    #         centroid+area in metres; levels from "building:levels"; nearest_node
    #   3. neighborhood from addr:suburb / admin boundary; name from name/addr
    raise NotImplementedError(
        "OSM ingestion seam is stubbed; choose a toolchain to wire it (see "
        "load_osm docstring). Use synthesize_city for now."
    )


# ===========================================================================
# Source 2: procedural synthesis  (deterministic, dependency-light)
# ===========================================================================
@dataclass
class SynthCitySpec:
    """Knobs for the procedural city generator.

    ``zoning_weights`` biases how blocks are zoned -- this is where a city's
    character comes from offline (a harbor weights INDUSTRIAL/TRANSIT up, a
    university town EDUCATION).  Everything is deterministic in the spawn seed.
    """

    blocks_x: int = 6
    blocks_y: int = 6
    block_size: float = 120.0           # metres between street intersections
    buildings_per_block: int = 6
    zoning_weights: dict[str, float] = field(default_factory=lambda: {
        RESIDENTIAL: 6.0, COMMERCIAL: 2.0, EDUCATION: 0.8, MEDICAL: 0.5,
        CIVIC: 0.5, INDUSTRIAL: 0.8, TRANSIT: 0.4,
    })


# Quadrant names give blocks a human-readable "neighborhood" without OSM.
_QUADRANTS = ("North End", "East Side", "South Bank", "West Quarter", "Midtown")


def _quadrant(i: int, j: int, bx: int, by: int) -> str:
    cx, cy = (bx - 1) / 2.0, (by - 1) / 2.0
    if abs(i - cx) <= 0.75 and abs(j - cy) <= 0.75:
        return _QUADRANTS[4]
    if j >= cy and abs(i - cx) <= abs(j - cy):
        return _QUADRANTS[0]
    if i > cx and abs(i - cx) > abs(j - cy):
        return _QUADRANTS[1]
    if j < cy and abs(i - cx) <= abs(j - cy):
        return _QUADRANTS[2]
    return _QUADRANTS[3]


def synthesize_city(spec: SynthCitySpec, seed: int = 0,
                    name: str = "synthetic") -> StreetMap:
    """Generate a deterministic gridded city: streets + zoned buildings.

    A lattice of intersections forms the street graph; each block is zoned by a
    weighted draw and filled with ``buildings_per_block`` footprints whose
    category, size and height follow the zoning.  Identical (spec, seed) always
    yields the identical map.
    """
    rng = np.random.default_rng(seed)
    bx, by, bs = spec.blocks_x, spec.blocks_y, spec.block_size

    # --- street graph: lattice intersections + 4-neighbour street segments ---
    def node_id(i, j):
        return i * (by + 1) + j

    nodes: dict[int, tuple[float, float]] = {}
    for i in range(bx + 1):
        for j in range(by + 1):
            nodes[node_id(i, j)] = (i * bs, j * bs)
    edges: list[tuple[int, int, float]] = []
    for i in range(bx + 1):
        for j in range(by + 1):
            if i < bx:
                edges.append((node_id(i, j), node_id(i + 1, j), bs))
            if j < by:
                edges.append((node_id(i, j), node_id(i, j + 1), bs))

    cats = list(spec.zoning_weights)
    cat_w = np.array([spec.zoning_weights[c] for c in cats], dtype=float)
    cat_p = cat_w / cat_w.sum()

    buildings: list[Building] = []
    bid = 0
    margin = bs * 0.12                  # street setback inside each block
    for i in range(bx):
        for j in range(by):
            zone_cat = cats[int(rng.choice(len(cats), p=cat_p))]
            hood = _quadrant(i, j, bx, by)
            x0, y0 = i * bs + margin, j * bs + margin
            inner = bs - 2 * margin
            # Lay buildings on a small sub-grid within the block.
            per_side = max(1, int(round(math.sqrt(spec.buildings_per_block))))
            cell = inner / per_side
            for si in range(per_side):
                for sj in range(per_side):
                    if len(buildings) and rng.random() < 0.1:
                        continue        # occasional empty lot
                    # Most blocks are residential-dominant but mixed; non-res
                    # blocks still carry some housing so people live near work.
                    cat = zone_cat
                    if zone_cat != RESIDENTIAL and rng.random() < 0.35:
                        cat = RESIDENTIAL
                    fw = cell * float(rng.uniform(0.45, 0.8))
                    fh = cell * float(rng.uniform(0.45, 0.8))
                    px = x0 + si * cell + (cell - fw) * 0.5
                    py = y0 + sj * cell + (cell - fh) * 0.5
                    lo, hi = LEVELS_RANGE[cat]
                    levels = int(rng.integers(lo, hi + 1))
                    footprint = [(px, py), (px + fw, py),
                                 (px + fw, py + fh), (px, py + fh)]
                    cx, cy = px + fw / 2, py + fh / 2
                    snode = node_id(min(i + (si >= per_side / 2), bx),
                                    min(j + (sj >= per_side / 2), by))
                    buildings.append(Building(
                        id=bid, category=cat, footprint=footprint,
                        centroid=(cx, cy), area=fw * fh, levels=levels,
                        neighborhood=hood, street_node=snode,
                        name=f"{hood} {cat} {bid}",
                    ))
                    bid += 1

    # --- road structures: a ring-road, a river of bridges, a tunnel, ramps ---
    # Illustrative tagging (OSM supplies the real ones via structure_from_osm_tags)
    # but enough to drive chokepoint congestion and the location-aware travel
    # events.  Everything not tagged here stays SURFACE.
    def ekey(a, b):
        return (a, b) if a <= b else (b, a)

    edge_attrs: dict[tuple[int, int], dict] = {}
    # Perimeter ring road -> highway.
    for i in range(bx):
        edge_attrs[ekey(node_id(i, 0), node_id(i + 1, 0))] = {"structure": HIGHWAY}
        edge_attrs[ekey(node_id(i, by), node_id(i + 1, by))] = {"structure": HIGHWAY}
    for j in range(by):
        edge_attrs[ekey(node_id(0, j), node_id(0, j + 1))] = {"structure": HIGHWAY}
        edge_attrs[ekey(node_id(bx, j), node_id(bx, j + 1))] = {"structure": HIGHWAY}
    # A river along a mid latitude -> the segments crossing it are bridges.
    jr = by // 2
    if 0 < jr < by:
        for i in range(bx + 1):
            edge_attrs[ekey(node_id(i, jr), node_id(i, jr + 1))] = {"structure": BRIDGE}
    # A short tunnel run along an interior column.
    ct = max(1, bx // 3)
    for j in range(1, min(3, by)):
        edge_attrs[ekey(node_id(ct, j), node_id(ct, j + 1))] = {"structure": TUNNEL}
    # Ramps connecting the ring road to the interior near two corners.
    for (a, b) in (((1, 0), (1, 1)), ((bx - 1, by), (bx - 1, by - 1))):
        if 0 <= a[0] <= bx and 0 <= b[1] <= by:
            edge_attrs.setdefault(ekey(node_id(*a), node_id(*b)), {"structure": RAMP})

    bbox = (0.0, 0.0, bx * bs, by * bs)
    return StreetMap(nodes=nodes, edges=edges, buildings=buildings,
                     bbox=bbox, source=f"synthetic:{name}", edge_attrs=edge_attrs)


# ===========================================================================
# Procedural interiors
# ===========================================================================
@dataclass
class InteriorParams:
    """Knobs for interior generation (room size target, entrances per floor)."""

    target_room_area: float = 25.0      # m^2 per room (drives the subdivision)
    min_rooms_per_floor: int = 1
    entrances: int = 1


def generate_interior(building: Building, params: InteriorParams = InteriorParams(),
                      seed: int = 0) -> Interior:
    """Subdivide a building footprint into rooms per floor (deterministic).

    A simple recursive split along the longer axis until rooms reach roughly
    ``target_room_area``.  Good enough to give NPCs places to *be* inside a
    building; richer layouts (corridors, room types per category) are the
    documented extension point.
    """
    rng = np.random.default_rng(seed ^ (building.id * 2654435761 & 0xFFFFFFFF))
    xs = [p[0] for p in building.footprint]
    ys = [p[1] for p in building.footprint]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)

    def split(x0, y0, x1, y1, depth=0):
        w, h = x1 - x0, y1 - y0
        if w * h <= params.target_room_area * 1.6 or depth > 6:
            return [(x0, y0, w, h)]
        if w >= h:
            cut = x0 + w * float(rng.uniform(0.4, 0.6))
            return split(x0, y0, cut, y1, depth + 1) + split(cut, y0, x1, y1, depth + 1)
        cut = y0 + h * float(rng.uniform(0.4, 0.6))
        return split(x0, y0, x1, cut, depth + 1) + split(x0, cut, x1, y1, depth + 1)

    levels = []
    for lvl in range(building.levels):
        rects = split(x0, y0, x1, y1)
        rooms = [Room(name=f"L{lvl}-R{k}", x=rx, y=ry, w=rw, h=rh)
                 for k, (rx, ry, rw, rh) in enumerate(rects)]
        levels.append(rooms)
    # Entrances along the footprint's south edge.
    ents = [(x0 + (x1 - x0) * (k + 1) / (params.entrances + 1), y0)
            for k in range(params.entrances)]
    return Interior(levels=levels, entrances=ents)


# ===========================================================================
# Serialisation of the lightweight source specs (the heavy StreetMap is never
# serialised onto a CityProfile -- the profile stores only how to *source* it).
# ===========================================================================
def osm_source_to_dict(s: OSMSource) -> dict:
    return asdict(s)


def synth_spec_to_dict(s: SynthCitySpec) -> dict:
    return asdict(s)

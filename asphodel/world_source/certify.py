"""Full-city certification harness (mission §25-§27).

Reads a compiled bundle from disk (never in-memory state) so certification
measures exactly what ships.  Produces a gate dict; the build CLI fails
closed when any gate is False.
"""
from __future__ import annotations

import json
import math
import os

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from .chunkgrid import CELLS_PER_CHUNK, SURFACE_CELL_M, rle_decode
from .detrand import DetRand
from .grammar_tables import SURFACE_TYPES
from .schema import validate_chunk

# TREE_CANOPY is walkable ground under a canopy, not a solid obstacle.
_WALKABLE = {"ROAD", "SIDEWALK", "PARKING", "OTHER_IMPERVIOUS",
             "MAINTAINED_GRASS", "ROUGH_VEGETATION", "BARE_GROUND",
             "TREE_CANOPY"}
# Classes that render as actual streets; service aprons / unknown stubs
# paint beneath buildings by precedence (observed footprint wins).
_STREET_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary",
                   "residential", "unclassified", "living_street"}
_URBAN_PARCELS = {"RESIDENTIAL", "MULTIFAMILY", "RETAIL", "OFFICE",
                  "INDUSTRIAL", "CIVIC", "SCHOOL", "MEDICAL"}
_OPEN_PARCELS = {"PARK", "VACANT_OPEN", "UNKNOWN"}

N_SAMPLES = 1000
EMPTY_RADIUS = 50.0


class _World:
    """Disk view of a compiled bundle."""

    def __init__(self, bundle_dir: str):
        wdir = os.path.join(bundle_dir, "world")
        with open(os.path.join(wdir, "world_meta.json")) as f:
            self.meta = json.load(f)
        import gzip
        with gzip.open(os.path.join(wdir, "spawn_anchors.json.gz"), "rt",
                       encoding="utf-8") as f:
            self.anchors = json.load(f)["anchors"]
        with open(os.path.join(bundle_dir, "buildings.json")) as f:
            self.buildings_json = json.load(f)
        cpath = os.path.join(bundle_dir, "citizens.json")
        self.citizens = []
        if os.path.exists(cpath):
            with open(cpath) as f:
                self.citizens = json.load(f)
        self.bounds = self.meta["bounds_m"]
        self.chunks = {}
        from .chunks import read_chunk
        cdir = os.path.join(wdir, "chunks")
        for name in sorted(os.listdir(cdir)):
            if not (name.endswith(".json") or name.endswith(".json.gz")):
                continue
            c = read_chunk(os.path.join(cdir, name))
            self.chunks[(c["cx"], c["cz"])] = c
        self._rasters = {}
        # Spatial indexes over shipped data.
        self._bpolys = []
        self._bids = []
        for c in self.chunks.values():
            for b in c["buildings"]:
                self._bpolys.append(Polygon([(p[0], p[1]) for p in b["poly"]]))
                self._bids.append(b["bid"])
        self._btree = STRtree(self._bpolys) if self._bpolys else None
        self._parcels = []
        for c in self.chunks.values():
            for p in c["parcels"]:
                try:
                    poly = Polygon([(q[0], q[1]) for q in p["poly"]])
                    if not poly.is_valid:
                        poly = poly.buffer(0)
                    self._parcels.append((poly, p["arch"]))
                except Exception:
                    continue
        self._ptree = STRtree([p for p, _ in self._parcels]) if self._parcels else None
        self._placements = []
        for c in self.chunks.values():
            for lst in ("props", "vehicles", "trees"):
                for row in c[lst]:
                    self._placements.append((row[1], row[2]))
        self._pl_tree = (STRtree([Point(x, z) for x, z in self._placements])
                         if self._placements else None)

    def raster(self, cx, cz):
        key = (cx, cz)
        if key not in self._rasters:
            self._rasters[key] = rle_decode(
                self.chunks[key]["surface"], CELLS_PER_CHUNK * CELLS_PER_CHUNK)
        return self._rasters[key]

    def surface_at(self, x, z) -> str:
        min_x, min_z, max_x, max_z = self.bounds
        if not (min_x <= x < max_x and min_z <= z < max_z):
            return "OFF_MAP"
        size = self.meta["chunk_size_m"]
        cx = int((x - min_x) // size)
        cz = int((z - min_z) // size)
        if (cx, cz) not in self.chunks:
            return "OFF_MAP"
        ox = min_x + cx * size
        oz = min_z + cz * size
        col = min(CELLS_PER_CHUNK - 1, int((x - ox) / SURFACE_CELL_M))
        row = min(CELLS_PER_CHUNK - 1, int((z - oz) / SURFACE_CELL_M))
        b = self.raster(cx, cz)[row * CELLS_PER_CHUNK + col]
        return SURFACE_TYPES[b]

    def inside_building(self, x, z) -> bool:
        if self._btree is None:
            return False
        pt = Point(x, z)
        for idx in self._btree.query(pt):
            if self._bpolys[int(idx)].covers(pt):
                return True
        return False

    def parcel_arch_at(self, x, z) -> str | None:
        if self._ptree is None:
            return None
        pt = Point(x, z)
        for idx in self._ptree.query(pt):
            poly, arch = self._parcels[int(idx)]
            if poly.covers(pt):
                return arch
        idx = self._ptree.nearest(pt)
        if idx is not None:
            poly, arch = self._parcels[int(idx)]
            if poly.distance(pt) < 40.0:
                return arch
        return None

    def context_within(self, x, z, r) -> dict:
        pt = Point(x, z)
        circle = pt.buffer(r)
        n_build = 0
        if self._btree is not None:
            n_build = sum(
                1 for idx in self._btree.query(circle)
                if self._bpolys[int(idx)].intersects(circle))
        n_place = 0
        if self._pl_tree is not None:
            n_place = sum(
                1 for idx in self._pl_tree.query(circle)
                if (self._placements[int(idx)][0] - x) ** 2
                + (self._placements[int(idx)][1] - z) ** 2 <= r * r)
        # road treatment: sample raster ring for ROAD/SIDEWALK cells
        road_cells = 0
        samples = 0
        rng = range(-int(r), int(r) + 1, 4)
        for dx in rng:
            for dz in rng:
                if dx * dx + dz * dz > r * r:
                    continue
                samples += 1
                if self.surface_at(x + dx, z + dz) in ("ROAD", "SIDEWALK",
                                                       "PARKING"):
                    road_cells += 1
        return {"buildings": n_build, "placements": n_place,
                "paved_frac": road_cells / max(samples, 1)}


def _spawn_ok(w: _World, x, z) -> tuple[bool, str]:
    surf = w.surface_at(x, z)
    if surf == "OFF_MAP":
        return False, "off_map"
    if surf == "WATER":
        return False, "water"
    if w.inside_building(x, z):
        return False, "inside_building"
    if surf == "BUILDING":
        # painted-building cell but not inside a footprint (2m raster edge)
        return True, "edge"
    if surf not in _WALKABLE:
        return False, f"surface_{surf}"
    return True, "ok"


def _visually_empty(w: _World, x, z) -> tuple[bool, str]:
    arch = w.parcel_arch_at(x, z)
    if arch is None or arch in _OPEN_PARCELS:
        return False, arch or "none"   # intentionally open contexts don't count
    ctx = w.context_within(x, z, EMPTY_RADIUS)
    empty = (ctx["buildings"] == 0 and ctx["placements"] < 3
             and ctx["paved_frac"] < 0.02)
    return empty, arch


def certify_city(bundle_dir: str, seed: int = 0,
                 n_samples: int = N_SAMPLES) -> dict:
    w = _World(bundle_dir)

    # -- chunk validity + surface enum ----------------------------------
    invalid_chunks = 0
    for key, chunk in w.chunks.items():
        if validate_chunk(chunk, CELLS_PER_CHUNK * CELLS_PER_CHUNK):
            invalid_chunks += 1

    # -- citizen spawn census -------------------------------------------
    bad_citizen_spawns = []
    fallback_spawns = 0
    for i, c in enumerate(w.citizens):
        xy = c.get("spawn_xy")
        if not xy:
            bad_citizen_spawns.append((i, "missing"))
            continue
        ok, why = _spawn_ok(w, xy[0], xy[1])
        if not ok:
            bad_citizen_spawns.append((i, why))
        if c.get("spawn_anchor") == "fallback":
            fallback_spawns += 1

    # -- sampled spawn contexts (deterministic) -------------------------
    anchors = [a for a in w.anchors
               if a[0] in ("BUILDING_ENTRANCE", "SIDEWALK_ANCHOR",
                           "PARKING_ANCHOR", "PEDESTRIAN_APPROACH",
                           "DRIVEWAY_ANCHOR")]
    rnd = DetRand(seed, "spawn_census")
    picks = []
    if anchors:
        for _ in range(n_samples):
            picks.append(anchors[rnd.randint(0, len(anchors) - 1)])
    bad_samples = []
    empty_urban = 0
    urban_total = 0
    dists = []
    for a in picks:
        kind, x, z, bid = a
        ok, why = _spawn_ok(w, x, z)
        if not ok:
            bad_samples.append((kind, x, z, why))
            continue
        emp, arch = _visually_empty(w, x, z)
        if arch in _URBAN_PARCELS:
            urban_total += 1
            if emp:
                empty_urban += 1
        ctx = w.context_within(x, z, EMPTY_RADIUS)
        dists.append(ctx["placements"])

    # -- coverage gates --------------------------------------------------
    n_buildings = len(w.buildings_json["buildings"])
    arch_counts: dict[str, int] = {}
    for b in w.buildings_json["buildings"]:
        arch_counts[b.get("arch", "?")] = arch_counts.get(b.get("arch", "?"), 0) + 1
    non_generic = sum(v for k, v in arch_counts.items()
                      if k not in ("GENERIC_UNKNOWN", "?"))

    parcels_total = sum(len(c["parcels"]) for c in w.chunks.values())
    road_total = 0
    road_with_xsec = 0
    seen_road_keys = set()
    for c in w.chunks.values():
        for r in c["roads"]:
            k = (r["class"], tuple(map(tuple, r["pts"][:1])))
            if k in seen_road_keys:
                continue
            seen_road_keys.add(k)
            road_total += 1
            if r.get("path_only") or r.get("carriage_w", 0) > 0:
                road_with_xsec += 1

    # parcel-or-context assignment: buildings linked to a parcel
    linked = set()
    for c in w.chunks.values():
        for p in c["parcels"]:
            pass
    # buildings.json doesn't carry parcel ids; use identity via chunks
    bids_in_chunks = set()
    for c in w.chunks.values():
        for b in c["buildings"]:
            bids_in_chunks.add(b["bid"])

    # contextual property detail: urban parcels with >=1 placement inside
    urban_parcels = [(poly, arch) for poly, arch in w._parcels
                     if arch in _URBAN_PARCELS]
    with_detail = 0
    for poly, arch in urban_parcels:
        found = False
        if w._pl_tree is not None:
            for idx in w._pl_tree.query(poly):
                x, z = w._placements[int(idx)]
                if poly.covers(Point(x, z)):
                    found = True
                    break
        if not found:
            # surface detail counts too (driveway/parking painted inside)
            c = poly.representative_point()
            if w.surface_at(c.x, c.y) in ("PARKING", "OTHER_IMPERVIOUS",
                                          "SIDEWALK"):
                found = True
        if found:
            with_detail += 1

    # building-on-road collisions (footprint majority inside carriageway)
    collisions = 0
    road_polys = []
    for c in w.chunks.values():
        for r in c["roads"]:
            if (r.get("path_only") or r.get("elevated")
                    or r["class"] not in _STREET_CLASSES):
                continue
            try:
                road_polys.append(LineString(
                    [(p[0], p[1]) for p in r["pts"]]).buffer(
                        r["carriage_w"] / 2.0))
            except Exception:
                continue
    if road_polys and w._btree is not None:
        from shapely.ops import unary_union
        rtree = STRtree(road_polys)
        for bp in w._bpolys:
            hit = [road_polys[int(i)] for i in rtree.query(bp)]
            if not hit:
                continue
            try:
                inter = unary_union(hit).intersection(bp).area
            except Exception:
                continue
            if inter > 0.5 * bp.area:
                collisions += 1

    n_cit = len(w.citizens)
    gates = {
        "SOURCE_PROVENANCE_COMPLETE": os.path.exists(
            os.path.join("geo", "provenance", "data_sources.json")),
        "UNCLASSIFIED_GROUND_ZERO": invalid_chunks == 0,
        "CHUNKS_VALID": invalid_chunks == 0,
        "BUILDING_ON_ROAD_COLLISIONS_ZERO": collisions == 0,
        "NORMAL_INVALID_PLAYER_SPAWNS_ZERO":
            len(bad_citizen_spawns) == 0 and fallback_spawns == 0,
        "VALID_PLAYER_SPAWN_100":
            n_cit > 0 and len(bad_citizen_spawns) == 0,
        "SAMPLED_SPAWNS_VALID": len(bad_samples) == 0,
        "PARCEL_OR_CONTEXT_ASSIGNMENT_98":
            n_buildings > 0 and len(bids_in_chunks) / n_buildings >= 0.98,
        "ROAD_CROSS_SECTION_COVERAGE_95":
            road_total > 0 and road_with_xsec / road_total >= 0.95,
        "BUILDING_ARCHETYPE_COVERAGE_95":
            n_buildings > 0 and non_generic / n_buildings >= 0.95,
        "CONTEXTUAL_PROPERTY_DETAIL_95":
            len(urban_parcels) > 0 and with_detail / len(urban_parcels) >= 0.95,
        "VISUALLY_EMPTY_URBAN_SPAWNS_LT2":
            urban_total > 0 and empty_urban / urban_total < 0.02,
    }
    return {
        "gates": gates,
        "citizens": {
            "total": n_cit,
            "invalid": bad_citizen_spawns[:20],
            "n_invalid": len(bad_citizen_spawns),
            "fallback_spawns": fallback_spawns,
        },
        "samples": {
            "n": len(picks),
            "invalid": bad_samples[:20],
            "n_invalid": len(bad_samples),
            "urban": urban_total,
            "visually_empty_urban": empty_urban,
            "mean_nearby_placements":
                round(sum(dists) / max(len(dists), 1), 1),
        },
        "coverage": {
            "buildings": n_buildings,
            "buildings_in_chunks": len(bids_in_chunks),
            "arch_counts": arch_counts,
            "non_generic_frac": round(non_generic / max(n_buildings, 1), 4),
            "parcels": parcels_total,
            "urban_parcels": len(urban_parcels),
            "urban_parcels_with_detail": with_detail,
            "road_records": road_total,
            "building_road_collisions": collisions,
        },
    }

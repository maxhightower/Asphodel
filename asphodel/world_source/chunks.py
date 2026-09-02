"""Chunk emitter: compiled stages -> per-chunk JSON (schema.py contract).

Each chunk file is independently derivable from the same inputs; emission
here is a pure partition + serialization step.  Determinism: features are
written in stable sorted order inside each chunk.
"""
from __future__ import annotations

import json
import os

from shapely.geometry import LineString, box

from .chunkgrid import CELLS_PER_CHUNK, CHUNK_SIZE_M, ChunkGrid, rle_encode
from .schema import CHUNK_SCHEMA_VERSION


def _rf(v: float) -> float:
    return round(float(v), 2)


def _clip_line(pts, chunk_poly):
    """Clip a polyline to a chunk box; yield coordinate lists."""
    try:
        inter = LineString(pts).intersection(chunk_poly)
    except Exception:
        return
    if inter.is_empty:
        return
    geoms = getattr(inter, "geoms", [inter])
    for g in geoms:
        if g.geom_type == "LineString" and len(g.coords) >= 2:
            yield [[_rf(x), _rf(z)] for x, z in g.coords]


def build_chunks(grid: ChunkGrid, rasters, segments, parcels, buildings,
                 placements, anchors) -> dict:
    """Partition everything into chunk dicts keyed (cx, cz)."""
    chunks = {}
    for cx, cz in grid.all_chunks():
        ox, oz = grid.chunk_origin(cx, cz)
        chunks[(cx, cz)] = {
            "v": CHUNK_SCHEMA_VERSION,
            "cx": cx, "cz": cz,
            "origin": [_rf(ox), _rf(oz)],
            "surface": rle_encode(rasters[(cx, cz)]),
            "roads": [], "parcels": [], "buildings": [],
            "props": [], "vehicles": [], "trees": [], "anchors": [],
        }

    # Roads: clipped into each chunk they cross (pad so cross-sections that
    # bleed over the border still render at chunk edges).
    pad = 24.0
    for seg in sorted(segments, key=lambda s: s.key):
        if len(seg.pts) < 2:
            continue
        xs = [p[0] for p in seg.pts]
        zs = [p[1] for p in seg.pts]
        c0 = grid.chunk_of(min(xs) - pad, min(zs) - pad)
        c1 = grid.chunk_of(max(xs) + pad, max(zs) + pad)
        for cz in range(c0[1], c1[1] + 1):
            for cx in range(c0[0], c1[0] + 1):
                ox, oz = grid.chunk_origin(cx, cz)
                cpoly = box(ox - pad, oz - pad,
                            ox + CHUNK_SIZE_M + pad, oz + CHUNK_SIZE_M + pad)
                for coords in _clip_line(seg.pts, cpoly):
                    chunks[(cx, cz)]["roads"].append({
                        "pts": coords, "class": seg.cls,
                        "carriage_w": _rf(seg.carriage_w), "lanes": seg.lanes,
                        "sidewalk_w": _rf(seg.sidewalk_w),
                        "verge_w": _rf(seg.verge_w), "curb": seg.curb,
                        "markings": seg.markings, "elevated": seg.elevated,
                        "path_only": seg.path_only,
                    })

    # Parcels/buildings: assigned to the chunk of their centroid (a feature
    # renders whole from its home chunk; pad on the renderer side).
    for p in sorted(parcels, key=lambda p: p.pid):
        c = p.poly.centroid
        key = grid.chunk_of(c.x, c.y)
        ring = [[_rf(x), _rf(z)] for x, z in p.poly.exterior.coords[:-1]]
        if len(ring) < 3:
            continue
        chunks[key]["parcels"].append({
            "id": p.pid, "poly": ring, "arch": p.arch, "obs": p.obs,
        })

    for b in sorted(buildings, key=lambda b: b.bid):
        c = b.poly.centroid
        key = grid.chunk_of(c.x, c.y)
        ring = [[_rf(x), _rf(z)] for x, z in b.poly.exterior.coords[:-1]]
        if len(ring) < 3:
            continue
        bdict = {
            "bid": b.bid, "poly": ring, "h": _rf(b.h), "floors": b.floors,
            "arch": b.arch, "roof": b.roof,
            "entrance": {"edge": b.entrance_edge, "t": round(b.entrance_t, 3),
                         "w": _rf(b.entrance_w)},
            "feat": sorted(b.feat),
        }
        if b.appearance is not None:      # Package B: appearance truth + provenance
            bdict["appearance"] = b.appearance
        if b.identity is not None:        # Package H: fictional business identity
            bdict["identity"] = b.identity
        chunks[key]["buildings"].append(bdict)

    cat_field = {"prop": "props", "vehicle": "vehicles", "tree": "trees"}
    for pl in sorted(placements, key=lambda p: (p.kind, round(p.x, 2),
                                                round(p.z, 2))):
        key = grid.chunk_of(pl.x, pl.z)
        chunks[key][cat_field[pl.cat]].append(
            [pl.kind, _rf(pl.x), _rf(pl.z), round(pl.rot, 1), pl.variant])

    for a in sorted(anchors, key=lambda a: (a.kind, round(a.x, 2),
                                            round(a.z, 2), a.bid)):
        key = grid.chunk_of(a.x, a.z)
        chunks[key]["anchors"].append([a.kind, _rf(a.x), _rf(a.z), a.bid])

    return chunks


def write_chunks(out_dir: str, chunks: dict) -> dict:
    """Write chunks/c_<cx>_<cz>.json.gz; returns {name: size} stats.

    Gzip with mtime=0 so identical content produces byte-identical files
    (deterministic rebuild gate).  Godot reads these via
    PackedByteArray.decompress_dynamic(..., COMPRESSION_GZIP).
    """
    import gzip

    cdir = os.path.join(out_dir, "chunks")
    os.makedirs(cdir, exist_ok=True)
    sizes = {}
    for (cx, cz), chunk in sorted(chunks.items()):
        name = f"c_{cx}_{cz}.json.gz"
        path = os.path.join(cdir, name)
        payload = json.dumps(chunk, separators=(",", ":"),
                             sort_keys=True).encode("utf-8")
        with open(path, "wb") as f:
            f.write(gzip.compress(payload, mtime=0))
        sizes[name] = os.path.getsize(path)
    return sizes


def read_chunk(path: str) -> dict:
    """Read one chunk file (.json.gz or legacy .json)."""
    import gzip

    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(path) as f:
        return json.load(f)


def expected_cells() -> int:
    return CELLS_PER_CHUNK * CELLS_PER_CHUNK

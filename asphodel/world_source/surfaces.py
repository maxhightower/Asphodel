"""OW-MVP-1: semantic surface raster painter.

A pure painter: every stage contributes SurfacePatch polygons with a
priority band (records.SurfacePatch); this module rasterizes them into a
2 m per-cell semantic byte raster per 256 m chunk.  There is no
"unclassified" byte — the base fill is a real surface type, so every
rendered playable location has an intentional interpretation.
"""
from __future__ import annotations

import numpy as np
import shapely
from shapely.strtree import STRtree

from .chunkgrid import CELLS_PER_CHUNK, CHUNK_SIZE_M, SURFACE_CELL_M, ChunkGrid
from .grammar_tables import SURFACE_TYPES

_TYPE_INDEX = {name: i for i, name in enumerate(SURFACE_TYPES)}
_BASE_FILL = _TYPE_INDEX["ROUGH_VEGETATION"]


def surface_index(name: str) -> int:
    return _TYPE_INDEX[name]


def paint_surfaces(grid: ChunkGrid, patches) -> dict:
    """Rasterize patches into per-chunk byte rasters.

    Returns {(cx, cz): bytearray(CELLS_PER_CHUNK**2)} row-major from the
    chunk's min corner (rows advance +z, columns +x) — matching the chunk
    JSON contract.
    """
    ordered = sorted(
        range(len(patches)),
        key=lambda i: (patches[i].priority, i),
    )
    geoms = [patches[i].poly for i in ordered]
    tree = STRtree(geoms) if geoms else None

    half = SURFACE_CELL_M / 2.0
    axis = np.arange(CELLS_PER_CHUNK) * SURFACE_CELL_M + half
    out = {}
    for cx, cz in grid.all_chunks():
        ox, oz = grid.chunk_origin(cx, cz)
        raster = np.full((CELLS_PER_CHUNK, CELLS_PER_CHUNK), _BASE_FILL,
                         dtype=np.uint8)
        if tree is not None:
            chunk_box = shapely.box(ox, oz, ox + CHUNK_SIZE_M, oz + CHUNK_SIZE_M)
            hits = sorted(int(i) for i in tree.query(chunk_box))
            xs = axis + ox
            zs = axis + oz
            for hi in hits:
                patch = patches[ordered[hi]]
                code = _TYPE_INDEX[patch.surface]
                minx, minz, maxx, maxz = patch.poly.bounds
                c0 = max(0, int((minx - ox) / SURFACE_CELL_M))
                c1 = min(CELLS_PER_CHUNK - 1, int((maxx - ox) / SURFACE_CELL_M))
                r0 = max(0, int((minz - oz) / SURFACE_CELL_M))
                r1 = min(CELLS_PER_CHUNK - 1, int((maxz - oz) / SURFACE_CELL_M))
                if c1 < c0 or r1 < r0:
                    continue
                sub_x = xs[c0:c1 + 1]
                sub_z = zs[r0:r1 + 1]
                gx, gz = np.meshgrid(sub_x, sub_z)
                mask = shapely.contains_xy(patch.poly, gx.ravel(), gz.ravel())
                if mask.any():
                    # NOTE: assign through the 2D boolean mask directly, not
                    # via block.ravel()[mask] -- block is a non-contiguous
                    # view (a row/col slice of `raster`), so .ravel() on it
                    # returns a *copy* and silently drops the write.
                    block = raster[r0:r1 + 1, c0:c1 + 1]
                    block[mask.reshape(block.shape)] = code
        out[(cx, cz)] = bytearray(raster.tobytes())
    return out


def census(rasters: dict) -> dict:
    """Cell counts per surface type across all chunks."""
    counts = {name: 0 for name in SURFACE_TYPES}
    for raster in rasters.values():
        arr = np.frombuffer(bytes(raster), dtype=np.uint8)
        binc = np.bincount(arr, minlength=len(SURFACE_TYPES))
        for i, name in enumerate(SURFACE_TYPES):
            counts[name] += int(binc[i])
    return counts

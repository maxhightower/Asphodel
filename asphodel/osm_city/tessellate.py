"""Tessellate a bbox into a square grid and assign density-weighted population.

Each building's projected footprint area (x its storey count) is accumulated
into the grid cell containing its centroid. Per-cell totals become a population
share of a configurable grand total. Zone ids follow row * cols + col so they
line up with `ZoneGraph.index` and the belief timeline columns.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import geometry as geo


@dataclass
class Tessellation:
    rows: int
    cols: int
    cell_w: float          # cell width in meters (east/x)
    cell_h: float          # cell height in meters (north/z)
    zones: list[dict]      # id,row,col,center_xy,extent,population,density


def _grid_dims(width_m: float, height_m: float, grid: int) -> tuple[int, int]:
    """Longer axis gets `grid` cells; shorter axis scales to keep cells ~square."""
    if width_m >= height_m:
        cols = grid
        rows = max(1, round(grid * height_m / width_m))
    else:
        rows = grid
        cols = max(1, round(grid * width_m / height_m))
    return rows, cols


def tessellate(bbox, buildings: list[dict], grid: int, total_pop: float) -> Tessellation:
    south, west, north, east = bbox
    lat0 = (south + north) / 2.0
    lon0 = (west + east) / 2.0

    # Project the bbox corners to get the play-area size in meters.
    x_min, z_min = geo.project(south, west, lat0, lon0)
    x_max, z_max = geo.project(north, east, lat0, lon0)
    width_m = x_max - x_min
    height_m = z_max - z_min

    # Use raw degree spans for the grid aspect ratio so that the cell count
    # reflects the geographic footprint (e.g. 1° lon x 0.5° lat -> cols:rows = 2:1).
    lon_span = east - west
    lat_span = north - south
    rows, cols = _grid_dims(lon_span, lat_span, grid)
    cell_w = width_m / cols
    cell_h = height_m / rows

    raw = [0.0] * (rows * cols)
    for b in buildings:
        ring_m = [geo.project(lat, lon, lat0, lon0) for (lat, lon) in b["ring"]]
        if len(ring_m) < 3:
            continue
        area = geo.polygon_area(ring_m)
        cx = sum(p[0] for p in ring_m) / len(ring_m)
        cz = sum(p[1] for p in ring_m) / len(ring_m)
        col = min(cols - 1, max(0, int((cx - x_min) / cell_w)))
        row = min(rows - 1, max(0, int((cz - z_min) / cell_h)))
        raw[row * cols + col] += area * max(1, int(b.get("levels", 1)))

    total_raw = sum(raw)
    max_raw = max(raw) if raw else 0.0

    zones = []
    for row in range(rows):
        for col in range(cols):
            i = row * cols + col
            center_x = x_min + (col + 0.5) * cell_w
            center_z = z_min + (row + 0.5) * cell_h
            population = (raw[i] / total_raw * total_pop) if total_raw > 0 else 0.0
            density = (raw[i] / max_raw) if max_raw > 0 else 0.0
            zones.append({
                "id": i, "row": row, "col": col,
                "center_xy": [center_x, center_z],
                "extent": [cell_w, cell_h],
                "population": population,
                "density": density,
            })
    return Tessellation(rows=rows, cols=cols, cell_w=cell_w, cell_h=cell_h, zones=zones)

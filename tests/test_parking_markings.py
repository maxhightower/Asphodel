"""P0-D5 -- parking stall marking generation.

The offline generator turns a chunk's S_PARKING raster into a `ground_markings`
stream of stall-divider stripes. These checks lock the record contract and the
key correctness property: every stripe's centre falls on an actual parking cell
(so irregular lots never spill stripes onto grass, road or buildings)."""
from __future__ import annotations

import numpy as np

from tools import repatch_parking_markings as pm


def _rect_parking_grid(r0, r1, c0, c1):
    grid = np.zeros((pm.CELLS, pm.CELLS), dtype=np.uint8)
    grid[r0:r1, c0:c1] = pm.S_PARKING
    return grid


def test_records_have_stripe_contract():
    grid = _rect_parking_grid(40, 70, 30, 90)   # a wide parking rectangle
    mask = grid == pm.S_PARKING
    origin = (0.0, 0.0)
    marks = []
    for cells in pm._components(mask):
        marks.extend(pm._region_marks(cells, origin, mask))
    assert marks, "a large parking rectangle should yield stall stripes"
    for m in marks:
        assert len(m) == 5
        x, z, heading, length, kind = m
        assert isinstance(x, float) and isinstance(z, float)
        assert -360.0 <= heading <= 360.0
        assert length == pm.STALL_DEPTH
        assert kind == "parking_stall"


def test_stripes_stay_on_parking():
    grid = _rect_parking_grid(40, 70, 30, 90)
    mask = grid == pm.S_PARKING
    origin = (0.0, 0.0)
    marks = []
    for cells in pm._components(mask):
        marks.extend(pm._region_marks(cells, origin, mask))
    for x, z, *_ in marks:
        col = int((x - origin[0]) / pm.CELL_M)
        row = int((z - origin[1]) / pm.CELL_M)
        assert mask[row, col], f"stripe centre ({x},{z}) is off the parking region"


def test_tiny_blob_is_ignored():
    grid = _rect_parking_grid(10, 12, 10, 13)   # ~6 cells, under MIN_REGION_CELLS
    mask = grid == pm.S_PARKING
    assert pm._components(mask) == []


def test_rle_roundtrip_matches_grid():
    grid = _rect_parking_grid(5, 8, 2, 9)
    runs = []
    flat = grid.reshape(-1)
    i = 0
    while i < len(flat):
        j = i
        while j < len(flat) and flat[j] == flat[i]:
            j += 1
        runs += [int(flat[i]), j - i]
        i = j
    decoded = pm._decode_rle(runs, pm.CELLS * pm.CELLS)
    assert np.array_equal(decoded, grid)

"""Tests for the bake-time erosion + hydrology pass (terrain realism)."""
from __future__ import annotations

import numpy as np

from asphodel.geo import GeoReference
from asphodel.region import SyntheticElevationProvider, ARCHETYPES, RegionalExtent, bake_heightmap
from asphodel.region.erosion import (
    erode_and_hydrology,
    flow_accumulation,
    thermal_relax,
    extract_water,
)


def _bake(gr, arch, step=1000.0):
    p = SyntheticElevationProvider(gr, ARCHETYPES[arch], seed=7)
    art = bake_heightmap(p, RegionalExtent.from_km(3, 40, 60), step_m=step)
    return np.array(art["heights"]), art["step_m"]


def test_erosion_is_deterministic():
    h, step = _bake(GeoReference(40.015, -105.27, origin_elevation=1655), "front_range_adjacent")
    a = erode_and_hydrology(h, step, seed=7, mountainous=True)
    b = erode_and_hydrology(h, step, seed=7, mountainous=True)
    assert np.array_equal(a["heights"], b["heights"])
    assert np.array_equal(a["water_mask"], b["water_mask"])


def test_flat_stays_flat_mountain_stays_mountainous():
    hf, sf = _bake(GeoReference(29.82, -95.46, origin_elevation=15), "coastal_plain")
    hm, sm = _bake(GeoReference(40.015, -105.27, origin_elevation=1655), "front_range_adjacent")
    ef = erode_and_hydrology(hf, sf, seed=7, mountainous=False)["heights"]
    em = erode_and_hydrology(hm, sm, seed=7, mountainous=True)["heights"]
    flat_relief = ef.max() - ef.min()
    mtn_relief = em.max() - em.min()
    assert flat_relief < 150.0
    assert mtn_relief > 800.0
    assert mtn_relief > 8.0 * flat_relief


def test_erosion_produces_rivers():
    h, step = _bake(GeoReference(40.015, -105.27, origin_elevation=1655), "front_range_adjacent")
    r = erode_and_hydrology(h, step, seed=7, mountainous=True)
    assert r["river_cells"] > 0
    assert r["water_mask"].sum() == r["river_cells"]


def test_flow_accumulation_concentrates_downstream():
    # A tilted plane: all flow runs to the low edge, so max accumulation >> 1.
    z = np.linspace(0, 100, 40)[:, None] * np.ones((1, 40))
    acc, downstream = flow_accumulation(z)
    assert acc.max() >= 39.0           # a channel gathered a whole column
    assert acc.min() >= 1.0            # every cell contributes at least itself


def test_thermal_relax_conserves_mass_and_reduces_slope():
    rng = np.random.default_rng(0)
    h = rng.random((30, 30)) * 100.0    # spiky
    out = thermal_relax(h, iters=8, talus=2.0)
    assert abs(out.sum() - h.sum()) / h.sum() < 0.02   # mass ~ conserved
    # peak-to-peak slope reduced
    def max_step(a):
        return max(np.abs(np.diff(a, axis=0)).max(), np.abs(np.diff(a, axis=1)).max())
    assert max_step(out) <= max_step(h)


def test_extract_water_marks_sub_sea_cells():
    h = np.array([[-5.0, -1.0, 2.0], [1.0, 3.0, 4.0], [5.0, 6.0, 7.0]])
    acc = np.ones_like(h)
    mask = extract_water(h, acc, cell_m=100.0, sea_level=0.0, river_fraction=1.1)
    assert mask[0, 0] and mask[0, 1]   # below sea level
    assert not mask[2, 2]              # high and dry

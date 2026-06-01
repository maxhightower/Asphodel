# OSM City Pipeline (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python pipeline that turns a city name into a bundle (zone graph + density-weighted population + roads + a precomputed belief-cascade timeline) that Godot will later render.

**Architecture:** A new `asphodel/osm_city/` package: geocode a city name to a bbox (Nominatim), fetch major roads + building footprints (Overpass, cached), tessellate the bbox into a square grid whose per-cell population comes from building density, run the *existing* belief-cascade sim on that grid via a small per-zone-population hook, and write a JSON bundle. All network I/O goes through injectable `fetch` callables so the whole pipeline is testable offline.

**Tech Stack:** Python 3, stdlib only for the new code (`urllib`, `json`, `math`, `hashlib`, `argparse`, `random`), plus the existing `numpy`/`pandas` sim. No new dependencies. Tests via `pytest`.

**Spec:** `docs/superpowers/specs/2026-06-01-osm-city-scene-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `asphodel/osm_city/__init__.py` | Package marker + shared exceptions (`CityNotFound`, `OSMError`). |
| `asphodel/osm_city/geometry.py` | Pure geo math: equirectangular projection, shoelace polygon area, block placement, polyline projection. |
| `asphodel/osm_city/tessellate.py` | bbox + buildings → square grid: dims from aspect, per-cell density → population. |
| `asphodel/osm_city/geocode.py` | City name → bbox via Nominatim (injectable fetch), bbox capping. |
| `asphodel/osm_city/overpass.py` | bbox → Overpass query/fetch (cached, injectable) → parsed buildings + roads. |
| `asphodel/osm_city/bundle.py` | Assemble + deterministically write `meta/zones/roads/timeline` JSON. |
| `asphodel/osm_city/pipeline.py` | `build_bundle(...)` core: tessellate → run sim → blocks/roads → write. Network-free. |
| `asphodel/osm_city/__main__.py` | CLI: parse args, geocode + fetch, call `build_bundle`. |
| `asphodel/config.py` (modify) | `GraphParams.population: Optional[list[float]]`. |
| `asphodel/model.py` (modify) | Use per-zone population vector when present. |
| `tests/test_osm_city.py` | All Phase-1 tests (offline, inline fixtures). |

Zone ordering is fixed everywhere: `zone id == row * cols + col`, matching `ZoneGraph.index(r, c)` in `asphodel/graph.py:53`. The population vector and timeline columns use this same order.

---

## Task 1: Package + geometry core (projection + polygon area)

**Files:**
- Create: `asphodel/osm_city/__init__.py`
- Create: `asphodel/osm_city/geometry.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_osm_city.py`:

```python
"""Phase-1 OSM city pipeline tests (offline; inline fixtures, no network)."""
import math

from asphodel.osm_city import geometry as geo


def test_project_origin_is_zero():
    assert geo.project(40.0, -73.0, 40.0, -73.0) == (0.0, 0.0)


def test_project_one_degree_lat_is_about_110540m():
    x, z = geo.project(41.0, -73.0, 40.0, -73.0)
    assert abs(x) < 1e-6
    assert abs(z - 110540.0) < 1.0


def test_project_one_degree_lon_scales_by_cos_lat():
    x, z = geo.project(40.0, -72.0, 40.0, -73.0)
    expected = 111320.0 * math.cos(math.radians(40.0))
    assert abs(x - expected) < 1.0
    assert abs(z) < 1e-6


def test_polygon_area_unit_square():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert abs(geo.polygon_area(square) - 100.0) < 1e-9


def test_polygon_area_is_orientation_independent():
    cw = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
    assert abs(geo.polygon_area(cw) - 100.0) < 1e-9


def test_polygon_area_degenerate_is_zero():
    assert geo.polygon_area([(0.0, 0.0), (1.0, 1.0)]) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city'`

- [ ] **Step 3: Write minimal implementation**

Create `asphodel/osm_city/__init__.py`:

```python
"""OSM -> Asphodel city bundle pipeline (Phase 1).

Turns a city name into a bundle (zone graph + density-weighted population +
roads + a precomputed belief-cascade timeline) consumed by the Godot frontend.
All network I/O is injectable so the pipeline is testable offline.
"""


class OSMError(Exception):
    """Base error for the OSM city pipeline."""


class CityNotFound(OSMError):
    """Geocoding returned no match for the requested city."""

    def __init__(self, query: str):
        super().__init__(f"No city found for query: {query!r}")
        self.query = query
```

Create `asphodel/osm_city/geometry.py`:

```python
"""Pure geometry helpers: projection, polygon area, block & polyline layout.

No network, no dependencies beyond the stdlib + a passed-in RNG, so every
function here is trivially unit-testable.
"""
from __future__ import annotations

import math
from typing import Iterable

# Meters per degree near the equator; lon is additionally scaled by cos(lat).
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0


def project(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Equirectangular projection of (lat, lon) to local meters about (lat0, lon0).

    Returns (x, z) where x is east, z is north. Sub-meter accurate at city scale.
    """
    x = (lon - lon0) * M_PER_DEG_LON * math.cos(math.radians(lat0))
    z = (lat - lat0) * M_PER_DEG_LAT
    return (x, z)


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Absolute area of a polygon via the shoelace formula.

    Units are the square of the input units (project first for square meters).
    Returns 0.0 for degenerate (<3 point) rings.
    """
    n = len(points)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/__init__.py asphodel/osm_city/geometry.py tests/test_osm_city.py
git commit -m "feat(osm): geometry core (projection + polygon area)"
```

---

## Task 2: Block placement + polyline projection

**Files:**
- Modify: `asphodel/osm_city/geometry.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
import random


def test_place_blocks_count_scales_with_density():
    rng = random.Random(0)
    low = geo.place_blocks(0.0, (0.0, 0.0), (100.0, 100.0), rng, max_blocks=8)
    rng = random.Random(0)
    high = geo.place_blocks(1.0, (0.0, 0.0), (100.0, 100.0), rng, max_blocks=8)
    assert len(low) == 0
    assert len(high) == 8


def test_place_blocks_positions_within_cell():
    rng = random.Random(1)
    blocks = geo.place_blocks(1.0, (50.0, -20.0), (100.0, 100.0), rng, max_blocks=8)
    for b in blocks:
        x, z = b["xy"]
        assert 0.0 <= x <= 100.0   # center 50 +/- 0.4*100
        assert -70.0 <= z <= 30.0  # center -20 +/- 0.4*100
        assert b["height"] > 0.0
        assert b["footprint"] > 0.0


def test_place_blocks_deterministic_for_same_seed():
    a = geo.place_blocks(0.7, (0.0, 0.0), (80.0, 80.0), random.Random(42), max_blocks=8)
    b = geo.place_blocks(0.7, (0.0, 0.0), (80.0, 80.0), random.Random(42), max_blocks=8)
    assert a == b


def test_project_polyline_maps_each_point():
    line = geo.project_polyline([(40.0, -73.0), (41.0, -73.0)], 40.0, -73.0)
    assert line[0] == [0.0, 0.0]
    assert abs(line[1][1] - 110540.0) < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k "place_blocks or polyline" -q`
Expected: FAIL — `AttributeError: module 'asphodel.osm_city.geometry' has no attribute 'place_blocks'`

- [ ] **Step 3: Write minimal implementation**

Append to `asphodel/osm_city/geometry.py`:

```python
def place_blocks(
    density: float,
    center_xy: tuple[float, float],
    cell_extent: tuple[float, float],
    rng,
    max_blocks: int = 8,
    min_height: float = 4.0,
    max_height: float = 40.0,
) -> list[dict]:
    """Representative low-poly blocks for one cell, count & height proportional to density.

    `density` in [0, 1]; positions are jittered within 80% of the cell to leave
    visible streets. `rng` is a `random.Random` for deterministic placement.
    Returns dicts: {"xy": [x, z], "height": float, "footprint": float}.
    """
    n = int(round(max(0.0, min(1.0, density)) * max_blocks))
    cx, cz = center_xy
    w, h = cell_extent
    blocks = []
    for _ in range(n):
        bx = cx + (rng.random() - 0.5) * w * 0.8
        bz = cz + (rng.random() - 0.5) * h * 0.8
        height = min_height + density * (max_height - min_height) * (0.6 + 0.8 * rng.random())
        footprint = 4.0 + 6.0 * rng.random()
        blocks.append({"xy": [bx, bz], "height": round(height, 3), "footprint": round(footprint, 3)})
    return blocks


def project_polyline(
    latlon_points: Iterable[tuple[float, float]], lat0: float, lon0: float
) -> list[list[float]]:
    """Project a sequence of (lat, lon) into a list of [x, z] pairs."""
    return [list(project(lat, lon, lat0, lon0)) for lat, lon in latlon_points]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/geometry.py tests/test_osm_city.py
git commit -m "feat(osm): block placement + polyline projection"
```

---

## Task 3: Tessellation (bbox + buildings → grid + population)

**Files:**
- Create: `asphodel/osm_city/tessellate.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
from asphodel.osm_city import tessellate as tess


def _square_building(lat, lon, d=0.0005, levels=1):
    """A small square building footprint centered at (lat, lon)."""
    return {
        "ring": [(lat - d, lon - d), (lat - d, lon + d),
                 (lat + d, lon + d), (lat + d, lon - d)],
        "levels": levels,
    }


def test_grid_dims_from_aspect_ratio():
    # Wide bbox (more lon span than lat span) -> more cols than rows.
    bbox = (40.0, -74.0, 40.5, -73.0)  # (s, w, n, e): 1.0 lon span, 0.5 lat span
    t = tess.tessellate(bbox, buildings=[], grid=8, total_pop=1000.0)
    assert t.cols == 8
    assert t.rows == 4
    assert len(t.zones) == 32


def test_population_sums_to_total():
    bbox = (40.0, -73.01, 40.01, -73.0)
    buildings = [_square_building(40.002, -73.008), _square_building(40.008, -73.002)]
    t = tess.tessellate(bbox, buildings, grid=4, total_pop=10000.0)
    assert abs(sum(z["population"] for z in t.zones) - 10000.0) < 1e-6


def test_empty_buildings_give_zero_population():
    bbox = (40.0, -73.01, 40.01, -73.0)
    t = tess.tessellate(bbox, buildings=[], grid=4, total_pop=10000.0)
    assert all(z["population"] == 0.0 for z in t.zones)


def test_zone_ids_match_row_col_order():
    bbox = (40.0, -73.01, 40.01, -73.0)
    t = tess.tessellate(bbox, buildings=[], grid=4, total_pop=1.0)
    for z in t.zones:
        assert z["id"] == z["row"] * t.cols + z["col"]


def test_levels_weight_population():
    # Two identical footprints; the 3-storey one gets ~3x the population.
    bbox = (40.0, -73.02, 40.01, -73.0)
    tall = _square_building(40.005, -73.015, levels=3)
    short = _square_building(40.005, -73.005, levels=1)
    t = tess.tessellate(bbox, [tall, short], grid=2, total_pop=4000.0)
    pops = sorted(z["population"] for z in t.zones if z["population"] > 0)
    assert len(pops) == 2
    assert abs(pops[1] / pops[0] - 3.0) < 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k tessellate -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city.tessellate'`

- [ ] **Step 3: Write minimal implementation**

Create `asphodel/osm_city/tessellate.py`:

```python
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

    rows, cols = _grid_dims(width_m, height_m, grid)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -q`
Expected: PASS (15 passed)

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/tessellate.py tests/test_osm_city.py
git commit -m "feat(osm): bbox tessellation with density-weighted population"
```

---

## Task 4: Per-zone population hook in the sim

**Files:**
- Modify: `asphodel/config.py` (`GraphParams`, ~line 62-70)
- Modify: `asphodel/model.py` (population init, line 81-82)
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
import numpy as np

from asphodel.config import ScenarioConfig, GraphParams, ModelParams
from asphodel.runner import run_scenario


def test_per_zone_population_sets_N0():
    pops = [100.0, 200.0, 300.0, 400.0]
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2, population=pops)),
        n_days=1.0,
    )
    from asphodel.model import Simulation
    sim = Simulation(cfg)
    assert np.allclose(sim.N0, np.array(pops))


def test_default_population_unchanged_when_vector_absent():
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2,
                                            population_per_zone=777.0)),
        n_days=1.0,
    )
    from asphodel.model import Simulation
    sim = Simulation(cfg)
    assert np.allclose(sim.N0, np.full(4, 777.0))


def test_run_scenario_with_heterogeneous_population():
    pops = [5000.0, 1000.0, 1000.0, 1000.0]
    cfg = ScenarioConfig(
        model=ModelParams(graph=GraphParams(grid_rows=2, grid_cols=2, population=pops)),
        n_days=5.0, seed_zone=0,
    )
    result = run_scenario(cfg)
    assert result.belief_history.shape == (cfg.n_ticks + 1, 4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k population -q`
Expected: FAIL — `TypeError: GraphParams.__init__() got an unexpected keyword argument 'population'`

- [ ] **Step 3: Write minimal implementation**

In `asphodel/config.py`, add a field to `GraphParams` (keep existing fields). The block becomes:

```python
@dataclass
class GraphParams:
    """Zone graph topology and inter-zone mobility."""

    grid_rows: int = 8
    grid_cols: int = 8
    population_per_zone: float = 5000.0
    mobility: float = 0.15             # fraction of within-zone contact that is
    #                                    actually with neighbouring zones
    #                                    (carries infection along the graph)
    # Optional explicit per-zone population (length grid_rows*grid_cols, ordered
    # row*cols+col). When set, overrides the uniform population_per_zone -- this
    # is how the OSM pipeline feeds real building-density populations.
    population: Optional[list] = None
```

(`Optional` is already imported in `config.py`.)

In `asphodel/model.py`, replace the population-init lines (currently `model.py:81-82`):

```python
        pop = config.model.graph.population_per_zone
        self.N0 = np.full(Z, pop, dtype=float)        # original population
```

with:

```python
        pop_vec = config.model.graph.population
        if pop_vec is not None:
            if len(pop_vec) != Z:
                raise ValueError(
                    f"graph.population has {len(pop_vec)} entries but grid has {Z} zones"
                )
            self.N0 = np.asarray(pop_vec, dtype=float)  # per-zone population
        else:
            pop = config.model.graph.population_per_zone
            self.N0 = np.full(Z, pop, dtype=float)      # uniform population
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -k population -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the existing sim tests to confirm no regression**

Run: `python -m pytest tests/test_model.py -q`
Expected: PASS (all existing tests still pass — the default path is unchanged)

- [ ] **Step 6: Commit**

```bash
git add asphodel/config.py asphodel/model.py tests/test_osm_city.py
git commit -m "feat(sim): optional per-zone population vector (OSM density hook)"
```

---

## Task 5: Geocoding (Nominatim, injectable fetch, bbox cap)

**Files:**
- Create: `asphodel/osm_city/geocode.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
import json as _json
import pytest

from asphodel.osm_city import geocode as gc
from asphodel.osm_city import CityNotFound

# Nominatim returns boundingbox as [south, north, west, east] strings.
_NOMINATIM_FIXTURE = _json.dumps([
    {"boundingbox": ["41.6", "42.0", "-87.9", "-87.5"], "display_name": "Chicago"}
])


def test_geocode_returns_bbox_in_swne_order():
    bbox = gc.geocode("Chicago", fetch=lambda url: _NOMINATIM_FIXTURE)
    s, w, n, e = bbox
    assert (s, w, n, e) == (41.6, -87.9, 42.0, -87.5)


def test_geocode_raises_when_empty():
    with pytest.raises(CityNotFound):
        gc.geocode("Nowhereville", fetch=lambda url: "[]")


def test_geocode_caps_oversized_bbox():
    huge = _json.dumps([{"boundingbox": ["30.0", "36.0", "-106.0", "-93.0"]}])  # Texas-ish
    bbox = gc.geocode("Texas", fetch=lambda url: huge, max_span_deg=0.5)
    s, w, n, e = bbox
    assert abs((n - s) - 0.5) < 1e-9
    assert abs((e - w) - 0.5) < 1e-9
    # Stays centered on the original center.
    assert abs(((s + n) / 2) - 33.0) < 1e-9
    assert abs(((w + e) / 2) - (-99.5)) < 1e-9


def test_geocode_builds_query_url():
    captured = {}
    def fake_fetch(url):
        captured["url"] = url
        return _NOMINATIM_FIXTURE
    gc.geocode("San Francisco", fetch=fake_fetch)
    assert "q=San+Francisco" in captured["url"]
    assert "format=json" in captured["url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k geocode -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city.geocode'`

- [ ] **Step 3: Write minimal implementation**

Create `asphodel/osm_city/geocode.py`:

```python
"""City name -> bounding box via the Nominatim (OSM) geocoder.

Network access goes through an injectable `fetch(url) -> str` so tests run
offline. Oversized bounding boxes are capped (centered) so a query like "Texas"
can't ask Overpass for a whole state.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import CityNotFound

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Asphodel/0.1 (research prototype; https://github.com/maxhightower/Asphodel)"


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _cap_bbox(bbox, max_span_deg: float):
    """Clamp each span to `max_span_deg`, keeping the center fixed."""
    s, w, n, e = bbox
    lat_c, lon_c = (s + n) / 2.0, (w + e) / 2.0
    lat_half = min((n - s) / 2.0, max_span_deg / 2.0)
    lon_half = min((e - w) / 2.0, max_span_deg / 2.0)
    return (lat_c - lat_half, lon_c - lon_half, lat_c + lat_half, lon_c + lon_half)


def geocode(query: str, fetch=_default_fetch, max_span_deg: float = 0.5):
    """Return a capped bbox `(south, west, north, east)` for `query`.

    Raises CityNotFound if Nominatim returns no match.
    """
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    raw = fetch(f"{NOMINATIM_URL}?{params}")
    data = json.loads(raw)
    if not data:
        raise CityNotFound(query)
    # Nominatim order: [south, north, west, east].
    south, north, west, east = (float(v) for v in data[0]["boundingbox"])
    return _cap_bbox((south, west, north, east), max_span_deg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -k geocode -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/geocode.py tests/test_osm_city.py
git commit -m "feat(osm): Nominatim geocoding with bbox capping"
```

---

## Task 6: Overpass fetch + parse + cache

**Files:**
- Create: `asphodel/osm_city/overpass.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
from asphodel.osm_city import overpass as ov

# Overpass `out geom;` returns ways with inline node geometry.
_OVERPASS_FIXTURE = {
    "elements": [
        {"type": "way", "tags": {"building": "yes", "building:levels": "3"},
         "geometry": [{"lat": 40.000, "lon": -73.000}, {"lat": 40.000, "lon": -73.001},
                      {"lat": 40.001, "lon": -73.001}, {"lat": 40.001, "lon": -73.000}]},
        {"type": "way", "tags": {"building": "house"},
         "geometry": [{"lat": 40.002, "lon": -73.002}, {"lat": 40.002, "lon": -73.003},
                      {"lat": 40.003, "lon": -73.003}]},
        {"type": "way", "tags": {"highway": "primary", "name": "Main St"},
         "geometry": [{"lat": 40.000, "lon": -73.000}, {"lat": 40.010, "lon": -73.010}]},
        {"type": "node", "lat": 40.0, "lon": -73.0},  # ignored
    ]
}


def test_build_query_contains_bbox_and_filters():
    q = ov.build_query((40.0, -73.1, 40.1, -73.0))
    assert "40.0,-73.1,40.1,-73.0" in q
    assert 'way["building"]' in q
    assert "highway" in q
    assert "out geom;" in q


def test_parse_osm_splits_buildings_and_roads():
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    assert len(buildings) == 2
    assert len(roads) == 1
    assert buildings[0]["levels"] == 3
    assert buildings[1]["levels"] == 1          # untagged -> default 1
    assert roads[0]["class"] == "primary"
    assert roads[0]["points"][0] == (40.000, -73.000)


def test_fetch_osm_uses_cache(tmp_path):
    calls = {"n": 0}
    def fake_fetch(query):
        calls["n"] += 1
        return _json.dumps(_OVERPASS_FIXTURE)
    bbox = (40.0, -73.1, 40.1, -73.0)
    a = ov.fetch_osm(bbox, cache_dir=str(tmp_path), fetch=fake_fetch)
    b = ov.fetch_osm(bbox, cache_dir=str(tmp_path), fetch=fake_fetch)
    assert calls["n"] == 1                        # second call served from cache
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k overpass -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city.overpass'`

- [ ] **Step 3: Write minimal implementation**

Create `asphodel/osm_city/overpass.py`:

```python
"""Fetch + parse OSM data for a bbox via the Overpass API.

Uses `out geom;` so each way carries its node geometry inline (no separate node
resolution). Raw responses are cached by query hash for offline replay and fast
tests. Network access is injectable.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

from . import OSMError

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Asphodel/0.1 (research prototype; https://github.com/maxhightower/Asphodel)"

_MAJOR_HIGHWAYS = "motorway|trunk|primary|secondary"


def build_query(bbox) -> str:
    """Overpass QL for major roads + building footprints inside `bbox` (s,w,n,e)."""
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    return (
        "[out:json][timeout:60];"
        "("
        f'way["building"]({box});'
        f'way["highway"~"^({_MAJOR_HIGHWAYS})$"]({box});'
        ");"
        "out geom;"
    )


def _default_fetch(query: str) -> str:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(
        OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8")


def _fetch_with_retry(query: str, fetch, retries: int) -> str:
    last = None
    for attempt in range(retries):
        try:
            return fetch(query)
        except Exception as exc:  # network/timeout/429 -> backoff and retry
            last = exc
            time.sleep(2 ** attempt)
    raise OSMError(f"Overpass request failed after {retries} attempts: {last}")


def fetch_osm(bbox, cache_dir=None, fetch=_default_fetch, retries: int = 3) -> dict:
    """Return the parsed Overpass JSON dict for `bbox`, using a disk cache if given."""
    query = build_query(bbox)
    path = None
    if cache_dir:
        key = hashlib.sha1(query.encode("utf-8")).hexdigest()
        path = os.path.join(cache_dir, f"{key}.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    raw = _fetch_with_retry(query, fetch, retries)
    data = json.loads(raw)
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    return data


def _parse_levels(tags: dict) -> int:
    try:
        return max(1, int(float(tags.get("building:levels", 1))))
    except (TypeError, ValueError):
        return 1


def parse_osm(data: dict):
    """Split Overpass elements into (buildings, roads).

    buildings: [{"ring": [(lat,lon),...], "levels": int}]
    roads:     [{"class": str, "points": [(lat,lon),...]}]
    """
    buildings, roads = [], []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry")
        if not geom:
            continue
        pts = [(g["lat"], g["lon"]) for g in geom]
        tags = el.get("tags", {})
        if "building" in tags:
            buildings.append({"ring": pts, "levels": _parse_levels(tags)})
        elif "highway" in tags:
            roads.append({"class": tags["highway"], "points": pts})
    return buildings, roads
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -k overpass -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/overpass.py tests/test_osm_city.py
git commit -m "feat(osm): Overpass fetch/parse with disk cache"
```

---

## Task 7: Bundle assembly + deterministic write

**Files:**
- Create: `asphodel/osm_city/bundle.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
import os

from asphodel.osm_city import bundle as bnd


def _toy_inputs():
    meta = {"name": "Toy", "query": "Toy", "bbox": [0, 0, 1, 1],
            "center": [0.5, 0.5], "projection": "equirectangular",
            "grid": {"rows": 2, "cols": 2, "cell_m": 100.0},
            "dt": 0.25, "n_days": 1.0, "n_ticks": 4,
            "genome": {"R0": 3.0}, "seed": 0, "seed_zone": 0, "version": "1"}
    zones = [{"id": 0, "row": 0, "col": 0, "center_xy": [0.0, 0.0], "extent": [100.0, 100.0],
              "population": 1000.0, "density": 1.0, "blocks": []}]
    roads = {"polylines": [{"class": "primary", "points": [[0.0, 0.0], [10.0, 10.0]]}]}
    timeline = {"field": "belief", "shape": [5, 1], "data": [[0.0], [0.1], [0.2], [0.3], [0.4]]}
    return meta, zones, roads, timeline


def test_write_bundle_creates_all_files(tmp_path):
    meta, zones, roads, timeline = _toy_inputs()
    bnd.write_bundle(str(tmp_path), meta, zones, roads, timeline)
    for name in ("meta.json", "zones.json", "roads.json", "timeline.json"):
        assert os.path.exists(tmp_path / name)


def test_write_bundle_is_deterministic(tmp_path):
    meta, zones, roads, timeline = _toy_inputs()
    a, b = tmp_path / "a", tmp_path / "b"
    bnd.write_bundle(str(a), meta, zones, roads, timeline)
    bnd.write_bundle(str(b), meta, zones, roads, timeline)
    for name in ("meta.json", "zones.json", "roads.json", "timeline.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_build_timeline_rounds_and_shapes():
    import numpy as np
    hist = np.array([[0.123456789, 0.5], [0.987654321, 0.25]])
    tl = bnd.build_timeline(hist)
    assert tl["field"] == "belief"
    assert tl["shape"] == [2, 2]
    assert tl["data"][0][0] == 0.12346     # rounded to 5 dp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k bundle -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city.bundle'`

- [ ] **Step 3: Write minimal implementation**

Create `asphodel/osm_city/bundle.py`:

```python
"""Assemble and write the city bundle (meta / zones / roads / timeline JSON).

Writes are deterministic: keys sorted, floats rounded, so identical inputs
produce byte-identical files (the spec's reproducibility guarantee).
"""
from __future__ import annotations

import json
import os


def build_timeline(belief_history, field: str = "belief", ndigits: int = 5) -> dict:
    """Turn a (n_ticks+1, Z) belief array into the timeline payload."""
    rows, cols = belief_history.shape
    data = [[round(float(v), ndigits) for v in row] for row in belief_history]
    return {"field": field, "shape": [rows, cols], "data": data}


def _write_json(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def write_bundle(out_dir: str, meta: dict, zones: list, roads: dict, timeline: dict) -> None:
    """Write the four bundle files into `out_dir` (created if absent)."""
    os.makedirs(out_dir, exist_ok=True)
    _write_json(os.path.join(out_dir, "meta.json"), meta)
    _write_json(os.path.join(out_dir, "zones.json"), zones)
    _write_json(os.path.join(out_dir, "roads.json"), roads)
    _write_json(os.path.join(out_dir, "timeline.json"), timeline)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -k bundle -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/bundle.py tests/test_osm_city.py
git commit -m "feat(osm): deterministic bundle assembly + writer"
```

---

## Task 8: Pipeline core + CLI (end-to-end, offline)

**Files:**
- Create: `asphodel/osm_city/pipeline.py`
- Create: `asphodel/osm_city/__main__.py`
- Test: `tests/test_osm_city.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_osm_city.py`:

```python
from asphodel.osm_city import pipeline as pipe


def test_build_bundle_end_to_end_offline(tmp_path):
    # Use the Overpass fixture parsed into buildings/roads, no network.
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    bbox = (40.0, -73.01, 40.01, -73.0)
    out = tmp_path / "city"
    pipe.build_bundle(
        query="Toytown", bbox=bbox, buildings=buildings, roads=roads,
        out_dir=str(out), grid=4, total_pop=20000.0, seed=0, n_days=10.0,
    )
    meta = _json.loads((out / "meta.json").read_text())
    zones = _json.loads((out / "zones.json").read_text())
    timeline = _json.loads((out / "timeline.json").read_text())

    assert meta["grid"]["rows"] * meta["grid"]["cols"] == len(zones)
    assert timeline["shape"] == [meta["n_ticks"] + 1, len(zones)]
    assert abs(sum(z["population"] for z in zones) - 20000.0) < 1.0
    assert all("blocks" in z for z in zones)
    # seed_zone is a populated cell
    assert zones[meta["seed_zone"]]["population"] > 0.0


def test_build_bundle_is_byte_deterministic(tmp_path):
    buildings, roads = ov.parse_osm(_OVERPASS_FIXTURE)
    bbox = (40.0, -73.01, 40.01, -73.0)
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        pipe.build_bundle(query="Toytown", bbox=bbox, buildings=buildings, roads=roads,
                          out_dir=str(out), grid=4, total_pop=20000.0, seed=0, n_days=10.0)
    for name in ("meta.json", "zones.json", "roads.json", "timeline.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_osm_city.py -k build_bundle -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city.pipeline'`

- [ ] **Step 3: Write minimal implementation**

Create `asphodel/osm_city/pipeline.py`:

```python
"""End-to-end (network-free) core: parsed OSM -> bundle on disk.

`build_bundle` takes an already-resolved bbox plus parsed buildings/roads (so it
is fully testable offline), tessellates, runs the existing belief-cascade sim on
the resulting per-zone populations, lays out blocks/roads, and writes the bundle.
"""
from __future__ import annotations

import random

from dataclasses import asdict

from ..config import ScenarioConfig, ModelParams, GraphParams, PathogenGenome
from ..runner import run_scenario
from . import geometry as geo
from . import tessellate as tess
from . import bundle as bnd


def _densest_populated_zone(zones: list[dict]) -> int:
    best = max(zones, key=lambda z: z["population"])
    if best["population"] > 0.0:
        return best["id"]
    return len(zones) // 2  # fallback: grid center-ish


def build_bundle(query, bbox, buildings, roads, out_dir, grid=16,
                 total_pop=500000.0, seed=0, n_days=120.0, dt=0.25,
                 genome=None) -> None:
    genome = genome or PathogenGenome()
    south, west, north, east = bbox
    lat0, lon0 = (south + north) / 2.0, (west + east) / 2.0

    # 1. Tessellate into a grid with density-weighted population.
    t = tess.tessellate(bbox, buildings, grid=grid, total_pop=total_pop)
    populations = [z["population"] for z in t.zones]
    seed_zone = _densest_populated_zone(t.zones)

    # 2. Run the existing belief-cascade sim on the real populations.
    cfg = ScenarioConfig(
        name=query,
        genome=genome,
        model=ModelParams(graph=GraphParams(
            grid_rows=t.rows, grid_cols=t.cols, population=populations,
        )),
        dt=dt, n_days=n_days, seed=seed, seed_zone=seed_zone,
    )
    result = run_scenario(cfg)

    # 3. Lay out representative blocks per zone (deterministic RNG).
    rng = random.Random(seed)
    for z in t.zones:
        z["blocks"] = geo.place_blocks(
            z["density"], tuple(z["center_xy"]), tuple(z["extent"]), rng,
        )

    # 4. Project roads to local meters.
    road_out = {"polylines": [
        {"class": r["class"], "points": geo.project_polyline(r["points"], lat0, lon0)}
        for r in roads
    ]}

    # 5. Assemble bundle.
    meta = {
        "name": query, "query": query,
        "bbox": [south, west, north, east], "center": [lat0, lon0],
        "projection": "equirectangular",
        "grid": {"rows": t.rows, "cols": t.cols, "cell_m": round(t.cell_w, 3)},
        "dt": dt, "n_days": n_days, "n_ticks": cfg.n_ticks,
        "genome": asdict(genome), "seed": seed, "seed_zone": seed_zone,
        "version": "1",
    }
    timeline = bnd.build_timeline(result.belief_history)
    bnd.write_bundle(out_dir, meta, t.zones, road_out, timeline)
```

Create `asphodel/osm_city/__main__.py`:

```python
"""CLI: python -m asphodel.osm_city "<city>" --out <dir>

Geocodes the city, fetches OSM (cached), and writes a bundle Godot can load.
"""
from __future__ import annotations

import argparse
import sys

from . import OSMError
from .geocode import geocode
from .overpass import fetch_osm, parse_osm
from .pipeline import build_bundle


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="asphodel.osm_city")
    p.add_argument("city", help="City name to geocode, e.g. \"Chicago\"")
    p.add_argument("--out", required=True, help="Output bundle directory")
    p.add_argument("--grid", type=int, default=16, help="Cells along the longer axis")
    p.add_argument("--total-pop", type=float, default=500000.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--days", type=float, default=120.0)
    p.add_argument("--cache", default=None, help="OSM response cache directory")
    p.add_argument("--max-span-deg", type=float, default=0.5)
    args = p.parse_args(argv)

    try:
        bbox = geocode(args.city, max_span_deg=args.max_span_deg)
        data = fetch_osm(bbox, cache_dir=args.cache)
        buildings, roads = parse_osm(data)
        build_bundle(
            query=args.city, bbox=bbox, buildings=buildings, roads=roads,
            out_dir=args.out, grid=args.grid, total_pop=args.total_pop,
            seed=args.seed, n_days=args.days,
        )
    except OSMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote bundle to {args.out} "
          f"({len(buildings)} buildings, {len(roads)} roads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_osm_city.py -k build_bundle -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/test_osm_city.py tests/test_model.py -q`
Expected: PASS (all tests pass — Phase 1 complete, no sim regression)

- [ ] **Step 6: Commit**

```bash
git add asphodel/osm_city/pipeline.py asphodel/osm_city/__main__.py tests/test_osm_city.py
git commit -m "feat(osm): end-to-end pipeline core + CLI"
```

---

## Task 9: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an OSM-city section to the README**

Append after the Phase 4a section in `README.md`:

```markdown
## OSM City Pipeline (Phase 1)

Turn a real city into an Asphodel bundle (zone graph + density-weighted
population + roads + a precomputed belief-cascade timeline) that the Godot
frontend renders.

\```bash
# Geocode a city, fetch OSM, run the sim, write a bundle
python -m asphodel.osm_city "Chicago" --out output/chicago --cache output/osm_cache

# Knobs: grid resolution, total population, sim horizon, RNG seed
python -m asphodel.osm_city "Boston" --out output/boston --grid 20 --total-pop 650000 --days 90
\```

The bundle is four JSON files (`meta`, `zones`, `roads`, `timeline`); the format
is documented in `docs/superpowers/specs/2026-06-01-osm-city-scene-design.md`.
All network access is cached, so re-runs are offline and deterministic.

\```bash
python -m pytest tests/test_osm_city.py -q   # offline (inline fixtures)
\```
```

(Remove the backslashes before the code fences — they're escaped here only to nest inside this plan.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the OSM city pipeline (Phase 1)"
```

---

## Done criteria (Phase 1)

- `python -m asphodel.osm_city "<city>" --out <dir>` writes a valid 4-file bundle.
- Per-zone population comes from real building density; the sim runs on it.
- `timeline.json` is `(n_ticks+1, Z)` belief, ready for Godot playback.
- Bundles are byte-deterministic from identical inputs.
- `tests/test_osm_city.py` passes offline; `tests/test_model.py` shows no regression.

**Next:** Phase 2 (Godot scene generation from a checked-in sample bundle) gets its own plan, followed by Phase 3 (city-select UX + timeline playback).

"""Deterministic, seed-stable value noise for regional terrain (AS-REGION-0).

No external noise library: a small integer-hash value noise plus fractal (fBm)
and ridged variants, all pure numpy so they run on scalars or whole arrays. The
same (coord, seed) always yields the same value on any machine — the
reproducibility guarantee terrain generation is tested against (§17.1).
"""
from __future__ import annotations

import numpy as np

# A large odd constant mix (splitmix-ish) keeps the hash well-distributed while
# staying integer-deterministic across platforms via uint64 wraparound.
_MASK = np.uint64(0xFFFFFFFFFFFFFFFF)


def _hash2(ix, iy, seed: int):
    """Hash integer lattice coords -> float in [0, 1). Vectorized over arrays.

    uint64 multiply wraps modulo 2**64 (intentional splitmix mixing); numpy would
    warn on that as "overflow", so we silence it locally — the wraparound is the
    algorithm, not a bug.
    """
    with np.errstate(over="ignore", invalid="ignore"):
        x = np.asarray(ix, dtype=np.int64).astype(np.uint64)
        y = np.asarray(iy, dtype=np.int64).astype(np.uint64)
        h = (x * np.uint64(0x9E3779B97F4A7C15)) & _MASK
        h ^= (y + np.uint64(0x632BE59BD9B4E019)) & _MASK
        h = (h ^ (h >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9) & _MASK
        h = (h ^ (h >> np.uint64(27))) * np.uint64(0x94D049BB133111EB) & _MASK
        h = (h ^ np.uint64(seed & 0xFFFFFFFFFFFFFFFF)) & _MASK
        h ^= h >> np.uint64(31)
        return (h & np.uint64(0xFFFFFF)).astype(np.float64) / float(0x1000000)


def _smooth(t):
    # Quintic smootherstep: C2-continuous, so fBm has no lattice creases.
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(x, y, seed: int = 0):
    """Bilinear value noise in [0, 1) with smootherstep interpolation."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = _smooth(x - x0)
    fy = _smooth(y - y0)
    v00 = _hash2(x0, y0, seed)
    v10 = _hash2(x0 + 1, y0, seed)
    v01 = _hash2(x0, y0 + 1, seed)
    v11 = _hash2(x0 + 1, y0 + 1, seed)
    a = v00 + (v10 - v00) * fx
    b = v01 + (v11 - v01) * fx
    return a + (b - a) * fy


def fbm(x, y, seed: int = 0, octaves: int = 5, lacunarity: float = 2.0,
        gain: float = 0.5, frequency: float = 1.0):
    """Fractal Brownian motion in ~[0, 1]. Smooth rolling terrain."""
    total = np.zeros(np.broadcast(np.asarray(x), np.asarray(y)).shape, dtype=np.float64)
    amp = 1.0
    freq = frequency
    norm = 0.0
    for o in range(octaves):
        total = total + amp * value_noise(x * freq, y * freq, seed + o * 1013)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm if norm else total


def ridged(x, y, seed: int = 0, octaves: int = 5, lacunarity: float = 2.0,
           gain: float = 0.5, frequency: float = 1.0):
    """Ridged multifractal in ~[0, 1]. Sharp ridgelines for mountain fronts."""
    total = np.zeros(np.broadcast(np.asarray(x), np.asarray(y)).shape, dtype=np.float64)
    amp = 1.0
    freq = frequency
    norm = 0.0
    for o in range(octaves):
        n = value_noise(x * freq, y * freq, seed + o * 2027)
        r = 1.0 - np.abs(2.0 * n - 1.0)  # crease toward 1 -> ridgelines
        total = total + amp * (r * r)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm if norm else total

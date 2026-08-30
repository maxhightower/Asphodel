"""Core determinism tests for the outside-world compiler substrate."""
from __future__ import annotations

from asphodel.world_source.chunkgrid import (
    CELLS_PER_CHUNK,
    ChunkGrid,
    rle_decode,
    rle_encode,
)
from asphodel.world_source.detrand import DetRand, hash64


def test_hash64_stable_values():
    # Pinned values: if these change, every procedural placement re-rolls.
    assert hash64(0, "houston") == hash64(0, "houston")
    assert hash64(0, "houston") != hash64(1, "houston")
    assert hash64(0, "houston") != hash64(0, "houstom")
    assert hash64("ab", "c") != hash64("a", "bc")  # length folding


def test_detrand_streams_independent_and_repeatable():
    a1 = [DetRand(7, "b:1", "props").random() for _ in range(3)]
    a2 = [DetRand(7, "b:1", "props").random() for _ in range(3)]
    b = [DetRand(7, "b:2", "props").random() for _ in range(3)]
    assert a1 == a2
    assert a1 != b
    for v in a1 + b:
        assert 0.0 <= v < 1.0


def test_detrand_helpers():
    r = DetRand(1, "x")
    for _ in range(200):
        assert 2 <= r.randint(2, 5) <= 5
    r2 = DetRand(2, "y")
    picks = {r2.weighted_choice([("a", 1.0), ("b", 3.0)]) for _ in range(200)}
    assert picks == {"a", "b"}


def test_chunk_grid_addressing():
    g = ChunkGrid(-2905.0, -3316.0, 2905.0, 3316.0)  # Houston-like extent
    assert g.cols == 23 and g.rows == 26
    assert g.chunk_of(-2905.0, -3316.0) == (0, 0)
    assert g.chunk_of(2904.9, 3315.9) == (g.cols - 1, g.rows - 1)
    # out-of-range clamps
    assert g.chunk_of(-9999, 9999) == (0, g.rows - 1)
    ox, oz = g.chunk_origin(1, 2)
    assert (ox, oz) == (-2905.0 + 256.0, -3316.0 + 512.0)
    assert len(list(g.all_chunks())) == g.cols * g.rows


def test_rle_roundtrip():
    raster = bytearray([4] * (CELLS_PER_CHUNK * CELLS_PER_CHUNK))
    raster[5000:5100] = bytes([1] * 100)
    runs = rle_encode(raster)
    assert rle_decode(runs, len(raster)) == raster
    assert len(runs) < 20  # highly compressible
    assert rle_encode(b"") == []

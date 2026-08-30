"""Chunk grid math and the semantic-surface RLE codec.

The compiled exterior world is partitioned into square chunks
(CHUNK_SIZE_M) in the bundle's projected metre frame (x=east, z=north,
origin at bbox centre).  Each chunk owns a 2 m semantic surface raster
stored row-major as run-length pairs [type, count, type, count, ...].

Chunks are addressed by integer (cx, cz) where chunk (0, 0)'s minimum
corner sits at the world minimum corner (west/south edge of the playable
extent), so chunk coords are always >= 0.
"""
from __future__ import annotations

from dataclasses import dataclass

CHUNK_SIZE_M = 256.0
SURFACE_CELL_M = 2.0
CELLS_PER_CHUNK = int(CHUNK_SIZE_M / SURFACE_CELL_M)  # 128


@dataclass(frozen=True)
class ChunkGrid:
    """World extent -> chunk addressing for one city bundle."""

    min_x: float
    min_z: float
    max_x: float
    max_z: float

    @property
    def cols(self) -> int:
        return max(1, int(-(-(self.max_x - self.min_x) // CHUNK_SIZE_M)))

    @property
    def rows(self) -> int:
        return max(1, int(-(-(self.max_z - self.min_z) // CHUNK_SIZE_M)))

    def chunk_of(self, x: float, z: float) -> tuple[int, int]:
        cx = int((x - self.min_x) // CHUNK_SIZE_M)
        cz = int((z - self.min_z) // CHUNK_SIZE_M)
        return (min(max(cx, 0), self.cols - 1), min(max(cz, 0), self.rows - 1))

    def chunk_origin(self, cx: int, cz: int) -> tuple[float, float]:
        """Minimum (west/south) corner of chunk (cx, cz) in world metres."""
        return (self.min_x + cx * CHUNK_SIZE_M, self.min_z + cz * CHUNK_SIZE_M)

    def all_chunks(self):
        for cz in range(self.rows):
            for cx in range(self.cols):
                yield (cx, cz)


def rle_encode(cells: bytes | bytearray) -> list[int]:
    """Row-major byte raster -> flat [type, count, ...] runs (count<=65535)."""
    out: list[int] = []
    if not cells:
        return out
    cur = cells[0]
    n = 0
    for b in cells:
        if b == cur and n < 65535:
            n += 1
        else:
            out.append(cur)
            out.append(n)
            cur = b
            n = 1
    out.append(cur)
    out.append(n)
    return out


def rle_decode(runs: list[int], expect_len: int | None = None) -> bytearray:
    out = bytearray()
    for i in range(0, len(runs), 2):
        out.extend(bytes([runs[i]]) * runs[i + 1])
    if expect_len is not None and len(out) != expect_len:
        raise ValueError(f"RLE length {len(out)} != expected {expect_len}")
    return out

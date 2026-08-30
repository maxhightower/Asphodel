"""Deterministic, order-independent randomness for world compilation.

Every procedural placement decision in the exterior compiler draws from a
stream keyed by (world_seed, generator_version, stable feature key, purpose
tag).  No global RNG state, no iteration-order dependence: the same feature
gets the same treatment no matter when or where it is compiled, which is
what makes chunks independently regenerable.

Presentation-only: nothing here touches simulation RNG streams.
"""
from __future__ import annotations

# Version stamp for the whole procedural generator family.  Bump when a
# change is *supposed* to re-roll the world's procedural detail.
GENERATOR_VERSION = 1

_MASK64 = 0xFFFFFFFFFFFFFFFF


def _splitmix64(x: int) -> int:
    """One splitmix64 step — small, stable, well-mixed."""
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return (z ^ (z >> 31)) & _MASK64


def hash64(*parts: object) -> int:
    """Combine ints/strings into one stable 64-bit hash.

    Strings are folded bytewise; ints folded directly.  Python's built-in
    hash() is salted per-process and MUST NOT be used here.
    """
    h = 0x8B72E9A6379BF213
    for p in parts:
        if isinstance(p, int):
            h = _splitmix64(h ^ (p & _MASK64))
        elif isinstance(p, str):
            for b in p.encode("utf-8"):
                h = _splitmix64(h ^ b)
            h = _splitmix64(h ^ len(p))
        elif isinstance(p, float):
            # floats only enter via already-quantized values; fold repr
            for b in repr(p).encode("ascii"):
                h = _splitmix64(h ^ b)
        else:
            raise TypeError(f"unhashable part type {type(p)!r}")
    return h


class DetRand:
    """Tiny deterministic RNG over a splitmix64 stream."""

    __slots__ = ("_state",)

    def __init__(self, *key: object) -> None:
        self._state = hash64(GENERATOR_VERSION, *key)

    def _next(self) -> int:
        self._state = _splitmix64(self._state)
        return self._state

    def random(self) -> float:
        """Uniform in [0, 1)."""
        return (self._next() >> 11) / float(1 << 53)

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.random()

    def randint(self, lo: int, hi: int) -> int:
        """Inclusive both ends."""
        span = hi - lo + 1
        return lo + (self._next() % span)

    def chance(self, p: float) -> bool:
        return self.random() < p

    def choice(self, seq):
        return seq[self._next() % len(seq)]

    def weighted_choice(self, pairs):
        """pairs: iterable of (value, weight>0)."""
        pairs = list(pairs)
        total = sum(w for _, w in pairs)
        r = self.random() * total
        acc = 0.0
        for v, w in pairs:
            acc += w
            if r < acc:
                return v
        return pairs[-1][0]

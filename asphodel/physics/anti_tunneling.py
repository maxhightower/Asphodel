"""Anti-tunneling contract for fast movers (AS-NAV-3 §8.3).

The engine realizes vehicle motion in Godot, which this environment cannot run.
But the *contract* the engine must honour is testable here: at maximum gameplay
speed a body impacting a thin solid barrier must never emerge on the far side.

Two tools enforce that:

* :func:`swept_segment_hits_aabb` — continuous (swept) collision between a body's
  motion segment this frame and a barrier box. This is the guarantee: it detects
  the crossing regardless of how large the per-frame displacement is, which naive
  end-point sampling (checking only where the body lands) does not.
* :func:`required_substeps` — how many integration substeps keep per-substep
  displacement below a barrier thickness, for engines that prefer substepping to
  a true swept shape.

The Godot vehicle controller must use one or the other; the regression test here
encodes the acceptance gate.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

Vec2 = Tuple[float, float]
AABB = Tuple[float, float, float, float]  # (min_x, min_z, max_x, max_z)


def swept_segment_hits_aabb(p0: Vec2, p1: Vec2, box: AABB,
                            radius: float = 0.0) -> bool:
    """Does the motion segment p0->p1 (optionally a disc of ``radius``) cross box?

    Slab method on the box expanded by ``radius``. Returns True if any point of
    the swept path intersects the barrier — the continuous-collision guarantee.
    """
    minx, minz, maxx, maxz = box
    minx -= radius; minz -= radius; maxx += radius; maxz += radius
    dx = p1[0] - p0[0]
    dz = p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for (p, d, lo, hi) in ((p0[0], dx, minx, maxx), (p0[1], dz, minz, maxz)):
        if abs(d) < 1e-12:
            if p < lo or p > hi:
                return False  # parallel and outside this slab
        else:
            ta = (lo - p) / d
            tb = (hi - p) / d
            if ta > tb:
                ta, tb = tb, ta
            t0 = max(t0, ta)
            t1 = min(t1, tb)
            if t0 > t1:
                return False
    return True


def endpoint_sampling_would_miss(p0: Vec2, p1: Vec2, box: AABB) -> bool:
    """True if checking only the endpoints misses a crossing the sweep catches.

    Demonstrates the tunneling failure mode the contract exists to prevent.
    """
    def inside(p: Vec2) -> bool:
        return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]
    return (not inside(p0) and not inside(p1)
            and swept_segment_hits_aabb(p0, p1, box))


def required_substeps(speed_mps: float, dt: float, min_thickness: float,
                      safety: float = 0.5) -> int:
    """Substeps so per-substep displacement stays below ``safety * thickness``."""
    disp = abs(speed_mps) * dt
    max_step = max(1e-6, min_thickness * safety)
    return max(1, math.ceil(disp / max_step))


def max_substep_displacement(speed_mps: float, dt: float, substeps: int) -> float:
    return abs(speed_mps) * dt / max(1, substeps)

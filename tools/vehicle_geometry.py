"""Shared vehicle footprint dimensions + oriented-bounding-box overlap (SAT), used
by the de-overlap repatch and the overlap correctness test.

Dimensions are the approximate (length, width) in metres of each vehicle mesh in
prop_meshes.gd (length along the vehicle's heading). Heading follows the compiler
convention _heading_deg(dx, dz) = atan2(dx, dz), so the length axis in world XZ is
(sin h, cos h) and the width axis is (cos h, -sin h)."""
from __future__ import annotations

import math

# kind -> (length_m, width_m)
VEHICLE_DIMS = {
    "sedan": (4.5, 1.8),
    "sports_car": (4.4, 1.86),
    "suv": (4.7, 1.9),
    "jeep": (4.2, 1.9),
    "pickup": (5.2, 1.8),
    "van": (4.9, 1.95),
    "box_truck": (6.0, 2.2),
    "semi_truck": (17.0, 2.5),
    "oil_tanker": (16.5, 2.45),
}
DEFAULT_DIM = (4.6, 1.85)


def dims(kind: str) -> tuple[float, float]:
    return VEHICLE_DIMS.get(kind, DEFAULT_DIM)


def _obb(x: float, z: float, heading_deg: float, half_l: float, half_w: float):
    h = math.radians(heading_deg)
    lx, lz = math.sin(h), math.cos(h)      # length axis
    wx, wz = math.cos(h), -math.sin(h)     # width axis
    return (x, z, (lx, lz), (wx, wz), half_l, half_w)


def _radius(obb, axis) -> float:
    _, _, la, wa, hl, hw = obb
    return hl * abs(la[0] * axis[0] + la[1] * axis[1]) + hw * abs(wa[0] * axis[0] + wa[1] * axis[1])


def obb_overlap(a, b, scale: float = 1.0) -> bool:
    """True if the two vehicle OBBs overlap. `a`,`b` = (x, z, heading_deg, kind).
    `scale` shrinks (or pads) both footprints — use <1 to require a real overlap,
    not just bumper contact."""
    la, wa = dims(a[3])
    lb, wb = dims(b[3])
    oa = _obb(a[0], a[1], a[2], la * 0.5 * scale, wa * 0.5 * scale)
    ob = _obb(b[0], b[1], b[2], lb * 0.5 * scale, wb * 0.5 * scale)
    dx, dz = ob[0] - oa[0], ob[1] - oa[1]
    for axis in (oa[2], oa[3], ob[2], ob[3]):
        d = abs(dx * axis[0] + dz * axis[1])
        if d > _radius(oa, axis) + _radius(ob, axis):
            return False   # separating axis found
    return True

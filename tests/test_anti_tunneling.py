"""Anti-tunneling contract regression gate (AS-NAV-3 §8.3, §18 item 10)."""
from __future__ import annotations

from asphodel.physics.anti_tunneling import (
    swept_segment_hits_aabb,
    endpoint_sampling_would_miss,
    required_substeps,
    max_substep_displacement,
)

# A thin solid barrier: 0.2 m thick wall spanning z in [-5, 5] at x in [0, 0.2].
THIN_BARRIER = (0.0, -5.0, 0.2, 5.0)
MAX_SPEED = 40.0   # m/s, emergency vehicle top speed
DT = 1.0 / 60.0


def test_swept_detects_high_speed_crossing():
    # A car at max speed crosses the whole barrier in one frame (~0.67 m of
    # travel over a 0.2 m wall): the endpoints straddle it, the sweep catches it.
    p0 = (-0.1, 0.0)
    p1 = (-0.1 + MAX_SPEED * DT, 0.0)
    assert p1[0] > THIN_BARRIER[2]        # really did overshoot the far face
    assert swept_segment_hits_aabb(p0, p1, THIN_BARRIER)


def test_endpoint_sampling_would_tunnel():
    # Both frame endpoints are OUTSIDE the barrier, yet the path crossed it:
    # this is exactly the tunneling a naive check misses and the sweep catches.
    p0 = (-0.3, 0.0)
    p1 = (0.5, 0.0)
    assert endpoint_sampling_would_miss(p0, p1, THIN_BARRIER)


def test_regression_gate_never_emerges_on_far_side():
    # Sweep the full range of per-frame displacements up to max speed; a straight
    # shot at the wall is ALWAYS detected — never emerges on the opposite side.
    for frac in range(1, 21):
        disp = MAX_SPEED * DT * frac      # up to ~0.67 m * 20 (very fast / low fps)
        p0 = (-0.05 - disp, 0.0)
        p1 = (p0[0] + disp + 0.1, 0.0)
        assert swept_segment_hits_aabb(p0, p1, THIN_BARRIER, radius=0.05)


def test_required_substeps_keep_step_below_thickness():
    n = required_substeps(MAX_SPEED, DT, min_thickness=0.2)
    assert max_substep_displacement(MAX_SPEED, DT, n) < 0.2


def test_miss_when_path_does_not_reach_barrier():
    # Moving parallel and away must NOT report a hit.
    assert not swept_segment_hits_aabb((-1.0, 0.0), (-1.0, 3.0), THIN_BARRIER)
    assert not swept_segment_hits_aabb((-1.0, 0.0), (-0.5, 0.0), THIN_BARRIER)

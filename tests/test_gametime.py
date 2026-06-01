"""
Game-time tests: real-seconds <-> in-game-hours <-> sim ticks, the collapse
warp, and citizen-schedule playback.

Run with:  python -m pytest tests/test_gametime.py -q
       or:  python tests/test_gametime.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.gametime import TimeScale, default_timescale, schedule_playback
from asphodel.citizen import default_catalog, default_cities, spawn_citizen


def test_default_is_pz_one_hour_per_day():
    ts = default_timescale()
    assert ts.real_seconds_per_day == 3600.0           # 1 real hour / in-game day
    assert ts.real_seconds_per_hour == 150.0           # 3600 / 24
    assert ts.real_seconds_per_tick == 900.0           # 6h tick at dt=0.25


def test_hour_conversions_round_trip():
    ts = TimeScale(real_seconds_per_day=1800.0)
    for h in (0.0, 1.5, 8.0, 24.0):
        assert abs(ts.game_hours(ts.real_seconds(h)) - h) < 1e-9


def test_collapse_warp_pins_panic_to_player_day_two():
    ts = TimeScale(collapse_by_day=2.0)
    # A scenario that tips on sim day 48 must be warped 24x so the player hits it
    # at player-day 2.
    warp = ts.collapse_warp(48.0)
    assert warp == 24.0
    assert abs(ts.player_day_to_sim_day(2.0, 48.0) - 48.0) < 1e-9
    # A scenario already tipping before day 2 is never slowed below real-time.
    assert ts.collapse_warp(1.0) == 1.0
    # No tip => no warp.
    assert ts.collapse_warp(None) == 1.0


def test_plan_session_reports_minutes_to_collapse():
    ts = default_timescale()                            # 1 hr/day, collapse day 2
    plan = ts.plan_session(sim_panic_day=40.0)
    # 2 in-game days at 1 hr/day => 2 real hours to collapse.
    assert abs(plan["real_minutes_to_collapse"] - 120.0) < 1e-6
    assert abs(plan["sim_day_at_collapse"] - 40.0) < 1e-6
    assert plan["collapse_warp"] == 20.0


def test_schedule_playback_compresses_downtime():
    ts = default_timescale()
    cat = default_catalog()
    c = spawn_citizen(default_cities()["generic"], cat, seed=3)
    rows = schedule_playback(c.schedule, ts)
    assert len(rows) == len(c.schedule)
    # Timeline is contiguous and monotonic.
    t = 0.0
    for r in rows:
        assert abs(r["real_start_s"] - t) < 1e-6
        t += r["real_seconds"]
    # A sleep hour is compressed relative to a same-length active hour.
    base_hour_s = ts.real_seconds(1.0)
    for r in rows:
        if r["activity"] == "sleep":
            per_hour = r["real_seconds"] / r["game_hours"]
            assert per_hour < base_hour_s
            break


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} checks passed.")

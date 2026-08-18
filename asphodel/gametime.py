"""
Game time: the bridge between real player seconds, the in-game clock the citizen
schedule runs on, and the simulation's tick/day axis.

The design target (Project-Zomboid-style pacing, with one Asphodel twist):

* **A full 24-hour cycle defaults to one real hour** -- PZ's default Day Length --
  so a work shift feels like a shift but you reach nightfall in a sitting. The
  rate is a single tunable knob (`real_seconds_per_day`).
* **The collapse must land within ~2 in-game days of play.** The epidemic is a
  long (≈120-day) calibrated arc, so we do *not* change its dynamics to force an
  early tip. Instead the player clock is *warped* against sim time: player day 2
  is pinned to the simulation's panic tipping point, so however long the
  pathogen actually takes to boil over, the player experiences it by day 2.
  Near the tip the warp relaxes toward real-time so the panic plays at full
  PZ minute-to-minute tension.
* **Downtime fast-forwards.** Sleep/idle blocks run at a compression factor, the
  way holding the skip key does in PZ, so the playable session is the
  interesting hours, not eight hours of watching someone sleep.

Everything here is pure arithmetic on top of the existing time scales
(`ScenarioConfig.dt` in days, the citizen schedule in hours), so it composes
with both tiers without touching them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TimeScale:
    """How real seconds map to in-game hours, sim ticks, and the player's arc."""

    # PZ default: one real hour per in-game day (sandbox-tunable down to seconds).
    real_seconds_per_day: float = 3600.0

    # Simulation tick length in days (mirror of ScenarioConfig.dt).
    dt_days: float = 0.25

    # The player should reach the collapse within this many in-game days, and
    # keep playing for a short aftermath beyond it.
    collapse_by_day: float = 2.0
    aftermath_days: float = 0.5

    # Sleep / idle downtime runs this many times faster than wall-clock.
    sleep_compression: float = 8.0

    # ---- base-rate conversions (player day == in-game day at this rate) ------
    @property
    def real_seconds_per_hour(self) -> float:
        return self.real_seconds_per_day / 24.0

    @property
    def real_seconds_per_tick(self) -> float:
        """Wall-clock seconds one simulation tick occupies at the base rate."""
        return self.real_seconds_per_day * self.dt_days

    @property
    def playable_days(self) -> float:
        """The player's session arc: up to collapse, plus a short aftermath."""
        return self.collapse_by_day + self.aftermath_days

    def real_seconds(self, game_hours: float) -> float:
        return game_hours * self.real_seconds_per_hour

    def game_hours(self, real_seconds: float) -> float:
        return real_seconds / self.real_seconds_per_hour

    def real_seconds_for_days(self, game_days: float) -> float:
        return game_days * self.real_seconds_per_day

    # ---- the collapse warp (sim time vs player time) -------------------------
    def collapse_warp(self, sim_panic_day: float | None) -> float:
        """*Average* sim-days advanced per player-day over the run-up to collapse,
        so the sim's panic tipping point lands on the player's ``collapse_by_day``.

        ``>1`` means sim time runs faster than the player clock -- compressing a
        long silent-incubation stretch into the playable window. ``None`` panic
        day (the sim never tips) falls back to 1.0 (no warp).

        This is the *mean* slope of ``player_day_to_sim_day`` over ``[0,
        collapse_by_day]``; the instantaneous slope is eased (see ``warp_at``):
        fast during the silent incubation and relaxing to real-time at the tip.
        """
        if not sim_panic_day or self.collapse_by_day <= 0:
            return 1.0
        return max(1.0, sim_panic_day / self.collapse_by_day)

    def player_day_to_sim_day(self, player_day: float,
                              sim_panic_day: float | None) -> float:
        """Map a player-experienced day onto a simulation day under an *eased*
        warp.

        The design promise (see the module docstring) is that time is compressed
        hardest early -- through the long silent incubation -- and **relaxes
        toward real-time as the panic tip approaches**, so the collapse itself
        plays at full minute-to-minute tension. A constant linear warp would run
        the tip in fast-forward too; instead the mapping is the quadratic that

            * passes through the origin,             f(0)   = 0
            * hits the panic day at collapse_by_day, f(D)   = sim_panic_day
            * arrives at real-time speed there,      f'(D)  = 1

        which forces the early slope to ``2*warp - 1`` and eases it monotonically
        down to 1.0 at the tip. Past ``collapse_by_day`` (the aftermath) time
        continues at real-time (slope 1).
        """
        D = self.collapse_by_day
        warp = self.collapse_warp(sim_panic_day)
        if warp <= 1.0 or D <= 0:
            return player_day                        # no compression: real-time
        P = D * warp                                 # sim day at collapse
        if player_day <= D:
            a = (D - P) / (D * D)                    # concave: slope decreasing
            b = 2.0 * P / D - 1.0                    # early slope = 2*warp - 1
            return a * player_day * player_day + b * player_day
        return P + (player_day - D)                  # real-time aftermath tail

    def warp_at(self, player_day: float, sim_panic_day: float | None) -> float:
        """Instantaneous warp (sim-days advanced per player-day) at ``player_day``.

        Eases from ``2*collapse_warp - 1`` at day 0 down to ~1.0 at the tip, then
        stays at 1.0 through the aftermath.
        """
        D = self.collapse_by_day
        warp = self.collapse_warp(sim_panic_day)
        if warp <= 1.0 or D <= 0 or player_day >= D:
            return 1.0
        P = D * warp
        a = (D - P) / (D * D)
        b = 2.0 * P / D - 1.0
        return 2.0 * a * player_day + b               # f'(player_day)

    def sim_tick_of_player_day(self, player_day: float,
                               sim_panic_day: float | None) -> int:
        sim_day = self.player_day_to_sim_day(player_day, sim_panic_day)
        return int(round(sim_day / self.dt_days))

    # ---- session planning ----------------------------------------------------
    def plan_session(self, sim_panic_day: float | None) -> dict:
        """Summarise the real-time shape of a session for a given scenario.

        ``sim_panic_day`` is the simulation's panic tipping day (e.g. from
        ``RunResult.panic_day()``); pass ``None`` if it never tips.
        """
        warp = self.collapse_warp(sim_panic_day)
        to_collapse_s = self.real_seconds_for_days(self.collapse_by_day)
        total_s = self.real_seconds_for_days(self.playable_days)
        return {
            "real_seconds_per_day": self.real_seconds_per_day,
            "sim_panic_day": sim_panic_day,
            "collapse_by_day": self.collapse_by_day,
            "collapse_warp": warp,                 # sim-days per player-day
            "sim_day_at_collapse": self.player_day_to_sim_day(
                self.collapse_by_day, sim_panic_day),
            "real_seconds_to_collapse": to_collapse_s,
            "real_minutes_to_collapse": to_collapse_s / 60.0,
            "real_seconds_total": total_s,
            "real_minutes_total": total_s / 60.0,
        }

    def summary(self, sim_panic_day: float | None = None) -> str:
        p = self.plan_session(sim_panic_day)
        hpd = self.real_seconds_per_day / 60.0
        line1 = (f"day length: {hpd:.0f} real min/in-game day "
                 f"({self.real_seconds_per_tick:.0f}s per sim tick)")
        if sim_panic_day:
            line2 = (f"collapse: sim day {sim_panic_day:.1f} -> player day "
                     f"{self.collapse_by_day:.1f} (warp x{p['collapse_warp']:.1f}), "
                     f"~{p['real_minutes_to_collapse']:.0f} min in")
        else:
            line2 = "collapse: scenario never tips (warp x1)"
        return f"{line1}\n{line2}"


def default_timescale() -> TimeScale:
    """PZ-default pacing: 1 real hour/day, collapse pinned to player day 2."""
    return TimeScale()


# ---------------------------------------------------------------------------
# Citizen schedule -> wall-clock playback
# ---------------------------------------------------------------------------
# Activities that count as downtime and run at the sleep-compression rate.
_DOWNTIME = {"sleep", "leisure"}


def block_real_seconds(activity: str, game_hours: float, ts: TimeScale) -> float:
    """Wall-clock seconds a schedule block occupies, fast-forwarding downtime."""
    secs = ts.real_seconds(game_hours)
    if activity in _DOWNTIME and ts.sleep_compression > 0:
        secs /= ts.sleep_compression
    return secs


def schedule_playback(schedule, ts: TimeScale) -> list[dict]:
    """Convert a citizen's day (in-game-hour blocks) into a wall-clock timeline.

    Returns one row per block with its real-time start/duration, so a game loop
    can drive the player's day directly. Downtime is compressed; active blocks
    (commute / work / errand) play at the base rate.
    """
    out = []
    t = 0.0
    for e in schedule:
        game_hours = e.end_hour - e.start_hour
        dur = block_real_seconds(e.activity, game_hours, ts)
        out.append({
            "activity": e.activity,
            "task": e.task,
            "location": e.location,
            "game_start_hour": e.start_hour,
            "game_hours": game_hours,
            "real_start_s": t,
            "real_seconds": dur,
        })
        t += dur
    return out

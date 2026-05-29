"""
Outcome metrics for Asphodel runs (Phase 4b consolidation).

Phase 3a and Phase 4a computed their scalar outcome metrics ad hoc, inline in
``experiments.py`` (``_tip_days`` / ``_summary``) and on ``RunResult``
(``panic_day`` / ``peak_infection_day`` / ``authority_alarm_day``).  This module
collects those *exact same* definitions in one place so:

* the scenario engine's ensemble/sweep runners can compute them uniformly,
* the existing experiments can call them without changing a single number,
* the set of "official" outcome metrics is documented in one spot.

Every function here is a pure function of a per-tick aggregate ``frame`` (the
``DataFrame`` produced by :func:`asphodel.runner.run_scenario`) plus the zone
count, so it works equally on a live ``RunResult`` and on a reloaded CSV.

The headline macro outcome metrics (the ones the brief names) are:

================================  =========================================
metric key                        meaning
================================  =========================================
``silent_phase_days``             day 10% of zones first cross panic
``day_50pct_panic``               day 50% of zones panic (the tipping point)
``day_90pct_panic``               day 90% of zones panic
``tip_sharpness_days``            day_90pct_panic - silent_phase_days
``peak_infection_day``            day of peak total infectious (I_a + I_s)
``peak_infection_height``         peak total infectious (people)
``attack_rate``                   ever-infected fraction = (N - S_final) / N
``total_dead``                    cumulative deaths at the horizon
``infra_collapse_day``            day a majority of zones lose water
``authority_alarm_day``           day the official signal first exceeds 0.5
================================  =========================================
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# primitive crossings (the shared definitions)
# --------------------------------------------------------------------------- #
def _first_day_at_or_above(frame: pd.DataFrame, column: str,
                           level: float) -> Optional[float]:
    """First ``day`` at which ``column`` first reaches ``level`` (else None).

    This is the single crossing primitive every "day-of" metric is built on,
    matching the inline definitions used in Phase 3a (``panic_day`` in
    ``runner.py`` and ``day_at`` in ``experiments.py``)."""
    crossed = frame[column] >= level
    if not crossed.any():
        return None
    return float(frame.loc[crossed, "day"].iloc[0])


def panic_day(frame: pd.DataFrame, n_zones: int,
              fraction: float = 0.5) -> Optional[float]:
    """Day the fraction of zones in panic first crosses ``fraction``.

    Identical to ``RunResult.panic_day`` / ``experiments._tip_days``: the
    threshold is ``fraction * n_zones`` applied to the ``n_panic`` column."""
    return _first_day_at_or_above(frame, "n_panic", fraction * n_zones)


def peak_infection_day(frame: pd.DataFrame) -> float:
    """Day of peak total infectious (``I_asymp + I_symp``).

    Matches ``RunResult.peak_infection_day``: argmax over the infectious sum."""
    infectious = (frame["I_asymp"] + frame["I_symp"]).to_numpy()
    return float(frame["day"].iloc[int(infectious.argmax())])


def peak_infection_height(frame: pd.DataFrame) -> float:
    """Peak total infectious (people) over the run."""
    return float((frame["I_asymp"] + frame["I_symp"]).max())


def authority_alarm_day(frame: pd.DataFrame,
                        threshold: float = 0.5) -> Optional[float]:
    """Day the official signal first crosses ``threshold`` (default 0.5).

    Matches ``RunResult.authority_alarm_day``."""
    return _first_day_at_or_above(frame, "official_signal", threshold)


def infra_collapse_day(frame: pd.DataFrame, n_zones: int,
                       fraction: float = 0.5) -> Optional[float]:
    """Day a ``fraction`` (default majority) of zones have lost water.

    The Phase 3a findings characterise infrastructure collapse by the
    ``n_water_fail`` count; this turns that into a single 'day of collapse'
    using the same majority-of-zones convention as the panic-day metric.
    Returns None if water never fails in that many zones (e.g. infra disabled)."""
    if "n_water_fail" not in frame.columns:
        return None
    return _first_day_at_or_above(frame, "n_water_fail", fraction * n_zones)


def peak_water_fail(frame: pd.DataFrame) -> int:
    """Peak number of zones that have lost water (Phase 3a ``_summary`` key)."""
    if "n_water_fail" not in frame.columns:
        return 0
    return int(frame["n_water_fail"].max())


# --------------------------------------------------------------------------- #
# population / epidemic totals
# --------------------------------------------------------------------------- #
_COMPARTMENTS = ("S", "E", "I_asymp", "I_symp", "R", "D")


def total_population(frame: pd.DataFrame) -> float:
    """Total living+dead population (conserved each tick) from the last row.

    The macro model conserves mass exactly, so summing the compartments on any
    row gives the population; we use the final row."""
    last = frame.iloc[-1]
    return float(sum(last[c] for c in _COMPARTMENTS))


def attack_rate(frame: pd.DataFrame) -> float:
    """Ever-infected fraction = (N - S_final) / N (everyone who left S)."""
    total = total_population(frame)
    if total <= 0:
        return 0.0
    s_final = float(frame["S"].iloc[-1])
    return (total - s_final) / total


def total_dead(frame: pd.DataFrame) -> float:
    """Cumulative deaths at the horizon."""
    return float(frame["D"].iloc[-1])


# --------------------------------------------------------------------------- #
# the consolidated metric dict
# --------------------------------------------------------------------------- #
def macro_metrics(frame: pd.DataFrame, n_zones: int) -> dict:
    """All headline macro outcome metrics for one run, as a flat scalar dict.

    A ``None`` value means the event never occurred within the horizon (e.g. the
    authority never alarmed, or fewer than a majority of zones lost water)."""
    t10 = panic_day(frame, n_zones, 0.1)
    t50 = panic_day(frame, n_zones, 0.5)
    t90 = panic_day(frame, n_zones, 0.9)
    sharpness = (t90 - t10) if (t10 is not None and t90 is not None) else None
    return {
        "silent_phase_days": t10,
        "day_50pct_panic": t50,
        "day_90pct_panic": t90,
        "tip_sharpness_days": sharpness,
        "peak_infection_day": peak_infection_day(frame),
        "peak_infection_height": peak_infection_height(frame),
        "attack_rate": attack_rate(frame),
        "total_dead": total_dead(frame),
        "infra_collapse_day": infra_collapse_day(frame, n_zones),
        "authority_alarm_day": authority_alarm_day(frame),
    }


def macro_metrics_from_result(result) -> dict:
    """Convenience wrapper: macro metrics from a :class:`RunResult`."""
    return macro_metrics(result.frame, result.graph.n_zones)


# --------------------------------------------------------------------------- #
# ensemble distribution summaries
# --------------------------------------------------------------------------- #
DEFAULT_PERCENTILES = (5, 25, 50, 75, 95)


def summarize_distribution(values: Sequence[Optional[float]],
                           percentiles: Sequence[float] = DEFAULT_PERCENTILES
                           ) -> dict:
    """Mean / std / median / percentile bands for one metric across seeds.

    ``None`` values (events that never occurred in a given run) are dropped from
    the numeric summary and counted separately as ``n_missing`` so a metric that
    only fires in some runs is reported honestly rather than silently biased."""
    arr = np.array([v for v in values if v is not None], dtype=float)
    n_missing = sum(1 for v in values if v is None)
    if arr.size == 0:
        out = {"n": 0, "n_missing": n_missing, "mean": None,
               "std": None, "median": None}
        for p in percentiles:
            out[f"p{int(p)}"] = None
        return out
    out = {
        "n": int(arr.size),
        "n_missing": int(n_missing),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        "median": float(np.median(arr)),
    }
    for p in percentiles:
        out[f"p{int(p)}"] = float(np.percentile(arr, p))
    return out


def summarize_metrics(per_run_metrics: Sequence[dict],
                      percentiles: Sequence[float] = DEFAULT_PERCENTILES
                      ) -> dict:
    """Turn a list of per-run metric dicts into a {metric: distribution} dict."""
    if not per_run_metrics:
        return {}
    keys = list(per_run_metrics[0].keys())
    return {
        key: summarize_distribution([m.get(key) for m in per_run_metrics],
                                    percentiles)
        for key in keys
    }

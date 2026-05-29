"""
The scenario engine (Phase 4b): run one or many :class:`Scenario` objects and
get back structured results and distribution summaries.

Three entry points, matching the brief:

* :func:`run_single`  -- one scenario -> a full per-tick :class:`RunResult`
                         (reuses the existing macro engine + CSV/history output).
* :func:`run_ensemble`-- one scenario x many seeds -> per-run outcome metrics
                         and their mean/median/percentile-band distribution
                         summaries (the metric set defined in ``metrics.py``).
* :func:`run_sweep`   -- a grid/list of scenarios x seeds -> a tidy results
                         table (one row per run: scenario axes + outcome
                         metrics), exportable to CSV/parquet for offline work.

Everything is deterministic and reproducible: a run is fully specified by its
scenario + seed, an ensemble by its scenario + seed list, and a sweep by its
base scenario + axis spec + seed list.  :func:`run_sweep` can dump the full
resolved sweep spec alongside the results so any table can be regenerated.

Parallel-by-seed is optional (``n_jobs > 1`` uses ``multiprocessing``); the
default is serial, which keeps small sweeps simple and bit-reproducible.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, asdict, replace
from typing import Any, Callable, Iterable, Optional, Sequence

import pandas as pd

from .runner import run_scenario, RunResult
from .scenario import Scenario, get_location_profile, LocationProfile
from . import metrics


# --------------------------------------------------------------------------- #
# single run
# --------------------------------------------------------------------------- #
def run_single(scenario: Scenario, record_belief: bool = True) -> RunResult:
    """Run one scenario through the macro engine and return its RunResult.

    The scenario is lowered to the frozen-engine :class:`ScenarioConfig` via
    :meth:`Scenario.to_scenario_config`; the macro core is untouched."""
    return run_scenario(scenario.to_scenario_config(), record_belief=record_belief)


# --------------------------------------------------------------------------- #
# dotted-path axis setter (so sweeps can vary any nested field by name)
# --------------------------------------------------------------------------- #
def set_path(scenario: Scenario, dotted: str, value: Any) -> Scenario:
    """Return a deep copy of ``scenario`` with the dotted-path field set.

    ``dotted`` walks attributes, e.g. ``"model_params.belief.w_social"``,
    ``"genome.incubation_period"``, ``"start_date"``.  As a convenience,
    setting ``"location_profile"`` to a *string* resolves it to the named
    starter profile (so a sweep can list location names directly)."""
    sc = copy.deepcopy(scenario)
    parts = dotted.split(".")
    if dotted == "location_profile" and isinstance(value, str):
        sc.location_profile = get_location_profile(value)
        return sc
    target = sc
    for p in parts[:-1]:
        target = getattr(target, p)
    leaf = parts[-1]
    if not hasattr(target, leaf):
        raise AttributeError(f"scenario has no field path {dotted!r} (no {leaf!r})")
    setattr(target, leaf, value)
    return sc


def _axis_label(dotted: str) -> str:
    """Short column name for a sweep axis (last dotted component)."""
    return dotted.split(".")[-1]


def _axis_value_repr(value: Any) -> Any:
    """A tidy-table-friendly representation of an axis value."""
    if isinstance(value, LocationProfile):
        return value.name
    return value


# --------------------------------------------------------------------------- #
# ensemble (one scenario x many seeds)
# --------------------------------------------------------------------------- #
@dataclass
class EnsembleResult:
    """One scenario run across many seeds."""

    scenario: Scenario
    seeds: list[int]
    per_run_metrics: list[dict]          # one metric dict per seed
    summary: dict                        # {metric: distribution-summary dict}
    representative: Optional[RunResult]  # first seed's RunResult (for plotting)

    def metrics_frame(self) -> pd.DataFrame:
        """Per-run metrics as a DataFrame (one row per seed)."""
        rows = []
        for seed, m in zip(self.seeds, self.per_run_metrics):
            row = {"seed": seed}
            row.update(m)
            rows.append(row)
        return pd.DataFrame(rows)


def _metrics_for_seed(scenario: Scenario, seed: int,
                      keep_result: bool) -> tuple[dict, Optional[RunResult]]:
    sc = replace_seed(scenario, seed)
    res = run_single(sc, record_belief=False)
    m = metrics.macro_metrics_from_result(res)
    return m, (res if keep_result else None)


def replace_seed(scenario: Scenario, seed: int) -> Scenario:
    """A shallow-safe copy of the scenario with a new seed."""
    sc = copy.deepcopy(scenario)
    sc.seed = seed
    return sc


# Top-level worker so it is picklable for multiprocessing.
def _seed_worker(packed):
    scenario, seed = packed
    sc = replace_seed(scenario, seed)
    res = run_single(sc, record_belief=False)
    return metrics.macro_metrics_from_result(res)


def run_ensemble(scenario: Scenario, seeds: Sequence[int],
                 n_jobs: int = 1,
                 percentiles: Sequence[float] = metrics.DEFAULT_PERCENTILES
                 ) -> EnsembleResult:
    """Run ``scenario`` once per seed and summarise the outcome metrics.

    With ``n_jobs == 1`` runs serially (and keeps the first seed's full
    ``RunResult`` for plotting).  With ``n_jobs > 1`` distributes seeds across
    processes (no representative result is kept, to avoid shipping frames back).
    """
    seeds = list(seeds)
    if n_jobs and n_jobs > 1 and len(seeds) > 1:
        import multiprocessing as mp
        with mp.Pool(processes=n_jobs) as pool:
            per_run = pool.map(_seed_worker, [(scenario, s) for s in seeds])
        representative = None
    else:
        per_run = []
        representative = None
        for i, s in enumerate(seeds):
            m, res = _metrics_for_seed(scenario, s, keep_result=(i == 0))
            per_run.append(m)
            if i == 0:
                representative = res
    summary = metrics.summarize_metrics(per_run, percentiles)
    return EnsembleResult(scenario=scenario, seeds=seeds,
                          per_run_metrics=per_run, summary=summary,
                          representative=representative)


# --------------------------------------------------------------------------- #
# sweep (grid/list of scenarios x seeds -> tidy table)
# --------------------------------------------------------------------------- #
def build_sweep(base: Scenario, axes: dict[str, Sequence[Any]]
                ) -> list[tuple[dict, Scenario]]:
    """Expand ``base`` over the cartesian product of ``axes`` into scenarios.

    ``axes`` maps a dotted field path to the list of values it should take, e.g.

        {"genome.incubation_period": [2, 5, 8, 12],
         "model_params.belief.w_social": [0.6, 0.8, 1.0]}

    Returns ``[(axis_values, scenario), ...]`` where ``axis_values`` is a dict
    of ``{short_axis_name: value}`` for the tidy table.  The product is taken in
    a deterministic (sorted-key, list-order) sequence."""
    import itertools
    if not axes:
        return [({}, copy.deepcopy(base))]
    keys = list(axes.keys())
    value_lists = [list(axes[k]) for k in keys]
    out = []
    for combo in itertools.product(*value_lists):
        sc = copy.deepcopy(base)
        axis_values = {}
        for dotted, value in zip(keys, combo):
            sc = set_path(sc, dotted, value)
            axis_values[_axis_label(dotted)] = _axis_value_repr(value)
        out.append((axis_values, sc))
    return out


def run_sweep(scenarios: Iterable[tuple[dict, Scenario]],
              seeds: Sequence[int], n_jobs: int = 1,
              progress: bool = False) -> pd.DataFrame:
    """Run a list of ``(axis_values, scenario)`` pairs across seeds.

    Returns a tidy DataFrame: one row per (scenario, seed) with columns
    ``scenario`` (name) + the axis columns + ``seed`` + every outcome metric.
    """
    scenarios = list(scenarios)
    seeds = list(seeds)

    # Flatten to (axis_values, scenario, seed) jobs so parallelism spans both.
    jobs = []
    for axis_values, sc in scenarios:
        for s in seeds:
            jobs.append((axis_values, sc, s))

    def _row(job):
        axis_values, sc, seed = job
        sc_seeded = replace_seed(sc, seed)
        res = run_single(sc_seeded, record_belief=False)
        m = metrics.macro_metrics_from_result(res)
        row = {"scenario": sc.metadata.name}
        row.update(axis_values)
        row["seed"] = seed
        row.update(m)
        return row

    if n_jobs and n_jobs > 1 and len(jobs) > 1:
        import multiprocessing as mp
        with mp.Pool(processes=n_jobs) as pool:
            rows = pool.map(_sweep_worker, jobs)
    else:
        rows = []
        for i, job in enumerate(jobs):
            rows.append(_row(job))
            if progress:
                print(f"  sweep {i + 1}/{len(jobs)}", end="\r")
        if progress:
            print()
    return pd.DataFrame(rows)


# Top-level worker for sweep parallelism (picklable).
def _sweep_worker(job):
    axis_values, sc, seed = job
    sc_seeded = replace_seed(sc, seed)
    res = run_single(sc_seeded, record_belief=False)
    m = metrics.macro_metrics_from_result(res)
    row = {"scenario": sc.metadata.name}
    row.update(axis_values)
    row["seed"] = seed
    row.update(m)
    return row


# --------------------------------------------------------------------------- #
# export helpers
# --------------------------------------------------------------------------- #
def export_table(df: pd.DataFrame, path: str) -> str:
    """Write a tidy results table to CSV or parquet (by extension).

    Parquet falls back to CSV if no parquet engine (pyarrow/fastparquet) is
    installed, so the engine never hard-depends on the optional package."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if path.endswith(".parquet"):
        try:
            df.to_parquet(path, index=False)
            return path
        except Exception:
            alt = path[: -len(".parquet")] + ".csv"
            df.to_csv(alt, index=False)
            return alt
    df.to_csv(path, index=False)
    return path


def dump_sweep_spec(base: Scenario, axes: dict[str, Sequence[Any]],
                    seeds: Sequence[int], path: str) -> str:
    """Log everything needed to reproduce a sweep (base scenario + axes + seeds).

    The base scenario is serialised exactly as its YAML form; axes/seeds are
    recorded verbatim.  Re-running ``build_sweep(base, axes)`` + ``run_sweep``
    with these seeds regenerates the table."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    spec = {
        "base_scenario": base.to_dict(),
        "axes": {k: list(v) for k, v in axes.items()},
        "seeds": list(seeds),
    }
    with open(path, "w") as f:
        json.dump(spec, f, indent=2, default=str)
    return path

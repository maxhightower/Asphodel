"""Deterministic ``World`` construction from a committed city bundle (M1).

``START_WORLD`` names a *bundle* (a real city baked under ``godot/bundles/<city>``:
``meta.json`` + ``zones.json`` + ``roads.json``), a ``seed``, optional micro
params and live-bubble budget. This module turns that into the exact
:class:`~asphodel.config.ScenarioConfig` the offline pipeline used to bake the
city (``asphodel.osm_city.pipeline._rebuild_sim_products``) so the *live* world
rides the same real-road mobility graph and real populations -- then wraps it in
an authoritative :class:`~asphodel.orchestrator.World`.

Crucially the live world is now the authority: it is not required to reproduce
the baked ``timeline.json`` (that was a macro-only preview); it only has to be
deterministic from ``(bundle, seed, micro, budget)``, which it is.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace

from ..config import (
    ScenarioConfig, PathogenGenome, ModelParams, GraphParams, MicroParams,
    HandoffParams,
)
from ..orchestrator import World
from ..osm_city import mobility as _mob


# Where committed bundles live, relative to the repo root (…/asphodel/bridge/..).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUNDLES_DIR = os.path.join(_REPO_ROOT, "godot", "bundles")


def resolve_bundle_dir(bundle: str) -> str:
    """Resolve a bundle reference to a directory.

    Accepts an explicit path (absolute, or relative to cwd) containing the bundle
    JSONs, or a bare city name resolved under ``godot/bundles/<name>``.
    """
    if os.path.isdir(bundle) and os.path.exists(os.path.join(bundle, "meta.json")):
        return os.path.abspath(bundle)
    candidate = os.path.join(_BUNDLES_DIR, bundle)
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "meta.json")):
        return candidate
    raise FileNotFoundError(f"no bundle found for {bundle!r} "
                            f"(looked at {bundle!r} and {candidate!r})")


def config_from_bundle(bundle: str, seed: int | None = None) -> ScenarioConfig:
    """Rebuild the exact ScenarioConfig a bundle was baked from.

    Mirrors ``asphodel.osm_city.pipeline._rebuild_sim_products``: zones sorted by
    id, per-zone real populations, genome from meta, and the real-road-derived
    weighted mobility graph. ``seed`` overrides the baked seed when given (so the
    same city can be replayed under different seeds).
    """
    bundle_dir = resolve_bundle_dir(bundle)
    with open(os.path.join(bundle_dir, "meta.json")) as f:
        meta = json.load(f)
    with open(os.path.join(bundle_dir, "zones.json")) as f:
        zones = json.load(f)
    with open(os.path.join(bundle_dir, "roads.json")) as f:
        roads = json.load(f)

    zones = sorted(zones, key=lambda z: z["id"])
    rows = int(meta["grid"]["rows"])
    cols = int(meta["grid"]["cols"])
    populations = [z["population"] for z in zones]
    local_floor = float(meta.get("mobility", {}).get("local_floor", 0.1))

    mobility_edges = _mob.derive_zone_mobility(
        zones, roads.get("polylines", []), rows, cols, local_floor=local_floor)

    genome = PathogenGenome(**meta["genome"])
    cfg = ScenarioConfig(
        name=meta.get("name", os.path.basename(bundle_dir)),
        genome=genome,
        model=ModelParams(graph=GraphParams(
            grid_rows=rows, grid_cols=cols, population=populations,
            mobility_edges=mobility_edges if mobility_edges else None,
        )),
        dt=float(meta["dt"]), n_days=float(meta["n_days"]),
        seed=int(meta["seed"]) if seed is None else int(seed),
        seed_zone=int(meta["seed_zone"]),
    )
    return cfg


def world_from_bundle(bundle: str, *, seed: int | None = None,
                      micro_params: MicroParams | None = None,
                      handoff: HandoffParams | None = None,
                      max_live_zones: int | None = None,
                      max_live_agents: int | None = None) -> World:
    """Construct an authoritative World for a bundle + seed + budget."""
    cfg = config_from_bundle(bundle, seed=seed)
    return World(
        cfg,
        micro_params=micro_params or MicroParams(area_size=100.0,
                                                 infection_radius=2.0,
                                                 mixing_step_frac=0.12),
        handoff=handoff,
        max_live_zones=max_live_zones,
        max_live_agents=max_live_agents,
        seed=int(cfg.seed),
    )


def bundle_summary(bundle: str) -> dict:
    """Small identity block for a bundle (echoed by START_WORLD)."""
    bundle_dir = resolve_bundle_dir(bundle)
    with open(os.path.join(bundle_dir, "meta.json")) as f:
        meta = json.load(f)
    return {
        "name": meta.get("name"),
        "grid": meta.get("grid"),
        "n_zones": int(meta["grid"]["rows"]) * int(meta["grid"]["cols"]),
        "dt": float(meta["dt"]),
        "seed_zone": int(meta["seed_zone"]),
    }

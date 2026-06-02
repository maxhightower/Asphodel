"""Bake a population of spawnable citizens into a city bundle.

Loads the citizen-spawn configs (CityProfile archetypes + the shared catalog),
spawns N citizens per profile, attaches each occupation's signature scenario,
assigns a generated display name, and flattens to render-ready dicts that Godot
reads from the bundle's citizens.json. No game-engine or network dependency.
"""
from __future__ import annotations

import json
import os

from ..citizen import CityProfile, CitizenSpawnCatalog, spawn_population
from ..signatures import default_signatures

DEFAULT_PROFILES = ["generic", "capital", "harbor", "university"]

_FIRST = ["Maria", "James", "Aisha", "Wei", "Carlos", "Nadia", "Tom", "Priya",
          "Diego", "Sara", "Omar", "Grace", "Leo", "Hana", "Ruth", "Andre"]
_LAST = ["Reyes", "Okafor", "Nguyen", "Patel", "Johnson", "Khan", "Garcia",
         "Mensah", "Silva", "Brooks", "Costa", "Ahmed", "Rivera", "Park",
         "Cohen", "Diallo"]


def _name_for(citizen_id: int, profile: str) -> str:
    """Deterministic display name (Python's hash() is salted, so derive our own)."""
    base = citizen_id * 1000 + sum(ord(ch) for ch in profile)
    return f"{_FIRST[base % len(_FIRST)]} {_LAST[(base // len(_FIRST)) % len(_LAST)]}"


def _flatten(profile_name: str, citizen, signatures: dict) -> dict:
    sig = signatures.get(citizen.occupation)
    return {
        "profile": profile_name,
        "name": _name_for(citizen.citizen_id, profile_name),
        "age": int(citizen.age),
        "occupation": citizen.occupation,
        "shift": citizen.shift,
        "home_district": citizen.home_district,
        "work_district": citizen.work_district or "",
        "spawn_hour": round(float(citizen.spawn_hour), 2),
        "current_activity": citizen.current_activity,
        "current_location": citizen.current_location,
        "inventory": dict(citizen.inventory),
        "signature_title": sig.name if sig else "",
        "signature_location": sig.location if sig else "",
        "signature_situation": sig.situation if sig else "",
        "signature_dilemma": sig.dilemma if sig else "",
    }


def build_citizen_population(cities_dir: str, profiles=None,
                             n_per_profile: int = 15, seed: int = 0) -> list[dict]:
    """Spawn n_per_profile citizens for each profile archetype; return flat dicts."""
    profiles = profiles or DEFAULT_PROFILES
    catalog = CitizenSpawnCatalog.from_yaml(os.path.join(cities_dir, "_catalog.yaml"))
    signatures = default_signatures()
    out: list[dict] = []
    for i, profile_name in enumerate(profiles):
        city = CityProfile.from_yaml(os.path.join(cities_dir, f"{profile_name}.yaml"))
        for citizen in spawn_population(city, catalog, n=n_per_profile, seed=seed + i):
            out.append(_flatten(profile_name, citizen, signatures))
    return out


def write_citizens(bundle_dir: str, cities_dir: str = "cities",
                   n_per_profile: int = 15, seed: int = 0) -> int:
    """Write <bundle_dir>/citizens.json; return the number of citizens written."""
    pop = build_citizen_population(cities_dir, n_per_profile=n_per_profile, seed=seed)
    os.makedirs(bundle_dir, exist_ok=True)
    path = os.path.join(bundle_dir, "citizens.json")
    with open(path, "w") as f:
        json.dump(pop, f, indent=2, sort_keys=True)
        f.write("\n")
    return len(pop)

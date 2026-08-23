"""Load a committed city bundle's real citizens into simulation-ready form (BW1).

The certified vertical demo built citizens in-process; a *real* client selects a
city and must get **that city's** bundled `citizens.json`. This module owns that
transformation (Python owns simulation-ready citizen construction — never Godot):

    bundle/ (meta,zones,roads,mobility,citizens.json)
        -> load_bundle_population(bundle_dir)
        -> list[CitizenProfile]  (citizen_id, home/work zone, reconstructed
                                  schedule, real bundle coordinates)
        -> World.set_citizens(...)

Two reconstructions are needed because the bake does not serialise them:

* **zone** from real bundle coordinates (`home_xy`) via the same spatial frame the
  simulation uses — the nearest zone centre (a regular grid, so this is the cell
  containing the point; ties -> lowest zone id; out-of-bounds clamps to the
  nearest edge cell). Deterministic.
* **schedule** deterministically from `shift`, mirroring `citizen._build_schedule`'s
  day/night/none structure, with the only jitter (wake time) seeded by the stable
  citizen id — so the same citizen in the same bundle always gets the identical
  schedule.
"""

from __future__ import annotations

import json
import os

import numpy as np

from .citizen import CitizenProfile, ScheduleEntry, SpawnParams


# --------------------------------------------------------------------------- #
# coordinate -> zone
# --------------------------------------------------------------------------- #
def zone_centers(zones: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Return (ids, centers) sorted by zone id — the simulation's zone frame."""
    zs = sorted(zones, key=lambda z: int(z["id"]))
    ids = np.array([int(z["id"]) for z in zs], dtype=np.int64)
    centers = np.array([[float(z["center_xy"][0]), float(z["center_xy"][1])]
                        for z in zs], dtype=float)
    return ids, centers


def zone_of_xy(x: float, z: float, ids: np.ndarray, centers: np.ndarray) -> int:
    """Map a coordinate to a zone index by nearest zone centre.

    On a regular grid this is the cell containing the point; a point on a cell
    boundary or outside the map resolves deterministically to the nearest centre,
    ties broken by lowest zone id (``argmin`` returns the first minimum, and
    ``centers`` is ordered by ascending id).
    """
    d2 = (centers[:, 0] - float(x)) ** 2 + (centers[:, 1] - float(z)) ** 2
    return int(ids[int(np.argmin(d2))])


# --------------------------------------------------------------------------- #
# schedule reconstruction (deterministic, seeded by citizen id)
# --------------------------------------------------------------------------- #
def reconstruct_schedule(shift: str, citizen_id: int,
                         home_n: str = "home", work_n: str | None = "work",
                         errand_loc: str = "errand",
                         p: SpawnParams | None = None) -> list[ScheduleEntry]:
    """A deterministic daily schedule from ``shift``, seeded by ``citizen_id``.

    Mirrors ``asphodel.citizen._build_schedule``'s three cases (none/night/day)
    using the same ``SpawnParams`` timing. Deterministic: the only random element
    (wake jitter) is drawn from ``default_rng([citizen_id])``, so the same citizen
    always gets the same schedule.
    """
    p = p or SpawnParams()
    rng = np.random.default_rng([int(citizen_id)])
    entries: list[ScheduleEntry] = []
    work_present = work_n is not None and str(shift).lower() != "none"

    if not work_present:
        wake = 7.5 + float(rng.uniform(-1.0, 1.5))
        entries += [
            ScheduleEntry(0.0, wake, "sleep", home_n),
            ScheduleEntry(wake, 10.5, "leisure", home_n, "morning at home"),
            ScheduleEntry(10.5, 12.0, "errand", errand_loc, "run errands"),
            ScheduleEntry(12.0, 18.0, "leisure", home_n, "afternoon at home"),
            ScheduleEntry(18.0, 22.0, "leisure", home_n, "evening"),
            ScheduleEntry(22.0, 24.0, "sleep", home_n),
        ]
        return _normalise(entries)

    commute = p.commute_hours
    if str(shift).lower() == "night":
        ws, we = p.night_start, p.night_end
        wake = ws - p.wake_before_work
        entries += [
            ScheduleEntry(4.0, 12.0, "sleep", home_n),
            ScheduleEntry(12.0, wake, "leisure", home_n, "day off-shift"),
            ScheduleEntry(wake, ws - commute, "errand", errand_loc, "pre-shift errands"),
            ScheduleEntry(ws - commute, ws, "commute", work_n),
            ScheduleEntry(ws, we - commute, "work", work_n, "on shift"),
            ScheduleEntry(we - commute, we, "commute", home_n),
        ]
    else:  # day shift
        ws, we = p.day_start, p.day_end
        wake = ws - p.wake_before_work
        entries += [
            ScheduleEntry(0.0, wake, "sleep", home_n),
            ScheduleEntry(wake, ws - commute, "leisure", home_n, "morning routine"),
            ScheduleEntry(ws - commute, ws, "commute", work_n),
            ScheduleEntry(ws, we, "work", work_n, "on shift"),
            ScheduleEntry(we, we + commute, "commute", home_n),
            ScheduleEntry(we + commute, we + commute + 1.5, "errand", errand_loc, "errands"),
            ScheduleEntry(we + commute + 1.5, 22.5, "leisure", home_n, "evening"),
            ScheduleEntry(22.5, 24.0, "sleep", home_n),
        ]
    return _normalise(entries)


def _normalise(entries: list[ScheduleEntry]) -> list[ScheduleEntry]:
    out = [e for e in entries if e.end_hour > e.start_hour]
    out.sort(key=lambda e: e.start_hour)
    return out


# --------------------------------------------------------------------------- #
# the loader
# --------------------------------------------------------------------------- #
def _age_band(age: int) -> str:
    if age < 18:
        return "youth"
    if age < 65:
        return "adult"
    return "senior"


def load_bundle_population(bundle_dir: str) -> list[CitizenProfile]:
    """Load ``citizens.json`` from a bundle into simulation-ready CitizenProfiles.

    Citizen ids are the (stable) file order, so they are unique by construction.
    Home/work zones come from the real bundle coordinates; schedules are
    reconstructed deterministically.
    """
    with open(os.path.join(bundle_dir, "zones.json")) as f:
        zones = json.load(f)
    with open(os.path.join(bundle_dir, "meta.json")) as f:
        meta = json.load(f)
    cit_path = os.path.join(bundle_dir, "citizens.json")
    if not os.path.exists(cit_path):
        raise FileNotFoundError(f"bundle has no citizens.json: {bundle_dir}")
    with open(cit_path) as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("citizens.json is not a list")

    ids, centers = zone_centers(zones)
    city = meta.get("name", os.path.basename(bundle_dir))

    out: list[CitizenProfile] = []
    for cid, c in enumerate(raw):
        home_xy = c.get("home_xy")
        work_xy = c.get("work_xy")
        home_zone = (zone_of_xy(home_xy[0], home_xy[1], ids, centers)
                     if home_xy else None)
        work_zone = (zone_of_xy(work_xy[0], work_xy[1], ids, centers)
                     if work_xy else None)
        shift = str(c.get("shift", "day"))
        age = int(c.get("age", 30))
        schedule = reconstruct_schedule(
            shift, cid,
            home_n=c.get("home_district") or "home",
            work_n=(c.get("work_district") or "work") if work_zone is not None else None,
            errand_loc="errand")
        out.append(CitizenProfile(
            citizen_id=cid, city=city, age=age, age_band=_age_band(age),
            occupation=str(c.get("occupation", "resident")),
            shift=shift,
            home_district=str(c.get("home_district", "")),
            work_district=c.get("work_district"),
            home_zone=home_zone, work_zone=work_zone,
            schedule=schedule, inventory=dict(c.get("inventory", {})),
            spawn_hour=float(c.get("spawn_hour", 8.0)),
            current_location=str(c.get("current_location", "")),
            current_activity=str(c.get("current_activity", "idle")),
            current_task=str(c.get("current_task", "")),
            home_xy=tuple(home_xy) if home_xy else None,
            work_xy=tuple(work_xy) if work_xy else None,
        ))
    return out

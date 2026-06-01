"""
Citizen spawn configs: the *possibility space* a player can be dropped into.

Part of the game loop is being randomly spawned as an ordinary citizen and
having to live a normal day before the world ends.  This module owns the data
that defines who a player can spawn as -- occupation, age, where they live, where
they work, the shape of their workday (job tasks), and what is in their pockets
-- and the deterministic sampler that draws one concrete citizen from it.

Design, matching the rest of Asphodel
-------------------------------------
* **Data, not code.**  The possibility space is a ``CitizenSpawnCatalog``
  (age bands, occupations, item kinds, timing knobs) plus a ``CityProfile`` (the
  city's district map and its biases).  Both round-trip to YAML, like
  ``ScenarioConfig``.
* **Agnostic, slightly city-determined.**  The *catalog* is shared and
  city-agnostic: in principle a citizen of any city can hold any age-eligible
  occupation and carry any item.  A *city* only ever **biases** that space --
  through age / occupation weight multipliers and, crucially, through which
  districts (and therefore which workplaces) actually exist on its map.  A harbor
  city has a port, so it spawns more dock workers; a university town is thick
  with students; nothing is hard-removed, only reweighted.
* **Deterministic from (config + seed).**  ``spawn_citizen(city, catalog,
  seed=...)`` is a pure function of its inputs, and ``spawn_population`` derives
  independent per-citizen RNGs from one base seed via ``SeedSequence`` so a whole
  crowd is reproducible.
* **Ties into the existing tiers.**  Districts carry an optional macro grid
  ``zone`` index, so a spawned citizen's home/work resolve to zones in the
  ``ZoneGraph`` -- and a spawned crowd can seed the micro ``AgentZone``.

The compartment / epidemic state is deliberately *not* set here: a fresh citizen
spawns susceptible, and the epidemic tiers (macro / micro) own disease state.
This module is purely about *who you are and what your day looks like* at the
moment the simulation hands you a body.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import yaml


# ===========================================================================
# The possibility space (data)
# ===========================================================================
@dataclass
class AgeBand:
    """A weighted age bracket.  Age is sampled uniformly within [min, max]."""

    name: str
    min_age: int
    max_age: int
    weight: float = 1.0          # base prevalence (before any city multiplier)


# Workplace category keys.  An occupation names the *kind* of place it works in;
# a city's districts advertise which kinds they host.  "" / "home" mean the day
# is not anchored to an external workplace (retirees, the unemployed, children).
HOME = "home"


@dataclass
class Occupation:
    """One thing a citizen can be, expressed as data.

    ``workplace`` is a category key matched against a district's ``workplaces``
    list; if no district in the city hosts it, the occupation is simply not
    offered there (the city-determined part).  ``tasks`` is the ordered spine of
    the workday -- the sampler spreads them across the work block to build the
    citizen's schedule.  ``inventory`` is what the job hands you to start with.
    """

    name: str
    min_age: int = 18
    max_age: int = 65
    base_weight: float = 1.0
    workplace: str = HOME              # category key, or HOME / "" for none
    shift: str = "day"                 # "day" | "night" | "none"
    tasks: list[str] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=dict)


@dataclass
class District:
    """A place on the city's map.

    ``residential_weight`` is the likelihood a citizen *lives* here;
    ``workplaces`` is the set of occupation categories that can be *worked* here.
    ``zone`` optionally pins the district onto the macro ``ZoneGraph`` grid so
    spawned citizens resolve to simulation zones.
    """

    name: str
    kind: str = "residential"          # residential / commercial / industrial /
    #                                    medical / civic / education / transit
    residential_weight: float = 1.0    # 0 => nobody lives here (pure workplace)
    workplaces: list[str] = field(default_factory=list)
    zone: Optional[int] = None         # macro grid zone index (None => unpinned)


@dataclass
class ScheduleEntry:
    """One block of a citizen's day.  Hours are in [0, 24); a block may end at
    >24 to denote wrap past midnight (night shifts), which the lookup handles."""

    start_hour: float
    end_hour: float
    activity: str                      # sleep / commute / work / errand / leisure
    location: str                      # district name
    task: str = ""                     # occupation task label, when activity=work


@dataclass
class SpawnParams:
    """Tunable knobs of the spawn process itself (timing, jitter, weighting)."""

    # Weight shaping: raw weights are raised to this power before sampling.
    # 1.0 = use weights as-is; <1 flattens toward uniform; >1 sharpens.
    weight_temperature: float = 1.0

    # Workday timing (hours).  Night shift wraps past midnight.
    day_start: float = 8.0
    day_end: float = 16.0
    night_start: float = 20.0
    night_end: float = 28.0            # 04:00 next day
    wake_before_work: float = 1.5      # wake this long before the commute
    commute_hours: float = 0.5         # door-to-door each way
    sleep_hours: float = 7.5           # nominal night's sleep for no-work days

    # Inventory rolling.
    common_item_prob: float = 0.6      # base chance to carry each common item
    inventory_jitter: float = 0.3      # +/- fractional wobble on job item counts

    # Spawn time-of-day.  None => sample an hour uniformly (you wake into the day
    # at a random point); set a value to spawn everyone at the same clock hour.
    spawn_hour: Optional[float] = None


@dataclass
class CitizenSpawnCatalog:
    """The agnostic, shared possibility space (every city draws from this)."""

    age_bands: list[AgeBand] = field(default_factory=list)
    occupations: list[Occupation] = field(default_factory=list)
    common_items: dict[str, int] = field(default_factory=dict)  # rolled for all
    params: SpawnParams = field(default_factory=SpawnParams)

    # -- YAML round-tripping -------------------------------------------------
    def to_yaml(self, path: str) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(asdict(self), f, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str) -> "CitizenSpawnCatalog":
        with open(path) as f:
            return cls.from_dict(yaml.safe_load(f))

    @classmethod
    def from_dict(cls, data: dict) -> "CitizenSpawnCatalog":
        data = dict(data)
        return cls(
            age_bands=[AgeBand(**b) for b in data.get("age_bands", [])],
            occupations=[Occupation(**o) for o in data.get("occupations", [])],
            common_items=dict(data.get("common_items", {})),
            params=SpawnParams(**(data.get("params") or {})),
        )


@dataclass
class CityProfile:
    """A city: its district map plus how it biases the agnostic catalog.

    The multipliers are the "slightly determined by the city" dial -- they scale
    the catalog's base weights but never invent or hard-delete possibilities.
    Reachability of an occupation is governed instead by whether any district
    hosts its workplace category, which is itself just the city's map.
    """

    name: str = "generic"
    population: Optional[int] = None
    districts: list[District] = field(default_factory=list)
    age_weight_multipliers: dict[str, float] = field(default_factory=dict)
    occupation_weight_multipliers: dict[str, float] = field(default_factory=dict)
    inventory_multiplier: float = 1.0   # scales job starting-inventory counts

    # -- convenience ---------------------------------------------------------
    def workplaces_available(self) -> set[str]:
        wp: set[str] = {HOME, ""}
        for d in self.districts:
            wp.update(d.workplaces)
        return wp

    def districts_of_kind(self, kind: str) -> list[District]:
        return [d for d in self.districts if d.kind == kind]

    def districts_hosting(self, workplace: str) -> list[District]:
        return [d for d in self.districts if workplace in d.workplaces]

    # -- YAML round-tripping -------------------------------------------------
    def to_yaml(self, path: str) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(asdict(self), f, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: str) -> "CityProfile":
        with open(path) as f:
            return cls.from_dict(yaml.safe_load(f))

    @classmethod
    def from_dict(cls, data: dict) -> "CityProfile":
        data = dict(data)
        districts = [District(**d) for d in data.pop("districts", [])]
        return cls(districts=districts, **data)


# ===========================================================================
# The spawn result (what the player IS)
# ===========================================================================
@dataclass
class CitizenProfile:
    """A single concrete citizen the player has been dropped into."""

    citizen_id: int
    city: str
    age: int
    age_band: str
    occupation: str
    shift: str

    home_district: str
    work_district: Optional[str]       # None => no external workplace
    home_zone: Optional[int]
    work_zone: Optional[int]

    schedule: list[ScheduleEntry]
    inventory: dict[str, int]

    # Where the clock found you at spawn.
    spawn_hour: float
    current_location: str
    current_activity: str
    current_task: str

    def summary(self) -> str:
        work = self.work_district or "—"
        line = (f"#{self.citizen_id:>4}  {self.occupation:<18} age {self.age:>2} "
                f"({self.age_band})  lives:{self.home_district:<14} "
                f"works:{work:<14}")
        clock = (f"  @ {self.spawn_hour:05.2f}h -> {self.current_activity}"
                 f"/{self.current_task or '-'} in {self.current_location}")
        items = ", ".join(f"{k}x{v}" for k, v in self.inventory.items())
        return f"{line}{clock}\n        carrying: {items}"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ===========================================================================
# The sampler
# ===========================================================================
def _weighted_choice(rng: np.random.Generator, items: list, weights: list[float],
                     temperature: float) -> object:
    """Pick one item with probability proportional to weight**(1/temperature-ish).

    We raise weights to ``temperature`` (temperature<1 flattens, >1 sharpens),
    then normalise.  All-zero weights fall back to uniform.
    """
    w = np.asarray(weights, dtype=float)
    w = np.clip(w, 0.0, None)
    if temperature != 1.0:
        w = np.power(w, temperature)
    total = w.sum()
    if total <= 0:
        idx = int(rng.integers(len(items)))
    else:
        idx = int(rng.choice(len(items), p=w / total))
    return items[idx]


def _pick_age(rng, catalog: CitizenSpawnCatalog, city: CityProfile) -> AgeBand:
    bands = catalog.age_bands
    mult = city.age_weight_multipliers
    weights = [b.weight * mult.get(b.name, 1.0) for b in bands]
    return _weighted_choice(rng, bands, weights, catalog.params.weight_temperature)


def _eligible_occupations(age: int, catalog: CitizenSpawnCatalog,
                          city: CityProfile) -> tuple[list[Occupation], list[float]]:
    available = city.workplaces_available()
    occs, weights = [], []
    mult = city.occupation_weight_multipliers
    for o in catalog.occupations:
        if not (o.min_age <= age <= o.max_age):
            continue
        if o.workplace not in available:
            continue                      # the city offers no such workplace
        occs.append(o)
        weights.append(o.base_weight * mult.get(o.name, 1.0))
    return occs, weights


def _pick_home(rng, city: CityProfile, temperature: float) -> District:
    residential = [d for d in city.districts if d.residential_weight > 0]
    if not residential:                   # degenerate map: fall back to anything
        residential = list(city.districts)
    weights = [d.residential_weight for d in residential]
    return _weighted_choice(rng, residential, weights, temperature)


def _pick_work(rng, occ: Occupation, home: District,
               city: CityProfile, temperature: float) -> Optional[District]:
    if occ.workplace in (HOME, ""):
        return None
    hosts = city.districts_hosting(occ.workplace)
    if not hosts:
        return None
    # Weight workplaces by residential_weight as a rough proxy for size/draw;
    # pure-workplace districts (weight 0) still get a small floor so they qualify.
    weights = [max(d.residential_weight, 0.25) for d in hosts]
    return _weighted_choice(rng, hosts, weights, temperature)


def _spread_tasks(tasks: list[str], start: float, end: float) -> list[ScheduleEntry]:
    """Lay an occupation's tasks end-to-end across [start, end) as work blocks."""
    if end <= start:
        return []
    labels = tasks or ["on shift"]
    span = (end - start) / len(labels)
    out = []
    for i, label in enumerate(labels):
        s = start + i * span
        out.append(ScheduleEntry(s, s + span, "work", "", label))
    return out


def _build_schedule(rng, occ: Occupation, home: District,
                    work: Optional[District], city: CityProfile,
                    p: SpawnParams) -> list[ScheduleEntry]:
    """Assemble a believable pre-collapse day for this citizen.

    Day workers: sleep -> wake/breakfast -> commute -> work(tasks) -> commute ->
    errand -> evening -> sleep.  Night workers invert it.  Citizens with no
    external workplace get a gentle home-and-errands day.  Locations are district
    names; work blocks inherit the workplace district.
    """
    home_n = home.name
    work_n = work.name if work else home_n
    entries: list[ScheduleEntry] = []

    # An optional midday/evening errand to the nearest commercial district.
    shops = city.districts_of_kind("commercial")
    errand_loc = shops[0].name if shops else home_n

    if work is None or occ.shift == "none":
        # Home-anchored day: sleep in, errands midday, leisure, sleep.
        wake = 7.5 + float(rng.uniform(-1.0, 1.5))
        entries.append(ScheduleEntry(0.0, wake, "sleep", home_n))
        entries.append(ScheduleEntry(wake, 10.5, "leisure", home_n, "morning at home"))
        entries.append(ScheduleEntry(10.5, 12.0, "errand", errand_loc, "run errands"))
        entries.append(ScheduleEntry(12.0, 18.0, "leisure", home_n, "afternoon at home"))
        entries.append(ScheduleEntry(18.0, 22.0, "leisure", home_n, "evening"))
        entries.append(ScheduleEntry(22.0, 24.0, "sleep", home_n))
        return _normalise(entries)

    commute = p.commute_hours
    if occ.shift == "night":
        ws, we = p.night_start, p.night_end          # e.g. 20 -> 28 (04:00)
        wake = ws - p.wake_before_work
        # The shift wraps past midnight (the 20->28 work/commute blocks below
        # cover 00:00-04:00 via the lookup's wrap rule); the citizen reaches home
        # ~04:00 and sleeps through the morning.
        entries.append(ScheduleEntry(4.0, 12.0, "sleep", home_n))
        entries.append(ScheduleEntry(12.0, wake, "leisure", home_n, "day off-shift"))
        entries.append(ScheduleEntry(wake, ws - commute, "errand", errand_loc,
                                     "pre-shift errands"))
        entries.append(ScheduleEntry(ws - commute, ws, "commute", work_n))
        entries.extend(_relocate(_spread_tasks(occ.tasks, ws, we - commute), work_n))
        entries.append(ScheduleEntry(we - commute, we, "commute", home_n))
    else:  # day shift
        ws, we = p.day_start, p.day_end
        wake = ws - p.wake_before_work
        entries.append(ScheduleEntry(0.0, wake, "sleep", home_n))
        entries.append(ScheduleEntry(wake, ws - commute, "leisure", home_n,
                                     "wake & breakfast"))
        entries.append(ScheduleEntry(ws - commute, ws, "commute", work_n))
        entries.extend(_relocate(_spread_tasks(occ.tasks, ws, we), work_n))
        entries.append(ScheduleEntry(we, we + commute, "commute", home_n))
        entries.append(ScheduleEntry(we + commute, we + commute + 1.5, "errand",
                                     errand_loc, "evening errands"))
        entries.append(ScheduleEntry(we + commute + 1.5, 22.5, "leisure", home_n,
                                     "evening at home"))
        entries.append(ScheduleEntry(22.5, 24.0, "sleep", home_n))
    return _normalise(entries)


def _relocate(entries: list[ScheduleEntry], location: str) -> list[ScheduleEntry]:
    for e in entries:
        e.location = location
    return entries


def _normalise(entries: list[ScheduleEntry]) -> list[ScheduleEntry]:
    """Drop zero/negative-length blocks and sort by start time."""
    out = [e for e in entries if e.end_hour > e.start_hour]
    out.sort(key=lambda e: e.start_hour)
    return out


def _current_block(schedule: list[ScheduleEntry], hour: float
                   ) -> Optional[ScheduleEntry]:
    """Find the block covering ``hour`` in [0,24), honouring blocks that wrap
    past midnight (end_hour > 24 covers the early-morning hours)."""
    for e in schedule:
        if e.start_hour <= hour < e.end_hour:
            return e
        if e.end_hour > 24.0 and (hour + 24.0) < e.end_hour and hour >= 0:
            # wrap: a block 20->28 also covers 0..4 of the next morning
            if e.start_hour <= hour + 24.0 < e.end_hour:
                return e
    return schedule[0] if schedule else None


def _roll_inventory(rng, occ: Occupation, catalog: CitizenSpawnCatalog,
                    city: CityProfile) -> dict[str, int]:
    p = catalog.params
    inv: dict[str, int] = {}
    # Occupation kit, scaled by the city's inventory multiplier with a wobble.
    for item, base in occ.inventory.items():
        scale = city.inventory_multiplier * (1.0 + float(
            rng.uniform(-p.inventory_jitter, p.inventory_jitter)))
        n = int(round(base * scale))
        if n > 0:
            inv[item] = inv.get(item, 0) + n
    # Common items everyone might be carrying, each rolled independently.
    for item, base in catalog.common_items.items():
        if rng.random() < p.common_item_prob:
            inv[item] = inv.get(item, 0) + max(1, base)
    return inv


def spawn_citizen(city: CityProfile, catalog: CitizenSpawnCatalog,
                  seed: int = 0, citizen_id: int = 0,
                  rng: Optional[np.random.Generator] = None) -> CitizenProfile:
    """Draw one citizen from ``city`` x ``catalog``.  Deterministic in ``seed``.

    Pass an explicit ``rng`` (e.g. from ``spawn_population``) to share a stream;
    otherwise one is built from ``seed``.
    """
    if rng is None:
        rng = np.random.default_rng(seed)
    p = catalog.params
    temp = p.weight_temperature

    band = _pick_age(rng, catalog, city)
    age = int(rng.integers(band.min_age, band.max_age + 1))

    occs, weights = _eligible_occupations(age, catalog, city)
    if not occs:                          # nothing age-eligible/reachable: idle
        occ = Occupation(name="resident", min_age=0, max_age=120,
                         workplace=HOME, shift="none")
    else:
        occ = _weighted_choice(rng, occs, weights, temp)

    home = _pick_home(rng, city, temp)
    work = _pick_work(rng, occ, home, city, temp)
    schedule = _build_schedule(rng, occ, home, work, city, p)
    inventory = _roll_inventory(rng, occ, catalog, city)

    spawn_hour = p.spawn_hour if p.spawn_hour is not None else float(rng.uniform(0, 24))
    block = _current_block(schedule, spawn_hour)

    return CitizenProfile(
        citizen_id=citizen_id,
        city=city.name,
        age=age,
        age_band=band.name,
        occupation=occ.name,
        shift=occ.shift,
        home_district=home.name,
        work_district=work.name if work else None,
        home_zone=home.zone,
        work_zone=work.zone if work else None,
        schedule=schedule,
        inventory=inventory,
        spawn_hour=spawn_hour,
        current_location=block.location if block else home.name,
        current_activity=block.activity if block else "idle",
        current_task=block.task if block else "",
    )


def spawn_population(city: CityProfile, catalog: CitizenSpawnCatalog,
                     n: int, seed: int = 0) -> list[CitizenProfile]:
    """Spawn ``n`` independent, reproducible citizens for a city.

    Per-citizen RNGs are spawned from one ``SeedSequence`` so the crowd is
    deterministic in ``seed`` and order-stable regardless of ``n``.
    """
    children = np.random.SeedSequence(seed).spawn(n)
    return [
        spawn_citizen(city, catalog, citizen_id=i,
                      rng=np.random.default_rng(children[i]))
        for i in range(n)
    ]


# ===========================================================================
# Default agnostic catalog + a handful of flavoured cities
# ===========================================================================
def default_catalog() -> CitizenSpawnCatalog:
    """The shared, city-agnostic possibility space.

    Every occupation here is offered in any city *that has a district hosting its
    workplace category* -- the catalog itself plays no favourites.
    """
    age_bands = [
        AgeBand("child", 0, 12, weight=0.14),
        AgeBand("teen", 13, 17, weight=0.07),
        AgeBand("young_adult", 18, 29, weight=0.20),
        AgeBand("adult", 30, 49, weight=0.28),
        AgeBand("middle_age", 50, 64, weight=0.18),
        AgeBand("senior", 65, 95, weight=0.13),
    ]

    occupations = [
        # name, ages, weight, workplace, shift, tasks, inventory
        Occupation("child", 0, 12, 1.0, HOME, "none",
                   ["play", "school run", "home"],
                   {"backpack": 1, "snack": 1}),
        Occupation("student", 6, 22, 1.0, "education", "day",
                   ["lectures", "library", "study group", "cafeteria"],
                   {"backpack": 1, "laptop": 1, "notebook": 1, "id_card": 1}),
        Occupation("teacher", 24, 65, 0.8, "education", "day",
                   ["homeroom", "lessons", "grading", "office hours"],
                   {"keys": 1, "laptop": 1, "id_card": 1, "marker": 2}),
        Occupation("nurse", 21, 63, 0.9, "medical", "night",
                   ["handover", "rounds", "medication", "charting", "rounds"],
                   {"id_badge": 1, "scrubs": 1, "phone": 1, "face_mask": 3,
                    "pen_light": 1}),
        Occupation("doctor", 27, 68, 0.5, "medical", "day",
                   ["ward round", "clinic", "consults", "notes"],
                   {"id_badge": 1, "stethoscope": 1, "phone": 1, "face_mask": 3}),
        Occupation("paramedic", 22, 60, 0.4, "medical", "night",
                   ["vehicle check", "callouts", "handover"],
                   {"id_badge": 1, "radio": 1, "trauma_kit": 1, "face_mask": 4}),
        Occupation("police_officer", 21, 60, 0.5, "civic", "night",
                   ["briefing", "patrol", "report writing", "patrol"],
                   {"badge": 1, "radio": 1, "keys": 1, "notebook": 1}),
        Occupation("firefighter", 21, 58, 0.3, "civic", "day",
                   ["equipment check", "drills", "standby", "callouts"],
                   {"radio": 1, "keys": 1, "helmet": 1}),
        Occupation("office_worker", 21, 66, 1.3, "commercial", "day",
                   ["email", "standup", "meetings", "spreadsheets", "calls"],
                   {"laptop": 1, "phone": 1, "id_card": 1, "keys": 1}),
        Occupation("grocery_clerk", 16, 67, 1.0, "commercial", "day",
                   ["open till", "restock", "checkout", "cash up"],
                   {"apron": 1, "name_tag": 1, "box_cutter": 1}),
        Occupation("chef", 18, 62, 0.6, "commercial", "day",
                   ["prep", "service", "clean down"],
                   {"knife_roll": 1, "apron": 1, "thermometer": 1}),
        Occupation("bus_driver", 24, 65, 0.5, "transit", "day",
                   ["vehicle check", "morning route", "layover", "evening route"],
                   {"keys": 1, "id_badge": 1, "ticket_machine": 1}),
        Occupation("dock_worker", 19, 60, 0.7, "industrial", "day",
                   ["muster", "load", "unload", "secure cargo"],
                   {"hi_vis": 1, "gloves": 1, "hard_hat": 1, "manifest": 1}),
        Occupation("factory_worker", 18, 63, 0.9, "industrial", "night",
                   ["line start", "run line", "qa checks", "shutdown"],
                   {"ear_plugs": 1, "gloves": 1, "id_badge": 1}),
        Occupation("construction_worker", 18, 62, 0.7, "industrial", "day",
                   ["toolbox talk", "build", "lunch", "build"],
                   {"hard_hat": 1, "gloves": 1, "tool_belt": 1, "hi_vis": 1}),
        Occupation("retiree", 60, 95, 1.0, HOME, "none",
                   ["morning walk", "errands", "rest"],
                   {"keys": 1, "reading_glasses": 1, "medication": 2}),
        Occupation("unemployed", 18, 64, 0.5, HOME, "none",
                   ["job search", "errands", "home"],
                   {"keys": 1, "phone": 1}),
    ]

    common_items = {
        "phone": 1, "wallet": 1, "keys": 1, "water_bottle": 1,
        "snack": 1, "cash": 1, "face_mask": 1, "transit_pass": 1,
    }

    return CitizenSpawnCatalog(age_bands=age_bands, occupations=occupations,
                               common_items=common_items, params=SpawnParams())


def _residential(name: str, zone: int, weight: float = 1.0) -> District:
    return District(name, "residential", weight, [], zone)


def default_cities() -> dict[str, CityProfile]:
    """A few cities that bias the same agnostic catalog in different directions.

    Each city is just a district map (some of which host workplaces) plus weight
    multipliers.  Zones are pinned onto an 8x8 macro grid so spawns resolve to
    ``ZoneGraph`` cells; the indices are illustrative, not load-bearing.
    """
    cities: dict[str, CityProfile] = {}

    # --- Generic balanced city (the agnostic baseline) ----------------------
    cities["generic"] = CityProfile(
        name="generic",
        population=40000,
        districts=[
            _residential("Old Town", zone=18, weight=1.2),
            _residential("Suburbs", zone=9, weight=1.5),
            District("Market", "commercial", 0.4, ["commercial"], zone=27),
            District("General Hospital", "medical", 0.1, ["medical"], zone=20),
            District("University", "education", 0.3, ["education"], zone=35),
            District("Civic Center", "civic", 0.2, ["civic"], zone=28),
            District("Industrial Estate", "industrial", 0.1, ["industrial"], zone=44),
            District("Central Depot", "transit", 0.1, ["transit"], zone=36),
        ],
    )

    # --- Harbor city: industry & transit heavy, has a real port -------------
    cities["harbor"] = CityProfile(
        name="harbor",
        population=70000,
        districts=[
            _residential("Dockside Rows", zone=11, weight=1.6),
            _residential("Hillside", zone=2, weight=1.0),
            District("Fish Market", "commercial", 0.4, ["commercial"], zone=19),
            District("Port Authority", "transit", 0.1, ["transit"], zone=12),
            District("Container Port", "industrial", 0.2, ["industrial"], zone=4),
            District("Shipyard", "industrial", 0.1, ["industrial"], zone=13),
            District("Harbor Clinic", "medical", 0.1, ["medical"], zone=20),
            District("Tech College", "education", 0.2, ["education"], zone=27),
            District("Harbor Patrol", "civic", 0.1, ["civic"], zone=3),
        ],
        occupation_weight_multipliers={
            "dock_worker": 3.0, "factory_worker": 1.8, "bus_driver": 1.4,
            "construction_worker": 1.3, "office_worker": 0.6, "doctor": 0.7,
        },
        age_weight_multipliers={"young_adult": 1.2, "senior": 0.85},
        inventory_multiplier=1.0,
    )

    # --- University town: students & teachers everywhere --------------------
    cities["university"] = CityProfile(
        name="university",
        population=30000,
        districts=[
            _residential("Student Halls", zone=26, weight=1.8),
            _residential("Faculty Row", zone=17, weight=0.9),
            District("Main Campus", "education", 0.2, ["education"], zone=27),
            District("Science Quad", "education", 0.1, ["education"], zone=35),
            District("High Street", "commercial", 0.5, ["commercial"], zone=18),
            District("Student Health", "medical", 0.1, ["medical"], zone=28),
            District("Town Hall", "civic", 0.1, ["civic"], zone=19),
            District("Bus Interchange", "transit", 0.1, ["transit"], zone=34),
        ],
        occupation_weight_multipliers={
            "student": 4.0, "teacher": 2.2, "office_worker": 0.7,
            "dock_worker": 0.1, "factory_worker": 0.2, "chef": 1.3,
        },
        age_weight_multipliers={"young_adult": 2.0, "teen": 1.3,
                                "middle_age": 0.7, "senior": 0.6},
    )

    # --- Capital: administration, services & commerce -----------------------
    cities["capital"] = CityProfile(
        name="capital",
        population=120000,
        districts=[
            _residential("Garden District", zone=10, weight=1.3),
            _residential("Riverside", zone=42, weight=1.4),
            District("Business District", "commercial", 0.3, ["commercial"], zone=27),
            District("Government Quarter", "civic", 0.2, ["civic"], zone=28),
            District("Central Hospital", "medical", 0.1, ["medical"], zone=20),
            District("State University", "education", 0.2, ["education"], zone=35),
            District("Grand Central", "transit", 0.1, ["transit"], zone=36),
            District("Light Industry", "industrial", 0.1, ["industrial"], zone=45),
        ],
        occupation_weight_multipliers={
            "office_worker": 2.2, "police_officer": 1.6, "doctor": 1.4,
            "nurse": 1.2, "dock_worker": 0.2, "factory_worker": 0.5,
        },
        age_weight_multipliers={"adult": 1.2, "middle_age": 1.1},
        inventory_multiplier=1.1,
    )

    return cities


# ===========================================================================
# CLI demo  (python -m asphodel.citizen [--emit] [--city NAME] [--n K])
# ===========================================================================
def _emit_presets(out_dir: str = "cities") -> None:
    """Write the default catalog + cities to YAML so the possibility space is
    committed as data (matching the project's config-as-data convention)."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    default_catalog().to_yaml(os.path.join(out_dir, "_catalog.yaml"))
    for name, city in default_cities().items():
        city.to_yaml(os.path.join(out_dir, f"{name}.yaml"))
    print(f"wrote catalog + {len(default_cities())} cities to {out_dir}/")


def _demo(city_name: str = "generic", n: int = 8, seed: int = 0) -> None:
    catalog = default_catalog()
    cities = default_cities()
    city = cities.get(city_name)
    if city is None:
        raise SystemExit(f"unknown city {city_name!r}; have {list(cities)}")
    print(f"=== {n} citizens spawned in '{city.name}' (seed {seed}) ===\n")
    for c in spawn_population(city, catalog, n, seed=seed):
        print(c.summary())
        print()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Citizen spawn demo / preset emitter")
    ap.add_argument("--emit", action="store_true",
                    help="write catalog + city presets to cities/*.yaml")
    ap.add_argument("--city", default="generic")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.emit:
        _emit_presets()
    else:
        _demo(args.city, args.n, args.seed)

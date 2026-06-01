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

from .world import (
    OSMSource, SynthCitySpec, StreetMap, Building,
    load_osm, synthesize_city,
)
from .vehicles import choose_commute, TrafficParams


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
    """A city: how to source its spatial world, plus how it biases the catalog.

    The multipliers are the "slightly determined by the city" dial -- they scale
    the catalog's base weights but never invent or hard-delete possibilities.

    A city's *world* (streets + buildings) comes from one of two sources:

    * ``osm`` -- an ``OSMSource`` locating a real city in OpenStreetMap; or
    * ``synth`` -- a ``SynthCitySpec`` for the deterministic procedural fallback.

    ``resolve_world`` turns whichever is set into a ``CityWorld`` (see below).
    The legacy ``districts`` list is the *map-less* path: when no world is
    resolved, occupation reachability and locations fall back to abstract
    districts -- which is why both paths still work.  The heavy ``StreetMap`` is
    never stored on the profile; the profile only says how to *source* it.
    """

    name: str = "generic"
    population: Optional[int] = None
    districts: list[District] = field(default_factory=list)
    age_weight_multipliers: dict[str, float] = field(default_factory=dict)
    occupation_weight_multipliers: dict[str, float] = field(default_factory=dict)
    inventory_multiplier: float = 1.0   # scales job starting-inventory counts

    # World source (the connection to the street map + building information).
    osm: Optional["OSMSource"] = None
    synth: Optional["SynthCitySpec"] = None

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
        osm_d = data.pop("osm", None)
        synth_d = data.pop("synth", None)
        osm = OSMSource(**osm_d) if osm_d else None
        synth = SynthCitySpec(**synth_d) if synth_d else None
        return cls(districts=districts, osm=osm, synth=synth, **data)


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

    # Resolved spatial world references (None on the abstract / map-less path).
    # When the city resolved a StreetMap, home/work are *real buildings* and the
    # coordinates are local metres in the map frame.
    home_building_id: Optional[int] = None
    work_building_id: Optional[int] = None
    home_xy: Optional[tuple[float, float]] = None
    work_xy: Optional[tuple[float, float]] = None
    commute_metres: Optional[float] = None   # street-routed distance home->work
    commute_mode: Optional[str] = None       # walk / bike / car / transit / drive_work
    vehicle: Optional[str] = None            # vehicle kind they travel in

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


def _build_schedule(rng, occ: Occupation, home_n: str,
                    work_n: Optional[str], errand_loc: str,
                    p: SpawnParams) -> list[ScheduleEntry]:
    """Assemble a believable pre-collapse day for this citizen.

    Day workers: sleep -> wake/breakfast -> commute -> work(tasks) -> commute ->
    errand -> evening -> sleep.  Night workers invert it.  Citizens with no
    external workplace get a gentle home-and-errands day.  Locations are plain
    place-name strings (a district name in the abstract path, a building label in
    the world path), so this routine is source-agnostic.
    """
    work_present = work_n is not None
    if not work_present:
        work_n = home_n
    entries: list[ScheduleEntry] = []

    if not work_present or occ.shift == "none":
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
    shops = city.districts_of_kind("commercial")
    errand_loc = shops[0].name if shops else home.name
    schedule = _build_schedule(rng, occ, home.name,
                               work.name if work else None, errand_loc, p)
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
# World-resolved spawn: citizens live and work in REAL buildings
# ===========================================================================
@dataclass
class CityWorld:
    """A resolved city: its ``CityProfile`` bound to a concrete ``StreetMap``.

    This is what ``choose a city -> world populates`` produces.  Spawning against
    a ``CityWorld`` places citizens in real building footprints and routes their
    commute along the street graph; home/work zones are derived from building
    position so the spawn still drops cleanly onto the macro ``ZoneGraph`` grid.
    """

    profile: CityProfile
    street_map: StreetMap
    grid_rows: int = 8                 # macro-grid resolution for zone mapping
    grid_cols: int = 8

    def zone_of_xy(self, xy: tuple[float, float]) -> int:
        """Map a metre coordinate to a macro grid zone index (row*cols+col)."""
        xmin, ymin, xmax, ymax = self.street_map.bbox
        fx = 0.0 if xmax == xmin else (xy[0] - xmin) / (xmax - xmin)
        fy = 0.0 if ymax == ymin else (xy[1] - ymin) / (ymax - ymin)
        col = min(self.grid_cols - 1, max(0, int(fx * self.grid_cols)))
        row = min(self.grid_rows - 1, max(0, int(fy * self.grid_rows)))
        return row * self.grid_cols + col


def resolve_world(profile: CityProfile, seed: int = 0,
                  grid_rows: int = 8, grid_cols: int = 8) -> CityWorld:
    """Populate a city's world from its source: choose a city -> a real map.

    Precedence: an explicit ``osm`` source (real OpenStreetMap) wins; otherwise a
    ``synth`` spec (or a default one) builds a deterministic procedural city so
    the pipeline always has a runnable world.
    """
    if profile.osm is not None:
        street_map = load_osm(profile.osm)         # real-city ingestion seam
    else:
        spec = profile.synth or SynthCitySpec()
        street_map = synthesize_city(spec, seed=seed, name=profile.name)
    return CityWorld(profile=profile, street_map=street_map,
                     grid_rows=grid_rows, grid_cols=grid_cols)


def _nearest_building(sm: StreetMap, origin_xy: tuple[float, float],
                      candidates: list[Building]) -> Optional[Building]:
    """The candidate building closest (Euclidean) to an origin point."""
    if not candidates:
        return None
    ox, oy = origin_xy
    return min(candidates, key=lambda b: (b.centroid[0] - ox) ** 2
               + (b.centroid[1] - oy) ** 2)


def spawn_citizen_in_world(world: CityWorld, catalog: CitizenSpawnCatalog,
                           seed: int = 0, citizen_id: int = 0,
                           rng: Optional[np.random.Generator] = None
                           ) -> CitizenProfile:
    """Draw one citizen whose home and work are real buildings on the map.

    The occupation possibility space is still the agnostic catalog, gated now by
    which building *categories* the map actually contains, and biased by the
    city's multipliers.  Home/work buildings are weighted by their occupant
    capacity (bigger buildings hold more people), the commute is street-routed,
    and the day's schedule uses building labels as locations.
    """
    if rng is None:
        rng = np.random.default_rng(seed)
    sm = world.street_map
    city = world.profile
    p = catalog.params
    temp = p.weight_temperature

    band = _pick_age(rng, catalog, city)
    age = int(rng.integers(band.min_age, band.max_age + 1))

    # Reachability is gated by building categories present in the actual map.
    present = sm.categories_present() | {HOME, ""}
    occs, weights = [], []
    occ_mult = city.occupation_weight_multipliers
    for o in catalog.occupations:
        if not (o.min_age <= age <= o.max_age):
            continue
        if o.workplace not in present:
            continue
        occs.append(o)
        weights.append(o.base_weight * occ_mult.get(o.name, 1.0))
    occ = (_weighted_choice(rng, occs, weights, temp) if occs
           else Occupation(name="resident", min_age=0, max_age=120,
                           workplace=HOME, shift="none"))

    # Home: a residential building weighted by capacity.
    homes = sm.residential_buildings() or sm.buildings
    home_b = _weighted_choice(rng, homes, [b.capacity for b in homes], temp)

    # Work: a building hosting the occupation's category, weighted by capacity.
    work_b: Optional[Building] = None
    if occ.workplace not in (HOME, ""):
        hosts = sm.buildings_hosting(occ.workplace)
        if hosts:
            work_b = _weighted_choice(rng, hosts, [b.capacity for b in hosts], temp)

    # Errand: the commercial building nearest home (a believable local shop).
    errand_b = _nearest_building(sm, home_b.centroid, sm.buildings_hosting("commercial"))
    errand_loc = errand_b.label() if errand_b else home_b.neighborhood

    schedule = _build_schedule(rng, occ, home_b.label(),
                               work_b.label() if work_b else None, errand_loc, p)
    inventory = _roll_inventory(rng, occ, catalog, city)

    commute_m = None
    commute_mode = vehicle = None
    if work_b is not None:
        commute_m = sm.route_length(home_b.street_node, work_b.street_node)
        if not np.isfinite(commute_m):
            commute_m = None
        # Travel mode + vehicle: driving jobs use their work vehicle; everyone
        # else picks by distance/age, transit only where the city has it.
        dist = commute_m if commute_m is not None else float(np.hypot(
            work_b.centroid[0] - home_b.centroid[0],
            work_b.centroid[1] - home_b.centroid[1]))
        transit_available = "transit" in sm.categories_present()
        commute_mode, vehicle = choose_commute(
            rng, occ.name, dist, age, transit_available, TrafficParams())

    spawn_hour = p.spawn_hour if p.spawn_hour is not None else float(rng.uniform(0, 24))
    block = _current_block(schedule, spawn_hour)

    return CitizenProfile(
        citizen_id=citizen_id,
        city=city.name,
        age=age,
        age_band=band.name,
        occupation=occ.name,
        shift=occ.shift,
        home_district=home_b.neighborhood,
        work_district=work_b.neighborhood if work_b else None,
        home_zone=world.zone_of_xy(home_b.centroid),
        work_zone=world.zone_of_xy(work_b.centroid) if work_b else None,
        schedule=schedule,
        inventory=inventory,
        spawn_hour=spawn_hour,
        current_location=block.location if block else home_b.label(),
        current_activity=block.activity if block else "idle",
        current_task=block.task if block else "",
        home_building_id=home_b.id,
        work_building_id=work_b.id if work_b else None,
        home_xy=home_b.centroid,
        work_xy=work_b.centroid if work_b else None,
        commute_metres=commute_m,
        commute_mode=commute_mode,
        vehicle=vehicle,
    )


def spawn_population_in_world(world: CityWorld, catalog: CitizenSpawnCatalog,
                             n: int, seed: int = 0) -> list[CitizenProfile]:
    """Spawn ``n`` reproducible citizens into a resolved city world."""
    children = np.random.SeedSequence(seed).spawn(n)
    return [
        spawn_citizen_in_world(world, catalog, citizen_id=i,
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
        # --- expanded diversity ---------------------------------------------
        # medical
        Occupation("pharmacist", 24, 66, 0.4, "medical", "day",
                   ["open dispensary", "prescriptions", "stock check", "advice"],
                   {"id_badge": 1, "white_coat": 1, "face_mask": 2}),
        Occupation("care_worker", 19, 64, 0.7, "medical", "day",
                   ["handover", "personal care", "meds round", "meals"],
                   {"id_badge": 1, "gloves": 2, "face_mask": 3}),
        Occupation("lab_technician", 22, 63, 0.4, "medical", "night",
                   ["sample intake", "run assays", "log results"],
                   {"id_badge": 1, "lab_coat": 1, "gloves": 2}),
        # education
        Occupation("professor", 30, 70, 0.4, "education", "day",
                   ["lecture", "research", "supervision", "faculty meeting"],
                   {"laptop": 1, "id_card": 1, "notebook": 1}),
        Occupation("childcare_worker", 19, 60, 0.6, "education", "day",
                   ["welcome", "activities", "lunch", "nap time"],
                   {"id_card": 1, "apron": 1, "first_aid_kit": 1}),
        # civic / public service
        Occupation("soldier", 18, 50, 0.4, "civic", "day",
                   ["muster", "drills", "duty", "stand-down"],
                   {"id_tag": 1, "boots": 1, "rations": 1}),
        Occupation("sanitation_worker", 20, 62, 0.6, "civic", "day",
                   ["depot", "collection round", "transfer station"],
                   {"hi_vis": 1, "gloves": 2, "keys": 1}),
        Occupation("social_worker", 24, 64, 0.4, "civic", "day",
                   ["case review", "home visits", "reports"],
                   {"laptop": 1, "id_card": 1, "phone": 1}),
        Occupation("lawyer", 26, 68, 0.3, "civic", "day",
                   ["case prep", "client meetings", "court", "filings"],
                   {"laptop": 1, "id_card": 1, "documents": 3}),
        # commercial / services
        Occupation("waiter", 17, 60, 0.8, "commercial", "night",
                   ["set up", "service", "bus tables", "close"],
                   {"apron": 1, "order_pad": 1, "name_tag": 1}),
        Occupation("barista", 16, 55, 0.7, "commercial", "day",
                   ["open", "morning rush", "restock", "clean"],
                   {"apron": 1, "name_tag": 1}),
        Occupation("accountant", 23, 67, 0.6, "commercial", "day",
                   ["reconcile", "ledgers", "client calls", "filings"],
                   {"laptop": 1, "id_card": 1, "calculator": 1}),
        Occupation("it_support", 20, 63, 0.7, "commercial", "day",
                   ["ticket queue", "deskside", "patching", "on-call"],
                   {"laptop": 1, "id_card": 1, "phone": 1, "usb_drive": 1}),
        Occupation("security_guard", 21, 67, 0.6, "commercial", "night",
                   ["briefing", "patrol", "monitor cctv", "patrol"],
                   {"radio": 1, "torch": 1, "id_badge": 1, "keys": 1}),
        Occupation("cleaner", 18, 68, 0.8, "commercial", "night",
                   ["supplies", "offices", "restrooms", "lock up"],
                   {"gloves": 2, "keys": 1, "id_badge": 1}),
        # industrial / trades
        Occupation("warehouse_worker", 18, 62, 0.8, "industrial", "day",
                   ["pick list", "pack", "load bay", "stocktake"],
                   {"hi_vis": 1, "gloves": 1, "scanner": 1}),
        Occupation("electrician", 20, 64, 0.5, "industrial", "day",
                   ["job sheet", "first fix", "test", "sign off"],
                   {"tool_belt": 1, "multimeter": 1, "gloves": 1}),
        Occupation("plumber", 20, 64, 0.5, "industrial", "day",
                   ["call list", "repairs", "install", "invoice"],
                   {"tool_bag": 1, "wrench": 2, "gloves": 1}),
        Occupation("mechanic", 18, 64, 0.6, "industrial", "day",
                   ["work orders", "diagnostics", "repairs", "road test"],
                   {"tool_box": 1, "rag": 1, "overalls": 1}),
        Occupation("welder", 20, 60, 0.4, "industrial", "night",
                   ["setup", "weld", "grind", "inspect"],
                   {"welding_mask": 1, "gloves": 1, "overalls": 1}),
        # driving / logistics (the vehicle-bound jobs)
        Occupation("taxi_driver", 21, 68, 0.5, "transit", "day",
                   ["vehicle check", "fares", "rank wait", "fares"],
                   {"keys": 1, "phone": 1, "id_badge": 1, "cash": 1}),
        Occupation("delivery_driver", 19, 64, 0.8, "commercial", "day",
                   ["load van", "route", "drops", "returns"],
                   {"keys": 1, "scanner": 1, "hi_vis": 1, "phone": 1}),
        Occupation("truck_driver", 23, 65, 0.6, "industrial", "day",
                   ["pre-trip check", "long haul", "delivery", "logbook"],
                   {"keys": 1, "logbook": 1, "hi_vis": 1, "thermos": 1}),
        Occupation("courier", 16, 55, 0.5, "commercial", "day",
                   ["depot", "pickups", "drops", "depot"],
                   {"backpack": 1, "phone": 1, "scanner": 1, "lock": 1}),
        Occupation("postal_worker", 18, 65, 0.6, "transit", "day",
                   ["sort", "load round", "deliver", "return"],
                   {"hi_vis": 1, "keys": 1, "scanner": 1}),
        # home-anchored
        Occupation("homemaker", 20, 75, 0.7, HOME, "none",
                   ["household", "errands", "childcare"],
                   {"keys": 1, "phone": 1, "shopping_bag": 1}),
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
        synth=SynthCitySpec(blocks_x=6, blocks_y=6),  # balanced default zoning
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
        synth=SynthCitySpec(blocks_x=7, blocks_y=6, zoning_weights={
            "residential": 5.0, "industrial": 2.8, "transit": 1.4,
            "commercial": 2.0, "medical": 0.4, "education": 0.6, "civic": 0.4,
        }),
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
        synth=SynthCitySpec(blocks_x=5, blocks_y=5, zoning_weights={
            "residential": 5.0, "education": 3.0, "commercial": 2.2,
            "medical": 0.5, "civic": 0.4, "industrial": 0.2, "transit": 0.5,
        }),
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
        synth=SynthCitySpec(blocks_x=8, blocks_y=8, zoning_weights={
            "residential": 6.0, "commercial": 3.0, "civic": 1.5,
            "medical": 0.8, "education": 1.0, "industrial": 0.6, "transit": 0.7,
        }),
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


def _demo(city_name: str = "generic", n: int = 8, seed: int = 0,
          world: bool = False) -> None:
    catalog = default_catalog()
    cities = default_cities()
    city = cities.get(city_name)
    if city is None:
        raise SystemExit(f"unknown city {city_name!r}; have {list(cities)}")

    if world:
        from .vehicles import congestion_report
        cw = resolve_world(city, seed=seed)
        sm = cw.street_map
        print(f"=== '{city.name}': {sm.source}, {len(sm.buildings)} buildings, "
              f"{len(sm.nodes)} street nodes ===\n")
        pop = spawn_population_in_world(cw, catalog, n, seed=seed)
        for c in pop:
            print(c.summary())
            extra = (f"        building #{c.home_building_id} @ "
                     f"({c.home_xy[0]:.0f},{c.home_xy[1]:.0f})")
            if c.commute_metres is not None:
                extra += (f"  commute {c.commute_metres:.0f} m "
                          f"by {c.commute_mode} ({c.vehicle})")
            print(extra)
            print()
        # Whole-population morning commute -> traffic snapshot.
        big = spawn_population_in_world(cw, catalog, max(n, 400), seed=seed)
        rep = congestion_report(cw, big)
        print(f"--- morning commute traffic ({len(big)} citizens) ---")
        print(f"    {rep['commuters']} commuters, {rep['motorized']} motorized, "
              f"{rep['total_pcu']:.0f} PCU on {rep['loaded_edges']} segments")
        print(f"    network load {rep['network_load']:.2f} (mean V/C), "
              f"worst {rep['max_voc']:.2f}, mean commute {rep['mean_commute_min']:.1f} min")
    else:
        print(f"=== {n} citizens spawned in '{city.name}' (seed {seed}) ===\n")
        for c in spawn_population(city, catalog, n, seed=seed):
            print(c.summary())
            print()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Citizen spawn demo / preset emitter")
    ap.add_argument("--emit", action="store_true",
                    help="write catalog + city presets to cities/*.yaml")
    ap.add_argument("--world", action="store_true",
                    help="resolve the city's street map + buildings and spawn into them")
    ap.add_argument("--city", default="generic")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.emit:
        _emit_presets()
    else:
        _demo(args.city, args.n, args.seed, world=args.world)

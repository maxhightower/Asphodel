"""
Environmental events: what the *place* does when the world ends.

Three event families already exist -- occupation ``signatures`` (what your job
makes of the collapse), ``travel_events`` (what the road does), and the aerial
crash hazards (what falls from the sky).  The abstraction under all of them is
the **environment**: where you physically are when it hits.  This module is that
layer -- the catalogue of things a *place* can do, independent of your job or
vehicle, so a citizen caught at home, on the street, in a high-rise, on the
waterfront, underground, in a hospital or a factory each faces hazards true to
that environment.

It is deliberately the open-ended, "explore all sorts of events" surface: adding
a new environment or a new event is a single entry in the list below.  Each event
names the environments it can occur in (or ``ANY_INDOOR`` / the broad lists) plus
the same situation / dilemma / assets / hazards / tags / severity shape the other
event families use, so a game layer treats them uniformly.

Pure content + a selector; no imports from the rest of the package.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# Environment taxonomy -- where a citizen can be standing at the collapse.
RESIDENTIAL = "residential"
HIGH_RISE = "high_rise"
RETAIL = "retail"
MEDICAL = "medical"
EDUCATION = "education"
CIVIC = "civic"
INDUSTRIAL = "industrial"
TRANSIT_HUB = "transit_hub"
STREET = "street"
WATERFRONT = "waterfront"
UNDERGROUND = "underground"

ENVIRONMENTS = (RESIDENTIAL, HIGH_RISE, RETAIL, MEDICAL, EDUCATION, CIVIC,
                INDUSTRIAL, TRANSIT_HUB, STREET, WATERFRONT, UNDERGROUND)

# Convenience groupings for events that span many places.
ANY_INDOOR = (RESIDENTIAL, HIGH_RISE, RETAIL, MEDICAL, EDUCATION, CIVIC,
              INDUSTRIAL, TRANSIT_HUB)
CROWDED = (RETAIL, EDUCATION, CIVIC, TRANSIT_HUB, HIGH_RISE, MEDICAL)


@dataclass
class EnvironmentEvent:
    """A hazard a place can produce, keyed to the environments it occurs in."""

    name: str
    environments: tuple
    situation: str = ""
    dilemma: str = ""
    assets: list = field(default_factory=list)
    hazards: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    weight: float = 1.0
    severity: int = 2


def default_environment_events() -> list[EnvironmentEvent]:
    """A broad first catalogue spanning every environment.  Extend freely."""
    E = EnvironmentEvent
    return [
        # --- cross-environment disasters ------------------------------------
        E("Fire takes hold", ANY_INDOOR,
          "Smoke starts stacking against the ceiling and the nearest exit is already backing up.",
          "Beat the crowd to a way out, or find a window and clean air.",
          ["you know this building's layout"],
          ["smoke and heat", "exits choking with people"],
          ["fire", "trapped", "crowd"], weight=1.6, severity=4),
        E("The power dies", ANY_INDOOR,
          "Lights, lifts and every system drop together; the building goes dark and silent.",
          "Feel your way out now, or wait for backup power that may not come.",
          ["a familiar space, even in the dark"],
          ["no light", "lifts and doors dead", "alarms failing"],
          ["infrastructure", "isolation"], weight=1.4, severity=2),
        E("Gas leak", (RESIDENTIAL, RETAIL, INDUSTRIAL, CIVIC),
          "A hiss and a stink of gas fills the room -- one spark from going up.",
          "Get out and get clear, or kill every ignition source first.",
          ["a few seconds before it finds a spark"],
          ["explosive atmosphere", "invisible, spreading"],
          ["gas", "fire", "trapped"], weight=0.9, severity=4),
        E("The structure gives", ANY_INDOOR,
          "A crack runs across the ceiling and a wall lets go in a gout of dust.",
          "Shelter under something solid, or break for the open before more comes down.",
          ["a doorway or a heavy table nearby"],
          ["falling masonry", "collapse", "dust choking the air"],
          ["structural", "trapped"], weight=1.0, severity=4),
        E("Crush at the doors", CROWDED,
          "Everyone makes for the same exit at once and the press of bodies takes your feet off the floor.",
          "Stay upright and ride the current, or peel away to a route no one else knows.",
          ["you spotted a side exit"],
          ["a panicking crowd", "no control over where you go"],
          ["crowd", "trapped"], weight=1.5, severity=3),

        # --- residential ----------------------------------------------------
        E("The neighbours turn", (RESIDENTIAL,),
          "Fists on the door -- the family from down the hall wants in, or wants what you have.",
          "Hold the door and talk them down, or slip out the back before it escalates.",
          ["a home you can lock", "knows the building's other ways out"],
          ["desperate people who know you're home"],
          ["crowd", "isolation"], weight=1.0, severity=3),
        E("The fire jumps the gap", (RESIDENTIAL,),
          "The house next door is alight and the wind is carrying it straight at yours.",
          "Grab what you can and go, or fight it at the boundary.",
          ["minutes before it crosses", "your own supplies to grab"],
          ["spreading fire", "smoke"],
          ["fire", "supplies"], weight=0.8, severity=4),

        # --- high-rise ------------------------------------------------------
        E("Trapped above the fire", (HIGH_RISE,),
          "Smoke is rising up the only stairwell -- and you're above it.",
          "Climb for the roof, or seal a room and signal from a window.",
          ["height and a clear view", "a sealable room"],
          ["fire below the only way down", "no working lift"],
          ["height", "fire", "trapped"], weight=1.1, severity=5),
        E("The curtain wall lets go", (HIGH_RISE,),
          "A whole pane of the glass facade shears away and the wind howls into the floor.",
          "Get back from the edge into the core, or use the chaos to move unseen.",
          ["the building's core is solid"],
          ["a sheer drop where a wall was", "flying glass"],
          ["height", "trapped"], weight=0.7, severity=4),

        # --- retail ---------------------------------------------------------
        E("Stampede down the aisles", (RETAIL,),
          "The shop floor turns into a stampede, shelves going over like dominoes.",
          "Take cover at the end of an aisle, or make for the stockroom behind you.",
          ["a stockroom of food and water", "you know the back of house"],
          ["toppling shelving", "a crushing crowd"],
          ["crowd", "supplies", "trapped"], weight=1.2, severity=3),

        # --- medical --------------------------------------------------------
        E("The oxygen system fails", (MEDICAL,),
          "Wall pressure drops and alarms shriek across the ward as the oxygen runs out.",
          "Help move patients to portable air, or get clear of a building turning into a tomb.",
          ["medical supplies all around", "portable oxygen, if you're quick"],
          ["patients dying around you", "a building you can't save"],
          ["mass_casualty", "medical_supplies"], weight=1.0, severity=4),
        E("The ward goes dark", (MEDICAL,),
          "Backup power coughs and fails; every monitor and ventilator on the floor flatlines at once.",
          "Hand-bag who you can, or accept there's nothing more to do here.",
          ["you understand the equipment"],
          ["life support gone", "an impossible triage"],
          ["mass_casualty", "infrastructure"], weight=0.8, severity=5),

        # --- education ------------------------------------------------------
        E("A building full of children", (EDUCATION,),
          "Classroom doors burst open into corridors filling with frightened kids and no teachers in sight.",
          "Shepherd a knot of children to safety, or move faster alone.",
          ["you know the floor plan"],
          ["children with no one to mind them", "a corridor crush"],
          ["children", "crowd", "vulnerable"], weight=1.0, severity=3),

        # --- civic ----------------------------------------------------------
        E("The holding cells", (CIVIC,),
          "Behind a door down the corridor, detainees are hammering as the electronic locks flicker.",
          "Let them out and gain numbers, or leave them and gain a head start.",
          ["control of the doors, for now"],
          ["people who may help or harm", "an impossible call"],
          ["keys_access", "crowd"], weight=0.7, severity=3),

        # --- industrial -----------------------------------------------------
        E("A tank ruptures", (INDUSTRIAL, WATERFRONT),
          "A storage tank splits and a low cloud of vapour begins rolling across the floor.",
          "Get upwind and out, or seal the bulkhead behind you.",
          ["you know the safe routes out"],
          ["toxic vapour", "no respirator"],
          ["hazmat", "fire", "trapped"], weight=0.9, severity=4),
        E("The line won't stop", (INDUSTRIAL,),
          "With the controls dead, the machinery keeps running -- presses, conveyors, blades, all of it.",
          "Pick your way past live machines to the exit, or kill the power at the main.",
          ["heavy tools", "knows the kill-switches"],
          ["unstoppable machinery", "no guards, no power"],
          ["tools", "trapped"], weight=0.8, severity=4),
        E("The racking comes down", (INDUSTRIAL,),
          "A run of warehouse racking buckles and tonnes of stock avalanche into the aisle.",
          "Dive clear down a cross-aisle, or shelter under the steel frame.",
          ["aisles of supplies, if you survive them"],
          ["tonnes of falling stock", "blocked aisles"],
          ["supplies", "structural", "trapped"], weight=0.9, severity=4),

        # --- transit hub ----------------------------------------------------
        E("The concourse crushes", (TRANSIT_HUB,),
          "The whole concourse surges for the platforms at once and the bottleneck takes hold.",
          "Get your back to a pillar and let it pass, or ride it down to the platforms.",
          ["sightlines over the whole hall"],
          ["a crowd with one direction", "no room to fall"],
          ["crowd", "trapped"], weight=1.2, severity=3),

        # --- waterfront -----------------------------------------------------
        E("The surge comes over the wall", (WATERFRONT,),
          "The sea heaves up over the harbour wall and water starts sheeting across the quay.",
          "Get to high ground or an upper floor, or reach a boat while you can.",
          ["boats and high ground both in sight"],
          ["rising water", "cold and current"],
          ["flood", "mobility"], weight=1.0, severity=4),
        E("Fuel ablaze on the water", (WATERFRONT,),
          "A ruptured bunker spreads burning fuel across the harbour, the fire walking toward the docks.",
          "Move inland away from the waterline, or commandeer something that floats and runs.",
          ["the docks' vehicles and gear"],
          ["fire spreading on water", "thick black smoke"],
          ["fire", "flood"], weight=0.7, severity=4),

        # --- underground ----------------------------------------------------
        E("The tunnel floods", (UNDERGROUND,),
          "Water starts pouring in from somewhere ahead, rising fast in the dark.",
          "Wade for the nearest exit now, or climb above the waterline and wait.",
          ["you can feel the slope toward the exits"],
          ["rising water in the dark", "no light", "cold"],
          ["flood", "tunnel", "isolation"], weight=1.0, severity=5),
        E("Smoke fills the dark", (UNDERGROUND,),
          "Somewhere below, something is burning, and the smoke has nowhere to go but here.",
          "Drop low and follow the wall to an exit, or find an air pocket and signal.",
          ["the wall will lead you out"],
          ["choking smoke", "total darkness", "no signal"],
          ["fire", "tunnel", "isolation"], weight=0.9, severity=4),

        # --- street ---------------------------------------------------------
        E("A facade comes down", (STREET,),
          "A whole storey of masonry sheets off the building above and rains onto the pavement.",
          "Get into a doorway or the road, away from the wall.",
          ["open space to run to"],
          ["falling masonry", "no warning"],
          ["structural", "exposed"], weight=1.0, severity=4),
        E("The crowd turns to a riot", (STREET,),
          "The street panic curdles into a riot -- windows going in, people swinging at anything.",
          "Get off the main drag down a side street, or keep your head down in the throng.",
          ["you know the back streets"],
          ["mob violence", "no police left"],
          ["crowd", "exposed"], weight=1.1, severity=3),
        E("A car ploughs the crowd", (STREET,),
          "A driver panics and accelerates straight through the press of people on the street.",
          "Pull whoever you can out of its line, or get yourself behind something solid.",
          ["a parked car or bollard to use as cover"],
          ["a vehicle out of control", "a packed pavement"],
          ["vehicle_moving", "crowd", "exposed"], weight=0.8, severity=4),
    ]


def select_environment_event(rng: np.random.Generator, environment: str,
                             events: list[EnvironmentEvent] | None = None
                             ) -> EnvironmentEvent | None:
    """Pick a hazard for ``environment`` (weighted, deterministic in ``rng``).

    Returns ``None`` if the environment has no events (e.g. one not yet given a
    catalogue), so the caller can fall back to its generic situation.
    """
    if events is None:
        events = default_environment_events()
    candidates = [e for e in events if environment in e.environments]
    if not candidates:
        return None
    weights = np.array([e.weight for e in candidates], dtype=float)
    return candidates[int(rng.choice(len(candidates), p=weights / weights.sum()))]

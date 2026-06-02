"""
Travel events: the predicaments that belong to *being in transit*, independent of
what you do for a living.

Where ``signatures.py`` answers "what does your job make of the collapse", this
answers "what does the *road* make of it" -- the gridlock that boxes you in, the
fuel tanker that goes up two cars ahead, the flyover you're stranded on with
traffic locked solid and a long drop either side, the tunnel that goes dark with
both ends jammed.  They fire when a citizen is caught mid-commute, selected from
the **road structure** they're physically on (surface / highway / bridge /
tunnel / ramp) and the **vehicle** they're in.

Pure content + a selector; imports only the road-structure constants from
``world`` (no cycle -- ``world`` doesn't import this).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .world import SURFACE, HIGHWAY, BRIDGE, TUNNEL, RAMP


@dataclass
class TravelEvent:
    """A traffic/transit predicament keyed to a road structure and vehicle class."""

    name: str
    structures: tuple = (SURFACE,)      # road structures this can happen on
    vehicles: str = "motorized"         # "any" | "motorized" | "nonmotorized" | "transit"
    situation: str = ""
    dilemma: str = ""
    assets: list = field(default_factory=list)
    hazards: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    weight: float = 1.0                 # relative likelihood among matches
    severity: int = 2                   # 1 (nuisance) .. 5 (lethal)


def default_travel_events() -> list[TravelEvent]:
    """The catalogue of in-transit events, spanning every road structure."""
    return [
        # --- surface streets ------------------------------------------------
        TravelEvent("Total gridlock", (SURFACE, RAMP), "motorized",
                    "Bumper to bumper, then nobody is moving at all.",
                    "Sit tight in a metal box, or abandon the car and go on foot.",
                    ["a vehicle, for now", "you can watch the panic spread car to car"],
                    ["boxed in on every side"],
                    ["trapped", "vehicle_moving", "crowd"], weight=2.0, severity=2),
        TravelEvent("Junction pile-up", (SURFACE,), "motorized",
                    "The lights die and four lanes claim the junction at once.",
                    "Thread the wreckage, or reverse out before the next car does.",
                    ["a vehicle", "an opening, if you're quick"],
                    ["crumpling metal", "blocked in seconds"],
                    ["vehicle_moving", "trapped"], weight=1.2, severity=3),
        # --- highway --------------------------------------------------------
        TravelEvent("Tanker goes up", (HIGHWAY,), "motorized",
                    "A fuel tanker jackknifes ahead and erupts into a wall of flame.",
                    "Reverse into the chaos behind you, or run from the fireball on foot.",
                    ["distance, if you move now"],
                    ["fire", "secondary explosions", "choking smoke"],
                    ["fire", "trapped", "vehicle_moving"], weight=1.0, severity=5),
        TravelEvent("Motorway folds up", (HIGHWAY,), "motorized",
                    "Eighty to zero -- the motorway concertinas into a pile-up in seconds.",
                    "Climb the central barrier on foot, or ride it out in the cab.",
                    ["a sturdy vehicle around you"],
                    ["high-speed wreckage", "no hard shoulder left"],
                    ["vehicle_moving", "trapped"], weight=1.4, severity=4),
        # --- ramp / flyover -------------------------------------------------
        TravelEvent("Stranded on the flyover", (RAMP,), "motorized",
                    "Caught on an overhead ramp with cars locked solid both ways and a "
                    "long drop off either edge.",
                    "Climb down the ramp's side on foot, or wait out a jam that won't clear.",
                    ["a high vantage over the gridlock below"],
                    ["nowhere to go but down", "exposed at height"],
                    ["height", "trapped", "vehicle_moving"], weight=2.0, severity=4),
        # --- bridge ---------------------------------------------------------
        TravelEvent("Trapped mid-span", (BRIDGE,), "any",
                    "Stuck halfway across the bridge as both ends choke -- water below, "
                    "gridlock fore and aft.",
                    "Push across on foot to the far bank, or fall back the way you came.",
                    ["only two ways off, both visible"],
                    ["a chokepoint everyone wants", "water on all sides"],
                    ["bridge", "trapped", "vehicle_moving"], weight=2.0, severity=4),
        # --- tunnel ---------------------------------------------------------
        TravelEvent("The tunnel goes dark", (TUNNEL,), "any",
                    "Deep in the tunnel the traffic stops, then the lights do. Engines, "
                    "then darkness.",
                    "Feel your way to a distant exit, or stay with the vehicle in the black.",
                    ["a hardened, enclosed space"],
                    ["no light", "no signal", "exhaust fumes", "both ends jamming"],
                    ["tunnel", "trapped", "isolation"], weight=2.0, severity=4),
        # --- on public transit ---------------------------------------------
        TravelEvent("Packed transit, stopped dead", (SURFACE, BRIDGE, TUNNEL, HIGHWAY),
                    "transit",
                    "Shoulder to shoulder on a bus that has stopped dead in the jam, the "
                    "doors hissing against the crowd.",
                    "Force the doors and join the street, or stay in the herd.",
                    ["a crowd to move with", "a raised, sealed cabin"],
                    ["crushed in a panicking crowd", "not your vehicle to drive"],
                    ["crowd", "trapped", "vehicle_moving"], weight=1.5, severity=3),
        # --- on foot / bike -------------------------------------------------
        TravelEvent("Faster than the jam", (SURFACE, RAMP, BRIDGE, HIGHWAY), "nonmotorized",
                    "The road seizes solid around you, but you're not in a car -- you can "
                    "still move.",
                    "Cut through the gridlock everyone else is trapped in, or get off the "
                    "road entirely.",
                    ["nimble and unboxed", "every gap is yours"],
                    ["exposed, carrying little"],
                    ["mobility", "exposed"], weight=2.0, severity=1),
    ]


def default_aerial_events() -> list[TravelEvent]:
    """Crash-from-above events: aircraft coming down on whoever is outdoors.

    Unlike road events these aren't tied to your vehicle or the segment you're on
    -- a jet doesn't care that you were walking.  They strike anyone caught in the
    open (commute or errand) with a small probability, layered over the normal
    situation; ``ALL`` structures so the selector never filters them out.
    """
    ALL = (SURFACE, HIGHWAY, BRIDGE, TUNNEL, RAMP)
    return [
        TravelEvent("A light aircraft clips the rooftops", ALL, "any",
                    "A small plane shears across the rooftops just above you, its engine dead.",
                    "Get indoors and off the street, or freeze and hope it carries past the block.",
                    ["a couple of seconds of warning from the silence"],
                    ["a shower of tile and glass", "spilled aviation fuel"],
                    ["aerial", "fire"], weight=1.6, severity=4),
        TravelEvent("A helicopter comes down", ALL, "any",
                    "A helicopter loses its tail rotor overhead and spirals into the street ahead.",
                    "Sprint clear of the rotor wash and the fire, or take cover behind something solid.",
                    ["the engine note warned you a beat early"],
                    ["whirling rotor debris", "burning fuel", "falling masonry"],
                    ["aerial", "fire", "trapped"], weight=1.0, severity=5),
        TravelEvent("An airliner comes down", ALL, "any",
                    "A wide-body crosses impossibly low and comes down across the blocks ahead in a wall of fire.",
                    "Run perpendicular to its path, or get something solid between you and the blast.",
                    ["the shadow gave you seconds"],
                    ["a wall of flame and debris", "collapsing buildings", "mass casualties"],
                    ["aerial", "fire", "mass_casualty"], weight=0.6, severity=5),
    ]


def select_aerial_event(rng: np.random.Generator,
                        events: list[TravelEvent] | None = None) -> TravelEvent:
    """Pick a crash-from-above event (weighted).  Deterministic given ``rng``."""
    if events is None:
        events = default_aerial_events()
    weights = np.array([e.weight for e in events], dtype=float)
    return events[int(rng.choice(len(events), p=weights / weights.sum()))]


def select_travel_event(rng: np.random.Generator, structure: str, vehicle: str,
                        events: list[TravelEvent] | None = None) -> TravelEvent:
    """Pick a travel event matching the road ``structure`` and ``vehicle`` class.

    Deterministic given ``rng``.  Falls back to gridlock (or, for a walker/cyclist,
    the on-foot event) if nothing else matches, so a situation is always returned.
    """
    from .vehicles import vehicle_class
    if events is None:
        events = default_travel_events()
    vclass = vehicle_class(vehicle) if vehicle else "motorized"

    def vehicle_ok(e: TravelEvent) -> bool:
        return e.vehicles == "any" or e.vehicles == vclass

    candidates = [e for e in events
                  if structure in e.structures and vehicle_ok(e)]
    if not candidates:
        # Structure had nothing for this vehicle class: fall back by class.
        candidates = [e for e in events if vehicle_ok(e)]
    if not candidates:
        candidates = events

    weights = np.array([e.weight for e in candidates], dtype=float)
    idx = int(rng.choice(len(candidates), p=weights / weights.sum()))
    return candidates[idx]

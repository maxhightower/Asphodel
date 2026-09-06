"""Smart Objects, rooms/zones, reservations and work execution
(ASPHODEL_SMART_OBJECTS_WORK_V1).

    building -> room/zone -> station -> smart object -> affordance -> action

* :mod:`.objects`      — SmartObject identity/kind/affordances/state, generated
                         deterministically from the canonical interior
                         descriptor (:mod:`asphodel.interiors`); zero
                         persistent bytes for the immutable part, persisted
                         deltas for mutable state.
* :mod:`.rooms`        — semantic zones over the interior rooms and the
                         doorway graph used for interior locomotion.
* :mod:`.reservations` — the one occupancy/reservation ledger.
* :mod:`.jobs`         — the job/task grammar and deterministic employment.
* :mod:`.runtime`      — WorkRuntime: executes tasks through objects for
                         citizens the TripExecutor has delivered into a
                         building; never plans city trips, never decides health.
"""
from .objects import SmartObject, Affordance, SmartObjectRegistry, OBJECT_KINDS
from .rooms import RoomGraph, zone_of_room_kind
from .reservations import ReservationLedger
from .jobs import JobRole, TaskDefinition, ROLES, employment_for, role_for_occupation
from .runtime import WorkRuntime, ActivityState

__all__ = ["SmartObject", "Affordance", "SmartObjectRegistry", "OBJECT_KINDS",
           "RoomGraph", "zone_of_room_kind", "ReservationLedger",
           "JobRole", "TaskDefinition", "ROLES", "employment_for", "role_for_occupation",
           "WorkRuntime", "ActivityState"]

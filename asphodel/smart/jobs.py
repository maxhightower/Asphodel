"""The job / task grammar and deterministic employment
(ASPHODEL_SMART_OBJECTS_WORK_V1 §5, §7).

A :class:`JobRole` is a list of :class:`TaskDefinition`, each naming the
affordance it needs, how the target object is chosen, its preconditions and
its duration. The WorkRuntime is a generic interpreter of this grammar; no
role has custom code. Three archetypes are certified:

* ``cashier``     — fixed exclusive station (a checkout), serves customers
                    who queue at it, takes a break on a seat, returns to a
                    valid available station (contention, substitution);
* ``desk_worker`` — selects a free workstation (cubicle/desk), long desk
                    tasks, a break;
* ``cleaner``     — dynamic target selection over many objects: fetch
                    supplies from storage, walk to the dirtiest object,
                    clean it (state change), pick the next one.

``stocker`` is available as a fourth data-driven role (retrieve goods from a
rack, carry them to a depleted shelf, restock) and used where a retail
workplace has enough workers.

Employment is a pure function of (world seed, citizen id, occupation, the
workplace's smart objects): the same citizen always gets the same role and
assigned station.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..world_source.detrand import hash64


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    affordance: str                 # affordance the target must offer
    selector: str                   # assigned | any_free | dirtiest | depleted | supplies | seat | wait_zone
    caps: Tuple[str, ...] = ()      # capabilities the target must have
    duration_s: Tuple[float, float] = (300.0, 900.0)   # min, max (deterministic per task instance)
    priority: float = 0.5
    interruptible: bool = True
    precondition: str = ""          # break_due | customer_waiting | has_supplies | needs_supplies | ""
    effect: str = ""                # served | documents | clean | restock | rest | supplies
    hold: str = "exclusive"         # exclusive | shared | none
    carry: str = ""                 # item carried after completion (goods, supplies)


@dataclass(frozen=True)
class JobRole:
    name: str
    workplace_zones: Tuple[str, ...]        # zones the role works in (first = idle zone)
    tasks: Tuple[TaskDefinition, ...]
    break_after_s: float = 2.5 * 3600.0     # continuous work before a break is due
    break_s: float = 15.0 * 60.0
    required_caps: Tuple[str, ...] = ()     # workplace must offer objects with these caps


ROLES: Dict[str, JobRole] = {
    "cashier": JobRole(
        "cashier", ("sales_floor", "employee_area", "break_room"),
        (TaskDefinition("take_break", "sit", "seat", ("seat",), (900.0, 900.0), 0.9, True,
                        "break_due", "rest"),
         TaskDefinition("serve_customer", "transact", "assigned", ("station", "transact"),
                        (60.0, 120.0), 0.85, True, "customer_waiting", "served"),
         TaskDefinition("man_register", "occupy_station", "assigned", ("station", "transact"),
                        (1800.0, 2400.0), 0.6, True, "", "staffed"),
         TaskDefinition("clean_station", "clean", "assigned", ("station", "transact"),
                        (120.0, 180.0), 0.4, True, "", "clean")),
        required_caps=("station", "transact")),
    "desk_worker": JobRole(
        "desk_worker", ("workspace", "office", "break_room", "meeting_room"),
        (TaskDefinition("take_break", "sit", "seat", ("seat",), (900.0, 900.0), 0.9, True,
                        "break_due", "rest"),
         TaskDefinition("desk_work", "desk_work", "any_free", ("station", "desk_work"),
                        (2700.0, 5400.0), 0.6, True, "", "documents"),
         TaskDefinition("tidy_desk", "clean", "any_free", ("station", "desk_work"),
                        (120.0, 180.0), 0.3, True, "", "clean")),
        required_caps=("station", "desk_work")),
    "cleaner": JobRole(
        "cleaner", ("employee_area", "stock_room", "storage", "hall", "workspace", "sales_floor"),
        (TaskDefinition("take_break", "sit", "seat", ("seat",), (900.0, 900.0), 0.9, True,
                        "break_due", "rest"),
         TaskDefinition("fetch_supplies", "use_storage", "supplies", ("storage",),
                        (60.0, 90.0), 0.8, True, "needs_supplies", "supplies", "exclusive", "supplies"),
         TaskDefinition("clean_object", "clean", "dirtiest", (), (90.0, 180.0), 0.7, True,
                        "has_supplies", "clean"),
         TaskDefinition("inspect", "browse", "any_free", ("shelf",), (120.0, 180.0), 0.2, True,
                        "", "", "shared")),
        required_caps=()),
    "stocker": JobRole(
        "stocker", ("stock_room", "sales_floor", "employee_area"),
        (TaskDefinition("take_break", "sit", "seat", ("seat",), (900.0, 900.0), 0.9, True,
                        "break_due", "rest"),
         TaskDefinition("fetch_goods", "retrieve_goods", "goods", ("storage", "goods"),
                        (120.0, 180.0), 0.8, True, "needs_goods", "goods", "shared", "goods"),
         TaskDefinition("restock_shelf", "restock", "depleted", ("shelf", "stock"),
                        (240.0, 300.0), 0.7, True, "has_goods", "restock", "shared"),
         TaskDefinition("face_shelf", "browse", "any_free", ("shelf",), (120.0, 180.0), 0.2, True,
                        "", "", "shared")),
        required_caps=("shelf", "stock")),
}

# Help tasks (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1 §12): what a coworker can
# do for another through the same grammar. They are not part of any role's
# pool; the cognition layer asks the WorkRuntime to run one (``assist``) once a
# citizen has decided to help. Targets are given, not selected.
HELP_TASKS: Dict[str, TaskDefinition] = {
    # take over a station's queue (the beneficiary's queue moves to it)
    "cover_station": TaskDefinition("cover_station", "transact", "given", ("station", "transact"),
                                    (1200.0, 1200.0), 0.95, True, "", "staffed"),
    # clean one object of a coworker's cleaning workload
    "help_clean": TaskDefinition("help_clean", "clean", "given", (), (90.0, 180.0), 0.95, True,
                                 "", "clean"),
    # restock one depleted shelf of a coworker's workload
    "help_restock": TaskDefinition("help_restock", "restock", "given", ("shelf", "stock"),
                                   (240.0, 300.0), 0.95, True, "", "restock", "shared"),
    # put a broken station back into service (maintenance through the object's clean affordance)
    "repair_station": TaskDefinition("repair_station", "clean", "given", ("station",),
                                     (300.0, 420.0), 0.95, True, "", "repair"),
}

# occupation -> preferred roles in order; the workplace's objects decide which applies
_OCCUPATION_ROLES: Dict[str, Tuple[str, ...]] = {
    "grocery_clerk": ("cashier", "stocker", "cleaner"),
    "barista": ("cashier", "cleaner"),
    "waiter": ("cashier", "cleaner"),
    "pharmacist": ("cashier", "desk_worker"),
    "office_worker": ("desk_worker", "cleaner"),
    "accountant": ("desk_worker", "cleaner"),
    "it_support": ("desk_worker", "cleaner"),
    "social_worker": ("desk_worker", "cleaner"),
    "teacher": ("desk_worker", "cleaner"),
    "student": ("desk_worker", "cleaner"),
    "cleaner": ("cleaner",),
    "landscaper": ("cleaner",),
    "window_washer": ("cleaner",),
    "sanitation_worker": ("cleaner",),
    "security_guard": ("cleaner", "desk_worker"),
    "warehouse_worker": ("stocker", "cleaner"),
    "factory_worker": ("stocker", "cleaner"),
    "mechanic": ("cleaner", "stocker"),
    "chef": ("cleaner", "cashier"),
    "nurse": ("cleaner", "desk_worker"),
    "doctor": ("desk_worker", "cleaner"),
    "care_worker": ("cleaner", "desk_worker"),
    "childcare_worker": ("cleaner", "desk_worker"),
}
_DEFAULT_ROLES = ("desk_worker", "cashier", "cleaner")


def role_for_occupation(occupation: str) -> Tuple[str, ...]:
    return _OCCUPATION_ROLES.get(str(occupation or ""), _DEFAULT_ROLES)


@dataclass
class Employment:
    citizen_id: int
    workplace_id: int
    role: str
    assigned_object: Optional[str]      # the station a cashier/desk worker is assigned to
    occupation: str

    def to_dict(self) -> dict:
        return {"citizen_id": self.citizen_id, "workplace_id": self.workplace_id,
                "role": self.role, "assigned_object": self.assigned_object,
                "occupation": self.occupation}


def employment_for(seed: int, cid: int, occupation: str, workplace_id: int, registry,
                   taken: Dict[str, int]) -> Optional[Employment]:
    """Deterministic role + assigned station for one citizen at one workplace.

    ``taken`` maps object ids already assigned (as fixed stations) to citizen
    ids; a citizen whose preferred stations are all assigned to others gets
    the next role that the workplace supports (a fourth clerk at a two-till
    shop stocks shelves). Pure: same inputs, same answer."""
    for role_name in role_for_occupation(occupation):
        role = ROLES[role_name]
        if role.required_caps and not registry.with_caps(*role.required_caps):
            continue
        assigned = None
        if role_name in ("cashier",):
            stations = [o for o in registry.with_caps("station", "transact") if o.object_id not in taken]
            if not stations:
                continue
            k = hash64(int(seed), int(cid), "station") % len(stations)
            assigned = stations[k].object_id
            taken[assigned] = int(cid)
        elif role_name == "desk_worker":
            stations = [o for o in registry.with_caps("station", "desk_work") if o.object_id not in taken]
            if stations:
                k = hash64(int(seed), int(cid), "station") % len(stations)
                assigned = stations[k].object_id
                taken[assigned] = int(cid)
            # no free desk at assignment time: the worker selects any free desk on the day
        return Employment(int(cid), int(workplace_id), role_name, assigned, str(occupation or ""))
    return None


def task_duration(seed: int, cid: int, task: TaskDefinition, instance: int) -> float:
    lo, hi = task.duration_s
    if hi <= lo:
        return float(lo)
    u = (hash64(int(seed), int(cid), f"task:{task.task_id}", int(instance)) % 10_000) / 10_000.0
    return float(lo + (hi - lo) * u)

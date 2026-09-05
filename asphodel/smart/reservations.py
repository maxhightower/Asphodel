"""The reservation / occupancy ledger (ASPHODEL_SMART_OBJECTS_WORK_V1 §10).

One ledger per world. Invariants it enforces:

* an exclusive object has at most one holder;
* a shared object has at most ``capacity`` holders;
* a citizen holds at most one exclusive object at a time (it cannot sit on
  two chairs) — a new exclusive hold releases the old one first;
* every hold is persisted with the world (save/load never forgets who is
  where) and released explicitly by the runtime that made it.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


class ReservationLedger:
    def __init__(self):
        self.holders: Dict[str, List[int]] = {}        # object_id -> [citizen ids]
        self.since: Dict[Tuple[str, int], float] = {}   # (object_id, cid) -> hold time
        self.exclusive_of: Dict[int, str] = {}          # cid -> exclusive object held

    # -- queries -----------------------------------------------------------------
    def holders_of(self, object_id: str) -> List[int]:
        return list(self.holders.get(object_id, []))

    def free_capacity(self, obj) -> int:
        return max(0, int(obj.capacity) - len(self.holders.get(obj.object_id, [])))

    def is_free(self, obj, exclusive: bool) -> bool:
        n = len(self.holders.get(obj.object_id, []))
        if exclusive or obj.exclusive:
            return n == 0
        return n < int(obj.capacity)

    def held_by(self, cid: int) -> List[str]:
        return sorted(oid for oid, hs in self.holders.items() if int(cid) in hs)

    # -- mutation ----------------------------------------------------------------
    def hold(self, obj, cid: int, now_s: float, exclusive: Optional[bool] = None) -> bool:
        """Take the object for ``cid``. Returns False (nothing changes) when the
        object is full or exclusively held by someone else."""
        cid = int(cid)
        excl = obj.exclusive if exclusive is None else bool(exclusive)
        hs = self.holders.setdefault(obj.object_id, [])
        if cid in hs:
            return True
        if excl and hs:
            return False
        if not excl and len(hs) >= int(obj.capacity):
            return False
        if excl:
            old = self.exclusive_of.get(cid)
            if old is not None and old != obj.object_id:
                self.release(cid, old)
            self.exclusive_of[cid] = obj.object_id
        hs.append(cid)
        self.since[(obj.object_id, cid)] = float(now_s)
        return True

    def release(self, cid: int, object_id: Optional[str] = None) -> List[str]:
        """Release one object (or every object) held by ``cid``."""
        cid = int(cid)
        out = []
        targets = [object_id] if object_id is not None else self.held_by(cid)
        for oid in targets:
            hs = self.holders.get(oid)
            if hs and cid in hs:
                hs.remove(cid)
                out.append(oid)
                self.since.pop((oid, cid), None)
                if not hs:
                    self.holders.pop(oid, None)
        if self.exclusive_of.get(cid) in out or object_id is None:
            self.exclusive_of.pop(cid, None)
        return out

    def release_object(self, object_id: str) -> List[int]:
        """Evict every holder of an object (it broke, it closed)."""
        hs = list(self.holders.get(object_id, []))
        for cid in hs:
            self.release(cid, object_id)
        return hs

    # -- persistence -------------------------------------------------------------
    def to_state(self) -> dict:
        return {"holders": {oid: list(hs) for oid, hs in sorted(self.holders.items()) if hs},
                "since": [[oid, cid, t] for (oid, cid), t in sorted(self.since.items())],
                "exclusive_of": {str(c): o for c, o in sorted(self.exclusive_of.items())}}

    @classmethod
    def from_state(cls, st: dict) -> "ReservationLedger":
        led = cls()
        for oid, hs in (st.get("holders") or {}).items():
            led.holders[oid] = [int(c) for c in hs]
        for oid, cid, t in (st.get("since") or []):
            led.since[(oid, int(cid))] = float(t)
        for c, o in (st.get("exclusive_of") or {}).items():
            led.exclusive_of[int(c)] = o
        return led

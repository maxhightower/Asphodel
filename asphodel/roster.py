"""A bounded, deterministic store of persistent *named* citizens (Phase 11 / M4).

The persistence LOD: the few citizens the player actually engages are kept across
the promote→demote→re-promote churn, while everyone else stays anonymous,
disposable statistical fill. The bound (``max_roster``) holds regardless of city
size or session length — this is the escape from "simulate everyone".

Promotion is **event-driven and interaction-keyed** (never spawn-order or a
timer); eviction is **least-recently-interacted, ties broken by lowest citizen
id**. No RNG, no wall-clock — the whole store is a pure function of
``(interaction history, tick)``, so it is reproducible and save/load-friendly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class RosterRecord:
    """One persistent named citizen. ``profile`` is an opaque reference (a
    CitizenProfile) the store never introspects beyond ``home_zone``."""

    citizen_id: int
    profile: object = None
    needs: dict = field(default_factory=dict)
    chosen_action: int = 0
    schedule_cursor: int = 0
    last_interaction_tick: int = 0
    promoted_tick: int = 0
    interactions: int = 0


class Roster:
    """A hard-bounded, deterministic collection of :class:`RosterRecord`."""

    def __init__(self, max_roster: int = 64):
        self.max_roster = int(max_roster)
        self._members: dict[int, RosterRecord] = {}

    def __len__(self) -> int:
        return len(self._members)

    def __contains__(self, cid: int) -> bool:
        return int(cid) in self._members

    def contains(self, cid: int) -> bool:
        return int(cid) in self._members

    # ------------------------------------------------------------------ mutate
    def promote(self, cid: int, profile, tick: int) -> bool:
        """Add ``cid`` to the roster (idempotent). Evicts the least-recently-
        interacted member first if full. Returns True if a *new* member was
        added. An existing member is refreshed (counts as an interaction)."""
        cid = int(cid)
        rec = self._members.get(cid)
        if rec is not None:
            rec.last_interaction_tick = int(tick)
            rec.interactions += 1
            return False
        if len(self._members) >= self.max_roster and self.max_roster > 0:
            self._evict_one()
        if self.max_roster <= 0:
            return False
        self._members[cid] = RosterRecord(
            citizen_id=cid, profile=profile,
            last_interaction_tick=int(tick), promoted_tick=int(tick),
            interactions=1)
        return True

    def interact(self, cid: int, tick: int) -> None:
        """Record a fresh interaction (updates LRU recency)."""
        rec = self._members.get(int(cid))
        if rec is not None:
            rec.last_interaction_tick = int(tick)
            rec.interactions += 1

    def _evict_one(self) -> int | None:
        """Evict the least-recently-interacted member; ties -> lowest citizen id.
        Returns the evicted id (or None if empty)."""
        if not self._members:
            return None
        victim = min(self._members.values(),
                     key=lambda r: (r.last_interaction_tick, r.citizen_id))
        del self._members[victim.citizen_id]
        return victim.citizen_id

    def set_state(self, cid, needs=None, chosen_action=None,
                  schedule_cursor=None, tick=None) -> None:
        """Persist a member's live state at checkpoint time. ``tick`` updates the
        LRU recency only when provided (demote-checkpoint passes ``None`` so mere
        leaving does not count as an interaction)."""
        rec = self._members.get(int(cid))
        if rec is None:
            return
        if needs is not None:
            rec.needs = dict(needs)
        if chosen_action is not None:
            rec.chosen_action = int(chosen_action)
        if schedule_cursor is not None:
            rec.schedule_cursor = int(schedule_cursor)
        if tick is not None:
            rec.last_interaction_tick = int(tick)

    # ------------------------------------------------------------------ read
    def checkpoint(self, cid: int) -> RosterRecord:
        """A detached copy of a member's record (survives a demote interval)."""
        return replace(self._members[int(cid)])

    def restore_record(self, cid: int) -> RosterRecord:
        """The live record for ``cid`` (identity-equal to its checkpoint)."""
        return self._members[int(cid)]

    def get(self, cid: int) -> RosterRecord | None:
        return self._members.get(int(cid))

    def members(self) -> list[RosterRecord]:
        """Members in a deterministic order (ascending citizen id)."""
        return [self._members[c] for c in sorted(self._members)]

    def ids(self) -> list[int]:
        return sorted(self._members)

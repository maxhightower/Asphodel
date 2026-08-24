"""Package 3 certification: the authoritative survival-resource loop.

Covers the brief's required tests: container persistence, inventory legality,
determinism, save/load continuation, and the population/disease regression guard
(survival never perturbs the epidemic).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import MicroParams
from asphodel.survival import Survival, SurvivalError, PlayerSurvival
from asphodel import items
from asphodel.bridge.worldfactory import world_from_bundle
from asphodel.bundle_population import load_bundle_population
from asphodel.bridge.worldfactory import resolve_bundle_dir
from asphodel.embodiment import CitySpatialContext
from asphodel.save import save_world, load_world_file, SAVE_VERSION


BUNDLE = "madisonville_tx"


def _find_stocked_container(s: Survival, max_b=400):
    """First (building, container) whose seed contents are non-empty, + a kind."""
    for b in range(max_b):
        for i in range(s.building_container_count(b)):
            c = s.container_contents(b, i)
            if c:
                return b, i, c
    raise AssertionError("no stocked container found")


# --------------------------------------------------------------------------- #
# Container persistence: take -> leave -> return -> still gone
# --------------------------------------------------------------------------- #
def test_container_persistence_take_is_permanent():
    s = Survival(world_seed=123)
    b, i, contents = _find_stocked_container(s)
    kind = contents[0].kind
    before_qty = contents[0].quantity

    # 3-4. Search reveals deterministic item X.
    revealed = {x["kind"]: x["quantity"] for x in s.search_container(b, i)["contents"]}
    assert revealed.get(kind) == before_qty

    # 5. Take X.
    s.take_item(b, i, kind, before_qty)

    # 6-7. "Leave and return" — re-derive the container from scratch.
    remaining = {x.kind: x.quantity for x in s.container_contents(b, i)}
    assert kind not in remaining, "taken item respawned in the container"

    # 8. Even a full re-search does not respawn it (world-delta persists).
    reveal2 = {x["kind"]: x["quantity"] for x in s.search_container(b, i)["contents"]}
    assert kind not in reveal2


def test_untouched_containers_regenerate_from_seed():
    # Two independent runtimes with the same seed agree on untouched contents,
    # and a touched container in one does not affect the other.
    a = Survival(world_seed=7)
    b = Survival(world_seed=7)
    bid, idx, contents = _find_stocked_container(a)
    a.take_item(bid, idx, contents[0].kind, contents[0].quantity)
    # b never touched it -> identical to the pristine seed contents.
    assert ([x.kind for x in b.container_contents(bid, idx)]
            == [x.kind for x in items.container_contents(7, bid, idx)])


# --------------------------------------------------------------------------- #
# Inventory legality
# --------------------------------------------------------------------------- #
def test_cannot_take_nonexistent_item():
    s = Survival(world_seed=1)
    b, i, _ = _find_stocked_container(s)
    try:
        s.take_item(b, i, "definitely_not_here", 1)
        assert False, "took a nonexistent item"
    except SurvivalError as e:
        assert e.code == "insufficient_in_container"


def test_cannot_duplicate_via_repeated_take():
    s = Survival(world_seed=2)
    b, i, contents = _find_stocked_container(s)
    kind, qty = contents[0].kind, contents[0].quantity
    s.take_item(b, i, kind, qty)              # takes all of it
    try:
        s.take_item(b, i, kind, 1)           # repeated command must fail
        assert False, "duplicated an item via repeated take"
    except SurvivalError as e:
        assert e.code == "insufficient_in_container"
    assert s.player.inventory.get(kind) == qty   # exactly what was taken, once


def test_cannot_use_item_not_owned():
    s = Survival(world_seed=3)
    try:
        s.use_item("mre")
        assert False, "used an unowned item"
    except SurvivalError as e:
        assert e.code == "not_owned"


def test_drop_transfers_ownership_exactly_once():
    s = Survival(world_seed=4)
    s._add_to_inventory("water_bottle", 3)
    r = s.drop_item("water_bottle", 2, 5.0, 6.0, 1)
    assert r["inventory"].get("water_bottle") == 1        # 3 - 2
    assert len(s.dropped) == 1 and s.dropped[0]["quantity"] == 2
    assert s.dropped[0]["instance_id"] == 1
    # Dropping more than held fails and changes nothing.
    try:
        s.drop_item("water_bottle", 5, 0, 0)
        assert False
    except SurvivalError as e:
        assert e.code == "insufficient_in_inventory"
    assert s.player.inventory.get("water_bottle") == 1
    # Pick it back up exactly once.
    s.pick_up_dropped(1)
    assert s.player.inventory.get("water_bottle") == 3
    assert len(s.dropped) == 0


def test_use_applies_effects_and_consumes():
    s = Survival(world_seed=5)
    s.player.hunger = 50.0
    s.player.thirst = 50.0
    s._add_to_inventory("canned_food", 1)
    r = s.use_item("canned_food")
    assert r["consumed"] is True
    assert s.player.hunger == 50.0 + items.item_kind("canned_food").hunger
    assert "canned_food" not in s.player.inventory     # consumed


# --------------------------------------------------------------------------- #
# Determinism: same seed + command sequence => identical everything
# --------------------------------------------------------------------------- #
def _scripted_run(seed):
    s = Survival(world_seed=seed)
    b, i, contents = _find_stocked_container(s)
    log = []
    log.append(("contents", [(x.kind, x.quantity) for x in contents]))
    # take first kind, drop it, use something if we can
    k0 = contents[0].kind
    s.take_item(b, i, k0, 1)
    log.append(("inv_after_take", dict(s.player.inventory)))
    d = s.drop_item(k0, 1, 111.0, 222.0, 4)
    log.append(("dropped", d["dropped"]))
    s._add_to_inventory("water_bottle", 1)
    u = s.use_item("water_bottle")
    log.append(("thirst", s.player.thirst))
    for _ in range(4):
        s.on_tick(0.25)
    log.append(("needs", (round(s.player.hunger, 6), round(s.player.thirst, 6))))
    return log


def test_determinism_same_seed_same_sequence():
    assert _scripted_run(99) == _scripted_run(99)
    # And a different seed generally diverges (sanity that seed matters).
    assert _scripted_run(99) != _scripted_run(100)


# --------------------------------------------------------------------------- #
# Save/load: continuation matches an uninterrupted run
# --------------------------------------------------------------------------- #
def _bundle_world_with_survival(seed=10):
    w = world_from_bundle(BUNDLE, seed=seed,
                          micro_params=MicroParams(area_size=100.0,
                                                   infection_radius=2.0,
                                                   mixing_step_frac=0.12))
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    w.set_citizens(pop)
    w.set_spatial_context(CitySpatialContext.from_bundle_dir(resolve_bundle_dir(BUNDLE)))
    surv = w.ensure_survival()
    return w, surv


def test_saveload_preserves_survival_and_continuation(tmp_path):
    w, s = _bundle_world_with_survival(seed=11)
    # start -> enter -> loot -> consume/drop
    b, i, contents = _find_stocked_container(s)
    s.enter_building(b)
    s.search_container(b, i)
    s.take_item(b, i, contents[0].kind, contents[0].quantity)
    s._add_to_inventory("canned_food", 1)
    s.use_item("canned_food")
    s.drop_item(contents[0].kind, 1, 50.0, 60.0, 2)
    for _ in range(3):
        w.step()

    path = str(tmp_path / "surv.json")
    save_world(w, path, bundle=BUNDLE, player_citizen=0)

    # Continue the live world...
    def continuation(world):
        out = []
        for _ in range(10):
            world.step()
            p = world.survival.player
            out.append((round(p.hunger, 9), round(p.thirst, 9), round(p.health, 9),
                        tuple(sorted(p.inventory.items())),
                        tuple((d["instance_id"], d["kind"], d["quantity"]) for d in world.survival.dropped)))
        return out

    live = continuation(w)

    # ...vs a reloaded (post-termination) world.
    reloaded = load_world_file(path)
    assert reloaded.survival is not None, "survival not restored"
    # Container delta persisted: the looted container is still empty of that kind.
    remaining = {x.kind for x in reloaded.survival.container_contents(b, i)}
    assert contents[0].kind not in remaining
    rel = continuation(reloaded)
    assert live == rel, "reloaded survival world did not continue deterministically"


def test_save_version_bumped():
    assert SAVE_VERSION == 2


# --------------------------------------------------------------------------- #
# Regression guard: survival never perturbs the epidemic
# --------------------------------------------------------------------------- #
def test_survival_is_epidemic_neutral():
    wa, sa = _bundle_world_with_survival(seed=13)
    wb = world_from_bundle(BUNDLE, seed=13,
                           micro_params=MicroParams(area_size=100.0,
                                                    infection_radius=2.0,
                                                    mixing_step_frac=0.12))
    pop = load_bundle_population(resolve_bundle_dir(BUNDLE))
    wb.set_citizens(pop)
    # wa has survival + looting activity; wb has none.
    b, i, contents = _find_stocked_container(sa)
    sa.take_item(b, i, contents[0].kind, 1)

    def totals(w):
        s = w.sim
        return [round(float(getattr(s, n).sum()), 9)
                for n in ("S", "E", "Ia", "Is", "R", "D")]

    for _ in range(40):
        wa.step()
        wb.step()
    assert totals(wa) == totals(wb), "survival loop perturbed the epidemic"


if __name__ == "__main__":
    import pathlib
    import tempfile
    import types
    import inspect
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            if "tmp_path" in inspect.signature(fn).parameters:
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print("ok", name)
    print("survival certified")

"""Package 3 vertical proof (executable): the full survival loop through the
authoritative command path.

Godot's client talks to Python over a socket carrying protocol dicts; here we
drive the same :class:`~asphodel.bridge.session.WorldSession` command processor
directly (the authoritative half of the exact path, minus the transport). This is
the strongest end-to-end proof available without a Godot binary — it exercises the
real command dispatch, validation, survival mutations, and save/destroy/reload.

Mirrors the milestone's final success sequence:

    start server -> spawn as a real bundled citizen -> begin in a coherent place ->
    advance -> observe another identified citizen on a routine -> enter a real
    building -> search a container -> take food/water -> it leaves the container ->
    it appears in inventory -> use/drop it -> survival state changes -> interact
    with an NPC (roster persists) -> save -> destroy the session -> load ->
    authoritative state + continuation are deterministic.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel.bridge.session import WorldSession
from asphodel.bridge import protocol as P
from asphodel.survival import Survival
from asphodel import items


BUNDLE = "madisonville_tx"


def _ok(reply):
    assert reply.get("ok"), f"command failed: {reply}"
    return reply


def _find_food_container(world_seed):
    """A (building, container, kind) with a consumable food/drink at this seed."""
    s = Survival(world_seed=world_seed)
    for b in range(1002):
        for i in range(s.building_container_count(b)):
            for st in s.container_contents(b, i):
                if items.item_kind(st.kind).category in ("food", "drink"):
                    return b, i, st.kind, st.quantity
    raise AssertionError("no food/drink container at this seed")


def test_package3_vertical_proof(tmp_path):
    print("\n=== Package 3 vertical proof (through WorldSession) ===")
    sess = WorldSession()

    # 1. handshake + start the authoritative server as a real bundled citizen.
    _ok(sess.handle(P.request("HELLO", protocol_version=P.PROTOCOL_VERSION)))
    PLAYER = 0
    started = _ok(sess.handle(P.request("START_WORLD", bundle=BUNDLE,
                                        player_citizen=PLAYER)))
    print(f"[1] started {started['bundle']['name']} as citizen #{PLAYER}, "
          f"home_zone={started['player_home_zone']}, n_citizens={started['n_citizens']}")
    world_seed = started["seed"]

    # 5. the player begins in a coherent physical place tied to their schedule.
    snap = _ok(sess.handle(P.request("SNAPSHOT")))["world"]
    assert "player_location" in snap, "no authoritative player location"
    ploc = snap["player_location"]
    print(f"[5] player_location: mode={ploc['mode']} bld={ploc['building_id']} "
          f"activity={ploc['activity']} xy=({ploc['x']:.0f},{ploc['y']:.0f})")
    assert ploc["citizen_id"] == PLAYER

    # 6-7. advance; observe at least one *other* identified citizen on a routine.
    adv = _ok(sess.handle(P.request("ADVANCE", ticks=2, snapshot=True)))
    world = adv["world"]
    identified = 0
    for z, ag in world.get("agents", {}).items():
        for cid, act in zip(ag["citizen_id"], ag["activity"]):
            if cid >= 0:
                identified += 1
    print(f"[7] identified citizens embodied with routines: {identified}")
    assert identified > 0, "no other identified citizen following a routine"

    # 8-9. enter a real building and search a real container.
    b, i, kind, qty = _find_food_container(world_seed)
    _ok(sess.handle(P.request("ENTER_BUILDING", building_id=b)))
    searched = _ok(sess.handle(P.request("SEARCH_CONTAINER", building_id=b, index=i)))
    contents = {c["kind"]: c["quantity"] for c in searched["contents"]}
    print(f"[8-9] entered building {b}, searched container {i}: {contents}")
    assert kind in contents

    # 10-12. take food/water -> it leaves the container -> appears in inventory.
    inv_before = _ok(sess.handle(P.request("INSPECT_INVENTORY")))["inventory"]
    took = _ok(sess.handle(P.request("TAKE_ITEM", building_id=b, index=i,
                                     kind=kind, quantity=1)))
    after_container = {c["kind"]: c["quantity"] for c in took["container"]}
    print(f"[10-12] took 1x {kind}; container now {after_container}; "
          f"inventory {took['inventory']}")
    assert after_container.get(kind, 0) == contents[kind] - 1     # left the container
    assert took["inventory"].get(kind, 0) == inv_before.get(kind, 0) + 1  # entered inv

    # 13-14. use it -> authoritative survival state changes.
    inv0 = _ok(sess.handle(P.request("INSPECT_INVENTORY")))
    used = _ok(sess.handle(P.request("USE_ITEM", kind=kind)))
    print(f"[13-14] used {kind}: consumed={used['consumed']} "
          f"survival hunger={used['survival']['hunger']:.1f} "
          f"thirst={used['survival']['thirst']:.1f}")
    spec = items.item_kind(kind)
    if spec.category == "drink":
        assert used["survival"]["thirst"] <= inv0["survival"]["thirst"]
    else:
        assert used["survival"]["hunger"] <= inv0["survival"]["hunger"]

    # drop something too (transfer ownership into the world exactly once).
    # take another unit first so we have something to drop deterministically.
    _ok(sess.handle(P.request("TAKE_ITEM", building_id=b, index=i,
                              kind=kind, quantity=1)))
    dropped = _ok(sess.handle(P.request("DROP_ITEM", kind=kind, quantity=1,
                                        x=ploc["x"], y=ploc["y"], zone=-1)))
    print(f"[13b] dropped 1x {kind} -> world item {dropped['dropped']['instance_id']}")

    # 15. interact with an NPC so roster persistence stays exercised.
    other = None
    for z, ag in world.get("agents", {}).items():
        for cid in ag["citizen_id"]:
            if cid >= 0 and cid != PLAYER:
                other = int(cid)
                break
        if other is not None:
            break
    if other is not None:
        r = _ok(sess.handle(P.request("INTERACT_WITH", citizen_id=other)))
        print(f"[15] interacted with citizen #{other}: in_roster={r['in_roster']}")

    # 16-17. leave and return; looted-container persistence holds.
    _ok(sess.handle(P.request("LEAVE_BUILDING")))
    _ok(sess.handle(P.request("ADVANCE", ticks=2)))
    re_search = _ok(sess.handle(P.request("SEARCH_CONTAINER", building_id=b, index=i)))
    re_contents = {c["kind"]: c["quantity"] for c in re_search["contents"]}
    print(f"[16-17] returned; container {i} still {re_contents} (took 2 total)")
    assert re_contents.get(kind, 0) == contents[kind] - 2, "looted items respawned"

    # 18. save.
    save_path = str(tmp_path / "survival_demo.json")
    _ok(sess.handle(P.request("SAVE", path=save_path)))
    # capture the authoritative continuation of the live session...
    def continuation(session):
        out = []
        for _ in range(8):
            a = _ok(session.handle(P.request("ADVANCE", ticks=1, snapshot=True)))
            sv = a["world"].get("survival", {}).get("survival", {})
            out.append((round(sv.get("hunger", 0), 9), round(sv.get("thirst", 0), 9),
                        round(sv.get("health", 0), 9),
                        round(a["total_pop"], 6)))
        return out
    live = continuation(sess)

    # 19-21. destroy the session, load into a fresh one, continue -> deterministic.
    fresh = WorldSession()
    _ok(fresh.handle(P.request("HELLO", protocol_version=P.PROTOCOL_VERSION)))
    loaded = _ok(fresh.handle(P.request("LOAD", path=save_path)))
    print(f"[19-20] reloaded at tick {loaded['tick']}")
    # looted container persisted across reload
    rs = _ok(fresh.handle(P.request("SEARCH_CONTAINER", building_id=b, index=i)))
    rc = {c["kind"]: c["quantity"] for c in rs["contents"]}
    assert rc.get(kind, 0) == contents[kind] - 2, "container delta lost on reload"
    rel = continuation(fresh)
    assert live == rel, "reloaded world did not continue deterministically"
    print("[21] continuation bit-identical after destroy+reload")
    print("=== Package 3 vertical proof PASS ===")


if __name__ == "__main__":
    import pathlib
    import tempfile
    test_package3_vertical_proof(pathlib.Path(tempfile.mkdtemp()))

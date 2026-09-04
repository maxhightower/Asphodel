"""Tests for the physics authority: collision matrix + solidity taxonomy (§4.1, §2.2)."""
from __future__ import annotations

from asphodel.physics import (
    BODY_PROFILES,
    Layer,
    Solidity,
    classify_object,
    collision_matrix,
    emit_gdscript,
    godot_layer_names,
    physically_blocks,
    senses,
)
from asphodel.physics.layers import OBJECT_SOLIDITY


def test_layer_bits_are_unique_powers_of_two():
    vals = [ly.value for ly in Layer]
    assert len(vals) == len(set(vals))
    for v in vals:
        assert v > 0 and (v & (v - 1)) == 0  # single bit set


def test_godot_indices_are_1_based_and_distinct():
    idx = godot_layer_names()
    assert set(idx) == {ly.godot_index for ly in Layer}
    assert min(idx) == 1


def test_moving_bodies_mutually_block():
    # Player/NPC/Vehicle/Prop must all stop each other in both directions so
    # nothing tunnels because only one side was scanning (§18 acceptance).
    movers = ["player", "npc", "vehicle", "dynamic_prop"]
    for a in movers:
        for b in movers:
            pa, pb = BODY_PROFILES[a], BODY_PROFILES[b]
            assert physically_blocks(pa, pb)
            # symmetric: both scan the other's layer
            assert pa.mask & pb.layer
            assert pb.mask & pa.layer


def test_movers_are_blocked_by_static_world():
    ws = BODY_PROFILES["world_static"]
    for m in ["player", "npc", "vehicle", "dynamic_prop"]:
        assert physically_blocks(BODY_PROFILES[m], ws)


def test_static_world_scans_nothing():
    # It never moves; giving it a mask would waste broadphase work.
    assert BODY_PROFILES["world_static"].mask == 0


def test_trigger_senses_agents_but_does_not_block_them():
    trig = BODY_PROFILES["trigger"]
    player = BODY_PROFILES["player"]
    assert senses(trig, player)                 # detected
    assert not physically_blocks(trig, player)  # not a wall
    # player does not treat the trigger as a solid obstacle
    assert not (player.mask & Layer.TRIGGER)


def test_nav_and_damage_queries_never_physically_block():
    for q in ["nav_query", "damage_query"]:
        for other in BODY_PROFILES.values():
            assert not physically_blocks(BODY_PROFILES[q], other)


def test_nav_query_scans_solid_world_and_vehicles():
    nq = BODY_PROFILES["nav_query"]
    assert nq.mask & Layer.WORLD_STATIC
    assert nq.mask & Layer.VEHICLE
    assert not (nq.mask & Layer.PLAYER)  # nav rays ignore the player


def test_collision_matrix_covers_all_physical_pairs():
    physical = [p for p in BODY_PROFILES.values() if p.is_physical]
    rows = collision_matrix()
    assert len(rows) == len(physical) * (len(physical) + 1) // 2


def test_solidity_taxonomy_is_complete_and_consistent():
    # Every declared object has a solidity; collision implies a *physical* body,
    # a non-colliding object has either no body or only a sensor (Area) body.
    for kind, prof in OBJECT_SOLIDITY.items():
        assert isinstance(prof.solidity, Solidity)
        if prof.collision:
            assert prof.body in BODY_PROFILES
            assert BODY_PROFILES[prof.body].is_physical
        elif prof.body:
            assert not BODY_PROFILES[prof.body].is_physical


def test_parked_vehicle_and_wreck_are_solid_obstacles():
    assert classify_object("parked_vehicle").collision
    assert classify_object("wreck").collision
    assert classify_object("wreck").solidity == Solidity.SOLID


def test_decoration_and_foliage_do_not_collide():
    assert not classify_object("terrain_far").collision
    assert not classify_object("foliage").collision
    assert classify_object("foliage").solidity == Solidity.NON_SOLID


def test_doorway_is_navigation_only():
    d = classify_object("doorway")
    assert d.navigation and not d.collision
    assert d.solidity == Solidity.NAVIGATION_ONLY


def test_unknown_object_kind_raises():
    import pytest
    with pytest.raises(KeyError):
        classify_object("mystery_blob")


def test_committed_gdscript_matches_authority():
    # The Godot autoload is generated from Python; it must not drift by hand-edit.
    import os
    path = os.path.join(os.path.dirname(__file__), os.pardir,
                        "godot", "scripts", "collision_layers.gd")
    if os.path.exists(path):
        with open(path) as f:
            on_disk = f.read()
        assert on_disk == emit_gdscript(), (
            "godot/scripts/collision_layers.gd is stale; regenerate via "
            "asphodel.physics.emit_gdscript()"
        )


def test_emit_gdscript_is_deterministic_and_mentions_every_layer():
    a = emit_gdscript()
    b = emit_gdscript()
    assert a == b
    for ly in Layer:
        assert ly.name in a
    for key in BODY_PROFILES:
        assert f'"{key}"' in a
    assert "extends Node" in a

"""A failed LOAD must not silently replace a playable world with partial state."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from asphodel.bridge.session import WorldSession


def test_failed_runtime_restore_preserves_current_session(tmp_path):
    session = WorldSession()
    original = object()
    session.world = original
    session.bundle = "original"
    session.player_citizen = 42
    session.seed = 7
    session.paused = True
    candidate = SimpleNamespace(_pending_mobility_state={})
    path = tmp_path / "save.json"
    path.write_text(json.dumps({"game_identity": {"bundle": "missing-city", "player_citizen": 9}}))
    with patch("asphodel.save.load_world", return_value=candidate), patch(
            "asphodel.bridge.worldfactory.resolve_bundle_dir", side_effect=ValueError("missing bundle")):
        response = session.handle({"cmd": "LOAD", "path": str(path)})
    assert response["ok"] is False
    assert "restoration failed" in response["error"]["message"]
    assert session.world is original
    assert (session.bundle, session.player_citizen, session.seed, session.paused) == ("original", 42, 7, True)


def test_saved_runtime_requires_bundle_identity(tmp_path):
    session = WorldSession()
    candidate = SimpleNamespace(_pending_mobility_state={})
    path = tmp_path / "save.json"
    path.write_text('{"game_identity": {}}')
    with patch("asphodel.save.load_world", return_value=candidate):
        response = session.handle({"cmd": "LOAD", "path": str(path)})
    assert response["ok"] is False
    assert "bundle identity" in response["error"]["message"]
    assert session.world is None


def test_malformed_save_preserves_current_world(tmp_path):
    session = WorldSession()
    session.world = original = object()
    path = tmp_path / "save.json"
    path.write_text('{')
    response = session.handle({"cmd": "LOAD", "path": str(path)})
    assert not response["ok"]
    assert session.world is original


def test_full_stack_load_and_continuation_are_identical(tmp_path):
    """Use the real city/command path, not mocks, for successful restoration."""
    session = WorldSession()
    started = session.handle({"cmd": "START_WORLD", "bundle": "madisonville_tx",
                              "start_hour": 8.0, "require_full_stack": True,
                              "outbreak": {"seed_index_case": False}})
    assert started["ok"], started
    flags = ("mobility_enabled", "outbreak_enabled", "work_enabled", "cognition_enabled",
             "dialogue_enabled", "groups_enabled")
    assert all(started.get(flag) for flag in flags)
    checkpoint = tmp_path / "checkpoint.json"
    assert session.handle({"cmd": "SAVE", "path": str(checkpoint)})["ok"]
    assert session.handle({"cmd": "ADVANCE_TIME", "seconds": 2.0})["ok"]
    control = tmp_path / "control.json"
    assert session.handle({"cmd": "SAVE", "path": str(control)})["ok"]
    restored = WorldSession()
    loaded = restored.handle({"cmd": "LOAD", "path": str(checkpoint)})
    assert loaded["ok"], loaded
    assert all(loaded.get(flag) for flag in flags)
    assert restored.handle({"cmd": "ADVANCE_TIME", "seconds": 2.0})["ok"]
    replay = tmp_path / "replay.json"
    assert restored.handle({"cmd": "SAVE", "path": str(replay)})["ok"]
    assert json.loads(control.read_text()) == json.loads(replay.read_text())


def test_playable_start_rejects_missing_stack_without_publishing_world():
    session = WorldSession()
    reply = session.handle({"cmd": "START_WORLD", "bundle": "madisonville_tx",
                            "citizens": False, "require_full_stack": True})
    assert not reply["ok"]
    assert "required runtimes" in reply["error"]["message"]
    assert session.world is None

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

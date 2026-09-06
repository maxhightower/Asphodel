"""Certification infrastructure must fail closed and clean up only owned children."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess

SPEC = importlib.util.spec_from_file_location("certifier", Path(__file__).resolve().parents[1] / "tools/certify_release.py")
certifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(certifier)


def test_script_error_is_failure_even_when_godot_exits_zero():
    assert not certifier.log_passes(0, "PASS something\nSCRIPT ERROR: invalid snapshot")
    assert not certifier.log_passes(0, "FAIL assertion")
    assert not certifier.log_passes(1, "PASS old result")
    assert certifier.log_passes(0, "PASS real result")


def test_finished_child_is_not_signalled():
    child = Mock()
    child.poll.return_value = 0
    certifier.stop_owned(child)
    child.terminate.assert_not_called()
    child.kill.assert_not_called()


def test_owned_child_is_reaped():
    child = Mock()
    child.poll.return_value = None
    certifier.stop_owned(child)
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=10)


def test_owned_unresponsive_child_is_killed_and_reaped():
    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [subprocess.TimeoutExpired("owned", 10), 0]
    certifier.stop_owned(child)
    child.kill.assert_called_once()
    assert child.wait.call_count == 2

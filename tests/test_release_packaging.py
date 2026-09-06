"""Dependency-free checks for release packaging failure modes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "release_builder", Path(__file__).resolve().parents[1] / "tools/build_windows_playable.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ReleasePackagingTests(unittest.TestCase):
    def test_missing_authority_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(builder.validate_authority(Path(tmp), "windows"))

    def test_wrong_platform_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "authority"
            root.mkdir()
            (root / "authority.exe").write_bytes(b"\x7fELF")
            (root / "SIM_SHA").write_text("test-sha")
            self.assertTrue(builder.validate_authority(Path(tmp), "windows"))

    def test_matching_platform_and_identity_required(self):
        for target, name, magic in (("windows", "authority.exe", b"MZ00"),
                                    ("linux", "authority", b"\x7fELF")):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "authority"
                root.mkdir()
                (root / name).write_bytes(magic)
                self.assertTrue(builder.validate_authority(Path(tmp), target))
                (root / "SIM_SHA").write_text(builder.source_sha())
                self.assertEqual(builder.validate_authority(Path(tmp), target), [])

    def test_stale_authority_stamp_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "authority"
            root.mkdir()
            (root / "authority.exe").write_bytes(b"MZ00")
            (root / "SIM_SHA").write_text("stale-sha")
            self.assertTrue(builder.validate_authority(Path(tmp), "windows"))

    def test_failed_export_cannot_pass_using_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "Asphodel.exe"
            output.write_bytes(b"old build")
            with patch.object(builder.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stdout="", stderr="export failed")):
                ok, _ = builder.run_export("godot", "Windows Desktop", output)
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Generate artifacts/windows_playable_v2/build_manifest.json.

Standalone (also called in-process by build_windows_playable.py). The manifest
is an honest, reproducible record of *what was actually built* on this host. On
a Linux/headless certification host the Windows-artifact fields are explicitly
``null`` with a ``blocked_reason``; on a Windows build host they are populated.

Fields:
  source_sha, godot_version, protocol_version, save_version,
  python (version + package/freeze method), cities, build_timestamp_utc,
  targets{windows,linux}: {status, dir, executable, executable_sha256, ...},
  authority: {method, status, executable, executable_sha256, blocked_reason},
  files: [{path, sha256, bytes}], archive: {path, sha256, bytes} | null.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
ARTIFACTS = REPO / "artifacts" / "windows_playable_v2"

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip()
    except Exception:
        return "unknown"


def godot_version() -> str | None:
    for exe in ("godot", "godot4", "Godot"):
        try:
            return subprocess.check_output(
                [exe, "--version"], text=True,
                stderr=subprocess.STDOUT).strip().splitlines()[-1]
        except Exception:
            continue
    return None


def read_int_const(rel: str, name: str) -> int | None:
    p = REPO / rel
    try:
        for line in p.read_text().splitlines():
            s = line.strip()
            if s.startswith(f"{name}") and "=" in s:
                return int(s.split("=", 1)[1].split("#")[0].strip())
    except Exception:
        pass
    return None


def _hash_dir_files(root: Path, files: list[dict], rel_to: Path) -> None:
    for dirpath, _dirs, names in os.walk(root):
        for n in sorted(names):
            fp = Path(dirpath) / n
            try:
                files.append({
                    "path": str(fp.relative_to(rel_to)),
                    "sha256": sha256_file(fp),
                    "bytes": fp.stat().st_size,
                })
            except OSError:
                continue


def build_manifest(cities: list[str],
                   authority_probe: dict | None = None,
                   archive: Path | None = None) -> dict:
    host = platform.system()
    is_windows_host = host == "Windows"

    win_dir = DIST / "asphodel-windows-v2"
    lin_dir = DIST / "asphodel-linux-v2"
    auth_dir = DIST / "authority"

    manifest: dict = {
        "schema": "asphodel.windows_playable.build_manifest/v2",
        "build_timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime()),
        "build_host_os": host,
        "source_sha": git_sha(),
        "godot_version": godot_version(),
        "protocol_version": read_int_const(
            "asphodel/bridge/protocol.py", "PROTOCOL_VERSION"),
        "save_version": read_int_const("asphodel/save.py", "SAVE_VERSION"),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "package_method": "pyinstaller-onedir-freeze",
        },
        "cities": cities,
        "targets": {},
        "authority": {},
        "files": [],
        "archive": None,
    }

    # ---- Windows target ----
    win_exe = win_dir / "Asphodel.exe"
    if win_exe.exists():
        manifest["targets"]["windows"] = {
            "status": "EXPORTED" if not is_windows_host else "OK",
            "dir": str(win_dir.relative_to(REPO)),
            "executable": str(win_exe.relative_to(REPO)),
            "executable_sha256": sha256_file(win_exe),
            "executable_bytes": win_exe.stat().st_size,
            "playable_certified": False if not is_windows_host else None,
            "blocked_reason": (
                None if is_windows_host else
                "Windows .exe was cross-exported on a non-Windows host; it "
                "cannot be launched or certified playable without a Windows "
                "host (no Wine here)."
            ),
        }
    else:
        manifest["targets"]["windows"] = {
            "status": "BLOCKED",
            "executable": None,
            "executable_sha256": None,
            "blocked_reason": "no Windows export present (template missing or "
                              "export not run).",
        }

    # ---- Linux proxy target ----
    lin_exe = lin_dir / "Asphodel.x86_64"
    if lin_exe.exists():
        manifest["targets"]["linux"] = {
            "status": "OK",
            "dir": str(lin_dir.relative_to(REPO)),
            "executable": str(lin_exe.relative_to(REPO)),
            "executable_sha256": sha256_file(lin_exe),
            "executable_bytes": lin_exe.stat().st_size,
            "note": "runnable proxy build (Linux); boots headless.",
        }
    else:
        manifest["targets"]["linux"] = {
            "status": "BLOCKED", "executable": None,
            "executable_sha256": None,
            "blocked_reason": "no Linux export present.",
        }

    # ---- Authority (frozen Python) ----
    auth_exe_lin = auth_dir / "authority"
    auth_exe_win = auth_dir / "authority.exe"
    auth_exe = auth_exe_win if auth_exe_win.exists() else auth_exe_lin
    if auth_exe.exists():
        served = None
        if authority_probe:
            served = bool(authority_probe.get("hello_ok"))
        manifest["authority"] = {
            "method": "pyinstaller-onedir",
            "status": "OK",
            "os": "windows" if auth_exe.name.endswith(".exe") else "linux",
            "dir": str(auth_dir.relative_to(REPO)),
            "executable": str(auth_exe.relative_to(REPO)),
            "executable_sha256": sha256_file(auth_exe),
            "served_hello": served,
            "blocked_reason": (
                None if auth_exe.name.endswith(".exe") else
                "This is the LINUX frozen authority (proof-of-approach). The "
                "shipped WINDOWS authority must be frozen on a Windows host "
                "with `python tools\\package_authority.py --target windows`."
            ),
        }
    else:
        manifest["authority"] = {
            "method": "pyinstaller-onedir",
            "status": "BLOCKED",
            "executable": None, "executable_sha256": None,
            "blocked_reason": "no frozen authority present; run "
                              "tools/package_authority.py.",
        }

    # ---- File list (hash every shipped file that exists) ----
    files: list[dict] = []
    for d in (win_dir, lin_dir, auth_dir):
        if d.exists():
            _hash_dir_files(d, files, REPO)
    manifest["files"] = files
    manifest["file_count"] = len(files)
    manifest["total_bytes"] = sum(f["bytes"] for f in files)

    # ---- Archive checksum ----
    if archive and archive.exists():
        manifest["archive"] = {
            "path": str(archive.relative_to(REPO)),
            "sha256": sha256_file(archive),
            "bytes": archive.stat().st_size,
        }

    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the V2 build manifest.")
    ap.add_argument("--cities", default=",".join(DEFAULT_CITIES),
                    help="comma-separated city ids included in the build")
    ap.add_argument("--archive", default=None,
                    help="path to the built zip, if any")
    ap.add_argument("--out", default=str(
        ARTIFACTS / "build_manifest.json"))
    args = ap.parse_args(argv)

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    probe_path = ARTIFACTS / "authority_freeze_probe.json"
    probe = None
    if probe_path.exists():
        try:
            probe = json.loads(probe_path.read_text())
        except Exception:
            probe = None
    archive = None
    if args.archive:
        ap_path = Path(args.archive)
        archive = ap_path if ap_path.is_absolute() else (REPO / ap_path)

    manifest = build_manifest(cities, authority_probe=probe, archive=archive)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2))
    print(f"[gen_build_manifest] wrote {out} "
          f"({manifest['file_count']} files, "
          f"{manifest['total_bytes']/1e6:.1f} MB hashed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

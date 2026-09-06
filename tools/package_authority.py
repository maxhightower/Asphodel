#!/usr/bin/env python3
"""Package the Asphodel Python simulation *authority* for shipping alongside
the Godot client.

WHY A FROZEN AUTHORITY
----------------------
The Windows player has no terminal and no system Python. The Godot client spawns
the authority as a child process (``authority_launcher.gd``), reads its
``{"event":"listening","port":N}`` line, and connects. So the authority must be a
self-contained, no-system-Python executable that resolves every ``asphodel``
import offline and carries its data files (e.g. city_visual/catalog_v1.yaml).

CHOSEN METHOD: PyInstaller **onedir** freeze of ``tools/authority_entry.py``
(which starts ``asphodel.bridge.server``). Onedir (not onefile) is deliberate:
it starts faster (no per-launch unpack to a temp dir), is trivially inspectable,
and plays well with antivirus. The freeze is the least-fragile method that needs
no runtime interpreter on the target.

LINUX vs WINDOWS (be honest)
----------------------------
PyInstaller freezes for the HOST OS only. On this Linux/headless host we build
and *prove* the LINUX authority (dist/authority/) actually launches and serves
HELLO. The IDENTICAL command on a Windows host produces the shipped Windows
authority; that step is BLOCKED here (documented, not faked).

    # Linux (runnable + proved here):
    python tools/package_authority.py --target linux
    # Windows (shipped; run on a Windows host with the same repo + pyinstaller):
    python tools\\package_authority.py --target windows

FALLBACK (documented, not chosen): if a freeze proves too heavy, ship an
"isolated runtime dir" instead — a bundled CPython + the asphodel source tree +
a launcher that runs ``<bundled_python> -m asphodel.bridge.server``. The freeze
is preferred and implemented; the fallback is described in
docs/windows/PLAYABLE_WINDOWS_README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENTRY = REPO / "tools" / "authority_entry.py"
DIST = REPO / "dist"
ARTIFACTS = REPO / "artifacts" / "windows_playable_v2"


def _host_target() -> str:
    return "windows" if platform.system() == "Windows" else "linux"


def _have_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
        return True
    except Exception:
        return False


def freeze(target: str, clean: bool = True) -> dict:
    """Run the PyInstaller onedir freeze for ``target``.

    Returns a status dict. If ``target`` is not the host OS, or PyInstaller is
    absent, returns a BLOCKED/SKIPPED status WITHOUT pretending to build.
    """
    host = _host_target()
    result: dict = {
        "target": target,
        "host": host,
        "method": "pyinstaller-onedir",
        "entry": str(ENTRY.relative_to(REPO)),
        "status": None,
        "dist_path": None,
        "blocked_reason": None,
    }

    if not _have_pyinstaller():
        result["status"] = "SKIPPED-blocked"
        result["blocked_reason"] = (
            "PyInstaller is not installed. `pip install pyinstaller` first."
        )
        return result

    if target != host:
        result["status"] = "SKIPPED-blocked"
        result["blocked_reason"] = (
            f"PyInstaller freezes for the host OS only (host={host}). A "
            f"'{target}' authority must be frozen on a {target} host with this "
            f"same command."
        )
        return result

    out_dir = DIST / "authority"
    work = DIST / "_authority_build"
    spec = DIST / "_authority_spec"
    for d in (out_dir, work, spec):
        if clean and d.exists():
            shutil.rmtree(d)
    out_dir.parent.mkdir(parents=True, exist_ok=True)

    # Data files the authority loads by path at runtime.
    sep = ";" if host == "windows" else ":"
    add_data = [
        (REPO / "asphodel" / "city_visual" / "catalog_v1.yaml",
         "asphodel/city_visual"),
        (REPO / "asphodel" / "city_visual" / "catalog_v1.json",
         "asphodel/city_visual"),
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir",
        "--name", "authority",
        "--console",
        "--distpath", str(out_dir.parent),
        "--workpath", str(work),
        "--specpath", str(spec),
        # asphodel uses only STATIC intra-package imports (verified: no
        # importlib/__import__ anywhere), so PyInstaller's dependency graph
        # traced from the entry captures every module the authority needs.
        # We deliberately do NOT --collect-submodules asphodel: that force-
        # imports unrelated leaf modules (osm_city/world_source pull requests
        # -> cryptography, which panics in some sandboxes) and bloats the
        # freeze with matplotlib/plotting code the authority never runs.
        # --collect-data only copies non-.py data files (no importing).
        "--collect-data", "asphodel",
        # keep the freeze lean and avoid dead-weight transitive deps. The
        # authority uses only CORE pandas (via asphodel.runner) and never the
        # optional pyarrow/DataFrame-styling/networking extras. Those extras
        # drag in urllib3 -> cryptography, whose Rust bindings panic under some
        # sandboxes at PyInstaller analysis time; excluding them is both leaner
        # and the fix for that crash. The authority never renders/plots/nets.
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "tkinter",
        "--exclude-module", "pyarrow",
        "--exclude-module", "cryptography",
        "--exclude-module", "urllib3",
        "--exclude-module", "requests",
        "--exclude-module", "IPython",
    ]
    for src, dest in add_data:
        if src.exists():
            cmd += ["--add-data", f"{src}{sep}{dest}"]
    cmd.append(str(ENTRY))

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    dt = time.time() - t0

    if proc.returncode != 0:
        result["status"] = "FAIL"
        result["blocked_reason"] = (
            "PyInstaller exited "
            f"{proc.returncode}. tail:\n" + proc.stderr[-1500:]
        )
        return result

    exe_name = "authority.exe" if host == "windows" else "authority"
    exe = out_dir / exe_name
    if not exe.exists():
        result["status"] = "FAIL"
        result["blocked_reason"] = f"freeze produced no {exe_name} in {out_dir}"
        return result

    result["status"] = "OK"
    # Stamp the binary at freeze time, not when an old freeze is later staged.
    try:
        sha = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                                      text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        result["status"] = "FAIL"
        result["blocked_reason"] = "cannot establish frozen authority source identity"
        return result
    (out_dir / "SIM_SHA").write_text(sha + "\n")
    result["dist_path"] = str(out_dir.relative_to(REPO))
    result["executable"] = str(exe.relative_to(REPO))
    result["build_seconds"] = round(dt, 1)
    return result


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_serves(exe: Path, timeout: float = 40.0) -> dict:
    """Launch the frozen authority, connect a raw socket, HELLO, verify ok,
    then shut it down. Returns a probe dict written to artifacts."""
    import socket

    probe: dict = {
        "executable": str(exe),
        "exists": exe.exists(),
        "launched": False,
        "listening_line": None,
        "port": None,
        "hello_ok": None,
        "hello_response": None,
        "shutdown_ok": None,
        "error": None,
        "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not exe.exists():
        probe["error"] = "executable missing"
        return probe

    proc = subprocess.Popen(
        [str(exe), "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        # Read the listening line (with a wall-clock deadline).
        deadline = time.time() + timeout
        line = None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if line:
                break
            if proc.poll() is not None:
                break
        probe["listening_line"] = (line or "").strip()
        if not line:
            probe["error"] = "no listening line (stderr tail): " + \
                (proc.stderr.read()[-800:] if proc.stderr else "")
            return probe
        info = json.loads(line)
        port = int(info["port"])
        probe["launched"] = True
        probe["port"] = port

        s = socket.create_connection(("127.0.0.1", port), timeout=10)
        s.sendall(b'{"cmd":"HELLO","protocol_version":9,"id":1}\n')
        raw = s.recv(65536).decode("utf-8").strip()
        probe["hello_response"] = raw
        resp = json.loads(raw)
        probe["hello_ok"] = bool(resp.get("ok")) and resp.get("cmd") == "HELLO" \
            and resp.get("protocol_version") == 9
        s.sendall(b'{"cmd":"SHUTDOWN","id":2}\n')
        try:
            bye = json.loads(s.recv(65536).decode("utf-8").strip())
            probe["shutdown_ok"] = bool(bye.get("ok"))
        except Exception:
            probe["shutdown_ok"] = False
        s.close()
    except Exception as e:  # noqa: BLE001
        probe["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return probe


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Freeze the Asphodel authority.")
    ap.add_argument("--target", choices=["windows", "linux"],
                    default=_host_target(),
                    help="OS to freeze for (default: host OS). Cross-OS is "
                         "reported blocked, never faked.")
    ap.add_argument("--no-probe", action="store_true",
                    help="skip the launch+HELLO serve probe")
    args = ap.parse_args(argv)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    print(f"[package_authority] target={args.target} host={_host_target()}")
    res = freeze(args.target)
    print(f"[package_authority] freeze status: {res['status']}")
    if res.get("blocked_reason"):
        print("  reason:", res["blocked_reason"])

    probe = None
    if res["status"] == "OK" and not args.no_probe:
        exe = REPO / res["executable"]
        res["executable_sha256"] = _sha256(exe)
        print(f"[package_authority] probing serve on {exe} ...")
        probe = probe_serves(exe)
        probe["freeze"] = res
        out = ARTIFACTS / "authority_freeze_probe.json"
        out.write_text(json.dumps(probe, indent=2))
        print(f"[package_authority] wrote {out.relative_to(REPO)}")
        ok = probe.get("hello_ok") and probe.get("launched")
        print(f"[package_authority] HELLO served: {ok} "
              f"(port={probe.get('port')})")
        return 0 if ok else 1
    else:
        # Still record the blocked/failed freeze as the probe artifact so the
        # manifest has an honest record.
        probe = {"freeze": res, "launched": False, "hello_ok": None,
                 "note": "freeze not OK on this host; see freeze.blocked_reason",
                 "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime())}
        out = ARTIFACTS / "authority_freeze_probe.json"
        out.write_text(json.dumps(probe, indent=2))
        print(f"[package_authority] wrote {out.relative_to(REPO)} "
              f"(status={res['status']})")
        return 0 if res["status"].startswith("SKIPPED") else 1


if __name__ == "__main__":
    raise SystemExit(main())

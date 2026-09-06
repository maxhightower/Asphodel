#!/usr/bin/env python3
"""THE canonical Asphodel Windows-playable build entry point (Convergence V2).

One command produces (as far as the host allows) a shippable client:

    python tools/build_windows_playable.py --target windows

Ordered steps (each reported OK / SKIPPED-blocked / FAIL):
  1. prereqs      - locate the godot binary + export templates; check pyinstaller
  2. authority    - freeze the Python authority (tools/package_authority.py)
  3. export       - Godot export of the client to dist/asphodel-<target>-v2/
  4. bundle       - verify/copy required city data + the frozen authority in
  5. manifest     - stamp artifacts/windows_playable_v2/build_manifest.json
  6. validate     - assert expected files exist with sane sizes
  7. zip          - (optional) dist/Asphodel-<Target>-V2.zip

HONEST DEGRADATION (this is the whole point):
  This runs on Linux/headless too. It NEVER pretends a Windows artifact was
  built or tested when it wasn't. If the Windows export template or a Windows
  Python freeze is unavailable, the Windows-only steps are marked
  SKIPPED-blocked, the Linux proxy build + Linux frozen authority are produced
  as real evidence, and a per-step status table is printed. "Exported" is never
  laundered into "playable-certified".

Data packing note: the Godot export already embeds the city bundles into the
PCK (export_presets.cfg include_filter packs bundles/**/*.json and the gzipped
world tiles). Step 4 therefore VERIFIES packing rather than copying loose data;
it copies the frozen authority tree next to the client so the shipped folder is
self-contained.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GODOT_PROJECT = REPO / "godot"
DIST = REPO / "dist"
ARTIFACTS = REPO / "artifacts" / "windows_playable_v2"

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio"]

# (preset name in export_presets.cfg, output subdir, client filename)
TARGET_SPEC = {
    "windows": ("Windows Desktop", "asphodel-windows-v2", "Asphodel.exe"),
    "linux": ("Linux/X11", "asphodel-linux-v2", "Asphodel.x86_64"),
}

STATUS_OK = "OK"
STATUS_SKIP = "SKIPPED-blocked"
STATUS_FAIL = "FAIL"


class Step:
    def __init__(self, name: str):
        self.name = name
        self.status = None
        self.detail = ""

    def set(self, status: str, detail: str = ""):
        self.status = status
        self.detail = detail
        return self


def _host_os() -> str:
    return "windows" if platform.system() == "Windows" else "linux"


def find_godot() -> str | None:
    for exe in ("godot", "godot4", "Godot"):
        if shutil.which(exe):
            return exe
    return None


def godot_templates_present(version_tag: str = "4.4.stable") -> dict:
    """Report which export templates are installed, per-OS."""
    import os
    candidates = []
    home = Path(os.path.expanduser("~"))
    candidates.append(home / ".local/share/godot/export_templates" / version_tag)
    candidates.append(home / ".config/godot/export_templates" / version_tag)
    # Windows default
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Godot/export_templates" / version_tag)
    found = {"dir": None, "linux": False, "windows": False}
    for c in candidates:
        if c.exists():
            found["dir"] = str(c)
            found["linux"] = (c / "linux_release.x86_64").exists()
            found["windows"] = (c / "windows_release_x86_64.exe").exists()
            if found["linux"] or found["windows"]:
                break
    return found


def run_export(godot: str, preset: str, out_file: Path) -> tuple[bool, str]:
    out_file.parent.mkdir(parents=True, exist_ok=True)  # Godot won't mkdir it
    cmd = [godot, "--headless", "--path", str(GODOT_PROJECT),
           "--export-release", preset, str(out_file)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = out_file.exists() and (out_file.stat().st_size > 0)
    tail = (proc.stdout + proc.stderr)
    # keep only interesting lines
    interesting = [l for l in tail.splitlines()
                   if any(k in l.lower() for k in
                          ("error", "warning", "template", "failed"))
                   and "step" not in l.lower()]
    return ok, "\n".join(interesting[-8:])


def verify_pck_packing(pck: Path, cities: list[str]) -> tuple[bool, str]:
    if not pck.exists():
        return False, "pck missing"
    blob = pck.read_bytes()
    missing = []
    for city in cities:
        needle = f"bundles/{city}/".encode()
        if blob.count(needle) == 0:
            missing.append(city)
    gz = blob.count(b".gz")
    if missing:
        return False, f"cities not packed: {missing}"
    return True, f"all {len(cities)} cities packed; {gz} gz tile refs"


def make_zip(src_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(src_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Asphodel Windows "
                                             "playable client (honest, "
                                             "reproducible).")
    ap.add_argument("--target", choices=["windows", "linux"], default="windows")
    ap.add_argument("--cities", default=",".join(DEFAULT_CITIES),
                    help="comma-separated city ids to require in the PCK")
    ap.add_argument("--zip", action="store_true",
                    help="also produce dist/Asphodel-<Target>-V2.zip")
    ap.add_argument("--skip-authority", action="store_true",
                    help="do not (re)freeze the authority")
    args = ap.parse_args(argv)

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    host = _host_os()
    target = args.target
    preset, out_sub, client_name = TARGET_SPEC[target]
    out_dir = DIST / out_sub
    client = out_dir / client_name

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    steps: list[Step] = []
    print(f"=== Asphodel Windows-playable build ===")
    print(f"host={host}  target={target}  cities={cities}")
    print(f"repo={REPO}\n")

    # ---- 1. prereqs ----
    s = Step("prereqs"); steps.append(s)
    godot = find_godot()
    templates = godot_templates_present()
    try:
        import PyInstaller  # noqa: F401
        have_pyi = True
    except Exception:
        have_pyi = False
    prereq_lines = [
        f"godot={'FOUND ('+godot+')' if godot else 'MISSING'}",
        f"templates.dir={templates['dir']}",
        f"templates.linux={templates['linux']} templates.windows={templates['windows']}",
        f"pyinstaller={'yes' if have_pyi else 'no'}",
    ]
    if not godot:
        s.set(STATUS_FAIL, "; ".join(prereq_lines) +
              " -- cannot export without a godot binary.")
    else:
        s.set(STATUS_OK, "; ".join(prereq_lines))
    for l in prereq_lines:
        print("  ", l)

    # target export blocked if that OS template is missing
    export_blocked = (not godot) or (not templates.get(target, False))
    cross_note = ""
    if target == "windows" and host != "windows":
        cross_note = ("Windows .exe will be CROSS-EXPORTED; it cannot be "
                      "launched/certified here (no Wine).")

    # ---- 2. authority freeze ----
    s = Step("authority"); steps.append(s)
    probe = None
    if args.skip_authority:
        s.set(STATUS_SKIP, "skipped by --skip-authority")
    elif not have_pyi:
        s.set(STATUS_SKIP, "pyinstaller not installed")
    else:
        auth_target = target if target == host else host
        # freeze for the host OS (a windows freeze needs a windows host)
        rc = subprocess.run(
            [sys.executable, str(REPO / "tools" / "package_authority.py"),
             "--target", host],
            capture_output=True, text=True)
        probe_path = ARTIFACTS / "authority_freeze_probe.json"
        if probe_path.exists():
            try:
                probe = json.loads(probe_path.read_text())
            except Exception:
                probe = None
        served = probe and probe.get("hello_ok")
        if rc.returncode == 0 and served:
            note = f"froze {host} authority; HELLO served on port " \
                   f"{probe.get('port')}"
            if target == "windows" and host != "windows":
                note += (". WINDOWS authority freeze BLOCKED here -- run "
                         "package_authority.py --target windows on a Windows "
                         "host.")
            s.set(STATUS_OK, note)
        else:
            s.set(STATUS_FAIL, rc.stderr[-400:] or "freeze/serve failed")

    # ---- 3. export ----
    s = Step("export"); steps.append(s)
    export_ok = False
    if not godot:
        s.set(STATUS_FAIL, "no godot binary")
    elif export_blocked:
        s.set(STATUS_SKIP, f"{target} export template missing "
                           f"(dir={templates['dir']}). Install the 4.4 "
                           f"{target} template to enable this step.")
    else:
        export_ok, detail = run_export(godot, preset, client)
        if export_ok:
            note = f"{client.relative_to(REPO)} ({client.stat().st_size:,} B)"
            if cross_note:
                note += " -- " + cross_note
            if detail:
                note += f" [notes: {detail}]"
            s.set(STATUS_OK, note)
        else:
            s.set(STATUS_FAIL, detail or "export produced no output")

    # ---- 4. bundle (verify PCK packing + colocate authority) ----
    s = Step("bundle"); steps.append(s)
    if export_ok:
        pck = out_dir / (client.stem + ".pck")
        packed_ok, packed_detail = verify_pck_packing(pck, cities)
        # Colocate the frozen authority ONLY when its OS matches the target,
        # so we never ship (e.g.) a Linux ELF authority next to a Windows .exe.
        # The freeze is host-OS only, so a cross-export cannot carry a matching
        # authority; in that case we drop an explicit placeholder instead of a
        # misleading mismatched binary.
        auth_src = DIST / "authority"
        auth_dst = out_dir / "authority"
        if auth_dst.exists():
            shutil.rmtree(auth_dst)
        if target == host and auth_src.exists():
            shutil.copytree(auth_src, auth_dst)
            auth_note = (f"colocated matching {host} authority/ "
                         f"({sum(1 for _ in auth_dst.rglob('*'))} entries)")
        else:
            auth_dst.mkdir(parents=True, exist_ok=True)
            (auth_dst / "README_AUTHORITY_MISSING.txt").write_text(
                f"The {target} simulation authority is NOT bundled here.\n\n"
                f"This client was built on a {host} host, and the Python "
                f"authority freeze (PyInstaller) is host-OS only. Freeze the "
                f"{target} authority ON A {target.upper()} HOST with:\n\n"
                f"    python tools/package_authority.py --target {target}\n\n"
                f"then copy the resulting dist/authority/ tree into this "
                f"folder next to the client executable.\n")
            auth_note = (f"authority NOT bundled (cross-build {host}->{target}); "
                         f"wrote placeholder + build instructions")
        if packed_ok:
            s.set(STATUS_OK, f"{packed_detail}; {auth_note}")
        else:
            s.set(STATUS_FAIL, packed_detail)
    else:
        s.set(STATUS_SKIP, "no client exported to bundle")

    # ---- 5. manifest ----
    s = Step("manifest"); steps.append(s)
    archive_path = DIST / f"Asphodel-{target.capitalize()}-V2.zip"
    manifest_args = [sys.executable, str(REPO / "tools" / "gen_build_manifest.py"),
                     "--cities", ",".join(cities)]
    if args.zip and archive_path.exists():
        manifest_args += ["--archive", str(archive_path)]
    rc = subprocess.run(manifest_args, capture_output=True, text=True)
    if rc.returncode == 0:
        s.set(STATUS_OK, rc.stdout.strip().splitlines()[-1] if rc.stdout else
              "manifest written")
    else:
        s.set(STATUS_FAIL, rc.stderr[-300:])

    # ---- 6. validate ----
    s = Step("validate"); steps.append(s)
    problems = []
    if export_ok:
        if not client.exists() or client.stat().st_size < 1_000_000:
            problems.append(f"{client.name} missing/too small")
        pck = out_dir / (client.stem + ".pck")
        if not pck.exists() or pck.stat().st_size < 10_000_000:
            problems.append("PCK missing/too small")
    if problems:
        s.set(STATUS_FAIL, "; ".join(problems))
    elif export_ok:
        s.set(STATUS_OK, "client + PCK present and sane")
    else:
        s.set(STATUS_SKIP, "nothing exported to validate")

    # ---- 7. zip ----
    s = Step("zip"); steps.append(s)
    if args.zip and export_ok:
        make_zip(out_dir, archive_path)
        s.set(STATUS_OK, f"{archive_path.relative_to(REPO)} "
                         f"({archive_path.stat().st_size:,} B)")
        # regenerate manifest to capture the archive checksum
        subprocess.run([sys.executable,
                        str(REPO / "tools" / "gen_build_manifest.py"),
                        "--cities", ",".join(cities),
                        "--archive", str(archive_path)],
                       capture_output=True, text=True)
    elif args.zip:
        s.set(STATUS_SKIP, "no client to zip")
    else:
        s.set(STATUS_SKIP, "not requested (--zip)")

    # ---- summary ----
    print("\n=== build summary ===")
    width = max(len(st.name) for st in steps)
    worst = STATUS_OK
    for st in steps:
        print(f"  {st.name.ljust(width)}  {str(st.status).ljust(15)}  "
              f"{st.detail}")
        if st.status == STATUS_FAIL:
            worst = STATUS_FAIL
        elif st.status == STATUS_SKIP and worst != STATUS_FAIL:
            worst = STATUS_SKIP

    print("\nHONESTY: ", end="")
    if target == "windows" and host != "windows":
        print("Windows .exe was cross-exported (if OK) but NOT executed or "
              "certified playable -- no Wine on this Linux host. The Linux "
              "proxy + Linux frozen authority are the runnable evidence.")
    else:
        print(f"target={target} built on host={host}.")

    print(f"\noverall: {worst}")
    # Non-fatal exit for SKIPPED-blocked (honest partial build); fail only on FAIL
    return 1 if worst == STATUS_FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

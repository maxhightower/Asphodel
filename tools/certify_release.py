#!/usr/bin/env python3
"""Sequential W48–W51 certification. Never kills a process it did not start.

Each run gets independent logs/traces and a source identity. A repository lock
rejects concurrent certification. Do not run screenshot jobs alongside this.
Missing tools and timeouts are failures, never inherited PASS results.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
SCENES = {"W48": ["OutbreakGate"], "W49": ["EmbodiedMobilityGate"],
          "W50": ["PhysicsGate", "RegionGate", "NavGate", "ConvergenceGate"]}


def stop_owned(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def log_passes(code, text):
    return code == 0 and "SCRIPT ERROR:" not in text and not any(
        line.startswith("FAIL") for line in text.splitlines())


def run_scene(godot, scene, out, timeout):
    server = None
    server_log = None
    trace = out / f"{scene}.json"
    command = [godot, "--headless", "--path", str(REPO / "godot"),
               f"res://tests/{scene}.tscn", "--", "--trace", str(trace),
               "--save", str(out / f"{scene}-save.json")]
    try:
        if scene in ("OutbreakGate", "EmbodiedMobilityGate"):
            path = out / f"{scene}-authority.log"
            server_log = path.open("w", encoding="utf-8")
            server = subprocess.Popen([sys.executable, "-u", "-m",
                "asphodel.bridge.server", "--host", "127.0.0.1", "--port", "0"],
                cwd=REPO, stdout=server_log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 30
            port = None
            while time.monotonic() < deadline and server.poll() is None:
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("event") == "listening":
                        port = event["port"]
                        break
                if port is not None:
                    break
                time.sleep(.1)
            if port is None:
                raise RuntimeError("owned authority did not announce readiness")
            command += ["--port", str(port)]
        logfile = out / f"{scene}.log"
        with logfile.open("w", encoding="utf-8") as stream:
            proc = subprocess.run(command, cwd=REPO, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=timeout)
        text = logfile.read_text(encoding="utf-8", errors="replace")
        passed = log_passes(proc.returncode, text) and "PASS" in text
        if scene in ("OutbreakGate", "EmbodiedMobilityGate"):
            passed = passed and trace.is_file()
        return {"scene": scene, "status": "PASS" if passed else "FAIL",
                "exit_code": proc.returncode, "log": str(logfile)}
    finally:
        stop_owned(server)
        if server_log:
            server_log.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", default=shutil.which("godot") or shutil.which("godot4"))
    parser.add_argument("--gates", default="W48,W49,W50,W51")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    gates = args.gates.split(",")
    if any(g not in (*SCENES, "W51") for g in gates):
        parser.error("unknown gate")
    out = (args.output or Path(tempfile.mkdtemp(prefix="asphodel-cert-"))).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = REPO / ".release-cert.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        parser.error("another certification owns .release-cert.lock; do not run concurrently")
    report = {"sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO,
                text=True).strip(), "dirty": bool(subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO)), "gates": []}
    try:
        os.close(fd)
        for gate in gates:
            print(f"START {gate} evidence={out}", flush=True)
            try:
                if gate == "W51":
                    with (out / "pytest.log").open("w") as stream:
                        result = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                            cwd=REPO, stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout)
                    row = {"status": "PASS" if result.returncode == 0 else "FAIL",
                           "exit_code": result.returncode}
                elif not args.godot:
                    row = {"status": "BLOCKED", "reason": "Godot executable unavailable"}
                else:
                    rows = [run_scene(args.godot, s, out, args.timeout) for s in SCENES[gate]]
                    row = {"status": "PASS" if all(r["status"] == "PASS" for r in rows) else "FAIL",
                           "scenes": rows}
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                row = {"status": "FAIL", "reason": str(exc)}
            row["gate"] = gate
            report["gates"].append(row)
            (out / "report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(row), flush=True)
    finally:
        lock.unlink()
    return 0 if all(r["status"] == "PASS" for r in report["gates"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

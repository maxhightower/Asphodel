#!/usr/bin/env python3
"""Execute the shipped client, isolated from the repo and Python PATH.

Checks four cities, cross-process deterministic snapshot continuation, and
missing/wrong-build authority failures. This is automated native evidence,
not a substitute for the manual desktop/visual acceptance checklist.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


def run_client(client, evidence, name, extra, env, timeout):
    trace = evidence / f"{name}.json"
    with (evidence / f"{name}.log").open("w") as log:
        result = subprocess.run([str(client), "--headless", "--", "--selftest-convergence",
            "--selftest-trace", str(trace), *extra], cwd=client.parent, env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if not trace.is_file():
        raise RuntimeError(f"{name}: client produced no trace (exit {result.returncode})")
    data = json.loads(trace.read_text())
    data["exit_code"] = result.returncode
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)
    evidence = args.output.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    host = platform.system()
    name = "Asphodel.exe" if host == "Windows" else "Asphodel.x86_64"
    report = {"platform": host, "native_windows": host == "Windows", "checks": []}
    try:
        with tempfile.TemporaryDirectory(prefix="Asphodel clean path ") as temp:
            destination = Path(temp) / "Game with spaces"
            shutil.copytree(args.package.resolve(), destination)
            client = destination / name
            with client.open("rb") as stream:
                report["client_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            report["source_sha"] = (destination / "SIM_SHA").read_text().strip()
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            env["PATH"] = (str(Path(env["SystemRoot"]) / "System32") if host == "Windows" else "/nonexistent")
            save = destination / "continuity.json"
            for city in ("houston", "madisonville_tx", "austin", "san_antonio"):
                extra = ["--selftest-bundle", city]
                if city == "houston":
                    extra += ["--selftest-save", str(save), "--selftest-state", str(destination / "before.json")]
                result = run_client(client, evidence, city, extra, env, args.timeout)
                report["checks"].append({"name": city, "pass": result.get("ok") is True and result["exit_code"] == 0})
                if city == "houston":
                    resumed = run_client(client, evidence, "reload", ["--selftest-load", str(save),
                        "--selftest-state", str(destination / "after.json")], env, args.timeout)
                    report["checks"].append({"name": "process_continuation", "pass":
                        result.get("ok") is True and resumed.get("ok") is True and resumed["exit_code"] == 0
                        and bool(result.get("world")) and result.get("world") == resumed.get("world")
                        and json.loads((destination / "before.json").read_text()) ==
                            json.loads((destination / "after.json").read_text())})
            stamp = destination / "SIM_SHA"
            original = stamp.read_text()
            stamp.write_text("wrong-build\n")
            wrong = run_client(client, evidence, "wrong-build", [], env, args.timeout)
            report["checks"].append({"name": "wrong_build_rejected", "pass":
                wrong.get("ok") is False and wrong["exit_code"] != 0})
            stamp.write_text(original)
            (destination / "authority").rename(destination / "authority-hidden")
            missing = run_client(client, evidence, "missing-authority", [], env, args.timeout)
            report["checks"].append({"name": "missing_authority_rejected", "pass":
                missing.get("ok") is False and missing["exit_code"] != 0})
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
    report["ok"] = "error" not in report and len(report["checks"]) == 7 and all(c["pass"] for c in report["checks"])
    (evidence / "packaged-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

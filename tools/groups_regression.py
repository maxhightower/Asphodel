#!/usr/bin/env python3
"""Aggregate the ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 regression suite into
artifacts/survivor_groups_v1/regression.json (mirrors artifacts/npc_dialogue_v1/
regression.json).

Runs, under xvfb, each live-bridge Godot gate and the headless Godot gate runner,
counts PASS / FAIL / INFO from each gate's own final RESULTS block (each check is
printed once while it runs and once in that block, so we count the block only),
and runs the full Python pytest suite, recording collected / passed / failed and
the failed test ids. The pre-existing Overture failure
(test_compile_writes_only_presentation_files) is the one acceptable failure,
exactly as the dialogue milestone recorded it.

    PYTHONPATH=. python3 tools/groups_regression.py [--skip-python] [--only gate ...]

Each gate can also be run on its own and merged with --merge.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "artifacts", "survivor_groups_v1")
ARTIFACT = os.path.join(ART, "regression.json")
LOGDIR = os.path.join(ART, "logs")

# gate key -> (G-number, command, kind)
GATES = {
    "groups_gate":    ("G46", ["bash", "tools/run_group_gate.sh"], "live"),
    "dialogue_gate":  ("G47", ["bash", "tools/run_dialogue_gate.sh"], "live"),
    "cognition_gate": ("G48", ["bash", "tools/run_cognition_gate.sh"], "live"),
    "work_gate":      ("G49", ["bash", "tools/run_work_gate.sh"], "live"),
    "outbreak_gate":  ("G50", ["bash", "tools/run_outbreak_gate.sh"], "live"),
    "mobility_gate":  ("G51", ["bash", "tools/run_mobility_gate.sh"], "live"),
    "run_gates":      ("G52", ["bash", "godot/tests/run_gates.sh"], "rungates"),
}


def _count_results_block(text: str) -> tuple:
    """Count PASS/FAIL/INFO in a gate's final RESULTS block only (checks are
    printed once live and once in the block; counting the block avoids the 2x)."""
    # the block starts at the last "==== ... RESULTS" line
    idx = text.rfind("RESULTS")
    tail = text[idx:] if idx >= 0 else text
    p = len(re.findall(r"(?m)^PASS\b", tail))
    f = len(re.findall(r"(?m)^FAIL\b", tail))
    i = len(re.findall(r"(?m)^INFO\b", tail))
    return p, f, i


def run_gate(key: str) -> dict:
    gnum, cmd, kind = GATES[key]
    os.makedirs(LOGDIR, exist_ok=True)
    log = os.path.join(LOGDIR, f"{key}.log")
    t0 = time.perf_counter()
    with open(log, "w") as f:
        proc = subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT)
    dt = round(time.perf_counter() - t0, 1)
    text = open(log, errors="replace").read()
    if kind == "rungates":
        # run_gates.sh runs 4 scenes; sum PASS/FAIL across them (each scene has
        # its own RESULTS block). Count every PASS/FAIL/INFO line once — the
        # runner echoes each check exactly once (grep of the scene log).
        p = len(re.findall(r"(?m)^PASS\b", text))
        f = len(re.findall(r"(?m)^FAIL\b", text))
        i = len(re.findall(r"(?m)^INFO\b", text))
        scenes = re.findall(r"running (tests/\w+\.tscn)", text)
        row = {"status": "PASS" if (proc.returncode == 0 and f == 0) else "FAIL",
               "pass": p, "fail": f, "info": i, "exited_nonzero": int(proc.returncode != 0),
               "scenes": scenes, "gate": gnum, "log": os.path.relpath(log, ART), "wall_s": dt}
        return row
    p, f, i = _count_results_block(text)
    row = {"status": "PASS" if (proc.returncode == 0 and f == 0) else "FAIL",
           "pass": p, "fail": f, "info": i, "exit": proc.returncode,
           "gate": gnum, "log": os.path.relpath(log, ART), "wall_s": dt}
    return row


def run_python() -> dict:
    os.makedirs(LOGDIR, exist_ok=True)
    log = os.path.join(LOGDIR, "python.log")
    cmd = ["python3", "-m", "pytest", "-q", "-rf", "--deselect", "tests/test_overture_ingest.py"]
    t0 = time.perf_counter()
    with open(log, "w") as f:
        proc = subprocess.run(cmd, cwd=REPO, stdout=f, stderr=subprocess.STDOUT,
                              env={**os.environ, "PYTHONPATH": REPO})
    dt = round(time.perf_counter() - t0, 1)
    text = open(log, errors="replace").read()
    m = re.search(r"(?m)^(?:=+\s*)?((?:\d+ \w+(?:, )?)+) in [\d.]+s", text)
    summary = m.group(0).strip("= ") if m else ""
    passed = int((re.search(r"(\d+) passed", text) or [0, 0])[1]) if "passed" in text else 0
    failed = int((re.search(r"(\d+) failed", text) or [0, 0])[1]) if "failed" in text else 0
    deselected = int((re.search(r"(\d+) deselected", text) or [0, 0])[1]) if "deselected" in text else 0
    xfailed = int((re.search(r"(\d+) xfailed", text) or [0, 0])[1]) if "xfailed" in text else 0
    failed_ids = re.findall(r"(?m)^FAILED (\S+)", text)
    collected = passed + failed
    OK_FAIL = "tests/test_world_from_compiled.py::test_compile_writes_only_presentation_files"
    only_ok = all(fid.split(" ")[0].startswith(OK_FAIL) or fid.startswith(OK_FAIL) for fid in failed_ids) if failed_ids else True
    status = "PASS" if (failed == 0 or (failed >= 1 and only_ok)) else "FAIL"
    return {"status": status, "collected": collected, "passed": passed, "failed": failed,
            "xfailed": xfailed, "deselected": deselected, "failed_tests": failed_ids,
            "summary_line": summary, "command": " ".join(cmd), "wall_s": dt,
            "log": os.path.relpath(log, ART),
            "note": ("The single acceptable failure is the pre-existing Overture one "
                     "(test_compile_writes_only_presentation_files needs the raw Overture packet; "
                     "tests/test_overture_ingest.py is deselected for the same reason), exactly as "
                     "artifacts/npc_dialogue_v1/regression.json records. Status PASS if that is the "
                     "only failure.")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="run only these keys (gate keys and/or 'python')")
    ap.add_argument("--skip-python", action="store_true")
    ap.add_argument("--merge", action="store_true", help="merge into an existing regression.json")
    args = ap.parse_args(argv)

    doc = {}
    if args.merge and os.path.exists(ARTIFACT):
        try:
            doc = json.load(open(ARTIFACT))
        except Exception:
            doc = {}

    def _flush():
        os.makedirs(ART, exist_ok=True)
        with open(ARTIFACT, "w") as f:
            json.dump(doc, f, indent=1)

    keys = args.only if args.only else (list(GATES.keys()) + ([] if args.skip_python else ["python"]))
    for key in keys:
        print(f"[groups_regression] running {key} ...", flush=True)
        if key == "python":
            doc["python"] = run_python()
            r = doc["python"]
            print(f"  python: {r['status']} ({r['passed']} passed, {r['failed']} failed)")
        else:
            doc[key] = run_gate(key)
            r = doc[key]
            print(f"  {key}: {r['status']} (pass {r['pass']}, fail {r['fail']}, info {r.get('info',0)})")
        _flush()   # incremental: a kill mid-suite preserves per-gate results (resume with --merge)

    doc["note"] = ("Regression for ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1. pass/fail/info per gate "
                   "are counted in that gate's final RESULTS block (each check is printed once while "
                   "it runs and once in that block). run_gates is godot/tests/run_gates.sh "
                   "(PhysicsGate, RegionGate, NavGate, ConvergenceGate) under xvfb; the live-bridge "
                   "gates and the new GroupGate run through their tools/run_*_gate.sh scripts. The "
                   "protocol handshake in the group gate expects v9 (this milestone bumped the "
                   "protocol to 9 for GET_GROUPS / GROUP_QUERY).")
    os.makedirs(ART, exist_ok=True)
    with open(ARTIFACT, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"\nwrote {ARTIFACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

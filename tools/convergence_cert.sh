#!/usr/bin/env bash
# Canonical convergence certification: everything a landing must pass, in one
# command. Python suite -> headless Godot suites -> live-bridge suites -> the
# multi-city matrix. Requires Godot 4.4 on PATH as `godot` (and `godot4` for
# the older live scripts), xvfb-run, and pytest.
#
#   tools/convergence_cert.sh            # full
#   SKIP_LIVE=1 tools/convergence_cert.sh # without the Python bridge scenes
set -u
cd "$(dirname "$0")/.."
R=0
step() { echo; echo "########## $1 ##########"; }

step "0. Godot import (class cache)"
godot --headless --path godot --import >/dev/null 2>&1 || true

step "1. Python suite"
python3 -m pytest -q -p no:cacheprovider 2>&1 | tail -3
[ "${PIPESTATUS[0]}" -ne 0 ] && R=1

step "2. Godot headless suites (no bridge)"
for sc in TestRunner StreetSmoke ExteriorStream CitizenHumanoidSmoke \
          IsometricExteriorSmoke IsometricCameraSmoke AssetCatalogSmoke \
          PhysicsGate RegionGate NavGate ConvergenceGate; do
  out=$(xvfb-run -a godot --headless --path godot "res://tests/$sc.tscn" 2>&1)
  code=$?
  line=$(echo "$out" | grep -E "done:|==== (PASS|FAIL)|SMOKE PASS|SMOKE FAIL" | tail -1)
  printf "%-26s exit=%d  %s\n" "$sc" "$code" "$line"
  [ $code -ne 0 ] && R=1
done

if [ "${SKIP_LIVE:-0}" != "1" ]; then
  step "3. Live bridge certification (tools/final_cert.sh)"
  bash tools/final_cert.sh 2>&1 | grep -E "exit=|done:|RESULT|BIT-IDENTICAL|BENCH|FAIL|FINAL_CERT_DONE"
fi

step "4. Multi-city matrix"
python3 tools/city_matrix.py 2>&1 | tail -4
[ "${PIPESTATUS[0]}" -ne 0 ] && R=1

step "CONVERGENCE_CERT: $([ $R -eq 0 ] && echo PASS || echo FAIL)"
exit $R

#!/usr/bin/env bash
# Headless proving-ground gates for Asphodel (§18/§20/§7 + the convergence gate).
# Requires a Godot 4.4 binary; pass its path as $GODOT or the first argument.
# Godot 3D physics runs on CPU under --headless, so these verify real in-engine
# behavior (no GPU needed).
#
# Run the project import ONCE first, so class_name lookups resolve:
#
#   godot --headless --path godot --import
#   GODOT=/path/to/Godot_v4.4-stable_linux.x86_64 ./godot/tests/run_gates.sh
#
# Exits non-zero if any gate fails.
set -uo pipefail
GODOT="${GODOT:-${1:-godot}}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # the godot/ project dir
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

fail=0
for scene in tests/PhysicsGate.tscn tests/RegionGate.tscn tests/NavGate.tscn \
		tests/ConvergenceGate.tscn; do
	echo "=== running $scene ==="
	# One run per gate. The exit code is the verdict, so it is captured BEFORE
	# any pipe — grep is only used to echo the result lines.
	"$GODOT" --headless --path "$HERE" "res://$scene" >"$LOG" 2>&1
	status=$?
	grep -E "^(PASS|FAIL|INFO)|====" "$LOG" || true
	if [ "$status" -ne 0 ]; then
		echo "!!! $scene exited $status"
		fail=1
	fi
done
exit $fail

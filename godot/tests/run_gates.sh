#!/usr/bin/env bash
# Headless proving-ground gates for Asphodel (§18/§20/§7). Requires a Godot 4.4
# binary; pass its path as $GODOT or the first argument. Godot 3D physics runs on
# CPU under --headless, so these verify real in-engine behavior (no GPU needed).
#
#   GODOT=/path/to/Godot_v4.4-stable_linux.x86_64 ./godot/tests/run_gates.sh
#
# Exits non-zero if any gate fails.
set -euo pipefail
GODOT="${GODOT:-${1:-godot}}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # the godot/ project dir

fail=0
for scene in tests/PhysicsGate.tscn tests/RegionGate.tscn tests/NavGate.tscn; do
	echo "=== running $scene ==="
	if ! "$GODOT" --headless --path "$HERE" "res://$scene" 2>&1 \
			| grep -E "PASS|FAIL|===="; then
		true
	fi
	# Re-run to capture the exit code (grep above consumes the pipe status).
	"$GODOT" --headless --path "$HERE" "res://$scene" >/dev/null 2>&1 || fail=1
done
exit $fail

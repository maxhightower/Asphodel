#!/usr/bin/env bash
# Playable Convergence Gate runner (Convergence V2). Unlike the other gates this
# does NOT pre-start a bridge server — the whole point is that the game's
# AuthorityLauncher auto-starts the authority. We only launch Godot headless; the
# gate spawns (and reaps) its own Python authority.
set -uo pipefail
cd "$(dirname "$0")/.."
BUNDLE="${1:-houston}"
TRACE="${2:-artifacts/windows_playable_v2/playable_convergence_trace.json}"
mkdir -p "$(dirname "$TRACE")"
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
echo "== Playable Convergence Gate: bundle=$BUNDLE (auto-start authority) =="
xvfb-run -a godot --headless --path godot res://tests/PlayableConvergenceGate.tscn -- \
    --bundle "$BUNDLE" --trace "$TRACE"
code=$?
echo "GATE_EXIT=$code"
exit $code

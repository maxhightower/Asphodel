#!/usr/bin/env bash
# ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2 in-engine gate for the developer/
# observer visibility layer (§19–§25). Start the live Python bridge, run the
# InspectorGate scene (the real IsometricWorld + real Godot) under xvfb, which
# boots a real world with mobility+cognition+dialogue+groups on, instantiates the
# SimulationInspector / BuildOverlay / EventFeed / FollowCamera nodes, drives their
# public refresh functions, and asserts each surface renders AUTHORITATIVE values
# (matching a direct GET_CITIZEN_CONTEXT / GET_GROUPS / GROUP_QUERY) and that the
# inspector mutates nothing. Then stop the bridge. Exit code = the gate's verdict.
#   tools/run_inspector_gate.sh [bundle] [player_citizen] [trace.json]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
PLAYER="${2:-82}"
TRACE="${3:-artifacts/windows_playable_v2/inspector_gate_trace.json}"
START_HOUR="${START_HOUR:-8.0}"
GAME_DT="${GAME_DT:-600.0}"
GODOT="${GODOT:-godot}"
mkdir -p "$(dirname "$TRACE")" /tmp/asph_livecert

# --- (1) live bridge --------------------------------------------------------
pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/inspector_gate_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done

# --- (2) the gate scene under xvfb / software GL ----------------------------
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/InspectorGate.tscn -- --bundle "$BUNDLE" --player "$PLAYER" \
    --start-hour "$START_HOUR" --trace "$(pwd)/$TRACE" --game-dt "$GAME_DT"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "GATE_EXIT=$CODE TRACE=$TRACE"
exit $CODE

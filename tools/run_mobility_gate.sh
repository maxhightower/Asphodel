#!/usr/bin/env bash
# ASPHODEL_EMBODIED_MOBILITY_V1 in-engine gate: start the live Python bridge,
# run the EmbodiedMobilityGate scene headless (real Godot physics, CPU), stop
# the bridge. Exit code = the gate's verdict.
#   tools/run_mobility_gate.sh [bundle] [citizen] [trace.json]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
CITIZEN="${2:-4}"
TRACE="${3:-artifacts/mobility/godot_probe_trace.json}"
GODOT="${GODOT:-godot}"
mkdir -p "$(dirname "$TRACE")" /tmp/asph_livecert
pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/mobility_gate_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done
"$GODOT" --headless --path godot res://tests/EmbodiedMobilityGate.tscn -- \
    --bundle "$BUNDLE" --citizen "$CITIZEN" --trace "$(pwd)/$TRACE"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "GATE_EXIT=$CODE TRACE=$TRACE"
exit $CODE

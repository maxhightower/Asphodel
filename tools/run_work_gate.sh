#!/usr/bin/env bash
# ASPHODEL_SMART_OBJECTS_WORK_V1 in-engine gate: start the live Python bridge,
# run the WorkGate scene (the real IsometricWorld scene + real Godot physics)
# under xvfb, stop the bridge. Exit code = the gate's verdict.
#   tools/run_work_gate.sh [bundle] [citizen] [building] [trace.json]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
CITIZEN="${2:-68}"
BUILDING="${3:-12013}"
TRACE="${4:-artifacts/smart_objects_work_v1/godot_probe_trace.json}"
GAME_DT="${GAME_DT:-1.0}"
GODOT="${GODOT:-godot}"
mkdir -p "$(dirname "$TRACE")" /tmp/asph_livecert
pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/work_gate_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/WorkGate.tscn -- --bundle "$BUNDLE" --citizen "$CITIZEN" \
    --building "$BUILDING" --trace "$(pwd)/$TRACE" --game-dt "$GAME_DT"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "GATE_EXIT=$CODE TRACE=$TRACE"
exit $CODE

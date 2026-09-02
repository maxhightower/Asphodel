#!/usr/bin/env bash
# Isometric live-certification orchestrator: start the authoritative Python bridge
# server, run a headless Godot isometric test scene against it, clean up.
#
# Usage: tools/run_iso_cert.sh <scene> [-- godot user args...]
#   e.g. tools/run_iso_cert.sh res://tests/IsometricLiveSmoke.tscn -- --bundle houston
#
# GODOT env var overrides the engine binary (default: godot on PATH).
set -u
cd "$(dirname "$0")/.."

SCENE="${1:-res://tests/IsometricLiveSmoke.tscn}"
shift || true
PORT="${PORT:-8765}"
GODOT="${GODOT:-godot}"

pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5

python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_iso_server.out 2>&1 &
SERVER_PID=$!
echo "server pid=$SERVER_PID port=$PORT"

for i in $(seq 1 150); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then
        echo "server is listening"
        break
    fi
    sleep 0.1
done

"$GODOT" --headless --path godot "$SCENE" -- "$@"
GODOT_CODE=$?
echo "godot exit=$GODOT_CODE"

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
echo "=== server log tail ==="
tail -5 /tmp/asph_iso_server.out 2>/dev/null || true
echo "ISO_LIVECERT_RESULT=$GODOT_CODE"
exit "$GODOT_CODE"

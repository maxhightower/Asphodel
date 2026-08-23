#!/usr/bin/env bash
# Live in-engine certification orchestrator: start the authoritative Python
# bridge server, run the headless Godot client against it, clean up.
#
# Usage: tools/run_live_cert.sh <scene> [-- godot user args...]
#   scene: res://tests/LiveSmoke.tscn (default)
set -u
cd "$(dirname "$0")/.."

SCENE="${1:-res://tests/LiveSmoke.tscn}"
shift || true
PORT="${PORT:-8765}"
SCRATCH="${SCRATCH:-/tmp/asph_livecert}"
mkdir -p "$SCRATCH"

pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5

python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > "$SCRATCH/server.out" 2>&1 &
SERVER_PID=$!
echo "server pid=$SERVER_PID port=$PORT"

# Wait for the port to accept connections (up to ~15s).
for i in $(seq 1 150); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then
        echo "server is listening"
        break
    fi
    sleep 0.1
done

xvfb-run -a godot4 --headless --path godot "$SCENE" -- "$@"
GODOT_CODE=$?
echo "godot exit=$GODOT_CODE"

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
echo "=== server log tail ==="
tail -5 "$SCRATCH/server.out" 2>/dev/null || true
echo "LIVECERT_RESULT=$GODOT_CODE"
exit "$GODOT_CODE"

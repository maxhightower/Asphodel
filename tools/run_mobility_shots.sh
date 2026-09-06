#!/usr/bin/env bash
# ASPHODEL_EMBODIED_MOBILITY_V1 visual evidence: the real IsometricWorld scene
# rendered under xvfb (software GL) with the live Python bridge, screenshots at
# every stage of one citizen's day.
#   tools/run_mobility_shots.sh [bundle] [citizen] [out_dir]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
CITIZEN="${2:-4}"
OUT="${3:-docs/mobility/evidence}"
GODOT="${GODOT:-godot}"
mkdir -p "$OUT" /tmp/asph_livecert
for p in $(pgrep -f "asphodel.bridge.serve[r]"); do kill "$p"; done
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/mobility_shots_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/EmbodiedMobilityShot.tscn -- --bundle "$BUNDLE" --citizen "$CITIZEN" --dir "$(pwd)/$OUT"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "SHOTS_EXIT=$CODE OUT=$OUT"
ls -l "$OUT" 2>/dev/null
exit $CODE

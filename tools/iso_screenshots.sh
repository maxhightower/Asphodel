#!/usr/bin/env bash
# Capture isometric visual evidence from the REAL renderer: start the Python
# bridge (so citizens/interiors are live), run the IsoScreenshot scene WITH
# rendering under xvfb + software OpenGL, save PNGs, clean up.
#
# Usage: tools/iso_screenshots.sh [bundle] [out_dir]
set -u
cd "$(dirname "$0")/.."

BUNDLE="${1:-houston}"
OUT="${2:-/tmp/asph_iso_shots}"
PORT="${PORT:-8765}"
GODOT="${GODOT:-godot}"
SCENE="${SCENE:-res://tests/IsoScreenshot.tscn}"
SCENE_ARGS="${SCENE_ARGS:---dir $OUT}"
mkdir -p "$OUT"

pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_iso_shot_server.out 2>&1 &
SERVER_PID=$!
for i in $(seq 1 150); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then
        echo "server listening"; break
    fi
    sleep 0.1
done

LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe xvfb-run -a \
    "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 \
    "$SCENE" -- --bundle "$BUNDLE" $SCENE_ARGS
CODE=$?

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
echo "shots exit=$CODE"
ls -la "$OUT" 2>/dev/null
exit "$CODE"

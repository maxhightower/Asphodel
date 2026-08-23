#!/usr/bin/env bash
# Capture a gameplay screenshot: start the live Python bridge, run the real
# StreetScene WITH rendering (opengl3, software mesa under xvfb), grab the viewport.
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
OUT="${2:-/tmp/asph_shot.png}"
EXTRA="${3:-}"           # e.g. --overhead
SCRATCH="/tmp/asph_livecert"; mkdir -p "$SCRATCH"

pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > "$SCRATCH/shot_server.out" 2>&1 &
SPID=$!
for i in $(seq 1 150); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done

xvfb-run -a -s "-screen 0 1280x720x24" godot4 --path godot \
    --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/Screenshot.tscn -- --bundle "$BUNDLE" --out "$OUT" $EXTRA
CODE=$?

kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "SHOT_EXIT=$CODE OUT=$OUT"
ls -l "$OUT" 2>/dev/null || echo "no output file"

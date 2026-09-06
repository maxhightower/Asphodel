#!/usr/bin/env bash
# ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1 visual evidence: the real IsometricWorld
# scene and the real DialoguePanel rendered under xvfb (software GL) with the
# live Python bridge, screenshots at every stage of the certified conversation day.
#   tools/run_dialogue_shots.sh [bundle] [player_citizen] [out_dir]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
PLAYER="${2:-82}"
OUT="${3:-docs/npc/evidence_dialogue}"
START_HOUR="${START_HOUR:-5.0}"
GODOT="${GODOT:-godot}"
mkdir -p "$OUT" /tmp/asph_livecert
for p in $(pgrep -f "asphodel.bridge.serve[r]"); do kill "$p"; done
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/dialogue_shots_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/DialogueShot.tscn -- --bundle "$BUNDLE" --player "$PLAYER" \
    --start-hour "$START_HOUR" --dir "$(pwd)/$OUT"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "SHOTS_EXIT=$CODE OUT=$OUT"
ls -l "$OUT" 2>/dev/null
exit $CODE

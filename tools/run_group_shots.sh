#!/usr/bin/env bash
# ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 visual evidence: build the deterministic
# survivor-group scenario with the Python pre-step (real cooperation -> emerged
# group, SAVEd), start the live Python bridge, run the GroupShot scene (the real
# IsometricWorld scene under xvfb / software GL) which boots the pre-formation
# world for frame 00 and then LOADs the saved world for the formed-group frames,
# saving a PNG + paired group snapshot for each stage of the certified group day.
#   tools/run_group_shots.sh [bundle] [player_citizen] [out_dir]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
PLAYER="${2:-82}"
OUT="${3:-docs/groups/evidence_groups}"
START_HOUR="${START_HOUR:-8.0}"
GODOT="${GODOT:-godot}"
SAVE="${SAVE:-/tmp/asph_group_save.json}"
SIDECAR="${SIDECAR:-/tmp/asph_group_scenario.json}"
mkdir -p "$OUT" /tmp/asph_livecert

# --- (0) deterministic pre-step: form the group and SAVE it (reuse if present) --
if [ ! -s "$SAVE" ] || [ ! -s "$SIDECAR" ] || [ -n "${REBUILD:-}" ]; then
    echo "[run_group_shots] building deterministic group scenario (pre-step)..."
    PYTHONPATH=. python3 tools/groups_build_scenario.py \
        --bundle "$BUNDLE" --start-hour "$START_HOUR" --save "$SAVE" --sidecar "$SIDECAR" \
        > /tmp/asph_livecert/group_shots_prestep.out 2>&1
    PRE=$?
    if [ "$PRE" -ne 0 ]; then
        echo "[run_group_shots] PRE-STEP FAILED (exit $PRE):"; tail -30 /tmp/asph_livecert/group_shots_prestep.out
        exit "$PRE"
    fi
    tail -2 /tmp/asph_livecert/group_shots_prestep.out
else
    echo "[run_group_shots] reusing existing scenario save $SAVE"
fi

# --- (1) live bridge --------------------------------------------------------
pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/group_shots_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done

# --- (2) the shot scene under xvfb / software GL ----------------------------
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/GroupShot.tscn -- --bundle "$BUNDLE" --player "$PLAYER" \
    --start-hour "$START_HOUR" --dir "$(pwd)/$OUT" --save "$SAVE" --sidecar "$SIDECAR"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "SHOTS_EXIT=$CODE OUT=$OUT"
ls -l "$OUT" 2>/dev/null
exit $CODE

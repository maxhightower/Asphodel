#!/usr/bin/env bash
# ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 in-engine gate: build the deterministic
# survivor-group scenario with a short Python pre-step (real cooperation ->
# emerged group, SAVEd), start the live Python bridge, run the GroupGate scene
# (the real IsometricWorld scene + real Godot physics) under xvfb which LOADs the
# save over the live bridge and observes/queries the group through GET_GROUPS /
# GROUP_QUERY, then stop the bridge. Exit code = the gate's verdict.
#   tools/run_group_gate.sh [bundle] [player_citizen] [trace.json]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
PLAYER="${2:-82}"
TRACE="${3:-artifacts/survivor_groups_v1/godot_probe_trace.json}"
START_HOUR="${START_HOUR:-8.0}"
GAME_DT="${GAME_DT:-1.0}"
GODOT="${GODOT:-godot}"
SAVE="${SAVE:-/tmp/asph_group_save.json}"
SIDECAR="${SIDECAR:-/tmp/asph_group_scenario.json}"
mkdir -p "$(dirname "$TRACE")" /tmp/asph_livecert

# --- (0) deterministic pre-step: form the group and SAVE it ------------------
echo "[run_group_gate] building deterministic group scenario (pre-step)..."
PYTHONPATH=. python3 tools/groups_build_scenario.py \
    --bundle "$BUNDLE" --start-hour "$START_HOUR" --save "$SAVE" --sidecar "$SIDECAR" \
    > /tmp/asph_livecert/group_gate_prestep.out 2>&1
PRE=$?
if [ "$PRE" -ne 0 ]; then
    echo "[run_group_gate] PRE-STEP FAILED (exit $PRE):"
    tail -30 /tmp/asph_livecert/group_gate_prestep.out
    exit "$PRE"
fi
tail -2 /tmp/asph_livecert/group_gate_prestep.out

# --- (1) live bridge --------------------------------------------------------
pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/group_gate_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done

# --- (2) the gate scene under xvfb / software GL ----------------------------
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/GroupGate.tscn -- --bundle "$BUNDLE" --player "$PLAYER" \
    --start-hour "$START_HOUR" --trace "$(pwd)/$TRACE" --game-dt "$GAME_DT" \
    --save "$SAVE" --sidecar "$SIDECAR"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
echo "GATE_EXIT=$CODE TRACE=$TRACE"
exit $CODE

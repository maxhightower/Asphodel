#!/usr/bin/env bash
# ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2 visual evidence (§40): render the REAL
# canonical IsometricWorld playable against the live Python authority under xvfb /
# software GL and save a PNG + paired authoritative bridge data for each converged
# system moment. Mirrors tools/run_group_shots.sh: it builds+SAVEs the deterministic
# survivor group with the Python pre-step (for the group-shelter frame), starts the
# live bridge server, runs the shots scene (the real scene brings up its OWN owned
# authority through AuthorityLauncher and START_WORLDs the full certified stack),
# then tears everything down.
#   tools/run_playable_shots.sh [bundle] [player_citizen] [out_dir]
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
BUNDLE="${1:-houston}"
PLAYER="${2:-82}"
OUT="${3:-docs/windows/evidence_windows}"
START_HOUR="${START_HOUR:-8.0}"
GODOT="${GODOT:-godot}"
SAVE="${SAVE:-/tmp/asph_playable_save.json}"
GROUP_SAVE="${GROUP_SAVE:-/tmp/asph_group_save.json}"
GROUP_SIDECAR="${GROUP_SIDECAR:-/tmp/asph_group_scenario.json}"
mkdir -p "$OUT" /tmp/asph_livecert

# --- (0) deterministic group pre-step: form the group and SAVE it (reuse if present) --
if [ ! -s "$GROUP_SAVE" ] || [ ! -s "$GROUP_SIDECAR" ] || [ -n "${REBUILD:-}" ]; then
    echo "[run_playable_shots] building deterministic group scenario (pre-step)..."
    PYTHONPATH=. python3 tools/groups_build_scenario.py \
        --bundle "$BUNDLE" --start-hour "$START_HOUR" --save "$GROUP_SAVE" --sidecar "$GROUP_SIDECAR" \
        > /tmp/asph_livecert/playable_shots_prestep.out 2>&1
    PRE=$?
    if [ "$PRE" -ne 0 ]; then
        echo "[run_playable_shots] PRE-STEP FAILED (exit $PRE) — the group-shelter frame will fall back to authority-rows-only:"
        tail -20 /tmp/asph_livecert/playable_shots_prestep.out
    else
        tail -2 /tmp/asph_livecert/playable_shots_prestep.out
    fi
else
    echo "[run_playable_shots] reusing existing group scenario save $GROUP_SAVE"
fi

# --- (1) live bridge (mirrors run_group_shots.sh) ---------------------------
pkill -f "asphodel.bridge.server" 2>/dev/null || true
sleep 0.5
PYTHONPATH=. python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
    > /tmp/asph_livecert/playable_shots_server.out 2>&1 &
SPID=$!
for i in $(seq 1 300); do
    if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
    sleep 0.1
done

# --- (2) the shot scene under xvfb / software GL ----------------------------
xvfb-run -a -s "-screen 0 1280x720x24" env LIBGL_ALWAYS_SOFTWARE=1 "$GODOT" --path godot \
    --rendering-method gl_compatibility --rendering-driver opengl3 --resolution 1280x720 \
    res://tests/PlayableShots.tscn -- --bundle "$BUNDLE" --player "$PLAYER" \
    --start-hour "$START_HOUR" --dir "$(pwd)/$OUT" --save "$SAVE" \
    --group-save "$GROUP_SAVE" --group-sidecar "$GROUP_SIDECAR"
CODE=$?
kill "$SPID" 2>/dev/null || true
wait "$SPID" 2>/dev/null || true
pkill -f "asphodel.bridge.server" 2>/dev/null || true
echo "SHOTS_EXIT=$CODE OUT=$OUT"
ls -l "$OUT" 2>/dev/null
exit $CODE

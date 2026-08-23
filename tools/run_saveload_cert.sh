#!/usr/bin/env bash
# BW7: deterministic save/destroy/reload through the real client path, with the
# Python server PROCESS DESTROYED between the reference run and the reload run.
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8765}"
SCRATCH="${SCRATCH:-/tmp/asph_livecert}"
mkdir -p "$SCRATCH"
rm -f /tmp/asph_ckpt.json /tmp/asph_reference.json /tmp/asph_continued.json

run_phase() {
    local phase="$1"
    pkill -f "asphodel.bridge.server" 2>/dev/null || true
    sleep 0.5
    python3 -m asphodel.bridge.server --host 127.0.0.1 --port "$PORT" \
        > "$SCRATCH/server_$phase.out" 2>&1 &
    local pid=$!
    for i in $(seq 1 150); do
        if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)"; then break; fi
        sleep 0.1
    done
    echo "--- phase=$phase (server pid=$pid) ---"
    xvfb-run -a godot4 --headless --path godot res://tests/LiveSaveLoad.tscn -- --phase "$phase"
    local code=$?
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    echo "phase=$phase godot exit=$code (server process destroyed)"
    return $code
}

run_phase save || { echo "SAVELOAD_RESULT=1"; exit 1; }
run_phase load || { echo "SAVELOAD_RESULT=1"; exit 1; }

# Compare the uninterrupted reference vs the reload-continued state, bit-for-bit.
python3 - <<'PY'
import json, sys
ref = json.load(open("/tmp/asph_reference.json"))
cont = json.load(open("/tmp/asph_continued.json"))
def strip(d):
    d = dict(d); d.pop("game_identity", None); return d
same = strip(ref) == strip(cont)
print("reference tick:", ref["sim"]["scalars"]["tick"],
      "continued tick:", cont["sim"]["scalars"]["tick"])
print("BIT-IDENTICAL after process destruction:", same)
if not same:
    # locate the first differing section for diagnostics
    for k in ("sim", "promoted", "roster", "world"):
        if strip(ref).get(k) != strip(cont).get(k):
            print("  section differs:", k)
sys.exit(0 if same else 2)
PY
CMP=$?
echo "SAVELOAD_RESULT=$CMP"
exit $CMP

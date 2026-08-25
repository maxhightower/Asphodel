#!/usr/bin/env bash
# Consolidated in-engine certification record for the Bundle-Wired Living City.
set -u
cd "$(dirname "$0")/.."
R=0
echo "########## 1. Godot TestRunner ##########"
xvfb-run -a godot4 --headless --path godot res://tests/TestRunner.tscn 2>&1 | grep -E "done:|FAIL"
xvfb-run -a godot4 --headless --path godot res://tests/TestRunner.tscn >/dev/null 2>&1; echo "TestRunner exit=$?"; [ $? -ne 0 ] && R=1
echo "########## 2. Godot StreetSmoke ##########"
xvfb-run -a godot4 --headless --path godot res://tests/StreetSmoke.tscn 2>&1 | grep -E "done:|FAIL"
echo "########## 3. Live cert (BW2-6) ##########"
bash tools/run_live_cert.sh res://tests/LiveSmoke.tscn -- --bundle houston --player 5 2>&1 | grep -E "cert done:|LIVECERT_RESULT|FAIL"
echo "########## 4. Save/destroy/reload (BW7) ##########"
bash tools/run_saveload_cert.sh 2>&1 | grep -E "BIT-IDENTICAL|SAVELOAD_RESULT"
echo "########## 4b. Survival-resource loop in-engine (P3) ##########"
bash tools/run_live_cert.sh res://tests/LiveSurvival.tscn -- --bundle houston --player 5 2>&1 | grep -E "survival cert done:|LIVECERT_RESULT|FAIL"
echo "########## 4c. Walk-in interiors: builder + fixtures + occupancy ##########"
bash tools/run_live_cert.sh res://tests/LiveInterior.tscn -- --bundle houston --player 5 2>&1 | grep -E "interior cert done:|LIVECERT_RESULT|FAIL"
echo "########## 4d. Walk-in interiors: enter/leave streaming ##########"
bash tools/run_live_cert.sh res://tests/LiveWalkIn.tscn -- --bundle houston --player 5 2>&1 | grep -E "walk-in cert done:|LIVECERT_RESULT|FAIL"
echo "########## 4e. Walk-in interiors: 30-step vertical ##########"
bash tools/run_live_cert.sh res://tests/LiveVertical.tscn -- --bundle houston --player 5 2>&1 | grep -E "live vertical done:|LIVECERT_RESULT|FAIL"
echo "########## 4f. Interior builder benchmark ##########"
bash tools/run_live_cert.sh res://tests/InteriorBench.tscn -- --bundle houston 2>&1 | grep -E "INTERIOR_BENCH"
echo "########## 5. Render+IPC benchmark (BW9) ##########"
bash tools/run_live_cert.sh res://tests/LiveBench.tscn -- --bundle houston 2>&1 | grep -E "BENCH"
bash tools/run_live_cert.sh res://tests/LiveBench.tscn -- --bundle madisonville_tx 2>&1 | grep -E "BENCH"
echo "########## FINAL_CERT_DONE ##########"

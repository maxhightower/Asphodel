# Godot gameplay-integrity tests

Two headless harnesses certify the first-person client's contracts. Both run as
**scenes** (not `--script`) so the `Session` / `GameClock` autoloads are loaded —
`--script` mode does not register autoloads. Requires Godot 4.4+.

## 1. Pure-logic + menu-flow checks (`TestRunner.tscn` → `run_tests.gd`)

Bundle validation, `GameClock` time / outbreak / pause logic, and that every
pre-StreetScene flow scene (MainMenu → CitySelect → CharacterScreen, plus
Settings) instances and builds its UI on `_ready` with the citizen data handoff
intact. No physics frame required.

```sh
godot --headless --path godot res://tests/TestRunner.tscn
```

## 2. Runtime spawn/pause/outbreak smoke (`StreetSmoke.tscn` → `test_street_scene.gd`)

Instances `StreetScene` with a selected bundle + citizen, runs real physics
frames, and asserts: player spawns near the citizen's authoritative coordinate,
starts on/above valid ground and not inside a building, the clock/outbreak
advance while unpaused (fast-forwarded so a real tick change is observed),
pause freezes the tree + clock + outbreak + player physics while resume advances
again, and an out-of-bounds fall recovers.

```sh
godot --headless --path godot res://tests/StreetSmoke.tscn
```

Both quit with code `0` on success, `1` on failure — suitable for CI.

## Run both

```sh
godot --headless --path godot res://tests/TestRunner.tscn  && \
godot --headless --path godot res://tests/StreetSmoke.tscn
```

## Execution status

**Executed and green on Godot 4.4.1-stable** (headless). `TestRunner.tscn` →
22/22 checks; `StreetSmoke.tscn` → 14/14 checks; both exit 0 with no runtime
script errors. The Python side of every gameplay-integrity contract is covered
by the `pytest` suite in `../../tests/`.

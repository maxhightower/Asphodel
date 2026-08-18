# Godot gameplay-integrity tests

Two headless harnesses certify the first-person client's contracts. Both are
plain GDScript `SceneTree` scripts (no plugin), run with the Godot 4 binary:

## 1. Pure-logic checks (`run_tests.gd`)

Bundle validation + `GameClock` time / outbreak / pause logic. Deterministic,
no rendering or physics frame required.

```sh
godot --headless --path godot --script res://tests/run_tests.gd
```

## 2. Runtime spawn/pause/outbreak smoke (`test_street_scene.gd`)

Instances `StreetScene` with a selected bundle + citizen, runs real physics
frames, and asserts: player spawns near the citizen's authoritative coordinate,
starts on/above valid ground and not inside a building, pause freezes the
clock/outbreak while resume advances it, and an out-of-bounds fall recovers.

```sh
godot --headless --path godot --script res://tests/test_street_scene.gd
```

Both exit `0` on success, `1` on failure — suitable for CI once a Godot binary
is available on the runner.

## Execution status in this environment

The CI/dev container this milestone was built in has **no Godot binary**
(`which godot` fails), so these harnesses were **written but not executed here**.
They are designed to run unmodified once Godot 4.4+ is on the runner. The Python
side of every gameplay-integrity contract (real-city citizens, authoritative
coordinates, context signatures, scoped inventory, JSON-safe snapshot, hard
agent cap, empty-cell belief, eased time warp) **is** covered by the executed
`pytest` suite in `../../tests/`.

The certified end-to-end flow (MainMenu → CitySelect → load bundle → citizen
selected → CharacterScreen → Continue → StreetScene, with a valid spawn, running
outbreak, working pause and out-of-bounds recovery) is exercised by
`test_street_scene.gd`; run it on a machine with Godot to complete the
integration certification.

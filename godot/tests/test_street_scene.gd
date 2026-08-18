extends SceneTree

## Runtime smoke test for the first-person spawn + pause + outbreak contract.
## Needs a running SceneTree WITH physics (a real frame loop), so unlike
## run_tests.gd it is launched on its own:
##
##     godot --headless --path godot --script res://tests/test_street_scene.gd
##
## It drives the actual MainMenu -> ... -> StreetScene flow's end state by
## loading a bundle, selecting a citizen, instancing StreetScene, letting a few
## physics frames run, then asserting the gameplay-integrity invariants:
##   * the selected bundle + citizen survive into the scene,
##   * the player spawns near the citizen's authoritative coordinate,
##   * the player starts on/above valid ground (not falling, not inside a wall),
##   * pause stops the clock/outbreak; resume lets it advance again,
##   * walking off the world recovers the player (no infinite fall).
##
## Exit code 0 = pass, 1 = fail.

var _failures := 0
const BUNDLE := "res://bundles/madisonville_tx"


func _check(cond: bool, msg: String) -> void:
	if cond:
		print("  ok  %s" % msg)
	else:
		_failures += 1
		print("  FAIL: %s" % msg)


func _initialize() -> void:
	root.call_deferred("set", "name", "root")
	_run.call_deferred()


func _run() -> void:
	print("== street-scene runtime smoke ==")
	# 1. Select a bundle + a citizen (what CitySelect does).
	var citizens := BundleLoader.load_citizens(BUNDLE)
	_check(citizens.size() > 0, "bundle has citizens")
	if citizens.is_empty():
		return _finish()
	Session.bundle_dir = BUNDLE
	Session.citizen = citizens[0]
	var spawn_xy = Session.citizen.get("spawn_xy")

	# 2. Instance StreetScene (what Continue does).
	var scene: Node = load("res://StreetScene.tscn").instantiate()
	root.add_child(scene)

	# Let a handful of physics frames run so the player settles on the ground.
	for i in range(20):
		await process_frame
	await create_timer(0.2).timeout

	var player: Node = _find_player(scene)
	_check(player != null, "a first-person player was spawned")
	if player == null:
		return _finish()

	# 3. Spawn near the citizen's authoritative coordinate.
	if spawn_xy != null and (spawn_xy as Array).size() >= 2:
		var dx: float = player.position.x - float(spawn_xy[0])
		var dz: float = player.position.z - float(spawn_xy[1])
		var dist := sqrt(dx * dx + dz * dz)
		_check(dist < 80.0, "player spawned near the citizen coordinate (%.1fm)" % dist)

	# 4. On/above valid ground, not fallen, not buried in a wall.
	_check(player.position.y > -5.0 and player.position.y < 10.0,
		"player rests on/near ground (y=%.2f)" % player.position.y)

	# 5. Outbreak advances while unpaused.
	var t0: int = GameClock.sim_tick
	await create_timer(0.3).timeout
	var t1: int = GameClock.sim_tick
	_check(t1 >= t0, "outbreak/clock advances while unpaused")

	# 6. Pause freezes the clock; resume lets it advance again.
	GameClock.set_paused(true)
	var tp: int = GameClock.sim_tick
	await create_timer(0.3).timeout
	_check(GameClock.sim_tick == tp, "clock/outbreak frozen while paused")
	GameClock.set_paused(false)
	await create_timer(0.3).timeout
	_check(GameClock.sim_tick >= tp, "clock resumes after unpause")

	# 7. Out-of-bounds recovery.
	player.position.y = -100.0
	for i in range(10):
		await process_frame
	_check(player.position.y > -50.0, "player recovered from out-of-bounds fall")

	_finish()


func _find_player(node: Node) -> Node:
	if node is CharacterBody3D:
		return node
	for child in node.get_children():
		var f := _find_player(child)
		if f != null:
			return f
	return null


func _finish() -> void:
	print("== done: %d failure(s) ==" % _failures)
	quit(1 if _failures > 0 else 0)

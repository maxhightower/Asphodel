extends Node

## Headless Godot test harness for the gameplay-integrity contracts.
##
## Run as a SCENE (so the Session/GameClock autoloads are loaded — `--script`
## mode does not register autoloads):
##     godot --headless --path godot res://tests/TestRunner.tscn
##
## Quits with code 0 if all checks pass, 1 otherwise. Covers the parts that are
## deterministic without a rendering/physics frame: bundle validation and the
## GameClock time/outbreak/pause logic. The full first-person spawn/collision
## smoke test (test_street_scene.gd / StreetSmoke.tscn) needs physics frames and
## is launched separately (see tests/README.md).

var _failures: int = 0


func _fail(msg: String) -> void:
	_failures += 1
	push_error("FAIL: %s" % msg)
	print("  FAIL: %s" % msg)


func _check(cond: bool, msg: String) -> void:
	if cond:
		print("  ok  %s" % msg)
	else:
		_fail(msg)


func _ready() -> void:
	print("== gameplay-integrity headless checks ==")
	_test_bundle_validation()
	_test_game_clock()
	await _test_menu_flow_scenes_boot()
	print("== done: %d failure(s) ==" % _failures)
	get_tree().quit(1 if _failures > 0 else 0)


func _test_menu_flow_scenes_boot() -> void:
	# The pre-StreetScene half of the flow (StreetScene itself is covered by the
	# StreetSmoke runtime test): every scene must instance and build its UI in
	# _ready without a script error, and the CitySelect -> CharacterScreen data
	# handoff (Session.bundle_dir + Session.citizen) must survive.
	print("- menu flow scenes boot")
	for scene_path in ["res://MainMenu.tscn", "res://CitySelect.tscn",
			"res://Settings.tscn"]:
		var inst: Node = load(scene_path).instantiate()
		add_child(inst)
		await get_tree().process_frame
		_check(inst.get_child_count() > 0, "%s builds its UI on _ready" % scene_path)
		inst.queue_free()
		await get_tree().process_frame

	# CitySelect's load step: choose a bundled city, pick a citizen (as _on_load).
	var pool := BundleLoader.load_citizens("res://bundles/houston")
	_check(pool.size() > 0, "CitySelect can load a bundled city's citizens")
	if not pool.is_empty():
		Session.bundle_dir = "res://bundles/houston"
		Session.citizen = pool[0]
		var cs: Node = load("res://CharacterScreen.tscn").instantiate()
		add_child(cs)
		await get_tree().process_frame
		_check(cs.get_child_count() > 0, "CharacterScreen renders the selected citizen")
		_check(Session.citizen.has("spawn_xy"),
			"selected citizen carries an authoritative spawn_xy into the flow")
		cs.queue_free()
		await get_tree().process_frame


# --------------------------------------------------------------------------- #
func _good_bundle() -> Dictionary:
	return {
		"meta": {"version": "1", "dt": 0.25, "n_ticks": 4,
			"grid": {"rows": 2, "cols": 2}},
		"zones": [{"center_xy": [0, 0], "extent": [100, 100], "density": 1.0,
			"blocks": [{"xy": [0, 0], "height": 10.0, "footprint": 6.0}]}],
		"roads": {"polylines": [{"class": "primary", "points": [[0, 0], [10, 10]]}]},
		"timeline": {"field": "belief", "shape": [5, 1],
			"data": [[0.0], [0.1], [0.2], [0.4], [0.8]]},
	}


func _test_bundle_validation() -> void:
	print("- BundleLoader.validate")
	_check(BundleLoader.validate(_good_bundle()) == "", "a well-formed bundle validates")

	var b := _good_bundle()
	b["meta"].erase("version")
	_check(BundleLoader.validate(b) != "", "missing meta.version is rejected")

	b = _good_bundle()
	b["zones"] = []
	_check(BundleLoader.validate(b) != "", "empty zones is rejected")

	b = _good_bundle()
	b["zones"][0].erase("blocks")
	_check(BundleLoader.validate(b) != "", "zone without blocks is rejected")

	b = _good_bundle()
	b["roads"] = {"nope": 1}
	_check(BundleLoader.validate(b) != "", "roads without polylines is rejected")

	b = _good_bundle()
	b["timeline"].erase("data")
	_check(BundleLoader.validate(b) != "", "timeline without data is rejected")


func _test_game_clock() -> void:
	print("- GameClock")
	var bundle := _good_bundle()
	GameClock.reset()
	GameClock.configure(bundle["meta"], bundle["timeline"], 8.0)

	_check(GameClock.configured, "clock configures from a bundle")
	_check(abs(GameClock.hour - 8.0) < 1e-6, "starts at the citizen's spawn hour")
	_check(GameClock.outbreak_belief() >= 0.0, "reports an initial outbreak value")

	# Advancing in-game hours rolls the clock and the sim tick forward.
	var before: float = GameClock.outbreak_belief()
	GameClock._advance(24.0)                    # a full in-game day
	_check(GameClock.game_day == 2, "a full day rolls the day counter")
	_check(GameClock.sim_tick > 0, "sim tick advances with time")
	_check(GameClock.outbreak_belief() >= before, "outbreak progresses as time passes")

	# Pause is authoritative: set_paused flips SceneTree.paused.
	GameClock.set_paused(true)
	_check(GameClock.is_paused(), "set_paused(true) records the paused state")
	_check(get_tree().paused, "pause freezes the whole tree (authoritative)")
	GameClock.set_paused(false)
	_check(not get_tree().paused, "resume unfreezes the tree")
	GameClock.reset()
	_check(not GameClock.configured, "reset clears configuration")

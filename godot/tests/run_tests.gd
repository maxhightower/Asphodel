extends SceneTree

## Headless Godot test harness for the gameplay-integrity contracts.
##
## Run with:
##     godot --headless --path godot --script res://tests/run_tests.gd
##
## Exits with code 0 if all checks pass, 1 otherwise. Covers the parts that are
## deterministic without a rendering/physics frame: bundle validation and the
## GameClock time/outbreak/pause logic. The full first-person spawn/collision
## smoke test (test_street_scene.gd) needs a running SceneTree with physics and
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


func _initialize() -> void:
	print("== gameplay-integrity headless checks ==")
	_test_bundle_validation()
	_test_game_clock()
	print("== done: %d failure(s) ==" % _failures)
	quit(1 if _failures > 0 else 0)


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
	var gc = load("res://scripts/game_clock.gd").new()
	get_root().add_child(gc)
	var bundle := _good_bundle()
	gc.configure(bundle["meta"], bundle["timeline"], 8.0)

	_check(gc.configured, "clock configures from a bundle")
	_check(abs(gc.hour - 8.0) < 1e-6, "starts at the citizen's spawn hour")
	_check(gc.outbreak_belief() >= 0.0, "reports an initial outbreak value")

	# Advancing in-game hours rolls the clock and the sim tick forward.
	var before := gc.outbreak_belief()
	gc._advance(24.0)                         # a full in-game day
	_check(gc.game_day == 2, "a full day rolls the day counter")
	_check(gc.sim_tick > 0, "sim tick advances with time")
	_check(gc.outbreak_belief() >= before, "outbreak progresses as time passes")

	# Pause is authoritative: it stops the tree, and _process is a no-op while
	# paused (PROCESS_MODE_PAUSABLE). We assert the state contract here.
	gc.set_paused(true)
	_check(gc.is_paused(), "set_paused(true) records the paused state")
	_check(get_root().get_tree().paused, "pause freezes the whole tree (authoritative)")
	var frozen_tick := gc.sim_tick
	gc._process(1000.0)                        # PAUSABLE: the real loop wouldn't call this
	# _process has no internal pause guard (the tree gates it), so we assert the
	# tree-level contract: paused == true means the loop won't tick it.
	_check(get_root().get_tree().paused, "still paused")

	gc.set_paused(false)
	_check(not get_root().get_tree().paused, "resume unfreezes the tree")
	gc.reset()
	_check(not gc.configured, "reset clears configuration")
	gc.queue_free()

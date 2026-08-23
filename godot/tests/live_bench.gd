extends Node3D

## BW9 — in-engine render + IPC benchmark. Measures the ONE domain the prior
## Python-only benchmark could not: Godot-side snapshot IPC + parse + MultiMesh
## apply, at the real focused-zone population. GPU frame time is not meaningful
## headless (no swapchain); that is characterised honestly in the report.
##
##   godot4 --headless --path godot res://tests/LiveBench.tscn -- --bundle houston

const ITERS := 30
const WARMUP := 3

var _render


func _ready() -> void:
	var bundle := "houston"
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			bundle = args[i + 1]

	var ok := false
	for attempt in range(50):
		if SimBridge.connect_to_sim("127.0.0.1", 8765):
			ok = true
			break
		OS.delay_msec(100)
	if not ok:
		printerr("bench: no connection")
		return get_tree().quit(1)

	var started: Dictionary = SimBridge.start_world(bundle, {"seed": 1, "player_citizen_id": 5})
	var home_zone := int(started.get("player_home_zone", 0))
	SimBridge.set_focus([home_zone])
	SimBridge.advance(3, false)

	var CitizenRender = load("res://scripts/citizen_render.gd")
	_render = CitizenRender.new()
	add_child(_render)

	# Warm up (first snapshot allocates the MultiMesh buffer).
	for w in range(WARMUP):
		var s0: Dictionary = SimBridge.snapshot().get("world", {})
		_render.render_snapshot(s0, home_zone)

	var ipc_us := 0.0
	var apply_us := 0.0
	var agents := 0
	for it in range(ITERS):
		var t0 := Time.get_ticks_usec()
		var snap: Dictionary = SimBridge.snapshot().get("world", {})   # send+recv+parse
		var t1 := Time.get_ticks_usec()
		agents = _render.render_snapshot(snap, home_zone)              # MultiMesh apply
		var t2 := Time.get_ticks_usec()
		ipc_us += float(t1 - t0)
		apply_us += float(t2 - t1)
		SimBridge.advance(1, false)

	print("BENCH bundle=%s live_agents=%d ipc_ms=%.3f apply_ms=%.3f instances=%d" % [
		bundle, agents, ipc_us / ITERS / 1000.0, apply_us / ITERS / 1000.0,
		_render.last_instance_count])

	SimBridge.disconnect_from_sim()
	get_tree().quit(0)

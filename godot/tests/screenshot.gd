extends Node

## Capture a gameplay screenshot of the living city. Runs the real StreetScene
## (first-person client) against the live Python bridge so the promoted zone's
## citizens render, waits for the world to populate + a few ticks, then saves the
## viewport to a PNG. Run WITH rendering (not --headless), under xvfb:
##
##   xvfb-run -a godot4 --path godot res://tests/Screenshot.tscn -- --bundle houston --out /tmp/shot.png

var _bundle := "houston"
var _out := "/tmp/asph_shot.png"
var _overhead := false


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--out" and i + 1 < args.size():
			_out = args[i + 1]
		elif args[i] == "--overhead":
			_overhead = true
	_run()


func _run() -> void:
	var dir := "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(dir)
	if citizens.is_empty():
		printerr("no citizens in bundle")
		return get_tree().quit(1)
	Session.bundle_dir = dir
	Session.citizen = citizens[0]

	var scene: Node = load("res://StreetScene.tscn").instantiate()
	add_child(scene)

	# Let the scene build + connect + promote the zone. Citizens render from the
	# initial snapshot (street_world pulls one on connect), so we do NOT need to
	# fast-forward time — a modest scale keeps the per-frame ADVANCE load light.
	GameClock.time_scale = 3.0
	for i in range(20):
		await get_tree().physics_frame
	# Force a fresh authoritative snapshot + render so the crowd is populated.
	if SimBridge.is_connected_to_sim():
		var snap: Dictionary = SimBridge.snapshot()
		if snap.get("ok", false):
			SimBridge.last_world = snap.get("world", {})
	await get_tree().create_timer(0.5).timeout

	if _overhead:
		_add_overhead_camera(scene)
		await get_tree().create_timer(0.3).timeout

	# Wait for a fully drawn frame, then grab the viewport.
	await RenderingServer.frame_post_draw
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var err := img.save_png(_out)
	print("SHOT saved=%s err=%d size=%dx%d connected=%s" % [
		_out, err, img.get_width(), img.get_height(),
		str(SimBridge.is_connected_to_sim())])
	get_tree().quit(0 if err == OK else 1)


func _add_overhead_camera(scene: Node) -> void:
	## An elevated angled camera for a city overview shot (makes the block city +
	## crowd legible instead of the ground-level first-person view). Aims at the
	## player's real-world location (the city sits at real bundle coordinates).
	var target := Vector3.ZERO
	var p = scene.get("_player")
	if p != null:
		target = p.position
	var cam := Camera3D.new()
	cam.position = target + Vector3(0, 120, 150)
	cam.look_at(target, Vector3.UP)
	cam.current = true
	cam.far = 4000.0
	add_child(cam)

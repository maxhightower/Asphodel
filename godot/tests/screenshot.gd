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
	# Explicitly drive the authoritative world so the player's zone is promoted and
	# populated, then render it — instead of depending on per-frame timing.
	var fz := int(scene.get("_current_focus_zone"))
	if SimBridge.is_connected_to_sim() and fz >= 0:
		SimBridge.set_focus([fz])
		SimBridge.advance(4, true)                 # promote + populate the crowd
		var snap: Dictionary = SimBridge.snapshot()
		if snap.get("ok", false):
			SimBridge.last_world = snap.get("world", {})
		scene._render_live()
	# Force DAYLIGHT + clear the haze (the citizen may spawn asleep at night, which
	# the day/night system renders near-black; fog washes out an aerial view).
	# Pure presentation — does not touch the sim.
	GameClock.hour = 13.0
	GameClock.ticked.emit(GameClock.game_day, 13.0, GameClock.outbreak_belief())
	var env = scene.get("_env")
	if env != null:
		env.fog_enabled = false
	await get_tree().create_timer(0.5).timeout
	var rc = scene.get("_citizen_render")
	if rc != null:
		print("RENDER instances=%d focus_zone=%d" % [rc.last_instance_count, fz])

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
	## A mid-level aerial framing the promoted zone: the citizen crowd renders at
	## the focus zone's centre, so aim there (not at the player, who may be at the
	## zone edge) and pull back a few hundred metres so streets, building blocks,
	## and the crowd are all legible.
	var target := Vector3.ZERO
	var fz = scene.get("_current_focus_zone")
	if fz != null and int(fz) >= 0:
		target = scene._zone_center(int(fz))
	else:
		var p = scene.get("_player")
		if p != null:
			target = p.position
	var cam := Camera3D.new()
	cam.fov = 62.0
	cam.far = 20000.0
	# Low oblique "drone" angle so building sides, the extruded streets between
	# blocks, and any elevated highway all read (a near-top-down shot flattens the
	# road extrusion). Aim a little above ground so the horizon sits high.
	cam.position = target + Vector3(0, 130, 235)
	cam.current = true
	add_child(cam)                                  # must be in-tree before look_at
	cam.look_at(target + Vector3(0, 25, 0), Vector3.UP)

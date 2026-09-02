extends Node

## Isometric visual-evidence capture. Runs the REAL IsometricWorld scene (with the
## live Python bridge if present) and saves the five required evidence shots from
## the actual renderer. Run WITH rendering (not --headless) under xvfb + software GL:
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/IsoScreenshot.tscn -- --bundle houston --dir /tmp/shots

var _bundle := "houston"
var _dir := "/tmp/asph_iso_shots"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--dir" and i + 1 < args.size():
			_dir = args[i + 1]
	DirAccess.make_dir_recursive_absolute(_dir)
	await _run()


func _shot(name: String) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.4).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	print("SHOT saved: %s (%dx%d)" % [path, img.get_size().x, img.get_size().y])


func _settle_chunks(scene: Node3D, passes: int) -> void:
	var ext = scene.get_exterior()
	if ext != null:
		ext.force_materialize(scene.get_player().position)
		for i in range(passes):
			ext.update_focus(scene.get_camera().get_focus())
			await get_tree().process_frame


func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.citizen = _first_citizen(Session.bundle_dir)
	var scene: Node3D = preload("res://IsometricWorld.tscn").instantiate()
	add_child(scene)
	for i in range(20):
		await get_tree().physics_frame
	await get_tree().create_timer(0.5).timeout

	var cam = scene.get_camera()

	# Prefer a populated zone so citizens are visible (needs the live bridge).
	var pz := -1
	if SimBridge.is_connected_to_sim():
		pz = scene.focus_populated_zone()
		GameClock.set_paused(true)
	# Force clear midday lighting for legible evidence (presentation only).
	GameClock.hour = 13.0
	GameClock.ticked.emit(GameClock.game_day, 13.0, 0.0)
	await _settle_chunks(scene, 120)

	# --- A: Houston exterior, medium zoom -----------------------------------
	cam.set_zoom(70.0)
	cam.settle()
	await _settle_chunks(scene, 60)
	await _shot("A_exterior_medium.png")

	# --- D: crowd / social scene (frame the crowd around the player) --------
	if pz >= 0:
		scene.render_live_now()
	cam.set_zoom(52.0)
	cam.settle()
	await _settle_chunks(scene, 30)
	await _shot("D_crowd.png")

	# --- B: close exterior beside a building/entrance -----------------------
	cam.set_zoom(24.0)
	cam.settle()
	await _settle_chunks(scene, 20)
	await _shot("B_close_exterior.png")

	# --- E: zoomed-out urban view -------------------------------------------
	cam.set_zoom(220.0)
	cam.settle()
	await _settle_chunks(scene, 120)
	await _shot("E_urban_wide.png")

	# --- C: interior cutaway (steeper, near-top-down so the roofless plan reads) --
	if SimBridge.is_connected_to_sim():
		var bid := _find_interior(scene)
		if bid >= 0:
			scene.enter_building_by_id(bid)
			for i in range(12):
				await get_tree().physics_frame
			cam.pitch_deg = 62.0
			cam.set_zoom(20.0)
			cam.settle()
			await get_tree().create_timer(0.4).timeout
			await _shot("C_interior_cutaway.png")

	print("== screenshots done in %s ==" % _dir)
	get_tree().quit(0)


func _find_interior(scene: Node3D) -> int:
	for probe in range(min(scene.building_count(), 60)):
		var gi: Dictionary = SimBridge.get_interior(probe)
		if gi.get("ok", false) and gi.get("interior", {}).get("rooms", []).size() > 0:
			return probe
	return -1


func _first_citizen(bundle_dir: String) -> Dictionary:
	var path := bundle_dir.path_join("citizens.json")
	if not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	var data = JSON.parse_string(f.get_as_text())
	var arr: Array = []
	if data is Array:
		arr = data
	elif data is Dictionary and data.has("citizens"):
		arr = data["citizens"]
	for i in range(arr.size()):
		var c = arr[i]
		if c is Dictionary and c.has("spawn_xy") and c["spawn_xy"] != null:
			c["citizen_id"] = i   # index == authoritative citizen id (roster order)
			return c
	if arr.size() > 0:
		arr[0]["citizen_id"] = 0
		return arr[0]
	return {}

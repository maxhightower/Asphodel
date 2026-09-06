extends Node

## Windowed screenshot of the ground cursor reticle. Warps the OS mouse to a
## point beside the player so the cyan cursor ring is visible and distinct from
## the white player ring.
##
##   Godot --path godot res://tests/CursorShot.tscn -- --out C:/path/shot.png

var _bundle := "houston"
var _out := "cursor.png"
var _zoom := 16.0
var _pitch := 40.0


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--out" and i + 1 < args.size():
			_out = args[i + 1]
		elif args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--zoom" and i + 1 < args.size():
			_zoom = float(args[i + 1])
	await _run()


func _run() -> void:
	DisplayServer.window_set_size(Vector2i(1152, 648))
	await get_tree().process_frame
	var dir := "res://bundles/" + _bundle
	Session.bundle_dir = dir
	var pool := BundleLoader.load_citizens(dir)
	Session.citizen = pool[0] if pool.size() > 0 else {}

	var scene: Node3D = preload("res://IsometricWorld.tscn").instantiate()
	add_child(scene)
	for i in range(20):
		await get_tree().physics_frame
	await get_tree().create_timer(0.4).timeout
	if SimBridge.is_connected_to_sim():
		GameClock.set_paused(true)
	GameClock.hour = 13.0
	GameClock.ticked.emit(GameClock.game_day, 13.0, 0.0)

	var player: CharacterBody3D = scene.get_player()
	var cam = scene.get_camera()
	cam.pitch_deg = _pitch
	cam.set_zoom(_zoom)
	cam.settle()
	var ext = scene.get_exterior()
	if ext != null:
		ext.force_materialize(player.position)
		for i in range(120):
			ext.update_focus(cam.get_focus())
			await get_tree().process_frame

	# Warp the mouse to a screen point offset from the player so the cursor reticle
	# lands on open ground next to the body, then let a few physics frames place it.
	var vp := get_viewport()
	var vr := vp.get_visible_rect().size
	vp.warp_mouse(Vector2(vr.x * 0.5 + 130.0, vr.y * 0.5 + 60.0))
	for i in range(8):
		await get_tree().physics_frame
	await get_tree().create_timer(0.3).timeout

	var hl = scene.get_highlight()
	print("cursor_visible=%s" % (str(hl.is_cursor_visible()) if hl != null else "no-highlight"))
	var img := vp.get_texture().get_image()
	img.save_png(_out)
	print("CURSOR SHOT saved: %s (%dx%d)" % [_out, img.get_size().x, img.get_size().y])
	get_tree().quit(0)

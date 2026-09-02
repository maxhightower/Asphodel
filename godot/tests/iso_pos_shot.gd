extends Node

## Screenshot the isometric exterior at an explicit continuous world position.
## Bridge optional (exterior renders without it). WITH rendering under xvfb + GL.
##
##   ... res://tests/IsoPosShot.tscn -- --bundle houston --pos 1303,-2072 --zoom 90 --out /tmp/x.png

var _bundle := "houston"
var _out := "/tmp/asph_iso_pos.png"
var _px := 0.0
var _pz := 0.0
var _zoom := 80.0
var _pitch := 40.0


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--out" and i + 1 < args.size():
			_out = args[i + 1]
		elif args[i] == "--pos" and i + 1 < args.size():
			var parts := args[i + 1].split(",")
			if parts.size() == 2:
				_px = float(parts[0]); _pz = float(parts[1])
		elif args[i] == "--zoom" and i + 1 < args.size():
			_zoom = float(args[i + 1])
		elif args[i] == "--pitch" and i + 1 < args.size():
			_pitch = float(args[i + 1])
	await _run()


func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.citizen = {}
	var scene: Node3D = preload("res://IsometricWorld.tscn").instantiate()
	add_child(scene)
	for i in range(16):
		await get_tree().physics_frame
	await get_tree().create_timer(0.3).timeout
	if SimBridge.is_connected_to_sim():
		GameClock.set_paused(true)
	GameClock.hour = 13.0
	GameClock.ticked.emit(GameClock.game_day, 13.0, 0.0)

	var player: CharacterBody3D = scene.get_player()
	player.teleport(Vector3(_px, 2.0, _pz))
	var cam = scene.get_camera()
	cam.pitch_deg = _pitch
	cam.set_zoom(_zoom)
	cam.settle()
	var ext = scene.get_exterior()
	if ext != null:
		ext.force_materialize(Vector3(_px, 0.0, _pz))
		for i in range(160):
			ext.update_focus(cam.get_focus())
			await get_tree().process_frame
	await get_tree().create_timer(0.5).timeout

	var img := get_viewport().get_texture().get_image()
	img.save_png(_out)
	print("POS SHOT saved: %s (%dx%d) at (%.1f, %.1f) zoom=%.0f" %
		[_out, img.get_size().x, img.get_size().y, _px, _pz, _zoom])
	if ext != null:
		print("resident_chunks=%d nodes=%d" % [ext.resident_chunk_count(), ext.resident_node_count()])
	get_tree().quit(0)

extends Node

## Windowed screenshot of the embodied player's character model, zoomed in close.
## Picks a real Houston citizen so the body has a named person's deterministic look.
##
##   Godot --path godot res://tests/PlayerBodyShot.tscn -- --out C:/path/shot.png

var _bundle := "houston"
var _out := "player_body.png"
var _zoom := 22.0
var _pitch := 38.0


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
	var dir := "res://bundles/" + _bundle
	Session.bundle_dir = dir
	var pool := BundleLoader.load_citizens(dir)
	Session.citizen = pool[0] if pool.size() > 0 else {}
	print("citizen: %s" % str(Session.citizen.get("name", "?")))

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
	print("player has body: %s" % str(player != null and player.body != null))
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
	await get_tree().create_timer(0.6).timeout

	var img := get_viewport().get_texture().get_image()
	img.save_png(_out)
	print("BODY SHOT saved: %s (%dx%d)" % [_out, img.get_size().x, img.get_size().y])
	get_tree().quit(0)

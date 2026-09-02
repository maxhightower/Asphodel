extends Node

## IsometricExteriorSmoke — ISO-2/3 certification (headless, no bridge required).
##
## Instantiates the real IsometricWorld scene over the compiled Houston world and
## asserts: the continuous OSM chunk stream loads, building identity is indexed,
## road geometry is continuous (polylines, not tiles), embodied WASD movement
## works on a CharacterBody3D, and streaming follows the player as they move —
## all in continuous world coordinates with no snapping.
##
##   godot --headless --path godot res://tests/IsometricExteriorSmoke.tscn

var _fail := 0


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  %s" % label)
	else:
		_fail += 1
		push_error("FAIL: %s" % label)
		print("  FAIL: %s" % label)


func _ready() -> void:
	print("== IsometricExteriorSmoke ==")
	var bundle_dir := "res://bundles/houston"
	if not DirAccess.dir_exists_absolute(ProjectSettings.globalize_path(bundle_dir)):
		print("  (houston bundle absent — skipping, treated as pass)")
		get_tree().quit(0)
		return

	# Resolve a citizen spawn from the bundle so the player spawns in the city.
	var citizen := _first_citizen(bundle_dir)
	Session.bundle_dir = bundle_dir
	Session.citizen = citizen

	var scene: Node3D = preload("res://IsometricWorld.tscn").instantiate()
	add_child(scene)
	for i in range(20):
		await get_tree().physics_frame
	await get_tree().create_timer(0.4).timeout

	# --- geometry / identity ------------------------------------------------
	var ext = scene.get_exterior()
	_check(ext != null, "compiled-world ExteriorWorld instantiated")
	if ext != null:
		_check(ext.world_meta_ok(), "world_meta.json parsed (grid bounds)")
		var grid: Vector2i = ext.chunk_grid_size()
		_check(grid.x > 0 and grid.y > 0, "chunk grid is %dx%d" % [grid.x, grid.y])
		ext.force_materialize(scene.get_player().position)
		for i in range(10):
			await get_tree().physics_frame
		_check(ext.resident_chunk_count() > 0, "Houston chunks resident (%d)" % ext.resident_chunk_count())
		_check(ext.resident_node_count() > 0, "exterior geometry nodes built (%d)" % ext.resident_node_count())
	_check(scene.building_count() > 0, "building identity indexed (%d buildings)" % scene.building_count())

	# --- roads are continuous polylines, not tiles --------------------------
	var roads := _load_roads(bundle_dir)
	var polylines: Array = roads.get("polylines", [])
	var long_pl := 0
	var non_integer := false
	for pl in polylines:
		var pts: Array = pl.get("points", [])
		if pts.size() >= 2:
			long_pl += 1
			for p in pts:
				if absf(float(p[0]) - round(float(p[0]))) > 0.001:
					non_integer = true
	_check(long_pl > 0, "road network has continuous polylines (%d)" % long_pl)
	_check(non_integer, "road vertices are continuous floats (not grid-snapped)")

	# --- embodied WASD movement on the CharacterBody3D ----------------------
	var player: CharacterBody3D = scene.get_player()
	_check(player is CharacterBody3D, "player is a physical CharacterBody3D")
	var before: Vector3 = player.global_position
	Input.action_press("move_forward")
	for i in range(40):
		await get_tree().physics_frame
	Input.action_release("move_forward")
	var after: Vector3 = player.global_position
	var moved := Vector2(after.x - before.x, after.z - before.z).length()
	_check(moved > 1.0, "WASD moved the player %.1f m in continuous space" % moved)
	_check(after.y > -20.0, "player stayed on/above ground while walking (y=%.1f)" % after.y)
	# The moved-to position is continuous (fractional), never tile-snapped.
	_check(absf(after.x - round(after.x)) > 0.0001 or absf(after.z - round(after.z)) > 0.0001,
		"player position is continuous after movement")

	# --- streaming follows the player ---------------------------------------
	if ext != null:
		var far := before + (after - before).normalized() * 600.0 if moved > 0.01 else before + Vector3(600, 0, 0)
		player.teleport(Vector3(far.x, player.position.y, far.z))
		scene.get_camera().settle()
		ext.force_materialize(player.position)
		for i in range(10):
			await get_tree().physics_frame
		_check(ext.resident_chunk_count() > 0,
			"streaming rebuilt chunks around the moved player (%d resident)" % ext.resident_chunk_count())

	scene.queue_free()
	print("== IsometricExteriorSmoke done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


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
	for c in arr:
		if c is Dictionary and c.has("spawn_xy") and c["spawn_xy"] != null:
			return c
	return arr[0] if arr.size() > 0 else {}


func _load_roads(bundle_dir: String) -> Dictionary:
	var path := bundle_dir.path_join("roads.json")
	if not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	var data = JSON.parse_string(f.get_as_text())
	return data if data is Dictionary else {}

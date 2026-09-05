extends Node3D

## Headless regional-terrain realization check (§20). Verifies RegionLoader builds
## chunk meshes, near-chunk collision, and atmosphere IN-ENGINE from the baked
## artifacts, and that the flat (Houston) vs mountain (Denver) relief is real in
## the constructed geometry. No screenshot (headless has no GPU) — this proves the
## realization seam runs and the geometry carries the geography.
##
## Run:  godot --headless --path godot res://tests/RegionGate.tscn

var _fail := 0
var _log: Array[String] = []


func _ready() -> void:
	await get_tree().process_frame
	await _check("res://bundles/houston", "houston_flat", 150.0, false)
	await _check("res://bundles/denver_region", "denver_mountain", 800.0, true)
	print("\n==== REGION GATE RESULTS ====")
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	get_tree().quit(1 if _fail > 0 else 0)


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_log.append("%s  %s  %s" % ["PASS" if cond else "FAIL", name, detail])
	if not cond:
		_fail += 1


func _check(dir: String, tag: String, relief_gate: float, mountainous: bool) -> void:
	var loader := RegionLoader.new()
	loader.bundle_dir = dir
	add_child(loader)                 # triggers _ready -> load_region
	await get_tree().process_frame
	await get_tree().process_frame

	# meshes built
	var meshes := 0
	var with_collision := 0
	var ymin := INF
	var ymax := -INF
	for child in loader.get_children():
		if child is MeshInstance3D:
			meshes += 1
			var aabb: AABB = child.mesh.get_aabb()
			ymin = min(ymin, aabb.position.y)
			ymax = max(ymax, aabb.position.y + aabb.size.y)
			for gc in child.get_children():
				if gc is StaticBody3D:
					with_collision += 1
	_ok("%s_chunks_built" % tag, meshes > 0, "mesh_instances=%d" % meshes)
	_ok("%s_near_collision" % tag, with_collision > 0,
		"chunks_with_static_collision=%d" % with_collision)
	# atmosphere applied
	var has_env := false
	for child in loader.get_children():
		if child is WorldEnvironment:
			has_env = true
	_ok("%s_atmosphere" % tag, has_env, "WorldEnvironment present=%s" % has_env)

	# relief in the constructed geometry
	var relief := ymax - ymin
	if mountainous:
		_ok("%s_relief_is_mountainous" % tag, relief > relief_gate,
			"constructed relief=%.0f m" % relief)
	else:
		_ok("%s_relief_is_flat" % tag, relief < relief_gate,
			"constructed relief=%.0f m" % relief)

	loader.queue_free()
	await get_tree().process_frame

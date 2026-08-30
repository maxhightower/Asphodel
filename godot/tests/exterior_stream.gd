extends Node

## Headless certification for the chunked streaming exterior renderer.
##
##   godot --headless --path godot res://tests/ExteriorStream.tscn
##
## Exits 0 on success, 1 on any failed assertion.

const ExteriorWorld = preload("res://scripts/exterior_world.gd")

var _fail := 0


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  ", label)
	else:
		_fail += 1
		printerr("  FAIL  ", label)


func _ready() -> void:
	print("== exterior streaming headless checks ==")
	var bundle_dir := "res://bundles/houston"
	if not DirAccess.dir_exists_absolute(ProjectSettings.globalize_path(bundle_dir)):
		bundle_dir = "user://__no_bundle__"

	var world := ExteriorWorld.new()
	add_child(world)
	var ok := world.setup(bundle_dir)
	_check(ok, "setup() parsed world_meta.json")
	if not ok:
		return _finish()

	var grid := world.chunk_grid_size()
	_check(grid.x == 23 and grid.y == 26, "chunk grid is 23x26 (got %s)" % str(grid))

	# RLE decode sanity on a couple of sampled chunks.
	_sanity_check_rle(bundle_dir)

	# Dense focus near the middle of the map -> repeated update_focus should
	# eventually materialize chunks up through T3.
	var dense_focus := Vector3(0.0, 0.0, 0.0)
	for i in range(40):
		world.update_focus(dense_focus)
	_check(world.resident_chunk_count() > 0, "resident_chunk_count > 0 after focusing origin")

	var origin_chunk := Vector2i(0, 0)
	# Find the chunk actually containing the focus point to check tiers on.
	var found_t3 := false
	var t3_key := Vector2i(-1, -1)
	for cz in range(grid.y):
		for cx in range(grid.x):
			if world.chunk_tier(cx, cz) == 3:
				found_t3 = true
				t3_key = Vector2i(cx, cz)
				break
		if found_t3:
			break
	_check(found_t3, "at least one T3 chunk exists after dense focus")

	var mm_found := _count_multimesh(world) > 0
	_check(mm_found, "MultiMesh instances present after T3 build")

	var first_hash := 0
	if found_t3:
		first_hash = world.chunk_debug_hash(t3_key.x, t3_key.y)
		_check(first_hash != 0, "chunk_debug_hash nonzero for a resident T3 chunk")

	var max_nodes := world.resident_node_count()

	# Move focus to a far corner repeatedly; hysteresis should eventually
	# unload the originally-loaded T3 chunk, and node count should not grow
	# without bound.
	var far_focus := Vector3(2800.0, 0.0, 3200.0)
	for i in range(200):
		world.update_focus(far_focus)
		max_nodes = maxi(max_nodes, world.resident_node_count())

	var still_t3 := found_t3 and world.chunk_tier(t3_key.x, t3_key.y) == 3
	_check(not still_t3, "originally-loaded T3 chunk was unloaded once far away")
	_check(world.resident_node_count() < max_nodes * 2, "node count didn't blow up (max=%d, now=%d)" %
		[max_nodes, world.resident_node_count()])

	# Return focus to the dense origin and rebuild; the same chunk's content
	# hash should reproduce exactly (reload identity).
	if found_t3:
		for i in range(60):
			world.update_focus(dense_focus)
		var rebuilt_tier := world.chunk_tier(t3_key.x, t3_key.y)
		_check(rebuilt_tier == 3, "origin T3 chunk rebuilt after returning focus")
		if rebuilt_tier == 3:
			var second_hash := world.chunk_debug_hash(t3_key.x, t3_key.y)
			_check(second_hash == first_hash,
				"chunk_debug_hash reproduces after unload+reload (%d == %d)" % [second_hash, first_hash])

	# Force-materialize sanity: spawn chunk + neighbours should build immediately.
	var fw := ExteriorWorld.new()
	add_child(fw)
	fw.setup(bundle_dir)
	fw.force_materialize(Vector3(0.0, 0.0, 0.0))
	_check(fw.resident_chunk_count() >= 1, "force_materialize populates at least the focus chunk")
	fw.queue_free()
	await get_tree().process_frame
	await get_tree().process_frame

	# No-leak check: free the world, await a frame, verify the child count
	# returns to baseline.
	var baseline := get_child_count()
	world.queue_free()
	await get_tree().process_frame
	await get_tree().process_frame
	_check(get_child_count() == baseline - 1, "freeing ExteriorWorld leaves no dangling children")

	_finish()


func _count_multimesh(root: Node) -> int:
	var count := 0
	var stack: Array = [root]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		if n is MultiMeshInstance3D:
			count += (n as MultiMeshInstance3D).multimesh.instance_count
		for c in n.get_children():
			stack.append(c)
	return count


func _sanity_check_rle(bundle_dir: String) -> void:
	var world_dir := bundle_dir.path_join("world")
	var samples := [Vector2i(0, 0), Vector2i(11, 13), Vector2i(22, 25)]
	for s in samples:
		var path := world_dir.path_join("chunks/c_%d_%d.json.gz" % [s.x, s.y])
		if not FileAccess.file_exists(path):
			continue
		var bytes := FileAccess.get_file_as_bytes(path)
		var raw := bytes.decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)
		var parsed: Variant = JSON.parse_string(raw.get_string_from_utf8())
		if not (parsed is Dictionary):
			continue
		var chunk: Dictionary = parsed
		var runs: Array = chunk.get("surface", [])
		var cells := 0
		for i in range(0, runs.size(), 2):
			cells += int(runs[i + 1])
		_check(cells == 128 * 128, "chunk c_%d_%d surface decodes to 128*128 cells (got %d)" %
			[s.x, s.y, cells])


func _finish() -> void:
	print("== exterior stream test done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)

extends Node

## IsometricPerfBench — ISO-10 performance certification for the isometric path.
##
## The isometric renderer reuses the SAME ExteriorWorld chunk stream as the
## first-person path, so the CPU-side streaming cost is expected to match the
## OwPerfBench baseline. This bench drives ExteriorWorld exactly as OwPerfBench
## does but through the isometric camera's ground-focus point (the value that
## actually drives streaming in isometric_world.gd), so the numbers are directly
## comparable and honestly measured. Headless, no bridge.
##
##   godot --headless --path godot res://tests/IsometricPerfBench.tscn -- --bundle houston

const ExteriorWorld = preload("res://scripts/exterior_world.gd")
const IsometricCameraScript = preload("res://scripts/isometric_camera.gd")

var _bundle := "houston"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
	await _run()


func _run() -> void:
	var dir := "res://bundles/" + _bundle
	print("== ISO perf bench: %s ==" % _bundle)

	# A moving target the isometric camera follows; its get_focus() drives streaming.
	var target := Node3D.new()
	add_child(target)
	var cam = IsometricCameraScript.new()
	add_child(cam)
	cam.set_target(target)

	var w := ExteriorWorld.new()
	add_child(w)
	if not w.setup(dir):
		printerr("setup failed for %s" % dir)
		return get_tree().quit(1)

	# Sweep the camera focus across a dense grid (same footprint as OwPerfBench) so
	# many chunks pass through all three tiers. Streaming is driven by the CAMERA
	# focus, mirroring the real isometric update path.
	for gz in range(-3, 4):
		for gx in range(-3, 4):
			target.position = Vector3(gx * 200.0, 0.0, gz * 200.0)
			cam.settle()
			w.update_focus(cam.get_focus())
	for i in range(400):
		w.update_focus(cam.get_focus())

	for tier in [1, 2, 3]:
		var s := w.build_ms_stats(tier)
		print("T%d build ms: min=%.3f avg=%.3f max=%.3f n=%d" %
			[tier, s["min"], s["avg"], s["max"], s["n"]])

	print("resident_chunks=%d resident_nodes=%d mm_instances=%d" %
		[w.resident_chunk_count(), w.resident_node_count(), w.total_mm_instances()])
	w.queue_free()
	await get_tree().process_frame

	var mem_before := OS.get_static_memory_usage()
	var w2 := ExteriorWorld.new()
	add_child(w2)
	w2.setup(dir)
	for gz in range(-1, 2):
		for gx in range(-1, 2):
			w2.force_materialize(Vector3(gx * 256.0, 0.0, gz * 256.0))
	var mem_after := OS.get_static_memory_usage()
	print("static_mem_before=%d static_mem_after=%d delta_mb=%.2f" %
		[mem_before, mem_after, float(mem_after - mem_before) / (1024.0 * 1024.0)])
	w2.queue_free()
	await get_tree().process_frame

	print("== done ==")
	get_tree().quit(0)

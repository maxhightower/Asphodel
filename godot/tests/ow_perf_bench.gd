extends Node

## Outside-world performance certification numbers for the streaming exterior
## renderer. Headless, no bridge required (pure presentation layer — see
## scripts/exterior_world.gd). Prints a markdown-friendly block and exits.
##
##   godot --headless --path godot res://tests/OwPerfBench.tscn -- --bundle houston

const ExteriorWorld = preload("res://scripts/exterior_world.gd")

var _bundle := "houston"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
	_run()


func _run() -> void:
	var dir := "res://bundles/" + _bundle
	print("== OW perf bench: %s ==" % _bundle)

	# (a) per-chunk T1/T2/T3 build time, min/avg/max over a dense sweep.
	var w := ExteriorWorld.new()
	add_child(w)
	if not w.setup(dir):
		printerr("setup failed for %s" % dir)
		return get_tree().quit(1)

	# Sweep the focus across a dense grid of points near the origin so many
	# distinct chunks pass through all three tiers.
	for gz in range(-3, 4):
		for gx in range(-3, 4):
			w.update_focus(Vector3(gx * 200.0, 0.0, gz * 200.0))
	# A few extra passes so tiers that were only queued get built (build is
	# rate-limited per call by BUILD_BUDGET).
	for i in range(400):
		w.update_focus(Vector3(0.0, 0.0, 0.0))

	for tier in [1, 2, 3]:
		var s := w.build_ms_stats(tier)
		print("T%d build ms: min=%.3f avg=%.3f max=%.3f n=%d" %
			[tier, s["min"], s["avg"], s["max"], s["n"]])

	# (b) resident node count + total MultiMesh instance count at steady state
	# around (0,0) (the sweep above already settled focus there).
	print("resident_chunks=%d resident_nodes=%d mm_instances=%d" %
		[w.resident_chunk_count(), w.resident_node_count(), w.total_mm_instances()])
	w.queue_free()
	await get_tree().process_frame

	# (c) static memory before/after materializing a fresh 3x3 T3 block.
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
	await get_tree().process_frame

	print("== done ==")
	get_tree().quit(0)

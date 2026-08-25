extends Node

## Godot-side interior performance: materialization time + node count + memory,
## measured separately (not folded into a frame average). Runs against the live
## server so descriptors are the real authoritative ones.

const InteriorBuilder = preload("res://scripts/interior_builder.gd")

var _bundle := "houston"


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
	for attempt in range(50):
		if SimBridge.connect_to_sim("127.0.0.1", 8765):
			break
		OS.delay_msec(100)
	SimBridge.start_world(_bundle, {"seed": 1, "player_citizen_id": 5})

	# gather a spread of real descriptors
	var descs: Array = []
	for b in range(400):
		var gi: Dictionary = SimBridge.get_interior(b)
		if gi.get("ok", false):
			var it: Dictionary = gi.get("interior", {})
			if it.get("fixtures", []).size() > 0:
				descs.append(it)
		if descs.size() >= 40:
			break

	var mem0 := Performance.get_monitor(Performance.MEMORY_STATIC)
	var nodes0 := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	var t0 := Time.get_ticks_usec()
	var iters := 0
	var last: Node3D = null
	for rep in range(5):
		for d in descs:
			if last != null:
				last.free()
			last = InteriorBuilder.build(d, Vector3(100000, 0, 0))
			add_child(last)
			iters += 1
	var t1 := Time.get_ticks_usec()
	var nodes1 := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	# measure one resident interior's memory + node footprint
	var mem_one := Performance.get_monitor(Performance.MEMORY_STATIC)
	var one_nodes := 0
	if last != null:
		one_nodes = _count(last)
	print("INTERIOR_BENCH bundle=%s descriptors=%d build_ms_avg=%.3f resident_nodes=%d static_mem_kb=%.1f node_delta=%d" % [
		_bundle, descs.size(), float(t1 - t0) / 1000.0 / max(iters, 1),
		one_nodes, (mem_one - mem0) / 1024.0, nodes1 - nodes0])
	if last != null:
		last.free()
	get_tree().quit(0)


func _count(n: Node) -> int:
	var c := 1
	for ch in n.get_children():
		c += _count(ch)
	return c

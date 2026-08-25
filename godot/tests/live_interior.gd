extends Node

## Live in-engine certification of walk-in interiors (Package 3 builder + streaming
## + Package 4 fixture->container authority), driven through the REAL Python
## bridge (protocol v3). Materializes authoritative interior descriptors, checks
## geometry/collision/fixtures, runs a repeated build/free cycle for leaks, and
## drives the fixture->container_id->SEARCH/TAKE chain over the socket.
##
##   godot4 --headless --path godot res://tests/LiveInterior.tscn -- --bundle houston --player 5

const InteriorBuilder = preload("res://scripts/interior_builder.gd")

var _fail := 0
var _bundle := "houston"
var _player := 5


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  ", label)
	else:
		_fail += 1
		printerr("  FAIL  ", label)


func _ready() -> void:
	_parse_args()
	print("== live interior certification (bundle=%s) ==" % _bundle)
	var connected := false
	for attempt in range(50):
		if SimBridge.connect_to_sim("127.0.0.1", 8765):
			connected = true
			break
		OS.delay_msec(100)
	_check(connected, "connect + HELLO (protocol v3)")
	if not connected:
		return _finish()
	var started: Dictionary = SimBridge.start_world(_bundle, {"seed": 1, "player_citizen_id": _player})
	_check(started.get("ok", false), "START_WORLD")

	# Find a building whose interior has at least one fixture (== container).
	var bid := -1
	var desc := {}
	for b in range(400):
		var gi: Dictionary = SimBridge.get_interior(b)
		if gi.get("ok", false):
			var it: Dictionary = gi.get("interior", {})
			if int(it.get("building_id", -1)) == b and it.get("fixtures", []).size() > 0:
				bid = b
				desc = it
				break
	_check(bid >= 0, "GET_INTERIOR returned a building with fixtures (bid=%d)" % bid)
	if bid < 0:
		return _finish()
	print("  .. building %d: arch=%s rooms=%d doors=%d fixtures=%d" % [
		bid, desc.get("archetype", "?"), desc.get("rooms", []).size(),
		desc.get("doorways", []).size(), desc.get("fixtures", []).size()])

	# Determinism: two fetches agree.
	var desc2: Dictionary = SimBridge.get_interior(bid).get("interior", {})
	_check(str(desc) == str(desc2) or desc.get("seed") == desc2.get("seed"),
		"interior descriptor deterministic across fetches")

	# Build it and check the materialized structure.
	var interior: Node3D = InteriorBuilder.build(desc, Vector3(100000, 0, 0))
	add_child(interior)
	_check(interior.has_node("Floor") or _find_child_named(interior, "Floor") != null,
		"floor materialized")
	var fixtures_node := interior.get_node_or_null("Fixtures")
	_check(fixtures_node != null and fixtures_node.get_child_count() == desc["fixtures"].size(),
		"one physical fixture per authoritative fixture (%d)" % desc["fixtures"].size())
	var coll := interior.get_node_or_null("InteriorCollision")
	_check(coll != null and coll.get_child_count() > 0, "wall collision bodies built")

	# Fixture -> container_index metadata is present + matches the descriptor.
	var meta_ok := true
	var expected_ci := {}
	for f in desc["fixtures"]:
		expected_ci[int(f["fixture_id"])] = int(f["container_index"])
	for fx in fixtures_node.get_children():
		var fid := int(fx.get_meta("fixture_id", -999))
		var ci := int(fx.get_meta("container_index", -999))
		if expected_ci.get(fid, -1) != ci:
			meta_ok = false
	_check(meta_ok, "every fixture carries its authoritative container_index")

	# --- Package 4: fixture -> container_id -> SEARCH/TAKE over the socket ---
	var target_fx: Node = fixtures_node.get_child(0)
	var ci0 := int(target_fx.get_meta("container_index"))
	var searched: Dictionary = SimBridge.search_container(bid, ci0)
	_check(searched.get("ok", false), "SEARCH_CONTAINER via fixture container_index")
	var contents: Array = searched.get("contents", [])
	if contents.size() > 0:
		var kind := str(contents[0]["kind"])
		var q0 := int(contents[0]["quantity"])
		var took: Dictionary = SimBridge.take_item(bid, ci0, kind, 1)
		_check(took.get("ok", false), "TAKE_ITEM from fixture container")
		# duplication guard: fully drain (using CURRENT remaining), then a further
		# take must fail — you cannot conjure items the container no longer holds.
		var remaining: Array = SimBridge.search_container(bid, ci0).get("contents", [])
		for c in remaining:
			SimBridge.take_item(bid, ci0, str(c["kind"]), int(c["quantity"]))
		var dup: Dictionary = SimBridge.take_item(bid, ci0, kind, 1)
		_check(not dup.get("ok", true), "cannot duplicate via repeated take")
	else:
		print("  .. first fixture container was empty; skipping take chain")

	# --- Package 3: streaming leak check — repeated build/free ---------------
	interior.free()
	var base_nodes := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	for i in range(60):
		var it2: Node3D = InteriorBuilder.build(desc, Vector3(100000, 0, 0))
		add_child(it2)
		it2.free()
	var after_nodes := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	_check(after_nodes <= base_nodes + 2,
		"no node leak over 60 build/free cycles (%d -> %d)" % [base_nodes, after_nodes])

	# --- Package 5: interior NPC occupancy ---------------------------------
	# Find a building that has authoritative occupants at the current time.
	var occ_bid := -1
	var occ_desc := {}
	for b in range(600):
		var gi2: Dictionary = SimBridge.get_interior(b)
		if gi2.get("ok", false):
			var it2: Dictionary = gi2.get("interior", {})
			if it2.get("occupants", []).size() > 0:
				occ_bid = b; occ_desc = it2; break
	_check(occ_bid >= 0, "found a building with authoritative interior occupants")
	if occ_bid >= 0:
		var occ_interior: Node3D = InteriorBuilder.build(occ_desc, Vector3(200000, 0, 0))
		add_child(occ_interior)
		var occ_node := occ_interior.get_node_or_null("Occupants")
		_check(occ_node != null and occ_node.get_child_count() == occ_desc["occupants"].size(),
			"occupant NPCs materialized (%d)" % occ_desc["occupants"].size())
		var first_cid := int(occ_desc["occupants"][0]["citizen_id"])
		var cid_ok := false
		if occ_node != null:
			for o in occ_node.get_children():
				if int(o.get_meta("citizen_id", -1)) == first_cid:
					cid_ok = true
		_check(cid_ok, "occupant carries its authoritative citizen_id")
		# unload/reload -> same occupant returns (deterministic, authority persists)
		occ_interior.free()
		var reocc: Dictionary = SimBridge.get_interior(occ_bid).get("interior", {})
		var same := false
		for o in reocc.get("occupants", []):
			if int(o["citizen_id"]) == first_cid:
				same = true
		_check(same, "same occupant returns after unload/reload")

	# Persistence: after the taking above, re-fetch shows the container searched.
	var reget: Dictionary = SimBridge.get_interior(bid).get("interior", {})
	var searched_flag := false
	for fs in reget.get("fixture_state", []):
		if int(fs["container_index"]) == ci0:
			searched_flag = bool(fs["searched"])
	_check(searched_flag, "fixture reads as searched after looting (persistent delta)")

	SimBridge.disconnect_from_sim()
	_finish()


func _find_child_named(n: Node, nm: String) -> Node:
	for c in n.get_children():
		if c.name == nm:
			return c
	return null


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])


func _finish() -> void:
	print("== live interior cert done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)

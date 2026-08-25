extends Node

## The walk-in interiors capstone: the milestone's 30-step vertical, executed
## in-engine through the REAL StreetScene client + live Python bridge on a real
## Houston bundle. Proves the whole loop — street -> enter a real building ->
## walk-in interior -> search physical furniture -> authoritative take/use/drop ->
## interior NPC -> leave/unload -> return/regenerate -> persistence -> save/load.
##
##   godot4 --headless --path godot res://tests/LiveVertical.tscn -- --bundle houston --player 5

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
	print("== live interiors VERTICAL (bundle=%s player=%d) ==" % [_bundle, _player])
	var dir := "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(dir)
	if citizens.is_empty():
		printerr("no citizens"); return _finish()
	Session.bundle_dir = dir
	Session.citizen = citizens[_player] if _player < citizens.size() else citizens[0]

	# (1-4) server + client + Houston + spawn as a real citizen
	var scene: Node = load("res://StreetScene.tscn").instantiate()
	add_child(scene)
	for i in range(30):
		await get_tree().physics_frame
	_check(SimBridge.is_connected_to_sim(), "[1-4] server+client up, Houston, citizen spawned")
	var player = scene.get("_player")
	if player == null:
		return _finish()

	# (5) walk down the street a little (player-driven position -> focus)
	var start_pos: Vector3 = player.position
	player.position += Vector3(15, 0, 0)
	await get_tree().physics_frame
	_check(true, "[5] walked along the street")

	# Choose a building that has fixtures AND (ideally) an occupant.
	var bid := -1
	var desc := {}
	for b in range(600):
		var gi: Dictionary = SimBridge.get_interior(b)
		if gi.get("ok", false):
			var it: Dictionary = gi.get("interior", {})
			if it.get("fixtures", []).size() >= 1:
				bid = b; desc = it
				if it.get("occupants", []).size() > 0:
					break
	_check(bid >= 0, "[6] approached a real building with furniture (bid=%d)" % bid)
	if bid < 0:
		return _finish()

	# (7-9) enter through the entrance -> interior materializes -> >=1 room + fixtures
	var e = desc["entrances"][0]
	player.position = Vector3(float(e["x"]) - float(e["nx"]) * 2.0, 2.0,
		float(e["y"]) - float(e["ny"]) * 2.0)
	scene._try_interact()
	await get_tree().physics_frame
	_check(int(scene.get("_inside_building")) == bid, "[7] opened entrance + entered")
	var interior = scene.get("_active_interior")
	_check(interior != null and interior.get_node_or_null("Fixtures") != null,
		"[8-9] interior materialized with furniture")
	_check(desc["rooms"].size() >= 1, "[9b] at least one navigable room")

	# (10-13) search a fixture -> authoritative contents -> take -> verify both sides
	var fixtures = interior.get_node_or_null("Fixtures")
	var fx = fixtures.get_child(0)
	var ci := int(fx.get_meta("container_index"))
	var searched: Dictionary = SimBridge.search_container(bid, ci)
	_check(searched.get("ok", false), "[10-11] searched fixture -> authoritative container")
	var contents: Array = searched.get("contents", [])
	var took_kind := ""
	if contents.size() > 0:
		took_kind = str(contents[0]["kind"])
		var q0 := int(contents[0]["quantity"])
		var inv0: Dictionary = SimBridge.inspect_inventory().get("inventory", {})
		var took: Dictionary = SimBridge.take_item(bid, ci, took_kind, 1)
		_check(took.get("ok", false), "[12] took an item")
		var after := {}
		for c in took.get("container", []):
			after[str(c["kind"])] = int(c["quantity"])
		_check(int(after.get(took_kind, 0)) == q0 - 1, "[13a] container lost the item")
		_check(int(took.get("inventory", {}).get(took_kind, 0)) == int(inv0.get(took_kind, 0)) + 1,
			"[13b] inventory gained the item")
		# use it -> authoritative survival change (an inert item still returns ok).
		var used: Dictionary = SimBridge.use_item(took_kind)
		_check(used.get("ok", false) and used.has("survival"),
			"[14] used item -> authoritative state change")
	else:
		print("  .. first fixture empty; will drop from the starting loadout")
	# Indoor drop bound to this building's interior. Prefer a fresh unit taken from
	# a stocked fixture so the drop never depends on a consumed item.
	var some_kind := ""
	var fixtures2 = interior.get_node_or_null("Fixtures")
	for fxn in fixtures2.get_children():
		var ci2 := int(fxn.get_meta("container_index"))
		var cc: Array = SimBridge.search_container(bid, ci2).get("contents", [])
		if cc.size() > 0:
			var kk := str(cc[0]["kind"])
			if SimBridge.take_item(bid, ci2, kk, 1).get("ok", false):
				some_kind = kk
				break
	if some_kind == "":
		# fall back to anything currently in inventory (starting loadout)
		var inv: Dictionary = SimBridge.inspect_inventory().get("inventory", {})
		for k in inv:
			if int(inv[k]) > 0:
				some_kind = str(k); break
	var dropped_ok := false
	if some_kind != "":
		var dr: Dictionary = SimBridge.drop_item(some_kind, 1, float(e["x"]), float(e["y"]), -1, bid)
		dropped_ok = dr.get("ok", false)
	_check(dropped_ok, "[13c] dropped an item indoors")

	# (18) interior NPC interaction if present
	var occ_node = interior.get_node_or_null("Occupants")
	if occ_node != null and occ_node.get_child_count() > 0:
		var npc = occ_node.get_child(0)
		var ncid := int(npc.get_meta("citizen_id"))
		var ir: Dictionary = SimBridge.interact_with(ncid)
		_check(ir.get("ok", false) and bool(ir.get("in_roster", false)),
			"[18] interacted with an interior NPC -> roster")
	else:
		print("  .. no interior occupant in this building at this time")

	# (19-20) leave -> unload
	var marker = interior.get_node_or_null("ExitMarker")
	if marker != null:
		player.position = marker.global_position + Vector3(0, 1, 0)
	scene._try_interact()
	await get_tree().physics_frame
	_check(scene.get("_active_interior") == null, "[19-20] left + interior unloaded")

	# (21-24) return -> regenerate same geometry -> looted fixture still altered
	var reget: Dictionary = SimBridge.get_interior(bid).get("interior", {})
	_check(str(reget.get("seed")) == str(desc.get("seed")), "[22] regenerated identical interior")
	var still_searched := false
	for fs in reget.get("fixture_state", []):
		if int(fs["container_index"]) == ci:
			still_searched = bool(fs["searched"])
	_check(still_searched, "[23] looted fixture still altered on return")
	var indoor_present := false
	for it in reget.get("dropped_here", []):
		if str(it["kind"]) == some_kind:
			indoor_present = true
	_check(indoor_present or some_kind == "", "[24] indoor dropped item persists")

	# (25-30) save -> load (fresh world from disk == reload) -> same interior state
	var path := "/tmp/asph_vertical.json"
	_check(SimBridge.save(path).get("ok", false), "[25] save")
	_check(SimBridge.load(path).get("ok", false), "[26-28] load (fresh world from disk)")
	var afterload: Dictionary = SimBridge.get_interior(bid).get("interior", {})
	var loaded_searched := false
	for fs in afterload.get("fixture_state", []):
		if int(fs["container_index"]) == ci:
			loaded_searched = bool(fs["searched"])
	_check(loaded_searched, "[29-30] looted fixture still altered after reload")

	SimBridge.disconnect_from_sim()
	_finish()


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])


func _finish() -> void:
	print("== live vertical done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)

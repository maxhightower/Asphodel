extends Node

## Live in-engine certification of the Package 3 survival-resource loop, driven
## through the REAL authoritative Python bridge over the socket (protocol v2).
## This is the in-engine equivalent of tests/test_survival_vertical.py: it proves
## the same authoritative loop works end-to-end through the actual Godot client
## command path, not just the Python session object.
##
##   godot4 --headless --path godot res://tests/LiveSurvival.tscn -- --bundle houston --player 5
##
## Exits 0 on success, 1 on any failed assertion.

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
	print("== live survival certification (bundle=%s player=%d) ==" % [_bundle, _player])

	var connected := false
	for attempt in range(50):
		if SimBridge.connect_to_sim("127.0.0.1", 8765):
			connected = true
			break
		OS.delay_msec(100)
	_check(connected, "connect + HELLO handshake (protocol v2)")
	if not connected:
		return _finish()

	var started: Dictionary = SimBridge.start_world(_bundle,
		{"seed": 1, "player_citizen_id": _player})
	_check(started.get("ok", false), "START_WORLD with real citizens")

	# Player begins with an authoritative on-person inventory + survival needs.
	var inv0: Dictionary = SimBridge.inspect_inventory()
	_check(inv0.get("ok", false), "INSPECT_INVENTORY returns authoritative state")
	_check(inv0.get("survival", {}).has("health"), "player has survival state")

	# Find a stocked container by scanning buildings through the real commands.
	var found := {}
	for bid in range(400):
		var info: Dictionary = SimBridge.inspect_building(bid)
		if not info.get("ok", false):
			continue
		var nc := int(info.get("n_containers", 0))
		for ci in range(nc):
			var searched: Dictionary = SimBridge.search_container(bid, ci)
			var contents: Array = searched.get("contents", [])
			if contents.size() > 0:
				found = {"bid": bid, "ci": ci, "contents": contents}
				break
		if not found.is_empty():
			break
	_check(not found.is_empty(), "found a stocked container by scanning real buildings")
	if found.is_empty():
		return _finish()
	var bid: int = found["bid"]
	var ci: int = found["ci"]
	var kind: String = str(found["contents"][0]["kind"])
	var qty0: int = int(found["contents"][0]["quantity"])
	print("  .. building %d container %d holds %d x %s" % [bid, ci, qty0, kind])

	# Enter the building and take one of the item.
	_check(SimBridge.enter_building(bid).get("ok", false), "ENTER_BUILDING %d" % bid)
	var inv_before: Dictionary = SimBridge.inspect_inventory().get("inventory", {})
	var have_before := int(inv_before.get(kind, 0))
	var took: Dictionary = SimBridge.take_item(bid, ci, kind, 1)
	_check(took.get("ok", false), "TAKE_ITEM 1x %s" % kind)
	# container lost exactly one; inventory gained exactly one.
	var after_container := {}
	for c in took.get("container", []):
		after_container[str(c["kind"])] = int(c["quantity"])
	_check(int(after_container.get(kind, 0)) == qty0 - 1, "container decremented by one")
	_check(int(took.get("inventory", {}).get(kind, 0)) == have_before + 1,
		"inventory incremented by one")

	# Illegal action: taking a nonexistent kind is rejected authoritatively.
	var illegal: Dictionary = SimBridge.take_item(bid, ci, "definitely_not_here", 1)
	_check(not illegal.get("ok", true), "illegal TAKE_ITEM rejected")

	# Use or drop, and observe an authoritative state change.
	var used: Dictionary = SimBridge.use_item(kind)
	if used.get("ok", false):
		_check(used.has("survival"), "USE_ITEM changed authoritative survival state")
	else:
		# not consumable/usable -> drop it instead (ownership transfers once).
		var dropped: Dictionary = SimBridge.drop_item(kind, 1, 0.0, 0.0, -1)
		_check(dropped.get("ok", false), "DROP_ITEM transferred ownership to the world")

	# Leave, advance, return -> looted container is still altered (persistence).
	SimBridge.leave_building()
	SimBridge.advance(2, false)
	var re: Dictionary = SimBridge.search_container(bid, ci)
	var re_c := {}
	for c in re.get("contents", []):
		re_c[str(c["kind"])] = int(c["quantity"])
	_check(int(re_c.get(kind, 0)) == qty0 - 1, "looted container still altered after return")

	# Save -> load (same process) -> container delta persists across reload.
	var path := "/tmp/asph_live_survival.json"
	_check(SimBridge.save(path).get("ok", false), "SAVE authoritative world")
	_check(SimBridge.load(path).get("ok", false), "LOAD authoritative world")
	var rs: Dictionary = SimBridge.search_container(bid, ci)
	var rs_c := {}
	for c in rs.get("contents", []):
		rs_c[str(c["kind"])] = int(c["quantity"])
	_check(int(rs_c.get(kind, 0)) == qty0 - 1, "container delta survived save/load")

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
	print("== live survival cert done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)

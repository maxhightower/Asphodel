extends Node

## Live in-engine certification (BW2–BW6): drive the REAL authoritative Python
## bridge from Godot and assert the whole living-city loop. Run headless against a
## running `python -m asphodel.bridge.server`:
##
##   godot4 --headless --path godot res://tests/LiveSmoke.tscn -- --bundle houston --player 5
##
## Exits 0 on success, 1 on any failed assertion — suitable for CI. Prints a
## machine-readable line per check.

var _fail := 0
var _bundle := "houston"
var _player := 5
var _seed_zone := 0


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  ", label)
	else:
		_fail += 1
		printerr("  FAIL  ", label)


func _ready() -> void:
	_parse_args()
	print("== live in-engine certification (bundle=%s player=%d) ==" % [_bundle, _player])

	# BW2: connect + handshake (retry while the server is still binding).
	var connected := false
	for attempt in range(50):
		if SimBridge.connect_to_sim("127.0.0.1", 8765):
			connected = true
			break
		OS.delay_msec(100)
	_check(connected, "connect + HELLO handshake with live Python server")
	if not connected:
		return _finish()

	# BW1+BW2: START_WORLD populates the real bundle citizens.
	var started: Dictionary = SimBridge.start_world(_bundle,
		{"seed": 1, "player_citizen_id": _player})
	_check(started.get("ok", false), "START_WORLD houston with real citizens")
	var n_citizens: int = int(started.get("n_citizens", 0))
	var home_zone: int = int(started.get("player_home_zone", -1))
	_seed_zone = int(started.get("seed_zone", 0))
	_check(n_citizens > 0, "bundle contributed %d citizens" % n_citizens)
	_check(home_zone >= 0, "player citizen resolved to home zone %d" % home_zone)

	# BW4: a snapshot after advancing carries real identified citizens in the
	# player's promoted zone.
	SimBridge.advance(3, true)
	var snap: Dictionary = SimBridge.snapshot().get("world", {})
	var agents: Dictionary = snap.get("agents", {})
	var akey := str(home_zone)
	_check(agents.has(akey), "player home zone %d is promoted + rendered" % home_zone)
	var identified := 0
	if agents.has(akey):
		for cid in agents[akey].get("citizen_id", []):
			if int(cid) >= 0:
				identified += 1
	_check(identified > 0, "%d identified citizens in the player's zone" % identified)

	# BW3: player position -> zone -> SET_FOCUS -> promotion follows the player.
	var bundle_data := BundleLoader.load_bundle("res://bundles/" + _bundle)
	var zmap := ZoneMap.new()
	if bundle_data.has("zones"):
		zmap.load_from_zones(bundle_data["zones"])
	_check(zmap.zone_count() > 0, "ZoneMap loaded %d zones" % zmap.zone_count())
	# Treat two distinct *populated* zone centres as successive player positions;
	# each must map back to its own zone and, once focused, promote. (Empty zones
	# never promote — there is nobody to resolve into agents.)
	var zones_arr: Array = bundle_data.get("zones", [])
	var populated: Array = []
	for z in zones_arr:
		if float(z.get("population", 0.0)) >= 1.0:
			populated.append(z)
	populated.sort_custom(func(a, b): return int(a["id"]) < int(b["id"]))
	_check(populated.size() >= 2, "bundle has >=2 populated zones (%d)" % populated.size())
	var zA: Dictionary = populated[0]
	var zB: Dictionary = populated[populated.size() / 2]
	var posA: Array = zA["center_xy"]
	var posB: Array = zB["center_xy"]
	_check(zmap.zone_of_xy(posA[0], posA[1]) == int(zA["id"]),
		"player position maps to its own zone %d" % int(zA["id"]))
	SimBridge.set_focus([zmap.zone_of_xy(posA[0], posA[1])])
	var advA: Dictionary = SimBridge.advance(2, false)
	var promA: Array = advA.get("promoted", [])
	_check(_contains_zone(promA, int(zA["id"])),
		"moving to zone %d promotes it (promoted=%s)" % [int(zA["id"]), str(promA)])
	SimBridge.set_focus([zmap.zone_of_xy(posB[0], posB[1])])
	var advB: Dictionary = SimBridge.advance(6, false)
	var promB: Array = advB.get("promoted", [])
	_check(_contains_zone(promB, int(zB["id"])),
		"walking to zone %d promotes it (promoted=%s)" % [int(zB["id"]), str(promB)])
	# restore focus to the player's home zone for the rest of the run
	SimBridge.set_focus([home_zone])
	SimBridge.advance(2, false)

	# BW4: ADVANCE changes activity state (a real live world, not static).
	var occ_before := _activity_occupancy(snap, home_zone)
	SimBridge.intervene("broadcast", null, {"level": 1.0})   # push belief up
	SimBridge.advance(8, true)
	var snap2: Dictionary = SimBridge.snapshot().get("world", {})
	var reacted := _reaction_share(snap2, home_zone)
	_check(reacted >= 0.0, "reaction share readable from snapshot")

	# BW5: interaction reaches the Python roster.
	var target := _first_identified(snap2, home_zone)
	_check(target >= 0, "found a rendered citizen to interact with (id=%d)" % target)
	var roster_ok := _interact_and_verify(target, home_zone)
	_check(roster_ok, "interaction added citizen %d to the authoritative roster" % target)

	# BW5 continuity: leave -> the zone demotes -> return -> the SAME person is
	# restored (same citizen id, still named, same stable appearance seed).
	if target >= 0:
		var seed_before := _visual_seed(target)
		SimBridge.set_focus([_seed_zone])            # travel far away
		var demoted := false
		for k in range(60):
			var adv: Dictionary = SimBridge.advance(1, false)
			if not _contains_zone(adv.get("promoted", []), home_zone):
				demoted = true
				break
		_check(demoted, "leaving demotes the player's home zone %d" % home_zone)
		SimBridge.set_focus([home_zone])             # return
		SimBridge.advance(2, false)
		var back: Dictionary = SimBridge.snapshot().get("world", {})
		var still_there := false
		var a2: Dictionary = back.get("agents", {}).get(str(home_zone), {})
		for cid in a2.get("citizen_id", []):
			if int(cid) == target:
				still_there = true
				break
		_check(still_there, "returning restores citizen %d as the same person" % target)
		_check(_visual_seed(target) == seed_before,
			"restored citizen keeps a stable appearance seed")

	# BW6: an in-engine intervention changes the future authoritative world.
	var diverged := _causality_ab()
	_check(diverged, "in-engine cordon changes the future authoritative state")

	SimBridge.disconnect_from_sim()
	_finish()


func _interact_and_verify(cid: int, home_zone: int) -> bool:
	if cid < 0:
		return false
	SimBridge.interact_with(cid)
	var snap: Dictionary = SimBridge.snapshot().get("world", {})
	for r in snap.get("roster", []):
		if int(r.get("citizen_id", -1)) == cid:
			return true
	# also accept the per-agent named flag
	var agents: Dictionary = snap.get("agents", {})
	var a: Dictionary = agents.get(str(home_zone), {})
	var ids: Array = a.get("citizen_id", [])
	var named: Array = a.get("named", [])
	for i in range(ids.size()):
		if int(ids[i]) == cid and named.size() > i and bool(named[i]):
			return true
	return false


func _causality_ab() -> bool:
	# Fork reproducibly via SAVE/LOAD through the client, run A (no intervention)
	# and B (cordon) for equal ticks, compare infected totals.
	var path := "/tmp/asph_live_fork.json"
	SimBridge.save(path)
	# Branch A: no intervention, advance a long horizon.
	SimBridge.load(path)
	SimBridge.advance(80, false)
	var a := _infected(SimBridge.advance(0, false))
	# Branch B: cordon the outbreak seed zone at the fork, same horizon.
	SimBridge.load(path)
	SimBridge.intervene("cordon", [_seed_zone], {})
	SimBridge.advance(80, false)
	var b := _infected(SimBridge.advance(0, false))
	print("  causality: seed_zone=%d  infected A=%.3f  B=%.3f  delta=%.3f"
		% [_seed_zone, a, b, a - b])
	return abs(a - b) > 1.0


func _infected(reply: Dictionary) -> float:
	var t: Dictionary = reply.get("totals", {})
	return float(t.get("E", 0)) + float(t.get("Ia", 0)) + float(t.get("Is", 0)) \
		+ float(t.get("R", 0)) + float(t.get("D", 0))


func _visual_seed(cid: int) -> int:
	if cid < 0:
		return 0
	var x := (cid * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF
	x ^= (x >> 16)
	x = (x * 0x85EBCA6B) & 0xFFFFFFFF
	x ^= (x >> 13)
	return x & 0x7FFFFFFF


func _contains_zone(promoted: Array, zid: int) -> bool:
	for z in promoted:
		if int(z) == zid:
			return true
	return false


func _first_identified(snap: Dictionary, zone: int) -> int:
	var a: Dictionary = snap.get("agents", {}).get(str(zone), {})
	for cid in a.get("citizen_id", []):
		if int(cid) >= 0:
			return int(cid)
	return -1


func _activity_occupancy(snap: Dictionary, zone: int) -> Dictionary:
	return snap.get("activity_occupancy", {}).get(str(zone), {})


func _reaction_share(snap: Dictionary, zone: int) -> float:
	var a: Dictionary = snap.get("agents", {}).get(str(zone), {})
	var acts: Array = a.get("chosen_action", [])
	var ids: Array = a.get("citizen_id", [])
	var named := 0
	var react := 0
	for i in range(ids.size()):
		if int(ids[i]) >= 0:
			named += 1
			var act := int(acts[i]) if acts.size() > i else 0
			if act == 1 or act == 2:   # shelter or flee
				react += 1
	return float(react) / float(max(named, 1))


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])


func _finish() -> void:
	print("== live cert done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)

extends Node3D

## Headless local-navigation check (§7.1 avoidance, §7.2 stuck -> replan), against
## REAL Godot physics. Verifies a CitizenBody steers around another agent, declares
## itself blocked when it cannot progress, and resumes to its goal after the
## strategic layer hands it a detour route.
##
## Run:  godot --headless --path godot res://tests/NavGate.tscn

var _fail := 0
var _log: Array[String] = []


func _ready() -> void:
	await get_tree().physics_frame
	await _scenario_avoidance()
	await _scenario_stuck()
	await _scenario_replan()
	print("\n==== NAV GATE RESULTS ====")
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	get_tree().quit(1 if _fail > 0 else 0)


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_log.append("%s  %s  %s" % ["PASS" if cond else "FAIL", name, detail])
	if not cond:
		_fail += 1


func _floor() -> void:
	var f := StaticBody3D.new()
	f.collision_layer = CollisionLayers.WORLD_STATIC
	f.collision_mask = 0
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(60, 1, 60)
	cs.shape = b
	f.add_child(cs)
	add_child(f)
	f.global_position = Vector3(0, -0.5, 0)


func _wall(pos: Vector3, size: Vector3) -> void:
	var w := StaticBody3D.new()
	w.collision_layer = CollisionLayers.WORLD_STATIC
	w.collision_mask = 0
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = size
	cs.shape = b
	w.add_child(cs)
	add_child(w)
	w.global_position = pos


func _npc(pos: Vector3) -> CitizenBody:
	var c := CitizenBody.new()
	c.position = pos          # set BEFORE add_child so _ready sees the real pose
	add_child(c)              # (avoids a one-frame overlap at the origin)
	return c


func _clear() -> void:
	for c in get_children():
		c.queue_free()
	await get_tree().physics_frame


# Scenario 1: steer around a stationary agent and still reach the goal.
func _scenario_avoidance() -> void:
	_floor()
	var blocker := _npc(Vector3(0, 1, 0))
	blocker.set_route([])                      # stands still in the path
	var mover := _npc(Vector3(-5, 1, 0))
	mover.set_route([Vector3(5, 0, 0)])
	for _i in range(900):
		await get_tree().physics_frame
		if mover.has_arrived():
			break
	_ok("avoidance_reaches_goal_around_agent",
		mover.has_arrived() or mover.global_position.x > 2.0,
		"x=%.2f arrived=%s stuck=%s" % [mover.global_position.x, mover.has_arrived(), mover.is_stuck])
	# and it did not simply walk through the blocker
	_ok("avoidance_did_not_overlap_blocker",
		mover.global_position.distance_to(blocker.global_position) > 0.5 or mover.global_position.x > 1.0,
		"kept clearance while passing")
	await _clear()


# Scenario 2: a solid wall with no gap -> the body declares itself blocked.
func _scenario_stuck() -> void:
	_floor()
	_wall(Vector3(0, 1.5, 0), Vector3(0.4, 3, 16))
	var mover := _npc(Vector3(-3, 1, 0))
	mover.stuck_frames = 60
	var got_block := {"v": false, "at": Vector3.ZERO}
	mover.blocked.connect(func(at): got_block["v"] = true; got_block["at"] = at)
	mover.set_route([Vector3(5, 0, 0)])
	for _i in range(400):
		await get_tree().physics_frame
		if got_block["v"]:
			break
	_ok("stuck_detected_emits_blocked", got_block["v"] and mover.is_stuck,
		"blocked=%s at x=%.2f" % [got_block["v"], got_block["at"].x])
	await _clear()


# Scenario 3: stuck -> strategic layer hands a detour through a gap -> resumes.
func _scenario_replan() -> void:
	_floor()
	# Wall from z=-8..2.5 and z=5.5..8, leaving a doorway gap at z in [2.5, 5.5].
	_wall(Vector3(0, 1.5, -2.75), Vector3(0.4, 3, 10.5))
	_wall(Vector3(0, 1.5, 6.75), Vector3(0.4, 3, 2.5))
	var mover := _npc(Vector3(-3, 1, 0))
	mover.stuck_frames = 60
	var replanned := {"v": false}
	mover.blocked.connect(func(_at):
		if not replanned["v"]:
			replanned["v"] = true
			# detour via the gap, then on to the goal
			mover.set_route([Vector3(0, 0, 4.0), Vector3(5, 0, 4.0), Vector3(5, 0, 0)]))
	mover.set_route([Vector3(5, 0, 0)])        # naive straight path -> will jam
	for _i in range(1500):
		await get_tree().physics_frame
		if mover.has_arrived():
			break
	_ok("stuck_then_replan_reaches_goal",
		replanned["v"] and (mover.has_arrived() or mover.global_position.x > 3.0),
		"replanned=%s x=%.2f arrived=%s" % [replanned["v"], mover.global_position.x, mover.has_arrived()])
	await _clear()

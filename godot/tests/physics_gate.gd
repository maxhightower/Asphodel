extends Node3D

## Headless physics proving ground (§18) — runs the acceptance items against REAL
## Godot 3D physics (CPU, works under --headless) and exits non-zero on any
## failure. Bodies use the generated CollisionLayers authority so this also
## verifies that autoload + the layer/mask matrix behave in-engine.
##
## Run:  godot --headless --path godot res://tests/PhysicsGate.tscn

var _fail := 0
var _log: Array[String] = []


func _ready() -> void:
	# run in a coroutine so we can await physics frames between steps
	await _run()
	print("\n==== PHYSICS GATE RESULTS ====")
	for line in _log:
		print(line)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	get_tree().quit(1 if _fail > 0 else 0)


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_log.append("%s  %s  %s" % ["PASS" if cond else "FAIL", name, detail])
	if not cond:
		_fail += 1


# ---- builders -------------------------------------------------------------
func _static_box(pos: Vector3, size: Vector3, layer: int) -> StaticBody3D:
	var b := StaticBody3D.new()
	b.collision_layer = layer
	b.collision_mask = 0
	var cs := CollisionShape3D.new()
	var sh := BoxShape3D.new()
	sh.size = size
	cs.shape = sh
	b.add_child(cs)
	add_child(b)
	b.global_position = pos
	return b


func _char(pos: Vector3, radius: float, height: float, layer: int, mask: int) -> CharacterBody3D:
	var c := CharacterBody3D.new()
	c.collision_layer = layer
	c.collision_mask = mask
	var cs := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = radius
	cap.height = height
	cs.shape = cap
	c.add_child(cs)
	add_child(c)
	c.global_position = pos
	return c


func _drive(mover: CharacterBody3D, vel: Vector3, frames: int) -> void:
	for _i in range(frames):
		mover.velocity = vel
		mover.move_and_slide()
		await get_tree().physics_frame


func _clear() -> void:
	for c in get_children():
		c.queue_free()
	await get_tree().physics_frame


# ---- the runs -------------------------------------------------------------
func _run() -> void:
	var L := CollisionLayers

	# item 1: player cannot walk through a house wall.
	_static_box(Vector3(0, 1.5, 0), Vector3(0.4, 3, 10), L.WORLD_STATIC)
	var player := _char(Vector3(-3, 1, 0), 0.35, 1.6, L.PLAYER, L.PROFILES["player"]["mask"])
	await _drive(player, Vector3(6, 0, 0), 120)
	_ok("item01_player_vs_house", player.global_position.x < -0.2,
		"x=%.2f (wall face at -0.2)" % player.global_position.x)
	await _clear()

	# item 2: NPC cannot walk through a wall.
	_static_box(Vector3(0, 1.5, 0), Vector3(0.4, 3, 10), L.WORLD_STATIC)
	var npc := _char(Vector3(-3, 1, 0), 0.35, 1.6, L.NPC, L.PROFILES["npc"]["mask"])
	await _drive(npc, Vector3(6, 0, 0), 120)
	_ok("item02_npc_vs_house", npc.global_position.x < -0.2,
		"x=%.2f" % npc.global_position.x)
	await _clear()

	# item 3: NPC cannot walk through the player.
	var p3 := _char(Vector3(0, 1, 0), 0.35, 1.6, L.PLAYER, L.PROFILES["player"]["mask"])
	var n3 := _char(Vector3(-3, 1, 0), 0.35, 1.6, L.NPC, L.PROFILES["npc"]["mask"])
	await _drive(n3, Vector3(4, 0, 0), 120)
	_ok("item03_npc_vs_player", n3.global_position.x < p3.global_position.x - 0.4,
		"npc.x=%.2f player.x=%.2f" % [n3.global_position.x, p3.global_position.x])
	await _clear()

	# item 4: NPCs cannot occupy the same space.
	var a4 := _char(Vector3(-1, 1, 0), 0.35, 1.6, L.NPC, L.PROFILES["npc"]["mask"])
	var b4 := _char(Vector3(1, 1, 0), 0.35, 1.6, L.NPC, L.PROFILES["npc"]["mask"])
	# push both toward the centre for a while
	for _i in range(120):
		a4.velocity = Vector3(2, 0, 0); a4.move_and_slide()
		b4.velocity = Vector3(-2, 0, 0); b4.move_and_slide()
		await get_tree().physics_frame
	var sep := a4.global_position.distance_to(b4.global_position)
	_ok("item04_npc_npc_no_overlap", sep > 0.6, "separation=%.2f" % sep)
	await _clear()

	# item 5: NPC can pass through a valid doorway (gap between two wall panels).
	_static_box(Vector3(0, 1.5, 3.0), Vector3(0.4, 3, 4.5), L.WORLD_STATIC)   # north panel
	_static_box(Vector3(0, 1.5, -3.0), Vector3(0.4, 3, 4.5), L.WORLD_STATIC)  # south panel
	var d5 := _char(Vector3(-3, 1, 0), 0.35, 1.6, L.NPC, L.PROFILES["npc"]["mask"])
	await _drive(d5, Vector3(6, 0, 0), 120)
	_ok("item05_npc_through_doorway", d5.global_position.x > 0.5,
		"x=%.2f (passed the doorway plane)" % d5.global_position.x)
	await _clear()

	# item 6: vehicle cannot pass through a building.
	_static_box(Vector3(0, 1.5, 0), Vector3(0.4, 3, 12), L.WORLD_STATIC)
	var v6 := _char(Vector3(-4, 1, 0), 1.0, 1.4, L.VEHICLE, L.PROFILES["vehicle"]["mask"])
	await _drive(v6, Vector3(10, 0, 0), 120)
	_ok("item06_vehicle_vs_building", v6.global_position.x < -0.5,
		"x=%.2f" % v6.global_position.x)
	await _clear()

	# item 7: vehicle cannot pass through another vehicle (parked = solid obstacle).
	_static_box(Vector3(0, 0.7, 0), Vector3(2, 1.4, 4.5), L.VEHICLE)
	var v7 := _char(Vector3(-4, 1, 0), 1.0, 1.4, L.VEHICLE, L.PROFILES["vehicle"]["mask"])
	await _drive(v7, Vector3(8, 0, 0), 120)
	# Gate: it stayed on the near side (never emerged past the other vehicle's centre).
	_ok("item07_vehicle_vs_vehicle", v7.global_position.x < -1.0,
		"moving.x=%.2f (blocked left of the parked car, no pass-through)" % v7.global_position.x)
	await _clear()

	# item 8: player cannot walk through a parked car (static, VEHICLE layer).
	_static_box(Vector3(0, 0.7, 0), Vector3(2, 1.4, 4.5), L.VEHICLE)
	var p8 := _char(Vector3(-4, 1, 0), 0.35, 1.6, L.PLAYER, L.PROFILES["player"]["mask"])
	await _drive(p8, Vector3(6, 0, 0), 120)
	_ok("item08_player_vs_parked_car", p8.global_position.x < -0.9,
		"x=%.2f" % p8.global_position.x)
	await _clear()

	# item 9: vehicle physically contacts a pedestrian (contact registered).
	var ped9 := _char(Vector3(0, 1, 0), 0.35, 1.6, L.NPC, L.PROFILES["npc"]["mask"])
	var v9 := _char(Vector3(-4, 1, 0), 1.0, 1.4, L.VEHICLE, L.PROFILES["vehicle"]["mask"])
	var contacted := false
	for _i in range(120):
		v9.velocity = Vector3(8, 0, 0); v9.move_and_slide()
		if v9.get_slide_collision_count() > 0:
			contacted = true
		await get_tree().physics_frame
	_ok("item09_vehicle_contacts_pedestrian", contacted,
		"slide contact registered=%s" % contacted)
	await _clear()

	# item 10: vehicle cannot tunnel a thin barrier at max speed (40 m/s).
	_static_box(Vector3(0, 1.5, 0), Vector3(0.15, 3, 8), L.WORLD_STATIC)  # 15 cm wall
	var v10 := _char(Vector3(-3, 1, 0), 0.4, 1.4, L.VEHICLE, L.PROFILES["vehicle"]["mask"])
	# 40 m/s * 1/60 ≈ 0.67 m/frame, ~4.5x the wall thickness — the tunnel risk.
	await _drive(v10, Vector3(40, 0, 0), 30)
	_ok("item10_anti_tunnel_thin_barrier", v10.global_position.x < -0.05,
		"x=%.3f (never emerged past the 15 cm wall)" % v10.global_position.x)
	await _clear()

	# items 11-13: mobility reacts to a persistent obstacle and restores (in-engine
	# routing via the baked houston mobility.json).
	var ml := MobilityLoader.new()
	var loaded := ml.load_mobility("res://bundles/houston")
	_ok("item11_mobility_artifact_loads", loaded and ml.segments.size() > 0,
		"segments=%d nodes=%d" % [ml.segments.size(), ml.nodes.size()])
	if loaded and ml.segments.size() > 0:
		# pick a segment and route across it
		var sid: String = ml.segments.keys()[0]
		var seg: Dictionary = ml.segments[sid]
		var u: String = seg["u"]
		var v: String = seg["v"]
		var base := ml.route(u, v, "car")
		_ok("item12_route_exists", base.size() >= 1, "hops=%d" % base.size())
		ml.close_segment(sid, ["car", "heavy"])
		var after := ml.route(u, v, "car")
		# The direct edge is closed: the route must no longer traverse u<->v directly.
		_ok("item12b_route_reacts_to_closure", not _uses_segment(after, u, v),
			"direct edge no longer used after closure")
		ml.open_segment(sid)
		var restored := ml.route(u, v, "car")
		_ok("item13_removal_restores_route", _uses_segment(restored, u, v),
			"direct edge usable again after reopening")

	# seam smoke: the body classes instantiate with authority layers in-engine.
	var cb := CitizenBody.new()
	add_child(cb)
	await get_tree().physics_frame
	_ok("seam_citizenbody_layers", cb.collision_layer == L.NPC,
		"layer=%d mask=%d" % [cb.collision_layer, cb.collision_mask])
	var vb := VehicleBody.new()
	add_child(vb)
	await get_tree().physics_frame
	_ok("seam_vehiclebody_layers", vb.collision_layer == L.VEHICLE,
		"layer=%d" % vb.collision_layer)
	await _clear()


func _uses_segment(path: Array, u: String, v: String) -> bool:
	for i in range(path.size() - 1):
		if (path[i] == u and path[i + 1] == v) or (path[i] == v and path[i + 1] == u):
			return true
	return false

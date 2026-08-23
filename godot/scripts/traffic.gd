extends Node3D

## Presentation-only traffic: placeholder vehicles (cars, trucks, motorcycles/
## bikes) driving along the bundle's road polylines. The authoritative Python
## world models commute *modes*, not individual vehicle positions, so this is
## pure ambiance — like the capsule citizens — and never feeds the simulation.
##
## Vehicles ride surface streets at road height and elevated freeways (motorway
## class) up on the deck. Each advances along its polyline every frame and
## respawns on a fresh road at the end.

const DECK_Y := 7.0        # must match street_world elevated deck height
const ROAD_Y := 0.28

class Lane:
	var pts: PackedVector2Array
	var y: float            # surface (0.28) or elevated deck (~7.1)
	var elevated: bool
	var speed_mult: float

class Vehicle:
	var node: MeshInstance3D
	var lane: Lane
	var seg: int
	var along: float        # metres travelled into current segment
	var speed: float
	var half_h: float

var _lanes: Array[Lane] = []
var _vehicles: Array[Vehicle] = []
var _rng := RandomNumberGenerator.new()
var _running := false


func setup(polylines: Array, count: int = 220, seed: int = 1) -> void:
	_rng.seed = seed
	for pl in polylines:
		var pts_raw: Array = pl.get("points", [])
		if pts_raw.size() < 2:
			continue
		var lane := Lane.new()
		lane.pts = PackedVector2Array()
		for p in pts_raw:
			lane.pts.append(Vector2(float(p[0]), float(p[1])))
		var cls := String(pl.get("class", ""))
		lane.elevated = (cls == "motorway" or cls == "trunk")
		lane.y = (DECK_Y + 0.1) if lane.elevated else (ROAD_Y + 0.05)
		lane.speed_mult = 2.2 if lane.elevated else 1.0
		_lanes.append(lane)
	if _lanes.is_empty():
		return
	for i in range(count):
		_spawn_vehicle()
	_running = true


func _spawn_vehicle() -> void:
	var lane: Lane = _lanes[_rng.randi() % _lanes.size()]
	# Elevated freeways carry cars/trucks only; surface streets also carry bikes.
	var kind := _pick_kind(lane.elevated)
	var v := Vehicle.new()
	v.lane = lane
	v.seg = _rng.randi() % max(1, lane.pts.size() - 1)
	v.along = 0.0
	v.node = MeshInstance3D.new()
	var mesh := BoxMesh.new()
	var dims: Vector3 = kind[0]
	mesh.size = dims
	v.half_h = dims.y * 0.5
	var mat := StandardMaterial3D.new()
	mat.albedo_color = kind[1]
	mesh.material = mat
	v.node.mesh = mesh
	v.speed = kind[2] * lane.speed_mult * (0.85 + 0.3 * _rng.randf())
	add_child(v.node)
	_place(v)
	_vehicles.append(v)


func _pick_kind(elevated: bool) -> Array:
	# [dims (w,h,l), colour, base_speed]
	var r := _rng.randf()
	if not elevated and r < 0.22:
		# motorcycle / bike
		var c := Color(0.15, 0.15, 0.18) if _rng.randf() < 0.5 else Color(0.8, 0.2, 0.2)
		return [Vector3(0.7, 1.0, 1.9), c, 9.0]
	if r < 0.5:
		return [Vector3(2.6, 2.9, 8.5), _truck_color(), 8.0]      # truck
	return [Vector3(1.8, 1.4, 4.3), _car_color(), 12.0]          # car


func _car_color() -> Color:
	var palette := [Color(0.85, 0.86, 0.9), Color(0.15, 0.17, 0.22),
		Color(0.6, 0.1, 0.12), Color(0.15, 0.32, 0.6), Color(0.75, 0.7, 0.2)]
	return palette[_rng.randi() % palette.size()]


func _truck_color() -> Color:
	var palette := [Color(0.9, 0.9, 0.92), Color(0.3, 0.35, 0.45), Color(0.5, 0.45, 0.4)]
	return palette[_rng.randi() % palette.size()]


func _process(delta: float) -> void:
	if not _running:
		return
	var step := clampf(delta, 0.0, 0.1)
	for v in _vehicles:
		v.along += v.speed * step
		_place(v)


func _place(v: Vehicle) -> void:
	var lane := v.lane
	var n := lane.pts.size()
	# Advance to the segment that contains `along`, walking forward.
	while true:
		var a: Vector2 = lane.pts[v.seg]
		var b: Vector2 = lane.pts[v.seg + 1]
		var seglen := a.distance_to(b)
		if v.along <= seglen or seglen < 0.001:
			var t := 0.0 if seglen < 0.001 else v.along / seglen
			var pos := a.lerp(b, t)
			v.node.position = Vector3(pos.x, lane.y + v.half_h, pos.y)
			var dir := (b - a)
			if dir.length() > 0.001:
				v.node.rotation.y = atan2(dir.x, dir.y)
			return
		v.along -= seglen
		v.seg += 1
		if v.seg >= n - 1:
			# End of the polyline: respawn on a random road (keeps traffic full).
			v.lane = _lanes[_rng.randi() % _lanes.size()]
			v.seg = 0
			v.along = 0.0
			return

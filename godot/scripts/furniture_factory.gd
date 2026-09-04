class_name FurnitureFactory
extends RefCounted

## Box-built furniture for generated interiors. Every maker returns a
## StaticBody3D (a Lootable when the piece is a container) with meshes and one
## collision box, origin at floor level, facing -Z. Sizes are in meters.

const WOOD := Color(0.5, 0.36, 0.24)
const WOOD_DARK := Color(0.38, 0.27, 0.18)
const FABRIC := Color(0.42, 0.44, 0.5)
const METAL := Color(0.62, 0.64, 0.66)
const WHITE := Color(0.88, 0.88, 0.86)


static func _box(parent: Node3D, size: Vector3, pos: Vector3, color: Color) -> void:
	var mesh := BoxMesh.new()
	mesh.size = size
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mat.roughness = 0.85
	mesh.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.position = pos
	parent.add_child(mi)


static func _body(size: Vector3, lootable: bool) -> StaticBody3D:
	var body: StaticBody3D = Lootable.new() if lootable else StaticBody3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = Vector3(0.0, size.y * 0.5, 0.0)
	body.add_child(cs)
	return body


## footprint (x, z) each maker occupies, used by the placer to avoid overlap
static func footprint_of(piece: String) -> Vector2:
	match piece:
		"table": return Vector2(1.6, 0.9)
		"chair": return Vector2(0.5, 0.5)
		"bed": return Vector2(1.5, 2.1)
		"sofa": return Vector2(1.9, 0.9)
		"shelf": return Vector2(1.8, 0.5)
		"counter": return Vector2(2.4, 0.7)
		"desk": return Vector2(1.5, 0.8)
		"crate": return Vector2(0.9, 0.9)
		"fridge": return Vector2(0.8, 0.8)
		"cabinet": return Vector2(1.0, 0.5)
		_: return Vector2(1.0, 1.0)


static func make(piece: String) -> StaticBody3D:
	match piece:
		"table": return _table()
		"chair": return _chair()
		"bed": return _bed()
		"sofa": return _sofa()
		"shelf": return _shelf()
		"counter": return _counter()
		"desk": return _desk()
		"crate": return _crate()
		"fridge": return _fridge()
		"cabinet": return _cabinet()
		_: return _crate()


static func _table() -> StaticBody3D:
	var b := _body(Vector3(1.6, 0.78, 0.9), false)
	_box(b, Vector3(1.6, 0.06, 0.9), Vector3(0, 0.75, 0), WOOD)
	for sx in [-0.72, 0.72]:
		for sz in [-0.38, 0.38]:
			_box(b, Vector3(0.07, 0.72, 0.07), Vector3(sx, 0.36, sz), WOOD_DARK)
	return b


static func _chair() -> StaticBody3D:
	var b := _body(Vector3(0.5, 0.95, 0.5), false)
	_box(b, Vector3(0.46, 0.05, 0.46), Vector3(0, 0.45, 0), WOOD)
	for sx in [-0.19, 0.19]:
		for sz in [-0.19, 0.19]:
			_box(b, Vector3(0.05, 0.44, 0.05), Vector3(sx, 0.22, sz), WOOD_DARK)
	_box(b, Vector3(0.46, 0.5, 0.05), Vector3(0, 0.72, 0.2), WOOD)
	return b


static func _bed() -> StaticBody3D:
	var b := _body(Vector3(1.5, 0.6, 2.1), false)
	_box(b, Vector3(1.5, 0.25, 2.1), Vector3(0, 0.25, 0), WOOD_DARK)
	_box(b, Vector3(1.44, 0.18, 2.0), Vector3(0, 0.47, 0), WHITE)
	_box(b, Vector3(1.3, 0.12, 0.5), Vector3(0, 0.58, -0.7), Color(0.8, 0.8, 0.85))
	_box(b, Vector3(1.5, 0.8, 0.08), Vector3(0, 0.4, -1.05), WOOD)
	return b


static func _sofa() -> StaticBody3D:
	var b := _body(Vector3(1.9, 0.8, 0.9), false)
	_box(b, Vector3(1.9, 0.4, 0.9), Vector3(0, 0.2, 0), FABRIC)
	_box(b, Vector3(1.9, 0.45, 0.22), Vector3(0, 0.6, 0.34), FABRIC)
	for sx in [-0.84, 0.84]:
		_box(b, Vector3(0.22, 0.6, 0.9), Vector3(sx, 0.3, 0), FABRIC.darkened(0.15))
	return b


static func _shelf() -> StaticBody3D:
	var b := _body(Vector3(1.8, 1.9, 0.5), true)
	(b as Lootable).display_name = "Shelf"
	_box(b, Vector3(1.8, 0.05, 0.5), Vector3(0, 0.05, 0), WOOD_DARK)
	for h in [0.55, 1.05, 1.55]:
		_box(b, Vector3(1.76, 0.04, 0.46), Vector3(0, h, 0), WOOD)
	for sx in [-0.88, 0.88]:
		_box(b, Vector3(0.05, 1.9, 0.5), Vector3(sx, 0.95, 0), WOOD_DARK)
	_box(b, Vector3(1.8, 1.9, 0.04), Vector3(0, 0.95, -0.23), WOOD_DARK.darkened(0.2))
	return b


static func _counter() -> StaticBody3D:
	var b := _body(Vector3(2.4, 1.0, 0.7), true)
	(b as Lootable).display_name = "Counter"
	_box(b, Vector3(2.4, 0.9, 0.7), Vector3(0, 0.45, 0), WOOD_DARK)
	_box(b, Vector3(2.5, 0.08, 0.8), Vector3(0, 0.94, 0), Color(0.75, 0.73, 0.7))
	return b


static func _desk() -> StaticBody3D:
	var b := _body(Vector3(1.5, 0.78, 0.8), true)
	(b as Lootable).display_name = "Desk"
	_box(b, Vector3(1.5, 0.06, 0.8), Vector3(0, 0.74, 0), WOOD)
	for sx in [-0.68, 0.68]:
		_box(b, Vector3(0.08, 0.72, 0.74), Vector3(sx, 0.36, 0), WOOD_DARK)
	_box(b, Vector3(0.5, 0.3, 0.35), Vector3(0.2, 0.92, 0.05), Color(0.15, 0.16, 0.18))
	return b


static func _crate() -> StaticBody3D:
	var b := _body(Vector3(0.9, 0.9, 0.9), true)
	(b as Lootable).display_name = "Crate"
	_box(b, Vector3(0.9, 0.9, 0.9), Vector3(0, 0.45, 0), WOOD)
	_box(b, Vector3(0.94, 0.1, 0.94), Vector3(0, 0.85, 0), WOOD_DARK)
	return b


static func _fridge() -> StaticBody3D:
	var b := _body(Vector3(0.8, 1.8, 0.8), true)
	(b as Lootable).display_name = "Fridge"
	_box(b, Vector3(0.8, 1.8, 0.8), Vector3(0, 0.9, 0), WHITE)
	_box(b, Vector3(0.06, 0.5, 0.06), Vector3(0.3, 1.1, -0.42), METAL)
	return b


static func _cabinet() -> StaticBody3D:
	var b := _body(Vector3(1.0, 1.1, 0.5), true)
	(b as Lootable).display_name = "Cabinet"
	_box(b, Vector3(1.0, 1.1, 0.5), Vector3(0, 0.55, 0), WOOD_DARK)
	for sx in [-0.24, 0.24]:
		_box(b, Vector3(0.04, 0.3, 0.04), Vector3(sx, 0.6, -0.26), METAL)
	return b

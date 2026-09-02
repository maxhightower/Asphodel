class_name IsometricCutaway
extends Node

## Interior cutaway for the isometric view (ISO-5).
##
## When the player is inside an authoritative interior, an overhead camera would
## otherwise be blocked by the roof/ceiling and the near walls. This node reduces
## that obstruction WITHOUT rebuilding the interior and WITHOUT any tile geometry:
##   * the ceiling is hidden outright;
##   * each generated wall segment carries an outward normal (attached by
##     InteriorBuilder); walls whose normal faces the camera are hidden (or faded),
##     so you look "into" the rooms from the current view angle.
## The interior's authoritative truth (descriptor geometry, fixture ids, container
## linkage, occupants) is untouched — this only decides what is VISIBLE. Collision
## on hidden walls is deliberately left intact so the player stays bounded.
##
## Rotating the camera re-evaluates which walls face it, so a 90-degree turn
## reveals the previously-near rooms — the Project-Zomboid reading, over Asphodel's
## continuous interior descriptor rather than a tile grid.

@export var face_threshold: float = 0.30   # hide walls whose outward normal·view < -this
@export var fade: bool = false             # true = fade to alpha; false = hard hide
@export var fade_alpha: float = 0.12

var camera: Camera3D = null
var _interior: Node3D = null
var _hidden := 0


## Begin cutting away `interior_root` for `cam`. Hides the ceiling at once and does
## a first wall pass. Safe to call again to retarget.
func apply(interior_root: Node3D, cam: Camera3D) -> void:
	_interior = interior_root
	camera = cam
	_hide_ceiling()
	_update_walls()


func clear() -> void:
	_interior = null
	_hidden = 0


func hidden_wall_count() -> int:
	return _hidden


func _hide_ceiling() -> void:
	if _interior == null or not is_instance_valid(_interior):
		return
	var ceil := _interior.get_node_or_null("Ceiling")
	if ceil != null:
		ceil.visible = false


func _process(_delta: float) -> void:
	if _interior != null and is_instance_valid(_interior) and camera != null and is_instance_valid(camera):
		_update_walls()


func _view_dir_h() -> Vector3:
	var f := -camera.global_transform.basis.z
	f.y = 0.0
	if f.length() < 0.001:
		return Vector3(0.0, 0.0, -1.0)
	return f.normalized()


func _update_walls() -> void:
	if _interior == null or not is_instance_valid(_interior):
		return
	var view := _view_dir_h()
	var count := 0
	for w in _interior_walls():
		if not is_instance_valid(w):
			continue
		var n2: Vector2 = w.get_meta("wall_normal", Vector2.ZERO)
		if n2 == Vector2.ZERO:
			continue
		var n := Vector3(n2.x, 0.0, n2.y)
		# A wall whose outward normal points back toward the camera (normal·view < 0)
		# stands between the camera and the room interior — hide it.
		var hide := n.dot(view) < -face_threshold
		_set_wall_visible(w, not hide)
		if hide:
			count += 1
	_hidden = count


func _interior_walls() -> Array:
	# Walls tagged by InteriorBuilder. Only the active interior is materialized at a
	# time (the world frees the previous), so the group is this interior's walls.
	var out: Array = []
	for w in _interior.get_tree().get_nodes_in_group("interior_walls"):
		if _interior.is_ancestor_of(w):
			out.append(w)
	return out


func _set_wall_visible(w: Node, vis: bool) -> void:
	if not fade:
		w.visible = vis
		return
	# Fade path: keep the node visible but drop its material alpha.
	w.visible = true
	if w is MeshInstance3D and w.mesh != null and w.mesh.material is StandardMaterial3D:
		var mat: StandardMaterial3D = w.mesh.material
		if vis:
			mat.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED
			mat.albedo_color.a = 1.0
		else:
			mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			mat.albedo_color.a = fade_alpha

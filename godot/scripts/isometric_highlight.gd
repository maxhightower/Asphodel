class_name IsometricHighlight
extends Node3D

## Presentation-only selection / target feedback for the isometric view (ISO-4).
##
## Draws a subtle marker under the player and a highlight ring at the currently
## targeted entity, so interaction is discoverable without first-person aiming and
## without permanent intrusive UI. This node owns NO gameplay state: it is told a
## continuous world position to mark and it draws a ring there. Identity always
## lives in the entity IDs the interaction layer resolves, never in these meshes.

const RING_COL_DEFAULT := Color(0.95, 0.9, 0.35)
const RING_COL_NPC := Color(0.45, 0.85, 1.0)
const RING_COL_BUILDING := Color(0.6, 1.0, 0.6)
const RING_COL_FIXTURE := Color(1.0, 0.7, 0.4)
const RING_COL_EXIT := Color(1.0, 0.5, 0.5)
const PLAYER_COL := Color(1.0, 1.0, 1.0, 0.85)

var _target_ring: MeshInstance3D
var _player_ring: MeshInstance3D
var _t := 0.0


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_target_ring = _make_ring(0.9)
	_target_ring.visible = false
	add_child(_target_ring)
	_player_ring = _make_ring(0.6)
	_set_ring_color(_player_ring, PLAYER_COL)
	add_child(_player_ring)


func _make_ring(radius: float) -> MeshInstance3D:
	var torus := TorusMesh.new()
	torus.inner_radius = radius * 0.82
	torus.outer_radius = radius
	torus.rings = 8
	torus.ring_segments = 24
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.albedo_color = RING_COL_DEFAULT
	mat.no_depth_test = true
	torus.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = torus
	return mi


func _set_ring_color(mi: MeshInstance3D, col: Color) -> void:
	var mat: StandardMaterial3D = mi.mesh.material
	if mat != null:
		mat.albedo_color = col


func _color_for(kind: int) -> Color:
	match kind:
		IsometricInteraction.CITIZEN, IsometricInteraction.OCCUPANT:
			return RING_COL_NPC
		IsometricInteraction.BUILDING:
			return RING_COL_BUILDING
		IsometricInteraction.FIXTURE:
			return RING_COL_FIXTURE
		IsometricInteraction.EXIT:
			return RING_COL_EXIT
		_:
			return RING_COL_DEFAULT


## Mark the current target at a continuous world position, tinted by entity kind.
func show_target(world_pos: Vector3, kind: int) -> void:
	_target_ring.global_position = world_pos + Vector3(0.0, 0.15, 0.0)
	_set_ring_color(_target_ring, _color_for(kind))
	_target_ring.visible = true


func clear_target() -> void:
	_target_ring.visible = false


## Keep the player marker under the player each frame (continuous position).
func mark_player(world_pos: Vector3) -> void:
	_player_ring.global_position = world_pos + Vector3(0.0, 0.1, 0.0)


func _process(delta: float) -> void:
	# Gentle pulse so the target ring reads as "selected" without a UI panel.
	_t += delta
	var s := 1.0 + 0.12 * sin(_t * 4.0)
	if _target_ring.visible:
		_target_ring.scale = Vector3(s, 1.0, s)

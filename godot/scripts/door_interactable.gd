class_name DoorInteractable
extends StaticBody3D

## A hinged door panel filling a doorway gap in a building wall. The body sits
## at the hinge; interacting swings the panel 105° open (or closed again), so
## players can walk from the street into generated interiors.

const WIDTH := 1.3
const HEIGHT := 2.2
const THICK := 0.07

var _open := false
var _panel: MeshInstance3D
var _tween: Tween
var _base_y := 0.0   # installed orientation; swing is relative to it


func _ready() -> void:
	_base_y = rotation.y


static func make(color: Color) -> DoorInteractable:
	var door := DoorInteractable.new()
	var mesh := BoxMesh.new()
	mesh.size = Vector3(WIDTH, HEIGHT, THICK)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mat.roughness = 0.7
	mesh.material = mat
	door._panel = MeshInstance3D.new()
	door._panel.mesh = mesh
	# hinge at the body origin: panel extends +x from it
	door._panel.position = Vector3(WIDTH * 0.5, HEIGHT * 0.5, 0.0)
	door.add_child(door._panel)

	var shape := BoxShape3D.new()
	shape.size = mesh.size
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = door._panel.position
	door.add_child(cs)

	# knob
	var knob := SphereMesh.new()
	knob.radius = 0.045
	knob.height = 0.09
	var knob_mi := MeshInstance3D.new()
	knob_mi.mesh = knob
	knob_mi.position = Vector3(WIDTH - 0.12, HEIGHT * 0.48, THICK)
	door.add_child(knob_mi)
	return door


func prompt() -> String:
	return "E — Close door" if _open else "E — Open door"


func interact(_player: Node) -> void:
	_open = not _open
	if _tween != null and _tween.is_valid():
		_tween.kill()
	_tween = create_tween()
	_tween.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
	var target := _base_y + (-1.833 if _open else 0.0)   # ~105 degrees
	_tween.tween_property(self, "rotation:y", target, 0.35)

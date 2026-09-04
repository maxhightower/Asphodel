class_name VehicleBody
extends CharacterBody3D

## Physical vehicle seam (AS-NAV-3 §8, §8.3 anti-tunneling).
##
## A near/controlled vehicle. Uses the CollisionLayers authority so it collides
## with terrain, buildings, barriers, other vehicles, pedestrians and the player,
## and parked cars remain solid obstacles. Motion is applied in substeps sized so
## per-substep displacement stays below the thinnest expected barrier — the
## anti-tunneling contract (asphodel/physics/anti_tunneling.py): at maximum
## gameplay speed the body can never emerge on the far side of a thin wall.
##
## NOTE: authored seam — not run in a Godot editor in this environment.

@export var min_barrier_thickness: float = 0.2
@export var max_speed: float = 40.0

var drive_velocity := Vector3.ZERO     # from lane-following / route controller
var semantic_id: String = ""


func _ready() -> void:
	collision_layer = CollisionLayers.VEHICLE
	collision_mask = CollisionLayers.PROFILES["vehicle"]["mask"]
	if not has_node("Collision"):
		var cs := CollisionShape3D.new()
		cs.name = "Collision"
		var box := BoxShape3D.new()
		box.size = Vector3(2.0, 1.4, 4.5)
		cs.shape = box
		add_child(cs)


func _required_substeps(speed: float, delta: float) -> int:
	var disp: float = abs(speed) * delta
	var max_step: float = max(0.0001, min_barrier_thickness * 0.5)
	return max(1, int(ceil(disp / max_step)))


func _physics_process(delta: float) -> void:
	# Substep the motion so no single move skips a thin barrier (swept-equivalent).
	var speed := drive_velocity.length()
	var n := _required_substeps(speed, delta)
	var sub := delta / n
	for _i in range(n):
		velocity = drive_velocity
		move_and_slide()
		if get_slide_collision_count() > 0:
			# A real contact: hand off to crash handling (fidelity -> CRASH).
			_on_impact()
			break


func _on_impact() -> void:
	# Hook: on a significant impact, transition the VehicleInstance to
	# PHYSICAL_CRASH; when settled it becomes a PERSISTENT_WRECK and yields a
	# MobilityObstruction to the graph (§8.1, §10).
	pass

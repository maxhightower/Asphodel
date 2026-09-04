class_name CitizenBody
extends CharacterBody3D

## Physical NPC body seam (AS-PHYS-0 §4.4, AS-NAV-2 §7).
##
## The authoritative physical object a near citizen follows. The visual avatar is
## a CHILD that follows this body — the planner never sets the transform directly;
## it supplies a desired velocity and physics decides where the body actually
## moves. Everyday locomotion is a cheap capsule (ragdoll is reserved for
## falls/death). Layers/masks come from the generated CollisionLayers authority so
## the NPC cannot pass through walls, the player, cars, or other NPCs, but can fit
## through a correctly sized doorway; crowd bottlenecks emerge from real collision.
##
## NOTE: authored seam — not run in a Godot editor in this environment.

@export var walk_speed: float = 1.4
@export var avoid_radius: float = 1.5

var desired_velocity := Vector3.ZERO   # set by the local-navigation layer
var semantic_id: String = ""           # stable citizen id across LOD (§12)

var _gravity := 20.0


func _ready() -> void:
	collision_layer = CollisionLayers.NPC
	collision_mask = CollisionLayers.PROFILES["npc"]["mask"]
	if not has_node("Collision"):
		var cap := CollisionShape3D.new()
		cap.name = "Collision"
		var shape := CapsuleShape3D.new()
		shape.radius = 0.35
		shape.height = 1.8
		cap.shape = shape
		add_child(cap)
	# A sensor Area on the TRIGGER layer for doors/hazards (senses, never blocks).
	if not has_node("Sensor"):
		var area := Area3D.new()
		area.name = "Sensor"
		area.collision_layer = CollisionLayers.TRIGGER
		area.collision_mask = CollisionLayers.NPC | CollisionLayers.VEHICLE
		add_child(area)


func _physics_process(delta: float) -> void:
	# Desired velocity from navigation + local avoidance; physics has final say.
	var v := desired_velocity
	v.y = velocity.y - _gravity * delta
	velocity = v
	move_and_slide()
	# Collision detected by physics is the truth; a repeatedly stuck body reports
	# a blockage upward so the strategic layer can replan (§7.2).
	if get_slide_collision_count() > 0 and desired_velocity.length() > 0.1:
		_maybe_report_blockage()


func _maybe_report_blockage() -> void:
	# Hook: emit to the citizen runtime's on_blockage() after N stuck frames.
	pass

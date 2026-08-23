extends CharacterBody3D

## First-person walker. Builds its own capsule collider + eye-height camera in
## _ready so the spawner only has to instance it and set a position. Movement and
## look are gated on the mouse being captured, so a pause overlay (which frees the
## cursor) naturally freezes the player.
##
## Also owns the survival loop's interaction side: an aim raycast that finds
## doors and lootable containers (anything exposing prompt()/interact()), and a
## small resource inventory filled by looting.

signal prompt_changed(text: String)
signal inventory_changed(inventory: Dictionary)
signal looted(items: Dictionary)

@export var walk_speed: float = 4.5
@export var sprint_speed: float = 9.0
@export var mouse_sensitivity: float = 0.0025
@export var eye_height: float = 1.7
@export var interact_range: float = 2.7

const _GRAVITY := 20.0

var inventory := {"food": 0, "water": 0, "meds": 0, "materials": 0, "valuables": 0}

var _camera: Camera3D
var _target: Node = null
var _prompt := ""


func _ready() -> void:
	add_to_group("player")
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.35
	capsule.height = 1.8
	var col := CollisionShape3D.new()
	col.shape = capsule
	col.position = Vector3(0.0, 0.9, 0.0)   # feet near y=0
	add_child(col)

	_camera = Camera3D.new()
	_camera.position = Vector3(0.0, eye_height, 0.0)
	_camera.far = 12000.0                    # see across the km-scale city
	add_child(_camera)
	_camera.current = true

	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * mouse_sensitivity)
		_camera.rotate_x(-event.relative.y * mouse_sensitivity)
		_camera.rotation.x = clampf(_camera.rotation.x, -1.4, 1.4)


func add_items(items: Dictionary) -> void:
	for k in items:
		inventory[k] = int(inventory.get(k, 0)) + int(items[k])
	inventory_changed.emit(inventory)
	looted.emit(items)


func _update_interact_target() -> void:
	var new_target: Node = null
	if _camera != null and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var from := _camera.global_position
		var to := from + (-_camera.global_transform.basis.z) * interact_range
		var query := PhysicsRayQueryParameters3D.create(from, to)
		query.exclude = [get_rid()]
		var hit := get_world_3d().direct_space_state.intersect_ray(query)
		if not hit.is_empty():
			var collider: Object = hit.get("collider")
			if collider is Node and (collider as Object).has_method("interact"):
				new_target = collider
	_target = new_target
	var text := ""
	if _target != null and _target.has_method("prompt"):
		text = str(_target.call("prompt"))
	if text != _prompt:
		_prompt = text
		prompt_changed.emit(text)


func _unhandled_key_input(event: InputEvent) -> void:
	if event.is_action_pressed("interact") and _target != null \
			and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_target.call("interact", self)


func _physics_process(delta: float) -> void:
	_update_interact_target()
	if Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
		var dir := (transform.basis * Vector3(input_dir.x, 0.0, input_dir.y))
		dir.y = 0.0
		dir = dir.normalized()
		var speed := sprint_speed if Input.is_action_pressed("sprint") else walk_speed
		velocity.x = dir.x * speed
		velocity.z = dir.z * speed
	else:
		velocity.x = 0.0
		velocity.z = 0.0

	if not is_on_floor():
		velocity.y -= _GRAVITY * delta
	else:
		velocity.y = 0.0

	move_and_slide()

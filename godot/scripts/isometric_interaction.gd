class_name IsometricInteraction
extends Node

## Presentation-independent interaction targeting for the isometric view (ISO-4).
##
## Replaces the first-person "look directly at an object -> raycast -> press E"
## model with a targeting system that works from an overhead camera and does NOT
## depend on the player aiming. Targets are resolved by CONTINUOUS-DISTANCE and
## SCREEN-SPACE proximity over a candidate list of real entities, each carrying an
## authoritative id (citizen_id / building_id / container_index). Node names are
## never used as identity — only ids the world supplies.
##
## Resolution priority (the mission's recommended order):
##   1. eligible entity under the cursor (screen-space pick; works for MultiMesh
##      crowds too, since we project each candidate's world position, not raycast);
##   2. the currently selected entity, if still eligible;
##   3. the nearest eligible entity within the interaction radius of the player;
##   4. no interaction.
##
## The candidate list is produced by the world orchestrator every frame from the
## authoritative snapshot (outdoor citizens, the nearest enterable building) and
## from the active interior subtree (occupants, fixtures, exit). This node only
## RANKS candidates and reports affordances; the world executes the chosen action
## through SimBridge and applies nothing before Python accepts it.

# Entity kinds. Stable ints so isometric_highlight can colour by kind.
enum { NONE = 0, CITIZEN = 1, BUILDING = 2, FIXTURE = 3, OCCUPANT = 4, EXIT = 5 }

@export var interaction_radius: float = 8.0
@export var cursor_pixel_radius: float = 46.0   # screen tolerance for "under cursor"

var player: Node3D = null
var camera: Camera3D = null

# Callable() -> Array[Dictionary]; each candidate is
#   {kind:int, id:int, position:Vector3, meta:Dictionary}
var candidate_provider: Callable = Callable()

var _selected: Dictionary = {}


func configure(p: Node3D, cam: Camera3D, provider: Callable) -> void:
	player = p
	camera = cam
	candidate_provider = provider


func _candidates() -> Array:
	if candidate_provider.is_valid():
		var out = candidate_provider.call()
		if out is Array:
			return out
	return []


## Resolve the current interaction target. `use_cursor` lets a headless test drive
## nearest-only selection deterministically without a real mouse.
func resolve_target(use_cursor: bool = true) -> Dictionary:
	var candidates := _candidates()
	if candidates.is_empty():
		return {}

	# 1. entity under the cursor
	if use_cursor and camera != null and is_instance_valid(camera):
		var picked := _pick_under_cursor(candidates)
		if not picked.is_empty():
			return picked

	# 2. the current selection, if still present and eligible
	if not _selected.is_empty():
		for c in candidates:
			if int(c.get("kind", NONE)) == int(_selected.get("kind", NONE)) \
					and int(c.get("id", -1)) == int(_selected.get("id", -1)):
				if _within_radius(c):
					return c

	# 3. nearest eligible within the interaction radius
	return _nearest_within_radius(candidates)


func _pick_under_cursor(candidates: Array) -> Dictionary:
	var vp := camera.get_viewport()
	if vp == null:
		return {}
	var mouse := vp.get_mouse_position()
	var best := {}
	var best_px := cursor_pixel_radius
	for c in candidates:
		var wp: Vector3 = c.get("position", Vector3.ZERO)
		if camera.is_position_behind(wp):
			continue
		var sp := camera.unproject_position(wp)
		var px := sp.distance_to(mouse)
		if px < best_px:
			best_px = px
			best = c
	return best


func _within_radius(c: Dictionary) -> bool:
	if player == null:
		return true
	var wp: Vector3 = c.get("position", Vector3.ZERO)
	return _planar_dist(wp, player.global_position) <= interaction_radius


func _nearest_within_radius(candidates: Array) -> Dictionary:
	if player == null:
		return {}
	var best := {}
	var best_d := interaction_radius * interaction_radius
	var pp := player.global_position
	for c in candidates:
		var wp: Vector3 = c.get("position", Vector3.ZERO)
		var dx := wp.x - pp.x
		var dz := wp.z - pp.z
		var d := dx * dx + dz * dz
		if d < best_d:
			best_d = d
			best = c
	return best


static func _planar_dist(a: Vector3, b: Vector3) -> float:
	var dx := a.x - b.x
	var dz := a.z - b.z
	return sqrt(dx * dx + dz * dz)


func set_selected(t: Dictionary) -> void:
	_selected = t


func get_selected() -> Dictionary:
	return _selected


func clear_selected() -> void:
	_selected = {}


## Contextual actions offered for a target. This is the forward-compatibility hook
## the mission asks for: today it maps entity kind -> the bridge commands that
## already exist, but the SHAPE is `query_affordances(entity) -> [action]`, so a
## later Semantic-Action layer can replace this body with a Python affordance query
## (ASK / INFORM / GIVE / RETRIEVE / ...) without changing any caller.
func query_affordances(target: Dictionary) -> Array:
	if target.is_empty():
		return []
	match int(target.get("kind", NONE)):
		CITIZEN, OCCUPANT:
			# "Talk" is the dialogue affordance (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1):
			# the world sends TALK and the authority decides whether the two can
			# speak at all (availability + co-presence).
			return ["Interact", "Talk"]
		BUILDING:
			return ["Enter"]
		FIXTURE:
			return ["Search"]
		EXIT:
			return ["Leave"]
		_:
			return []


## Human-readable label for the current target (HUD / hover surface).
func describe(target: Dictionary) -> String:
	if target.is_empty():
		return ""
	match int(target.get("kind", NONE)):
		CITIZEN:
			return "Citizen %d" % int(target.get("id", -1))
		OCCUPANT:
			return "Citizen %d (indoors)" % int(target.get("id", -1))
		BUILDING:
			return "Building %d" % int(target.get("id", -1))
		FIXTURE:
			return "%s" % str(target.get("meta", {}).get("label", "Container"))
		EXIT:
			return "Exit"
		_:
			return ""

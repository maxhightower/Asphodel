extends CanvasLayer

## Living-city debug overlay (§19).
##
## Renders the mandated inspectable state for the selected citizen and vehicle and
## the terrain LOD, so the simulation is understandable by inspection. It reads the
## same machine-readable debug() dictionaries the Python CitizenRuntime and
## VehicleInstance emit (relayed to Godot each frame), so what you see is exactly
## what the sim believes.
##
## Fields (per §19): citizen ID, active goal, destination, mobility mode, route,
## current road segment, physical/semantic LOD, vehicle ID, obstruction state,
## terrain chunk LOD. Toggle with F3.
##
## NOTE: authored seam — not run in a Godot editor in this environment.

@export var enabled: bool = true

var _label: Label
var citizen_debug := {}      # the CitizenRuntime.debug() dict
var vehicle_debug := {}      # the VehicleInstance.to_dict() dict
var terrain_lod := {}        # {chunk_key: lod, ...} for chunks near the camera
var obstructions := []       # active MobilityObstruction dicts


func _ready() -> void:
	_label = Label.new()
	_label.position = Vector2(16, 16)
	_label.add_theme_font_size_override("font_size", 14)
	add_child(_label)


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_F3:
		enabled = not enabled
		_label.visible = enabled


func _process(_delta: float) -> void:
	if not enabled:
		return
	_label.text = _compose()


func _compose() -> String:
	var lines := []
	if not citizen_debug.is_empty():
		lines.append("CITIZEN %s" % citizen_debug.get("citizen_id", "?"))
		var g: Variant = citizen_debug.get("active_goal", null)
		if g != null:
			lines.append("  goal: %s(%s)" % [g.get("kind", "?"), g.get("target", "?")])
			lines.append("  why:  %s" % citizen_debug.get("why", ""))
		lines.append("  dest: %s   mode: %s" % [
			citizen_debug.get("destination", "-"), citizen_debug.get("mode", "-")])
		var plan: Variant = citizen_debug.get("plan", null)
		if plan != null:
			var steps := []
			for s in plan.get("steps", []):
				steps.append(s.get("kind", "?"))
			lines.append("  plan: %s" % ", ".join(steps))
		if citizen_debug.get("last_replan", null) != null:
			lines.append("  replan: %s" % citizen_debug["last_replan"])
		if citizen_debug.get("current_failure", null) != null:
			lines.append("  FAILURE: %s" % citizen_debug["current_failure"])
	if not vehicle_debug.is_empty():
		lines.append("VEHICLE %s  fidelity: %s  seg: %s  progress: %.2f" % [
			vehicle_debug.get("vehicle_id", "?"), vehicle_debug.get("fidelity", "?"),
			vehicle_debug.get("segment", "-"), vehicle_debug.get("route_progress", 0.0)])
	if obstructions.size() > 0:
		lines.append("OBSTRUCTIONS: %d active" % obstructions.size())
		for o in obstructions:
			lines.append("  %s on %s (%.0f%% blocked)" % [
				o.get("kind", "?"), o.get("affected_segment", "?"),
				100.0 * float(o.get("blocked_fraction", 0.0))])
	if not terrain_lod.is_empty():
		lines.append("TERRAIN LOD: %s" % str(terrain_lod))
	return "\n".join(lines)

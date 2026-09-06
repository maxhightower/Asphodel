class_name BuildOverlay
extends CanvasLayer

## Build / metadata overlay (ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2, §11/§23).
##
## A small, always-available corner surface that names exactly WHICH client is
## talking to WHICH authority, so a stale or mismatched pairing is visible at a
## glance rather than showing up as an "old city on a new backend". It reads only
## already-fetched, authoritative identity — it issues NO bridge command and
## advances nothing. Refreshes on a ~0.25s Timer, never per-frame.
##
## Shows:
##   * Godot build SHA   — from a generated res://build_info.json, else "dev"
##   * Simulation SHA    — SimBridge.last_summary.sim_sha (echoed from the
##                         authority's build_info(); also in last_hello)
##   * Protocol version  — SimBridge.PROTOCOL_VERSION vs the handshake's value
##   * City / bundle     — SimBridge.last_summary.city
##   * Sim connection    — SimBridge.is_connected_to_sim()
##   * Game time         — GameClock.game_day / GameClock.hour
##   * Feature flags     — mobility / work / cognition / dialogue / groups / outbreak
##
## Public API: toggle(), refresh(), set_bridge(bridge). Toggle key F10 is handled
## here so the integrator need not edit this file; it may also call toggle().

const REFRESH_S := 0.25

var _bridge = null
var _clock = null
var _godot_sha := ""
var _shown := true

var last_render: Dictionary = {}

var _root: PanelContainer
var _body: Label
var _timer: Timer


func _init() -> void:
	layer = 11


func _ready() -> void:
	_godot_sha = _read_godot_sha()
	# Bind the autoloads by default; set_bridge can override the bridge for tests.
	_bridge = get_node_or_null("/root/SimBridge")
	_clock = get_node_or_null("/root/GameClock")
	_build()
	visible = _shown
	_timer = Timer.new()
	_timer.wait_time = REFRESH_S
	_timer.one_shot = false
	_timer.timeout.connect(refresh)
	add_child(_timer)
	_timer.start()
	refresh()


# ------------------------------------------------------------------ public API
func set_bridge(bridge) -> void:
	_bridge = bridge
	refresh()


func toggle() -> void:
	_shown = not _shown
	visible = _shown


func is_shown() -> bool:
	return _shown


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo \
			and event.keycode == KEY_F10:
		toggle()
		get_viewport().set_input_as_handled()


# ------------------------------------------------------------------ refresh
func refresh() -> void:
	var connected: bool = _bridge != null and _bridge.has_method("is_connected_to_sim") \
		and _bridge.is_connected_to_sim()
	var summary: Dictionary = {}
	if _bridge != null and "last_summary" in _bridge:
		var s = _bridge.last_summary
		summary = s if s is Dictionary else {}

	var sim_sha := _short(str(summary.get("sim_sha", "—")))
	var proto = summary.get("protocol_version", null)
	# The version this client speaks is a class constant (not a property, so `in`
	# / get() won't see it); read it from the SimBridge autoload directly.
	var speaks := -1
	var sb = get_node_or_null("/root/SimBridge")
	if sb != null:
		speaks = int(sb.PROTOCOL_VERSION)
	var city := str(summary.get("city", "—"))
	var day := 0
	var hour := 0.0
	if _clock != null:
		if "game_day" in _clock:
			day = int(_clock.game_day)
		if "hour" in _clock:
			hour = float(_clock.hour)

	var flags := {
		"mobility": _flag("mobility_enabled"),
		"work": _flag("work_enabled"),
		"cognition": _flag("cognition_enabled"),
		"dialogue": _flag("dialogue_enabled"),
		"groups": _flag("groups_enabled"),
		"outbreak": _flag("outbreak_enabled")}

	last_render = {
		"godot_sha": _godot_sha,
		"sim_sha": str(summary.get("sim_sha", "—")),
		"protocol_reported": proto,
		"protocol_speaks": speaks,
		"city": city,
		"connected": connected,
		"game_day": day,
		"hour": hour,
		"flags": flags}

	var on := []
	for k in flags:
		if flags[k]:
			on.append(k)

	var lines: Array[String] = []
	lines.append("ASPHODEL BUILD")
	lines.append("godot   %s" % _short(_godot_sha))
	lines.append("sim     %s" % sim_sha)
	lines.append("proto   v%s (speaks v%d)" % [str(proto) if proto != null else "—", speaks])
	lines.append("city    %s" % city)
	lines.append("sim     %s" % ("CONNECTED" if connected else "OFFLINE"))
	lines.append("time    Day %d  %02d:%02d" % [day, int(hour), int((hour - int(hour)) * 60.0)])
	lines.append("flags   %s" % ("—" if on.is_empty() else " ".join(on)))
	_body.text = "\n".join(lines)


func rendered_text() -> String:
	return _body.text if _body != null else ""


# ------------------------------------------------------------------ helpers
func _flag(name: String) -> bool:
	if _bridge == null or not (name in _bridge):
		return false
	return bool(_bridge.get(name))


func _short(sha: String) -> String:
	if sha == null or sha == "" or sha == "—":
		return "—"
	return sha.substr(0, 10) if sha.length() > 10 else sha


func _read_godot_sha() -> String:
	## A committed/generated build stamp; absent in a dev checkout -> "dev".
	if not FileAccess.file_exists("res://build_info.json"):
		return "dev"
	var f := FileAccess.open("res://build_info.json", FileAccess.READ)
	if f == null:
		return "dev"
	var txt := f.get_as_text()
	f.close()
	var parsed = JSON.parse_string(txt)
	if parsed is Dictionary:
		var sha = parsed.get("sha", parsed.get("commit", "dev"))
		return str(sha) if sha != null else "dev"
	return "dev"


# ------------------------------------------------------------------ layout
func _build() -> void:
	_root = PanelContainer.new()
	_root.set_anchors_preset(Control.PRESET_TOP_LEFT)
	_root.offset_left = 12
	_root.offset_top = 12
	_root.offset_right = 320
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 10)
	margin.add_theme_constant_override("margin_right", 10)
	margin.add_theme_constant_override("margin_top", 8)
	margin.add_theme_constant_override("margin_bottom", 8)
	_root.add_child(margin)

	_body = Label.new()
	_body.add_theme_font_size_override("font_size", 12)
	_body.text = "ASPHODEL BUILD"
	margin.add_child(_body)

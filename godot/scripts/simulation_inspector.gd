class_name SimulationInspector
extends CanvasLayer

## Simulation Inspector — a READ-ONLY observer surface on the authoritative
## Python world (ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2, §19–§25 visibility).
##
## THE INSPECTOR INVENTS NO SIMULATION FACT. Every value it renders is a field
## the authority put in a GET_CITIZEN_CONTEXT / GET_GROUPS / GROUP_QUERY reply;
## this script parses and lays those out and NOTHING else. It never advances the
## world and never calls a mutating bridge method — the only bridge calls it makes
## are get_citizen_context(), get_groups_snapshot() and group_query() with the
## read-only ops "membership"/"where" (never "ask_to_join", which would run a real
## admission decision). `_mutations` is kept at 0 by construction as a witness.
##
## Two explicitly-labelled modes (§22):
##   PLAYER    — only what the player's own character could legitimately know or
##               perceive: identity, physical presence, the visible current
##               activity, and who is co-present. It does NOT read the NPC's mind
##               (memories/beliefs) or its hidden infection state.
##   DEV TRUTH — the full authority state, including cognition (salient memories,
##               active beliefs, perceived danger, avoidances) and health.
## Tab toggles the mode while the panel is shown (re-renders the cached context,
## no new fetch). The context fetch runs on a ~0.5s Timer and ONLY for the
## selected/followed citizen (§35 — never poll every citizen every frame).
##
## Public API (the integrator wires these; it never edits this file):
##   set_bridge(bridge)          bind the SimBridge autoload (or any object with
##                               the same read-only method surface)
##   set_selected(citizen_id)    choose the citizen to inspect (< 0 clears)
##   toggle()                    show / hide the panel
##   refresh()                   do one fetch + render now (also driven by Timer)
##
## Robust to a disconnected bridge and to missing dict keys: every field falls
## back to "—".

const MODE_PLAYER := 0
const MODE_DEV := 1
const REFRESH_S := 0.5
const DIM_KEYS := ["trust", "affinity", "obligation", "familiarity", "fear", "hostility"]

var _bridge = null
var _selected := -1
var _mode := MODE_DEV
var _shown := false

# The most recent authoritative payloads (raw), cached so a mode toggle re-renders
# without a new fetch.
var _ctx: Dictionary = {}
var _membership: Dictionary = {}
var _where: Dictionary = {}
var _group: Dictionary = {}

# Structured witness of exactly what the panel last rendered, keyed by section, so
# a certification gate can assert the surface shows the SAME values the authority
# reports (proving it reads authority, not fabrication).
var last_render: Dictionary = {}

# By construction the inspector performs no mutating bridge call; this counter is
# never incremented and exists so a gate can assert it stayed 0.
var _mutations := 0

var _root: PanelContainer
var _title: Label
var _mode_label: Label
var _body: Label
var _timer: Timer


func _init() -> void:
	layer = 12


func _ready() -> void:
	_build()
	visible = false
	_timer = Timer.new()
	_timer.wait_time = REFRESH_S
	_timer.one_shot = false
	_timer.timeout.connect(_on_tick)
	add_child(_timer)


# ------------------------------------------------------------------ public API
func set_bridge(bridge) -> void:
	_bridge = bridge


func set_selected(citizen_id: int) -> void:
	_selected = int(citizen_id)
	_ctx = {}
	_membership = {}
	_where = {}
	_group = {}
	if _shown and _selected >= 0:
		refresh()


func toggle() -> void:
	_shown = not _shown
	visible = _shown
	if _shown:
		if _selected >= 0:
			refresh()
		if _timer != null:
			_timer.start()
	else:
		if _timer != null:
			_timer.stop()


func is_shown() -> bool:
	return _shown


func mode_name() -> String:
	return "DEV TRUTH" if _mode == MODE_DEV else "PLAYER"


func mutation_calls() -> int:
	return _mutations


func refresh() -> void:
	## One periodic pull for the SELECTED citizen only (§35). Read-only.
	if _selected >= 0 and _connected():
		var r: Dictionary = _bridge.get_citizen_context(_selected)
		if _truth(r.get("ok", true)):
			_ctx = _dict(r.get("context", _ctx))
		# group facts: bounded read-only queries + the roster snapshot
		_membership = _dict(_bridge.group_query("membership", _selected))
		_where = _dict(_bridge.group_query("where", _selected))
		_group = _group_of(str(_membership.get("in_group", "")))
	_render()


# ------------------------------------------------------------------ input
func _input(event: InputEvent) -> void:
	if not _shown:
		return
	if event is InputEventKey and event.pressed and not event.echo \
			and event.keycode == KEY_TAB:
		_mode = MODE_PLAYER if _mode == MODE_DEV else MODE_DEV
		_render()   # re-render cached context in the new mode; no new fetch
		get_viewport().set_input_as_handled()


func _on_tick() -> void:
	if _shown and _selected >= 0:
		refresh()


# ------------------------------------------------------------------ rendering
func _render() -> void:
	var dev := _mode == MODE_DEV
	var lines: Array[String] = []
	var render := {"citizen_id": _selected, "mode": mode_name()}

	if _selected < 0:
		_title.text = "SIMULATION INSPECTOR"
		_mode_label.text = "no citizen selected"
		_body.text = "Select a citizen to inspect."
		last_render = render
		return
	if not _connected():
		_title.text = "SIMULATION INSPECTOR — c%d" % _selected
		_mode_label.text = "%s   (bridge disconnected)" % mode_name()
		_body.text = "— authority not connected —"
		last_render = render
		return

	var loc := _dict(_ctx.get("location"))
	var task := _dict(_ctx.get("task"))
	var goal := _dict(_ctx.get("goal"))

	# --- Identity ----------------------------------------------------------
	var ident := {"citizen_id": _selected, "band": _val(loc.get("band"))}
	lines.append("[IDENTITY]")
	lines.append("  citizen        c%d" % _selected)
	lines.append("  LOD band       %s" % _val(loc.get("band")))
	render["identity"] = ident

	# --- Physical ----------------------------------------------------------
	var phys := {
		"building_id": loc.get("building_id"), "room_id": loc.get("room_id"),
		"zone": loc.get("zone"), "x": loc.get("x"), "y": loc.get("y"),
		"inside": loc.get("inside"), "band": loc.get("band")}
	lines.append("")
	lines.append("[PHYSICAL]")
	lines.append("  building       %s" % _val(loc.get("building_id")))
	lines.append("  room           %s" % _val(loc.get("room_id")))
	lines.append("  zone           %s" % _val(loc.get("zone")))
	lines.append("  position       (%s, %s)  inside=%s" % [
		_val(loc.get("x")), _val(loc.get("y")), _val(loc.get("inside"))])
	render["physical"] = phys

	# --- Current behavior --------------------------------------------------
	var behavior := {
		"goal_kind": goal.get("kind"), "goal_target": goal.get("target"),
		"goal_source": goal.get("source"), "goal_reason": goal.get("reason"),
		"task_id": task.get("task_id"), "phase": task.get("phase"),
		"object_id": task.get("object_id"), "role": task.get("role")}
	lines.append("")
	lines.append("[CURRENT BEHAVIOR]")
	lines.append("  goal           %s -> %s" % [_val(goal.get("kind")), _val(goal.get("target"))])
	lines.append("  goal source    %s" % _val(goal.get("source")))
	lines.append("  work phase     %s" % _val(task.get("phase")))
	lines.append("  task           %s" % _val(task.get("task_id")))
	lines.append("  object target  %s" % _val(task.get("object_id")))
	lines.append("  role           %s" % _val(task.get("role")))
	render["behavior"] = behavior

	# --- Health (DEV only: infection state is hidden knowledge) ------------
	if dev:
		lines.append("")
		lines.append("[HEALTH]  (dev truth)")
		lines.append("  infection      %s" % _val(_ctx.get("health")))
		render["health"] = _ctx.get("health")
	else:
		render["health"] = null

	# --- Cognition (DEV: the NPC's private mind) ---------------------------
	if dev:
		var mems := _arr(_ctx.get("memories"))
		var bels := _arr(_ctx.get("beliefs"))
		lines.append("")
		lines.append("[COGNITION]  (dev truth)")
		lines.append("  memories       %s salient / %s total" % [
			str(mems.size()), _val(_ctx.get("n_memories"))])
		for m in mems.slice(0, 4):
			var md := _dict(m)
			lines.append("    - %s eff=%s (%s)" % [
				_val(md.get("kind")), _val(md.get("effective")),
				"1st-hand" if _truth(md.get("source", "") == "direct") else _val(md.get("source"))])
		lines.append("  perceived dgr  %s" % _val(_ctx.get("perceived_danger")))
		var avoiding := _dict(_ctx.get("avoiding"))
		lines.append("  avoiding       %s" % ("—" if avoiding.is_empty() else _val(avoiding.get("building_id"))))
		lines.append("  avoid rooms    %s" % _val(_ctx.get("avoid_rooms_here")))
		lines.append("  beliefs        %s active" % str(bels.size()))
		for b in bels.slice(0, 3):
			var bd := _dict(b)
			lines.append("    - %s = %s" % [_val(bd.get("key")), _val(bd.get("value"))])
		render["cognition"] = {
			"n_memories": _ctx.get("n_memories"),
			"n_salient": mems.size(),
			"memory_kinds": _memory_kinds(mems),
			"perceived_danger": _ctx.get("perceived_danger"),
			"avoiding_building": avoiding.get("building_id"),
			"avoid_rooms_here": _ctx.get("avoid_rooms_here"),
			"n_beliefs": bels.size(),
			"belief_keys": _belief_keys(bels)}
	else:
		# Player mode: the player cannot read another mind — show only that they
		# sense general danger where they stand (perception, not the belief graph).
		lines.append("")
		lines.append("[SENSE]  (player)")
		lines.append("  danger sensed  %s" % _val(_ctx.get("perceived_danger")))
		lines.append("  (memories / beliefs / health are DEV-only)")
		render["cognition"] = null

	# --- Social ------------------------------------------------------------
	var nearby := _arr(_ctx.get("people_nearby"))
	var rels := _arr(_ctx.get("relationships"))
	var nearby_ids: Array = []
	for p in nearby:
		nearby_ids.append(int(_dict(p).get("citizen_id", -1)))
	lines.append("")
	lines.append("[SOCIAL]")
	lines.append("  nearby known   %s" % (str(nearby_ids) if not nearby_ids.is_empty() else "—"))
	var rel_render: Array = []
	if dev:
		for r in rels.slice(0, 5):
			var rd := _dict(r)
			lines.append("    c%s  trust=%s affinity=%s oblig=%s" % [
				_val(rd.get("other")), _val(rd.get("trust")),
				_val(rd.get("affinity")), _val(rd.get("obligation"))])
			rel_render.append({"other": rd.get("other"), "trust": rd.get("trust"),
				"affinity": rd.get("affinity"), "obligation": rd.get("obligation")})
	else:
		lines.append("  (relationship internals are DEV-only)")
	render["social"] = {"nearby": nearby_ids, "relationships": rel_render}

	# --- Group -------------------------------------------------------------
	var in_group = _membership.get("in_group")
	lines.append("")
	lines.append("[GROUP]")
	if in_group == null or str(in_group) == "":
		lines.append("  membership     — (not in a survivor group)")
		render["group"] = {"in_group": null, "role": null,
			"shelter_building": null, "coordinator": null, "members": []}
	else:
		var wd := _dict(_where.get("group"))
		var coordinator = _group.get("coordinator")
		var objectives := _dict(_group.get("objectives")).keys()
		lines.append("  membership     %s  role=%s" % [_val(in_group), _val(_membership.get("role"))])
		lines.append("  shelter        building %s (room %s)" % [
			_val(wd.get("shelter_building")), _val(wd.get("shelter_room"))])
		lines.append("  coordinator    %s" % _val(coordinator))
		lines.append("  members        %s" % _val(wd.get("members")))
		if dev:
			lines.append("  objectives     %s" % (str(objectives) if not objectives.is_empty() else "—"))
		render["group"] = {
			"in_group": str(in_group), "role": _membership.get("role"),
			"shelter_building": wd.get("shelter_building"),
			"coordinator": coordinator, "members": wd.get("members"),
			"objectives": objectives}

	_title.text = "SIMULATION INSPECTOR — c%d" % _selected
	_mode_label.text = "MODE: %s   (Tab to switch)" % mode_name()
	_body.text = "\n".join(lines)
	last_render = render


func rendered_text() -> String:
	return _body.text if _body != null else ""


# ------------------------------------------------------------------ helpers
func _connected() -> bool:
	return _bridge != null and _bridge.has_method("is_connected_to_sim") \
		and _bridge.is_connected_to_sim()


func _group_of(gid: String) -> Dictionary:
	if gid == "" or not _connected():
		return {}
	var snap: Dictionary = _dict(_bridge.get_groups_snapshot(0))
	var groups := _dict(snap.get("groups"))
	return _dict(groups.get(gid))


func _memory_kinds(mems: Array) -> Array:
	var out: Array = []
	for m in mems:
		out.append(_dict(m).get("kind"))
	return out


func _belief_keys(bels: Array) -> Array:
	var out: Array = []
	for b in bels:
		out.append(_dict(b).get("key"))
	return out


func _dict(v) -> Dictionary:
	return v if v is Dictionary else {}


func _arr(v) -> Array:
	return v if v is Array else []


func _truth(v) -> bool:
	return v == true


func _val(v) -> String:
	if v == null:
		return "—"
	if v is float:
		return "%.3f" % v
	if v is Array:
		return "—" if v.is_empty() else str(v)
	if v is String and v == "":
		return "—"
	return str(v)


# ------------------------------------------------------------------ layout
func _build() -> void:
	_root = PanelContainer.new()
	_root.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_root.offset_left = -520
	_root.offset_right = -12
	_root.offset_top = 12
	_root.offset_bottom = 720
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 12)
	margin.add_theme_constant_override("margin_right", 12)
	margin.add_theme_constant_override("margin_top", 10)
	margin.add_theme_constant_override("margin_bottom", 10)
	_root.add_child(margin)

	var vb := VBoxContainer.new()
	margin.add_child(vb)

	_title = Label.new()
	_title.text = "SIMULATION INSPECTOR"
	vb.add_child(_title)

	_mode_label = Label.new()
	_mode_label.text = "MODE: DEV TRUTH   (Tab to switch)"
	vb.add_child(_mode_label)

	_body = Label.new()
	_body.text = ""
	_body.add_theme_font_size_override("font_size", 12)
	vb.add_child(_body)

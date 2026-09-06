class_name EventFeed
extends CanvasLayer

## Developer event feed (ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2, §21/§24).
##
## A bounded, scrolling window on the authority's own event streams. It shows that
## the backend is ALIVE — work sessions clocking in, cognition perceiving danger,
## groups forming, conversations happening — without inventing anything: every
## line is one event row the Python runtimes emitted (each carries its own `seq`
## and world time `t`). The feed is READ-ONLY; it advances nothing.
##
## Streams polled (each with its OWN last-seen sequence id so nothing is ever
## re-fetched from 0 or double-counted):
##   GET_WORK        -> "work"       (EMPLOYED, CLOCK_IN, TASK_START, USE_START…)
##   GET_COGNITION   -> "cognition"  (PERCEIVED, WARNING_SHARED, HELP_STARTED…)
##   GET_DIALOGUE    -> "dialogue"   (CONVERSATION_STARTED, SPEECH_ACT, ANSWERED…)
##   GET_GROUPS      -> "groups"     (GROUP_FORMED, SHELTER_SELECTED, ROLE_*…)
##   GET_OUTBREAK    -> "outbreak"   (only when the outbreak layer is live)
## The filter also accepts "mobility"; movement has no discrete event log, so that
## category currently matches nothing but stays a valid, selectable filter key.
##
## Public API: set_bridge(bridge), poll() (drive on a ~1s Timer), set_filter(cats)
## (an Array of category names; empty = show all). Bounded to MAX_LINES on screen.

const MAX_LINES := 40
const POLL_S := 1.0
const CATEGORIES := ["mobility", "outbreak", "work", "cognition", "dialogue", "groups"]

var _bridge = null
# Per-stream last-seen sequence id — the delta cursor (never reset to 0).
var _seq := {"work": 0, "cognition": 0, "dialogue": 0, "groups": 0, "outbreak": 0}
var _filter: Array = []            # empty = all categories
var _lines: Array = []             # ring buffer of rendered line strings
var _rows: Array = []              # parallel {cat, kind, cid, t, text} for gate/introspection

var last_render: Dictionary = {}

var _root: PanelContainer
var _body: Label
var _timer: Timer


func _init() -> void:
	layer = 11


func _ready() -> void:
	_build()
	_timer = Timer.new()
	_timer.wait_time = POLL_S
	_timer.one_shot = false
	_timer.timeout.connect(poll)
	add_child(_timer)
	_timer.start()


# ------------------------------------------------------------------ public API
func set_bridge(bridge) -> void:
	_bridge = bridge


func set_filter(cats: Array) -> void:
	## Show only these categories (a subset of CATEGORIES). Empty = show all.
	var clean: Array = []
	for c in cats:
		if CATEGORIES.has(str(c)):
			clean.append(str(c))
	_filter = clean
	_render()


func toggle() -> void:
	visible = not visible


func poll() -> void:
	## Pull the delta from each stream since its own cursor and append. Read-only.
	if _bridge == null or not _bridge.has_method("is_connected_to_sim") \
			or not _bridge.is_connected_to_sim():
		return
	_pull("work", "get_work", "work")
	_pull("cognition", "get_cognition", "cognition")
	_pull("dialogue", "get_dialogue", "dialogue")
	_pull_groups()
	if "outbreak_enabled" in _bridge and bool(_bridge.get("outbreak_enabled")) \
			and _bridge.has_method("get_outbreak"):
		_pull("outbreak", "get_outbreak", "outbreak")
	_render()


func lines() -> Array:
	return _lines.duplicate()


func rows() -> Array:
	return _rows.duplicate()


func rendered_text() -> String:
	return _body.text if _body != null else ""


# ------------------------------------------------------------------ polling
func _pull(cat: String, method: String, block_key: String) -> void:
	if not _bridge.has_method(method):
		return
	var r: Dictionary = _bridge.call(method, _seq[cat])
	if r.get("ok", false) != true:
		return
	var block = r.get(block_key)
	if not (block is Dictionary):
		return
	_ingest(cat, block.get("events", []))
	_seq[cat] = max(_seq[cat], int(block.get("event_seq", _seq[cat])))


func _pull_groups() -> void:
	if not _bridge.has_method("get_groups_snapshot"):
		return
	var snap: Dictionary = _bridge.get_groups_snapshot(_seq["groups"])
	if not (snap is Dictionary) or snap.is_empty():
		return
	_ingest("groups", snap.get("events", []))
	_seq["groups"] = max(_seq["groups"], int(snap.get("event_seq", _seq["groups"])))


func _ingest(cat: String, events) -> void:
	if not (events is Array):
		return
	for e in events:
		if not (e is Dictionary):
			continue
		var row := {
			"cat": cat,
			"kind": str(e.get("event", "?")),
			"cid": e.get("citizen_id", e.get("reporter", e.get("actor"))),
			"t": float(e.get("t", 0.0)),
			"group": e.get("group_id")}
		row["text"] = _format(row)
		_rows.append(row)
		_lines.append(row["text"])
	# Bound the buffers (ring): keep only the newest MAX_LINES.
	if _rows.size() > MAX_LINES:
		_rows = _rows.slice(_rows.size() - MAX_LINES, _rows.size())
	if _lines.size() > MAX_LINES:
		_lines = _lines.slice(_lines.size() - MAX_LINES, _lines.size())


func _format(row: Dictionary) -> String:
	var cid = row.get("cid")
	var cid_s := ("c%d" % int(cid)) if cid != null else "----"
	var extra := ""
	if row.get("group") != null:
		extra = " group:%s" % str(row["group"])
	return "%s %s %s%s" % [_clock_str(row.get("t", 0.0)), cid_s, row.get("kind", "?"), extra]


func _clock_str(t: float) -> String:
	## Convert a world-second event timestamp to an in-game HH:MM using the base
	## hour implied by the authority's summary (current hour - elapsed seconds).
	var base := 8.0
	if _bridge != null and "last_summary" in _bridge:
		var s = _bridge.last_summary
		if s is Dictionary:
			var cur := float(s.get("hour", 8.0))
			var gs := float(s.get("game_seconds", 0.0))
			base = cur - gs / 3600.0
	var h := base + t / 3600.0
	h = fposmod(h, 24.0)
	var hh := int(h)
	var mm := int((h - hh) * 60.0)
	return "%02d:%02d" % [hh, mm]


# ------------------------------------------------------------------ render
func _render() -> void:
	var shown: Array = []
	for row in _rows:
		if _filter.is_empty() or _filter.has(str(row.get("cat"))):
			shown.append(str(row.get("text")))
	# On-screen is bounded; show the newest tail.
	if shown.size() > MAX_LINES:
		shown = shown.slice(shown.size() - MAX_LINES, shown.size())
	last_render = {"n_rows": _rows.size(), "n_shown": shown.size(),
		"filter": _filter.duplicate(), "seq": _seq.duplicate()}
	var header := "EVENT FEED  [%s]" % ("all" if _filter.is_empty() else " ".join(_filter))
	_body.text = header + "\n" + "\n".join(shown)


# ------------------------------------------------------------------ layout
func _build() -> void:
	_root = PanelContainer.new()
	_root.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	_root.offset_left = 12
	_root.offset_bottom = -12
	_root.offset_top = -360
	_root.offset_right = 420
	_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_root)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 10)
	margin.add_theme_constant_override("margin_right", 10)
	margin.add_theme_constant_override("margin_top", 8)
	margin.add_theme_constant_override("margin_bottom", 8)
	_root.add_child(margin)

	_body = Label.new()
	_body.add_theme_font_size_override("font_size", 11)
	_body.text = "EVENT FEED"
	margin.add_child(_body)

class_name DialoguePanel
extends CanvasLayer

## The player<->NPC dialogue surface (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1).
##
## A THIN, TRUTHFUL WINDOW ON THE AUTHORITY. Every word of NPC (and player)
## speech in this panel is a string the Python DialogueRuntime rendered and sent
## back in the TALK reply (`acts[i].line`); this script never composes, edits,
## completes or paraphrases a line. What it adds is presentation only:
##
##   * the speaker prefix ("you" / "citizen 25"), the bundle display name in the
##     header (identity, not truth), and the epistemic tag it copies verbatim out
##     of the act's own `proposition.epistemic`;
##   * six bounded options — the authority's own `PLAYER_OPTIONS` (ASK_FACT,
##     ASK_LOCATION, ASK_PERSON, ASK_SAFETY, ASK_FOR_HELP, END_CONVERSATION) —
##     as buttons / number keys. The option LABELS are UI text for the ACT; the
##     line the player is shown as having said is again the authority's.
##
## When the authority refuses (ok:false), the panel shows its `reason` verbatim
## and nothing else — no invented apology, no fallback text.
##
## The panel decides no dialogue content. Its only inputs to the authority are
## the act name and structured arguments (building_id / subject / object_id),
## which come from the world (the building the player is inside, the subject of
## the last answer, a nearby station id).

signal talked(reply: Dictionary)          # every TALK reply, ok or not
signal closed()

## The bounded option set, in key order 1..6. `act` is the authority's act name.
const OPTIONS := [
	{"key": "1", "label": "What happened?", "act": "ASK_FACT"},
	{"key": "2", "label": "Where was that?", "act": "ASK_LOCATION"},
	{"key": "3", "label": "Have you seen ...?", "act": "ASK_PERSON"},
	{"key": "4", "label": "Is this place safe?", "act": "ASK_SAFETY"},
	{"key": "5", "label": "Can you cover this task?", "act": "ASK_FOR_HELP"},
	{"key": "6", "label": "Goodbye", "act": "END_CONVERSATION"},
]

# --- context the WORLD supplies for the structured arguments -----------------
var context_building_id := -1        # the building the player is inside, or -1
var context_room_id := -1
var context_subject := -1            # last citizen seen (ASK_PERSON fallback)
var context_object_id := ""          # a nearby station (ASK_FOR_HELP), or ""
var names: Dictionary = {}           # citizen_id -> bundle display name (identity only)
var player_citizen := -1

# --- authoritative state of the open conversation ---------------------------
var npc := -1
var conv_id := ""
var last_reply: Dictionary = {}
var last_acts: Array = []            # the acts of the LAST reply (authority rows)
var transcript: Array = []           # the authority's own running transcript
var last_npc_line := ""
var last_subject := -1               # subject of the last answer's proposition
var last_error := ""

var _root: PanelContainer
var _header: Label
var _channel: Label
var _warmth: Label
var _lines: VBoxContainer
var _status: Label
var _buttons: Array = []


func _init() -> void:
	layer = 10
	process_mode = Node.PROCESS_MODE_ALWAYS


func _ready() -> void:
	_build()
	visible = false


func _build() -> void:
	_root = PanelContainer.new()
	_root.anchor_left = 0.0
	_root.anchor_right = 0.0
	_root.anchor_top = 1.0
	_root.anchor_bottom = 1.0
	_root.offset_left = 16
	_root.offset_top = -330
	_root.offset_bottom = -100
	_root.custom_minimum_size = Vector2(620, 230)
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.05, 0.07, 0.10, 0.90)
	sb.border_color = Color(0.55, 0.75, 0.9, 0.9)
	sb.set_border_width_all(2)
	sb.set_content_margin_all(10)
	_root.add_theme_stylebox_override("panel", sb)
	add_child(_root)

	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 4)
	_root.add_child(vb)

	_header = Label.new()
	_header.add_theme_font_size_override("font_size", 18)
	_header.modulate = Color(1.0, 0.95, 0.8)
	vb.add_child(_header)

	_channel = Label.new()
	_channel.add_theme_font_size_override("font_size", 13)
	_channel.modulate = Color(0.7, 0.85, 1.0)
	vb.add_child(_channel)

	_warmth = Label.new()
	_warmth.add_theme_font_size_override("font_size", 13)
	_warmth.modulate = Color(0.8, 0.9, 0.8)
	vb.add_child(_warmth)

	_lines = VBoxContainer.new()
	_lines.add_theme_constant_override("separation", 2)
	vb.add_child(_lines)

	_status = Label.new()
	_status.add_theme_font_size_override("font_size", 13)
	_status.modulate = Color(1.0, 0.7, 0.6)
	vb.add_child(_status)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	vb.add_child(row)
	for i in range(OPTIONS.size()):
		var b := Button.new()
		b.text = "%s %s" % [OPTIONS[i]["key"], OPTIONS[i]["label"]]
		b.add_theme_font_size_override("font_size", 12)
		b.process_mode = Node.PROCESS_MODE_ALWAYS
		b.pressed.connect(_on_option.bind(i))
		row.add_child(b)
		_buttons.append(b)


func _on_option(i: int) -> void:
	choose(i)


# ------------------------------------------------------------------ public API
func is_open() -> bool:
	return visible and npc >= 0


func display_name(cid: int) -> String:
	var n := str(names.get(cid, ""))
	return n if n != "" else ""


## Open a conversation with `cid`: one GREET through the authority. The panel
## opens whatever the authority answers — including a refusal, which it shows.
func open_with(cid: int) -> Dictionary:
	npc = int(cid)
	conv_id = ""
	transcript = []
	last_acts = []
	last_npc_line = ""
	last_subject = -1
	last_error = ""
	visible = true
	var reply := _talk("GREET", {})
	return reply


## Send the bounded option `i` (0..5). Returns the authority's reply.
func choose(i: int) -> Dictionary:
	if npc < 0 or i < 0 or i >= OPTIONS.size():
		return {}
	var act := str(OPTIONS[i]["act"])
	return _talk(act, _args_for(act))


## Send an act by name with explicit args (the same path the buttons use).
func send_act(act: String, args: Dictionary = {}) -> Dictionary:
	if npc < 0:
		return {}
	return _talk(act, args)


func close() -> void:
	visible = false
	npc = -1
	conv_id = ""
	last_npc_line = ""
	closed.emit()


## The structured arguments of each bounded option. These are the ONLY things
## the panel contributes to a question: the authority decides the answer.
func _args_for(act: String) -> Dictionary:
	match act:
		"ASK_FACT":
			# "what happened?" — scoped to the building the player is inside
			var a := {}
			if context_building_id >= 0:
				a["building_id"] = context_building_id
			return a
		"ASK_LOCATION":
			# "where was that?" — the authority resolves the event from the last
			# thing this NPC asserted to this player (no event_ref sent).
			return {}
		"ASK_PERSON":
			var subj := last_subject if last_subject >= 0 else context_subject
			return ({"citizen_id": subj} if subj >= 0 else {})
		"ASK_SAFETY":
			var a2 := {}
			if context_building_id >= 0:
				a2["building_id"] = context_building_id
				if context_room_id >= 0:
					a2["room_id"] = context_room_id
			return a2
		"ASK_FOR_HELP":
			var a3 := {"kind": "cover_station"}
			if context_object_id != "":
				a3["object_id"] = context_object_id
			return a3
		_:
			return {}


func _talk(act: String, args: Dictionary) -> Dictionary:
	if not SimBridge.is_connected_to_sim():
		last_error = "no bridge connection"
		_render()
		return {}
	var reply: Dictionary = SimBridge.talk(npc, act, args)
	last_reply = reply
	if reply.get("ok", false) == true:
		last_error = ""
		conv_id = str(reply.get("conv_id", conv_id))
		var acts = reply.get("acts", [])
		last_acts = acts if acts is Array else []
		var tr = reply.get("transcript", [])
		transcript = tr if tr is Array else transcript
		for r in last_acts:
			if not (r is Dictionary):
				continue
			if int(r.get("speaker", -1)) == npc:
				last_npc_line = str(r.get("line", ""))
			var p = r.get("proposition")
			if p is Dictionary and p.get("subject") != null:
				last_subject = int(p["subject"])
		if str(reply.get("state", "")) != "active":
			# the authority closed the conversation (goodbye / interrupted)
			pass
	else:
		var err = reply.get("error")
		if err is Dictionary:
			last_error = "%s: %s" % [str(err.get("code", "")), str(err.get("message", ""))]
		else:
			last_error = str(reply.get("reason", "refused"))
	_render()
	talked.emit(reply)
	if act == "END_CONVERSATION" and reply.get("ok", false) == true:
		# keep the closing lines on screen; the world closes the panel
		pass
	return reply


# ------------------------------------------------------------------ rendering
func _render() -> void:
	var nm := display_name(npc)
	_header.text = "citizen %d%s" % [npc, ("  ·  %s" % nm) if nm != "" else ""]
	var chan := "face to face"
	_channel.text = "Channel: %s   (authority channel \"player\"%s)" % [chan,
		("" if conv_id == "" else ", " + conv_id)]
	if last_reply.get("ok", false) == true:
		var rel = last_reply.get("relationship")
		var rel_txt := "no relationship on record"
		if rel is Dictionary:
			rel_txt = "familiarity %s · trust %s · affinity %s · obligation %s" % [
				str(rel.get("familiarity")), str(rel.get("trust")),
				str(rel.get("affinity")), str(rel.get("obligation"))]
		_warmth.text = "Warmth %s   (%s)  — the authority's numbers, toward you" % [
			str(last_reply.get("warmth")), rel_txt]
	else:
		_warmth.text = ""
	for c in _lines.get_children():
		# free() and not queue_free(): a deferred free would leave the previous
		# exchange's labels in the tree for the rest of the frame, and the panel
		# must show exactly the acts of the reply it just received.
		_lines.remove_child(c)
		c.free()
	for r in last_acts:
		if not (r is Dictionary):
			continue
		var speaker := int(r.get("speaker", -1))
		var who := "you" if speaker == player_citizen else "citizen %d" % speaker
		var tag := ""
		var p = r.get("proposition")
		if p is Dictionary and str(p.get("epistemic", "")) != "":
			tag = "   [%s]" % str(p["epistemic"])
		var l := Label.new()
		l.add_theme_font_size_override("font_size", 15)
		l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		l.custom_minimum_size = Vector2(590, 0)
		l.modulate = Color(0.85, 0.95, 1.0) if speaker == player_citizen else Color(1.0, 1.0, 0.9)
		# VERBATIM: r["line"] is the authority's rendered line.
		l.text = "%s: %s%s" % [who, str(r.get("line", "")), tag]
		_lines.add_child(l)
	if last_error != "":
		_status.text = "the authority refused: %s" % last_error
	elif last_reply.get("ok", false) == true and str(last_reply.get("state", "")) != "active":
		_status.text = "conversation %s" % str(last_reply.get("state", ""))
	else:
		_status.text = ""


## The lines of the last reply, exactly as the authority sent them.
func authority_lines() -> Array:
	var out := []
	for r in last_acts:
		if r is Dictionary:
			out.append(str(r.get("line", "")))
	return out


## The lines this panel currently DISPLAYS, stripped of the speaker prefix and
## the epistemic tag — so a test can prove the panel adds no words of its own.
func displayed_lines() -> Array:
	var out := []
	for c in _lines.get_children():
		if not (c is Label):
			continue
		var t := str(c.text)
		var i := t.find(": ")
		if i >= 0:
			t = t.substr(i + 2)
		var j := t.find("   [")
		if j >= 0:
			t = t.substr(0, j)
		out.append(t)
	return out

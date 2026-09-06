extends Node

## Dialogue visual evidence (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1).
##
## Runs the REAL IsometricWorld scene and the REAL DialoguePanel against the live
## Python bridge (protocol v8) and saves a frame at each stage of the certified
## conversation day: a coworker asking another for help and the helper walking to
## the object it accepted, a refusal, the player approaching a citizen inside the
## busiest shop, the panel open on that citizen, a first-hand answer to "What
## happened?" after the attack, an "I don't know.", the warning wave the
## authority runs between NPCs, and a conversation the threat cut short.
##
## Every line in every panel is the authority's own rendered string (the TALK
## reply); this harness composes no dialogue and poses nobody: interior bodies
## are driven from authoritative interior positions.
##
## CAPTIONS say what the PIXELS prove and what only the authority's ROWS prove —
## speech has no visual channel in this renderer beyond the panel and the small
## label over the speaker's head, both of which print the authority's string.
## `_reached` is false unless the thing the run was waiting for actually
## happened, and the caption is then prefixed NOT REACHED.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/DialogueShot.tscn -- --bundle houston --player 82 \
##     --dir docs/npc/evidence_dialogue

var _bundle := "houston"
var _player := 82
var _start_hour := 5.0
var _dir := "/tmp/asph_dialogue_shots"
var _game_dt := 1.0

var _scene: Node3D
var _emb: EmbodiedMobility
var _panel: DialoguePanel
var _manifest := []
var _dseq := 0
var _cseq := 0
var _wseq := 0
var _dlg: Array = []
var _cog: Array = []
var _kinds := {}
var _counts := {}
var _reached := true

var _shop := -1
var _seeded := -1
var _witness := -1
var _uninformed := -1
var _pre_unknown := {}       # the pre-attack "I don't know." reply, if there was one
var _pre_unknown_npc := -1
var _known_req := {}


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])
		elif args[i] == "--start-hour" and i + 1 < args.size():
			_start_hour = float(args[i + 1])
		elif args[i] == "--dir" and i + 1 < args.size():
			_dir = args[i + 1]
	DirAccess.make_dir_recursive_absolute(_dir)
	await _run()


# ------------------------------------------------------------------ helpers
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _hour() -> float:
	return float(SimBridge.last_summary.get("hour", 0.0))


func _hhmm() -> String:
	var h := _hour()
	return "%02d:%02d" % [int(h), int(floor((h - floor(h)) * 60.0))]


func _caption(text: String) -> String:
	if _reached:
		return text
	return "NOT REACHED within the captured window - the frame shows the world as it was: " + text


func _row(block: Dictionary, cid: int) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == cid:
			return row
	return {}


func _work(row: Dictionary) -> Dictionary:
	var w = row.get("work", {})
	return w if w is Dictionary else {}


func _context(cid: int) -> Dictionary:
	var c = SimBridge.get_citizen_context(cid).get("context")
	return c if c is Dictionary else {}


func _people_nearby(cid: int) -> Array:
	var out := []
	for n in _context(cid).get("people_nearby", []):
		if n is Dictionary:
			out.append(_iv(n.get("citizen_id")))
		else:
			out.append(int(n))
	return out


func _pull() -> void:
	var d: Dictionary = SimBridge.get_dialogue(_dseq).get("dialogue", {})
	for e in d.get("events", []):
		_dseq = max(_dseq, int(e.get("seq", 0)))
		var kind := str(e.get("event", ""))
		_kinds[kind] = int(_kinds.get(kind, 0)) + 1
		if _dlg.size() < 9000:
			_dlg.append(e)
	var counts = d.get("counts")
	if counts is Dictionary:
		_counts = counts
	var c: Dictionary = SimBridge.get_cognition(_cseq).get("cognition", {})
	for e in c.get("events", []):
		_cseq = max(_cseq, int(e.get("seq", 0)))
		if str(e.get("event", "")) == "PERCEIVED" and _cog.size() < 9000:
			_cog.append(e)
	SimBridge.get_work(_wseq)
	for e in SimBridge.last_work.get("events", []):
		_wseq = max(_wseq, int(e.get("seq", 0)))


func _dev(kind: String) -> Array:
	var out := []
	for e in _dlg:
		if str(e.get("event", "")) == kind:
			out.append(e)
	return out


func _acts_of(conv_id: String) -> Array:
	var out := []
	for e in _dlg:
		if str(e.get("event", "")) == "SPEECH_ACT" and str(e.get("conv_id", "")) == conv_id:
			out.append(e)
	return out


func _act_lines(conv_id: String) -> Array:
	var out := []
	for a in _acts_of(conv_id):
		out.append("%s->%s %s: %s" % [str(a.get("speaker")), str(a.get("listener")),
			str(a.get("act")), str(a.get("line"))])
	return out


func _sessions() -> Dictionary:
	var s = SimBridge.last_work.get("sessions", {})
	return s if s is Dictionary else {}


func _session_of(cid: int) -> Dictionary:
	var s = _sessions().get(str(cid), {})
	return s if s is Dictionary else {}


func _customers(bid: int) -> Array:
	var out := []
	for k in _sessions():
		var s = _sessions()[k]
		if s is Dictionary and str(s.get("kind", "")) == "customer" and _iv(s.get("building_id")) == bid:
			out.append(int(str(k)))
	out.sort()
	return out


func _object_row(bid: int, oid: String) -> Dictionary:
	for o in SimBridge.get_rooms(bid).get("objects", []):
		if str(o["object_id"]) == oid:
			return o
	return {}


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, d)
	_pull()
	return block


func _staged(x: float, y: float) -> Vector3:
	return _scene.interior_offset() + Vector3(x, _emb.body_height, y)


func _place_player(row: Dictionary, off: Vector2 = Vector2(3.0, 2.5)) -> void:
	if row.is_empty():
		return
	var p = _scene.get_player()
	if p == null:
		return
	var bid := int(row.get("building_id", -1))
	if _scene.inside_building() >= 0 and _scene.inside_building() == bid:
		p.teleport(_staged(float(row["x"]), float(row["y"])) + Vector3(off.x, 1.0, off.y))
	elif _scene.inside_building() < 0:
		p.teleport(Vector3(float(row["x"]) + off.x, 1.5, float(row["y"]) + off.y))
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _zoom(v: float) -> void:
	var cam = _scene.get_camera()
	if cam != null:
		cam.set_zoom(v)


func _settle(frames: int) -> void:
	var ext = _scene.get_exterior()
	for i in range(frames):
		if ext != null and _scene.inside_building() < 0:
			ext.update_focus(_scene.get_camera().get_focus())
		await get_tree().physics_frame


func _bodies_here() -> Array:
	var out := []
	for id in _emb.interior_body_ids():
		out.append(str(id))
	out.sort()
	return out


func _enter(bid: int) -> void:
	_scene.enter_building_by_id(bid)
	await get_tree().physics_frame
	_step(_game_dt)
	_emb.refresh_object_markers()
	await get_tree().physics_frame


func _leave() -> void:
	var interior = _scene.active_interior()
	if interior != null and is_instance_valid(interior):
		var marker: Node3D = interior.get_node_or_null("ExitMarker")
		if marker != null:
			_scene.get_player().teleport(marker.global_position + Vector3(0, 1.5, 0))
			await get_tree().physics_frame
	_scene.leave_current_building()
	await get_tree().physics_frame


func _shot(name: String, caption: String, extra: Dictionary = {}) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.3).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	var prow := _row(SimBridge.last_mobility, _player)
	var row := {"file": name, "caption": caption, "hour": _hour(), "clock": _hhmm(),
		"player_citizen": _player, "shop": _shop, "seeded": _seeded,
		"player_row": {"state": prow.get("state"), "building_id": prow.get("building_id"),
			"x": prow.get("x"), "y": prow.get("y"), "work": _work(prow),
			"dialogue": prow.get("dialogue")},
		"inside_building": _scene.inside_building(),
		"interior_bodies": _emb.interior_bodies, "interior_body_ids": _bodies_here(),
		"panel_open": _panel.is_open(), "panel_npc": _panel.npc,
		"panel_displayed_lines": _panel.displayed_lines(),
		"panel_authority_lines": _panel.authority_lines(),
		"dialogue_counts": _counts}
	for k in extra:
		row[k] = extra[k]
	_manifest.append(row)
	print("SHOT saved: %s (%dx%d)" % [path, img.get_size().x, img.get_size().y])


func _until(pred: Callable, max_game_s: float, chunk_s: float, follow: int = -1,
		place: bool = false) -> Dictionary:
	var t := 0.0
	var row := {}
	_reached = false
	while t < max_game_s:
		var block := _step(chunk_s)
		if block.is_empty():
			break
		t += chunk_s
		if follow >= 0:
			row = _row(block, follow)
			if not row.is_empty():
				if place:
					_place_player(row)
				else:
					SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
					SimBridge.has_focus_xy = true
		if pred.call():
			_reached = true
			return row
		if chunk_s <= 5.0 or int(t / chunk_s) % 8 == 0:
			await get_tree().physics_frame
	return row


# ------------------------------------------------------------ predicates
func _p_request_accepted() -> bool:
	for e in _dev("REQUEST_ACCEPTED"):
		if not _known_req.has(str(e.get("request_id", ""))):
			return true
	return false


func _p_request_refused() -> bool:
	return not _dev("REQUEST_REFUSED").is_empty()


func _p_player_shopping() -> bool:
	if _hour() < 10.0:
		return false
	var r := _row(SimBridge.last_mobility, _player)
	return int(r.get("building_id", -1)) >= 0 and str(r.get("state")) == "doing_activity" \
		and str(_work(r).get("role", "")) == "customer"


func _p_someone_near_player() -> bool:
	return not _people_nearby(_player).is_empty()


func _p_attacked_in_shop() -> bool:
	for e in _cog:
		if str(e.get("what", "")) == "attacked_by" and _iv(e.get("building_id")) == _shop:
			return true
	return false


# ------------------------------------------------------------------- the run
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.start_hour = _start_hour
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_player] if _player < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _player if _player < citizens.size() else 0
	_scene = preload("res://IsometricWorld.tscn").instantiate()
	add_child(_scene)
	for i in range(20):
		await get_tree().physics_frame
	await get_tree().create_timer(0.5).timeout
	if not SimBridge.is_connected_to_sim() or not SimBridge.dialogue_enabled:
		printerr("no live bridge with dialogue; start python -m asphodel.bridge.server")
		get_tree().quit(1)
		return
	_emb = _scene.get_embodied()
	_panel = _scene.get_dialogue_panel()
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	GameClock.time_scale = 0.0
	_zoom(16.0)
	_pull()
	print("SHOTS: dialogue world started at hour %s, player citizen %d" % [str(_hour()), _player])

	# --- 05 / 06 an NPC asks another for help, and the helper goes to do it ---
	await _until(_p_request_accepted, 6.0 * 3600.0, 10.0, -1)
	var got := _reached
	var ra := {}
	for e in _dev("REQUEST_ACCEPTED"):
		if ra.is_empty():
			ra = e
	var rid := str(ra.get("request_id", ""))
	var helper := _iv(ra.get("speaker"))
	var requester := _iv(ra.get("listener"))
	var obj := str(ra.get("object_id", ""))
	var bid := -1
	for e in _dev("REQUEST_MADE"):
		if str(e.get("request_id", "")) == rid:
			bid = _iv(e.get("building_id"))
	if got and bid >= 0:
		await _enter(bid)
		var hrow := _row(SimBridge.last_mobility, helper)
		_place_player(hrow, Vector2(3.5, 3.0))
		await _settle(20)
		_reached = got
		await _shot("05_help_request.png", _caption(
			"%s — building %d: citizen %d told citizen %d it had a problem and asked for help; citizen %d accepted (request %s, task %s, object %s). The authority's own acts, in order: %s. PIXELS: two worker bodies standing in the same staged interior, each driven from its authoritative interior position (%d interior bodies here). AUTHORITY ONLY: that they spoke, what they said, and that the request was accepted — speech has no visual channel out here; the rows in this manifest are the evidence."
			% [_hhmm(), bid, requester, helper, helper, rid, str(ra.get("task_id")), obj,
				str(_act_lines(str(ra.get("conv_id", "")))), _emb.interior_bodies]),
			{"request_accepted": ra, "conversation_acts": _act_lines(str(ra.get("conv_id", "")))})
		# the helper at the object it accepted
		var orow := _object_row(bid, obj)
		var d_min := 1.0e9
		var d_start := -1.0
		for i in range(240):
			var b := _step(_game_dt)
			if b.is_empty():
				break
			var cb = _emb.body_of("cit:%d" % helper)
			if cb != null and not orow.is_empty():
				var want := _staged(float(orow["x"]), float(orow["y"]))
				var d := Vector2(cb.global_position.x, cb.global_position.z).distance_to(
					Vector2(want.x, want.z))
				if d_start < 0.0:
					d_start = d
				d_min = min(d_min, d)
				if d <= 1.5:
					break
			await get_tree().physics_frame
		var hrow2 := _row(SimBridge.last_mobility, helper)
		_place_player(hrow2, Vector2(3.0, 2.5))
		await _settle(10)
		var sess := _session_of(helper)
		_reached = d_min <= 2.0
		await _shot("06_helper_at_the_object.png", _caption(
			"%s — the helper (citizen %d) executing what it accepted: its CitizenBody is %.2f m from the authoritative position of %s (it was %.2f m away when the frame before was taken), and the authority's own GET_WORK session for it reads task %s / object %s / help_for %s. PIXELS: a body standing at a fixture inside the room. AUTHORITY ONLY: that this fixture is the object of the accepted request and that this body is the citizen that accepted it."
			% [_hhmm(), helper, d_min, obj, d_start, str(sess.get("task_id")),
				str(sess.get("object_id")), str(sess.get("help_for"))]),
			{"object_row": orow, "helper_session": sess, "d_start_m": d_start, "d_min_m": d_min})
		await _leave()
	else:
		_manifest.append({"file": null,
			"caption": "05/06 skipped: no REQUEST_ACCEPTED in the authority's dialogue log by %s" % _hhmm()})

	# --- 07 a refusal ---------------------------------------------------------
	await _until(_p_request_refused, 3.0 * 3600.0, 10.0, -1)
	var got_ref := _reached
	var refused := _dev("REQUEST_REFUSED")
	if got_ref and not refused.is_empty():
		var rf: Dictionary = refused[0]
		var rbid := -1
		for e in _dev("REQUEST_MADE"):
			if str(e.get("request_id", "")) == str(rf.get("request_id", "")):
				rbid = _iv(e.get("building_id"))
		var asker := _iv(rf.get("listener"))
		var asked_npc := _iv(rf.get("speaker"))
		if rbid >= 0:
			await _enter(rbid)
			_place_player(_row(SimBridge.last_mobility, asked_npc), Vector2(3.5, 3.0))
			await _settle(20)
		_reached = got_ref
		await _shot("07_request_refused.png", _caption(
			"%s — building %s: citizen %d asked citizen %d for help and was REFUSED. The authority's structured reason is \"%s\" (help score %s against threshold %s, components %s) and its rendered line is \"%s\". The whole exchange: %s. PIXELS: worker bodies in the staged interior where the authority says the refusal happened (%d interior bodies). AUTHORITY ONLY: the refusal, its reason and its score — nothing about a refusal is visible."
			% [_hhmm(), str(rbid), asker, asked_npc, str(rf.get("reason")), str(rf.get("score")),
				str(rf.get("threshold")), str(rf.get("components")),
				_refusal_line(str(rf.get("conv_id", ""))),
				str(_act_lines(str(rf.get("conv_id", "")))), _emb.interior_bodies]),
			{"request_refused": rf, "conversation_acts": _act_lines(str(rf.get("conv_id", "")))})
		if _scene.inside_building() >= 0:
			await _leave()
	else:
		_manifest.append({"file": null,
			"caption": "07 skipped: no REQUEST_REFUSED in the authority's dialogue log by %s" % _hhmm()})

	# --- 00 / 01 the player approaches a citizen inside the busiest shop ------
	await _until(_p_player_shopping, 6.0 * 3600.0, 60.0, _player)
	var shopping := _reached
	var prow := _row(SimBridge.last_mobility, _player)
	_shop = int(prow.get("building_id", -1))
	if not shopping or _shop < 0:
		_manifest.append({"file": null,
			"caption": "00-04 skipped: the player's citizen %d never became a customer inside a building" % _player})
		_finish()
		return
	await _enter(_shop)
	await _until(_p_someone_near_player, 30.0 * 60.0, 15.0, _player, true)
	var company := _reached
	var near := _people_nearby(_player)
	var npc := int(near[0]) if not near.is_empty() else -1
	var nrow := _row(SimBridge.last_mobility, npc) if npc >= 0 else {}
	_place_player(nrow, Vector2(2.0, 1.6))
	await _settle(20)
	_reached = company and npc >= 0
	await _shot("00_approach.png", _caption(
		"%s — the player's own citizen %d is a customer inside building %d (task %s, room %s) and the authority reports citizen(s) %s co-present with it (same room). The player avatar stands next to citizen %d's CitizenBody; %d bodies are drawn in this staged interior, each at its authoritative interior position. PIXELS: the shop floor with the player and other bodies in it. AUTHORITY ONLY: which body is which citizen, and that these two are close enough for the authority to allow a conversation."
		% [_hhmm(), _player, _shop, str(_work(prow).get("task")), str(_work(prow).get("room_id")),
			str(near), npc, _emb.interior_bodies]),
		{"people_nearby": near, "customers_in_shop": _customers(_shop)})

	var open_reply: Dictionary = _scene.talk_to_citizen(npc)
	await _settle(6)
	_reached = open_reply.get("ok", false) == true
	await _shot("01_panel_open.png", _caption(
		"%s — the dialogue panel, opened on citizen %d exactly as the T key opens it on a targeted citizen. Everything in it comes from the authority's TALK reply: the lines %s, the channel, the warmth %s and the relationship %s. PIXELS: the panel and its six bounded options, and the small label over the speaker's body carrying the same authority string. AUTHORITY ONLY: that these words are what that citizen said — Godot composed none of them."
		% [_hhmm(), npc, str(_panel.authority_lines()), str(open_reply.get("warmth")),
			str(open_reply.get("relationship"))]),
		{"talk_reply": open_reply})

	# the same question before anything has happened here
	_panel.context_building_id = _shop
	var pre := _panel.choose(0)
	await _settle(4)
	var pre_act := _answer_act(pre)
	if str(_prop(pre_act).get("kind", "")) == "UNKNOWN":
		_pre_unknown = pre
		_pre_unknown_npc = npc
	_panel.choose(5)
	await _settle(2)
	_scene.close_dialogue()

	# --- the threat -----------------------------------------------------------
	var customers := _customers(_shop)
	var seedable := []
	for cid in customers:
		if int(cid) != _player:
			seedable.append(int(cid))
	if seedable.is_empty():
		_manifest.append({"file": null, "caption": "02-04, 08 skipped: no other customer to seed in shop %d" % _shop})
		_finish()
		return
	_seeded = int(seedable[0])
	SimBridge.seed_outbreak("classic_zombie_fast", _seeded)
	await _until(_p_attacked_in_shop, 40.0 * 60.0, 5.0, _player, true)
	var attacked := _reached
	var first_attack := {}
	for e in _cog:
		if str(e.get("what", "")) == "attacked_by" and _iv(e.get("building_id")) == _shop:
			first_attack = e
			break

	# --- 02 / 03 the answers ---------------------------------------------------
	var asked := {}
	var witness_reply := {}
	var unknown_reply := {}
	var t := 0.0
	while t < 3.0 * 3600.0 and (_witness < 0 or _uninformed < 0):
		var chunk := 5.0 if _witness < 0 else 20.0
		var b := _step(chunk)
		if b.is_empty():
			break
		t += chunk
		var pr2 := _row(b, _player)
		if _scene.inside_building() >= 0 and int(pr2.get("building_id", -1)) != _scene.inside_building():
			await _leave()
		if _scene.inside_building() < 0 and int(pr2.get("building_id", -1)) >= 0:
			await _enter(int(pr2.get("building_id", -1)))
		for cid in _people_nearby(_player):
			var n := int(cid)
			if asked.has(n) or n == _seeded:
				continue
			var op: Dictionary = _scene.talk_to_citizen(n)
			if op.get("ok", false) != true:
				continue
			_panel.context_building_id = _shop
			var ans := _panel.choose(0)
			_pull()
			var act := _answer_act(ans)
			var p := _prop(act)
			asked[n] = "%s/%s" % [str(p.get("kind")), str(p.get("epistemic"))]
			var epi := str(p.get("epistemic", ""))
			if _witness < 0 and (epi == "DIRECT_OBSERVATION" or epi == "EXPERIENCED"):
				_witness = n
				witness_reply = ans
				var wrow := _row(SimBridge.last_mobility, n)
				_place_player(wrow, Vector2(2.0, 1.6))
				await _settle(12)
				_reached = attacked
				await _shot("02_grounded_answer.png", _caption(
					"%s — the player asked citizen %d \"What happened?\" (option 1, ASK_FACT scoped to building %d) minutes after the attack, and the panel shows the authority's answer verbatim: \"%s\" carrying epistemic status %s, proposition %s about citizen %s in room %s. The attack itself: %s. PIXELS: the panel text, the label over the speaker's body, and bodies in the world. AUTHORITY ONLY: that this citizen actually saw it — the epistemic status and the supporting memory fact (%s) live in its own store."
					% [_hhmm(), n, _shop, str(act.get("line")), epi, str(p.get("kind")),
						str(p.get("subject")), str(p.get("room_id")), str(first_attack),
						str(p.get("event_ref"))]),
					{"talk_reply": ans, "answer_proposition": p, "attack_event": first_attack})
				_panel.choose(5)
				_scene.close_dialogue()
			elif _uninformed < 0 and str(p.get("kind", "")) == "UNKNOWN":
				_uninformed = n
				unknown_reply = ans
				var urow := _row(SimBridge.last_mobility, n)
				_place_player(urow, Vector2(2.0, 1.6))
				await _settle(12)
				_reached = true
				await _shot("03_i_dont_know.png", _caption(
					"%s — the same question, ASK_FACT about building %d, put to citizen %d, which the authority's own store gives nothing to answer with: \"%s\" (kind %s, epistemic %s). PIXELS: the panel text. AUTHORITY ONLY: that this citizen has no memory of the event — an ignorant citizen and a knowing one look exactly alike."
					% [_hhmm(), _shop, n, str(act.get("line")), str(p.get("kind")),
						str(p.get("epistemic"))]),
					{"talk_reply": ans, "answer_proposition": p})
				_panel.choose(5)
				_scene.close_dialogue()
			else:
				_panel.choose(5)
				_scene.close_dialogue()
		await get_tree().physics_frame
	if _witness < 0:
		_manifest.append({"file": null,
			"caption": "02 skipped: no co-present citizen answered first hand; answers were %s" % str(asked)})
	if _uninformed < 0:
		# the pre-attack "I don't know." is the same grounded no-knowledge path,
		# and it is labelled as what it is.
		if not _pre_unknown.is_empty():
			var pact := _answer_act(_pre_unknown)
			var pp := _prop(pact)
			_scene.talk_to_citizen(_pre_unknown_npc)
			_panel.context_building_id = _shop
			var again := _panel.choose(0)
			await _settle(8)
			var aact := _answer_act(again)
			var ap := _prop(aact)
			_reached = false
			await _shot("03_i_dont_know.png", _caption(
				"NOT REACHED as a post-attack frame: in this run every citizen the authority ever put next to the player after the attack had fled the shop with it and answered first hand, so no post-attack \"I don't know.\" was available. What this frame DOES show is the same grounded no-knowledge path: earlier, at the time stamped in the manifest, citizen %d answered the identical question about building %d with \"%s\" (kind %s, epistemic %s) because its store held nothing about that building; asked again now the authority answers \"%s\" (kind %s, epistemic %s). PIXELS: the panel text. AUTHORITY ONLY: what that citizen does or does not remember."
				% [_pre_unknown_npc, _shop, str(pact.get("line")), str(pp.get("kind")),
					str(pp.get("epistemic")), str(aact.get("line")), str(ap.get("kind")),
					str(ap.get("epistemic"))]),
				{"pre_attack_reply": _pre_unknown, "asked_again_now": again,
					"post_attack_answers": asked})
			_panel.choose(5)
			_scene.close_dialogue()
		else:
			_manifest.append({"file": null,
				"caption": "03 skipped: no UNKNOWN answer was given to the player in this run; answers were %s" % str(asked)})

	# --- 04 the warning wave between NPCs -------------------------------------
	var warns := []
	for e in _dev("CONVERSATION_STARTED"):
		if str(e.get("channel", "")) in ["shout", "call", "face_to_face"] \
				and (e.get("topic") is Dictionary) and str(e["topic"].get("kind", "")).find("ATTACK") >= 0:
			warns.append(e)
	var rows := []
	for w in warns.slice(0, 6):
		rows.append("%s %s->%s: %s" % [str(w.get("channel")), str(w.get("speaker")),
			str(w.get("listener")), str(_act_lines(str(w.get("conv_id", ""))))])
	var pr3 := _row(SimBridge.last_mobility, _player)
	if _scene.inside_building() >= 0:
		await _leave()
	_place_player(pr3, Vector2(6.0, 6.0))
	_zoom(24.0)
	await _settle(20)
	_reached = not warns.is_empty()
	await _shot("04_npc_warning_exchange.png", _caption(
		"%s — the warning wave the authority ran between NPCs after the attack in shop %d: %d conversations about it so far (%s of them by shout, %s by call, %s face to face). The first of them, verbatim: %s. PIXELS: the street and the bodies on it around the player — a shout and a telephone call look exactly like nothing at all. AUTHORITY ONLY: everything about the exchange; the rows are in this manifest."
		% [_hhmm(), _shop, warns.size(), str(_count_channel(warns, "shout")),
			str(_count_channel(warns, "call")), str(_count_channel(warns, "face_to_face")),
			str(rows.slice(0, 2))]),
		{"warning_conversations": rows, "dialogue_kinds": _kinds})

	# --- 08 a conversation the threat cut short --------------------------------
	var interrupted := _dev("CONVERSATION_INTERRUPTED")
	var single := []
	for e in _dev("CONVERSATION_ENDED"):
		if str(e.get("reason", "")) in ["warning_in_passing", "shout"] and int(e.get("acts", 0)) <= 1:
			single.append(e)
	var pick := {}
	for e in interrupted:
		if str(e.get("reason", "")) == "threat":
			pick = e
			break
	if pick.is_empty() and not interrupted.is_empty():
		pick = interrupted[0]
	var who := -1
	if not pick.is_empty():
		var parts = pick.get("participants", [])
		if parts is Array and not parts.is_empty():
			who = int(parts[0])
	elif not single.is_empty():
		var parts2 = single[0].get("participants", [])
		if parts2 is Array and not parts2.is_empty():
			who = int(parts2[0])
	var wrow2 := _row(SimBridge.last_mobility, who) if who >= 0 else {}
	if not wrow2.is_empty():
		if _scene.inside_building() >= 0:
			await _leave()
		_place_player(wrow2, Vector2(7.0, 7.0))
	await _settle(20)
	_reached = not (pick.is_empty() and single.is_empty())
	await _shot("08_interrupted.png", _caption(
		"%s — a conversation the threat did not let finish. The authority's row: %s; and %d warning(s) in this run were delivered as a SINGLE act with no exchange to sit through, which is what an alarmed citizen does instead of talking (e.g. %s). The frame is centred on citizen %d (state %s, building %s) — one of the participants. PIXELS: bodies moving through the city. AUTHORITY ONLY: that a conversation was cut short, and why."
		% [_hhmm(), str(pick), single.size(), str(single[0]) if not single.is_empty() else "-",
			who, str(wrow2.get("state")), str(wrow2.get("building_id"))]),
		{"interrupted": pick, "single_act_warnings": single.size(),
			"interrupted_count": interrupted.size()})
	_finish()


func _count_channel(rows: Array, ch: String) -> int:
	var n := 0
	for r in rows:
		if str(r.get("channel", "")) == ch:
			n += 1
	return n


func _answer_act(reply: Dictionary) -> Dictionary:
	var acts = reply.get("acts", [])
	if not (acts is Array):
		return {}
	for i in range(acts.size() - 1, -1, -1):
		var a = acts[i]
		if a is Dictionary and str(a.get("act", "")) == "ANSWER":
			return a
	return {}


func _prop(act: Dictionary) -> Dictionary:
	var p = act.get("proposition")
	return p if p is Dictionary else {}


func _refusal_line(conv_id: String) -> String:
	for a in _acts_of(conv_id):
		if str(a.get("act", "")) == "REFUSE":
			return str(a.get("line", ""))
	return ""


func _finish() -> void:
	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"bundle": _bundle, "player_citizen": _player,
			"note": "The HUD text burned into every frame (\"Day 1 hh:mm\", \"Outbreak: 0%\") is the Godot scene's own GameClock overlay, which this harness freezes; it is NOT the authoritative clock. The authoritative hour of each frame is the `hour`/`clock` field of that frame's row below, read from the bridge summary at capture time. Every dialogue line shown in a panel is the string the Python DialogueRuntime rendered and returned in the TALK reply; `panel_displayed_lines` and `panel_authority_lines` of each row are the two sides of that claim.",
			"shop": _shop, "seeded": _seeded, "witness": _witness, "uninformed": _uninformed,
			"start_hour": _start_hour, "dialogue_kinds_drained": _kinds,
			"authority_counts": _counts, "shots": _manifest}, "  "))
		f.close()
	print("SHOTS done: %d" % _manifest.size())
	SimBridge.disconnect_from_sim()
	get_tree().quit(0)

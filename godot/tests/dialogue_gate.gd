extends Node

## DIALOGUE GATE — grounded player<->NPC and NPC<->NPC conversation in the real
## city (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1).
##
## Live Python bridge (protocol v8) + the REAL IsometricWorld scene + the REAL
## dialogue UI (`DialoguePanel`, driven exactly as the T key and the 1..6 option
## keys drive it: `IsometricWorld.talk_to_citizen()` / `dialogue_choose()` /
## `DialoguePanel.choose()`) + real Godot physics. The gate speaks NO dialogue
## and invents NO line: every word checked here is a string the Python
## DialogueRuntime rendered and returned in a TALK reply or a GET_DIALOGUE row.
##
## The day it drives (Houston, weekday from 05:00, seed 0):
##
##   * NPC <-> NPC REQUEST — a worker reports a problem to a coworker and asks
##     for help; the authority's conversation carries REPORT_PROBLEM /
##     ASK_FOR_HELP / ACCEPT and a REQUEST_ACCEPTED row with the task and the
##     object. The player stands in that staged interior and the helper's
##     CitizenBody walks to the object the authority sent it to.
##   * A REQUEST REFUSED with one of the authority's structured reasons.
##   * PLAYER TALK — the session's player citizen is a CUSTOMER of the busiest
##     shop, so its authoritative body is inside that shop's staged interior
##     with other people. The gate opens the real dialogue panel on a citizen
##     the authority reports co-present, and checks the panel displays exactly
##     the authority's lines.
##   * SAVE / LOAD in the middle of that open conversation: the dialogue counts
##     and the active conversation survive, and the next option continues the
##     SAME conv_id.
##   * THREAT — the lowest-id customer the authority reports inside the shop is
##     seeded with a fast pathogen, dies, rises and attacks. The player then
##     asks "What happened?" of the citizens the authority reports co-present:
##     a WITNESS answers first hand (DIRECT_OBSERVATION / EXPERIENCED), an
##     UNINFORMED citizen answers "I don't know." (UNKNOWN).
##   * A citizen far away refuses to talk at all: ok:false not_co_present.
##   * NPC <-> NPC CALL — a warning carried by telephone as a sequenced
##     conversation, and a conversation INTERRUPTED by the threat.
##
## THE GATE DECIDES NOTHING. It never picks a helper, a witness, a line or an
## answer: it reads them out of the authority's TALK replies and GET_DIALOGUE
## rows. The only two things it asks for are the player's own bounded speech
## acts and the one external shock the scenario needs (SEED_OUTBREAK on the
## lowest-id customer the authority reports inside the shop).
##
##   godot --headless --path godot res://tests/DialogueGate.tscn -- \
##       --bundle houston --player 82 --trace /tmp/trace.json

var _bundle := "houston"
var _player := 82                 # the citizen the player embodies (a shop customer at ~10:35)
var _start_hour := 5.0
var _trace_path := "/tmp/asph_dialogue_probe.json"
var _save_path := "/tmp/asph_dialogue_gate_save.json"
var _game_dt := 1.0

var _fail := 0
var _log: Array[String] = []
var _rows: Array = []
var _dlg: Array = []              # dialogue events kept by this gate
var _kinds := {}                  # every dialogue event kind seen -> count drained here
var _counts := {}                 # GET_DIALOGUE `counts`: the authority's persistent totals
var _dseq := 0
var _cseq := 0
var _wseq := 0
var _known_req := {}
var _advance_error := ""
var _cog: Array = []
var _scene: Node3D
var _emb: EmbodiedMobility
var _panel: DialoguePanel
var _stats := {}
var _talks: Array = []            # every TALK reply this gate made, verbatim

# scenario facts the AUTHORITY decides (the gate only reads them)
var _shop := -1
var _seeded := -1
var _witness := -1
var _uninformed := -1
var _far := -1

# predicate state
var _p_cid := -1

const MAX_KEPT := 9000
const LEASH_M := 5.0
const FIRST_HAND := ["DIRECT_OBSERVATION", "EXPERIENCED"]
const REFUSAL_REASONS := ["too_dangerous", "already_occupied", "no_capability", "low_trust",
	"current_urgent_task", "unavailable", "shift_obligation", "not_worth_it"]
const DIALOGUE_KEYS := ["version", "now_s", "active", "requests", "events", "event_seq",
	"counts", "recent_lines", "n_conversations"]


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_log.append("%s  %s  %s" % ["PASS" if cond else "FAIL", name, detail])
	print(_log[-1])
	if not cond:
		_fail += 1


func _info(name: String, detail: String) -> void:
	_log.append("INFO  %s  %s" % [name, detail])
	print(_log[-1])


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])
		elif args[i] == "--start-hour" and i + 1 < args.size():
			_start_hour = float(args[i + 1])
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])
	await get_tree().physics_frame
	await _run()
	_finish()


# ------------------------------------------------------------------ helpers
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _hour() -> float:
	return float(SimBridge.last_summary.get("hour", 0.0))


func _hhmm() -> String:
	var h := _hour()
	return "%02d:%02d" % [int(h), int(floor((h - floor(h)) * 60.0))]


func _row(block: Dictionary, cid: int) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == cid:
			return row
	return {}


func _work(row: Dictionary) -> Dictionary:
	var w = row.get("work", {})
	return w if w is Dictionary else {}


func _live_row(cid: int) -> Dictionary:
	return _row(SimBridge.get_mobility(false).get("mobility", {}), cid)


func _context(cid: int) -> Dictionary:
	var c = SimBridge.get_citizen_context(cid).get("context")
	return c if c is Dictionary else {}


## Who the AUTHORITY reports next to the player right now (same room indoors,
## or within its outdoor radius). The gate never computes co-presence itself.
func _people_nearby(cid: int) -> Array:
	var out := []
	for n in _context(cid).get("people_nearby", []):
		if n is Dictionary:
			out.append(_iv(n.get("citizen_id")))
		else:
			out.append(int(n))
	return out


func _focus(row: Dictionary) -> void:
	if row.is_empty():
		return
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		if _advance_error == "":
			_advance_error = "%s at hour %s" % [str(r.get("error")), _hhmm()]
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, d)
	return block


func _pull() -> void:
	## Drain both event logs every step (the Python side keeps rings).
	var d: Dictionary = SimBridge.get_dialogue(_dseq).get("dialogue", {})
	for e in d.get("events", []):
		_dseq = max(_dseq, int(e.get("seq", 0)))
		var kind := str(e.get("event", ""))
		_kinds[kind] = int(_kinds.get(kind, 0)) + 1
		if _dlg.size() < MAX_KEPT:
			_dlg.append(e)
	var counts = d.get("counts")
	if counts is Dictionary:
		_counts = counts
	var c: Dictionary = SimBridge.get_cognition(_cseq).get("cognition", {})
	for e in c.get("events", []):
		_cseq = max(_cseq, int(e.get("seq", 0)))
		if str(e.get("event", "")) == "PERCEIVED" and _cog.size() < MAX_KEPT:
			_cog.append(e)
	SimBridge.get_work(_wseq)  # refreshes last_work.sessions (read-only)
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


func _sessions() -> Dictionary:
	var s = SimBridge.last_work.get("sessions", {})
	return s if s is Dictionary else {}


func _session_of(cid: int) -> Dictionary:
	var s = _sessions().get(str(cid), {})
	return s if s is Dictionary else {}


func _shop_customers(bid: int) -> Array:
	var out := []
	for k in _sessions():
		var s = _sessions()[k]
		if s is Dictionary and str(s.get("kind", "")) == "customer" and _iv(s.get("building_id")) == bid:
			out.append(int(str(k)))
	out.sort()
	return out


## The customer census the authority reports per building right now — the
## evidence for calling one shop the busiest, not a claim the gate makes.
func _customer_census() -> Dictionary:
	var out := {}
	for k in _sessions():
		var s = _sessions()[k]
		if s is Dictionary and str(s.get("kind", "")) == "customer":
			var b := str(_iv(s.get("building_id")))
			out[b] = int(out.get(b, 0)) + 1
	return out


func _object_row(bid: int, oid: String) -> Dictionary:
	for o in SimBridge.get_rooms(bid).get("objects", []):
		if str(o["object_id"]) == oid:
			return o
	return {}


func _staged(x: float, y: float) -> Vector3:
	return _scene.interior_offset() + Vector3(x, _emb.body_height, y)


func _enter(bid: int) -> void:
	_scene.enter_building_by_id(bid)
	await get_tree().physics_frame
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


func _place_player_on(cid: int) -> void:
	## Put the Godot avatar where the authority puts the citizen the player
	## embodies, so the panel opens on a body that is actually there.
	var row := _row(SimBridge.last_mobility, cid)
	if row.is_empty():
		return
	var p = _scene.get_player()
	if p == null:
		return
	if _scene.inside_building() >= 0 and _scene.inside_building() == int(row.get("building_id", -1)):
		p.teleport(_staged(float(row["x"]), float(row["y"])) + Vector3(1.5, 1.0, 1.5))
	elif _scene.inside_building() < 0:
		p.teleport(Vector3(float(row["x"]) + 2.0, 1.5, float(row["y"]) + 2.0))
	_focus(row)


func _record(block: Dictionary, tag: String, cids: Array) -> void:
	for cid in cids:
		var row := _row(block, int(cid))
		if row.is_empty():
			continue
		var out := {"t": float(block.get("t_s", 0.0)), "hour": _hour(), "tag": tag,
			"citizen_id": int(cid), "state": row.get("state"), "ax": row.get("x"),
			"ay": row.get("y"), "building_id": row.get("building_id"),
			"work": _work(row), "dialogue": row.get("dialogue")}
		var cb = _emb.body_of("cit:%d" % int(cid))
		if cb != null:
			out["bx"] = cb.global_position.x
			out["bz"] = cb.global_position.z
			out["interior_body"] = _emb.interior_body_ids().has("cit:%d" % int(cid))
		_rows.append(out)


## Advance until `pred` says so or the budget runs out, draining both logs.
func _until(pred: Callable, max_game_s: float, chunk_s: float, tag: String, follow: Array) -> bool:
	var t := 0.0
	var i := 0
	while t < max_game_s:
		var block := _step(chunk_s)
		if block.is_empty():
			break
		t += chunk_s
		i += 1
		if not follow.is_empty():
			_focus(_row(block, int(follow[0])))
		_pull()
		if chunk_s <= 5.0 or i % 4 == 0:
			_record(block, tag, follow)
		if pred.call():
			return true
		await get_tree().physics_frame
	return false


## One TALK through the REAL UI: the panel the T key opens and the buttons /
## number keys drive. `option` < 0 means "open the panel" (its GREET).
func _panel_talk(cid: int, option: int, building_ctx: int = -2) -> Dictionary:
	var reply := {}
	if option < 0:
		reply = _scene.talk_to_citizen(cid)
	else:
		if building_ctx != -2:
			_panel.context_building_id = building_ctx
			_panel.context_room_id = -1
		reply = _panel.choose(option)
	_talks.append({"hour": _hour(), "clock": _hhmm(), "npc": cid,
		"option": option, "reply": reply,
		"panel_displayed": _panel.displayed_lines(),
		"panel_authority_lines": _panel.authority_lines()})
	return reply


func _answer_act(reply: Dictionary) -> Dictionary:
	## The NPC's ANSWER row of a reply (the authority's own act row).
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


# ------------------------------------------------------------ predicates
func _p_request_accepted() -> bool:
	return not _dev("REQUEST_ACCEPTED").is_empty()


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


# ------------------------------------------------------------------ the gate
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
	if not SimBridge.is_connected_to_sim():
		_ok("bridge_connected", false, "start python -m asphodel.bridge.server first")
		return
	_emb = _scene.get_embodied()
	_panel = _scene.get_dialogue_panel()
	if _emb == null or _panel == null:
		_ok("scene_has_dialogue_ui", false,
			"EmbodiedMobility=%s DialoguePanel=%s" % [str(_emb), str(_panel)])
		return
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	GameClock.time_scale = 0.0     # this gate is the only driver of the clock

	# --- (a) protocol v9 + a world with dialogue -----------------------------
	var started: Dictionary = SimBridge.last_summary
	var pv := int(started.get("protocol_version", -1))
	_ok("protocol_v9", pv == 9 and SimBridge.PROTOCOL_VERSION == 9,
		"START_WORLD reply protocol_version=%d, SimBridge speaks v%d (TALK / GET_DIALOGUE)"
		% [pv, SimBridge.PROTOCOL_VERSION])
	var on: bool = bool(started.get("dialogue_enabled", false))
	_ok("world_started_with_dialogue",
		on and SimBridge.dialogue_enabled and SimBridge.cognition_enabled
			and SimBridge.work_enabled and SimBridge.mobility_enabled,
		"the scene's own START_WORLD (bundle %s, start_hour %s, player_citizen_id %d) left the world at hour %s with dialogue_enabled=%s cognition=%s work=%s mobility=%s. NOTE: `player_citizen` is not in this summary because SimBridge.last_summary has already been replaced by the scene's first ADVANCE_TIME reply, whose summary block does not carry it; that the authority speaks as citizen %d is checked below on the first TALK reply (talk_speaks_as_the_player_citizen)."
		% [_bundle, str(_start_hour), _player, str(started.get("hour")), str(on),
			str(SimBridge.cognition_enabled), str(SimBridge.work_enabled),
			str(SimBridge.mobility_enabled), _player])
	if not on:
		return

	# --- (b) GET_DIALOGUE shape ---------------------------------------------
	var snap0: Dictionary = SimBridge.get_dialogue(0).get("dialogue", {})
	var missing := []
	for k in DIALOGUE_KEYS:
		if not snap0.has(k):
			missing.append(k)
	_ok("dialogue_snapshot_shape", missing.is_empty(),
		"GET_DIALOGUE v%s: %d keys, missing %s; %s conversations, %d active, event_seq=%s, counts=%s"
		% [str(snap0.get("version")), snap0.size(), str(missing),
			str(snap0.get("n_conversations")), snap0.get("active", []).size(),
			str(snap0.get("event_seq")), str(snap0.get("counts"))])
	_pull()

	# --- (c) NPC <-> NPC: a coworker asks another for help -------------------
	var got_req := await _until(_p_request_accepted, 6.0 * 3600.0, 10.0, "await_request", [])
	var accepted := _dev("REQUEST_ACCEPTED")
	if not got_req or accepted.is_empty():
		_ok("npc_request_accepted", false,
			"no REQUEST_ACCEPTED in the authority's dialogue log by %s (kinds drained: %s)"
			% [_hhmm(), str(_kinds)])
	else:
		var ra: Dictionary = accepted[0]
		var conv_id := str(ra.get("conv_id", ""))
		var helper := _iv(ra.get("speaker"))
		var requester := _iv(ra.get("listener"))
		var task := str(ra.get("task_id", ""))
		var obj := str(ra.get("object_id", ""))
		var acts := _acts_of(conv_id)
		var seq_acts := []
		var kinds := []
		var bid := -1
		for a in acts:
			seq_acts.append("%s->%s %s: %s" % [str(a.get("speaker")), str(a.get("listener")),
				str(a.get("act")), str(a.get("line"))])
			kinds.append(str(a.get("act", "")))
			if bid < 0:
				bid = _iv(a.get("building_id"))
		if bid < 0:
			for e in _dev("REQUEST_MADE"):
				if str(e.get("request_id", "")) == str(ra.get("request_id", "")):
					bid = _iv(e.get("building_id"))
		_ok("npc_request_accepted",
			acts.size() >= 3 and kinds.has("ASK_FOR_HELP") and kinds.has("ACCEPT"),
			"at %s citizen %d asked citizen %d for help and was accepted (request %s, task %s, object %s, building %d, score %s, components %s). The authority's sequenced acts: %s"
			% [_hhmm(), requester, helper, str(ra.get("request_id")), task, obj, bid,
				str(ra.get("score")), str(ra.get("components")), str(seq_acts)])
		# --- the helper's body walks to the object it accepted --------------
		# The gate can only watch a walk it arrives in time for. If the first
		# accepted request was already finished by the time the coarse scan saw
		# it, that is reported, and the gate waits for the NEXT accepted request
		# (5 s chunks) so it can enter the room while the helper is still moving.
		var watched := await _watch_help_walk(ra)
		var tries := [watched]
		if not bool(watched.get("observed", false)):
			_known_req[str(ra.get("request_id", ""))] = true
			for e in _dev("REQUEST_ACCEPTED"):
				_known_req[str(e.get("request_id", ""))] = true
			var again := await _until(_p_new_request_accepted, 120.0 * 60.0, 5.0, "await_request2", [])
			if again:
				var ra2 := {}
				for e in _dev("REQUEST_ACCEPTED"):
					if not _known_req.has(str(e.get("request_id", ""))):
						ra2 = e
						break
				if not ra2.is_empty():
					tries.append(await _watch_help_walk(ra2))
		var observed := false
		var details := []
		for x in tries:
			observed = observed or bool(x.get("observed", false))
			details.append(str(x.get("detail", "")))
		if observed:
			_ok("helper_body_reached_the_accepted_object", true, " || ".join(details))
		else:
			_info("helper_body_reached_the_accepted_object",
				"NOT OBSERVED as a walk: %s — reported, not claimed" % " || ".join(details))

	# --- (d) a refusal with a structured reason ------------------------------
	var refused := _dev("REQUEST_REFUSED")
	if refused.is_empty():
		_info("npc_request_refused_with_a_reason",
			"no REQUEST_REFUSED had been drained by %s" % _hhmm())
	else:
		var rr: Dictionary = refused[0]
		var reason := str(rr.get("reason", ""))
		_ok("npc_request_refused_with_a_reason", REFUSAL_REASONS.has(reason),
			"%d refusals so far; the first: citizen %s refused citizen %s with the authority's structured reason \"%s\" (score %s vs threshold %s, components %s, request %s). The refusal LINE is the authority's: %s"
			% [refused.size(), str(rr.get("speaker")), str(rr.get("listener")), reason,
				str(rr.get("score")), str(rr.get("threshold")), str(rr.get("components")),
				str(rr.get("request_id")), str(_refusal_line(str(rr.get("conv_id", ""))))])

	# --- (e) the player's own citizen goes shopping --------------------------
	var shopping := await _until(_p_player_shopping, 6.0 * 3600.0, 60.0, "await_shop", [_player])
	var prow := _row(SimBridge.last_mobility, _player)
	_shop = int(prow.get("building_id", -1))
	var census := _customer_census()
	if not shopping or _shop < 0:
		_ok("player_citizen_is_inside_a_shop", false,
			"citizen %d never became a customer inside a building by %s (state %s, building %s)"
			% [_player, _hhmm(), str(prow.get("state")), str(prow.get("building_id"))])
		return
	_ok("player_citizen_is_inside_a_shop", true,
		"at %s the authority reports the player's citizen %d as a %s inside building %d (task %s, room %s); the customer census over all buildings right now is %s, and %d of those customer sessions are in this one — the gate did not choose the building, the citizen's own itinerary did"
		% [_hhmm(), _player, str(_work(prow).get("role")), _shop, str(_work(prow).get("task")),
			str(_work(prow).get("room_id")), str(census), _shop_customers(_shop).size()])
	await _enter(_shop)
	_place_player_on(_player)
	_step(_game_dt)
	_pull()

	# --- (f) the dialogue panel opens on a co-present citizen ---------------
	var near_ok := await _until(_p_someone_near_player, 30.0 * 60.0, 15.0, "await_company", [_player])
	var near := _people_nearby(_player)
	if not near_ok or near.is_empty():
		_ok("panel_opens_on_a_co_present_npc", false,
			"the authority reports nobody co-present with citizen %d at %s" % [_player, _hhmm()])
		return
	var first := int(near[0])
	var open_reply := _panel_talk(first, -1)
	var pctx := _context(_player)
	_ok("panel_opens_on_a_co_present_npc",
		open_reply.get("ok", false) == true and _panel.is_open() and _panel.npc == first,
		"the gate drove the REAL UI path (IsometricWorld.talk_to_citizen(), the same call the T key makes on a resolved citizen target): TALK GREET to citizen %d while the authority puts the player's citizen %d in %s -> ok=%s, conv_id=%s, panel open=%s showing %d authority line(s), warmth %s, relationship %s"
		% [first, _player, str(pctx.get("location")), str(open_reply.get("ok")),
			str(open_reply.get("conv_id")), str(_panel.is_open()),
			_panel.authority_lines().size(), str(open_reply.get("warmth")),
			str(open_reply.get("relationship"))])
	_ok("talk_speaks_as_the_player_citizen",
		_iv(open_reply.get("player_citizen")) == _player,
		"the authority's TALK reply reports player_citizen=%s — the session speaks as the citizen the scene passed to START_WORLD (%d), which is the citizen whose position decides co-presence (the Godot avatar's own walking never moves it)"
		% [str(open_reply.get("player_citizen")), _player])
	var conv_before := str(_panel.conv_id)
	# the panel must show the authority's strings and nothing else
	var ask := _panel_talk(first, 0, _shop)      # option 1: "What happened?"
	var shown := _panel.displayed_lines()
	var authority := _panel.authority_lines()
	_ok("panel_shows_exactly_the_authority_lines",
		not authority.is_empty() and shown == authority,
		"after option 1 (ASK_FACT, building %d) the panel displays %s and the authority's TALK reply carried %s — identical=%s. The panel adds only the speaker prefix and the epistemic tag it copies out of the act's own proposition."
		% [_shop, str(shown), str(authority), str(shown == authority)])

	# the same bounded question, asked before anything has happened in that
	# building: the grounded-UNKNOWN path with its own rendered line
	var pre_act := _answer_act(ask)
	var pre_p := _prop(pre_act)
	if str(pre_p.get("kind", "")) == "UNKNOWN":
		var unk_rows := 0
		_pull()
		for e in _dev("ANSWER_UNKNOWN"):
			if _iv(e.get("speaker")) == first and _iv(e.get("listener")) == _player:
				unk_rows += 1
		_ok("answer_unknown_is_grounded_and_rendered",
			str(pre_act.get("line", "")) == "I don\'t know."
				and str(pre_p.get("epistemic", "")) == "UNKNOWN" and unk_rows > 0,
			"before anything has happened in shop %d, citizen %d answers the player's \"What happened?\" with \"%s\" (kind %s, epistemic %s) and the authority logs %d ANSWER_UNKNOWN row(s) for the pair — the same grounded no-knowledge path the post-attack uninformed check looks for"
			% [_shop, first, str(pre_act.get("line")), str(pre_p.get("kind")),
				str(pre_p.get("epistemic")), unk_rows])
	else:
		_info("answer_unknown_is_grounded_and_rendered",
			"citizen %d already had something to report about shop %d before the attack: %s [%s] — no pre-event UNKNOWN to check here"
			% [first, _shop, str(pre_act.get("line")), str(pre_p.get("epistemic"))])

	# --- (g) SAVE / LOAD across an open player conversation ------------------
	var counts_before := _counts.duplicate(true)
	var snap_before: Dictionary = SimBridge.get_dialogue(0).get("dialogue", {})
	var sr: Dictionary = SimBridge.save(_save_path)
	var lr: Dictionary = SimBridge.load(_save_path)
	var snap_after: Dictionary = SimBridge.get_dialogue(0).get("dialogue", {})
	var after := _panel_talk(first, 3, _shop)    # option 4: "Is this place safe?"
	var same_conv: bool = str(after.get("conv_id", "")) == conv_before and conv_before != ""
	var active_before := []
	for a in snap_before.get("active", []):
		active_before.append(str(a.get("conv_id", "")))
	var active_after := []
	for a in snap_after.get("active", []):
		active_after.append(str(a.get("conv_id", "")))
	_ok("saveload_keeps_dialogue_and_the_open_conversation",
		sr.get("ok", false) and lr.get("ok", false)
			and JSON.stringify(snap_before.get("counts", {})) == JSON.stringify(snap_after.get("counts", {}))
			and _iv(snap_before.get("event_seq")) == _iv(snap_after.get("event_seq"))
			and active_before == active_after and same_conv and after.get("ok", false) == true,
		"SAVE+LOAD around the open conversation %s: counts %s -> %s, event_seq %s -> %s, active conversations %s -> %s; the next option (ASK_SAFETY) continued in conv_id %s (same=%s) and the NPC answered %s"
		% [conv_before, str(snap_before.get("counts")), str(snap_after.get("counts")),
			str(snap_before.get("event_seq")), str(snap_after.get("event_seq")),
			str(active_before), str(active_after), str(after.get("conv_id")), str(same_conv),
			str(after.get("lines"))])
	_info("saveload_load_reply_player_citizen",
		"AUTHORITY OBSERVATION: the LOAD reply does not echo player_citizen (%s) although the session keeps it — the very next TALK reply reports player_citizen=%s and the conversation continued"
		% [str(lr.get("player_citizen")), str(after.get("player_citizen"))])
	# a request the player makes as a customer: reported, whatever the authority says
	var helpr := _panel_talk(first, 4, _shop)    # option 5: "Can you cover this task?"
	_info("player_request_for_help",
		"the player's ASK_FOR_HELP (kind cover_station, object %s) to citizen %d: ok=%s, the authority's acts %s — the player's citizen is a CUSTOMER here, so a refusal with a structured reason is the honest outcome, not a bug"
		% [str(_panel.context_object_id), first, str(helpr.get("ok")),
			str(_lines_of(helpr))])
	var bye := _panel_talk(first, 5)             # option 6: "Goodbye"
	_ok("end_conversation_closes_it",
		bye.get("ok", false) == true and str(bye.get("state", "")) == "ended",
		"option 6 (END_CONVERSATION) -> state %s, the authority's closing lines %s"
		% [str(bye.get("state")), str(_lines_of(bye))])
	_scene.close_dialogue()

	# --- (h) the threat ------------------------------------------------------
	var customers := _shop_customers(_shop)
	var seedable := []
	for cid in customers:
		if int(cid) != _player:
			seedable.append(int(cid))
	if seedable.is_empty():
		_ok("threat_seeded_on_a_shop_customer", false,
			"the authority reports no other customer inside shop %d at %s (customers %s)"
			% [_shop, _hhmm(), str(customers)])
		return
	_seeded = int(seedable[0])
	var sr2: Dictionary = SimBridge.seed_outbreak("classic_zombie_fast", _seeded)
	_ok("threat_seeded_on_a_shop_customer", sr2.get("ok", false),
		"at %s the authority reports customer sessions %s inside shop %d; SEED_OUTBREAK(classic_zombie_fast, %d) accepted=%s"
		% [_hhmm(), str(customers), _shop, _seeded, str(sr2.get("ok"))])
	var attacked := await _until(_p_attacked_in_shop, 40.0 * 60.0, 5.0, "await_attack", [_player])
	var first_attack := {}
	for e in _cog:
		if str(e.get("what", "")) == "attacked_by" and _iv(e.get("building_id")) == _shop:
			first_attack = e
			break
	_ok("undead_attacks_inside_the_shop", attacked and not first_attack.is_empty(),
		"at %s the risen citizen %d attacked inside shop %d: the first PERCEIVED attacked_by is citizen %s in room %s"
		% [_hhmm(), _seeded, _shop, str(first_attack.get("citizen_id")),
			str(first_attack.get("room_id"))])

	# --- (i) ask the people the authority puts next to the player ------------
	# The gate asks EVERY co-present citizen the same bounded question and
	# sorts them by the ANSWER the authority gives: it never picks a witness.
	var asked := {}
	var refusals := {}
	var t := 0.0
	var nearby_n := 1
	# The witness is looked for at 5 s while the alarm is fresh; the hunt for a
	# citizen that never heard of it runs on to the evening (the player's own
	# citizen goes home after its errand and is alone there for hours), fast
	# while nobody is co-present and slow while somebody is.
	# 6 game hours: past that the authority's own ADVANCE_TIME raises
	# KeyError('conv:<n>') once more than MAX_CONVERSATIONS_KEPT conversations
	# have ended (see the AUTHORITY OBSERVATION at the end of this run), so the
	# gate stops the hunt before the crash rather than running into it.
	while t < 6.0 * 3600.0 and (_witness < 0 or _uninformed < 0):
		var chunk := 5.0 if _witness < 0 else (15.0 if nearby_n > 0 else 60.0)
		var b := _step(chunk)
		if b.is_empty():
			break
		t += chunk
		_pull()
		_record(b, "post_attack", [_player])
		var pr2 := _row(b, _player)
		_focus(pr2)
		if _scene.inside_building() >= 0 and int(pr2.get("building_id", -1)) != _scene.inside_building():
			await _leave()
		if _scene.inside_building() < 0 and int(pr2.get("building_id", -1)) >= 0:
			await _enter(int(pr2.get("building_id", -1)))
		_place_player_on(_player)
		var nearby := _people_nearby(_player)
		nearby_n = nearby.size()
		for cid in nearby:
			var n := int(cid)
			if asked.has(n) or n == _seeded:
				continue
			var open2 := _panel_talk(n, -1)
			if open2.get("ok", false) != true:
				# not an answer: the authority would not let them talk at all.
				# Recorded, and re-tried later if they become co-present.
				refusals[n] = str(open2.get("reason", "?"))
				continue
			var ans := _panel_talk(n, 0, _shop)   # option 1: "What happened?"
			_pull()
			var act := _answer_act(ans)
			var p := _prop(act)
			var epi := str(p.get("epistemic", ""))
			var kind := str(p.get("kind", ""))
			asked[n] = "%s/%s" % [kind, epi]
			if _witness < 0 and FIRST_HAND.has(epi) and _iv(p.get("building_id")) == _shop:
				_witness = n
				_check_witness(n, act, p)
			elif _uninformed < 0 and kind == "UNKNOWN" and epi == "UNKNOWN":
				_uninformed = n
				_check_uninformed(n, act, p)
			else:
				_panel_talk(n, 5)
			_scene.close_dialogue()
		await get_tree().physics_frame
	if _witness < 0:
		_ok("witness_answers_first_hand", false,
			"no co-present citizen answered ASK_FACT about shop %d first hand within %d game minutes of the attack; the answers the authority gave were %s (refusals %s)"
			% [_shop, int(t / 60.0), str(asked), str(refusals)])
		_ok("panel_line_equals_the_authority_line", false, "no witness answer to compare against")
		_ok("ask_location_is_grounded_in_the_same_event", false, "no witness to ask")
	if _uninformed < 0:
		_info("uninformed_npc_answers_unknown",
			"NOT REACHED: no co-present citizen answered ASK_FACT about shop %d with UNKNOWN in the %d game minutes after the attack. Everyone the authority ever put next to the player's citizen %d in that window had fled the shop with it, and after 10:55 that citizen is alone in its own home (it lives alone in the bundle). The answers the authority gave were %s (and the citizens it refused to let talk: %s). Reported, not claimed."
			% [_shop, int(t / 60.0), _player, str(asked), str(refusals)])
	_info("co_present_answers",
		"every citizen the authority reported co-present with the player and the answer kind/epistemic it gave: %s; and the ones the authority refused to let talk, with its reason: %s (asked over %d game minutes, ending at %s)"
		% [str(asked), str(refusals), int(t / 60.0), _hhmm()])

	# --- (j) a citizen far away cannot be talked to --------------------------
	var pr3 := _live_row(_player)
	var here := Vector2(float(pr3.get("x", 0.0)), float(pr3.get("y", 0.0)))
	var tried_far := []
	for r in SimBridge.last_mobility.get("citizens", []):
		if _far >= 0 or tried_far.size() >= 14:
			break
		var cid := int(r["citizen_id"])
		if cid == _player:
			continue
		var d := here.distance_to(Vector2(float(r["x"]), float(r["y"])))
		if d < 400.0:
			continue
		var reply: Dictionary = SimBridge.talk(cid, "ASK_FACT", {"building_id": _shop})
		_talks.append({"hour": _hour(), "npc": cid, "option": -2, "reply": reply,
			"distance_m": d, "note": "far-away probe (TALK command directly, no panel)"})
		tried_far.append("%d@%.0fm:%s" % [cid, d, str(reply.get("reason", reply.get("ok")))])
		if reply.get("ok", false) == false and str(reply.get("reason", "")).begins_with("not_co_present"):
			_far = cid
			_ok("far_npc_is_not_co_present", true,
				"TALK ASK_FACT to citizen %d, %.0f m away from the player's citizen %d, was refused by the authority: ok=false reason=\"%s\" (no conversation started, no line invented). Probes tried: %s"
				% [cid, d, _player, str(reply.get("reason")), str(tried_far)])
	if _far < 0:
		_ok("far_npc_is_not_co_present", false,
			"no far-away citizen answered with not_co_present; the refusals the authority gave were %s" % str(tried_far))

	# --- (k) NPC <-> NPC over the telephone, and an interrupted conversation --
	var calls := []
	for e in _dev("CONVERSATION_STARTED"):
		if str(e.get("channel", "")) == "call":
			calls.append(e)
	if calls.is_empty():
		_info("npc_call_conversation_is_sequenced",
			"no call-channel conversation had been drained by %s" % _hhmm())
	else:
		var cconv := str(calls[0].get("conv_id", ""))
		var cacts := _acts_of(cconv)
		var seq := []
		var alternating := true
		var increasing := true
		var last_speaker := -1
		var last_t := -1.0
		for a in cacts:
			seq.append("%s: %s" % [str(a.get("speaker")), str(a.get("line"))])
			if int(a.get("speaker", -1)) == last_speaker:
				alternating = false
			last_speaker = int(a.get("speaker", -1))
			var tt := float(a.get("t", 0.0))
			if tt < last_t:
				increasing = false
			last_t = tt
		_ok("npc_call_conversation_is_sequenced",
			cacts.size() >= 4 and alternating and increasing,
			"conversation %s on channel \"call\": citizen %s called citizen %s about %s and the authority played %d acts, alternating=%s, non-decreasing act times=%s: %s"
			% [cconv, str(calls[0].get("speaker")), str(calls[0].get("listener")),
				str(calls[0].get("topic")), cacts.size(), str(alternating), str(increasing),
				str(seq)])
	var interrupted := _dev("CONVERSATION_INTERRUPTED")
	var passing := []
	for e in _dev("CONVERSATION_ENDED"):
		if str(e.get("reason", "")) in ["warning_in_passing", "shout"] and int(e.get("acts", 0)) <= 1:
			passing.append(e)
	if not interrupted.is_empty():
		var ie: Dictionary = interrupted[0]
		for e in interrupted:
			if str(e.get("reason", "")) == "threat":
				ie = e
				break
		_ok("conversation_interrupted_or_single_act_warning", true,
			"%d conversation(s) were INTERRUPTED and %d warning(s) were single-act exchanges in passing. The first interruption: %s between %s on channel %s after %s act(s), reason \"%s\" (%d act(s) dropped)"
			% [interrupted.size(), passing.size(), str(ie.get("conv_id")),
				str(ie.get("participants")), str(ie.get("channel")), str(ie.get("acts")),
				str(ie.get("reason")), _iv(ie.get("dropped"), 0)])
	elif not passing.is_empty():
		var pe: Dictionary = passing[0]
		_ok("conversation_interrupted_or_single_act_warning", true,
			"no CONVERSATION_INTERRUPTED was drained, but %d warning(s) were delivered as a SINGLE act with no exchange to sit through (the authority's own handling of an alarmed speaker): e.g. %s between %s, reason \"%s\", acts %s"
			% [passing.size(), str(pe.get("conv_id")), str(pe.get("participants")),
				str(pe.get("reason")), str(pe.get("acts"))])
	else:
		_ok("conversation_interrupted_or_single_act_warning", false,
			"neither a CONVERSATION_INTERRUPTED row nor a single-act warning was drained after the attack (kinds: %s)" % str(_kinds))

	# --- (l) every answer's frame matches its epistemic status ---------------
	var frames := {"DIRECT_OBSERVATION": "I saw", "EXPERIENCED": "It happened to me:",
		"HEARSAY": "I heard", "BELIEF": "I think", "UNCERTAIN": "I\'m not sure, but I think",
		"UNKNOWN": "I don\'t know"}
	var checked := 0
	var bad := []
	for tk in _talks:
		var rep = tk.get("reply")
		if not (rep is Dictionary) or rep.get("ok", false) != true:
			continue
		for a in rep.get("acts", []):
			if not (a is Dictionary) or str(a.get("act", "")) != "ANSWER":
				continue
			var p2 = a.get("proposition")
			if not (p2 is Dictionary):
				continue
			var epi2 := str(p2.get("epistemic", ""))
			var line2 := str(a.get("line", ""))
			checked += 1
			if epi2 == "SECOND_HAND":
				if not line2.begins_with("citizen %s told me" % str(p2.get("source_citizen"))):
					bad.append("%s | %s" % [epi2, line2])
			elif frames.has(epi2):
				if not line2.begins_with(str(frames[epi2])):
					bad.append("%s | %s" % [epi2, line2])
			else:
				bad.append("unknown epistemic %s | %s" % [epi2, line2])
	_ok("answer_frames_match_the_epistemic_status", checked > 0 and bad.is_empty(),
		"%d ANSWER acts came back to the player in this run; every one of them opens with the frame its own proposition's epistemic status prescribes (\"I saw\" / \"It happened to me:\" / \"<who> told me\" / \"I heard\" / \"I think\" / \"I\'m not sure, but I think\" / \"I don\'t know\"). Mismatches: %s"
		% [checked, str(bad)])

	if _advance_error != "":
		_info("advance_time_error",
			"AUTHORITY OBSERVATION: an ADVANCE_TIME was refused by the authority during this run: %s. The gate stopped that phase and carried on with what it already had."
			% _advance_error)

	_stats = {"event_kinds": _kinds, "authority_counts": _counts, "player": _player,
		"shop": _shop, "seeded": _seeded, "witness": _witness, "uninformed": _uninformed,
		"far": _far, "hour_end": _hour(), "interior_bodies": _emb.interior_bodies,
		"promotions": _emb.promotions, "demotions": _emb.demotions}
	SimBridge.disconnect_from_sim()


## The witness checks, made ON THE OPEN PANEL, in the same conversation, before
## the gate moves on to anyone else.
func _check_witness(n: int, act: Dictionary, p: Dictionary) -> void:
	var wline := str(act.get("line", ""))
	_ok("witness_answers_first_hand",
		FIRST_HAND.has(str(p.get("epistemic", ""))) and str(p.get("kind", "")) != "UNKNOWN",
		"citizen %d, co-present with the player's citizen %d, answered \"What happened?\" with %s [%s] — proposition kind %s, subject %s, building %s, room %s, confidence %s, event_ref %s, hops %s. The line is the authority's."
		% [n, _player, wline, str(p.get("epistemic")), str(p.get("kind")), str(p.get("subject")),
			str(p.get("building_id")), str(p.get("room_id")), str(p.get("confidence")),
			str(p.get("event_ref")), str(p.get("hops"))])
	_ok("panel_line_equals_the_authority_line",
		_panel.authority_lines().has(wline) and _panel.displayed_lines().has(wline),
		"the witness's answer line is in the panel's authority rows (%s) and in what the panel DISPLAYS (%s) — byte-identical, no rewriting. Panel rows: %s"
		% [str(_panel.authority_lines().has(wline)), str(_panel.displayed_lines().has(wline)),
			str(_panel.displayed_lines())])
	var loc := _panel_talk(n, 1)                 # option 2: "Where was that?"
	var lact := _answer_act(loc)
	var lp := _prop(lact)
	_ok("ask_location_is_grounded_in_the_same_event",
		loc.get("ok", false) == true and str(lp.get("kind", "")) == "EVENT_LOCATION"
			and _iv(lp.get("building_id")) == _shop,
		"option 2 (ASK_LOCATION, with NO event_ref sent — the authority resolves it from what this NPC last asserted to this player): %s [%s], kind %s, building %s, room %s, event_ref %s"
		% [str(lact.get("line")), str(lp.get("epistemic")), str(lp.get("kind")),
			str(lp.get("building_id")), str(lp.get("room_id")), str(lp.get("event_ref"))])
	var bye := _panel_talk(n, 5)
	_info("witness_conversation_closed",
		"END_CONVERSATION with the witness -> state %s, the authority's lines %s"
		% [str(bye.get("state")), str(_lines_of(bye))])


## The uninformed citizen's checks, on the open panel.
func _check_uninformed(n: int, act: Dictionary, p: Dictionary) -> void:
	var uctx := _context(n)
	var mem_here := 0
	for f in uctx.get("memories", []):
		if _iv(f.get("building_id")) == _shop:
			mem_here += 1
	var ev_unknown := 0
	for e in _dev("ANSWER_UNKNOWN"):
		if _iv(e.get("speaker")) == n and _iv(e.get("listener")) == _player:
			ev_unknown += 1
	var line := str(act.get("line", ""))
	_ok("uninformed_npc_answers_unknown",
		str(p.get("kind", "")) == "UNKNOWN" and str(p.get("epistemic", "")) == "UNKNOWN"
			and line == "I don\'t know." and ev_unknown > 0
			and _panel.displayed_lines().has(line),
		"citizen %d, co-present with the player's citizen %d, answered \"What happened at building %d?\" with \"%s\" — kind %s, epistemic %s; the authority logged %d ANSWER_UNKNOWN row(s) for this pair, GET_CITIZEN_CONTEXT(%d) holds %d salient memories about that building (of %s in all), and the panel displayed the line verbatim (%s)"
		% [n, _player, _shop, line, str(p.get("kind")), str(p.get("epistemic")), ev_unknown, n,
			mem_here, str(uctx.get("n_memories")), str(_panel.displayed_lines())])
	_panel_talk(n, 5)


## Enter the building of an accepted request and watch the helper's CitizenBody
## against the authoritative position of the object it accepted. Returns
## {observed: bool, detail: String}.
func _watch_help_walk(ra: Dictionary) -> Dictionary:
	var helper := _iv(ra.get("speaker"))
	var obj := str(ra.get("object_id", ""))
	var rid := str(ra.get("request_id", ""))
	var bid := -1
	for e in _dev("REQUEST_MADE"):
		if str(e.get("request_id", "")) == rid:
			bid = _iv(e.get("building_id"))
	if bid < 0:
		for a in _acts_of(str(ra.get("conv_id", ""))):
			if bid < 0:
				bid = _iv(a.get("building_id"))
	if bid < 0:
		return {"observed": false, "detail": "request %s carries no building_id" % rid}
	if _scene.inside_building() != bid:
		if _scene.inside_building() >= 0:
			await _leave()
		await _enter(bid)
	_step(_game_dt)
	_pull()
	var orow := _object_row(bid, obj)
	if orow.is_empty():
		await _leave()
		return {"observed": false,
			"detail": "object %s of request %s is not in GET_ROOMS(%d)" % [obj, rid, bid]}
	var otarget := Vector2(float(orow["x"]), float(orow["y"]))
	var hid := "cit:%d" % helper
	var d_start := -1.0
	var d_min := 1.0e9
	var walked := 0.0
	var last_pos := Vector3.ZERO
	var done := false
	for i in range(600):
		var b2 := _step(_game_dt)
		if b2.is_empty():
			break
		_pull()
		_record(b2, "help_walk", [helper, _iv(ra.get("listener"))])
		_focus(_row(b2, helper))
		var cb = _emb.body_of(hid)
		if cb != null:
			if last_pos != Vector3.ZERO:
				walked += Vector2(cb.global_position.x, cb.global_position.z).distance_to(
					Vector2(last_pos.x, last_pos.z))
			last_pos = cb.global_position
			var want := _staged(otarget.x, otarget.y)
			var d := Vector2(cb.global_position.x, cb.global_position.z).distance_to(
				Vector2(want.x, want.z))
			if d_start < 0.0:
				d_start = d
			d_min = min(d_min, d)
		for e in _dev("REQUEST_COMPLETED"):
			if str(e.get("request_id", "")) == rid:
				done = true
		if done and d_start >= 0.0:
			break
		await get_tree().physics_frame
	var sess := _session_of(helper)
	var closed := d_start - d_min
	var observed: bool = d_start > 2.0 and closed >= 1.0
	var detail := "request %s (task %s, object %s, building %d): when the gate reached the staged interior the helper's (citizen %d) CitizenBody was %.2f m from the authoritative object position (%.1f, %.1f); it then closed %.2f m to %.2f m, walking %.1f m; GET_WORK session object %s / help_for %s; REQUEST_COMPLETED=%s" % [
		rid, str(ra.get("task_id")), obj, bid, helper, d_start, otarget.x, otarget.y, closed,
		d_min, walked, str(sess.get("object_id")), str(sess.get("help_for")), str(done)]
	await _leave()
	return {"observed": observed, "detail": detail}


func _p_new_request_accepted() -> bool:
	for e in _dev("REQUEST_ACCEPTED"):
		if not _known_req.has(str(e.get("request_id", ""))):
			return true
	return false


func _lines_of(reply: Dictionary) -> Array:
	var out := []
	for a in reply.get("acts", []):
		if a is Dictionary:
			out.append(str(a.get("line", "")))
	return out


func _refusal_line(conv_id: String) -> String:
	for a in _acts_of(conv_id):
		if str(a.get("act", "")) == "REFUSE":
			return str(a.get("line", ""))
	return ""


func _finish() -> void:
	var n := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n += 1
	if n < 14:
		_ok("all_checks_ran", false, "only %d PASS/FAIL checks ran" % n)
	print("\n==== DIALOGUE GATE RESULTS (%s, player citizen %d, shop %d) ===="
		% [_bundle, _player, _shop])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle, "player": _player,
			"shop": _shop, "seeded": _seeded, "witness": _witness, "uninformed": _uninformed,
			"start_hour": _start_hour, "game_dt": _game_dt, "results": _log, "stats": _stats,
			"talks": _talks, "dialogue_events": _dlg, "rows": _rows}))
		f.close()
		print("TRACE saved: %s (%d rows, %d dialogue events, %d talks)"
			% [_trace_path, _rows.size(), _dlg.size(), _talks.size()])
	get_tree().quit(1 if _fail > 0 else 0)

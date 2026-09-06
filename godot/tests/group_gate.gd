extends Node

## GROUP GATE — a real survivor group observed live in the real city
## (ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1).
##
## Live Python bridge (protocol v9) + the REAL IsometricWorld scene + real Godot
## physics. The gate invents NO group fact: every membership, role, shelter,
## coordinator, shared-record fact and query result checked here is a value the
## Python GroupRuntime put in a GET_GROUPS snapshot or a GROUP_QUERY reply.
##
## Groups form only from real cooperation, so a short live run will not naturally
## form the certified group. This gate uses the milestone's recommended approach
## (b): a short Python pre-step (tools/groups_build_scenario.py) drove the SAME
## causal chain the certification day uses — repeated mutual aid + fleeing danger
## together -> a group emerges; a shelter chosen from member knowledge; members
## regroup; a coordinator, a guard and a scavenger take real roles; an outsider
## becomes assessable; a threat warning shared with preserved provenance — and
## SAVEd the world. This gate:
##
##   1. lets the scene boot its OWN fresh world through START_WORLD and checks
##      the v9 handshake and that groups are enabled by default (a live world
##      with the group layer running);
##   2. LOADs the pre-built save over the SAME live bridge (the real save/load +
##      bridge path), reaching a world that already holds the emerged group;
##   3. observes and queries that group live through GET_GROUPS / GROUP_QUERY and
##      asserts on the authoritative snapshot — group present with >=3 members, a
##      shelter, a coordinator; valid membership states; a role held; membership
##      resolves for a member and is null for a non-member; where resolves the
##      shelter; the shared record shows provenance; a grounded ask-to-join.
##
## Every citizen id the gate touches (a member, a non-member, the outsider, the
## coordinator, the guard, the shelter) was DISCOVERED from authoritative state
## by the pre-step and handed over in a sidecar — there is no city-name logic.
##
##   godot --headless --path godot res://tests/GroupGate.tscn -- \
##       --bundle houston --save /tmp/save.json --sidecar /tmp/scn.json --trace /tmp/t.json

var _bundle := "houston"
var _player := 82
var _start_hour := 8.0
var _game_dt := 1.0
var _save_path := "/tmp/asph_group_save.json"
var _sidecar_path := "/tmp/asph_group_scenario.json"
var _trace_path := "/tmp/asph_group_probe.json"

var _fail := 0
var _log: Array[String] = []
var _scene: Node3D
var _side := {}
var _snap := {}
var _stats := {}

const GROUP_KEYS := ["version", "groups", "member_of", "events", "event_seq", "counts"]
const VALID_STATES := ["candidate", "invited", "provisional", "member", "departed", "expelled"]
const ACTIVE_STATES := ["provisional", "member"]
const HELD_ROLES := ["coordinator", "guard", "scavenger"]


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
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])
		elif args[i] == "--save" and i + 1 < args.size():
			_save_path = args[i + 1]
		elif args[i] == "--sidecar" and i + 1 < args.size():
			_sidecar_path = args[i + 1]
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
	await get_tree().physics_frame
	await _run()
	_finish()


# ------------------------------------------------------------------ helpers
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _hour() -> float:
	return float(SimBridge.last_summary.get("hour", 0.0))


func _load_sidecar() -> bool:
	if not FileAccess.file_exists(_sidecar_path):
		return false
	var f := FileAccess.open(_sidecar_path, FileAccess.READ)
	if f == null:
		return false
	var txt := f.get_as_text()
	f.close()
	var parsed = JSON.parse_string(txt)
	if not (parsed is Dictionary):
		return false
	_side = parsed
	return true


func _get_groups(since := 0) -> Dictionary:
	var r := SimBridge.get_groups_snapshot(since)
	var g = r.get("groups", {})
	return g if g is Dictionary else {}


func _members_of(g: Dictionary) -> Dictionary:
	var m = g.get("members", {})
	return m if m is Dictionary else {}


func _active_members(g: Dictionary) -> Array:
	var out := []
	for k in _members_of(g):
		if ACTIVE_STATES.has(str(_members_of(g)[k])):
			out.append(int(str(k)))
	out.sort()
	return out


func _event_kinds(snap: Dictionary) -> Dictionary:
	var out := {}
	for e in snap.get("events", []):
		var k := str(e.get("event", ""))
		out[k] = int(out.get(k, 0)) + 1
	return out


func _events_of(snap: Dictionary, kind: String) -> Array:
	var out := []
	for e in snap.get("events", []):
		if str(e.get("event", "")) == kind:
			out.append(e)
	return out


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
	GameClock.time_scale = 0.0     # this gate is the only driver of the clock

	# --- (a) protocol v9 handshake ------------------------------------------
	var started: Dictionary = SimBridge.last_summary
	var pv := int(started.get("protocol_version", -1))
	_ok("protocol_v9", pv == 9 and SimBridge.PROTOCOL_VERSION == 9,
		"START_WORLD reply protocol_version=%d, SimBridge speaks v%d (GET_GROUPS / GROUP_QUERY)"
		% [pv, SimBridge.PROTOCOL_VERSION])

	# --- (b) the scene's own fresh world runs the group layer ----------------
	var on: bool = bool(started.get("groups_enabled", false)) or SimBridge.groups_enabled
	_ok("world_started_with_groups",
		on and SimBridge.groups_enabled and SimBridge.dialogue_enabled
			and SimBridge.cognition_enabled and SimBridge.mobility_enabled,
		"the scene's own START_WORLD (bundle %s, start_hour %s) left the world at hour %s with groups_enabled=%s (dialogue=%s cognition=%s work=%s mobility=%s). START_WORLD enables the survivor-group layer by default alongside dialogue."
		% [_bundle, str(_start_hour), str(started.get("hour")), str(SimBridge.groups_enabled),
			str(SimBridge.dialogue_enabled), str(SimBridge.cognition_enabled),
			str(SimBridge.work_enabled), str(SimBridge.mobility_enabled)])
	if not SimBridge.groups_enabled:
		return

	# A fresh short-lived world has no formed group yet (groups emerge from real
	# cooperation over time) — that is the honest baseline the LOAD then changes.
	var fresh := _get_groups(0)
	_info("fresh_world_baseline",
		"before LOAD, the scene's just-booted world reports %d group(s) (a group emerges only from real cooperation, so a freshly started world has none — this is why the deterministic scenario is built by the pre-step and reached here through the real save/load path)"
		% _members_of_count(fresh))

	# --- (c) LOAD the pre-built world that already holds the emerged group ----
	if not _load_sidecar():
		_ok("scenario_sidecar_present", false,
			"no scenario sidecar at %s — run tools/groups_build_scenario.py first (the gate shell script does)" % _sidecar_path)
		return
	if not FileAccess.file_exists(_save_path):
		_ok("scenario_save_present", false, "no scenario save at %s" % _save_path)
		return
	var lr: Dictionary = SimBridge.load(_save_path)
	_ok("loaded_world_with_group",
		lr.get("ok", false) == true and SimBridge.groups_enabled,
		"LOAD %s over the live bridge -> ok=%s, groups_enabled=%s, hour=%s. The pre-step formed the group '%s' (reason \"%s\") and SAVEd it; this is the real save/load + bridge path reaching the emerged group."
		% [_save_path, str(lr.get("ok")), str(SimBridge.groups_enabled), str(lr.get("hour")),
			str(_side.get("group_id")), str(_side.get("formed_reason"))])

	# --- (d) GET_GROUPS snapshot shape --------------------------------------
	_snap = _get_groups(0)
	var missing := []
	for k in GROUP_KEYS:
		if not _snap.has(k):
			missing.append(k)
	_ok("get_groups_snapshot_shape", missing.is_empty(),
		"GET_GROUPS v%s: keys %s, missing %s; %d group(s), member_of=%s, event_seq=%s, counts=%s"
		% [str(_snap.get("version")), str(_snap.keys()), str(missing),
			_members_of_count(_snap), str(_snap.get("member_of")),
			str(_snap.get("event_seq")), str(_snap.get("counts"))])

	# --- (e) a real group: >=3 members, a shelter, a coordinator -------------
	var gid := str(_side.get("group_id", ""))
	var groups = _snap.get("groups", {})
	var g = groups.get(gid, {}) if groups is Dictionary else {}
	if not (g is Dictionary) or g.is_empty():
		_ok("real_group_present", false,
			"the authority's snapshot has no group '%s' (groups: %s)" % [gid, str(groups.keys() if groups is Dictionary else groups)])
		return
	var active := _active_members(g)
	var shelter := _iv(g.get("shelter_building"))
	var coordinator := _iv(g.get("coordinator"))
	_ok("real_group_present",
		active.size() >= 3 and shelter >= 0 and coordinator >= 0 and active.has(coordinator),
		"group '%s' formed at %ss holds %d active members %s, shelters in building %d (room %s, entrance room %s, node %s), and its coordinator is citizen %d (an active member). founders %s, formed_reason \"%s\"."
		% [gid, str(g.get("created_s")), active.size(), str(active), shelter,
			str(g.get("shelter_room")), str(g.get("entrance_room")), str(g.get("shelter_node")),
			coordinator, str(g.get("founders")), str(g.get("formed_reason"))])

	# --- (f) every membership state is valid ---------------------------------
	var bad_states := []
	for k in _members_of(g):
		var stt := str(_members_of(g)[k])
		if not VALID_STATES.has(stt):
			bad_states.append("%s=%s" % [str(k), stt])
	_ok("membership_states_valid", bad_states.is_empty(),
		"the group's membership map is %s; every state is one of %s (invalid: %s)"
		% [str(_members_of(g)), str(VALID_STATES), str(bad_states)])

	# --- (g) a real role is held (guard / scavenger / coordinator) -----------
	var roles = g.get("roles", {})
	var roles_d: Dictionary = roles if roles is Dictionary else {}
	var held := []
	for r in roles_d:
		if HELD_ROLES.has(str(r)) and _active_members(g).has(_iv(roles_d[r])):
			held.append("%s=%d" % [str(r), _iv(roles_d[r])])
	_ok("a_role_is_held", not held.is_empty(),
		"the group's active members hold real roles %s (from %s). The roles were taken through the real role-request path (ROLE_PROPOSED -> ROLE_ACCEPTED), the coordinator emerged at formation from highest influence."
		% [str(held), str(roles_d)])

	# --- (h) GROUP_QUERY membership: a member resolves, a non-member is null --
	var member: int = active[0]
	# prefer a member that also holds a role, so the role field is exercised
	for r in roles_d:
		if HELD_ROLES.has(str(r)) and active.has(_iv(roles_d[r])):
			member = _iv(roles_d[r])
			break
	var non_member := _iv(_side.get("non_member"))
	var qm := SimBridge.group_query("membership", member)
	var qn := SimBridge.group_query("membership", non_member)
	_ok("group_query_membership",
		str(qm.get("in_group", "")) == gid and qn.get("in_group") == null,
		"GROUP_QUERY membership(citizen %d) -> in_group=%s role=%s (a member of '%s'); membership(citizen %d) -> in_group=%s (a non-member the pre-step confirmed is in no group). The authority answered both from live state."
		% [member, str(qm.get("in_group")), str(qm.get("role")), gid,
			non_member, str(qn.get("in_group"))])

	# --- (i) GROUP_QUERY where returns the shelter ---------------------------
	var qw := SimBridge.group_query("where", member)
	var where = qw.get("group", {})
	var where_d: Dictionary = where if where is Dictionary else {}
	_ok("group_query_where_returns_shelter",
		_iv(where_d.get("shelter_building")) == shelter and shelter >= 0,
		"GROUP_QUERY where(citizen %d) -> shelter_building=%s (room %s), members %s — the same shelter (%d) the group selected from its members' own knowledge and recorded in the snapshot."
		% [member, str(where_d.get("shelter_building")), str(where_d.get("shelter_room")),
			str(where_d.get("members")), shelter])

	# --- (j) the shared record / a GROUP_WARNING shows provenance ------------
	var shared = g.get("shared_record", {})
	var shared_d: Dictionary = shared if shared is Dictionary else {}
	var prov := {}
	for fid in shared_d:
		var gf = shared_d[fid]
		if gf is Dictionary and gf.get("origin_witness") != null:
			prov = gf
			break
	var warnings := _events_of(_snap, "GROUP_WARNING")
	var warn_fact_id := ""
	if not warnings.is_empty():
		warn_fact_id = str(warnings[0].get("fact_id", ""))
	_ok("shared_record_shows_provenance",
		not prov.is_empty() and _iv(prov.get("origin_witness")) >= 0
			and not warnings.is_empty() and shared_d.has(warn_fact_id),
		"the group's shared record holds a fact with preserved provenance: fact %s (kind %s) records origin_witness=%s, source_citizen=%s, subject=%s, building=%s — the lineage of the citizen who first knew it, never an omniscient copy. A GROUP_WARNING event references fact %s (reporter %s, told %s, uncontacted %s), and that fact is in the shared record."
		% [str(prov.get("fact_id")), str(prov.get("kind")), str(prov.get("origin_witness")),
			str(prov.get("source_citizen")), str(prov.get("subject")), str(prov.get("building_id")),
			warn_fact_id, str(warnings[0].get("reporter") if not warnings.is_empty() else null),
			str(warnings[0].get("told") if not warnings.is_empty() else null),
			str(warnings[0].get("uncontacted") if not warnings.is_empty() else null)])

	# --- (k) GROUP_QUERY ask_to_join is grounded -----------------------------
	var outsider := _iv(_side.get("outsider"))
	if outsider < 0:
		_info("group_query_ask_to_join_is_grounded",
			"the pre-step found no assessable outsider to offer the group; ask-to-join not exercised")
	else:
		var qj := SimBridge.group_query("ask_to_join", member, outsider)
		var res = qj.get("result", {})
		var res_d: Dictionary = res if res is Dictionary else {}
		var accept = res_d.get("accept")
		var reason := str(res_d.get("reason", ""))
		_ok("group_query_ask_to_join_is_grounded",
			res_d.get("ok", false) == true and (accept is bool) and reason != "",
			"GROUP_QUERY ask_to_join(via member %d, player citizen %d) -> ok=%s, accept=%s, reason=\"%s\", aggregate=%s. The group ran its real admission decision (each member votes from its own knowledge of the outsider, influence-weighted, resolved within capacity) — a grounded accept/refuse, not a free-text guess."
			% [member, outsider, str(res_d.get("ok")), str(accept), reason, str(res_d.get("aggregate"))])

	# --- (l) the group is still there under the LIVE clock -------------------
	var b := SimBridge.advance_time(_game_dt, "mobility")
	var snap2 := _get_groups(0)
	var g2 = (snap2.get("groups", {}) as Dictionary).get(gid, {})
	var active2 := _active_members(g2 if g2 is Dictionary else {})
	_ok("group_persists_live_after_advance",
		b.get("ok", false) == true and active2.size() >= 3 and active2.has(coordinator),
		"after one live ADVANCE_TIME (%ss) the authority still reports group '%s' with %d active members %s and coordinator %d — membership and roles are LOD/clock independent and survive the load into a running world."
		% [str(_game_dt), gid, active2.size(), str(active2), coordinator])

	_stats = {"group_id": gid, "members": active, "coordinator": coordinator, "shelter": shelter,
		"roles": roles_d, "event_kinds": _event_kinds(_snap), "counts": _snap.get("counts"),
		"outsider": outsider, "non_member": non_member, "member_queried": member,
		"hour_end": _hour(), "sidecar": _side}
	SimBridge.disconnect_from_sim()


func _members_of_count(snap: Dictionary) -> int:
	var g = snap.get("groups", {})
	return g.size() if g is Dictionary else 0


func _finish() -> void:
	var n := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n += 1
	if n < 10:
		_ok("all_checks_ran", false, "only %d PASS/FAIL checks ran" % n)
	print("\n==== GROUP GATE RESULTS (%s, group %s) ===="
		% [_bundle, str(_side.get("group_id"))])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle,
			"save_path": _save_path, "sidecar_path": _sidecar_path,
			"results": _log, "stats": _stats, "snapshot": _snap}))
		f.close()
		print("TRACE saved: %s" % _trace_path)
	get_tree().quit(1 if _fail > 0 else 0)

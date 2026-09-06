extends Node
## ConvergenceSelfTest — a built-in headless self-test the SHIPPED build runs when
## launched with `-- --selftest-convergence` (Convergence V2 §38/§53). It proves the
## exported executable, from a clean directory with no repo and no system Python,
## auto-starts its OWN bundled authority, completes the v9 handshake, starts the
## real world with the full system stack, and shuts the authority down cleanly.
##
## It does nothing on a normal launch (no flag), so it is inert for players.

func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if not args.has("--selftest-convergence"):
		return
	call_deferred("_run")


func _run() -> void:
	var out := {"ok": false, "steps": []}
	var args := OS.get_cmdline_user_args()
	var bundle := "houston"
	var checkpoint := ""
	var restore := ""
	var final_state := ""
	for i in range(args.size() - 1):
		if args[i] == "--selftest-bundle":
			bundle = args[i + 1]
		elif args[i] == "--selftest-save":
			checkpoint = args[i + 1]
		elif args[i] == "--selftest-load":
			restore = args[i + 1]
		elif args[i] == "--selftest-state":
			final_state = args[i + 1]
	var boot: Dictionary = AuthorityLauncher.ensure_authority()
	out["steps"].append({"auto_start": boot.get("ok", false), "port": boot.get("port")})
	if not boot.get("ok", false):
		out["error"] = "authority did not auto-start: %s" % str(boot)
		_emit(out)
		return
	var hello: Dictionary = SimBridge.last_hello
	out["steps"].append({"handshake": int(hello.get("protocol_version", -1)) == SimBridge.PROTOCOL_VERSION,
		"sim_sha": str(hello.get("sim_sha", ""))})
	var started: Dictionary
	if restore != "":
		started = SimBridge.load(restore)
	else:
		started = SimBridge.start_world(bundle, {"start_hour": 8.0})
	var flags_on = started.get("mobility_enabled", false) and started.get("cognition_enabled", false) \
		and started.get("dialogue_enabled", false) and started.get("groups_enabled", false) \
		and started.get("work_enabled", false)
	out["steps"].append({"start_world": started.get("ok", false), "city": started.get("city"),
		"n_citizens": started.get("n_citizens"), "full_stack": flags_on})
	var saved := true
	if checkpoint != "":
		saved = SimBridge.save(checkpoint).get("ok", false)
		out["steps"].append({"save": saved})
	var advanced: Dictionary = SimBridge.advance_time(30.0)
	var snap: Dictionary = SimBridge.snapshot()
	out["world"] = snap.get("world", {})
	if final_state != "":
		saved = SimBridge.save(final_state).get("ok", false) and saved
	out["ok"] = boot.get("ok", false) and started.get("ok", false) and flags_on \
		and saved and advanced.get("ok", false) and snap.get("ok", false) \
		and int(hello.get("protocol_version", -1)) == SimBridge.PROTOCOL_VERSION
	AuthorityLauncher.shutdown()
	_emit(out)


func _emit(out: Dictionary) -> void:
	print("SELFTEST_CONVERGENCE " + JSON.stringify(out))
	var path := "user://selftest_convergence.json"
	var args := OS.get_cmdline_user_args()
	for i in range(args.size() - 1):
		if args[i] == "--selftest-trace":
			path = args[i + 1]
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(out, "  "))
		f.close()
	get_tree().quit(0 if out.get("ok", false) else 1)

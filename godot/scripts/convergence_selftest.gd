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
	var boot: Dictionary = AuthorityLauncher.ensure_authority()
	out["steps"].append({"auto_start": boot.get("ok", false), "port": boot.get("port")})
	if not boot.get("ok", false):
		out["error"] = "authority did not auto-start: %s" % str(boot)
		_emit(out)
		return
	var hello: Dictionary = SimBridge.last_hello
	out["steps"].append({"handshake": int(hello.get("protocol_version", -1)) == SimBridge.PROTOCOL_VERSION,
		"sim_sha": str(hello.get("sim_sha", "")).substr(0, 12)})
	var started: Dictionary = SimBridge.start_world("houston", {"start_hour": 8.0})
	var flags_on = started.get("mobility_enabled", false) and started.get("cognition_enabled", false) \
		and started.get("dialogue_enabled", false) and started.get("groups_enabled", false)
	out["steps"].append({"start_world": started.get("ok", false), "city": started.get("city"),
		"n_citizens": started.get("n_citizens"), "full_stack": flags_on})
	SimBridge.advance_time(30.0)
	out["ok"] = boot.get("ok", false) and started.get("ok", false) and flags_on
	AuthorityLauncher.shutdown()
	_emit(out)


func _emit(out: Dictionary) -> void:
	print("SELFTEST_CONVERGENCE " + JSON.stringify(out))
	var f := FileAccess.open("user://selftest_convergence.json", FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(out, "  "))
		f.close()
	get_tree().quit(0 if out.get("ok", false) else 1)

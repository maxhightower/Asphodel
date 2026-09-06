extends Node
## AuthorityLauncher — owns the bundled simulation authority process so the
## Windows player never opens a terminal or starts Python (Convergence V2 §8-§10).
##
## Registered as the autoload singleton "AuthorityLauncher". Lifecycle:
##   1. pick a free localhost port (robust against a busy 8765, §10)
##   2. spawn the authority child on that port — the frozen `authority/` executable
##      shipped beside the game, or in a dev checkout `python tools/authority_launch.py`
##   3. health-check by completing SimBridge's HELLO handshake (build/protocol
##      verified, §11); retry until the child is listening or we time out
##   4. own the child: kill it on quit so there are no zombie authorities (§9)
##
## We only ever connect to the port we just spawned our own child on, and the
## handshake verifies protocol/build — so we never silently attach to a foreign,
## incompatible process (§10/§11).

signal authority_ready(port: int, hello: Dictionary)
signal authority_failed(code: String, detail: String)

const HEALTH_TIMEOUT_MS := 15000
const HEALTH_RETRY_MS := 150

var authority_port := -1
var running := false
var last_error_code := ""
var last_error_detail := ""
var _pid := -1
var _owns_child := false


func _exit_tree() -> void:
	shutdown()


func ensure_authority(host: String = "127.0.0.1") -> Dictionary:
	## Idempotent: bring up (or reuse) the owned authority and connect SimBridge.
	## Returns {ok, port, code, detail}.
	if running and SimBridge.is_connected_to_sim():
		return {"ok": true, "port": authority_port, "code": "", "detail": ""}

	var port := _free_port()
	if port <= 0:
		return _fail("port_failure", "could not reserve a free localhost port")

	var cmd := _resolve_authority()
	if not cmd.get("ok", false):
		return _fail(cmd.get("code", "authority_missing"), cmd.get("detail", ""))

	var args: Array = cmd["args"].duplicate()
	args.append("--port")
	args.append(str(port))
	args.append("--host")
	args.append(host)

	# Non-blocking spawn; we own the returned PID.
	_pid = OS.create_process(cmd["exe"], args, false)
	if _pid <= 0:
		return _fail("authority_crashed",
			"failed to spawn authority: %s %s" % [cmd["exe"], str(args)])
	_owns_child = true

	# Health check: the child needs a moment to bind and start serving.
	var deadline := Time.get_ticks_msec() + HEALTH_TIMEOUT_MS
	while Time.get_ticks_msec() < deadline:
		if _pid > 0 and not OS.is_process_running(_pid):
			return _fail("authority_crashed",
				"authority process exited before it began serving (see logs)")
		if SimBridge.connect_to_sim(host, port, HEALTH_RETRY_MS):
			authority_port = port
			running = true
			last_error_code = ""
			last_error_detail = ""
			authority_ready.emit(port, SimBridge.last_hello)
			return {"ok": true, "port": port, "code": "", "detail": ""}
		OS.delay_msec(HEALTH_RETRY_MS)

	return _fail("connect_failure",
		"authority did not accept a connection on port %d within %d ms"
		% [port, HEALTH_TIMEOUT_MS])


func shutdown() -> void:
	## Graceful: SHUTDOWN over the socket (the server stops itself), then make sure
	## the owned child is gone so relaunch never hits a stale authority/port (§9).
	if SimBridge.is_connected_to_sim():
		SimBridge.disconnect_from_sim()
	if _owns_child and _pid > 0 and OS.is_process_running(_pid):
		OS.delay_msec(120)   # give the graceful SHUTDOWN a moment to take
		if OS.is_process_running(_pid):
			OS.kill(_pid)
	_pid = -1
	_owns_child = false
	running = false
	authority_port = -1


# ---------------------------------------------------------------- internals
func _fail(code: String, detail: String) -> Dictionary:
	last_error_code = code
	last_error_detail = detail
	shutdown()
	push_error("AuthorityLauncher %s: %s" % [code, detail])
	authority_failed.emit(code, detail)
	return {"ok": false, "port": -1, "code": code, "detail": detail}


func _free_port() -> int:
	var s := TCPServer.new()
	# port 0 asks the OS for any free ephemeral port.
	if s.listen(0, "127.0.0.1") != OK:
		return -1
	var p := s.get_local_port()
	s.stop()
	return p


func _resolve_authority() -> Dictionary:
	## Prefer the frozen authority shipped beside the executable; fall back to a
	## dev checkout's python entrypoint.
	var exe_dir := OS.get_executable_path().get_base_dir()
	var is_win := OS.get_name() == "Windows"
	var bundled := exe_dir.path_join("authority").path_join(
		"asphodel-authority" + (".exe" if is_win else ""))
	if FileAccess.file_exists(bundled):
		return {"ok": true, "exe": bundled, "args": []}

	# Dev: run tools/authority_launch.py with the interpreter we can find.
	var repo := _repo_root()
	var launch := repo.path_join("tools").path_join("authority_launch.py")
	if not FileAccess.file_exists(launch):
		return {"ok": false, "code": "authority_missing",
			"detail": "no bundled authority at %s and no dev entrypoint at %s"
				% [bundled, launch]}
	var py := _find_python()
	if py == "":
		return {"ok": false, "code": "authority_missing",
			"detail": "no bundled authority and no python interpreter on PATH"}
	return {"ok": true, "exe": py, "args": [launch]}


func _repo_root() -> String:
	# res:// maps to the godot/ project dir; the repo root is its parent.
	var proj := ProjectSettings.globalize_path("res://").trim_suffix("/")
	return proj.get_base_dir()


func _find_python() -> String:
	if OS.get_name() == "Windows":
		for c in ["python", "python3"]:
			var r := _which(c)
			if r != "":
				return r
		return ""
	for c in ["python3", "python"]:
		var r := _which(c)
		if r != "":
			return r
	return ""


func _which(name: String) -> String:
	var out: Array = []
	var finder := "where" if OS.get_name() == "Windows" else "which"
	var code := OS.execute(finder, [name], out, true)
	if code == 0 and out.size() > 0:
		var line := String(out[0]).strip_edges().split("\n")[0].strip_edges()
		if line != "" and FileAccess.file_exists(line):
			return line
	# Last resort: the bare name (create_process may still resolve it via PATH).
	return name if OS.get_name() != "Windows" else ""

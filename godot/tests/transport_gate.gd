extends Node
## Real local TCP tests: partial reply timeout, fragmentation, request correlation.
var failures := 0
var server: TCPServer
var remote: StreamPeerTCP

func check(ok: bool, label: String) -> void:
	print(("PASS " if ok else "FAIL ") + label)
	if not ok:
		failures += 1

func pair() -> bool:
	server = TCPServer.new()
	if server.listen(0, "127.0.0.1") != OK:
		return false
	SimBridge._peer = StreamPeerTCP.new()
	SimBridge._peer.connect_to_host("127.0.0.1", server.get_local_port())
	var end := Time.get_ticks_msec() + 1000
	while Time.get_ticks_msec() < end:
		SimBridge._peer.poll()
		if server.is_connection_available():
			remote = server.take_connection()
			return true
		OS.delay_msec(1)
	return false

func close_pair() -> void:
	SimBridge.disconnect_from_sim()
	if remote != null:
		remote.disconnect_from_host()
	server.stop()

func _ready() -> void:
	if not pair():
		check(false, "local TCP pair")
		get_tree().quit(1)
		return
	remote.put_data('{"ok":'.to_utf8_buffer())
	var started := Time.get_ticks_msec()
	var result: Dictionary = SimBridge._read_reply(30)
	check(result.get("error", {}).get("code") == "reply_timeout", "partial reply times out")
	check(Time.get_ticks_msec() - started < 1000, "timeout is bounded")
	check(SimBridge._peer == null, "timed-out stream cannot serve a later request")
	close_pair()
	if pair():
		remote.put_data('{"ok":true,'.to_utf8_buffer())
		remote.put_data('"value":"caf\u00e9"}\n'.to_utf8_buffer())
		result = SimBridge._read_reply(1000)
		check(result.get("ok", false) and result.get("value") == "café", "fragmented JSON is assembled")
		close_pair()
	else:
		check(false, "fragment TCP pair")
	if pair():
		remote.put_data('{"ok":true,"id":-999}\n'.to_utf8_buffer())
		result = SimBridge._send("SNAPSHOT", {}, 1000)
		check(result.get("error", {}).get("code") == "reply_mismatch", "stale response id rejected")
		close_pair()
	else:
		check(false, "correlation TCP pair")
	get_tree().quit(0 if failures == 0 else 1)

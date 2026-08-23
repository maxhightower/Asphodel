extends Node

## BW7 — deterministic save/destroy/reload through the real client path.
##
## Two phases, each run against a SEPARATE Python server process (the process is
## destroyed between them, which is the point):
##
##   phase=save: START houston -> ADVANCE to K -> SAVE checkpoint -> ADVANCE M ->
##               SAVE reference  (reference = uninterrupted continuation)
##   phase=load: LOAD checkpoint -> ADVANCE M -> SAVE continued
##
## A separate Python comparator then asserts reference == continued bit-for-bit.

const K := 30
const M := 20


func _ready() -> void:
	var phase := "save"
	var ckpt := "/tmp/asph_ckpt.json"
	var ref := "/tmp/asph_reference.json"
	var cont := "/tmp/asph_continued.json"
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--phase" and i + 1 < args.size():
			phase = args[i + 1]

	var ok := false
	for attempt in range(50):
		if SimBridge.connect_to_sim("127.0.0.1", 8765):
			ok = true
			break
		OS.delay_msec(100)
	if not ok:
		printerr("saveload[%s]: no connection" % phase)
		return get_tree().quit(1)

	if phase == "save":
		var r: Dictionary = SimBridge.start_world("houston", {"seed": 1, "player_citizen_id": 5})
		if not r.get("ok", false):
			printerr("START failed: ", r)
			return get_tree().quit(1)
		SimBridge.set_focus([int(r.get("player_home_zone", 0))])
		SimBridge.advance(K, false)
		SimBridge.save(ckpt)
		SimBridge.advance(M, false)
		SimBridge.save(ref)
		print("saveload[save]: wrote checkpoint + reference at tick ", K + M)
	else:
		var rl: Dictionary = SimBridge.load(ckpt)
		if not rl.get("ok", false):
			printerr("LOAD failed: ", rl)
			return get_tree().quit(1)
		SimBridge.advance(M, false)
		SimBridge.save(cont)
		print("saveload[load]: continued reload to tick ", int(rl.get("tick", 0)) + M)

	SimBridge.disconnect_from_sim()
	get_tree().quit(0)

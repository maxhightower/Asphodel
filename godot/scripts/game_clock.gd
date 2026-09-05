extends Node

## The one authoritative gameplay clock + outbreak-progression + pause authority,
## registered as the autoload singleton "GameClock". Everything time-driven reads
## from here so the citizen, the HUD, the day/night lighting and the outbreak all
## describe the same reality.
##
## Time model (mirrors asphodel/gametime.py): a full 24h in-game day defaults to
## one real hour (Project-Zomboid pacing). The player's hour advances in real
## time; each in-game moment maps onto a simulation tick.
##
## M1 change — the clock is NO LONGER the outbreak authority. It used to read a
## baked per-tick belief timeline (timeline.json) and compute the visible outbreak
## from it. Now the authoritative Python World owns the outbreak: as in-game time
## crosses a tick boundary this clock asks SimBridge to ADVANCE the live world by
## that many ticks and reads the authoritative mean belief back. The baked
## timeline is retained only as an offline/preview fixture, never as game truth.
## When no live bridge is connected the clock still keeps time; the outbreak value
## simply holds (no baked truth is substituted).
##
## Pause authority: pause() sets get_tree().paused. This node and the player are
## PAUSABLE, so both this clock and the player's physics freeze together; while
## paused no ADVANCE is sent, so the authoritative world is frozen too. The pause
## UI runs in a WHEN_PAUSED layer so it still responds.

signal ticked(game_day: int, hour: float, outbreak: float)
signal paused_changed(is_paused: bool)
## Embodied mobility: a fresh movement block arrived from ADVANCE_TIME.
## `game_dt` is the game seconds the block advanced by since the previous one.
signal mobility_updated(block: Dictionary, game_dt: float)

const REAL_SECONDS_PER_DAY := 3600.0
const HOURS_PER_DAY := 24.0

# Multiplier on how fast in-game time flows vs wall-clock (1.0 = the default
# PZ pacing). Raise it to fast-forward (used by the headless smoke test to make
# outbreak progression observable within a few real frames).
var time_scale: float = 1.0
var configured: bool = false
var game_day: int = 1
var hour: float = 8.0                      # in-game hour [0, 24)
var sim_tick: int = 0                      # authoritative tick of the live World
var _dt_days: float = 0.25
var _n_ticks: int = 0
var _elapsed_ingame_hours: float = 0.0     # since spawn, for tick mapping
var _is_paused: bool = false

# Authoritative outbreak intensity (mean zone belief in [0,1]), fed by the live
# World via SimBridge. Held between ticks; NOT derived from any baked timeline.
var _outbreak: float = 0.0
# Optional bound live bridge (SimBridge autoload). When present + connected, tick
# crossings drive World.advance and refresh _outbreak from the authoritative reply.
var _bridge: Node = null

# --- Embodied mobility clock (ASPHODEL_EMBODIED_MOBILITY_V1) --------------
# When the live world executes itineraries (SimBridge.mobility_enabled) the
# clock sends ADVANCE_TIME with the exact game seconds elapsed, throttled to
# SEND_INTERVAL real seconds per request; the server auto-ticks the epidemic
# when the sub-tick clock crosses a tick, so there is ONE time axis.
const SEND_INTERVAL := 0.1
var use_time_clock := true
var _pending_game_s := 0.0
var _since_send := 0.0
var _last_snapshot_tick := -1


func _ready() -> void:
	# PAUSABLE: when the tree is paused this clock stops advancing, so the
	# outbreak stops with it. (The pause UI uses a WHEN_PAUSED layer instead.)
	process_mode = Node.PROCESS_MODE_PAUSABLE


func configure(meta: Dictionary, start_hour: float) -> void:
	## Wire the clock to a loaded bundle's time axis + the citizen's spawn hour.
	## Outbreak truth comes from the bound bridge (bind_bridge), not from `meta`.
	_dt_days = float(meta.get("dt", 0.25))
	_n_ticks = int(meta.get("n_ticks", 0))
	hour = clampf(start_hour, 0.0, 23.999)
	game_day = 1
	sim_tick = 0
	_elapsed_ingame_hours = 0.0
	_is_paused = false
	_outbreak = 0.0
	configured = true
	# Emit an initial state so listeners paint the correct starting time at once.
	ticked.emit(game_day, hour, outbreak_belief())


func bind_bridge(bridge: Node) -> void:
	## Bind the authoritative live World client. When connected, tick crossings
	## drive World.advance and refresh the outbreak from the authoritative reply.
	_bridge = bridge


func apply_outbreak(value: float) -> void:
	## Externally set the authoritative outbreak intensity (e.g. from an initial
	## SNAPSHOT before the first tick crossing).
	_outbreak = clampf(value, 0.0, 1.0)


func reset() -> void:
	configured = false
	set_paused(false)


# ------------------------------------------------------------------ pause
func set_paused(p: bool) -> void:
	if _is_paused == p:
		return
	_is_paused = p
	# The single pause authority: freezes player physics AND this clock (hence
	# the outbreak/timeline), since both are PAUSABLE nodes. Guard get_tree() so
	# this is safe to call before the node is in the scene tree.
	var tree := get_tree()
	if tree != null:
		tree.paused = p
	paused_changed.emit(p)


func toggle_paused() -> void:
	set_paused(not _is_paused)


func is_paused() -> bool:
	return _is_paused


# ------------------------------------------------------------------ time
func _process(delta: float) -> void:
	if not configured:
		return
	var real_seconds_per_hour := REAL_SECONDS_PER_DAY / HOURS_PER_DAY
	var d_hours := (delta * time_scale) / real_seconds_per_hour
	_advance(d_hours)


func _advance(d_hours: float) -> void:
	hour += d_hours
	_elapsed_ingame_hours += d_hours
	while hour >= HOURS_PER_DAY:
		hour -= HOURS_PER_DAY
		game_day += 1
	# Map elapsed in-game time onto the sim's tick axis. One in-game day spans
	# 1/_dt_days ticks. When we cross into new ticks, drive the AUTHORITATIVE
	# world forward by exactly that many ticks and read the outbreak back.
	if _time_clock_active():
		_pending_game_s += d_hours * 3600.0
		_since_send += d_hours * 3600.0 / (24.0 * 3600.0 / REAL_SECONDS_PER_DAY) / max(time_scale, 0.0001)
		if _since_send >= SEND_INTERVAL:
			flush_time()
		ticked.emit(game_day, hour, outbreak_belief())
		return
	var ticks_per_hour := (1.0 / _dt_days) / HOURS_PER_DAY
	var target := int(floor(_elapsed_ingame_hours * ticks_per_hour))
	if target > sim_tick:
		_advance_world(target - sim_tick)
		sim_tick = target
	ticked.emit(game_day, hour, outbreak_belief())


func _time_clock_active() -> bool:
	return use_time_clock and _bridge != null and _bridge.is_connected_to_sim() \
		and bool(_bridge.get("mobility_enabled"))


func flush_time() -> void:
	## Send the accumulated game seconds as one ADVANCE_TIME (movement block
	## back); on a tick crossing also refresh the full authoritative snapshot.
	_since_send = 0.0
	if _pending_game_s <= 0.0 or not _time_clock_active():
		return
	var sent := _pending_game_s
	_pending_game_s = 0.0
	var reply: Dictionary = _bridge.advance_time(sent, "mobility")
	if reply.get("ok", false) != true:
		return
	var t := int(reply.get("tick", sim_tick))
	if t != sim_tick or _last_snapshot_tick < 0:
		sim_tick = t
		_last_snapshot_tick = t
		var snap: Dictionary = _bridge.snapshot()
		if snap.get("ok", false) == true:
			_outbreak = _bridge._mean_belief_from(snap)
			_bridge.advanced.emit(t, _outbreak, snap)
	if reply.has("mobility") and reply["mobility"] != null:
		mobility_updated.emit(reply["mobility"], sent)


func _advance_world(delta_ticks: int) -> void:
	## Ask the live World to advance by delta_ticks and refresh the authoritative
	## outbreak. No live bridge -> the outbreak simply holds (no baked substitute).
	if delta_ticks <= 0:
		return
	if _bridge == null or not _bridge.is_connected_to_sim():
		return
	var reply: Dictionary = _bridge.advance(delta_ticks, true)
	if reply.get("ok", false) == true:
		# SimBridge computes the authoritative mean belief and exposes it via the
		# `advanced` signal; read it straight from the world snapshot here.
		_outbreak = _bridge._mean_belief_from(reply)


func outbreak_belief() -> float:
	## Authoritative outbreak intensity (mean zone belief, [0,1]) from the live
	## World. Held between tick crossings; never derived from a baked timeline.
	return _outbreak


func is_daytime() -> bool:
	return hour >= 6.0 and hour < 19.0


func time_string() -> String:
	var h := int(floor(hour))
	var m := int((hour - h) * 60.0)
	return "Day %d  %02d:%02d" % [game_day, h, m]

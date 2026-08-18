extends Node

## The one authoritative gameplay clock + outbreak-progression + pause authority,
## registered as the autoload singleton "GameClock". Everything time-driven reads
## from here so the citizen, the HUD, the day/night lighting and the outbreak all
## describe the same reality.
##
## Time model (mirrors asphodel/gametime.py): a full 24h in-game day defaults to
## one real hour (Project-Zomboid pacing). The player's hour advances in real
## time; each in-game moment maps onto a tick of the bundle's baked belief
## timeline, so standing still visibly advances the outbreak.
##
## Pause authority: pause() sets get_tree().paused. This node and the player are
## PAUSABLE, so both this clock (hence the outbreak) and the player's physics
## freeze together; the pause UI runs in a WHEN_PAUSED layer so it still responds.

signal ticked(game_day: int, hour: float, outbreak: float)
signal paused_changed(is_paused: bool)

const REAL_SECONDS_PER_DAY := 3600.0
const HOURS_PER_DAY := 24.0

var configured: bool = false
var game_day: int = 1
var hour: float = 8.0                      # in-game hour [0, 24)
var sim_tick: int = 0                      # index into the belief timeline
var _dt_days: float = 0.25
var _n_ticks: int = 0
var _timeline: Array = []                  # per-tick rows of per-zone belief
var _rows: int = 0
var _elapsed_ingame_hours: float = 0.0     # since spawn, for tick mapping
var _is_paused: bool = false


func _ready() -> void:
	# PAUSABLE: when the tree is paused this clock stops advancing, so the
	# outbreak stops with it. (The pause UI uses a WHEN_PAUSED layer instead.)
	process_mode = Node.PROCESS_MODE_PAUSABLE


func configure(meta: Dictionary, timeline: Dictionary, start_hour: float) -> void:
	## Wire the clock to a loaded bundle + the selected citizen's spawn hour.
	_dt_days = float(meta.get("dt", 0.25))
	_n_ticks = int(meta.get("n_ticks", 0))
	_timeline = timeline.get("data", []) as Array
	var shape: Array = timeline.get("shape", [0, 0])
	_rows = int(shape[0]) if shape.size() > 0 else _timeline.size()
	hour = clampf(start_hour, 0.0, 23.999)
	game_day = 1
	sim_tick = 0
	_elapsed_ingame_hours = 0.0
	_is_paused = false
	configured = true
	# Emit an initial state so listeners paint the correct starting time at once.
	ticked.emit(game_day, hour, outbreak_belief())


func reset() -> void:
	configured = false
	set_paused(false)


# ------------------------------------------------------------------ pause
func set_paused(p: bool) -> void:
	if _is_paused == p:
		return
	_is_paused = p
	# The single pause authority: freezes player physics AND this clock (hence
	# the outbreak/timeline), since both are PAUSABLE nodes.
	get_tree().paused = p
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
	var d_hours := delta / real_seconds_per_hour
	_advance(d_hours)


func _advance(d_hours: float) -> void:
	hour += d_hours
	_elapsed_ingame_hours += d_hours
	while hour >= HOURS_PER_DAY:
		hour -= HOURS_PER_DAY
		game_day += 1
	# Map elapsed in-game time onto the sim's tick axis. One in-game day spans
	# 1/_dt_days ticks; clamp to the baked timeline length.
	var ticks_per_hour := (1.0 / _dt_days) / HOURS_PER_DAY
	var t := int(floor(_elapsed_ingame_hours * ticks_per_hour))
	if _rows > 0:
		t = clampi(t, 0, _rows - 1)
	sim_tick = t
	ticked.emit(game_day, hour, outbreak_belief())


func outbreak_belief() -> float:
	## Mean belief across zones at the current sim tick, in [0, 1]. This is the
	## outbreak's visible intensity; it advances as the clock runs (unless paused).
	if _timeline.is_empty() or sim_tick < 0 or sim_tick >= _timeline.size():
		return 0.0
	var row: Array = _timeline[sim_tick]
	if row.is_empty():
		return 0.0
	var s := 0.0
	for v in row:
		s += float(v)
	return clampf(s / row.size(), 0.0, 1.0)


func is_daytime() -> bool:
	return hour >= 6.0 and hour < 19.0


func time_string() -> String:
	var h := int(floor(hour))
	var m := int((hour - h) * 60.0)
	return "Day %d  %02d:%02d" % [game_day, h, m]

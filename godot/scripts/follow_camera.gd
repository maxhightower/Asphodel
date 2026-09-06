class_name FollowCamera
extends Node

## Follow-NPC camera helper (ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2, §25).
##
## PRESENTATION ONLY. This node changes NO authority: it does not move a citizen,
## does not send a bridge command, does not advance anything. It only remembers
## which citizen the observer chose to follow and exposes that id together with
## the citizen's latest authoritative ground position. The integrator reads
## `followed_id` and `target_xy` to move the real camera; nothing here does.
##
## Public API: follow(citizen_id), clear(), set_bridge(bridge), refresh().

var followed_id := -1
var target_xy := Vector2.ZERO
var has_target := false

var _bridge = null


func set_bridge(bridge) -> void:
	_bridge = bridge


func follow(citizen_id: int) -> void:
	followed_id = int(citizen_id)
	refresh()


func clear() -> void:
	followed_id = -1
	has_target = false
	target_xy = Vector2.ZERO


func is_following() -> bool:
	return followed_id >= 0


func refresh() -> void:
	## Recompute target_xy from the authority's most recent movement block. The
	## bridge already caches it (last_mobility); we only read it.
	has_target = false
	if followed_id < 0 or _bridge == null or not ("last_mobility" in _bridge):
		return
	var block = _bridge.last_mobility
	if not (block is Dictionary):
		return
	for row in block.get("citizens", []):
		if not (row is Dictionary):
			continue
		if int(row.get("citizen_id", -1)) == followed_id:
			target_xy = Vector2(float(row.get("x", 0.0)), float(row.get("y", 0.0)))
			has_target = true
			return

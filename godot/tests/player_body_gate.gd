extends Node

## PlayerBodyGate — the embodied player has a VISIBLE character model (ISO body).
##
## The isometric player used to be an invisible collision capsule. It now carries
## a CitizenAvatar body, built from the SAME humanoid system as the crowd, so the
## person you embody is shaded and animated identically to everyone else. This
## gate proves the presentation-only wiring without needing the authority:
##   * appearance is a deterministic pure function of the citizen's NAME,
##   * the gait mapping (idle / walk / run) is correct at the speed thresholds,
##   * set_body actually attaches a CitizenAvatar carrying a built mesh.
##
##   godot --headless --path godot res://tests/PlayerBodyGate.tscn

const World = preload("res://scripts/isometric_world.gd")

var _fail := 0


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  %s" % label)
	else:
		_fail += 1
		push_error("FAIL: %s" % label)
		print("  FAIL: %s" % label)


func _ready() -> void:
	print("== PlayerBodyGate ==")
	_test_appearance_from_name()
	_test_gait_thresholds()
	_test_body_attaches()
	print("== PlayerBodyGate done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


func _test_appearance_from_name() -> void:
	# Deterministic: the same name always yields the same look.
	var a1 := World.player_appearance({"name": "Diego Rivera"})
	var a2 := World.player_appearance({"name": "Diego Rivera"})
	_check(a1 == a2, "appearance is deterministic for a given name")
	_check(a1.has("body") and a1.has("skin") and a1.has("top"),
		"appearance carries the humanoid fields")
	# Different people generally look different (these two differ in at least one axis).
	var b := World.player_appearance({"name": "Ada Lovelace"})
	_check(a1 != b, "different names produce different appearances")
	# No name => the stable anonymous fallback (seed 0), never a crash.
	var empty := World.player_appearance({})
	_check(empty == CitizenVisualIdentity.appearance_from_seed(0),
		"missing name falls back to the anonymous seed-0 look")


func _test_gait_thresholds() -> void:
	var walk := 4.5
	var sprint := 9.0
	_check(IsometricPlayer.gait_for_speed(0.0, walk, sprint) == 0.0,
		"standing still => idle gait (0.0)")
	_check(IsometricPlayer.gait_for_speed(0.05, walk, sprint) == 0.0,
		"a sliver of drift still reads as idle")
	_check(IsometricPlayer.gait_for_speed(walk, walk, sprint) == 0.5,
		"walking speed => walk gait (0.5)")
	_check(IsometricPlayer.gait_for_speed(sprint, walk, sprint) == 1.0,
		"sprint speed => run gait (1.0)")


func _test_body_attaches() -> void:
	var player := IsometricPlayer.new()
	add_child(player)
	var appearance := World.player_appearance({"name": "Diego Rivera"})
	var material := CitizenVisualIdentity.build_material()
	var avatar := CitizenAvatar.new()
	avatar.configure(-1, appearance, material, 0.0, CitizenMeshes.LOD_NEAR)
	player.set_body(avatar)

	_check(player.body == avatar, "player.body references the attached avatar")
	_check(avatar.get_parent() == player, "avatar is parented to the player body")
	_check(avatar.visible, "avatar is visible")
	# The avatar drives a MultiMeshInstance3D whose mesh must be built.
	var mmi := avatar.get_child(0) as MultiMeshInstance3D
	_check(mmi != null and mmi.multimesh != null and mmi.multimesh.mesh != null,
		"the attached body carries a built humanoid mesh")

	# Setting the body a second time replaces the first (no orphan bodies).
	var avatar2 := CitizenAvatar.new()
	avatar2.configure(-1, appearance, material, 0.0, CitizenMeshes.LOD_NEAR)
	player.set_body(avatar2)
	_check(player.body == avatar2, "set_body replaces the previous body")
	_check(not is_instance_valid(avatar) or avatar.get_parent() != player,
		"the previous body is detached")

	player.queue_free()

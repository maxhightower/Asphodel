extends Node
func _ready() -> void:
	for p in ["res://scripts/dialogue_panel.gd", "res://scripts/isometric_world.gd",
			"res://tests/dialogue_gate.gd", "res://tests/dialogue_shot.gd"]:
		print("load ", p, " -> ", load(p) != null)
	get_tree().quit(0)

extends Control

## Main menu: title + Start Game / Settings / Exit Game. Built in code so the
## .tscn stays a trivial Control root (robust without opening the editor).

func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.07, 0.09, 0.13)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(bg)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vb := VBoxContainer.new()
	vb.alignment = BoxContainer.ALIGNMENT_CENTER
	vb.add_theme_constant_override("separation", 16)
	center.add_child(vb)

	var title := Label.new()
	title.text = "ASPHODEL"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 64)
	vb.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "belief-cascade outbreak simulator"
	subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	subtitle.add_theme_font_size_override("font_size", 18)
	subtitle.modulate = Color(0.7, 0.75, 0.8)
	vb.add_child(subtitle)

	var gap := Control.new()
	gap.custom_minimum_size = Vector2(0, 28)
	vb.add_child(gap)

	vb.add_child(_make_button("Start Game", _on_start))
	vb.add_child(_make_button("Settings", _on_settings))
	vb.add_child(_make_button("Exit Game", _on_exit))


func _make_button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(280, 48)
	b.add_theme_font_size_override("font_size", 24)
	b.pressed.connect(handler)
	return b


func _on_start() -> void:
	get_tree().change_scene_to_file("res://CitySelect.tscn")


func _on_settings() -> void:
	get_tree().change_scene_to_file("res://Settings.tscn")


func _on_exit() -> void:
	get_tree().quit()

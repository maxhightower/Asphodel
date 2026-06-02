extends Control

## Minimal settings: a live Fullscreen toggle and a Master-volume slider (wired
## to the audio bus, harmless with no audio yet). Applied immediately; not yet
## persisted to disk. Back returns to the main menu.

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
	vb.add_theme_constant_override("separation", 16)
	center.add_child(vb)

	var title := Label.new()
	title.text = "Settings"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 40)
	vb.add_child(title)

	vb.add_child(_fullscreen_row())
	vb.add_child(_volume_row())

	var gap := Control.new()
	gap.custom_minimum_size = Vector2(0, 20)
	vb.add_child(gap)

	var back := Button.new()
	back.text = "Back"
	back.custom_minimum_size = Vector2(300, 48)
	back.add_theme_font_size_override("font_size", 22)
	back.pressed.connect(_on_back)
	vb.add_child(back)


func _row_label(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.custom_minimum_size = Vector2(170, 0)
	l.add_theme_font_size_override("font_size", 20)
	return l


func _fullscreen_row() -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	row.add_child(_row_label("Fullscreen"))
	var toggle := CheckButton.new()
	toggle.button_pressed = (
		DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_FULLSCREEN
	)
	toggle.toggled.connect(_on_fullscreen_toggled)
	row.add_child(toggle)
	return row


func _volume_row() -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	row.add_child(_row_label("Master Volume"))
	var slider := HSlider.new()
	slider.custom_minimum_size = Vector2(240, 0)
	slider.min_value = 0.0
	slider.max_value = 1.0
	slider.step = 0.01
	var bus := AudioServer.get_bus_index("Master")
	slider.value = db_to_linear(AudioServer.get_bus_volume_db(bus))
	slider.value_changed.connect(_on_volume_changed)
	row.add_child(slider)
	return row


func _on_fullscreen_toggled(on: bool) -> void:
	DisplayServer.window_set_mode(
		DisplayServer.WINDOW_MODE_FULLSCREEN if on else DisplayServer.WINDOW_MODE_WINDOWED
	)


func _on_volume_changed(value: float) -> void:
	var bus := AudioServer.get_bus_index("Master")
	AudioServer.set_bus_volume_db(bus, linear_to_db(maxf(value, 0.0001)))


func _on_back() -> void:
	get_tree().change_scene_to_file("res://MainMenu.tscn")

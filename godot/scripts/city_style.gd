class_name CityStyle
extends RefCounted

## Deterministic per-city visual palette. The city name picked in the menu
## hashes to one of a few regional looks, so Houston, Austin, San Antonio and
## Madisonville each render with their own ground, sky, asphalt and building
## colors — and the same city always looks the same.

var grass: Color
var asphalt: Color
var asphalt_minor: Color
var marking: Color
var sidewalk: Color
var sky_top: Color
var sky_horizon: Color
var sun_color: Color
var sun_energy: float
var roof_colors: Array[Color]
var interior_floor: Color
var interior_wall: Color
var _wall_palettes: Dictionary   # kind -> Array[Color]
var _rng_seed: int


static func for_city(city_name: String) -> CityStyle:
	var s := CityStyle.new()
	s._rng_seed = hash(city_name)
	var themes := [s._theme_gulf, s._theme_hill, s._theme_plains, s._theme_coastal]
	themes[absi(s._rng_seed) % themes.size()].call()
	return s


func _theme_gulf() -> void:
	grass = Color(0.30, 0.38, 0.24)
	asphalt = Color(0.16, 0.165, 0.18)
	asphalt_minor = Color(0.22, 0.22, 0.23)
	marking = Color(0.85, 0.8, 0.55)
	sidewalk = Color(0.55, 0.53, 0.50)
	sky_top = Color(0.30, 0.48, 0.75)
	sky_horizon = Color(0.78, 0.82, 0.86)
	sun_color = Color(1.0, 0.95, 0.85)
	sun_energy = 1.3
	roof_colors = [Color(0.35, 0.30, 0.28), Color(0.30, 0.30, 0.32), Color(0.42, 0.35, 0.3)]
	interior_floor = Color(0.52, 0.42, 0.32)
	interior_wall = Color(0.82, 0.79, 0.72)
	_wall_palettes = {
		"house": [Color(0.78, 0.72, 0.62), Color(0.72, 0.6, 0.52), Color(0.62, 0.66, 0.68), Color(0.75, 0.75, 0.7)],
		"apartments": [Color(0.6, 0.5, 0.42), Color(0.55, 0.55, 0.58)],
		"shop": [Color(0.7, 0.62, 0.55), Color(0.62, 0.58, 0.62), Color(0.66, 0.5, 0.42)],
		"commercial": [Color(0.58, 0.6, 0.64), Color(0.5, 0.52, 0.56)],
		"office": [Color(0.45, 0.52, 0.6), Color(0.5, 0.55, 0.6)],
		"industrial": [Color(0.55, 0.53, 0.5), Color(0.48, 0.45, 0.44)],
		"generic": [Color(0.66, 0.62, 0.58), Color(0.6, 0.58, 0.55)],
	}


func _theme_hill() -> void:
	grass = Color(0.34, 0.40, 0.22)
	asphalt = Color(0.17, 0.17, 0.18)
	asphalt_minor = Color(0.24, 0.23, 0.22)
	marking = Color(0.88, 0.85, 0.7)
	sidewalk = Color(0.6, 0.57, 0.52)
	sky_top = Color(0.25, 0.45, 0.8)
	sky_horizon = Color(0.85, 0.85, 0.8)
	sun_color = Color(1.0, 0.97, 0.9)
	sun_energy = 1.4
	roof_colors = [Color(0.5, 0.32, 0.25), Color(0.35, 0.33, 0.3), Color(0.3, 0.35, 0.4)]
	interior_floor = Color(0.55, 0.45, 0.33)
	interior_wall = Color(0.85, 0.82, 0.76)
	_wall_palettes = {
		"house": [Color(0.85, 0.8, 0.7), Color(0.8, 0.68, 0.55), Color(0.7, 0.72, 0.66)],
		"apartments": [Color(0.66, 0.55, 0.45), Color(0.6, 0.6, 0.62)],
		"shop": [Color(0.75, 0.65, 0.5), Color(0.68, 0.6, 0.65)],
		"commercial": [Color(0.6, 0.62, 0.66), Color(0.55, 0.56, 0.6)],
		"office": [Color(0.5, 0.58, 0.66), Color(0.55, 0.6, 0.62)],
		"industrial": [Color(0.58, 0.55, 0.52), Color(0.5, 0.48, 0.46)],
		"generic": [Color(0.72, 0.68, 0.6), Color(0.65, 0.62, 0.58)],
	}


func _theme_plains() -> void:
	grass = Color(0.38, 0.4, 0.24)
	asphalt = Color(0.18, 0.18, 0.19)
	asphalt_minor = Color(0.25, 0.24, 0.23)
	marking = Color(0.9, 0.88, 0.75)
	sidewalk = Color(0.58, 0.56, 0.53)
	sky_top = Color(0.32, 0.5, 0.78)
	sky_horizon = Color(0.82, 0.84, 0.82)
	sun_color = Color(1.0, 0.96, 0.88)
	sun_energy = 1.35
	roof_colors = [Color(0.4, 0.33, 0.28), Color(0.33, 0.33, 0.35), Color(0.45, 0.4, 0.32)]
	interior_floor = Color(0.5, 0.4, 0.3)
	interior_wall = Color(0.8, 0.78, 0.72)
	_wall_palettes = {
		"house": [Color(0.8, 0.75, 0.66), Color(0.75, 0.63, 0.55), Color(0.68, 0.7, 0.66)],
		"apartments": [Color(0.62, 0.52, 0.44), Color(0.58, 0.58, 0.6)],
		"shop": [Color(0.72, 0.64, 0.55), Color(0.65, 0.6, 0.63)],
		"commercial": [Color(0.6, 0.61, 0.64), Color(0.52, 0.54, 0.57)],
		"office": [Color(0.47, 0.54, 0.62), Color(0.52, 0.57, 0.61)],
		"industrial": [Color(0.56, 0.54, 0.51), Color(0.49, 0.47, 0.45)],
		"generic": [Color(0.68, 0.64, 0.6), Color(0.62, 0.6, 0.57)],
	}


func _theme_coastal() -> void:
	grass = Color(0.28, 0.4, 0.28)
	asphalt = Color(0.15, 0.16, 0.18)
	asphalt_minor = Color(0.21, 0.22, 0.24)
	marking = Color(0.9, 0.9, 0.85)
	sidewalk = Color(0.6, 0.6, 0.58)
	sky_top = Color(0.28, 0.45, 0.72)
	sky_horizon = Color(0.8, 0.85, 0.88)
	sun_color = Color(0.98, 0.95, 0.9)
	sun_energy = 1.25
	roof_colors = [Color(0.32, 0.35, 0.4), Color(0.36, 0.3, 0.28), Color(0.4, 0.38, 0.34)]
	interior_floor = Color(0.48, 0.42, 0.34)
	interior_wall = Color(0.83, 0.82, 0.78)
	_wall_palettes = {
		"house": [Color(0.76, 0.78, 0.76), Color(0.7, 0.74, 0.78), Color(0.8, 0.74, 0.64)],
		"apartments": [Color(0.6, 0.62, 0.66), Color(0.56, 0.52, 0.48)],
		"shop": [Color(0.68, 0.66, 0.62), Color(0.6, 0.62, 0.68)],
		"commercial": [Color(0.56, 0.6, 0.65), Color(0.5, 0.53, 0.58)],
		"office": [Color(0.46, 0.53, 0.62), Color(0.5, 0.56, 0.62)],
		"industrial": [Color(0.54, 0.53, 0.52), Color(0.47, 0.46, 0.45)],
		"generic": [Color(0.66, 0.65, 0.62), Color(0.6, 0.6, 0.58)],
	}


## Deterministic wall color for one building: kind palette + per-building jitter.
func wall_color(kind: String, salt: int) -> Color:
	var pal: Array = _wall_palettes.get(_kind_family(kind), _wall_palettes["generic"])
	var h := absi(hash(str(_rng_seed, ":", salt)))
	var base: Color = pal[h % pal.size()]
	var jitter := float((h / 7) % 100) / 100.0 * 0.12 - 0.06
	return Color(clampf(base.r + jitter, 0.0, 1.0),
			clampf(base.g + jitter, 0.0, 1.0),
			clampf(base.b + jitter, 0.0, 1.0))


func roof_color(salt: int) -> Color:
	return roof_colors[absi(hash(str(_rng_seed, "roof", salt))) % roof_colors.size()]


static func _kind_family(kind: String) -> String:
	match kind:
		"house", "garage", "hotel":
			return "house"
		"apartments":
			return "apartments"
		"shop", "restaurant", "pharmacy":
			return "shop"
		"commercial":
			return "commercial"
		"office", "civic", "school", "hospital":
			return "office"
		"industrial":
			return "industrial"
		_:
			return "generic"

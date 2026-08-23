extends RefCounted
class_name ZoneMap

## Presentation-side spatial mapping: a Godot world position -> the authoritative
## simulation zone, using the SAME frame + nearest-centre rule as Python's
## `asphodel.bundle_population.zone_of_xy`. This is the one place Godot resolves
## geography; the player's position drives SET_FOCUS through it, so the promoted
## micro bubble follows the player and stays consistent with the city bundle.

var _ids: PackedInt32Array = PackedInt32Array()
var _cx: PackedFloat64Array = PackedFloat64Array()
var _cz: PackedFloat64Array = PackedFloat64Array()


func load_from_zones(zones: Array) -> void:
	## Build from a bundle's zones array (each has `id` and `center_xy`), ordered
	## by ascending id so nearest-centre ties break to the lowest id (as Python).
	var sorted := zones.duplicate()
	sorted.sort_custom(func(a, b): return int(a["id"]) < int(b["id"]))
	_ids = PackedInt32Array()
	_cx = PackedFloat64Array()
	_cz = PackedFloat64Array()
	for z in sorted:
		_ids.append(int(z["id"]))
		var c: Array = z["center_xy"]
		_cx.append(float(c[0]))
		_cz.append(float(c[1]))


func zone_count() -> int:
	return _ids.size()


func zone_of_xy(x: float, z: float) -> int:
	## Nearest zone centre (deterministic; ties -> lowest id). -1 if empty.
	var best := -1
	var best_d := INF
	for i in range(_ids.size()):
		var dx := _cx[i] - x
		var dz := _cz[i] - z
		var d := dx * dx + dz * dz
		if d < best_d:
			best_d = d
			best = _ids[i]
	return best

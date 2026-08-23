class_name BundleLoader
extends RefCounted

## Loads an Asphodel city bundle (the 4 JSON files produced by
## `python -m asphodel.osm_city`) from a res:// or user:// directory into a
## typed Dictionary: { "meta":Dictionary, "zones":Array, "roads":Dictionary,
## "timeline":Dictionary }. Returns an empty Dictionary and pushes a clear error
## if anything is missing or malformed.

const _PARTS := ["meta", "zones", "roads", "timeline"]


static func load_bundle(dir_path: String) -> Dictionary:
	var bundle := {}
	for part in _PARTS:
		var path := dir_path.path_join(part + ".json")
		if not FileAccess.file_exists(path):
			push_error("Bundle file missing: %s" % path)
			return {}
		var text := FileAccess.get_file_as_string(path)
		if text.is_empty():
			push_error("Bundle file empty or unreadable: %s" % path)
			return {}
		var parsed: Variant = JSON.parse_string(text)
		if parsed == null:
			push_error("Bundle file is not valid JSON: %s" % path)
			return {}
		bundle[part] = parsed

	var meta: Dictionary = bundle["meta"]
	if not meta.has("version"):
		push_error("Bundle meta.json missing 'version' — not an Asphodel bundle?")
		return {}
	return bundle


static func load_buildings(dir_path: String, zones: Array) -> Array:
	## Building footprints for the street world. Prefers buildings.json (real
	## OSM outlines, or the synth fallback baked next to them); for bundles
	## that predate it, converts the zones' abstract blocks into square
	## footprints so the world still renders.
	var path := dir_path.path_join("buildings.json")
	if FileAccess.file_exists(path):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
		if parsed is Array and not (parsed as Array).is_empty():
			return parsed
	push_warning("No buildings.json in %s — falling back to zone blocks." % dir_path)
	var out: Array = []
	for z in zones:
		for blk in (z.get("blocks", []) as Array):
			var xy: Array = blk["xy"]
			var half := float(blk.get("footprint", 8.0)) * 0.5
			var cx := float(xy[0])
			var cz := float(xy[1])
			out.append({
				"footprint": [
					[cx - half, cz - half], [cx + half, cz - half],
					[cx + half, cz + half], [cx - half, cz + half],
				],
				"center_xy": [cx, cz],
				"height": float(blk.get("height", 6.0)),
				"levels": 1,
				"kind": "generic",
				"area_m2": half * half * 4.0,
			})
	return out


static func load_citizens(dir_path: String) -> Array:
	## Returns the bundle's citizen list, or [] if absent/invalid.
	var path := dir_path.path_join("citizens.json")
	if not FileAccess.file_exists(path):
		push_warning("No citizens.json in %s" % dir_path)
		return []
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed if parsed is Array else []

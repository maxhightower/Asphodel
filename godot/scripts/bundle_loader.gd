class_name BundleLoader
extends RefCounted

## Loads an Asphodel city bundle (the 4 JSON files produced by
## `python -m asphodel.osm_city`) from a res:// or user:// directory into a
## typed Dictionary: { "meta":Dictionary, "zones":Array, "roads":Dictionary,
## "timeline":Dictionary }. Returns an empty Dictionary and pushes a clear error
## if anything is missing OR structurally malformed -- the playable code assumes
## deeper structure than "the file parsed", so it is validated up front rather
## than crashing a downstream script mid-scene.

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

	var err := validate(bundle)
	if err != "":
		push_error("Invalid bundle at %s: %s" % [dir_path, err])
		return {}
	return bundle


static func validate(bundle: Dictionary) -> String:
	## Returns "" if the bundle is structurally sound, else a readable reason.
	var meta = bundle.get("meta")
	if not (meta is Dictionary):
		return "meta.json is not an object"
	if not meta.has("version"):
		return "meta missing 'version' — not an Asphodel bundle?"
	if not (meta.get("grid") is Dictionary):
		return "meta.grid missing/!object"
	var grid: Dictionary = meta["grid"]
	for k in ["rows", "cols"]:
		if not (grid.get(k) is float or grid.get(k) is int):
			return "meta.grid.%s missing/!number" % k

	var zones = bundle.get("zones")
	if not (zones is Array) or (zones as Array).is_empty():
		return "zones.json is not a non-empty array"
	var z0 = zones[0]
	if not (z0 is Dictionary):
		return "zones[0] is not an object"
	for k in ["center_xy", "extent"]:
		var v = z0.get(k)
		if not (v is Array) or (v as Array).size() < 2:
			return "zones[0].%s missing/!(len>=2 array)" % k
	if not (z0.has("blocks") and z0["blocks"] is Array):
		return "zones[0].blocks missing/!array"

	var roads = bundle.get("roads")
	if not (roads is Dictionary):
		return "roads.json is not an object"
	if not (roads.get("polylines") is Array):
		return "roads.polylines missing/!array"

	var timeline = bundle.get("timeline")
	if not (timeline is Dictionary):
		return "timeline.json is not an object"
	if not (timeline.get("data") is Array):
		return "timeline.data missing/!array"
	var shape = timeline.get("shape")
	if not (shape is Array) or (shape as Array).size() < 2:
		return "timeline.shape missing/!(len 2 array)"
	return ""


static func load_mobility(dir_path: String) -> Dictionary:
	## The road-derived zone-mobility graph the Python sim used (optional; older
	## bundles omit it). Since M1 the live Python World owns simulation truth and
	## rides this graph itself; the renderer neither infers its own graph nor
	## replays the baked timeline for truth, so this is exposed for
	## tooling/inspection only. Returns {} if absent or malformed.
	var path := dir_path.path_join("mobility.json")
	if not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary) or not (parsed.get("edges") is Array):
		push_error("mobility.json malformed: %s" % path)
		return {}
	return parsed


static func load_citizens(dir_path: String) -> Array:
	## Returns the bundle's citizen list, or [] if absent/invalid. Each entry is
	## validated to carry the fields the character screen + spawn depend on.
	var path := dir_path.path_join("citizens.json")
	if not FileAccess.file_exists(path):
		push_warning("No citizens.json in %s" % dir_path)
		return []
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Array):
		push_error("citizens.json is not an array: %s" % path)
		return []
	var out: Array = []
	for c in parsed:
		if c is Dictionary and c.has("name") and c.has("occupation") \
				and c.has("spawn_hour"):
			out.append(c)
	if out.is_empty():
		push_error("citizens.json has no valid citizen records: %s" % path)
	return out

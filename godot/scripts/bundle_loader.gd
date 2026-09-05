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

# Schema contract at the Godot boundary (Gate I). The Python compiler stamps
# these versions; anything else is a skew we refuse rather than misread.
const BUILDINGS_VERSION := 1
const STREETMAP_VERSIONS := [1, 2]


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


static func load_buildings(dir_path: String) -> Array:
	## Real (or procedural) building footprints to extrude. buildings.json MUST be
	## the versioned object form {"version": 1, "buildings": [{"poly": [[x,z],...],
	## "height": float}, ...]}; a bare JSON array (the pre-v1 synth.py output) is
	## REJECTED rather than silently half-read, because a renderer that misreads
	## footprints draws a plausible city that does not match Python's world.
	## Returns [] (absent bundle, or contract violation + push_error).
	var path := dir_path.path_join("buildings.json")
	if not FileAccess.file_exists(path):
		return []
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	var err := check_buildings(parsed)
	if err != "":
		push_error("buildings.json rejected (%s): %s" % [path, err])
		return []
	return (parsed as Dictionary)["buildings"]


static func check_buildings(parsed: Variant) -> String:
	## "" if `parsed` satisfies the buildings.json v1 contract, else the reason.
	if not (parsed is Dictionary):
		return "not a JSON object (a bare array is the obsolete pre-v1 form)"
	var doc: Dictionary = parsed
	if int(doc.get("version", -1)) != BUILDINGS_VERSION:
		return "version is %s, expected %d" % [str(doc.get("version")), BUILDINGS_VERSION]
	if not (doc.get("buildings") is Array):
		return "'buildings' missing/!array"
	var records: Array = doc["buildings"]
	if records.is_empty():
		return ""            # a legitimately empty city is not a schema violation
	var b0 = records[0]
	if not (b0 is Dictionary):
		return "buildings[0] is not an object"
	if not (b0.get("poly") is Array):
		return "buildings[0].poly missing/!array"
	var h = b0.get("height")
	if not (h is float or h is int):
		return "buildings[0].height missing/!number"
	return ""


static func load_streetmap(dir_path: String) -> Dictionary:
	## The compiled street graph: {"version": 1|2, "nodes": {id: [x, z]},
	## "segments": [...]}. Returns {} (+ push_error) on any contract violation --
	## a half-read graph would route citizens down streets that do not exist.
	var path := dir_path.path_join("streetmap.json")
	if not FileAccess.file_exists(path):
		push_error("streetmap.json missing: %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	var err := check_streetmap(parsed)
	if err != "":
		push_error("streetmap.json rejected (%s): %s" % [path, err])
		return {}
	return parsed


static func check_streetmap(parsed: Variant) -> String:
	## "" if `parsed` satisfies the streetmap contract, else the reason.
	if not (parsed is Dictionary):
		return "not a JSON object"
	var doc: Dictionary = parsed
	var version := int(doc.get("version", -1))
	if not (version in STREETMAP_VERSIONS):
		return "version is %s, expected one of %s" % [str(doc.get("version")), str(STREETMAP_VERSIONS)]
	if not (doc.get("nodes") is Dictionary):
		return "'nodes' missing/!object"
	if not (doc.get("segments") is Array):
		return "'segments' missing/!array"
	return ""


static func load_region(dir_path: String) -> Dictionary:
	## The baked regional terrain descriptor. Requires a version and a heightmap
	## carrying the sampling frame RegionLoader bilinearly interpolates against.
	## Returns {} (+ push_error) on any contract violation.
	var path := dir_path.path_join("region.json")
	if not FileAccess.file_exists(path):
		push_error("region.json missing: %s" % path)
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	var err := check_region(parsed)
	if err != "":
		push_error("region.json rejected (%s): %s" % [path, err])
		return {}
	return parsed


static func check_region(parsed: Variant) -> String:
	## "" if `parsed` satisfies the region contract, else the reason.
	if not (parsed is Dictionary):
		return "not a JSON object"
	var doc: Dictionary = parsed
	if not doc.has("version"):
		return "'version' missing -- not an Asphodel region?"
	if not (doc.get("heightmap") is Dictionary):
		return "'heightmap' missing/!object"
	var hm: Dictionary = doc["heightmap"]
	for k in ["x0", "z0", "step_m"]:
		var v = hm.get(k)
		if not (v is float or v is int):
			return "heightmap.%s missing/!number" % k
	if not (hm.get("heights") is Array) or (hm["heights"] as Array).is_empty():
		return "heightmap.heights missing/!(non-empty array)"
	return ""


static func validate_bundle_schema(dir_path: String) -> String:
	## One boundary check for every schema-bearing file the bundle actually ships.
	## Returns "" when the bundle is safe to render, else a readable reason. The
	## world scenes call this straight after load_bundle and REFUSE to render on a
	## non-empty result: a misread bundle is worse than a black screen, because it
	## renders a world Python does not believe in.
	var names := ["buildings.json", "streetmap.json", "region.json"]
	for name in names:
		var path := dir_path.path_join(name)
		if not FileAccess.file_exists(path):
			continue          # optional per bundle; only what ships is contracted
		var text := FileAccess.get_file_as_string(path)
		if text.is_empty():
			return "%s is empty or unreadable" % name
		var parsed: Variant = JSON.parse_string(text)
		if parsed == null:
			return "%s is not valid JSON" % name
		var err := ""
		match name:
			"buildings.json":
				err = check_buildings(parsed)
			"streetmap.json":
				err = check_streetmap(parsed)
			"region.json":
				err = check_region(parsed)
		if err != "":
			return "%s: %s" % [name, err]
	return ""


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

class_name MobilityLoader
extends RefCounted

## Mobility graph realization seam (AS-NAV-0, §5).
##
## Loads streetmap.json (baked by asphodel.mobility.bake) into a routable directed
## graph and routes with Dijkstra over current dynamic costs, honouring per-mode
## access and runtime obstructions/closures — the same authority the Python
## MobilityGraph implements. The engine uses this for vehicle/pedestrian routing
## and for reacting to wrecks (a MobilityObstruction closes a segment, routes
## reroute, clearing it restores them).
##
## Two schema versions load, and only two — anything else is a hard error rather
## than a graph whose geometry means something other than what this reads:
##   1  legacy: no per-segment geometry; a segment is the straight u->v line.
##   2  canonical: "pts" carries the segment's own polyline, oriented u->v, so
##      the client drives the same street the Python sim measured.
##
## NOTE: authored seam — mirrors asphodel/mobility/graph.py; not run in-editor here.

const SUPPORTED_VERSIONS := [1, 2]

var version := 0
var source := ""
var nodes := {}          # id -> Vector2 (x, z)
var segments := {}       # id -> Dictionary(u, v, class, length, modes, directionality)
var points := {}         # id -> PackedVector2Array (v2 only; empty for v1)
var _adj := {}           # node -> Array of [to_node, seg_id]
var _closed := {}        # seg_id -> Array of closed mode strings
var _congestion := {}    # seg_id -> float


func load_mobility(dir_path: String) -> bool:
	var path := dir_path.path_join("streetmap.json")
	if not FileAccess.file_exists(path):
		push_error("streetmap.json missing: %s" % path)
		return false
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (parsed is Dictionary):
		push_error("streetmap.json is not a JSON object: %s" % path)
		return false
	var m: Dictionary = parsed
	if not m.has("version"):
		push_error("streetmap.json has no 'version' field: %s" % path)
		return false
	# The bake has written version as both a string ("1") and a number (2).
	var v := int(str(m["version"]))
	if not (v in SUPPORTED_VERSIONS):
		push_error("unsupported streetmap version %s in %s (expected 1 or 2)"
			% [str(m["version"]), path])
		return false
	version = v
	source = str(m.get("source", ""))

	nodes.clear(); segments.clear(); points.clear()
	_adj.clear(); _closed.clear(); _congestion.clear()
	for nid in m["nodes"]:
		var p: Array = m["nodes"][nid]
		nodes[nid] = Vector2(p[0], p[1])
		_adj[nid] = []
	for seg in m["segments"]:
		var sid: String = seg["id"]
		segments[sid] = seg
		_congestion[sid] = 1.0
		if seg.has("pts"):
			var pv := PackedVector2Array()
			for q in seg["pts"]:
				pv.append(Vector2(q[0], q[1]))
			points[sid] = pv
		var u: String = seg["u"]; var v_id: String = seg["v"]
		var dir := str(seg["directionality"])
		if dir != "backward":
			_adj[u].append([v_id, sid])
		if dir != "forward":
			_adj[v_id].append([u, sid])
	return true


## The segment's polyline in bundle metres, oriented u->v. Version-1 artifacts
## carry no geometry, so this synthesizes the straight u->v line instead.
func segment_points(seg_id: String) -> PackedVector2Array:
	if points.has(seg_id):
		return points[seg_id]
	var pv := PackedVector2Array()
	if not segments.has(seg_id):
		return pv
	var seg: Dictionary = segments[seg_id]
	if nodes.has(seg["u"]) and nodes.has(seg["v"]):
		pv.append(nodes[seg["u"]])
		pv.append(nodes[seg["v"]])
	return pv


func close_segment(seg_id: String, modes: Array) -> void:
	_closed[seg_id] = modes            # a MobilityObstruction closing the segment

func open_segment(seg_id: String) -> void:
	_closed.erase(seg_id)

func set_congestion(seg_id: String, factor: float) -> void:
	_congestion[seg_id] = max(1.0, factor)


func _cost(seg_id: String, mode: String) -> float:
	var seg: Dictionary = segments[seg_id]
	if not (mode in seg["modes"]):
		return INF
	if _closed.has(seg_id) and (mode in _closed[seg_id]):
		return INF
	return float(seg["length"]) * _congestion.get(seg_id, 1.0)


# -- binary min-heap over [cost, node] pairs (a city graph is ~10^4 nodes; a
# re-sorted array frontier is quadratic there and stalls the frame).
func _heap_push(heap: Array, item: Array) -> void:
	heap.append(item)
	var i := heap.size() - 1
	while i > 0:
		var parent := (i - 1) >> 1
		if heap[parent][0] <= heap[i][0]:
			break
		var tmp: Array = heap[parent]; heap[parent] = heap[i]; heap[i] = tmp
		i = parent


func _heap_pop(heap: Array) -> Array:
	var top: Array = heap[0]
	var last: Array = heap.pop_back()
	if heap.size() > 0:
		heap[0] = last
		var i := 0
		while true:
			var l := 2 * i + 1
			var r := l + 1
			var small := i
			if l < heap.size() and heap[l][0] < heap[small][0]:
				small = l
			if r < heap.size() and heap[r][0] < heap[small][0]:
				small = r
			if small == i:
				break
			var tmp: Array = heap[small]; heap[small] = heap[i]; heap[i] = tmp
			i = small
	return top


func route(origin: String, dest: String, mode: String) -> Array:
	# Returns an Array of node ids (empty if unreachable). Dijkstra.
	if origin == dest:
		return [origin]
	if not _adj.has(origin) or not _adj.has(dest):
		return []
	var dist := {origin: 0.0}
	var prev := {}
	var visited := {}
	var frontier: Array = []
	_heap_push(frontier, [0.0, origin])
	while frontier.size() > 0:
		var top: Array = _heap_pop(frontier)
		var u: String = top[1]
		if visited.has(u):
			continue
		visited[u] = true
		if u == dest:
			break
		for edge in _adj.get(u, []):
			var w: String = edge[0]
			var c := _cost(edge[1], mode)
			if c == INF:
				continue
			var nd: float = float(dist[u]) + c
			if nd < float(dist.get(w, INF)):
				dist[w] = nd
				prev[w] = u
				_heap_push(frontier, [nd, w])
	if not dist.has(dest) or not prev.has(dest):
		return []
	var path := [dest]
	var cur := dest
	while cur != origin:
		cur = prev[cur]
		path.push_front(cur)
	return path

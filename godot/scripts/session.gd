extends Node

## Cross-scene state, registered as the autoload singleton "Session".
## CitySelect writes the chosen city's bundle directory here; the world scene
## (IsometricWorld / StreetScene) reads it so it knows which city to render.
## Empty means "fall back to the scene's own default" (the sample bundle).

var bundle_dir: String = ""
var citizen: Dictionary = {}   # the citizen the player was spawned as
# Optional in-game start hour for the one START_WORLD the world scene issues.
# < 0 means "let the authority use its own default" (hour 0). Certification
# harnesses set it so the day they measure begins where the Python-side run
# that certified it began (e.g. 5.0 for a working day).
var start_hour: float = -1.0

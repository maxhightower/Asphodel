extends Node

## Cross-scene state, registered as the autoload singleton "Session".
## CitySelect writes the chosen city's bundle directory here; CityScene reads it
## so it knows which city to render. Empty means "fall back to the scene's own
## default" (the checked-in sample bundle).

var bundle_dir: String = ""

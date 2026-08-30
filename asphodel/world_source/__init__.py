"""Public-data acquisition layer for Asphodel city bundles.

This package is the *only* place in the repo that is allowed to reach out to
the public internet for city geometry (buildings, roads, land use, places).
Everything downstream (bundle generation, the Godot frontend, simulation
code) consumes the parquet files this package writes under
``data/raw/overture/<release>/<city>/`` plus the machine-readable manifest at
``geo/provenance/data_sources.json`` -- it never talks to a remote host
itself.

Network reality (verified, do not re-litigate -- see AGENT notes in
``overture.py``): the only host reachable from this environment is Overture
Maps' public S3 bucket over plain HTTPS/REST. Government/city GIS portals
(USGS 3DEP, NLCD, Houston COHGIS/ArcGIS) are blocked by egress policy; those
gaps are recorded as FAILED entries in the provenance manifest with a
documented fallback, not silently skipped.
"""
from __future__ import annotations

# Native Windows release acceptance

Run the `Release certification` workflow on the candidate PR. It builds the
Python authority on Windows, imports/exports Godot 4.4, executes W48–W51
sequentially, then launches the exported client from a clean path with spaces
and without Python on PATH. The packaged test compares complete authoritative
snapshots after SAVE → process exit → relaunch → LOAD → identical advancement.
It also checks all four cities and rejects missing or wrong-build authorities.

Automated Windows success is not manual desktop acceptance. Keep the overall
release PARTIAL until a tester records the following against the exact ZIP
checksum, Windows version, and candidate SHA:

- Extract to a new directory with spaces and double-click Asphodel.exe.
- No terminal, Python installation, or manually started server is required.
- Menu → city → character → IsometricWorld works in each bundled city.
- Citizens, vehicles, inventory, dialogue, and the read-only inspector are usable.
- Save, quit, relaunch, and load; check visible continuity.
- Confirm the owned authority exits after game shutdown in Task Manager.
- Repeat launch with port 8765 occupied by an unrelated local application;
  that application must remain untouched.
- Missing authority and wrong SIM_SHA produce readable errors, not silent fallback.
- Record Defender/SmartScreen behavior honestly; unsigned builds may warn.
- Capture ordinary gameplay and failure screens, with captions and artifact identity.

Do not change W52 to PASS based on export success, Linux execution, Wine, or
historical traces. Archive the native workflow result and desktop acceptance
record alongside the release. Do not merge the integrated candidate while its
required gates are red or unverified.

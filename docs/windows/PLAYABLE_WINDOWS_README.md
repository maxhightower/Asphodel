# Asphodel — Windows Playable (Convergence V2)

A self-contained Windows build of Asphodel: the **Godot client** you launch plus
the bundled **Python simulation authority** it starts for you. No terminal, no
system Python, no manual server step.

> **Build-host honesty.** This README ships with the pipeline that *produces* the
> Windows build. The build/certification host used for this milestone is
> **Linux, headless, with no Wine**, so the Windows `.exe` here was *cross-
> exported* but could **not be launched or certified playable** on that host.
> The runnable evidence produced there is the **Linux proxy build** and the
> **Linux frozen authority** (which was launched and served the bridge
> handshake). Produce and smoke-test the real Windows build on a Windows host.

---

## 1. What's in the shipped folder

```
Asphodel-Windows-V2/            (unzipped from Asphodel-Windows-V2.zip)
├─ Asphodel.exe                 the game client (double-click this)
├─ Asphodel.pck                 all game data + every city bundle, packed
└─ authority/                   the frozen Python simulation authority
   └─ authority.exe             started automatically by the client
```

The city data (Houston, Madisonville TX, Austin, San Antonio) is packed **inside
`Asphodel.pck`** — there are no loose data files to manage.

---

## 2. Build it (one command)

From the repository root on a **Windows** host with Python 3.11+, Godot 4.4, and
`pip install pyinstaller` done:

```powershell
.\tools\build_windows_playable.ps1 -Target windows -Zip
```

That wrapper just calls the one canonical entry point (works identically on any
OS):

```bash
python tools/build_windows_playable.py --target windows --zip
```

Select cities with `--cities houston,madisonville_tx,austin,san_antonio`
(default is all four). The script runs, in order: prereq check → freeze the
authority → Godot export → verify the city data is packed → stamp the build
manifest → validate outputs → (optional) zip. It prints a per-step
**OK / SKIPPED-blocked / FAIL** table and **never** reports a Windows artifact as
built or tested when it wasn't.

**Requirements on the build host**
- **Godot 4.4** on `PATH` (`godot --version` → `4.4.stable...`).
- **Godot 4.4 export templates** installed (the Windows template is
  `windows_release_x86_64.exe`). Get them via the Godot editor
  (*Editor → Manage Export Templates*) or by extracting
  `Godot_v4.4-stable_export_templates.tpz` into
  `%APPDATA%\Godot\export_templates\4.4.stable\`.
- **Python 3.11+** and **PyInstaller** (`pip install pyinstaller`) to freeze the
  authority.
- On Windows, to stamp the `.exe` icon/version, Godot needs **rcedit**
  configured (*Editor Settings → Export → Windows → rcedit*). Without it the
  export still succeeds; only the embedded icon/metadata are skipped (a harmless
  warning).

The authority is packaged separately by `tools/package_authority.py` (a
PyInstaller **onedir** freeze of `asphodel.bridge.server`). The build script
calls it for you; you can run it directly to (re)build just the authority:

```powershell
python tools\package_authority.py --target windows
```

> **Why onedir freeze?** It needs no system Python on the player's machine,
> resolves every `asphodel` import offline, carries its data files, and starts
> fast (no per-launch unpack). A cross-OS freeze is **not** possible — a Windows
> authority must be frozen on a Windows host. *Fallback (not used, documented for
> completeness):* if a freeze is ever impractical, ship an isolated runtime dir
> — a bundled CPython + the `asphodel` source + a launcher that runs
> `python -m asphodel.bridge.server`. The freeze is preferred.

---

## 3. Launch it

1. Unzip `Asphodel-Windows-V2.zip`.
2. **Double-click `Asphodel.exe`.**
3. The client starts the bundled authority on a private localhost port,
   completes the protocol **v9** handshake, and loads. Pick **Start → city →
   citizen → Continue** to enter the world.

There is nothing else to run. The client owns the authority process and shuts it
down when you quit.

---

## 4. Controls

Read from the shipped client scripts. Final key mapping is confirmed by the
gameplay team; these are what the current build binds:

| Action | Key |
|---|---|
| Move | **W / A / S / D** |
| Sprint | **Shift** |
| Interact (enter building, use object, search) | **E** (or click the target) |
| Talk to a citizen | **T** |
| Dialogue option 1–6 | **1 … 6** |
| Rotate camera | **[** and **]** |
| Developer **Simulation Inspector** | **F3** (Tab switches PLAYER / DEV-TRUTH) |
| Developer **event feed** | **F4** |
| Developer **build overlay** | **F10** |

### Developer inspector
Press **F3** in-world to toggle the **Simulation Inspector** — a read-only view
onto the authoritative simulation (selected citizen's cognition, work, groups,
dialogue, mobility). It performs no mutating calls; it only observes the live
authority over the existing bridge API.

---

## 5. Where saves and logs live

The client uses Godot's `user://` location. On **Windows** that resolves to:

```
%APPDATA%\Godot\app_userdata\Asphodel\
├─ saves\    game saves (user://saves)
└─ logs\     client + authority logs (user://logs)
```

Paste `%APPDATA%\Godot\app_userdata\Asphodel` into Explorer's address bar to open
it. If the client hits a fatal error (authority missing/crashed, bundle missing,
incompatible save/protocol) it shows a readable error screen that points at the
`logs\` path above. Saves carry an explicit `save_version`; a save written by an
incompatible build is refused rather than silently mishandled.

---

## 6. Build record & verification

Every build stamps an honest manifest and probe log under
`artifacts/windows_playable_v2/`:

- **`build_manifest.json`** — source SHA, Godot version, protocol version (9),
  save version, Python/package method, included cities, per-file sha256 + sizes,
  executable hashes, and the archive checksum. Windows-artifact fields carry a
  `blocked_reason` when built on a non-Windows host.
- **`authority_freeze_probe.json`** — proof the frozen authority launches and
  answers the `HELLO` handshake (captured for the Linux authority on this host).
- **`export_probe.txt`** — exactly what the Godot export did, per target,
  including whether each export template was present.
- **`SHA256SUMS.txt`** — checksums for the shipped zips and executables.

Verify a download against the manifest:

```powershell
# PowerShell
(Get-FileHash .\Asphodel-Windows-V2.zip -Algorithm SHA256).Hash.ToLower()
# compare to artifacts\windows_playable_v2\SHA256SUMS.txt
```

---

## 7. Known blocked-on-Linux steps (must be done on Windows)

| Step | Status on the Linux cert host | Where it must run |
|---|---|---|
| Windows `.exe` **export** | OK (cross-exported) | anywhere with the Windows template |
| Windows `.exe` **launch / playable cert** | **BLOCKED** (no Wine) | a Windows host |
| Windows **authority freeze** | **BLOCKED** (PyInstaller is host-OS only) | a Windows host |
| `.exe` icon/version stamping (rcedit) | warned/skipped | a Windows host with rcedit |
| Linux proxy export + boot | OK, runnable | this host (evidence) |
| Linux authority freeze + `HELLO` serve | OK, verified | this host (evidence) |

"Exported successfully" is never the same as "Windows playable certified." The
final Windows smoke test (double-click launch, authority auto-start, save/load,
clean-directory launch) is owned by the Windows build host.

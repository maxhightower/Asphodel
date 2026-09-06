<#
.SYNOPSIS
    Thin PowerShell wrapper around tools/build_windows_playable.py for Windows
    operators. This is NOT a second build implementation — the Python script is
    the ONE canonical entry point; this only locates Python and forwards args.

.EXAMPLE
    .\tools\build_windows_playable.ps1 -Target windows -Zip
    .\tools\build_windows_playable.ps1 -Target windows -Cities houston,austin

.NOTES
    On a real Windows host this produces a launchable Asphodel.exe AND (via
    package_authority.py --target windows) a Windows frozen authority. Run it
    from the repo root. Requires: Python 3.11+, `pip install pyinstaller`, and
    Godot 4.4 with the Windows export templates installed.
#>
[CmdletBinding()]
param(
    [ValidateSet("windows", "linux")]
    [string]$Target = "windows",
    [string[]]$Cities = @("houston", "madisonville_tx", "austin", "san_antonio"),
    [switch]$Zip,
    [switch]$SkipAuthority
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Locate a Python interpreter.
$py = $null
foreach ($cand in @("python", "python3", "py")) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $py = $cand; break }
}
if (-not $py) { throw "Python 3.11+ not found on PATH. Install it, then retry." }

$script = Join-Path $repo "tools\build_windows_playable.py"
$argList = @($script, "--target", $Target, "--cities", ($Cities -join ","))
if ($Zip) { $argList += "--zip" }
if ($SkipAuthority) { $argList += "--skip-authority" }

Write-Host "==> $py $($argList -join ' ')" -ForegroundColor Cyan
& $py @argList
exit $LASTEXITCODE

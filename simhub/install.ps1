# Installs SimCoach's SimHub plugin and dashboard into your SimHub.
#   powershell -ExecutionPolicy Bypass -File simhub\install.ps1 [-SimHub <folder>] [-Restart]
# -Restart closes SimHub (if open) and starts it again so it loads the plugin. Without it, restart SimHub yourself.
# On SimHub's next start, say yes if it asks to enable the new "SimCoach" plugin.
param([string]$SimHub = "", [switch]$Restart)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-SimHub {
    foreach ($k in @("HKCU:\Software\SimHub", "HKLM:\SOFTWARE\WOW6432Node\SimHub", "HKLM:\SOFTWARE\SimHub")) {
        try { $p = (Get-ItemProperty $k -ErrorAction Stop).InstallDirectory; if ($p -and (Test-Path "$p\SimHubWPF.exe")) { return $p } } catch {}
    }
    $run = Get-Process SimHubWPF -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($run -and $run.Path) { return (Split-Path -Parent $run.Path) }
    foreach ($p in @("${env:ProgramFiles(x86)}\SimHub", "$env:ProgramFiles\SimHub", "C:\SimHub")) {
        if (Test-Path "$p\SimHubWPF.exe") { return $p }
    }
    return $null
}
if (-not $SimHub) { $SimHub = Find-SimHub }
if (-not $SimHub -or -not (Test-Path "$SimHub\SimHubWPF.exe")) { throw "SimHub not found. Install SimHub first, or pass -SimHub <folder>." }
$dll = Join-Path $here "SimCoach.SimHub.dll"
$dash = Join-Path $here "dashboard\SimCoach"
if (-not (Test-Path $dll)) { throw "Missing $dll (build it with simhub\build_plugin.ps1)." }

$exe = "$SimHub\SimHubWPF.exe"
$wasRunning = $null -ne (Get-Process SimHubWPF -ErrorAction SilentlyContinue)
if ($Restart -and $wasRunning) {
    Write-Host "Closing SimHub..."
    Get-Process SimHubWPF | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    for ($i = 0; $i -lt 40 -and (Get-Process SimHubWPF -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 500 }
    try { Get-Process SimHubWPF -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction Stop } catch {
        # SimHub often runs as administrator; then only an administrator (or SimHub's own Exit) can close it
        Write-Warning "Couldn't close SimHub (it's running as administrator). Exit it from its tray icon, then start it again."
        $Restart = $false
    }
}

$dest = "$SimHub\SimCoach.SimHub.dll"
Remove-Item "$dest.old" -Force -ErrorAction SilentlyContinue      # left by an update while SimHub was open
try {
    Copy-Item $dll $dest -Force -ErrorAction Stop
} catch {
    # SimHub has the old plugin loaded: Windows lets a loaded DLL be renamed, so the new one loads next start
    try {
        Rename-Item $dest "SimCoach.SimHub.dll.old" -Force -ErrorAction Stop
        Copy-Item $dll $dest -Force -ErrorAction Stop
        Write-Host "SimHub has the old plugin loaded: the new one loads when SimHub next starts."
    } catch {
        throw "Couldn't copy the plugin into $SimHub. Exit SimHub (tray icon > Exit) and run this again. $_"
    }
}
$target = "$SimHub\DashTemplates\SimCoach"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item "$dash\*" $target -Recurse -Force
Write-Host "Plugin:    $SimHub\SimCoach.SimHub.dll"
Write-Host "Dashboard: $target"

if ($Restart) {
    Start-Process $exe
    Write-Host "SimHub started. If it asks about a new plugin called SimCoach, choose to enable it."
} elseif ($wasRunning) {
    Write-Host "SimHub is open: restart it to load the plugin (the dashboard shows up straight away in Dash Studio)."
}
Write-Host "Then: Dash Studio > SimCoach > Play (or pick it on your device / phone). Start SimCoach and drive."

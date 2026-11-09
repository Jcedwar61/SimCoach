# Removes SimCoach (run from Settings > Apps > Installed apps > SimCoach > Uninstall).
# Keeps the user's data: reference laps and settings (%APPDATA%\SimCoach) and reports (Documents\SimCoach Reports).
param([switch]$Quiet)

$Dest = $PSScriptRoot
$programs = Join-Path $env:LOCALAPPDATA 'Programs'
# safety: only ever remove the folder the installer made
if ((Split-Path $Dest -Leaf) -ne 'SimCoach' -or -not $Dest.StartsWith($programs, [StringComparison]::OrdinalIgnoreCase)) { exit 1 }

Add-Type -AssemblyName System.Windows.Forms

# A SimCoach running from this folder: politely first (it saves the session and writes its report), then force.
function Get-SimCoachProcs {
    $script = Join-Path $Dest 'sim_coach.py'
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.Name -notlike 'SimCoach-Setup*' -and (
            (($_.Name -like 'python*' -or $_.Name -like 'uv*') -and $_.CommandLine -and
             $_.CommandLine.IndexOf($script, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Dest + '\', [StringComparison]::OrdinalIgnoreCase)))
    })
}

function Close-SimCoach {
    $procs = Get-SimCoachProcs
    if ($procs.Count -eq 0) { return $false }
    foreach ($p in $procs) {
        if ($p.Name -like 'python*') {
            try {
                $gp = Get-Process -Id $p.ProcessId -ErrorAction Stop
                if ($gp.MainWindowHandle -ne [IntPtr]::Zero) { [void]$gp.CloseMainWindow() }
            } catch {}
        }
    }
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline -and @(Get-SimCoachProcs).Count -gt 0) {      # Python, then uv and the launcher
        Start-Sleep -Milliseconds 300
    }
    # what's left: the launcher first (it waits on SimCoach and would report the others closing), then uv, then Python
    $left = @(Get-SimCoachProcs | Sort-Object { if ($_.Name -like 'SimCoach*') { 0 } elseif ($_.Name -like 'uv*') { 1 } else { 2 } })
    foreach ($p in $left) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    foreach ($p in $left) { Wait-Process -Id $p.ProcessId -Timeout 5 -ErrorAction SilentlyContinue }
    return $true
}

if (-not $Quiet) {
    $msg = "Remove SimCoach from this PC?`n`nYour reference laps, settings and reports are kept:`n" +
           "    $env:APPDATA\SimCoach`n    Documents\SimCoach Reports`n`nIf SimCoach is running it will be closed."
    $r = [System.Windows.Forms.MessageBox]::Show($msg, 'Uninstall SimCoach', 'OKCancel', 'Question')
    if ($r -ne 'OK') { exit 1 }
}

# close a running SimCoach of this installed copy (one run from another folder is left alone)
try { [void](Close-SimCoach) } catch {}

foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    if ($folder) { Remove-Item (Join-Path $folder 'SimCoach.lnk') -Force -ErrorAction SilentlyContinue }
}
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCoach' -Recurse -Force -ErrorAction SilentlyContinue

Set-Location $env:TEMP
Start-Sleep -Milliseconds 600
Remove-Item $Dest -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $Dest) {
    # something was still in use: finish a moment after this script exits
    Start-Process -WindowStyle Hidden "$env:SystemRoot\System32\cmd.exe" -ArgumentList "/c timeout /t 3 /nobreak >nul & rmdir /s /q `"$Dest`""
}
if (-not $Quiet) {
    [System.Windows.Forms.MessageBox]::Show('SimCoach was removed.', 'Uninstall SimCoach', 'OK', 'Information') | Out-Null
}
exit 0

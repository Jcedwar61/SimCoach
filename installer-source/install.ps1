# SimCoach setup steps (run by SimCoach-Setup.exe in its own console window).
# Exit codes: 0 = all done, 2 = installed but the parts download didn't finish (first launch retries), 1 = failed.
param([string]$Dest = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
try { $Host.UI.RawUI.WindowTitle = 'SimCoach setup' } catch {}
$log = Join-Path $Dest 'install.log'
try { Start-Transcript -Path $log -Force | Out-Null } catch {}

function Step($n, $t) { Write-Host ''; Write-Host "  [$n/4]  $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "          ok  $t" -ForegroundColor Green }
function Warn($t) { Write-Host "          !!  $t" -ForegroundColor Yellow }
function Note($t) { Write-Host "          $t" -ForegroundColor DarkGray }

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

function Find-UV {
    $c = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($d in @("$env:USERPROFILE\.local\bin", "$env:USERPROFILE\.cargo\bin")) {
        $p = Join-Path $d 'uv.exe'
        if (Test-Path $p) { return $p }
    }
    return $null
}

$warn = $false
try {
    Write-Host ''
    Write-Host '  SimCoach setup' -ForegroundColor White
    Note "Installing to $Dest"

    # an update while SimCoach is running: close it, or the new version can't start (one SimCoach at a time)
    try {
        $ErrorActionPreference = 'Continue'
        if (Close-SimCoach) { Note 'closed the SimCoach that was running (its session was saved)' }
        Remove-Item (Join-Path $Dest 'SimCoach.exe.old') -Force -ErrorAction SilentlyContinue
    } catch {
        Warn "couldn't close the running SimCoach: $($_.Exception.Message)"
    } finally {
        $ErrorActionPreference = 'Stop'
    }

    # 1. uv: runs SimCoach with its own Python 3.12 and packages (nothing touches a system Python)
    Step 1 'Python runner (uv)'
    $uv = Find-UV
    if (-not $uv) {
        Note 'downloading uv from github.com/astral-sh/uv ...'
        try {
            # uv's official release zip (uv.exe, uvw.exe, uvx.exe), into the folder uv's own installer uses
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
            $bin = Join-Path $env:USERPROFILE '.local\bin'
            $zip = Join-Path $env:TEMP 'simcoach-uv.zip'
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip" -OutFile $zip
            New-Item -ItemType Directory -Force -Path $bin | Out-Null
            Expand-Archive -Force -Path $zip -DestinationPath $bin
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
        } catch {
            Warn "uv download failed: $($_.Exception.Message)"
        } finally {
            $ErrorActionPreference = 'Stop'
        }
        $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
        $uv = Find-UV
    }
    if ($uv) { Ok $uv } else { Warn 'uv is not installed yet; SimCoach installs it on first launch'; $warn = $true }

    # 2. shortcuts with the SimCoach icon
    Step 2 'Desktop and Start menu shortcuts'
    $exe = Join-Path $Dest 'SimCoach.exe'
    $ico = Join-Path $Dest 'SimCoach.ico'
    $ws = New-Object -ComObject WScript.Shell
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        if (-not $folder) { continue }
        $lnk = $ws.CreateShortcut((Join-Path $folder 'SimCoach.lnk'))
        $lnk.TargetPath = $exe
        $lnk.WorkingDirectory = $Dest
        $lnk.IconLocation = "$ico,0"
        $lnk.Description = 'SimCoach - live voice coach for sim racing'
        $lnk.Save()
    }
    Ok 'SimCoach on the desktop and in the Start menu'

    # 3. Settings > Apps entry with an uninstaller
    Step 3 'Apps & features entry'
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCoach'
    New-Item -Path $key -Force | Out-Null
    $ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $un = Join-Path $Dest 'uninstall.ps1'
    $size = [int]((Get-ChildItem $Dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
    $props = [ordered]@{
        DisplayName          = 'SimCoach'
        DisplayVersion       = '6.10'
        Publisher            = 'SimCoach'
        DisplayIcon          = $ico
        InstallLocation      = $Dest
        UninstallString      = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$un`""
        QuietUninstallString = "`"$ps`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$un`" -Quiet"
    }
    foreach ($k in $props.Keys) { New-ItemProperty -Path $key -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
    foreach ($k in @('NoModify', 'NoRepair')) { New-ItemProperty -Path $key -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
    New-ItemProperty -Path $key -Name 'EstimatedSize' -Value $size -PropertyType DWord -Force | Out-Null
    Ok 'Settings > Apps > Installed apps > SimCoach (Uninstall is there)'

    # 4. the parts: Python 3.12, the packages and the offline speech parts, so the first launch is quick
    Step 4 'SimCoach parts (Python 3.12, packages, offline speech parts)'
    if ($uv) {
        Note 'a few minutes the first time; later updates are quick ...'
        $ErrorActionPreference = 'Continue'
        Push-Location $Dest
        & $uv run --python 3.12 (Join-Path $Dest 'sim_coach.py') --setup
        $code = $LASTEXITCODE
        Pop-Location
        $ErrorActionPreference = 'Stop'
        if ($code -eq 0) { Ok 'ready' } else { Warn "parts setup stopped (code $code); they finish on first launch"; $warn = $true }
    } else {
        Warn 'skipped (no uv yet)'
        $warn = $true
    }

    Write-Host ''
    if ($warn) { Write-Host '  SimCoach is installed (some parts finish on first launch).' -ForegroundColor Yellow }
    else       { Write-Host '  SimCoach is installed and ready.' -ForegroundColor Green }
    try { Stop-Transcript | Out-Null } catch {}
    Start-Sleep -Seconds 2
    if ($warn) { exit 2 } else { exit 0 }
}
catch {
    Write-Host ''
    Write-Host "  Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Details: $log" -ForegroundColor DarkGray
    try { Stop-Transcript | Out-Null } catch {}
    Read-Host '  Press Enter to close'
    exit 1
}

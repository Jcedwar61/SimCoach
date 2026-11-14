# SimCoach setup steps, run by the setup wizard (SimCoach-Setup.exe) one at a time with no window of their own;
# what they print shows in the wizard's progress list.
#   -Step close   close a SimCoach running from the install folder (its session is saved first)
#   -Step uv      find or download uv, which runs SimCoach with its own Python
#   -Step parts   Python 3.12, SimCoach's packages and the offline speech recognition
# Exit codes: 0 = done, 2 = didn't finish (SimCoach finishes it on first launch), 1 = failed.
# 'parts' also leaves setup-ready.txt in the install folder when it really finished: the wizard checks for that file
# rather than trusting an exit code (a blocked or missing PowerShell can look like success).
param([string]$Dest = $PSScriptRoot, [ValidateSet('close', 'uv', 'parts')][string]$Step = 'parts')

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$log = Join-Path $Dest 'install.log'

function Say($t) { Write-Output $t; try { Add-Content -Path $log -Value "$(Get-Date -Format s)  $t" } catch {} }

# A SimCoach running from this folder: politely first (it saves the session and writes its report), then force.
function Get-SimCoachProcs {
    $script = Join-Path $Dest 'sim_coach.py'
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.Name -notlike 'SimCoach-Setup*' -and $_.Name -notlike 'Uninstall SimCoach*' -and
        $_.Name -notlike 'Au_*' -and (
            (($_.Name -like 'python*' -or $_.Name -like 'uv*') -and $_.CommandLine -and
             $_.CommandLine.IndexOf($script, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Dest + '\', [StringComparison]::OrdinalIgnoreCase) -and
             $_.Name -like 'SimCoach.exe'))
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
    while ((Get-Date) -lt $deadline -and @(Get-SimCoachProcs).Count -gt 0) { Start-Sleep -Milliseconds 300 }
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

try {
    switch ($Step) {
        'close' {
            $ErrorActionPreference = 'Continue'
            if (Close-SimCoach) { Say 'Closed the SimCoach that was running (its session was saved).' }
            Remove-Item (Join-Path $Dest 'SimCoach.exe.old') -Force -ErrorAction SilentlyContinue
            exit 0
        }
        'uv' {
            $uv = Find-UV
            if (-not $uv) {
                Say 'Downloading uv from github.com/astral-sh/uv ...'
                try {
                    # uv's official release zip (uv.exe, uvw.exe, uvx.exe), into the folder uv's own installer uses
                    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
                    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
                    $bin = Join-Path $env:USERPROFILE '.local\bin'
                    $zip = Join-Path $env:TEMP 'simcoach-uv.zip'
                    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip" -OutFile $zip
                    New-Item -ItemType Directory -Force -Path $bin | Out-Null
                    Expand-Archive -Force -Path $zip -DestinationPath $bin
                    Remove-Item $zip -Force -ErrorAction SilentlyContinue
                } catch {
                    Say "uv download failed: $($_.Exception.Message)"
                }
                $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
                $uv = Find-UV
            }
            if ($uv) { Say "uv: $uv"; exit 0 }
            Say 'uv is not installed yet; SimCoach installs it the first time it starts.'
            exit 2
        }
        'parts' {
            $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
            $uv = Find-UV
            if (-not $uv) { Say 'Skipped: no uv yet (SimCoach finishes this the first time it starts).'; exit 2 }
            $env:PYTHONIOENCODING = 'utf-8'
            $env:NO_COLOR = '1'
            $env:UV_NO_PROGRESS = '1'
            Remove-Item (Join-Path $Dest 'setup-ready.txt') -Force -ErrorAction SilentlyContinue
            Push-Location $Dest
            $ErrorActionPreference = 'Continue'
            & $uv run --python 3.12 (Join-Path $Dest 'sim_coach.py') --setup 2>&1 | ForEach-Object { Say "$_" }
            $code = $LASTEXITCODE
            Pop-Location
            if ($code -eq 0) { Set-Content -Path (Join-Path $Dest 'setup-ready.txt') -Value 'ok'; Say 'Ready.'; exit 0 }
            Say "Stopped (code $code); SimCoach finishes this the first time it starts."
            exit 2
        }
    }
}
catch {
    Say "Setup step '$Step' failed: $($_.Exception.Message)"
    exit 1
}

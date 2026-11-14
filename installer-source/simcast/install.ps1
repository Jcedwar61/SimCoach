# SimCast setup steps, run by the setup wizard (SimCast-Setup.exe) one at a time with no window of their own;
# what they print shows in the wizard's progress list.
#   -Step close   close a SimCast running from the install folder
#   -Step uv      find or download uv, which runs SimCast with its own Python
#   -Step parts   Python 3.12 and SimCast's packages
# Exit codes: 0 = done, 2 = didn't finish (SimCast finishes it on first launch), 1 = failed.
# 'parts' also leaves setup-ready.txt in the install folder when it really finished (the wizard checks the file,
# not the exit code: a blocked or missing PowerShell can look like success).
param([string]$Dest = $PSScriptRoot, [ValidateSet('close', 'uv', 'parts')][string]$Step = 'parts')

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$log = Join-Path $Dest 'install.log'

function Say($t) { Write-Output $t; try { Add-Content -Path $log -Value "$(Get-Date -Format s)  $t" } catch {} }

function Get-SimCastProcs {
    $script = Join-Path $Dest 'sim_cast.py'
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.Name -notlike 'SimCast-Setup*' -and $_.Name -notlike 'Uninstall SimCast*' -and
        $_.Name -notlike 'Au_*' -and (
            (($_.Name -like 'python*' -or $_.Name -like 'uv*') -and $_.CommandLine -and
             $_.CommandLine.IndexOf($script, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Dest + '\', [StringComparison]::OrdinalIgnoreCase) -and
             $_.Name -like 'SimCast.exe'))
    })
}

function Close-SimCast {
    $procs = Get-SimCastProcs
    if ($procs.Count -eq 0) { return $false }
    foreach ($p in $procs) {
        if ($p.Name -like 'python*') {
            try {
                $gp = Get-Process -Id $p.ProcessId -ErrorAction Stop
                if ($gp.MainWindowHandle -ne [IntPtr]::Zero) { [void]$gp.CloseMainWindow() }
            } catch {}
        }
    }
    $deadline = (Get-Date).AddSeconds(6)
    while ((Get-Date) -lt $deadline -and @(Get-SimCastProcs).Count -gt 0) { Start-Sleep -Milliseconds 300 }
    $left = @(Get-SimCastProcs | Sort-Object { if ($_.Name -like 'SimCast*') { 0 } elseif ($_.Name -like 'uv*') { 1 } else { 2 } })
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
            if (Close-SimCast) { Say 'Closed the SimCast that was running.' }
            exit 0
        }
        'uv' {
            $uv = Find-UV
            if (-not $uv) {
                Say 'Downloading uv from github.com/astral-sh/uv ...'
                try {
                    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
                    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
                    $bin = Join-Path $env:USERPROFILE '.local\bin'
                    $zip = Join-Path $env:TEMP 'simcast-uv.zip'
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
            Say 'uv is not installed yet; SimCast installs it the first time it starts.'
            exit 2
        }
        'parts' {
            $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
            $uv = Find-UV
            if (-not $uv) { Say 'Skipped: no uv yet (SimCast finishes this the first time it starts).'; exit 2 }
            $env:PYTHONIOENCODING = 'utf-8'
            $env:NO_COLOR = '1'
            $env:UV_NO_PROGRESS = '1'
            Remove-Item (Join-Path $Dest 'setup-ready.txt') -Force -ErrorAction SilentlyContinue
            Push-Location $Dest
            $ErrorActionPreference = 'Continue'
            & $uv run --python 3.12 (Join-Path $Dest 'sim_cast.py') --setup 2>&1 | ForEach-Object { Say "$_" }
            $code = $LASTEXITCODE
            Pop-Location
            if ($code -eq 0) { Set-Content -Path (Join-Path $Dest 'setup-ready.txt') -Value 'ok'; Say 'Ready.'; exit 0 }
            Say "Stopped (code $code); SimCast finishes this the first time it starts."
            exit 2
        }
    }
}
catch {
    Say "Setup step '$Step' failed: $($_.Exception.Message)"
    exit 1
}

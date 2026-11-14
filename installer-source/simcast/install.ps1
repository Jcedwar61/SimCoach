# Closes a SimCast running from the install folder before the setup wizard (SimCast-Setup.exe) replaces its files
# or the uninstaller removes them. Everything else the installer does needs no PowerShell (SimCast.exe --setup gets
# uv, Python and the packages), so under Wine, where there's no PowerShell, only this convenience is skipped.
param([string]$Dest = $PSScriptRoot, [ValidateSet('close')][string]$Step = 'close')

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

try {
    switch ($Step) {
        'close' {
            $ErrorActionPreference = 'Continue'
            if (Close-SimCast) { Say 'Closed the SimCast that was running.' }
            exit 0
        }
    }
}
catch {
    Say "Setup step '$Step' failed: $($_.Exception.Message)"
    exit 1
}

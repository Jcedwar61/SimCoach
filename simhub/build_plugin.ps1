# Builds simhub\SimCoach.SimHub.dll from simhub\plugin\SimCoachPlugin.cs with the C# compiler that comes with
# Windows (.NET Framework 4.x): no Visual Studio needed. It compiles against your installed SimHub's own DLLs.
#   powershell -ExecutionPolicy Bypass -File simhub\build_plugin.ps1 [-SimHub "C:\Program Files (x86)\SimHub"]
param([string]$SimHub = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-SimHub {
    foreach ($k in @("HKCU:\Software\SimHub", "HKLM:\SOFTWARE\WOW6432Node\SimHub", "HKLM:\SOFTWARE\SimHub")) {
        try { $p = (Get-ItemProperty $k -ErrorAction Stop).InstallDirectory; if ($p -and (Test-Path "$p\SimHubWPF.exe")) { return $p } } catch {}
    }
    foreach ($p in @("${env:ProgramFiles(x86)}\SimHub", "$env:ProgramFiles\SimHub", "C:\SimHub")) {
        if (Test-Path "$p\SimHubWPF.exe") { return $p }
    }
    return $null
}
if (-not $SimHub) { $SimHub = Find-SimHub }
if (-not $SimHub -or -not (Test-Path "$SimHub\SimHub.Plugins.dll")) { throw "SimHub not found. Pass -SimHub <folder>." }

$fw = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319"
if (-not (Test-Path "$fw\csc.exe")) { $fw = "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319" }
$wpf = "$fw\WPF"
$out = Join-Path $here "SimCoach.SimHub.dll"
$refs = @(
    "$SimHub\SimHub.Plugins.dll", "$SimHub\GameReaderCommon.dll", "$SimHub\SimHub.Logging.dll",
    "$SimHub\log4net.dll", "$SimHub\Newtonsoft.Json.dll",
    "$wpf\PresentationCore.dll", "$wpf\PresentationFramework.dll", "$wpf\WindowsBase.dll", "$fw\System.Xaml.dll"
) | ForEach-Object { "/reference:`"$_`"" }

& "$fw\csc.exe" /nologo /target:library /optimize+ /platform:anycpu /warn:4 "/out:$out" @refs (Join-Path $here "plugin\SimCoachPlugin.cs")
if ($LASTEXITCODE -ne 0) { throw "Build failed." }
Write-Host "Built $out against SimHub in $SimHub"

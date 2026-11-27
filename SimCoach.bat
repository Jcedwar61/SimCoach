@echo off
setlocal
title SimCoach
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 goto run
if exist "%USERPROFILE%\.local\bin\uv.exe" (set "PATH=%USERPROFILE%\.local\bin;%PATH%" & goto run)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (set "PATH=%USERPROFILE%\.cargo\bin;%PATH%" & goto run)
echo First run: downloading uv (Python runner, from github.com/astral-sh/uv)...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor 3072; $a='x86_64'; if($env:PROCESSOR_ARCHITECTURE -eq 'ARM64'){$a='aarch64'}; $d=Join-Path $env:USERPROFILE '.local\bin'; $z=Join-Path $env:TEMP 'simcoach-uv.zip'; $h=@{'x86_64'='ACFDE570451CFDB8689FA159A138EE805BA4E241C466432750302C86254B0984';'aarch64'='A7427EA0440BB826B6716D1837FF3D173B8E7D496CB09EE8F456B4E023A2FDCD'}; Invoke-WebRequest -UseBasicParsing ('https://github.com/astral-sh/uv/releases/download/0.11.32/uv-'+$a+'-pc-windows-msvc.zip') -OutFile $z; if((Get-FileHash -Algorithm SHA256 $z).Hash -ne $h[$a]){Remove-Item $z; throw 'uv download checksum mismatch'}; New-Item -ItemType Directory -Force $d | Out-Null; Expand-Archive -Force $z $d; Remove-Item $z"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
:run
echo Starting SimCoach... (first launch downloads its parts, a few minutes)
if "%~1"=="" if exist "%APPDATA%\SimCoach\config.json" (
    where uvw >nul 2>nul
    if not errorlevel 1 (start "" uvw run --python 3.12 sim_coach.py & exit /b)
)
uv run --python 3.12 sim_coach.py %*

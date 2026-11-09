@echo off
setlocal
title SimCoach
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 goto run
if exist "%USERPROFILE%\.local\bin\uv.exe" (set "PATH=%USERPROFILE%\.local\bin;%PATH%" & goto run)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (set "PATH=%USERPROFILE%\.cargo\bin;%PATH%" & goto run)
echo First run: downloading uv (Python runner, from github.com/astral-sh/uv)...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor 3072; $a='x86_64'; if($env:PROCESSOR_ARCHITECTURE -eq 'ARM64'){$a='aarch64'}; $d=Join-Path $env:USERPROFILE '.local\bin'; $z=Join-Path $env:TEMP 'simcoach-uv.zip'; Invoke-WebRequest -UseBasicParsing ('https://github.com/astral-sh/uv/releases/latest/download/uv-'+$a+'-pc-windows-msvc.zip') -OutFile $z; New-Item -ItemType Directory -Force $d | Out-Null; Expand-Archive -Force $z $d; Remove-Item $z"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
:run
echo Starting SimCoach... (first launch downloads its parts, a few minutes)
if "%~1"=="" if exist "%APPDATA%\SimCoach\config.json" (
    where uvw >nul 2>nul
    if not errorlevel 1 (start "" uvw run --python 3.12 sim_coach.py & exit /b)
)
uv run --python 3.12 sim_coach.py %*

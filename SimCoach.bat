@echo off
setlocal
title SimCoach
cd /d "%~dp0"
where uv >nul 2>nul
if %errorlevel%==0 goto run
if exist "%USERPROFILE%\.local\bin\uv.exe" (set "PATH=%USERPROFILE%\.local\bin;%PATH%" & goto run)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (set "PATH=%USERPROFILE%\.cargo\bin;%PATH%" & goto run)
echo First run: installing uv (Python runner, from astral.sh)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
:run
echo Starting SimCoach... (first launch downloads its parts, a few minutes)
if "%~1"=="" if exist "%APPDATA%\SimCoach\config.json" (
    where uvw >nul 2>nul
    if not errorlevel 1 (start "" uvw run --python 3.12 sim_coach.py & exit /b)
)
uv run --python 3.12 sim_coach.py %*

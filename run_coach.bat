@echo off
setlocal
title SimCoach
cd /d "%~dp0"
rem Uses uv (fast Python runner). Installs everything it needs on first run.
where uv >nul 2>nul
if %errorlevel%==0 goto run
if exist "%USERPROFILE%\.local\bin\uv.exe" (set "PATH=%USERPROFILE%\.local\bin;%PATH%" & goto run)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (set "PATH=%USERPROFILE%\.cargo\bin;%PATH%" & goto run)
echo uv was not found. Installing it once (from astral.sh)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
:run
uv run --python 3.12 sim_coach.py %*
echo.
pause

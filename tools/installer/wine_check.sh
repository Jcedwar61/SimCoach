#!/usr/bin/env bash
# Run SimCoach-Setup.exe under Wine on a virtual screen: click through every page of the wizard, screenshot each
# one, then check what it installed and run the uninstaller. Needs: wine wine32:i386 xvfb xdotool imagemagick.
# Wine has no PowerShell, so the download steps "don't finish" here: the finish page shows that case.
#   tools/installer/wine_check.sh [SimCoach-Setup.exe] [OUT_DIR]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
EXE="$(realpath "${1:-$REPO/SimCoach-Setup.exe}")"
OUT="$(realpath -m "${2:-$REPO/dist/installer-check}")"
mkdir -p "$OUT"; rm -f "$OUT"/*.png
export WINEPREFIX="$(mktemp -d)/prefix" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
trap 'wineserver -k >/dev/null 2>&1 || true; rm -rf "$(dirname "$WINEPREFIX")"' EXIT

run() {
  wineboot -i >/dev/null 2>&1
  wine "$EXE" >/dev/null 2>&1 &
  local W=""
  for _ in $(seq 1 60); do W=$(xdotool search --name "SimCoach .* Setup" 2>/dev/null | head -1 || true); [ -n "$W" ] && break; sleep 1; done
  [ -n "$W" ] || { echo "the wizard never opened"; exit 1; }
  shot() { sleep "${2:-2}"; import -window root -crop "$(xwininfo -id "$W" | awk '/Width:/{w=$2}/Height:/{h=$2}/Absolute upper-left X:/{x=$4}/Absolute upper-left Y:/{y=$4}END{print w"x"h"+"x"+"y}')" "$OUT/$1.png"; }
  next() { xdotool windowactivate --sync "$W" 2>/dev/null || true; xdotool key --window "$W" Return; }
  shot 1_welcome 3; next
  shot 2_licence; next            # "I Agree"
  shot 3_components; next
  shot 4_folder; next             # Install
  shot 5_installing 1
  for _ in $(seq 1 60); do xwininfo -id "$W" -tree 2>/dev/null | grep -q '"&Finish"\|"Finish"' && break; sleep 1; done
  shot 6_finish 2
  # untick "Start SimCoach" (space on the focused checkbox would work too) by closing with Finish after unticking
  xdotool key --window "$W" alt+s 2>/dev/null || true
  next
  sleep 2
  local D="$WINEPREFIX/drive_c/users/$USER/AppData/Local/Programs/SimCoach"
  [ -d "$D" ] || D="$(find "$WINEPREFIX/drive_c/users" -maxdepth 6 -type d -path '*Programs/SimCoach' | head -1)"
  echo "installed in: $D"; ls -1 "$D"
  for f in sim_coach.py SimCoach.exe SimCoach.ico README.txt LICENSE.txt install.ps1 "Uninstall SimCoach.exe"; do
    [ -f "$D/$f" ] || { echo "MISSING: $f"; exit 1; }
  done
  if cmp -s "$D/sim_coach.py" "$REPO/sim_coach.py"; then echo "sim_coach.py matches the repo"
  else echo "NOTE: the installed sim_coach.py differs from the repo's (rebuild the installer?)"; fi
  wine reg query 'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCoach' 2>/dev/null | tr -d '\r' | grep -E "DisplayName|DisplayVersion|InstallLocation|UninstallString" || true
  find "$WINEPREFIX/drive_c/users" -name 'SimCoach.lnk' | sed 's/^/shortcut: /'
  wine "$D/Uninstall SimCoach.exe" /S >/dev/null 2>&1; sleep 6
  if [ -e "$D/sim_coach.py" ]; then echo "UNINSTALL left files"; exit 1; fi
  wine reg query 'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SimCoach' >/dev/null 2>&1 && { echo "UNINSTALL left the Apps entry"; exit 1; }
  [ -z "$(find "$WINEPREFIX/drive_c/users" -name 'SimCoach.lnk')" ] || { echo "UNINSTALL left a shortcut"; exit 1; }
  echo "uninstall: files, shortcuts and the Apps entry removed"
}
export -f run 2>/dev/null || true
export EXE OUT REPO
xvfb-run -a -s "-screen 0 1280x900x24" bash -c "$(declare -f run); run"
echo "Screenshots in $OUT"

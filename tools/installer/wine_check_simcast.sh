#!/usr/bin/env bash
# Check SimCast-Setup.exe under Wine (64-bit), the way Linux and Steam Deck players run it:
#   1. a fresh prefix, a silent install (/S): files, shortcuts and the Settings > Apps entry are there
#   2. SimCast.exe --setup got uv, Python 3.12 and the packages (setup-ready.txt)
#   3. SimCast's own Python runs a whole demo race inside Wine (--test) without errors
#   4. the SimCast window opens under Wine (a screenshot is saved)
#   5. the uninstaller removes it all and keeps the settings
# Needs: wine (wine64), xvfb-run, imagemagick (import), internet for step 2.
#   tools/installer/wine_check_simcast.sh [SimCast-Setup.exe] [OUT_DIR]
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
EXE="$(realpath "${1:-$REPO/SimCast-Setup.exe}")"
OUT="$(realpath -m "${2:-$REPO/dist/simcast-wine-check}")"
mkdir -p "$OUT"
WINE="$(command -v wine64 || command -v wine || echo /usr/lib/wine/wine64)"
export WINEPREFIX="$(mktemp -d)/prefix" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=;winedbg.exe=d"
trap 'wineserver -k >/dev/null 2>&1 || /usr/lib/wine/wineserver -k >/dev/null 2>&1; rm -rf "$(dirname "$WINEPREFIX")"' EXIT
fail=0
check() { if eval "$1"; then echo "ok   $2"; else echo "FAIL $2"; fail=1; fi; }

xvfb-run -a "$WINE" wineboot -i >/dev/null 2>&1
timeout 900 xvfb-run -a "$WINE" "$EXE" /S >"$OUT/install.txt" 2>&1
USERDIR="$(ls -d "$WINEPREFIX"/drive_c/users/*/ | grep -v Public | head -1)"
D="$USERDIR/AppData/Local/Programs/SimCast"
UV="$USERDIR/.local/bin/uv.exe"
check '[ -f "$D/SimCast.exe" ] && [ -f "$D/sim_cast.py" ] && [ -f "$D/simcast/app.py" ]' "installed: SimCast.exe, sim_cast.py, simcast/"
check '[ -f "$D/simcast/licenses/THIRD_PARTY_NOTICES.txt" ] && [ -f "$D/LICENSE.txt" ]' "installed: licences"
check '[ ! -e "$D/sim_coach.py" ]' "doesn't need SimCoach (no sim_coach.py)"
check '[ -f "$USERDIR/Desktop/SimCast.lnk" ] || ls "$USERDIR"/Desktop/*SimCast* >/dev/null 2>&1' "desktop shortcut"
check 'ls "$USERDIR"/AppData/Roaming/Microsoft/Windows/"Start Menu"/Programs/SimCast.lnk >/dev/null 2>&1' "Start menu shortcut"
check '"$WINE" reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SimCast" 2>/dev/null | grep -q DisplayVersion' "Settings > Apps entry"
check '[ -f "$UV" ]' "SimCast.exe --setup downloaded uv (no PowerShell needed)"
check '[ -f "$D/setup-ready.txt" ]' "SimCast.exe --setup finished (Python 3.12 and the packages)"
# through cmd's own redirection: a Linux-side redirect gives Wine's Python invalid standard handles
WD="$(echo "$D" | sed -E "s#^$WINEPREFIX/drive_c#C:#; s#/#\\\\#g")"
WUV="$(echo "$UV" | sed -E "s#^$WINEPREFIX/drive_c#C:#; s#/#\\\\#g")"
(cd "$D" && timeout 600 xvfb-run -a "$WINE" cmd /c "cd /d $WD && $WUV run --python 3.12 sim_cast.py --test --laps 3 > C:\\simcast-test.txt 2>&1")
cp "$WINEPREFIX/drive_c/simcast-test.txt" "$OUT/test-race.txt" 2>/dev/null
check 'grep -q "errors: none" "$OUT/test-race.txt"' "a whole demo race runs inside Wine ($(grep -c '' "$OUT/test-race.txt" 2>/dev/null) lines)"
# the window, for real, under Wine, with the demo race running
Xvfb :77 -screen 0 1280x860x24 >/dev/null 2>&1 & XPID=$!
sleep 2
(cd "$D" && DISPLAY=:77 timeout 120 "$WINE" cmd /c "cd /d $WD && $WUV run --python 3.12 sim_cast.py --demo --no-voice > C:\\simcast-window.txt 2>&1" &)
sleep 75
DISPLAY=:77 import -window root "$OUT/simcast-under-wine.png" 2>/dev/null
check '[ -s "$OUT/simcast-under-wine.png" ]' "window screenshot under Wine: $OUT/simcast-under-wine.png"
kill $XPID 2>/dev/null
"$WINE" wineserver -k >/dev/null 2>&1 || true
mkdir -p "$USERDIR/AppData/Roaming/SimCast" && echo '{}' > "$USERDIR/AppData/Roaming/SimCast/config.json"
timeout 300 xvfb-run -a "$WINE" "$D/Uninstall SimCast.exe" /S >/dev/null 2>&1
sleep 5
check '[ ! -e "$D/SimCast.exe" ] && [ ! -e "$D/simcast" ]' "uninstalled"
check '[ -d "$USERDIR/AppData/Roaming/SimCast" ]' "settings kept after uninstalling"
[ "$fail" = 0 ] && echo PASSED || echo FAILED
exit $fail

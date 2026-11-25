#!/usr/bin/env bash
# Build the SimCoach-Setup.exe wizard from the repo with NSIS (makensis, Linux or Windows: apt install nsis) and check
# that every file inside it matches the repo byte for byte (7-Zip reads NSIS installers: apt install p7zip-full).
# Writes ./SimCoach-Setup.exe at the repo root.
#   tools/installer/build_installer.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
VERSION="$(tr -d '\r' < "$REPO/sim_coach.py" | sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p')"  # CRLF-safe (Windows checkouts)
[ -n "$VERSION" ] || { echo "APP_VERSION not found in sim_coach.py"; exit 1; }
IFS=. read -r a b c d <<<"$VERSION"; VIVERSION="${a:-0}.${b:-0}.${c:-0}.${d:-0}"
FILES=(sim_coach.py SimCoach.exe SimCoach.ico SimCoach.bat run_coach.bat bind_push_to_talk.bat README.txt)
cp "$REPO/installer-source/simcoach.nsi" "$REPO/installer-source/install.ps1" "$WORK/"
cp -r "$REPO/installer-source/art" "$WORK/art"
cp "$REPO/LICENSE" "$WORK/LICENSE.txt"
for f in "${FILES[@]}"; do cp "$REPO/$f" "$WORK/"; done
(cd "$WORK" && makensis -V2 -WX -DVERSION="$VERSION" -DVIVERSION="$VIVERSION" simcoach.nsi)
# what's inside must be exactly the repo's files
mkdir "$WORK/check"
7z x -y -o"$WORK/check" "$WORK/SimCoach-Setup.exe" >/dev/null
for f in "${FILES[@]}" install.ps1; do
  cmp -s "$WORK/$f" "$WORK/check/$f" || { echo "MISMATCH inside the installer: $f"; exit 1; }
done
cmp -s "$WORK/LICENSE.txt" "$WORK/check/LICENSE.txt" || { echo "MISMATCH inside the installer: LICENSE.txt"; exit 1; }
SIZE=$(wc -c < "$WORK/SimCoach-Setup.exe")
# SimCoach 6.x checks a downloaded update is at least 500 kB before running it
[ "$SIZE" -ge 500000 ] || { echo "installer is only $SIZE bytes: older SimCoach versions would refuse it as an update"; exit 1; }
cp "$WORK/SimCoach-Setup.exe" "$REPO/SimCoach-Setup.exe"
echo "Built $REPO/SimCoach-Setup.exe (SimCoach $VERSION wizard, $SIZE bytes); all $(( ${#FILES[@]} + 2 )) files inside match the repo."

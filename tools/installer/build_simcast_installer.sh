#!/usr/bin/env bash
# Build SimCast-Setup.exe (the setup wizard) from the repo with NSIS, and check every file inside it matches the
# repo byte for byte. Needs makensis and 7z (apt install nsis p7zip-full). Build SimCast.exe first
# (tools/launcher/build_launcher.sh). Writes ./SimCast-Setup.exe at the repo root.
#   tools/installer/build_simcast_installer.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' "$REPO/simcast/app.py")"
[ -n "$VERSION" ] || { echo "APP_VERSION not found in simcast/app.py"; exit 1; }
IFS=. read -r a b c d <<<"$VERSION"; VIVERSION="${a:-0}.${b:-0}.${c:-0}.${d:-0}"
FILES=(sim_cast.py SimCast.exe SimCast.ico SimCast.bat)
cp "$REPO/installer-source/simcast/simcast.nsi" "$REPO/installer-source/simcast/install.ps1" "$WORK/"
cp -r "$REPO/installer-source/simcast/art" "$WORK/art"
cp "$REPO/LICENSE" "$WORK/LICENSE.txt"
for f in "${FILES[@]}"; do cp "$REPO/$f" "$WORK/"; done
mkdir -p "$WORK/simcast/assets" "$WORK/simcast/licenses"
cp "$REPO"/simcast/*.py "$WORK/simcast/"
cp "$REPO"/simcast/assets/*.png "$WORK/simcast/assets/"
cp "$REPO"/simcast/licenses/*.txt "$WORK/simcast/licenses/"
(cd "$WORK" && makensis -V2 -WX -DVERSION="$VERSION" -DVIVERSION="$VIVERSION" simcast.nsi)
mkdir "$WORK/check"
7z x -y -o"$WORK/check" "$WORK/SimCast-Setup.exe" >/dev/null
n=0
for f in "${FILES[@]}" install.ps1 LICENSE.txt simcast/*.py simcast/assets/*.png simcast/licenses/*.txt; do
  (cd "$WORK" && cmp -s "$f" "check/$f") || { echo "MISMATCH inside the installer: $f"; exit 1; }
  n=$((n+1))
done
cp "$WORK/SimCast-Setup.exe" "$REPO/SimCast-Setup.exe"
echo "Built $REPO/SimCast-Setup.exe (SimCast $VERSION wizard, $(wc -c < "$WORK/SimCast-Setup.exe") bytes); all $n files inside match the repo."

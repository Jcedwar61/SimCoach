#!/usr/bin/env bash
# Build SimCast.exe (the windowless launcher) at the repo root with Go, the icon and version info embedded.
# Needs Go and go-winres:  go install github.com/tc-hib/go-winres@v0.3.3
#   tools/launcher/build_launcher.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
GO="${GO:-go}"; WINRES="${WINRES:-$(command -v go-winres || echo "$HOME/go/bin/go-winres")}"
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' "$REPO/simcast/app.py")"
[ -n "$VERSION" ] || { echo "APP_VERSION not found in simcast/app.py"; exit 1; }
IFS=. read -r a b c d <<<"$VERSION"; V4="${a:-0}.${b:-0}.${c:-0}.${d:-0}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp "$HERE/simcast/main.go" "$WORK/"
mkdir "$WORK/winres"
sed -e "s/VERSION4/$V4/g" -e "s/\"VERSION\"/\"$VERSION\"/g" "$HERE/simcast/winres.json" > "$WORK/winres/winres.json"
cp "$REPO/simcast/assets/icon-256.png" "$WORK/winres/icon.png"
cd "$WORK"
cat > go.mod <<MOD
module simcast-launcher

go 1.21
MOD
"$WINRES" make --arch amd64 >/dev/null
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 "$GO" build -trimpath -ldflags "-H windowsgui -s -w" -o SimCast.exe .
cp SimCast.exe "$REPO/SimCast.exe"
echo "Built $REPO/SimCast.exe (SimCast $VERSION launcher, $(wc -c < SimCast.exe) bytes)"

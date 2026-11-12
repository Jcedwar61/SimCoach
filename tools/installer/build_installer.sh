#!/usr/bin/env bash
# Build SimCoach-Setup.exe from the repo (needs Go 1.22+; cross-compiles from Linux/macOS too) and check that every
# file inside it matches the repo byte for byte. Writes ./SimCoach-Setup.exe at the repo root.
#   tools/installer/build_installer.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp "$REPO"/installer-source/{main.go,files.go,files_test.go,go.mod,rsrc_windows_amd64.syso} "$WORK/"
mkdir -p "$WORK/payload"
cp "$REPO"/installer-source/{install.ps1,uninstall.ps1} "$WORK/payload/"
cp "$REPO"/{sim_coach.py,README.txt,SimCoach.exe,SimCoach.ico,SimCoach.bat,run_coach.bat,bind_push_to_talk.bat} "$WORK/payload/"
cd "$WORK"
export GOTOOLCHAIN=local
go vet . && go test . >/dev/null
GOOS=windows GOARCH=amd64 go vet .
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-H windowsgui -s -w" -o SimCoach-Setup.exe .
"$PY" "$HERE/extract_payload.py" SimCoach-Setup.exe "$WORK/check" >/dev/null
for f in $(cd payload && ls); do
  cmp -s "payload/$f" "check/payload/$f" || { echo "MISMATCH inside the installer: $f"; exit 1; }
done
cp SimCoach-Setup.exe "$REPO/SimCoach-Setup.exe"
echo "Built $REPO/SimCoach-Setup.exe ($(wc -c < SimCoach-Setup.exe) bytes); all $(ls payload | wc -l) bundled files match the repo."

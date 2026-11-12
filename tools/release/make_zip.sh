#!/usr/bin/env bash
# Build the release zip (same layout as earlier releases) from a git ref, default origin/main, and check the
# installer inside it carries that ref's sim_coach.py.
#   tools/release/make_zip.sh [REF] [OUT.zip]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
PY="${PYTHON:-python3}"
REF="${1:-origin/main}"
cd "$REPO"; git fetch -q origin main || true
VER="$(git show "$REF:sim_coach.py" | sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p')"
OUT="${2:-$REPO/dist/SimCoach-v$VER-release.zip}"
WORK="$(mktemp -d)"; trap 'git -C "$REPO" worktree remove --force "$WORK/src" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
git worktree add -q --detach "$WORK/src" "$REF"
S="$WORK/src"; Z="$WORK/zip/SimCoach"
mkdir -p "$Z/SimCoachWeather" "$Z/installer-source" "$(dirname "$OUT")"
cp "$S"/{sim_coach.py,README.txt,SimCoach.exe,SimCoach-Setup.exe,SimCoach.ico,SimCoach.bat,run_coach.bat,bind_push_to_talk.bat,sample_coach_report.html,LICENSE} "$Z/"
cp "$S"/SimCoachWeather/* "$Z/SimCoachWeather/"; cp "$S"/installer-source/* "$Z/installer-source/"
"$PY" "$REPO/tools/installer/extract_payload.py" "$Z/SimCoach-Setup.exe" "$WORK/check" >/dev/null
cmp -s "$WORK/check/payload/sim_coach.py" "$Z/sim_coach.py" || { echo "The installer at $REF doesn't carry its sim_coach.py: rebuild it."; exit 1; }
rm -f "$OUT"; (cd "$WORK/zip" && zip -q -r -X "$OUT" SimCoach)
echo "Wrote $OUT (SimCoach $VER from $REF)"

#!/usr/bin/env bash
# Run SimCoach's tests. Each one uses a throwaway settings folder, never your real one.
#   tools/run_tests.sh             offline tests (about 3 minutes)
#   tools/run_tests.sh --gui       + the real app window (needs a display; on Linux: xvfb-run, python3-tk)
#   tools/run_tests.sh --network   + the update check against GitHub
# PYTHON=... picks the interpreter (needs numpy and openai; the window tests need tkinter).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"; GUI=0; NET=0
for a in "$@"; do case "$a" in --gui) GUI=1;; --network) NET=1;; esac; done
pass=0; fail=0; failed=()
run() {  # name, command...
  local name="$1"; shift
  local log; log="$(mktemp)"
  if "$@" >"$log" 2>&1; then pass=$((pass+1)); echo "PASS  $name"
  else fail=$((fail+1)); failed+=("$name"); echo "FAIL  $name"; grep -E "^FAIL |Traceback|Error" "$log" | head -8 | sed 's/^/        /'; fi
  rm -f "$log"
}
cd "$HERE/tests"
run "syntax (pyflakes)" bash -c "'$PY' -m pyflakes '$REPO/sim_coach.py' | grep -v 'imported but unused\|assigned to but never used\|redefinition of unused' | grep . && exit 1 || exit 0"
run "offline coaching run (--test)" bash -c "APPDATA=\$(mktemp -d) '$PY' '$REPO/sim_coach.py' --test --no-voice --no-mic --no-overlay"
for t in test_*.py; do run "${t%.py}" "$PY" "$t"; done
if [ "$NET" = 1 ]; then for t in net_test_*.py; do run "${t%.py}" "$PY" "$t"; done; fi
if [ "$GUI" = 1 ]; then
  if command -v xvfb-run >/dev/null && [ -z "${DISPLAY:-}" ]; then run "gui_test_app" xvfb-run -a -s "-screen 0 1280x900x24" "$PY" gui_test_app.py
  else run "gui_test_app" "$PY" gui_test_app.py; fi
fi
echo; echo "$pass passed, $fail failed${failed:+: ${failed[*]}}"
[ "$fail" = 0 ]

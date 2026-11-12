"""Check every lap in references/ the way SimCoach checks a download: a complete reference for the sim / track / car
in its file name, a clean (not provisional) lap, under 3 MB.     python tools/references/check_library.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "tests"))
from _common import load  # noqa: E402

sc = load()
folder = os.path.join(REPO, "references")
bad = n = 0
for f in sorted(os.listdir(folder)):
    if not f.endswith(".json"):
        continue
    n += 1
    path = os.path.join(folder, f)
    try:
        if os.path.getsize(path) > 3_000_000:
            raise ValueError("over 3 MB")
        d = json.load(open(path, encoding="utf-8"))
        prob = sc.ref_problem(d)
        if prob:
            raise ValueError(prob)
        if sc.library_file_name(d["key"]) != f:
            raise ValueError(f"file name should be {sc.library_file_name(d['key'])}")
        if d.get("provisional"):
            raise ValueError("provisional lap (had an off-track moment)")
        print(f"ok   {f}  ({sc.fmt_time(d['best_time']).replace(' ', ':')})")
    except Exception as e:
        bad += 1
        print(f"FAIL {f}: {e}")
print(f"{n} laps in the library, {bad} with problems")
sys.exit(1 if bad else 0)

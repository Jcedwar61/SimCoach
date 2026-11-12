"""Shared reference library (with a local stand-in for GitHub): exact-key lookups, checks on downloaded files,
and the coach flow: a library lap replaces the starter lap and is kept as the driver's reference until beaten."""
import json
import os
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, headless_coach, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()
lib = tempfile.mkdtemp(prefix="simcoach-test-library-")
KEY = ["ACC", "spa", "porsche_992_gt3_r"]


def lap_file(key, **extra):
    r = sc.starter_reference("Spa", "gt3")
    d = {"key": list(key), "ref": r["ref"], "best_time": 138.2, "corners": [list(c) for c in r["corners"]],
         "best_corner": {str(k): v for k, v in r["best_corner"].items()}, "saved": "2026-11-12 10:00",
         "provisional": False, "source": "library"}
    d.update(extra)
    return d


json.dump(lap_file(KEY), open(os.path.join(lib, sc.library_file_name(KEY)), "w"))
json.dump(lap_file(["ACC", "monza", "other_car"]), open(os.path.join(lib, sc.library_file_name(["ACC", "zolder", "x"])), "w"))
json.dump(lap_file(["ACC", "imola", "x"], provisional=True), open(os.path.join(lib, sc.library_file_name(["ACC", "imola", "x"])), "w"))


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=lib, **k)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}/"
sc.LIBRARY_URL = base

check(sc.library_file_name(KEY) == "ACC__spa__porsche_992_gt3_r.json", "file name = the reference's own name")
d = sc.fetch_library_lap(KEY, base=base)
check(d is not None and d["best_time"] == 138.2, "exact sim/track/car found")
check(sc.fetch_library_lap(["ACC", "spa", "another_car"], base=base) is None, "missing combination -> None")
for key, what in ((["ACC", "zolder", "x"], "a file for a different combination"), (["ACC", "imola", "x"], "a provisional lap")):
    try:
        sc.fetch_library_lap(key, base=base)
        check(False, f"{what} is refused")
    except ValueError:
        check(True, f"{what} is refused")


STORE = tempfile.mkdtemp(prefix="simcoach-test-refs-")


def session(cfg_extra=None, secs=8):
    cfg = sc.load_config()
    cfg.update(driver_name="Sam", **(cfg_extra or {}))
    cfg, voice, coach = headless_coach(sc, cfg)
    coach.store_dir = STORE                  # one reference folder, like the real app
    said = []
    voice.log = lambda m: said.append(m)
    for i in range(60 * secs):
        f = sc.Frame("ACC", "spa", "porsche_992_gt3_r", 0, 0.01, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 1.0, 0.0, True, False,
                     fuel=50.0, fuel_cap=100.0, track_len=7004, session="practice")
        coach.update(f, i / 60)
        if i == 30:
            time.sleep(1.0)            # the library download runs in the background
    return coach, said


coach, said = session()
check(any("starter lap for Spa" in m for m in said), "starter lap first")
check(coach.ref_source == "library" and coach.best_time == 138.2, "then the library lap replaces it")
check(any("SimCoach library" in m for m in said), "and says so")
saved = json.load(open(coach._path(), encoding="utf-8"))
check(saved.get("source") == "library" and not saved.get("provisional"), "kept locally, marked as a library lap")
coach2, said2 = session()
check(coach2.ref_source == "library" and any("your best here is" in m for m in said2), "next time it loads from disk")
os.remove(coach._path())
coach3, said3 = session({"shared_refs": False})
check(coach3.ref_source == "starter", "library switched off: starter lap only")
done()

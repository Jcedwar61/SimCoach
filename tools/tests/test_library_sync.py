"""Automatic library sync (with a local stand-in for GitHub's folder listing): new shared laps are added, changed
library laps are updated, unchanged ones aren't downloaded again, bad files are skipped, the driver's own laps are
never replaced, and a lap that arrives for the combination being driven is adopted and announced."""
import hashlib
import json
import os
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, headless_coach, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()
lib = tempfile.mkdtemp(prefix="simcoach-test-library-")
STORE = tempfile.mkdtemp(prefix="simcoach-test-refs-")
fetched = []


def lap(key, t=138.2, **extra):
    r = sc.starter_reference("Spa", "gt3")
    d = {"key": list(key), "ref": r["ref"], "best_time": t, "corners": [list(c) for c in r["corners"]],
         "best_corner": {str(k): v for k, v in r["best_corner"].items()}, "saved": "2026-11-12 10:00",
         "provisional": False, "source": "library"}
    d.update(extra)
    return d


def put(key, name=None, **kw):
    with open(os.path.join(lib, name or sc.library_file_name(key)), "w") as fh:
        json.dump(lap(key, **kw), fh)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=lib, **k)

    def do_GET(self):
        if self.path == "/api":
            base = f"http://127.0.0.1:{self.server.server_port}/"
            items = [{"name": n, "type": "file", "size": os.path.getsize(os.path.join(lib, n)),
                      "sha": hashlib.sha1(open(os.path.join(lib, n), "rb").read()).hexdigest(),
                      "download_url": base + n} for n in sorted(os.listdir(lib))]
            items.append({"name": "README.md", "type": "file", "size": 10, "sha": "x", "download_url": base + "README.md"})
            body = json.dumps(items).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        fetched.append(self.path.lstrip("/"))
        super().do_GET()

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_port}/api"

A = ("ACC", "spa", "porsche_992_gt3_r")
B = ("iRacing", "monza full", "bmw m4 gt3")
C = ("ACC", "imola", "x")                    # provisional: refused
D = ("ACC", "zolder", "x")                   # file named for D but holds another combination: refused
E = ("LMU", "le mans", "hypercar")           # the driver already has their own lap here
put(A)
put(B, t=108.4)
put(C, provisional=True)
put(("ACC", "monza", "other"), name=sc.library_file_name(D))
put(E, t=200.0)
own_e = lap(E, t=215.0, source="own")
json.dump(own_e, open(os.path.join(STORE, sc.library_file_name(E)), "w"))

cfg, voice, coach = headless_coach(sc)
coach.store_dir = STORE
said = []
voice.log = lambda m: said.append(m)
logs = []
seen = {}

added, updated = sc.sync_library(coach, seen, STORE, api=API, log=logs.append)
check(sorted(added) == sorted([A, B]) and not updated, f"new library laps added ({added})")
check(json.load(open(os.path.join(STORE, sc.library_file_name(B))))["source"] == "library", "saved as library laps")
check(not os.path.exists(os.path.join(STORE, sc.library_file_name(C))), "provisional lap skipped")
check(not os.path.exists(os.path.join(STORE, sc.library_file_name(D))), "mismatched file skipped")
check(json.load(open(os.path.join(STORE, sc.library_file_name(E))))["best_time"] == 215.0, "driver's own lap untouched")
check(sc.library_file_name(E) not in fetched, "own lap's library copy not even downloaded")
check(len(seen) == 5 and "README.md" not in seen, "every lap remembered (not the README)")

fetched.clear()
added, updated = sc.sync_library(coach, seen, STORE, api=API, log=logs.append)
check(not added and not updated and not fetched, "nothing changed: nothing downloaded")

put(B, t=107.9)
added, updated = sc.sync_library(coach, seen, STORE, api=API, log=logs.append)
check(updated == [B] and not added, "a faster lap shared to the library updates the library copy")
check(json.load(open(os.path.join(STORE, sc.library_file_name(B))))["best_time"] == 107.9, "new time saved")

# driving a combination on the starter lap when its library lap arrives
F = ("ACC", "spa", "ferrari_296_gt3")
for i in range(60):
    coach.update(sc.Frame("ACC", "spa", "ferrari_296_gt3", 0, 0.01, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 1.0, 0.0, True, False,
                          fuel=50.0, fuel_cap=100.0, track_len=7004, session="practice"), i / 60)
check(coach.key == F and coach.ref_source in (None, "starter"), f"driving F on {coach.ref_source}")
put(F, t=139.1)
added, updated = sc.sync_library(coach, seen, STORE, api=API, log=logs.append)
check(added == [F] and coach.ref_source == "library" and coach.best_time == 139.1, "arriving lap adopted at once")
check(any("just arrived from the SimCoach library" in m for m in said), "and the coach says so")

# the driver's own lap in memory (not yet on disk) for the combination being driven isn't replaced
coach.ref_source = "own"
coach.best_time = 140.0
put(F, t=138.0)
added, updated = sc.sync_library(coach, seen, STORE, api=API, log=logs.append)
check(not added and not updated and coach.best_time == 140.0, "own lap being driven is kept")

# a lap taken out of the library is removed locally; the driver's own laps and the lap being driven stay
os.remove(os.path.join(lib, sc.library_file_name(B)))
os.remove(os.path.join(lib, sc.library_file_name(E)))
os.remove(os.path.join(lib, sc.library_file_name(F)))
sc.sync_library(coach, seen, STORE, api=API, log=logs.append)
check(not os.path.exists(os.path.join(STORE, sc.library_file_name(B))), "lap removed from the library is removed here")
check(os.path.exists(os.path.join(STORE, sc.library_file_name(E))), "the driver's own lap stays")
check(os.path.exists(os.path.join(STORE, sc.library_file_name(F))), "the lap being driven stays")
check(sc.library_file_name(B) not in seen, "and it's forgotten, so a re-added lap is imported again")
done()

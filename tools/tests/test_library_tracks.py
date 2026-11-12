"""Starter-lap track shapes from the library (references/tracks/, local stand-in for GitHub): downloaded, checked,
used for a starter lap on a track SimCoach doesn't have built in, and removed when taken out of the library."""
import hashlib
import json
import os
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, headless_coach, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()
lib = tempfile.mkdtemp(prefix="simcoach-test-tracks-")
sc.TRACK_DIR = tempfile.mkdtemp(prefix="simcoach-test-trackdir-")
L, steps = sc._starter_data()["Spa"]


def track(tid, **kw):
    d = {"id": tid, "spoken": "Test Ring", "phrases": ["test ring"], "length": 6000.0, "steps": list(steps)}
    d.update(kw)
    return d


def put(name, d):
    json.dump(d, open(os.path.join(lib, name), "w"))


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=lib, **k)

    def do_GET(self):
        if self.path == "/api/tracks":
            base = f"http://127.0.0.1:{self.server.server_port}/"
            body = json.dumps([{"name": n, "type": "file", "size": os.path.getsize(os.path.join(lib, n)),
                                "sha": hashlib.sha1(open(os.path.join(lib, n), "rb").read()).hexdigest(),
                                "download_url": base + n} for n in sorted(os.listdir(lib))]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/none/tracks":
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_port}/api"

check(sc.track_file_problem(track("TestRing")) is None, "good track file accepted")
for what, bad in (("short data", track("X1", steps=[0] * 10)), ("wild curvature", track("X2", steps=[30000] + [0] * 1999)),
                  ("bad phrase", track("X3", phrases=["Te$t"])), ("silly length", track("X4", length=5.0))):
    check(sc.track_file_problem(bad) is not None, f"{what} refused")

check(sc.sync_library_tracks({}, api=f"http://127.0.0.1:{srv.server_port}/none") == [], "no tracks folder in the library: fine")
put("TestRing.json", track("TestRing"))
put("Bad.json", track("Bad", steps=[0] * 10))
put("Other.json", track("Mismatch"))
put("Spa.json", track("Spa", spoken="Fake Spa", phrases=["test ring"], length=6000.0))
seen = {}
got = sc.sync_library_tracks(seen, api=API, log=lambda m: None)
check(got == ["Test Ring"] and os.listdir(sc.TRACK_DIR) == ["TestRing.json"],
      f"valid tracks downloaded, bad ones skipped ({got})")
check("TestRing" in sc.starter_tracks() and sc.starter_tracks()["Spa"][0] == "Spa", "added to the starter tracks; built-in ones win")
check(sc.starter_track("ACC", "Test Ring GP", 6050) == "TestRing", "matched by name and length")
check(sc.starter_track("ACC", "Test Ring GP", 4000) is None, "another layout (length) not matched")
check(sc.sync_library_tracks(seen, api=API, log=lambda m: None) == [], "unchanged: nothing downloaded")

cfg, voice, coach = headless_coach(sc)
said = []
voice.log = lambda m: said.append(m)
for i in range(120):
    coach.update(sc.Frame("ACC", "Test Ring GP", "bmw_m4_gt3", 0, 0.01, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 1.0, 0.0, True, False,
                          fuel=50.0, fuel_cap=100.0, track_len=6000, session="practice"), i / 60)
check(coach.ref_source == "starter" and any("starter lap for Test Ring" in m for m in said), "starter lap from a library track")

os.remove(os.path.join(lib, "TestRing.json"))
sc.sync_library_tracks(seen, api=API, log=lambda m: None)
check("TestRing" not in sc.starter_tracks() and "TestRing.json" not in os.listdir(sc.TRACK_DIR), "removed from the library: removed here")
done()

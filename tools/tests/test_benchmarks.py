"""Benchmark lap times: starter laps are tuned to a real quick GT3 lap, the coach quotes the target, tracks without a
starter lap still get a target, and the library's benchmark file is checked and picked up (local stand-in)."""
import json
import os
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, headless_coach, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()
sc.BENCH_PATH = os.path.join(tempfile.mkdtemp(), "benchmarks_gt3.json")

b = sc.benchmarks()
check(sc.bench_problem(b) is None and "Spa" in b["tracks"], "built-in benchmarks are valid")
for tid in ("Spa", "Monza", "Catalunya", "Sakhir"):
    r = sc.starter_reference(tid, "gt3")
    check(abs(r["best_time"] - b["tracks"][tid]) < 0.15, f"{tid}: GT3 starter lap tuned to the benchmark ({r['best_time']:.1f} s)")
g4, g3, f1 = (sc.starter_reference("Spa", c)["best_time"] for c in ("gt4", "gt3", "f1"))
check(f1 < g3 < g4, "other classes keep their order at a tuned track")
check(sc._GRIP.get("Silverstone", 1.0) == 1.0 and sc.starter_reference("Silverstone", "gt3"), "no benchmark: untouched")
sc.benchmarks()["tracks"]["Zandvoort"] = 60.0
sc._GRIP.clear()
sc.starter_reference("Zandvoort", "gt3")
check(sc._GRIP["Zandvoort"] == 1.0, "a benchmark far from the calculation (another layout) is ignored")
sc.benchmarks_changed()

check(sc.benchmark_time("iRacing", "Road Atlanta - Full Course", 4088) == (78.395, "Road Atlanta"), "track without a starter lap")
check(sc.benchmark_time("ACC", "Nurburgring Nordschleife", 20832)[0] == 394.067
      and sc.benchmark_time("ACC", "Nurburgring 24h", 25378)[0] == 506.535, "layouts told apart by length")
check(sc.benchmark_time("ACC", "Silverstone", 5891) is None, "Silverstone GP isn't given the National time")


def first_words(track, length, car="Porsche 911 GT3 R (992)"):
    cfg, voice, coach = headless_coach(sc)
    said = []
    voice.log = lambda m: said.append(m)
    for i in range(60):
        coach.update(sc.Frame("ACC", track, car, 0, 0.01, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 1.0, 0.0, True, False,
                              fuel=50.0, fuel_cap=100.0, track_len=length, session="practice"), i / 60)
    return " ".join(said)


check("A quick GT3 lap here is about 2 16.4" in first_words("spa", 7004), "starter lap announcement quotes the target")
check("quick GT3 lap" not in first_words("spa", 7004, car="Mazda MX-5 Cup"), "not quoted for other classes")
t = first_words("Road Atlanta", 4088)
check("A quick GT3 lap at Road Atlanta is about 1 18.4" in t and "Give me a clean lap" in t, f"target without a starter lap ({t[:90]})")

# the library's file
lib = tempfile.mkdtemp()
os.makedirs(os.path.join(lib, "benchmarks"))


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=lib, **k)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}/"
check(sc.sync_library_benchmarks(base=base) is False, "no benchmark file in the library: fine")
new = {"tracks": {"Spa": 135.0}, "other": []}
json.dump(new, open(os.path.join(lib, "benchmarks", "gt3.json"), "w"))
check(sc.sync_library_benchmarks(base=base) is True and sc.benchmarks()["tracks"] == {"Spa": 135.0}, "library benchmarks picked up")
check(abs(sc.starter_reference("Spa", "gt3")["best_time"] - 135.0) < 0.15, "and starter laps re-tuned")
check(sc.sync_library_benchmarks(base=base) is False, "unchanged: no change")
json.dump({"tracks": {"Spa": 5}}, open(os.path.join(lib, "benchmarks", "gt3.json"), "w"))
check(sc.sync_library_benchmarks(base=base, log=lambda m: None) is False and sc.benchmarks()["tracks"]["Spa"] == 135.0,
      "a bad file is ignored")
done()

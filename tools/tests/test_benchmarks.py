"""Benchmark lap times by sim and class: starter laps are tuned to them, the coach quotes the target, tracks without
a starter lap still get a target, and the library's benchmark file is checked and picked up (local stand-in)."""
import json
import os
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from _common import check, done, headless_coach, load

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sc = load()
sc.BENCH_PATH = os.path.join(tempfile.mkdtemp(), "benchmarks.json")
here = os.path.dirname(os.path.abspath(__file__))

b = sc.benchmarks()
check(sc.bench_problem(b) is None and len(b["laps"]) > 50, "built-in benchmarks are valid")
lib_file = json.load(open(os.path.join(here, "..", "..", "references", "benchmarks", "laps.json"), encoding="utf-8"))
check(sc.bench_problem(lib_file) is None and lib_file["laps"] == b["laps"] and lib_file["tracks"] == b["tracks"],
      "the library's file matches the built-in copy")

PORSCHE = "Porsche 911 GT3 R (992)"
check(sc.benchmark_lap("ACC", PORSCHE, "gt3", "Spa") == (136.434, False), "ACC GT3 Spa: ACC's own time")
check(sc.benchmark_lap("LMU", "Ferrari 296 LMGT3", "gt3", "Spa") == (137.732, False), "LMU GT3 Spa: LMU's own time")
check(sc.benchmark_lap("AC", "ks_porsche_911_gt3_r", "gt3", "Spa") == (136.4, False), "a sim without its own time: the general one")
check(sc.benchmark_lap("iRacing", "Porsche 963 GTP", "proto", "Montreal") == (83.647, True), "a time for the car itself")
check(sc.benchmark_lap("iRacing", "Ligier JS P320", "proto", "Montreal") is None, "another car of the class: none here")
check(sc.benchmark_lap("ACC", PORSCHE, "gt4", "Spa") is None, "no time for the class")
check(sc.benchmark_lap("RaceRoom", "car 123", "gt3", "Spa") is None, "RaceRoom (no car names): none")

for game, tid in (("ACC", "Spa"), ("LMU", "Monza"), ("iRacing", "Montreal"), ("AMS2", "SaoPaulo")):
    grip, bench = sc.starter_grip(tid, game, PORSCHE, "gt3")
    r = sc.starter_reference(tid, "gt3", grip=grip)
    check(bench and abs(r["best_time"] - bench[0]) < 0.2, f"{game} {tid}: GT3 starter lap tuned to {bench[0]:.1f} s (grip {grip:.2f})")
grip, bench = sc.starter_grip("Spa", "F1 25", "McLaren", "f1")
check(bench and abs(sc.starter_reference("Spa", "f1", grip=grip)["best_time"] - bench[0]) < 0.2, "F1 at Spa tuned to the F1 time")
g4, bench4 = sc.starter_grip("Spa", "ACC", "Porsche 718 Cayman GT4", "gt4")
g3, _ = sc.starter_grip("Spa", "ACC", PORSCHE, "gt3")
check(bench4 is None and g4 == g3 != 1.0, "a class without a time gets the track's GT3 correction, and no quoted target")
grip, bench = sc.starter_grip("Monza", "iRacing", "Porsche 919 Hybrid", "proto")
check(grip == 1.0 and bench == (88.594, True), "a time the car model can't reach is quoted but not tuned to")
check(sc.starter_grip("Silverstone", "AC EVO", PORSCHE, "gt3") == (1.0, None), "no benchmark: untouched")

check(sc.benchmark_track("iRacing", "Road Atlanta - Full Course", 4088) == ("RoadAtlanta", "Road Atlanta"), "track without a starter lap")
check(sc.benchmark_track("ACC", "Nurburgring Nordschleife", 20832)[0] == "Nordschleife"
      and sc.benchmark_track("ACC", "nurburgring_24h", 25378)[0] == "Nurburgring24h", "layouts told apart by length")
check(sc.benchmark_track("ACC", "Silverstone", 5891) is None, "Silverstone GP isn't taken for the National layout")
check(sc.benchmark_track("iRacing", "Indianapolis Motor Speedway - Road Course", 3925)[0] == "IndianapolisRoad"
      and sc.benchmark_track("ACC", "indianapolis", 4167)[0] == "IndianapolisGP", "two Indianapolis layouts")


def first_words(game, track, length, car=PORSCHE):
    cfg, voice, coach = headless_coach(sc)
    said = []
    voice.log = lambda m: said.append(m)
    for i in range(60):
        coach.update(sc.Frame(game, track, car, 0, 0.01, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 1.0, 0.0, True, False,
                              fuel=50.0, fuel_cap=100.0, track_len=length, session="practice"), i / 60)
    return " ".join(said), coach


t, coach = first_words("ACC", "spa", 7004)
check("A quick GT3 lap here is about 2 16.4" in t, "starter lap announcement quotes the sim's target")
check(abs(coach.best_time - 136.434) < 0.2, "and the starter lap in use is the tuned one")
t, _ = first_words("ACC", "spa", 7004, car="Mazda MX-5 Cup")
check("A quick" not in t, "no target for a class without one")
t, _ = first_words("iRacing", "Circuit Gilles Villeneuve", 4361, car="Ferrari 499P")
check("A quick lap in this car here is about 1 24.0" in t, f"car-specific target ({t[60:200]})")
t, _ = first_words("ACC", "Laguna Seca", 3602)
check("A quick GT3 lap at Laguna Seca is about 1 21.3" in t and "Give me a clean lap" in t, "target without a starter lap")

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
new = {"tracks": {}, "laps": [["ACC", "gt3", "Spa", 135.0, None, "test"]]}
json.dump(new, open(os.path.join(lib, "benchmarks", "laps.json"), "w"))
check(sc.sync_library_benchmarks(base=base) is True and sc.benchmark_lap("ACC", PORSCHE, "gt3", "Spa") == (135.0, False),
      "library benchmarks picked up")
grip, bench = sc.starter_grip("Spa", "ACC", PORSCHE, "gt3")
check(abs(sc.starter_reference("Spa", "gt3", grip=grip)["best_time"] - 135.0) < 0.2, "and starter laps re-tuned")
check(sc.sync_library_benchmarks(base=base) is False, "unchanged: no change")
json.dump({"tracks": {}, "laps": [["ACC", "gt3", "Spa", 5, None, "x"]]}, open(os.path.join(lib, "benchmarks", "laps.json"), "w"))
check(sc.sync_library_benchmarks(base=base, log=lambda m: None) is False
      and sc.benchmark_lap("ACC", PORSCHE, "gt3", "Spa") == (135.0, False), "a bad file is ignored")
done()

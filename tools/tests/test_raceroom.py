"""RaceRoom car names: the model id from shared memory becomes the car's real name and class, benchmarks and
starter-lap classes work there, and references saved under the old 'car <id>' name are moved to the new one."""
import json
import os

from _common import check, done, headless_coach, load

sc = load()
by_id, by_name = sc._raceroom()
check(len(by_id) >= 350 and len(by_id) == len(by_name), f"{len(by_id)} RaceRoom cars, every name unique")
check(sc.raceroom_car(1738).startswith("BMW Z4 GT3"), f"model 1738 -> {sc.raceroom_car(1738)}")
check(sc.raceroom_car(99999999) == "car 99999999", "a car newer than the table keeps its number")
Z4 = sc.raceroom_car(1738)
check(sc.car_class("RaceRoom", Z4) == "gt3", "a GTR 3 car is a GT3 car")
classes = {}
for cid, (name, cls) in by_id.items():
    classes.setdefault(cls, []).append(name)
check(all(classes.get(c) for c in ("gt3", "gt4", "gte", "proto", "formula", "cup", "road")), "every car class has RaceRoom cars")
gt4 = next(n for n in classes["gt4"] if "GT4" in n)
check(sc.car_class("RaceRoom", gt4) == "gt4", f"a GT4 car: {gt4}")
unknown = next((n for n, (_i, c) in by_name.items() if c is None), None)
check(unknown is not None and sc.car_class("RaceRoom", unknown) == "gt3", "an unusual class falls back to GT3 for the starter lap")

check(sc.benchmark_lap("RaceRoom", Z4, "gt3", "Hockenheim") == (97.522, False), "a known RaceRoom car gets target times")
check(sc.benchmark_lap("RaceRoom", unknown, "gt3", "Hockenheim") is None, "a car in an unknown class gets none")
check(sc.benchmark_lap("RaceRoom", "car 99999999", "gt3", "Hockenheim") is None, "nor does an unknown car")

# a reference saved by an older version as 'car 1738' is adopted under the car's name
cfg, voice, coach = headless_coach(sc)
r = sc.starter_reference("Hockenheim", "gt3")
old_key = ["RaceRoom", "Hockenheimring Grand Prix", "car 1738"]
d = {"key": old_key, "ref": r["ref"], "best_time": 99.9, "corners": [list(c) for c in r["corners"]],
     "best_corner": {str(k): v for k, v in r["best_corner"].items()}, "saved": "2026-10-01 10:00", "provisional": False,
     "source": "own"}
old_path = os.path.join(coach.store_dir, sc.library_file_name(old_key))
os.makedirs(coach.store_dir, exist_ok=True)
json.dump(d, open(old_path, "w"))
json.dump([{"date": "2026-10-01", "best": 99.9, "laps": 8}], open(old_path.replace(".json", ".sessions.json"), "w"))
said = []
voice.log = lambda m: said.append(m)
for i in range(60):
    coach.update(sc.Frame("RaceRoom", "Hockenheimring Grand Prix", Z4, 0, 0.01, 0.0, 0.0, 0.0, 0.0, 0, 900.0, 1.0, 0.0, True, False,
                          fuel=50.0, fuel_cap=100.0, track_len=4574, session="practice"), i / 60)
check(coach.ref_source == "own" and coach.best_time == 99.9, "the old reference is loaded under the car's name")
check(not os.path.exists(old_path) and os.path.exists(coach._path()), "and its file is renamed")
check(json.load(open(coach._path()))["key"][2] == Z4, "with the car's name inside")
check(len(coach.past_sessions()) == 1, "its session history comes along")
check(any("your best here is" in m for m in said), "the coach greets with the saved best")
tg = coach.target()
check(tg and tg[2] == "gt3", f"and has a target for it ({tg})")
done()

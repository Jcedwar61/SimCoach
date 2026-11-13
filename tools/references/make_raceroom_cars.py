"""Rebuild the RaceRoom car table in sim_coach.py (RACEROOM_CARS_B64): car model id -> [car name, class name].

RaceRoom's shared memory only gives a car's numeric model id. The names come from Sector3 Studios' own data file,
r3e-data.json (https://github.com/sector3studios/r3e-spectator-overlay).

    curl -L -o /tmp/r3e-data.json https://raw.githubusercontent.com/sector3studios/r3e-spectator-overlay/master/r3e-data.json
    python tools/references/make_raceroom_cars.py /tmp/r3e-data.json
"""
import base64
import json
import os
import re
import sys
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    classes = {int(k): v["Name"] for k, v in d["classes"].items()}
    cars = {str(int(k)): [v["Name"], classes.get(v.get("Class"), "")] for k, v in sorted(d["cars"].items(), key=lambda kv: int(kv[0]))}
    blob = base64.b64encode(zlib.compress(json.dumps(cars, separators=(",", ":"), ensure_ascii=False).encode(), 9)).decode()
    lines = [blob[i:i + 116] for i in range(0, len(blob), 116)]
    block = "RACEROOM_CARS_B64 = (\n" + "\n".join(f'    "{ln}"' for ln in lines) + "\n)\n"
    p = os.path.join(REPO, "sim_coach.py")
    s = open(p, encoding="utf-8", newline="").read()
    new, n = re.subn(r"RACEROOM_CARS_B64 = \(\n.*?\n\)\n", lambda m: block, s, count=1, flags=re.S)
    if n != 1:
        sys.exit("RACEROOM_CARS_B64 block not found in sim_coach.py")
    open(p, "w", encoding="utf-8", newline="").write(new)
    print(f"{len(cars)} RaceRoom cars, {len(blob)} characters embedded in sim_coach.py")


if __name__ == "__main__":
    main(sys.argv[1])

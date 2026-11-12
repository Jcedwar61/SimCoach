"""Write the library's benchmark lap times (references/benchmarks/laps.json) and the copy built into sim_coach.py.

The times are quick, repeatable laps collected by the library owner (November 2026) from setup shops, leaderboards
and league results; the source of each is in the table. They are lap times only (no telemetry).

    python tools/references/make_benchmarks.py
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def t(x):
    m, s = x.split(":")
    return round(int(m) * 60 + float(s), 3)


# tracks SimCoach has no starter lap for: id -> (spoken, phrases in the sim's track name, length m)
TRACKS = {
    "Nordschleife": ("the Nordschleife", ["nordschleife"], 20832),
    "Nurburgring24h": ("the Nürburgring 24 hour layout", ["nordschleife", "nurburgring", "24h"], 25378),
    "LeMans": ("Le Mans", ["le mans", "sarthe"], 13626),
    "RoadAtlanta": ("Road Atlanta", ["road atlanta", "atlanta"], 4088),
    "Fuji": ("Fuji", ["fuji"], 4563),
    "DaytonaRoad": ("the Daytona road course", ["daytona"], 5730),
    "Jerez": ("Jerez", ["jerez"], 4428),
    "Zhuhai": ("Zhuhai", ["zhuhai"], 4319),
    "Bathurst": ("Bathurst", ["bathurst", "mount panorama", "panorama"], 6213),
    "SilverstoneNational": ("Silverstone National", ["silverstone"], 2639),
    "Silverstone2008": ("the old Silverstone Grand Prix layout", ["silverstone"], 5141),
    "IndianapolisRoad": ("the Indianapolis road course", ["indianapolis", "indy"], 3925),
    "IndianapolisGP": ("Indianapolis", ["indianapolis", "indy"], 4170),
    "TheBend": ("The Bend", ["the bend", "bend motorsport"], 7770),
    "Motegi": ("Motegi", ["motegi"], 4801),
    "CharlotteRoval": ("the Charlotte Roval", ["charlotte"], 3670),
    "Misano": ("Misano", ["misano"], 4226),
    "Zolder": ("Zolder", ["zolder"], 4011),
    "Donington": ("Donington", ["donington"], 4020),
    "LagunaSeca": ("Laguna Seca", ["laguna seca", "laguna"], 3602),
    "OultonPark": ("Oulton Park", ["oulton"], 4307),
    "Snetterton": ("Snetterton", ["snetterton"], 4779),
    "Valencia": ("Valencia", ["valencia", "ricardo tormo"], 4005),
    "LongBeach": ("Long Beach", ["long beach"], 3167),
    "Sebring": ("Sebring", ["sebring"], 6019),
    "MidOhio": ("Mid-Ohio", ["mid ohio"], 3634),
    "RoadAmerica": ("Road America", ["road america"], 6515),
}

SRA = "SimRacingAlliance D1 reference"
LAPS = []   # [sim ("*" = any), class, track id, seconds, car phrases or None, source]


def add(sim, cls, src, rows, car=None):
    for track, lap in rows.items():
        LAPS.append([sim, cls, track, t(lap), car, src])


add("ACC", "gt3", SRA, {
    "Catalunya": "1:42.782", "BrandsHatch": "1:22.500", "Austin": "2:04.607", "Donington": "1:25.910",
    "Budapest": "1:42.443", "Imola": "1:39.949", "IndianapolisGP": "1:34.863", "Kyalami": "1:39.805",
    "LagunaSeca": "1:21.301", "Misano": "1:32.698", "Monza": "1:46.711", "Bathurst": "1:59.575",
    "Nurburgring24h": "8:10.000", "Nuerburgring": "1:53.255", "OultonPark": "1:32.485", "PaulRicard": "1:52.906",
    "Spielberg": "1:27.629", "Silverstone": "1:56.848", "Snetterton": "1:45.596", "Spa": "2:16.434",
    "Suzuka": "1:58.666", "Valencia": "1:29.735", "WatkinsGlen": "1:43.244", "Zandvoort": "1:34.706",
    "Zolder": "1:27.578"})
add("iRacing", "gt3", "HYMO Setups / Apex Racing Academy / Coach Dave Academy reference", {
    "Montreal": "1:32.329", "TheBend": "2:53.188", "Spielberg": "1:28.303", "Motegi": "1:49.400",
    "IndianapolisRoad": "1:22.441"})
add("iRacing", "gt4", "HYMO Setups reference", {"CharlotteRoval": "1:20.841"})
add("iRacing", "proto", "HYMO Setups reference", {"CharlotteRoval": "1:10.812"}, ["p320", "lmp3"])
for car, lap in ((["valkyrie"], "1:23.397"), (["arx"], "1:23.518"), (["963"], "1:23.647"), (["499p"], "1:23.965"),
                 (["p217", "lmp2"], "1:28.416")):
    add("iRacing", "proto", "HYMO Setups reference", {"Montreal": lap}, car)
add("iRacing", "proto", "iRacing track record (Fernando Horta database)", {
    "Silverstone2008": "1:27.084", "WatkinsGlen": "1:24.103", "Mugello": "1:20.869", "SaoPaulo": "1:15.906",
    "Monza": "1:28.594"}, ["919"])
add("AC", "gt3", "Track Titan top lap", {"Nordschleife": "6:26.232"})
add("rFactor 2", "gt3", "league result (Simresults)", {"Monza": "1:49.094"})
add("rFactor 2", "gte", "rFactor 2 record (Fernando Horta database)", {"MidOhio": "1:25.398", "Sebring": "2:03.310"}, ["c6"])
add("AMS2", "gt3", "AMS2 leaderboards (GT3 Gen2)", {
    "SaoPaulo": "1:26.236", "Catalunya": "1:40.162", "Monza": "1:46.433", "Jerez": "1:35.721",
    "BrandsHatch": "1:22.152", "DaytonaRoad": "1:42.303"})
add("AMS2", "formula", "AMS2 leaderboard", {"RoadAmerica": "1:49.925"}, ["reynard"])
add("LMU", "gt3", "LMU leaderboards and race results", {
    "Spa": "2:17.732", "Imola": "1:42.355", "Fuji": "1:39.981", "SaoPaulo": "1:31.039", "LeMans": "3:53.398",
    "Monza": "1:49.815", "LongBeach": "1:20.969", "Sakhir": "1:58.476"})
add("LMU", "proto", "LMU / WEC reference", {"LeMans": "3:22.564"})
add("LMU", "proto", "LMU leaderboard", {"Sakhir": "1:44.586"}, ["cadillac", "v series"])
add("F1 25", "f1", "F1 24 time trial, top 5 % (SimRacingSetup)", {"Spa": "1:41.749", "Monza": "1:18.950", "Zandvoort": "1:09.100"})
add("*", "gt3", "GT3 leaderboards (sim not recorded)", {
    "Spa": "2:16.400", "Monza": "1:46.350", "Suzuka": "1:57.475", "Spielberg": "1:26.867", "Catalunya": "1:40.162",
    "SaoPaulo": "1:26.236", "Imola": "1:43.364", "Mugello": "1:47.222", "Nuerburgring": "1:55.416",
    "Hockenheim": "1:37.522", "Oschersleben": "1:21.160", "BrandsHatch": "1:22.152", "Sakhir": "1:58.476",
    "RoadAtlanta": "1:18.395", "Nordschleife": "6:34.067", "Zhuhai": "1:32.485", "Bathurst": "2:04.202",
    "Fuji": "1:41.488", "DaytonaRoad": "1:47.282", "SilverstoneNational": "0:52.620", "Jerez": "1:35.721"})

data = {"about": "Quick, repeatable lap times by sim and car class (lap times only, no telemetry). SimCoach tunes its "
                 "calculated starter laps to them and quotes them as a target. laps: [sim (* = any), class, track id, "
                 "seconds, car-name phrases or null, source]. tracks: tracks without a starter lap (spoken name, "
                 "phrases in the sim's track name, length m); other ids are starter-lap tracks.",
        "tracks": {k: {"spoken": v[0], "phrases": v[1], "length": v[2]} for k, v in TRACKS.items()},
        "laps": LAPS}
out = os.path.join(REPO, "references", "benchmarks", "laps.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    fh.write("{\n \"about\": " + json.dumps(data["about"]) + ",\n \"tracks\": {\n"
             + ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in data["tracks"].items())
             + "\n },\n \"laps\": [\n" + ",\n".join("  " + json.dumps(x, ensure_ascii=False) for x in LAPS) + "\n ]\n}\n")
emb = json.dumps({"tracks": data["tracks"], "laps": LAPS}, ensure_ascii=True, separators=(",", ":"))
lines = [emb[i:i + 108] for i in range(0, len(emb), 108)]
block = "STARTER_BENCH = json.loads(\"\".join((\n" + "\n".join("    " + json.dumps(x) + "," for x in lines) + "\n)))\n"
p = os.path.join(REPO, "sim_coach.py")
s = open(p, encoding="utf-8", newline="").read()
new, n = re.subn(r"STARTER_BENCH = json\.loads\(\"\"\.join\(\(?\n.*?\n\)\)\)?\n", lambda m: block, s, count=1, flags=re.S)
assert n == 1, "STARTER_BENCH block not found"
open(p, "w", encoding="utf-8", newline="").write(new)
print(f"{len(LAPS)} benchmark laps, {len(TRACKS)} extra tracks")

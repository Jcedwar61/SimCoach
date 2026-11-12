"""iRacing reader against a synthetic SDK memory image built to the documented layout: header, 144-byte
variable descriptions, three rotating buffers (newest in the middle) and a session YAML with a pace car and a
spectator. Then frames go through the coach and crew like the live loop."""
import struct
import tempfile

from _common import check, done, headless_coach, load

sc = load()
YAML = """---
WeekendInfo:
 TrackName: spa 2024 bumpy
 TrackDisplayName: Circuit de Spa-Francorchamps
 TrackLength: 6.93 km
SessionInfo:
 Sessions:
 - SessionNum: 0
   SessionLaps: unlimited
   SessionTime: 600.0000 sec
   SessionType: Practice
 - SessionNum: 1
   SessionLaps: 12
   SessionTime: unlimited
   SessionType: Race
DriverInfo:
 DriverCarIdx: 3
 DriverCarRedLine: 7900.000
 DriverCarFuelMaxLtr: 120.000
 Drivers:
 - CarIdx: 0
   UserName: Pace Car
   CarScreenName: Safety Car
   CarIsPaceCar: 1
   IsSpectator: 0
 - CarIdx: 1
   UserName: Alex Fast
   CarScreenName: Porsche 911 GT3 R (992)
   CarIsPaceCar: 0
   IsSpectator: 0
 - CarIdx: 3
   UserName: Sam Driver
   CarScreenName: BMW M4 GT3
   CarIsPaceCar: 0
   IsSpectator: 0
 - CarIdx: 5
   UserName: Robin Close
   CarScreenName: Ferrari 296 GT3
   CarIsPaceCar: 0
   IsSpectator: 0
 - CarIdx: 9
   UserName: Watcher
   CarScreenName: BMW M4 GT3
   CarIsPaceCar: 0
   IsSpectator: 1
...
"""
VARS = [("Speed", 4, 1, 50.0), ("Throttle", 4, 1, 0.85), ("Brake", 4, 1, 0.0), ("SteeringWheelAngle", 4, 1, -0.5),
        ("SteeringWheelAngleMax", 4, 1, 4.0), ("Gear", 2, 1, 4), ("RPM", 4, 1, 6800.0), ("LapDistPct", 4, 1, 0.4321),
        ("LapCompleted", 2, 1, 3), ("LapCurrentLapTime", 4, 1, 61.5), ("LapLastLapTime", 4, 1, 138.25),
        ("OnPitRoad", 1, 1, False), ("PlayerTrackSurface", 2, 1, 3), ("FuelLevel", 4, 1, 54.5), ("PlayerCarPosition", 2, 1, 2),
        ("PlayerCarIdx", 2, 1, 3), ("SessionNum", 2, 1, 1), ("SessionState", 2, 1, 4), ("SessionFlags", 3, 1, 0x4 | 0x20),
        ("SessionTimeRemain", 5, 1, 1800.0), ("WaterTemp", 4, 1, 91.0), ("OilTemp", 4, 1, 104.0),
        ("CarIdxPosition", 2, 64, None), ("CarIdxF2Time", 4, 64, None), ("Unrelated", 4, 1, 1.0)]
fmt = {1: "?", 2: "i", 3: "I", 4: "f", 5: "d"}; size = {1: 1, 2: 4, 3: 4, 4: 4, 5: 8}
pos = [0] * 64; pos[1], pos[3], pos[5] = 1, 2, 3
f2 = [0.0] * 64; f2[1], f2[3], f2[5] = 0.0, 1.85, 2.6
def build(values_override={}, flags=None, newest=1):
    vh_off, n = 112, len(VARS)
    off, layout = 0, []
    for name, t, cnt, _ in VARS:
        layout.append((name, t, cnt, off)); off += size[t] * cnt
    buf_len = off; yaml = YAML.encode("latin-1")
    yaml_off = vh_off + n * 144; bufs_off = yaml_off + len(yaml) + 64
    mem = bytearray(bufs_off + 3 * buf_len)
    ticks = [100, 300, 200]                       # buffer 1 is the newest
    if newest != 1: ticks = [300, 100, 200]
    struct.pack_into("<10i", mem, 0, 2, 1, 60, 7, len(yaml), yaml_off, n, vh_off, 3, buf_len)
    for k in range(3): struct.pack_into("<4i", mem, 48 + 16 * k, ticks[k], bufs_off + k * buf_len, 0, 0)
    for i, (name, t, cnt, o) in enumerate(layout):
        struct.pack_into("<3i?3x32s", mem, vh_off + i * 144, t, o, cnt, False, name.encode())
    mem[yaml_off:yaml_off + len(yaml)] = yaml
    for k in range(3):
        base = bufs_off + k * buf_len
        for (name, t, cnt, o), (_, _, _, v) in zip(layout, VARS):
            v = values_override.get(name, v)
            if name == "SessionFlags" and flags is not None: v = flags
            if name == "Speed" and k != (1 if newest == 1 else 0): v = 1.0      # stale buffers carry junk speed
            if name == "CarIdxPosition": struct.pack_into("<64i", mem, base + o, *pos)
            elif name == "CarIdxF2Time": struct.pack_into("<64f", mem, base + o, *f2)
            else: struct.pack_into("<" + fmt[t], mem, base + o, v)
    return bytes(mem)
r = sc.IRacingReader()
r.m = sc._RawBlock(build())
f = r.read()
show = {k: getattr(f, k) for k in ("game", "track", "car", "laps_done", "pct", "speed", "throttle", "steer", "gear", "rpm", "cur_time",
                                    "last_time", "in_pit", "off_track", "fuel", "fuel_cap", "track_len", "max_rpm", "session",
                                    "position", "cars", "race_laps", "time_left", "flag", "gap_ahead", "gap_behind", "water_temp")}
check(f.track == "Circuit de Spa-Francorchamps" and f.car == "BMW M4 GT3" and f.track_len == 6930, "track, car, length from the YAML")
check(abs(f.speed - 180.0) < 0.01 and abs(f.steer - 0.125) < 1e-6 and f.max_rpm == 7900, "speed in km/h, steering, redline")
check(f.session == "race" and f.race_laps == 12 and f.cars == 3 and f.position == 2 and f.laps_done == 3,
      "race session, laps, field without pace car/spectator")
check(abs(f.gap_ahead - 1.85) < 1e-5 and abs(f.gap_behind - 0.75) < 1e-5 and f.car_ahead["name"] == "Alex Fast", "gaps and rivals")
check(f.flag == "blue" and f.time_left is None and f.fuel == 54.5 and f.fuel_cap == 120, "flag, fuel")
r.m = sc._RawBlock(build(flags=0x4000))
check(r.read().flag == "fcy", "caution -> full course yellow")
r.m = sc._RawBlock(build(newest=0))
check(round(r.read().speed, 1) == 180.0, "newest buffer picked")
r2 = sc.IRacingReader()
r2.m = sc._RawBlock(build(values_override={"SessionNum": 0}))
fp = r2.read()
check(fp.session == "practice" and fp.race_laps == 0 and round(fp.time_left) == 1800, "practice session")
r3 = sc.IRacingReader()
r3.m = sc._RawBlock(build(values_override={"PlayerTrackSurface": 0}))
check(r3.read().off_track is True, "off track")
cfg, voice, coach = headless_coach(sc)
for i in range(120):
    fr = r.read()
    coach.update(fr, i / 60)
    coach.crew.update(fr, i / 60)
check(coach.key == ("iRacing", "Circuit de Spa-Francorchamps", "BMW M4 GT3"), "frames accepted by the coach")
done()

"""The driver's data survives problems: an unreadable config.json, session history or reference is set aside
(kept as .corrupt-<time>) instead of being overwritten; saves are atomic and survive another thread changing a
setting mid-save; keys are encrypted on Windows only (passed through elsewhere); goals follow their corners when
the corners are re-mapped; the F1 reader waits for a session packet, reads max RPM and wheel speeds."""
import glob
import json
import os
import struct
import threading

from _common import check, done, load, headless_coach

sc = load()
real = sc                                                   # load_config and the real save_config (load() stubs it)
real.save_config = sc.real_save_config

# --- config.json ---------------------------------------------------------------------------------------------
os.makedirs(real.APP_DIR, exist_ok=True)
with open(real.CONFIG_PATH, "w", encoding="utf-8") as fh:
    fh.write('{"driver_name": "Sam", "openai_api_key": "sk-')        # torn by a power cut
cfg = real.load_config()
kept = glob.glob(real.CONFIG_PATH + ".corrupt-*")
check(cfg["driver_name"] == real.DEFAULT_CONFIG["driver_name"] and len(kept) == 1, "torn config.json is set aside")
check(open(kept[0], encoding="utf-8").read().startswith('{"driver_name": "Sam"'), "what it held is kept")
check(not os.path.exists(real.CONFIG_PATH), "and the defaults start from a clean slate")

cfg["driver_name"] = "Sam"
cfg["openai_api_key"] = "sk-test"
sc.real_save_config(cfg)
saved = json.load(open(real.CONFIG_PATH, encoding="utf-8"))
check(saved["driver_name"] == "Sam" and saved["openai_api_key"] == "sk-test", "saved (no encryption off Windows)")
check(not glob.glob(real.CONFIG_PATH + ".*.tmp"), "no temp files left behind")
check(real.load_config()["openai_api_key"] == "sk-test", "and read back")
check(real.seal_secret("") == "" and real.open_secret("plain") == "plain", "plain keys from older versions still work")
check(real.open_secret("dpapi:not-base64!") == "", "a key that can't be decrypted comes back empty")

# another thread adding settings while saving: no "dictionary changed size during iteration"
errors, stop = [], threading.Event()


def churn():
    i = 0
    while not stop.is_set():
        cfg["briefed"] = {f"k{j}": "x" for j in range(i % 50)}
        cfg[f"x{i % 200}"] = i
        i += 1


t = threading.Thread(target=churn)
t.start()
try:
    for _ in range(200):
        sc.real_save_config(cfg)
except Exception as e:
    errors.append(e)
stop.set()
t.join()
check(not errors, f"saving while another thread changes settings {errors[:1]}")
check(isinstance(json.load(open(real.CONFIG_PATH, encoding="utf-8")), dict), "config.json still whole")

# --- session history and reference laps --------------------------------------------------------------------
_cfg, _voice, coach = headless_coach(sc)
coach.key = ("ACC", "spa", "porsche_992_gt3_r")
os.makedirs(coach.store_dir, exist_ok=True)
sp = coach._sessions_path()
with open(sp, "w", encoding="utf-8") as fh:
    fh.write('[{"date": "2026-11-01", "best": 138.2}, {"date": "2026-11-0')
check(coach.past_sessions() == [] and glob.glob(sp + ".corrupt-*") and not os.path.exists(sp),
      "torn session history is set aside, not overwritten")
with open(coach._path(), "w", encoding="utf-8") as fh:
    fh.write('{"key": ["ACC", "spa", "porsche_992_gt3_r"], "ref": {"speed": [1, 2')
check(coach.load() is False and glob.glob(coach._path() + ".corrupt-*"), "torn reference lap is set aside")

# --- goals follow their corners ------------------------------------------------------------------------------
T = sc.GOAL_APEX_TOL
goals = [{"ci": 2, "apex": 3000, "avg": 5.0, "loss": 0.3}, {"ci": 4, "apex": 6000, "avg": 4.0, "loss": 0.2}]
corners = [(100, 400, 600), (2700, 3000 + T // 2, 3300), (5000, 5200, 5400)]   # re-mapped: fewer corners
moved = sc.remap_goals(goals, corners)
check([g["ci"] for g in moved] == [1], f"goal moved to its corner's new number, a vanished corner dropped {moved}")

# --- F1: session first, max RPM, wheel speeds -----------------------------------------------------------------
r = sc.F1Reader(port=47779)


def hdr(pid, size):
    b = bytearray(size)
    struct.pack_into("<HBBBBB", b, 0, 2025, 25, 1, 0, 1, pid)
    b[27] = 0                                                   # player car index
    return b


def lap_pkt():
    per = 57
    b = hdr(2, 29 + 22 * per + 2)
    struct.pack_into("<II", b, 29, 90000, 30000)
    struct.pack_into("<f", b, 29 + 20, 1200.0)
    b[29 + 32], b[29 + 33] = 1, 2                               # position, lap number
    return bytes(b)


def tel_pkt():
    b = hdr(6, 29 + 22 * 60 + 3)
    struct.pack_into("<Hfff", b, 29, 250, 1.0, 0.0, 0.0)
    struct.pack_into("<H", b, 29 + 16, 11000)
    return bytes(b)


def sess_pkt():
    b = hdr(1, 700)
    struct.pack_into("<H", b, 33, 7004)
    b[35], b[36] = 1, 10                                        # practice, Spa
    return bytes(b)


def status_pkt():
    per = 55
    b = hdr(7, 29 + 22 * per)
    struct.pack_into("<ff", b, 29 + 5, 50.0, 110.0)
    struct.pack_into("<H", b, 29 + 17, 13000)
    return bytes(b)


def motion_ex_pkt():
    b = hdr(13, 29 + 237)
    struct.pack_into("<4f", b, 29 + 48, 60.0, 61.0, 20.0, 21.0)  # RL, RR, FL, FR in m/s (fronts locking)
    return bytes(b)


r.parse(lap_pkt())
check(r.parse(tel_pkt()) is None, "no frames before the session packet (no made-up 'F1 circuit' session)")
r.parse(sess_pkt())
r.parse(lap_pkt())
r.parse(status_pkt())
r.parse(motion_ex_pkt())
f = r.parse(tel_pkt())
check(f is not None and f.track == "Spa" and f.max_rpm == 13000.0, f"max RPM read from car status ({f and f.max_rpm})")
check(f is not None and f.wheel_kmh is not None and round(f.wheel_kmh[0]) == 72 and round(f.wheel_kmh[2]) == 216,
      f"wheel speeds from Motion Ex, fronts first ({f and f.wheel_kmh})")
r.close()
done()
